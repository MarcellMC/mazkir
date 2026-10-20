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
from zoneinfo import ZoneInfo

from src.config import settings

from src.services.daily_tasks import remove_todo, set_todo_checked
from src.services.fast_lane.act import _find as find_event
from src.services.fast_lane.receipt import UNDO_WINDOW
from src.services.habit_completion import retract_completion

logger = logging.getLogger(__name__)

# The fields you can change in /day or by talking; a difference in any means "changed since".
# `date` is deliberately absent: `find_event` adds it to every snapshot and to
# the current copy alike, and a move between days already shows in the times.
_COMPARED = ("name", "state", "location", "activity", "proposed")
_TIMES = ("start_time", "end_time")
# Keys that exist only on `find_event`'s copies, or that must never be rewritten.
_NOT_FIELDS = {"id", "date"}
# What `update_event` rewrites when a restore moves a block back across days.
_PROVENANCE = ("source_ids", "moved_from_source_ids", "source")
_UNDOABLE = ("done", "approved", "pending")


def _local(value) -> dt.datetime | None:
    """The vault-local wall time a stored timestamp names, or None if it doesn't parse.

    A naive value is already local wall time. An aware one — Google's echo,
    `…T08:00:00+02:00`, which reconcile persists over Mazkir's naive original —
    is converted to the vault's zone first, so it compares as the same instant.
    (`habit_completion._wall` only drops the offset, which is wrong for `Z`.)
    """
    try:
        moment = dt.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone(ZoneInfo(settings.vault_timezone)).replace(tzinfo=None)
    return moment


def _same_time(a, b) -> bool:
    if a == b:
        return True
    la, lb = _local(a), _local(b)
    return la is not None and lb is not None and la == lb


def _changed(current: dict, after: dict | None) -> bool:
    if after is None:
        return True
    if any(current.get(k) != after.get(k) for k in _COMPARED):
        return True
    return not all(_same_time(current.get(k), after.get(k)) for k in _TIMES)


def _retract(completion: dict, vault) -> str | None:
    result = retract_completion(vault, completion["path"], completion["completed_at"], completion["prior"])
    return None if result["ok"] else f"habit: {result['reason']}"


def _google_blocker(event: dict, calendar) -> str | None:
    """Why the block's Google entry can't be removed, or None. Mazkir's copy alone would merge back."""
    if not (event.get("source_ids") or {}).get("calendar_id"):
        return None
    if event.get("calendar") not in (None, "Mazkir"):
        return "it lives in another calendar"
    if calendar is None or not getattr(calendar, "is_initialized", False):
        return "Google Calendar isn't reachable"
    return None


def _delete_google(event: dict, calendar) -> str | None:
    """Remove the block's Google entry (preconditions already checked), or say why not."""
    google_id = (event.get("source_ids") or {}).get("calendar_id")
    if not google_id:
        return None
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
    # Refuse before touching anything: a tick taken back from a block that
    # then stays would be half an undo.
    for event in live:
        if why := _google_blocker(event, calendar):
            return why
    for event in live:
        if why := _delete_google(event, calendar):
            return why
        source_ids = event.get("source_ids") or {}
        removed = "calendar_id" in source_ids
        if removed:
            # Gone from Google: forget the id, so a retry after a failed
            # retract below does not ask Google to delete it a second time.
            rest = {k: v for k, v in source_ids.items() if k != "calendar_id"}
            events.update_event(event["date"], event["id"], {"source_ids": rest})
        completion = event.get("habit_completion")
        if completion and (why := _retract(completion, vault)):
            return f"removed from Google; {why}" if removed else why
        events.delete_event(event["date"], event["id"])
    return None


def _undo_edited(rec: dict, line: dict, *, events, vault, calendar) -> str | None:
    before, after = rec.get("before") or {}, rec.get("after") or {}
    if not rec.get("restored"):
        current = find_event(events, rec["event_id"])
        if current is None:
            return "the block is gone"
        if not before:
            return "nothing was kept to restore"
        if _changed(current, after):
            return "changed since"
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
        # The fields are back. A retry after a failed retract below must go
        # straight to the tick: re-comparing the restored block with `after`
        # would read our own restore as "changed since".
        rec["restored"] = True
    # Only once the fields are back: a refused restore must leave the tick too.
    # Read from the snapshot, not the block — the restore cleared it there.
    ticked = after.get("habit_completion")
    if ticked and not before.get("habit_completion") and (why := _retract(ticked, vault)):
        return f"block restored; {why}"
    restored = find_event(events, rec["event_id"])
    if restored and (restored.get("source_ids") or {}).get("calendar_id") and calendar is not None:
        from src.services.calendar_push import sync_block
        # Best effort: reported on the line, never a reason to refuse the undo.
        line["calendar_sync"] = sync_block(calendar, events, restored["date"], rec["event_id"])
    return None


def _undo_todo(rec: dict, *, vault, remove: bool) -> str | None:
    note = vault.read_daily_note(rec["date"])
    content = (note or {}).get("content") or ""
    if remove:
        body, reason = remove_todo(content, rec["text"])
        if reason == "not_found":
            return "the todo isn't there any more"
    else:
        body, reason = set_todo_checked(content, rec["text"], checked=False)
        if reason == "not_found":
            return "the todo is gone"
    if reason != "ok":
        return f"several todos match “{rec['text']}”"
    vault.write_daily_note(rec["date"], body)
    return None


def _undo_one(rec: dict, line: dict, *, events, vault, calendar) -> str | None:
    kind = rec.get("kind")
    if kind == "created":
        return _undo_created(rec, events=events, vault=vault, calendar=calendar)
    if kind == "edited":
        return _undo_edited(rec, line, events=events, vault=vault, calendar=calendar)
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
        # Each record that is taken back leaves the line, so a retry after a
        # refusal sees only what is left — never re-attempts what already
        # succeeded (an added todo it removed itself would read as "gone").
        while line["undo"]:
            rec = line["undo"][-1]
            try:
                why = _undo_one(rec, line, events=events, vault=vault, calendar=calendar)
            except Exception as e:   # one line's failure must not strand the rest
                logger.warning("fast lane undo failed on a line", exc_info=True)
                why = str(e) or type(e).__name__
            if why:
                break
            line["undo"].pop()
        if why:
            line["undo_note"] = f"can't undo: {why}"
            kept += 1
        else:
            line["status"] = "undone"
            line.pop("undo_note", None)
            undone += 1
    return turn, _toast(undone, kept)
