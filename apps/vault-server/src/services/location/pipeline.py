"""One tracker event, handled end to end (trips spec §5, §6).

The worker thread calls `handle_event` for each event, in order:
- **LEFT**: an ongoing "Trip" block appears in /day.
- **STOPPED**: a place you named names the stop silently; any other stop is
  asked about once, with the model's guesses about the place as buttons and
  "Later" to answer at home. A pause spot is skipped with no model call. The
  trip's own activity never names a stop (2026-11-14).
- **LEFT_STOP**: an unsent question is withdrawn. A stop you left unanswered
  stays unnamed, with no block of its own.
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
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from opentelemetry.trace import Status, StatusCode

from src.services.fast_lane.places import PAUSE_KIND, add_pause_spot, learn_place, load_places, nearest
from src.services.location.context import gather_context
from src.services.location.decide import Decision, Option, decide
from src.services.location.edits import trip_of
from src.services.location.guess import Guess, describe_trip, guess
from src.services.location.history import load_confirmed, score_history
from src.services.location.map_lookup import map_area, map_near
from src.services.location.messages import arrival_receipt, question_receipt
from src.services.location.model import TrackerEvent, Trip, safe_error
from src.services.location.names import canonical, known_names, name_key, title_for
from src.services.location.records import new_record
from src.services.location.visits import earlier_visits
from src.services.location.writer import apply_blocks, plan_blocks
from src.tracing_setup import get_tracer

logger = logging.getLogger(__name__)

STALE_QUESTION = dt.timedelta(minutes=10)
MAP_CLOSE_M = 15.0                     # a map place this close is "what is here" (map spec §5.2, §5.4)


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
    derived_dir: Path | None = None
    map_index: Path | None = None      # the local map copy (map spec); None: no map, stops asked as before
    raw_dir: Path | None = None        # data/locations/raw: the points an edit's stop centre comes from


def _places(deps: TripDeps):
    return load_places(deps.places_path)


def _known(deps: TripDeps, confirmed) -> dict:
    """The names you already use: your confirmed purposes, then your habits and their aliases."""
    try:
        habits = deps.vault.list_active_habits() if deps.vault is not None else []
    except Exception:
        logger.warning("location names: habits unavailable")
        habits = []
    return known_names([c.purpose for c in sorted(confirmed, key=lambda c: c.start, reverse=True)], habits)


def _guess(subject: str, trip: Trip, stop, deps: TripDeps, places, *, trip_purpose: str | None = None,
           visits: int = 0, map_places=None) -> tuple[list[Guess], list[dict], list]:
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
    kept, dropped = guess(subject, describe_trip(trip, stop, places, now, deps.tz, visits=visits), history, lines,
                          deps.claude, model=deps.model, timeout_s=deps.timeout_s, map_places=map_places)
    known = _known(deps, confirmed)
    kept = [replace(g, purpose=canonical(g.purpose, known)) for g in kept]
    if subject == "stop":
        # In code, not only in the prompt: on 14 Nov the model named both stops
        # of a dog walk "Dog walking", from the message saying so.
        trip_key = name_key(trip_purpose) if trip_purpose else None
        about_place = []
        for g in kept:
            if not g.destination:
                dropped.append({"purpose": g.purpose, "reason": "about the trip, not the place"})
            elif trip_key is not None and name_key(g.purpose) == trip_key:
                dropped.append({"purpose": g.purpose, "reason": "the trip's own purpose"})
            else:
                about_place.append(g)
        kept = about_place
    return kept, dropped, history


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
    # The place id is written on the tracker's own trip, never on the overlay:
    # writing trip_of's result back would apply every edit twice.
    base = Trip.from_dict(rec["trip"])
    base_stop = base.stop(sid)
    info = _stop_info(rec, sid)
    # From places.json as it is now, not the tracker's start-up copy: a pause
    # spot or a place learned an hour ago counts at once.
    known = nearest(base_stop.lat, base_stop.lng, [p for p in places if p.id != "home"]) if base_stop else None
    if known is not None and base_stop.place_id != known.id:
        base_stop.place_id = known.id
        rec["trip"] = base.to_dict()
    trip = trip_of(rec)
    stop = trip.stop(sid)
    if known is not None and known.kind == PAUSE_KIND:
        _log(deps, ev.kind, rec, sid, decision=Decision("quiet", reason="pause spot"))
        return
    visits = earlier_visits(stop, rec["id"], trip.left_at, deps.records, deps.derived_dir, deps.now())
    info["visits"] = visits
    mapped, area = [], None
    if known is not None:
        # Your place names it (decide below): nothing to look up or guess.
        guesses, dropped, history = [], [], []
    else:
        mapped, area = _map(stop, deps)
        info["map"] = [m.to_dict() for m in mapped]
        info["area"] = area
        guesses, dropped, history = _guess("stop", trip, stop, deps, places,
                                           trip_purpose=(rec.get("purpose") or {}).get("name"), visits=visits,
                                           map_places=mapped if deps.map_index is not None else None)
    # A street is context for the model, never a button: "what's this?" [Yesod HaMa'ala] answers nothing.
    places_only = [m for m in mapped if m.group == "place"]
    close = [m for m in places_only if m.distance_m <= MAP_CLOSE_M][:3] or places_only[:1]
    map_options = [Option(m.label, m.label, m.osm) for m in close]
    # A STOPPED handled long after it happened (the server was down, or the
    # inbox is replaying) is about a stop you have likely left: never ask then.
    fresh = (deps.now() - ev.ts) <= STALE_QUESTION
    d = decide(guesses, history, known_place=known, may_ask=fresh,
               at_stop=True, map_options=map_options)
    if d.action == "name":
        info.update(status="named", name=d.name, place=d.destination or (known.name if known else None))
    elif d.action == "ask":
        info.update(status="asked", options=[o.to_dict() for o in d.options], asked_at=deps.now().isoformat())
        receipt = question_receipt(rec, sid, list(d.options), deps.now(), deps.tz,
                                   place_name=known.name if known else None, visits=visits,
                                   map_label=mapped[0].label if mapped and mapped[0].distance_m <= MAP_CLOSE_M
                                   else None, area=area)
        # Saved before queueing, and queued by key: a crash in between can
        # replay this event, but never send the question twice.
        deps.records.save(rec)
        deps.outbox.add("question", receipt, rec["id"], key=question_key(rec["id"], sid))
    _log(deps, ev.kind, rec, sid, history, guesses, dropped, d, extra={"map": info.get("map") or []})


def _map(stop, deps: TripDeps):
    """The map places at this stop and its area name: a local file read, never a network call."""
    if deps.map_index is None or stop is None:
        return [], None
    with get_tracer().start_as_current_span("location.map.lookup", record_exception=False,
                                            set_status_on_exception=False) as span:
        mapped = map_near(deps.map_index, stop.lat, stop.lng, stop.spread_m)
        area = map_area(deps.map_index, stop.lat, stop.lng)
        span.set_attribute("count", len(mapped))
        if mapped:
            span.set_attribute("top_distance_m", mapped[0].distance_m)
    return mapped, area


def question_key(trip_id: str, stop_id: str) -> str:
    return f"q:{trip_id}:{stop_id}"


def _on_left_stop(rec: dict, ev: TrackerEvent, deps: TripDeps, places) -> None:
    sid = ev.stop_id
    # A question no point carried to you before you left is not asked any more.
    # Unanswered, it stays unnamed and gets no block (the user's rule): no
    # second guess once you have left.
    deps.outbox.withdraw(question_key(rec["id"], sid))
    _later_if_asked(rec, sid)
    _log(deps, ev.kind, rec, sid)


def _later_if_asked(rec: dict, sid: str) -> None:
    """An asked stop nobody answered waits for the arrival message as a ? line."""
    info = (rec.get("stops") or {}).get(sid)
    if info and info.get("status") == "asked" and not info.get("answered"):
        info["status"] = "later"


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
    for sid in rec.get("stops") or {}:
        deps.outbox.withdraw(question_key(rec["id"], sid))
        _later_if_asked(rec, sid)
    _apply(rec, deps, places)
    _name_from_your_block(rec, deps)
    if (rec.get("purpose") or {}).get("name") or rec.get("trip_question"):
        _log(deps, ev.kind, rec, decision=Decision("name", (rec.get("purpose") or {}).get("name"),
                                                   reason="already named"))
        return
    trip = trip_of(rec)
    guesses, dropped, history = _guess("trip", trip, None, deps, places)
    d = decide(guesses, history, known_place=None, may_ask=True)
    if d.action == "ask":
        rec["trip_question"] = {"options": [o.to_dict() for o in d.options], "asked_at": deps.now().isoformat()}
    _log(deps, ev.kind, rec, None, history, guesses, dropped, d)


def _apply(rec: dict, deps: TripDeps, places) -> None:
    apply_blocks(rec, plan_blocks(rec, places), run_tool=deps.run_tool, events=deps.events, tz=deps.tz,
                 vault=deps.vault)


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
    # Not recorded by OTel itself: its exception event carries the message,
    # and a message could quote a coordinate.
    with get_tracer().start_as_current_span("location.trip.decide", record_exception=False,
                                            set_status_on_exception=False) as span:
        span.set_attribute("location.event", ev.kind)
        try:
            with deps.records.lock_for(ev.trip.id):
                _handle(ev, deps)
        except Exception as exc:
            # The type and where, never the message: it could quote a coordinate.
            span.set_status(Status(StatusCode.ERROR, safe_error(exc)))
            raise


def _handle(ev: TrackerEvent, deps: TripDeps) -> None:
    places = _places(deps)
    rec = deps.records.get(ev.trip.id)
    if rec is not None and rec.get("last_event_ts") and ev.ts < dt.datetime.fromisoformat(rec["last_event_ts"]):
        # An older event replayed after newer ones (a failed one, from the
        # inbox) would rewind the trip: reopen stops, drop later parts.
        _log(deps, ev.kind, rec, ev.stop_id, extra={"skipped": "older than the record"})
        return
    rec = rec or new_record(ev.trip)
    rec["trip"] = ev.trip.to_dict()
    rec["last_event_ts"] = ev.ts.isoformat()
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


def defer_stop(trip_id: str, stop_id: str, deps: TripDeps) -> dict[str, Any]:
    """"Later": the stop's question waits for the arrival message. Raises KeyError for an unknown trip or stop."""
    with deps.records.lock_for(trip_id):
        rec = deps.records.get(trip_id)
        if rec is None or trip_of(rec).stop(stop_id) is None:
            raise KeyError(stop_id if rec else trip_id)
        info = _stop_info(rec, stop_id)
        if info["status"] in ("asked", "unnamed") and not info.get("answered"):
            info["status"] = "later"
        _refresh_arrival(rec, deps)
        deps.records.save(rec)
        _log(deps, "LATER", rec, stop_id)
        return rec


