from datetime import date

from fastapi import APIRouter, Depends

from src.auth import verify_api_key
from src.main import get_vault, get_calendar, get_timeline
from src.services.merger_service import MergerService

router = APIRouter(
    prefix="/merged-events",
    tags=["merged-events"],
    dependencies=[Depends(verify_api_key)],
)


@router.get("/{target_date}")
async def get_merged_events(target_date: date):
    vault = get_vault()
    timeline = get_timeline()
    calendar = get_calendar()

    # Get calendar events
    calendar_events = []
    if calendar and calendar.is_initialized:
        try:
            calendar_events = await calendar.get_todays_events(all_calendars=True)
        except Exception:
            pass  # Calendar is best-effort

    # Get timeline data
    timeline_data = {"visits": [], "activities": []}
    if timeline:
        timeline_data = timeline.get_day(target_date)

    # Get habits
    habits = []
    try:
        raw_habits = vault.list_active_habits()
        today_str = target_date.isoformat()
        for h in raw_habits:
            meta = h["metadata"]
            habits.append({
                "name": meta.get("name", ""),
                "completed_today": meta.get("last_completed") == today_str,
                "streak": meta.get("streak", 0),
                "tokens_per_completion": meta.get("tokens_per_completion", 5),
            })
    except Exception:
        pass

    # Get daily summary
    daily = {}
    try:
        daily = vault.read_daily_note(target_date)
        daily = daily.get("metadata", {})
    except Exception:
        pass

    # Merge
    merger = MergerService(timezone="Asia/Jerusalem")
    events = merger.merge(
        calendar_events=calendar_events,
        timeline_data=timeline_data,
        habits=habits,
        daily=daily,
    )

    return {
        "date": target_date.isoformat(),
        "events": [e.model_dump() for e in events],
        "summary": {
            "total_events": len(events),
            "total_tokens": sum(e.tokens_earned for e in events),
        },
    }
