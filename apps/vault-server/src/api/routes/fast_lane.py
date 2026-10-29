"""Taps on a receipt (fast-lane spec §8.2): approve, dismiss, add a place, confirm a habit, undo.

Each tap changes one line of the turn record and returns the re-rendered
receipt, which the bot edits in place. A line already settled answers with
a toast and changes nothing, so a double tap is harmless.

Every tap is one read-modify-write of the saved turn, under `act.update_turn`'s
process-wide lock. The on-route patches each line's Google sync onto the same
record after the reply, and a tap holding a copy read before that patch would
erase it (or the patch would erase the tap's `undone` markers). Taps call
Google and the vault while holding that lock, so the handlers are plain `def`:
FastAPI runs them in its threadpool, never on the event loop.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException

from src.auth import verify_api_key
from src.config import settings
from src.services.fast_lane.act import _find as find_event
from src.services.fast_lane.act import apply_result, load_turn, run_step, update_turn
from src.services.fast_lane.actions import Step
from src.services.fast_lane.receipt import render_receipt

router = APIRouter(prefix="/fast", tags=["fast-lane"], dependencies=[Depends(verify_api_key)])
logger = logging.getLogger(__name__)

_LINE_ACTIONS = frozenset({"ok", "no", "pl", "hb", "sy", "sn"})
_LINE = re.compile(r"[0-9]{1,4}")
_LIVE = ("done", "approved", "pending")
SETTLED = "Already settled"
FAILED = "That didn't work"


class _NoSuchLine(Exception):
    pass


def get_receipt_deps() -> dict:
    """Module-level shim so tests can patch the services without importing src.main."""
    from src.main import get_agent, get_calendar, get_events, get_vault
    agent = get_agent()
    if agent is None:
        raise HTTPException(503, "Agent service not initialized")
    return {"run_tool": agent.run_tool, "events": get_events(), "vault": get_vault(),
            "calendar": get_calendar(), "data_dir": settings.events_data_path.parent}


def _now() -> dt.datetime:
    return dt.datetime.now(ZoneInfo(settings.vault_timezone))


def _gone() -> HTTPException:
    return HTTPException(404, "That receipt is gone — receipts are kept for a day")


# --- what a tap does to one line -------------------------------------------


def _note_snapshot(rec: dict, event_id: str, **fields) -> None:
    """Fold a change this receipt made into the line's undo snapshot of the block.

    Undo refuses a block that differs from its snapshot ("changed since"), so
    an approval tapped here would otherwise read as your edit and make the
    turn un-undoable. Only the fields the tap itself set are folded in: an
    edit you made in /day meanwhile still stops the undo.
    """
    for undo in reversed(rec.get("undo") or []):
        if undo.get("kind") == "created" and event_id in (undo.get("ids") or []):
            after = (undo.get("after") or {}).get(event_id)
            if after is not None:
                after.update(fields)
            return
        if undo.get("kind") == "edited" and undo.get("event_id") == event_id:
            if undo.get("after") is not None:
                undo["after"].update(fields)
            return


def _run_pending(rec: dict, deps: dict) -> None:
    """A proposal's withheld calls, in order, folded into its line exactly as `run_lines` does."""
    rec.setdefault("steps", [])
    succeeded = None
    for s in rec.get("pending") or []:
        try:
            res = run_step(Step(s["tool"], s["params"]), run_tool=deps["run_tool"], events=deps["events"])
        except Exception as e:
            logger.error("fast lane receipt step %s raised", s.get("tool"), exc_info=True)
            res = {"ok": False, "reason": f"error: {type(e).__name__}", "code": "EXCEPTION", "undo": []}
        rec["steps"].append({"tool": s["tool"], "ok": res["ok"], "reason": res["reason"],
                             "code": None if res["ok"] else res.get("code", "FAILED")})
        # "approved", not "done": you said yes to it, and the receipt draws that ✓.
        apply_result(rec, res, done_status="approved",
                     partial_of=(succeeded, s["tool"]) if succeeded and not res["ok"] else None)
        if not res["ok"]:
            break
        succeeded = succeeded or s["tool"]
    rec["pending"] = []


def _set_state(rec: dict, deps: dict, state: str) -> tuple[dict | None, str | None]:
    """Approve or dismiss the line's block through /day's own route, which syncs and ticks.

    Returns `(response, None)`, or `(None, why)`. Never raises: a Google or
    merge failure is a toast on this tap, not a failed request.
    """
    from src.api.routes import events as events_route
    from src.services.async_bridge import maybe_await

    found = find_event(deps["events"], rec["event_id"], rec.get("date"))
    if found is None:
        return None, "That block is gone"
    try:
        response = maybe_await(events_route.set_event_state(
            dt.date.fromisoformat(found["date"]), rec["event_id"], events_route.SetStateBody(state=state)))
    except HTTPException as e:
        return None, str(e.detail)
    except Exception:
        logger.warning("fast lane receipt could not set %s on %s", state, rec["event_id"], exc_info=True)
        return None, FAILED
    rec["date"] = found["date"]
    return response, None


def _approve(rec: dict, deps: dict) -> str:
    response, why = _set_state(rec, deps, "approved")
    if why:
        return why
    rec["status"] = "approved"
    if response.get("calendar_sync") is not None:
        rec["calendar_sync"] = response["calendar_sync"]
    event = find_event(deps["events"], rec["event_id"], rec["date"]) or {}
    _note_snapshot(rec, rec["event_id"], state=event.get("state"))
    if event.get("habit_completion") and not rec.get("habit"):
        rec["habit"], rec["habit_candidate"] = event["habit_completion"], None
        _note_snapshot(rec, rec["event_id"], habit_completion=event["habit_completion"])
    return "Approved"