def apply_answer(trip_id: str, stop_id: str | None, purpose: str | None, place: str | None, deps: TripDeps,
                 *, pause: bool = False, osm: str | None = None) -> dict[str, Any]:
    """Your answer to a question about a stop or the whole trip. Raises KeyError for an unknown trip or stop."""
    with deps.records.lock_for(trip_id):
        return _answer(trip_id, stop_id, purpose, place, deps, pause, osm)


def _map_osm(info: dict, *names: str | None) -> str | None:
    """The map place an answer names, by the same words, among those seen at the stop."""
    keys = {name_key(n) for n in names if n}
    return next((m.get("osm") for m in info.get("map") or [] if name_key(m.get("label") or "") in keys), None)


def _answer(trip_id: str, stop_id: str | None, purpose: str | None, place: str | None, deps: TripDeps,
            pause: bool, osm: str | None = None) -> dict[str, Any]:
    rec = deps.records.get(trip_id)
    if rec is None:
        raise KeyError(trip_id)
    trip = trip_of(rec)
    conflict = None
    if purpose:
        # Your words, unless they are a name you already use spelled another way.
        confirmed = load_confirmed(deps.labels_dir, deps.records, deps.events, deps.tz, deps.now())
        purpose = canonical(title_for(purpose.strip(), place), _known(deps, confirmed))
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
                _, clash = learn_place(deps.places_path, place, stop.lat, stop.lng, stop.spread_m,
                                       osm=osm or _map_osm(info, place, purpose))
                conflict = place if clash else None
    else:
        rec["purpose"] = {"name": purpose, "destination": place, "source": "answer"}
        # Only a trip-level answer confirms why the trip happened (spec §5.2);
        # naming a stop, or calling it a pause, does not.
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
