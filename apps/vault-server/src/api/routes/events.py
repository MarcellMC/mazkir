"""Events persistence API — read, refresh, patch persisted merged events."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/events", tags=["events"])


class PatchEventBody(BaseModel):
    photos: list[dict] | None = None
    assets: dict[str, str] | None = None
    name: str | None = None
    location: dict | None = None


@router.get("/{date}")
async def get_events(date: str):
    """Get persisted events for a date."""
    from src.main import get_events as get_events_svc
    events_svc = get_events_svc()
    if not events_svc:
        raise HTTPException(503, "Events service not initialized")
    events = events_svc.get_events(date)
    return {"date": date, "events": events}


@router.post("/{date}/refresh")
async def refresh_events(date: str):
    """Re-merge events from sources, preserving manual data."""
    from src.main import get_events as get_events_svc, get_calendar, get_timeline, get_vault
    events_svc = get_events_svc()
    if not events_svc:
        raise HTTPException(503, "Events service not initialized")

    from src.services.merger_service import MergerService
    merger = MergerService()
    vault = get_vault()
    calendar = get_calendar()
    timeline = get_timeline()

    # Gather source data
    calendar_events = []
    if calendar and calendar.is_initialized:
        try:
            from datetime import date as date_type
            target = date_type.fromisoformat(date)
            calendar_events = await calendar.get_todays_events(all_calendars=True, target_date=target)
        except Exception:
            pass

    timeline_data = None
    if timeline:
        try:
            from datetime import date as date_type
            timeline_data = timeline.get_day(date_type.fromisoformat(date))
        except Exception:
            pass

    habits = vault.list_active_habits()
    daily = vault.read_daily_note()

    fresh_events = merger.merge(
        calendar_events=calendar_events,
        timeline_data=timeline_data,
        habits=habits,
        daily=daily,
    )
    fresh_dicts = [e.model_dump() for e in fresh_events]

    result = events_svc.refresh_events(date, fresh_dicts)
    return {"date": date, "events": result, "refreshed": True}


@router.patch("/{date}/{event_id}")
async def patch_event(date: str, event_id: str, body: PatchEventBody):
    """Update a single persisted event."""
    from src.main import get_events as get_events_svc
    events_svc = get_events_svc()
    if not events_svc:
        raise HTTPException(503, "Events service not initialized")

    events = events_svc.get_events(date)
    for event in events:
        if event["id"] == event_id:
            updates = body.model_dump(exclude_none=True)
            event.update(updates)
            events_svc.save_events(date, events)
            return {"updated": event_id, "event": event}

    raise HTTPException(404, f"Event {event_id} not found")