def _suggestion(action: str, rec: dict, deps: dict, now: dt.datetime) -> str:
    if rec["status"] != "pending":
        return SETTLED
    if action in ("ok", "sy"):
        try:
            res = deps["run_tool"]("create_habit", {"name": rec["suggest"], "frequency": "daily"})
        except Exception:
            logger.warning("fast lane receipt could not create habit %r", rec["suggest"], exc_info=True)
            res = {"ok": False}
        if not (isinstance(res, dict) and res.get("ok")):
            return FAILED
        rec["status"] = "done"
        return f"Tracking {rec['suggest']}"
    if action in ("no", "sn"):
        from src.services.fast_lane.habits import decline_suggestion
        decline_suggestion(rec["suggest"], now.date(), deps["data_dir"] / "fast-lane-suggestions.json")
        rec["status"] = "dismissed"
        return "Not now"
    return "Nothing to do"


def _add_place(rec: dict, deps: dict) -> str:
    if not rec.get("place_text") or rec["status"] not in _LIVE:
        return SETTLED
    from src.services.fast_lane.places import add_place
    place = add_place(deps["data_dir"] / "places.json", rec["place_text"])
    if rec.get("event_id"):
        res = deps["run_tool"]("update_event", {
            "event_id": rec["event_id"], "date": rec.get("date"),
            "_fast": {"defer_calendar_sync": True, "fields": {"place_id": place.id, "place_text": None}}})
        if not (isinstance(res, dict) and res.get("ok")):
            return FAILED   # place_text stays, so the button stays for another try
    added, rec["place_text"] = rec["place_text"], None
    return f"Added {added}"


def _tick_habit(rec: dict, deps: dict) -> str:
    if rec.get("habit"):
        return SETTLED
    candidate = rec.get("habit_candidate")
    if not candidate or not rec.get("event_id") or rec["status"] not in ("done", "approved"):
        return "Nothing to do"
    from src.services.fast_lane.habits import HabitMatch, tick_block_habit
    found = find_event(deps["events"], rec["event_id"], rec.get("date"))
    if found is None:
        return "That block is gone"
    # Task 7's tick: stamped at the block's own end, so it credits the block's day, once.
    completion = tick_block_habit(deps["vault"], deps["events"], found["date"], rec["event_id"],
                                  HabitMatch(candidate["path"], candidate["name"], "fuzzy"))
    rec["habit_candidate"] = None
    if not completion:
        return f"{candidate['name']} is already done for the day"
    rec["habit"] = completion
    _note_snapshot(rec, rec["event_id"], habit_completion=completion)
    return f"Ticked {candidate['name']}"


def _tap(action: str, rec: dict, deps: dict, now: dt.datetime) -> str:
    if rec.get("kind") == "suggest":
        return _suggestion(action, rec, deps, now)
    if action in ("sy", "sn"):
        return "Nothing to do"
    if action == "pl":
        return _add_place(rec, deps)
    if action == "hb":
        return _tick_habit(rec, deps)
    if rec["status"] != "pending":   # ok / no
        return SETTLED
    if action == "ok":
        if rec["kind"] == "propose":
            _run_pending(rec, deps)
            return "Done" if rec["status"] == "approved" else FAILED
        if rec.get("event_id"):
            return _approve(rec, deps)
        return "Nothing to do"
    # action == "no"
    if rec["kind"] != "propose" and rec.get("event_id"):
        _, why = _set_state(rec, deps, "dismissed")
        if why:
            return why
    rec["pending"] = []
    rec["status"] = "dismissed"
    return "Dismissed"


# --- routes -----------------------------------------------------------------


@router.get("/receipts/{turn_id}")
def get_receipt(turn_id: str):
    deps = get_receipt_deps()
    turn = load_turn(deps["data_dir"] / "actions", turn_id)
    if turn is None:
        raise _gone()
    return render_receipt(turn, _now())


@router.post("/receipts/{turn_id}/{line}/{action}")
def tap_receipt(turn_id: str, line: str, action: str):
    # `def`, not `async def`: the whole tap runs under the turn lock and may
    # wait seconds on Google, so it belongs in the threadpool, off the loop.
    undo = line == "u" and action == "un"
    if not undo and not (_LINE.fullmatch(line) and action in _LINE_ACTIONS):
        raise HTTPException(404, "No such tap")
    deps = get_receipt_deps()
    now = _now()
    out: dict[str, str] = {}

    def change(turn: dict) -> None:
        if undo:
            from src.services.fast_lane.undo import undo_turn
            # Mutates the turn in place; update_turn saves it even when lines were kept.
            _, out["toast"] = undo_turn(turn, events=deps["events"], vault=deps["vault"],
                                        calendar=deps["calendar"], now=now)
            return
        rec = next((r for r in turn["lines"] if r.get("id") == int(line)), None)
        if rec is None:
            raise _NoSuchLine
        try:
            out["toast"] = _tap(action, rec, deps, now)
        except Exception:
            # What the tap already wrote stays recorded on the line: save, don't abort.
            logger.error("fast lane receipt tap %s on %s/%s failed", action, turn_id, line, exc_info=True)
            out["toast"] = FAILED

    try:
        turn = update_turn(deps["data_dir"] / "actions", turn_id, change)
    except _NoSuchLine:
        raise HTTPException(404, "No such line on that receipt")
    if turn is None:
        raise _gone()
    return {"receipt": render_receipt(turn, now), "toast": out["toast"]}
