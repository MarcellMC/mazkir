"""Unified events API — auto-merges from sources on read, persists enriched data."""

from datetime import date as date_type

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.services.habit_completion import completions_today, daily_target_of, is_complete_today
from src.services.merger_service import MergerService

router = APIRouter(prefix="/events", tags=["events"])


class PatchEventBody(BaseModel):
    photos: list[dict] | None = None
    assets: dict[str, str] | None = None
    name: str | None = None
    location: dict | None = None


async def _merge_from_sources(date: date_type) -> list[dict]:
    """Run MergerService against all sources and return fresh event dicts."""
    from src.main import get_vault, get_calendar, get_timeline

    vault = get_vault()
    calendar = get_calendar()
    timeline = get_timeline()

    calendar_events = []
    if calendar and calendar.is_initialized:
        try:
            calendar_events = await calendar.get_todays_events(
                all_calendars=True, target_date=date,
            )
        except Exception:
            pass

    timeline_data = {"visits": [], "activities": []}
    if timeline:
        try:
            timeline_data = timeline.get_day(date)
        except Exception:
            pass

    habits = []
    try:
        raw_habits = vault.list_active_habits()
        for h in raw_habits:
            meta = h["metadata"]
            habits.append({
                "name": meta.get("name", ""),
                # Target met on `date`, not merely touched: `last_completed`
                # is stamped on partial completions too.
                "completed_today": is_complete_today(h, date),
                "streak": meta.get("streak", 0),
                "tokens_per_completion": meta.get("tokens_per_completion", 5),
                "scheduled_at": meta.get("scheduled_at") or meta.get("scheduled_time") or None,
                "duration_minutes": meta.get("duration_minutes", 0),
                "completions_today": completions_today(h, date),
                "daily_target": daily_target_of(meta),
            })
    except Exception:
        pass

    daily = {}
    daily_body = ""
    try:
        raw_daily = vault.read_daily_note(date)
        daily = raw_daily.get("metadata", {})
        daily_body = raw_daily.get("content", "")
    except Exception:
        pass

    merger = MergerService(timezone="Asia/Jerusalem")
    events = merger.merge(
        calendar_events=calendar_events,
        timeline_data=timeline_data,
        habits=habits,
        daily=daily,
        daily_body=daily_body,
        date=date.isoformat(),
    )
    return [e.model_dump() for e in events]


@router.get("/{date}")
async def get_events(date: date_type):
    """Get events for a date — auto-merges from sources and persists."""
    from src.main import get_events as get_events_svc
    events_svc = get_events_svc()
    if not events_svc:
        raise HTTPException(503, "Events service not initialized")

    fresh = await _merge_from_sources(date)
    result = events_svc.auto_refresh(date.isoformat(), fresh)

    return {
        "date": date.isoformat(),
        "events": result,
        "summary": {
            "total_events": len(result),
            "total_tokens": sum(e.get("tokens_earned", 0) for e in result),
        },
    }


@router.post("/{date}/refresh")
async def refresh_events(date: date_type):
    """Force-refresh events from sources (same as GET, explicit intent)."""
    result = await get_events(date)
    result["refreshed"] = True
    return result


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
