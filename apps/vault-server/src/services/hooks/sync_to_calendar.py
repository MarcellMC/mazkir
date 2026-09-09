"""sync_to_calendar post-hook — push task/habit writes to Google Calendar.

Wired into tools that create/update/complete/archive/delete a task or habit.
Reads the affected vault path from output._items, loads the metadata, and
dispatches to CalendarService.sync_task / sync_habit / mark_event_complete.

Hook failures log at WARNING and never re-raise — calendar sync is
best-effort.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.services.async_bridge import maybe_await as _maybe_await

logger = logging.getLogger(__name__)

_DELETE_TOOLS = {"delete_task", "delete_habit", "archive_task", "archive_goal"}
_COMPLETE_TOOLS = {"complete_task", "complete_habit"}


def _record(output: dict, **fields) -> None:
    """Stamp the calendar-sync outcome onto a successful tool result.

    The agent is instructed never to claim a sync it cannot see. On success,
    we leave a verdict at `output["data"]["calendar_sync"]`. On failure, the
    tool result carries `error` (not `data`), and the agent reads the error
    instead — no stamp is needed.

    Every stamp carries `attempted`, which separates the two kinds of
    `ok: false`:

      - `attempted: True`  — a sync was expected to happen and did not.
        The user should be told the calendar was NOT updated.
      - `attempted: False` — there was nothing to sync (no calendar
        configured, a delete, a task with no due date). Not a failure;
        the agent stays quiet about the calendar.
    """
    data = output.get("data")
    if isinstance(data, dict):
        data["calendar_sync"] = fields


def sync_to_calendar(params: dict, output: dict, ctx: Any) -> None:
    """Post-hook: push changes to Google Calendar (best-effort)."""
    try:
        calendar = (ctx or {}).get("calendar")
        if calendar is None or not getattr(calendar, "is_initialized", False):
            _record(
                output, ok=False, attempted=False, reason="calendar_not_configured"
            )
            return
        if not output.get("ok", False):
            return

        tool_name = ctx.get("tool", {}).get("schema", {}).get("name", "")

        if tool_name in _DELETE_TOOLS:
            _record(output, ok=False, attempted=False, reason="not_applicable")
            return

        items = output.get("_items") or []
        if not items:
            _record(output, ok=False, attempted=True, reason="no_items")
            return
        path = items[0]

        vault = ctx.get("vault")
        if vault is None:
            _record(output, ok=False, attempted=True, reason="vault_unavailable")
            return

        try:
            item = vault.read_file(path)
        except Exception:
            _record(output, ok=False, attempted=True, reason="path_unreadable")
            return
        meta = item.get("metadata", {})
        item_type = meta.get("type")

        if tool_name in _COMPLETE_TOOLS and meta.get("google_event_id"):
            google_event_id = meta["google_event_id"]
            # mark_event_complete swallows HttpError and returns False — a stale
            # event id (404), a revoked token (401) or a quota trip (403) all
            # come back as a falsy return, never an exception. Reporting success
            # here would be exactly the lie §3.4 forbids.
            marked = _maybe_await(calendar.mark_event_complete(google_event_id))
            if marked:
                _record(output, ok=True, attempted=True, event_id=google_event_id)
            else:
                _record(
                    output,
                    ok=False,
                    attempted=True,
                    reason="mark_complete_failed",
                    event_id=google_event_id,
                )
            return

        # sync_task returns None both for "this task has no due date, there is
        # nothing to put on a calendar" and for "the API call failed". Screen
        # the first case here so the second one can be reported honestly.
        if item_type == "task" and not meta.get("due_date"):
            _record(output, ok=False, attempted=False, reason="no_due_date")
            return
        if item_type not in ("task", "habit"):
            _record(output, ok=False, attempted=False, reason="not_syncable")
            return

        if item_type == "task":
            event_id = _maybe_await(calendar.sync_task(item))
        else:
            event_id = _maybe_await(calendar.sync_habit(item))

        if event_id and not meta.get("google_event_id"):
            vault.update_file(path, {"google_event_id": event_id})

        if event_id:
            _record(output, ok=True, attempted=True, event_id=event_id)
        else:
            _record(output, ok=False, attempted=True, reason="no_event_created")
    except Exception as e:
        logger.warning("sync_to_calendar hook failed: %s", e)
        _record(output, ok=False, attempted=True, reason=str(e))
