"""One tracker event, handled end to end (trips spec §5, §6).

The worker thread calls `handle_event` for each event, in order:
- **LEFT**: an ongoing "Trip" block appears in /day.
- **STOPPED**: name the stop silently, or ask once. A pause spot is skipped
  with no model call.
- **LEFT_STOP**: a stop never named gets one more guess, now that its length
  is known. It is never asked about: you have already left.
- **BACK_HOME**: the trip gets a purpose (or one question), its blocks are
  finalised, and the arrival message is queued.

`apply_answer` takes your answer, from a button or from the agent's
`set_trip_purpose`, and re-plans the blocks.

Every decision writes one line to the decision log. It holds names,
distances and ids only, never coordinates.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.services.fast_lane.places import PAUSE_KIND, add_pause_spot, learn_place, load_places
from src.services.location.context import gather_context
from src.services.location.decide import Decision, Option, decide
from src.services.location.guess import Guess, describe_trip, guess
from src.services.location.history import load_confirmed, score_history
from src.services.location.messages import arrival_receipt, question_receipt
from src.services.location.model import TrackerEvent, Trip
from src.services.location.records import new_record
from src.services.location.writer import apply_blocks, plan_blocks
from src.services.tracing_helpers import with_span_status
from src.tracing_setup import get_tracer

logger = logging.getLogger(__name__)


@dataclass
class TripDeps:
    records: Any
    outbox: Any
    places_path: Path
    labels_dir: Path
    run_tool: Callable[[str, dict], dict]
    events: Any
    vault: Any
    claude: Any
    conversations_dir: Path
    tz: str
    model: str
    timeout_s: float
    boundary_hour: int
    chat_id: Callable[[], int | None]
    now: Callable[[], dt.datetime]
    log: Callable[[dict], None]


def _places(deps: TripDeps):
    return load_places(deps.places_path)


def _guess(subject: str, trip: Trip, stop, deps: TripDeps, places) -> tuple[list[Guess], list[dict], list]:
    now = deps.now()
    confirmed = load_confirmed(deps.labels_dir, deps.records, deps.events, deps.tz, now)
    history = score_history(trip, confirmed, now, deps.tz, stop=stop)
    if subject == "stop":
        # What a stop is, is a place you went to. A purpose that is the moving
        # itself (a walk) is the trip's, and would name the stop after the trip.
        history = [h for h in history if h.destination]
    if deps.claude is None:
        return [], [{"purpose": None, "reason": "no model configured"}], history
    lines = gather_context(now, vault=deps.vault, events=deps.events, conversations_dir=deps.conversations_dir,
                           chat_id=deps.chat_id(), tz=deps.tz)
    kept, dropped = guess(subject, describe_trip(trip, stop, places, now, deps.tz), history, lines, deps.claude,
                          model=deps.model, timeout_s=deps.timeout_s)
    return kept, dropped, history


def _questions_today(deps: TripDeps) -> int:
    now = deps.now()
    day = (now - dt.timedelta(hours=deps.boundary_hour)).date()
    return deps.records.questions_on(day, deps.tz, deps.boundary_hour)


def _log(deps: TripDeps, event: str, rec: dict, stop_id: str | None = None, history=(), guesses=(),
         dropped=(), decision: Decision | None = None, extra: dict | None = None) -> None:
    line = {
        "event": event, "trip_id": rec["id"], "stop_id": stop_id,
        "history": [{"id": h.id, "purpose": h.purpose, "score": h.score} for h in history],
        "guesses": [{"purpose": g.purpose, "likelihood": g.likelihood, "history_id": g.history_id,
                     "cites": list(g.cites), "destination": g.destination} for g in guesses],
        "dropped": list(dropped),
        "decision": ({"action": decision.action, "name": decision.name, "destination": decision.destination,
                      "options": [o.name for o in decision.options], "reason": decision.reason}
                     if decision else None),
        "blocks": {part: ref.get("event_id") for part, ref in (rec.get("blocks") or {}).items()},
        "merged": {part: m.get("event_id") for part, m in (rec.get("merged") or {}).items()},
        **(extra or {}),
    }
    try:
        deps.log(line)
    except Exception:
        logger.exception("location decision log failed")


def _stop_info(rec: dict, stop_id: str) -> dict:
    return rec["stops"].setdefault(stop_id, {"status": "unnamed", "name": None, "place": None,
                                             "options": [], "asked_at": None})


def _on_stopped(rec: dict, ev: TrackerEvent, deps: TripDeps, places) -> None:
    sid = ev.stop_id
    if sid in rec["stops"]:
        return                                     # handled already: never ask twice
    trip = Trip.from_dict(rec["trip"])
    stop = trip.stop(sid)
    info = _stop_info(rec, sid)
    known = next((p for p in places if stop is not None and p.id == stop.place_id), None)
    if known is not None and known.kind == PAUSE_KIND:
        _log(deps, ev.kind, rec, sid, decision=Decision("quiet", reason="pause spot"))
        return
    guesses, dropped, history = _guess("stop", trip, stop, deps, places)
    d = decide(guesses, history, known_place=known, may_ask=True, questions_today=_questions_today(deps))
    if d.action == "name":
        info.update(status="named", name=d.name, place=d.destination or (known.name if known else None))
    elif d.action == "ask":
        info.update(status="asked", options=[o.to_dict() for o in d.options], asked_at=deps.now().isoformat())
        receipt = question_receipt(rec, sid, list(d.options), deps.now(), deps.tz,
                                   place_name=known.name if known else None)
        deps.outbox.add("question", receipt, rec["id"])
    _log(deps, ev.kind, rec, sid, history, guesses, dropped, d)


def _on_left_stop(rec: dict, ev: TrackerEvent, deps: TripDeps, places) -> None:
    sid = ev.stop_id
    info = _stop_info(rec, sid)
    if info["status"] in ("named", "pause") or info.get("answered") or info.get("reguessed"):
        return
    info["reguessed"] = True
    trip = Trip.from_dict(rec["trip"])
    guesses, dropped, history = _guess("stop", trip, trip.stop(sid), deps, places)
    d = decide(guesses, history, known_place=None, may_ask=False, questions_today=0)
    if d.action == "name":
        info.update(status="named", name=d.name, place=d.destination)
    _log(deps, ev.kind, rec, sid, history, guesses, dropped, d)


def _name_from_your_block(rec: dict, deps: TripDeps) -> None:
    """A block of yours that the trip merged with names the trip: your words win."""
    merged = (rec.get("merged") or {}).get("trip")
    if not merged or (rec.get("purpose") or {}).get("source") == "answer":
        return
    e = next((x for x in deps.events.get_events(merged["date"]) if x.get("id") == merged["event_id"]), None)
    if e and e.get("name"):
        rec["purpose"] = {"name": e["name"], "destination": None, "source": "user_block"}
        rec["confirmed"] = True


def _on_back_home(rec: dict, ev: TrackerEvent, deps: TripDeps, places) -> None:
    rec["closed"] = True
    _apply(rec, deps, places)
    _name_from_your_block(rec, deps)
    if (rec.get("purpose") or {}).get("name") or rec.get("trip_question"):
        _log(deps, ev.kind, rec, decision=Decision("name", (rec.get("purpose") or {}).get("name"),
                                                   reason="already named"))
        return
    trip = Trip.from_dict(rec["trip"])
    guesses, dropped, history = _guess("trip", trip, None, deps, places)
    d = decide(guesses, history, known_place=None, may_ask=True, questions_today=_questions_today(deps))
    if d.action == "name":
        rec["purpose"] = {"name": d.name, "destination": d.destination, "source": "guess"}
    elif d.action == "ask":
        rec["trip_question"] = {"options": [o.to_dict() for o in d.options], "asked_at": deps.now().isoformat()}
    _log(deps, ev.kind, rec, None, history, guesses, dropped, d)


def _apply(rec: dict, deps: TripDeps, places) -> None:
    apply_blocks(rec, plan_blocks(rec, places), run_tool=deps.run_tool, events=deps.events, tz=deps.tz)


def _refresh_arrival(rec: dict, deps: TripDeps) -> None:
    """Queue the arrival message once; while unsent, keep it up to date."""
    if not rec.get("closed"):
        return
    receipt = arrival_receipt(rec, deps.events, deps.tz)
    item = rec.get("arrival_item")
    if item is None:
        rec["arrival_item"] = deps.outbox.add("arrival", receipt, rec["id"])
    else:
        deps.outbox.update(item, receipt)


def handle_event(ev: TrackerEvent, deps: TripDeps) -> None:
    if ev.trip is None:
        return
    with get_tracer().start_as_current_span("location.trip.decide") as span:
        with with_span_status(span):
            span.set_attribute("location.event", ev.kind)
            places = _places(deps)
            rec = deps.records.get(ev.trip.id) or new_record(ev.trip)
            rec["trip"] = ev.trip.to_dict()
            if ev.kind == "STOPPED":
                _on_stopped(rec, ev, deps, places)
            elif ev.kind == "LEFT_STOP":
                _on_left_stop(rec, ev, deps, places)
            elif ev.kind == "BACK_HOME":
                _on_back_home(rec, ev, deps, places)
            elif ev.kind == "LEFT":
                _log(deps, ev.kind, rec)
            _apply(rec, deps, places)
            if ev.kind != "BACK_HOME":
                _name_from_your_block(rec, deps)
            _refresh_arrival(rec, deps)
            deps.records.save(rec)


def apply_answer(trip_id: str, stop_id: str | None, purpose: str | None, place: str | None, deps: TripDeps,
                 *, pause: bool = False) -> dict[str, Any]:
    """Your answer to a question about a stop or the whole trip. Raises KeyError for an unknown trip or stop."""
    rec = deps.records.get(trip_id)
    if rec is None:
        raise KeyError(trip_id)
    trip = Trip.from_dict(rec["trip"])
    conflict = None
    if stop_id is not None:
        stop = trip.stop(stop_id)
        if stop is None:
            raise KeyError(stop_id)
        info = _stop_info(rec, stop_id)
        info["answered"] = True
        if pause:
            add_pause_spot(deps.places_path, stop.lat, stop.lng, stop.spread_m)
            info.update(status="unnamed", name=None, place=None)
        else:
            info.update(status="named", name=purpose, place=place)
            if place:
                _, clash = learn_place(deps.places_path, place, stop.lat, stop.lng, stop.spread_m)
                conflict = place if clash else None
    else:
        rec["purpose"] = {"name": purpose, "destination": place, "source": "answer"}
    rec["confirmed"] = True
    places = _places(deps)
    _apply(rec, deps, places)
    _refresh_arrival(rec, deps)
    deps.records.save(rec)
    _log(deps, "ANSWER", rec, stop_id, extra={"answer": purpose, "pause": pause, "place": place})
    return {"record": rec, "conflict": conflict}


def options_for(rec: dict, line: str) -> list[Option]:
    if line == "trip":
        return [Option.from_dict(o) for o in (rec.get("trip_question") or {}).get("options") or []]
    return [Option.from_dict(o) for o in ((rec.get("stops") or {}).get(line) or {}).get("options") or []]
