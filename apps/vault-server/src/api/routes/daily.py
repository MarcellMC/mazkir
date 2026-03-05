"""Daily note API routes."""
from datetime import datetime
from fastapi import APIRouter, Depends
import pytz
from src.main import get_vault, get_calendar
from src.auth import verify_api_key
from src.config import settings
from src.api.routes import item_name

router = APIRouter(prefix="/daily", tags=["daily"], dependencies=[Depends(verify_api_key)])

tz = pytz.timezone(settings.vault_timezone)


@router.get("")
async def get_daily():
    vault = get_vault()
    calendar = get_calendar()

    # Read or create daily note
    try:
        daily = vault.read_daily_note()
    except FileNotFoundError:
        daily = vault.create_daily_note()

    metadata = daily["metadata"]

    # Get habits status
    habits = vault.list_active_habits()
    completed_habits = metadata.get("completed_habits", [])
    today = datetime.now(tz).strftime("%Y-%m-%d")

    habit_status = []
    for h in habits:
        h_meta = h["metadata"]
        name = item_name(h)
        habit_status.append({
            "name": name,
            "completed": name in completed_habits or h_meta.get("last_completed") == today,
            "streak": h_meta.get("streak", 0),
        })

    # Get calendar events
    calendar_events = []
    if calendar and calendar.is_initialized:
        try:
            events = await calendar.get_todays_events(all_calendars=True)
            calendar_events = events
        except Exception:
            pass

    # Get notes section
    notes = vault.get_daily_notes_section()

    return {
        "date": metadata.get("date"),
        "day_of_week": metadata.get("day_of_week"),
        "tokens_earned": metadata.get("tokens_earned", 0),
        "tokens_total": metadata.get("tokens_total", 0),
        "habits": habit_status,
        "calendar_events": calendar_events,
        "notes": notes,
    }
