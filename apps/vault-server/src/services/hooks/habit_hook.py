"""Post-hook: a block written by any path that is a habit ticks that habit (fast-lane spec §7.2)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _fetch(events, event_id: str, hint: str | None) -> dict | None:
    """The event `event_id` names, or None if no file holds it."""
    date = events.resolve_event_date(event_id, hint)
    if date is None:
        return None
    return next((e for e in events.get_events(date) if e.get("id") == event_id), None)


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

        hint = data.get("date") or params.get("date")
        # A block split at midnight ticks once, on its LAST fragment only —
        # that is when it ended. Never fall back to an earlier fragment: an
        # earlier one can have begun while the last has not (ticking it
        # would stamp the completion before the activity actually finished),
        # or can belong to a day whose own target is already met (ticking it
        # would credit the wrong day). Fragments are listed earliest first,
        # so the last one is simply the final entry.
        ids = list(dict.fromkeys([first, *(data.get("fragments") or [])]))
        fetched = [_fetch(events, event_id, hint) for event_id in ids]

        # At most one tick per block: if any fragment already carries a
        # completion, the block was ticked already and nothing fires again.
        if any(event and event.get("habit_completion") for event in fetched):
            return

        last_id = ids[-1]
        last_date = events.resolve_event_date(last_id, hint)
        if last_date:
            tick_if_habit(vault, events, last_date, last_id)
    except Exception:
        logger.warning("habit hook failed", exc_info=True)
