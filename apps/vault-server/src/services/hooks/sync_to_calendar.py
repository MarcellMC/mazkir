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

logger = logging.getLogger(__name__)

_DELETE_TOOLS = {"delete_task", "delete_habit", "archive_task", "archive_goal"}
_COMPLETE_TOOLS = {"complete_task", "complete_habit"}


def _record(output: dict, **fields) -> None:
    """Stamp the calendar-sync outcome onto a successful tool result.

    The agent is instructed never to claim a sync it cannot see. On success,
    we leave a verdict at `output["data"]["calendar_sync"]`. On failure, the
    tool result carries `error` (not `data`), and the agent reads the error
    instead — no stamp is needed.
    """
    data = output.get("data")
    if isinstance(data, dict):
        data["calendar_sync"] = fields


def _maybe_await(value):
    """If `value` is a coroutine, run it; otherwise return as-is."""
    if asyncio.iscoroutine(value):
        try:
            return asyncio.run(value)
        except RuntimeError:
            # Already inside an event loop — run in a worker thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                return ex.submit(asyncio.run, value).result()
    return value


def sync_to_calendar(params: dict, output: dict, ctx: Any) -> None:
    """Post-hook: push changes to Google Calendar (best-effort)."""
    try:
        calendar = (ctx or {}).get("calendar")
        if calendar is None or not getattr(calendar, "is_initialized", False):
            _record(output, ok=False, reason="calendar_not_configured")
            return
        if not output.get("ok", False):
            return

        tool_name = ctx.get("tool", {}).get("schema", {}).get("name", "")

        if tool_name in _DELETE_TOOLS:
            _record(output, ok=False, reason="not_applicable")
            return

        items = output.get("_items") or []
        if not items:
            _record(output, ok=False, reason="no_items")
            return
        path = items[0]

        vault = ctx.get("vault")
        if vault is None:
            _record(output, ok=False, reason="vault_unavailable")
            return

        try:
            item = vault.read_file(path)
        except Exception:
            _record(output, ok=False, reason="path_unreadable")
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
                _record(output, ok=True, event_id=google_event_id)
            else:
                _record(
                    output,
                    ok=False,
                    reason="mark_complete_failed",
                    event_id=google_event_id,
                )
            return

        event_id = None
        if item_type == "task":
            event_id = _maybe_await(calendar.sync_task(item))
        elif item_type == "habit":
            event_id = _maybe_await(calendar.sync_habit(item))

        if event_id and not meta.get("google_event_id"):
            vault.update_file(path, {"google_event_id": event_id})

        if event_id:
            _record(output, ok=True, event_id=event_id)
        else:
            _record(output, ok=False, reason="no_event_created")
    except Exception as e:
        logger.warning("sync_to_calendar hook failed: %s", e)
        _record(output, ok=False, reason=str(e))
