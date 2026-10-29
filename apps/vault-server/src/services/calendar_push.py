"""Tell Google Calendar about one of Mazkir's blocks, and say exactly what happened.

The decision tree `update_event` always used, in one place so the fast lane
can run it after its receipt is on screen (fast-lane spec §7.5):

- a block with no start can't be told to Google;
- a span across midnight is left alone (Google keeps one event where Mazkir
  keeps two fragments);
- only Mazkir's own calendar is ours to change;
- an inferred block (a checkbox, a habit, a visit) is never duplicated into
  Google;
- a proposal waits for your ✓.

The result is the `calendar_sync` shape every reporting rule already reads.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _skip(reason: str) -> dict:
    return {"ok": False, "attempted": False, "reason": reason}


def sync_block(calendar: Any, events: Any, date_str: str, event_id: str) -> dict:
    """Create or update the Google entry for one block. Never raises."""
    from src.services.async_bridge import maybe_await
    from src.services.events_service import is_complete
    from src.services.interval import crosses_midnight

    stored = next((e for e in events.get_events(date_str) if e.get("id") == event_id), None)
    if stored is None:
        return _skip("not_found")
    source_ids = stored.get("source_ids") or {}
    calendar_id = source_ids.get("calendar_id")
    if stored.get("proposed") and stored.get("state") != "approved":
        return _skip("proposed")
    if not stored.get("start_time"):
        return _skip("no_start_time")
    if is_complete(stored) and crosses_midnight(stored["start_time"], stored["end_time"]):
        return _skip("crosses_midnight")
    if stored.get("source") == "photo":
        return _skip("not_applicable")
    if not calendar or not getattr(calendar, "is_initialized", False):
        return _skip("calendar_not_configured")
    if calendar_id and stored.get("calendar") not in (None, "Mazkir"):
        return _skip("not_in_mazkir_calendar")
    if not calendar_id and source_ids:
        return _skip("derived_from_source")
    try:
        if calendar_id:
            pushed = maybe_await(calendar.update_event(
                event_id=calendar_id,
                name=stored.get("name"),
                start_time=stored.get("start_time"),
                end_time=stored.get("end_time"),
            ))
            sync = {"ok": bool(pushed), "attempted": True, "event_id": calendar_id}
            if not pushed:
                sync["reason"] = "update_failed"
            return sync
        gcal_id = maybe_await(calendar.create_event(
            name=stored.get("name"),
            date=date_str,
            start_time=(stored.get("start_time") or "")[11:16],
            end_time=(stored.get("end_time") or "")[11:16] or None,
        ))
        sync = {"ok": bool(gcal_id), "attempted": True, "event_id": gcal_id}
        if gcal_id:
            # Membership is recorded by calendar_id alone: without it the next
            # edit would create a second Google entry.
            saved = events.update_event(date=date_str, event_id=event_id,
                                        updates={"source_ids": {**source_ids, "calendar_id": gcal_id}})
            if not (saved or {}).get("updated") and events.resolve_event_date(event_id, date_str) is None:
                # Undone while Google was creating it: undo saw no calendar_id and
                # deleted only the ledger row. The new entry would merge back as a
                # pending calendar block, so it goes too. Not a ⚠: nothing failed
                # that the user still wants.
                try:
                    if not maybe_await(calendar.delete_event(gcal_id)):
                        logger.warning("Google refused to delete %s, the entry of an undone block", gcal_id)
                except Exception as e:
                    logger.warning("Failed to delete the Google entry of an undone block: %s", e)
                return _skip("undone_meanwhile")
        else:
            sync["reason"] = "create_failed"
        return sync
    except Exception as e:
        logger.warning("Failed to sync block to Google Calendar: %s", e)
        return {"ok": False, "attempted": True, "reason": str(e)}
