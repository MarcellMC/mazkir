"""Take a fast-lane turn back, line by line (fast-lane spec §7.6, §9.3).

From the snapshots `act.py` kept at write time. A line whose item changed
since — you fixed the block in /day, say — is refused with the reason rather
than overwritten: undo restores what Mazkir did, never what you did after.
Available for 24 hours from the turn's `created_at`.

Lines are undone newest first, and within a line its records newest first,
so a later write never depends on an earlier one that is already gone. A
partial line (the block was written, a later step failed) carries undo
records only for the steps that ran, so those are what is reversed.
"""

from __future__ import annotations

import datetime as dt
import logging

from src.services.daily_tasks import remove_todo, set_todo_checked
from src.services.fast_lane.act import _find as find_event
from src.services.fast_lane.receipt import UNDO_WINDOW
from src.services.habit_completion import retract_completion

logger = logging.getLogger(__name__)

# The fields you can change in /day or by talking; a difference in any means "changed since".
# `date` is deliberately absent: `find_event` adds it to every snapshot and to
# the current copy alike, and a move between days already shows in the times.
_COMPARED = ("name", "start_time", "end_time", "state", "location", "activity", "proposed")
# Keys that exist only on `find_event`'s copies, or that must never be rewritten.
_NOT_FIELDS = {"id", "date"}
# What `update_event` rewrites when a restore moves a block back across days.
_PROVENANCE = ("source_ids", "moved_from_source_ids", "source")
_UNDOABLE = ("done", "approved", "pending")


def _changed(current: dict, after: dict | None) -> bool:
    return after is None or any(current.get(k) != after.get(k) for k in _COMPARED)


def _retract(completion: dict, vault) -> str | None:
    result = retract_completion(vault, completion["path"], completion["completed_at"], completion["prior"])
    return None if result["ok"] else f"habit: {result['reason']}"


def _delete_google(event: dict, calendar) -> str | None:
    """Remove the block's Google entry, or say why not. Mazkir's copy alone would merge back."""
    google_id = (event.get("source_ids") or {}).get("calendar_id")
    if not google_id:
        return None
    if event.get("calendar") not in (None, "Mazkir"):
        return "it lives in another calendar"
    if calendar is None or not getattr(calendar, "is_initialized", False):
        return "Google Calendar isn't reachable"
    from src.services.async_bridge import maybe_await
    try:
        if not maybe_await(calendar.delete_event(google_id)):
            return "Google refused to delete it"
    except Exception as e:
        return f"Google refused to delete it: {e}"
    return None


def _undo_created(rec: dict, *, events, vault, calendar) -> str | None:
    after = rec.get("after") or {}
    live = [e for e in (find_event(events, eid) for eid in rec["ids"]) if e is not None]
    if any(_changed(e, after.get(e["id"])) for e in live):
        return "changed since"
    for event in live:
        completion = event.get("habit_completion")
        if completion:
            if why := _retract(completion, vault):
                return why
            # Taken back: clear it, so a retry after a Google refusal below
            # does not try to take the same tick back a second time.
            events.update_event(event["date"], event["id"], {"habit_completion": None})
        if why := _delete_google(event, calendar):
            return why
        events.delete_event(event["date"], event["id"])
    return None


def _undo_edited(rec: dict, *, events, vault, calendar) -> str | None:
    current = find_event(events, rec["event_id"])
    if current is None:
        return "the block is gone"
    before, after = rec.get("before") or {}, rec.get("after") or {}
    if not before:
        return "nothing was kept to restore"
    if _changed(current, after):
        return "changed since"
    ticked = current.get("habit_completion")
    if ticked and not before.get("habit_completion") and (why := _retract(ticked, vault)):
        return why
    keys = (set(before) | set(after)) - _NOT_FIELDS
    updates = {k: before.get(k) for k in keys if before.get(k) != after.get(k)}
    if updates:
        result = events.update_event(current["date"], rec["event_id"], updates)
        if "error" in result:
            return result["error"]
        if result.get("moved_from"):
            # Moving back re-detaches the upstream ids exactly as the forward
            # move did; put the provenance the block had before the edit back.
            events.update_event(result["date"], rec["event_id"], {k: before.get(k) for k in _PROVENANCE})
    restored = find_event(events, rec["event_id"])
    if restored and (restored.get("source_ids") or {}).get("calendar_id") and calendar is not None:
        from src.services.calendar_push import sync_block
        sync_block(calendar, events, restored["date"], rec["event_id"])   # best effort; logs its own failure
    return None


def _undo_todo(rec: dict, *, vault, remove: bool) -> str | None:
    note = vault.read_daily_note(rec["date"])
    content = (note or {}).get("content") or ""
    if remove:
        body, reason = remove_todo(content, rec["text"])
        if reason == "not_found":
            return None                     # already gone: nothing of ours is left to take back
    else:
        body, reason = set_todo_checked(content, rec["text"], checked=False)
        if reason == "not_found":
            return "the todo is gone"
    if reason != "ok":
        return f"several todos match “{rec['text']}”"
    vault.write_daily_note(rec["date"], body)
    return None


def _undo_one(rec: dict, *, events, vault, calendar) -> str | None:
    kind = rec.get("kind")
    if kind == "created":
        return _undo_created(rec, events=events, vault=vault, calendar=calendar)
    if kind == "edited":
        return _undo_edited(rec, events=events, vault=vault, calendar=calendar)
    if kind in ("todo_added", "todo_checked"):
        return _undo_todo(rec, vault=vault, remove=kind == "todo_added")
    if kind == "habit":
        return _retract(rec, vault)
    return rec.get("why") or "this can't be undone"


def _toast(undone: int, kept: int) -> str:
    if undone == 0 and kept == 0:
        return "Nothing to undo"
    if undone == 0:
        return f"Nothing undone, {kept} kept"
    return f"Undone {undone}" + (f", {kept} kept" if kept else "")


def undo_turn(turn: dict, *, events, vault, calendar, now: dt.datetime) -> tuple[dict, str]:
    """Reverse every line that can be, newest first. Returns the updated turn and a toast."""
    created = dt.datetime.fromisoformat(turn["created_at"]).replace(tzinfo=None)
    if now.replace(tzinfo=None) - created >= UNDO_WINDOW:
        return turn, "Too late to undo — it has been a day"
    undone = kept = 0
    for line in reversed(turn["lines"]):
        if line.get("status") not in _UNDOABLE or not line.get("undo"):
            continue
        why = None
        for rec in reversed(line["undo"]):
            try:
                why = _undo_one(rec, events=events, vault=vault, calendar=calendar)
            except Exception as e:   # one line's failure must not strand the rest
                logger.warning("fast lane undo failed on a line", exc_info=True)
                why = str(e) or type(e).__name__
            if why:
                break
        if why:
            line["undo_note"] = f"can't undo: {why}"
            kept += 1
        else:
            line["status"] = "undone"
            line.pop("undo_note", None)
            undone += 1
    return turn, _toast(undone, kept)
