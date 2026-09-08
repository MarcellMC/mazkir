"""Unified events API — auto-merges from sources on read, persists enriched data."""

from datetime import date as date_type

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.services.day_assembly import merge_from_sources as _merge_from_sources

router = APIRouter(prefix="/events", tags=["events"])


class PatchEventBody(BaseModel):
    photos: list[dict] | None = None
    assets: dict[str, str] | None = None
    name: str | None = None
    location: dict | None = None


def _events_payload(date: date_type, result: list[dict]) -> dict:
    return {
        "date": date.isoformat(),
        "events": result,
        "summary": {
            "total_events": len(result),
            "total_tokens": sum(e.get("tokens_earned", 0) for e in result),
        },
    }


@router.get("/{date}")
async def get_events(date: date_type):
    """Get events for a date — auto-merges from sources and persists."""
    from src.main import get_events as get_events_svc
    events_svc = get_events_svc()
    if not events_svc:
        raise HTTPException(503, "Events service not initialized")

    fresh, available_sources = await _merge_from_sources(date)
    result = events_svc.auto_refresh(date.isoformat(), fresh, available_sources)
    return _events_payload(date, result)


async def get_events_preview(date: date_type) -> dict:
    """Merge from sources and reconcile against persisted data, without
    persisting the result.

    `/daily` uses this instead of `get_events` so that browsing a date can
    never itself write `data/events/{date}.json` for it — a persisted event
    for a past date must not be silently rewritten just because someone
    looked at it.

    `GET /events/{date}` itself keeps persisting: `list_events`,
    `attach_photo_to_event` and `update_event` (the agent's event tools) all
    read the raw persisted file via `EventsService.get_events`/`attach_photo`
    rather than re-merging, so this route's persist is what makes a
    calendar/timeline/habit-derived event referenceable by ID at all — an
    event the agent should attach a photo to has to have landed in the store
    via some prior GET (or an explicit POST .../refresh) first. Removing
    that persist would silently break every one of those tools for anything
    that isn't a manually created event.
    """
    from src.main import get_events as get_events_svc
    events_svc = get_events_svc()
    if not events_svc:
        raise HTTPException(503, "Events service not initialized")

    fresh, available_sources = await _merge_from_sources(date)
    result = events_svc.reconcile(date.isoformat(), fresh, available_sources)
    return _events_payload(date, result)


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
