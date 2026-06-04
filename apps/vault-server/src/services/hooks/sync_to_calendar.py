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
            return
        if not output.get("ok", False):
            return

        tool_name = ctx.get("tool", {}).get("schema", {}).get("name", "")

        # Delete/archive tools may leave nothing to sync.
        if tool_name in _DELETE_TOOLS:
            return

        items = output.get("_items") or []
        if not items:
            return
        path = items[0]

        vault = ctx.get("vault")
        if vault is None:
            return

        try:
            item = vault.read_file(path)
        except Exception:
            return
        meta = item.get("metadata", {})
        item_type = meta.get("type")

        # Complete: if a google_event_id exists, mark it done. Otherwise fall through to sync.
        if tool_name in _COMPLETE_TOOLS and meta.get("google_event_id"):
            _maybe_await(calendar.mark_event_complete(meta["google_event_id"]))
            return

        if item_type == "task":
            _maybe_await(calendar.sync_task(item))
        elif item_type == "habit":
            _maybe_await(calendar.sync_habit(item))
    except Exception as e:
        logger.warning("sync_to_calendar hook failed: %s", e)
