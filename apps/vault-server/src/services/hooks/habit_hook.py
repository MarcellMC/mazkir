"""Post-hook: a block written by any path that is a habit ticks that habit (fast-lane spec §7.2)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def habit_hook(params: dict, output: dict, ctx) -> None:
    """Side effect only, and never raises: a failed tick must not fail the write."""
    try:
        if not isinstance(output, dict) or not output.get("ok"):
            return
        events, vault = ctx.get("events"), ctx.get("vault")
        if events is None or vault is None:
            return
        data = output.get("data") or {}
        first = data.get("event_id") or (data.get("event") or {}).get("id")
        if not first:
            return
        from src.services.fast_lane.habits import tick_if_habit
        # A block split at midnight ticks once, on its last fragment: that is when it ended.
        for event_id in reversed(list(dict.fromkeys([first, *(data.get("fragments") or [])]))):
            date = events.resolve_event_date(event_id, data.get("date") or params.get("date"))
            if date and tick_if_habit(vault, events, date, event_id):
                return
    except Exception:
        logger.warning("habit hook failed", exc_info=True)
