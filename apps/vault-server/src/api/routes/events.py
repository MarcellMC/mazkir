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


async def _merge_from_sources(date: date_type) -> tuple[list[dict], set[str]]:
    """Run MergerService against all sources and return fresh event dicts.

    Also returns which source systems actually answered this call —
    `refresh_events` needs that to tell "the calendar has nothing today"
    apart from "the calendar failed to answer", since only the former means
    an unmatched persisted event was genuinely deleted upstream. An
    uninitialized calendar (no OAuth token yet) is not an available source
    either — that's the exact condition that caused the original data loss.
    """
    from src.main import get_vault, get_calendar, get_timeline

    vault = get_vault()
    calendar = get_calendar()
    timeline = get_timeline()

    available_sources: set[str] = set()

    calendar_events = []
    if calendar and calendar.is_initialized:
        try:
            # `.get_todays_events` swallows HttpErrors and returns [] either
            # way, so it cannot tell "the calendar is empty" from "the token
            # expired" — that was the bug this fix exists for. The
            # `_with_status` variant reports a real ok/failed signal.
            calendar_events, calendar_ok = await calendar.get_todays_events_with_status(
                all_calendars=True, target_date=date,
            )
            if calendar_ok:
                available_sources.add("calendar")
        except Exception:
            pass

    timeline_data = {"visits": [], "activities": []}
    if timeline:
        try:
            timeline_data = timeline.get_day(date)
            # get_day/_load_timeline_objects returns [] when data/timeline/
            # doesn't exist rather than raising, so a missing Takeout export
            # looks identical to "nothing happened today" unless gated here.
            if timeline.data_path.exists():
                available_sources.add("timeline")
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
        available_sources.add("habit")
    except Exception:
        pass

    daily = {}
    daily_body = ""
    try:
        raw_daily = vault.read_daily_note(date)
        daily = raw_daily.get("metadata", {})
        daily_body = raw_daily.get("content", "")
        # read_daily_note catches FileNotFoundError internally and returns
        # an empty note, so the call succeeding says nothing about whether
        # a note exists — a missing note for `date` is real information (no
        # checkboxes to merge), not a failure. Gate on the vault directory
        # itself resolving instead; that is the actual "did this source
        # answer" question.
        if vault.vault_path.exists():
            available_sources.add("daily-note")
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
    return [e.model_dump() for e in events], available_sources


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
