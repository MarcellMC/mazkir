"""Location awareness at run time: the tracker, its state, the worker and the clock (trips spec §3).

- `feed(point)` runs inside `POST /locations/points`. It advances the tracker
  (a few milliseconds of pure code), persists `state.json`, queues any events
  for the worker, and returns what the outbox holds for the bot to send.
- One worker thread handles the events in order (`pipeline.handle_event`).
  An event is written to `inbox.json` before it is queued and removed only
  once handled, so a restart in between loses nothing.
- `tick(now)`, every 60 s from the lifespan loop, notices a share that
  stopped (no point will carry that message) and learns home.

`inbox.json` is a file of its own rather than a key in each trip record: the
worker holds a record for the seconds a model call takes, and an event queued
meanwhile would otherwise be lost when the worker saved the record.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import queue
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from src.services.fast_lane import places as places_mod
from src.services.location.home import find_home
from src.services.location.messages import arrival_receipt, notice_receipt, question_receipt
from src.services.location.model import TrackerEvent, Trip, safe_error
from src.services.location.pipeline import TripDeps, apply_answer, defer_stop, handle_event, options_for
from src.services.location.raw import load_fixes, point_to_fix
from src.services.location.writer import fragments
from src.services.location.tracker import Params, Tracker

logger = logging.getLogger(__name__)

SHARE_STOPPED = "Location sharing stopped — share again to keep your day filling in"
HOME_FOUND = "I found home — trips from here will fill your day."
HOME_DAYS = 14

_runtime: "LocationRuntime | None" = None


def get_runtime() -> "LocationRuntime | None":
    return _runtime


def set_runtime(rt: "LocationRuntime | None") -> None:
    global _runtime
    _runtime = rt


def _atomic_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(path)


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except (OSError, ValueError):
        logger.exception("location runtime: %s unreadable", path.name)
        return default


class LocationRuntime:
    def __init__(self, root: Path, deps: TripDeps, *, synchronous: bool = False, params: Params = Params()):
        self.root = Path(root)
        self.deps = deps
        self.synchronous = synchronous
        self._lock = threading.RLock()
        self._state_path = self.root / "state.json"
        self._inbox_path = self.root / "inbox.json"
        state = _read(self._state_path, {})
        self.chat_id: int | None = state.get("chat_id")
        deps.chat_id = lambda: self.chat_id
        home, others = self._places()
        self.tracker = (Tracker.from_dict(state["tracker"], home, others, params) if state.get("tracker")
                        else Tracker(home, others, params))
        self._home_checked: dt.date | None = None
        self._queue: "queue.Queue[tuple[str, TrackerEvent] | None]" = queue.Queue()
        self._thread: threading.Thread | None = None
        if not synchronous:
            self._thread = threading.Thread(target=self._work, name="location-trips", daemon=True)
            self._thread.start()
        for item in _read(self._inbox_path, {"events": []}).get("events", []):
            self._dispatch(item["seq"], TrackerEvent.from_dict(item["event"]))

    # --- places --------------------------------------------------------------

    def _places(self):
        places = places_mod.load_places(self.deps.places_path)
        home = next(((p.lat, p.lng) for p in places if p.id == "home" and p.lat is not None), None)
        return home, [p for p in places if p.id != "home"]

    # --- the inbox and the worker -------------------------------------------

    def _inbox_add(self, ev: TrackerEvent) -> str:
        seq = uuid4().hex[:12]
        with self._lock:
            inbox = _read(self._inbox_path, {"events": []})
            inbox["events"].append({"seq": seq, "event": ev.to_dict()})
            _atomic_write(self._inbox_path, inbox)
        return seq

    def _inbox_done(self, seq: str) -> None:
        with self._lock:
            inbox = _read(self._inbox_path, {"events": []})
            inbox["events"] = [e for e in inbox["events"] if e["seq"] != seq]
            _atomic_write(self._inbox_path, inbox)

    def _dispatch(self, seq: str, ev: TrackerEvent) -> None:
        if self.synchronous:
            self._handle(seq, ev)
        else:
            self._queue.put((seq, ev))

    def _handle(self, seq: str, ev: TrackerEvent) -> None:
        try:
            handle_event(ev, self.deps)
        except Exception as exc:
            # The event stays in the inbox: the next start handles it again.
            logger.error("location trips: handling %s failed: %s", ev.kind, safe_error(exc))
            return
        self._inbox_done(seq)

    def _work(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            self._handle(*item)

    def stop(self) -> None:
        if self._thread is not None:
            self._queue.put(None)
            self._thread.join(timeout=10)

    # --- state ---------------------------------------------------------------

    def _persist(self) -> None:
        _atomic_write(self._state_path, {"tracker": self.tracker.to_dict(), "chat_id": self.chat_id})

    # --- the request path ----------------------------------------------------

    def feed(self, point: dict[str, Any]) -> list[dict[str, Any]]:
        fix = point_to_fix(point)
        with self._lock:
            if point.get("chat_id"):
                self.chat_id = int(point["chat_id"])
            events = self.tracker.feed(fix) if fix is not None else []
            self._persist()
            queued = [(self._inbox_add(ev), ev) for ev in events]
        for seq, ev in queued:
            self._dispatch(seq, ev)
        return self.deps.outbox.serve()

    def ack(self, item_id: str) -> bool:
        return self.deps.outbox.ack(item_id)

    # --- the clock -----------------------------------------------------------

    def tick(self, now: dt.datetime) -> list[dict[str, Any]]:
        """Run once a minute. Returns notices that must be pushed directly (no point will carry them)."""
        notices: list[dict[str, Any]] = []
        with self._lock:
            events = self.tracker.tick(now)
            self._maybe_find_home(now)
            # Places learned from answers, and pause spots, reach the tracker
            # within a minute rather than at the next restart.
            self.tracker.places = self._places()[1]
            self._persist()
            queued = [(self._inbox_add(ev), ev) for ev in events]
        for seq, ev in queued:
            self._dispatch(seq, ev)
        if any(ev.kind == "SHARE_ENDED" for ev in events):
            notices.append(notice_receipt(SHARE_STOPPED))
        return notices

    def _maybe_find_home(self, now: dt.datetime) -> None:
        if self.tracker.home is not None:
            return
        today = now.astimezone(ZoneInfo(self.deps.tz)).date()
        if self._home_checked == today:
            return
        self._home_checked = today
        fixes = load_fixes(self.root, today - dt.timedelta(days=HOME_DAYS), today)
        home = find_home(fixes, self.deps.tz, today, HOME_DAYS)
        if home is None:
            return
        places_mod.set_home(self.deps.places_path, *home)
        self.tracker.set_home(home)
        self.deps.outbox.add("notice", notice_receipt(HOME_FOUND), None)

    # --- answers -------------------------------------------------------------

    def answer(self, trip_id: str, stop_id: str | None, purpose: str, place: str | None) -> dict[str, Any]:
        out = apply_answer(trip_id, stop_id, purpose, place, self.deps)
        rec = out["record"]
        return {"trip_id": trip_id, "stop_id": stop_id, "purpose": purpose, "conflict": out["conflict"],
                "blocks": {part: ref.get("event_id") for part, ref in rec["blocks"].items()}}

    def render_arrival(self, trip_id: str) -> dict[str, Any] | None:
        with self.deps.records.lock_for(trip_id):
            rec = self.deps.records.get(trip_id)
            if rec is None:
                return None
            receipt = arrival_receipt(rec, self.deps.events, self.deps.tz)
            if rec.get("arrival_item"):
                self.deps.outbox.update(rec["arrival_item"], receipt)
            self.deps.records.save(rec)
            return receipt

    def tap(self, trip_id: str, line: str, action: str) -> dict[str, Any]:
        """A button on a trip message. Raises KeyError when the trip is gone.

        Answer taps are applied here. Approval taps are returned as
        `approvals` — (date, event_id, state) — for the route to run through
        `set_event_state`, which is async and owns Google and habit ticks.
        """
        with self.deps.records.lock_for(trip_id):
            return self._tap(trip_id, line, action)

    def _tap(self, trip_id: str, line: str, action: str) -> dict[str, Any]:
        rec = self.deps.records.get(trip_id)
        if rec is None:
            raise KeyError(trip_id)
        out: dict[str, Any] = {"receipt": None, "toast": None, "open_question": None, "approvals": [],
                               "syncs": [], "rerender": False}
        if action in ("ok", "no"):
            return self._approve(rec, line, action, out)

        stop_id = None if line == "trip" else line
        if stop_id is not None and Trip.from_dict(rec["trip"]).stop(stop_id) is None:
            raise KeyError(stop_id)
        if action == "t":
            options = options_for(rec, line)
            q = question_receipt(rec, stop_id, options, self.deps.now(), self.deps.tz)
            out.update(toast="Type what it was — your next message is the answer.", open_question=q["open_question"])
            return out
        if action == "l" and stop_id is not None:
            if rec.get("closed"):
                out["toast"] = "It's in the message from when you got home."
                return out
            defer_stop(trip_id, stop_id, self.deps)
            out.update(toast="OK — I'll ask when you're home", receipt=_answered(rec, "Later", glyph="…"))
            return out
        # An answer given in the arrival message redraws that message, not a question.
        at_home = bool(rec.get("closed"))
        if action == "p" and stop_id is not None:
            apply_answer(trip_id, stop_id, None, None, self.deps, pause=True)
            out["toast"] = "Just a pause — noted"
            if at_home:
                out["rerender"] = True
            else:
                out["receipt"] = _answered(rec, "Just a pause")
            return out
        options = options_for(rec, line)
        index = int(action[1:]) if action.startswith("a") and action[1:].isdigit() else -1
        if not 0 <= index < len(options):
            out["toast"] = "That choice is gone."
            return out
        chosen = options[index]
        result = apply_answer(trip_id, stop_id, chosen.name, chosen.destination, self.deps, osm=chosen.osm)
        out["toast"] = f"✓ {chosen.name}"
        if result["conflict"]:
            out["toast"] += f" — is this a different {result['conflict']}?"
        if stop_id is None or at_home:
            out["rerender"] = True
        else:
            out["receipt"] = _answered(rec, chosen.name)
        return out

    def _approve(self, rec: dict, line: str, action: str, out: dict[str, Any]) -> dict[str, Any]:
        order = rec.get("arrival_lines") or []
        if line == "all":
            parts = list(order)
        elif line.isdigit() and 1 <= int(line) <= len(order):
            parts = [order[int(line) - 1]]
        else:
            out["toast"] = "That line is gone — refresh /day."
            return out
        state = "approved" if action == "ok" else "dismissed"
        for part in parts:
            ref = (rec.get("blocks") or {}).get(part)
            if ref and not ref.get("gone"):
                # Every piece of a block split at midnight, not only the first.
                for frag in fragments(ref):
                    out["approvals"].append((frag["date"], frag["event_id"], state))
                continue
            merged = (rec.get("merged") or {}).get(part)
            if merged and not merged.get("confirmed"):
                if self._settle_merged(merged, action):
                    out["syncs"].append((merged["date"], merged["event_id"]))
        # ✓ confirms the trip's purpose only when it covers the block that
        # carries it (spec §5.2): ✓ All, or ✓ on the trip's own block.
        if action == "ok" and (line == "all" or "trip" in parts):
            rec["confirmed"] = True
        self.deps.records.save(rec)
        out["rerender"] = True
        out["toast"] = "✓ Confirmed" if action == "ok" else "Dismissed"
        return out

    def _settle_merged(self, merged: dict, action: str) -> bool:
        """✓ keeps what location filled into your block; ✕ puts your block back as you left it.

        Returns whether the block now needs pushing to Google: the fill was
        held back until this ✓ (writer `_merge`, deferred sync).
        """
        merged["confirmed"] = True
        if action == "ok":
            fields = {f.replace("_time", "_precision"): "exact" for f in merged.get("filled") or {}}
            if fields:
                self.deps.events.update_event(date=merged["date"], event_id=merged["event_id"], updates=fields)
            return bool(fields)
        # Straight to the store, not through update_event's schema: the value
        # to put back is often "no end yet" (None), which the tool refuses.
        # The fill never reached Google, so there is nothing to undo there.
        restore = {**(merged.get("filled") or {}), **(merged.get("filled_precision") or {})}
        if restore:
            self.deps.events.update_event(date=merged["date"], event_id=merged["event_id"], updates=restore)
        merged["rejected"] = True
        return False


def _answered(rec: dict, name: str, glyph: str = "✓") -> dict[str, Any]:
    """The question message once answered: what you said, no buttons."""
    line = {"id": 0, "glyph": glyph, "when": "", "text": name, "detail": None, "sync": None, "reason": "",
            "status": "answered", "buttons": []}
    return {"turn_id": rec["id"], "lines": [line], "undo": None, "open_question": None, "text": f"{glyph} {name}"}


def build_runtime(settings, *, agent, events, vault, claude, log) -> LocationRuntime:
    data = Path(settings.events_data_path).parent
    deps = TripDeps(
        records=None, outbox=None, places_path=data / "places.json", labels_dir=data / "eval" / "location",
        run_tool=agent.run_tool, events=events, vault=vault, claude=claude,
        conversations_dir=Path(settings.vault_path) / "00-system" / "conversations", tz=settings.vault_timezone,
        model=settings.location_guess_model, timeout_s=settings.location_guess_timeout_s,
        boundary_hour=settings.fast_lane_day_boundary_hour, chat_id=lambda: None,
        now=lambda: dt.datetime.now(ZoneInfo(settings.vault_timezone)), log=log,
        derived_dir=Path(settings.location_data_path) / "derived",
    )
    if settings.location_map == "on":
        from src.services.location.map_update import index_path
        deps.map_index = index_path(settings.location_map_path)
    from src.services.location.outbox import Outbox
    from src.services.location.records import TripRecords
    root = Path(settings.location_data_path)
    deps.records = TripRecords(root)
    deps.outbox = Outbox(root / "outbox.json")
    return LocationRuntime(root, deps)
