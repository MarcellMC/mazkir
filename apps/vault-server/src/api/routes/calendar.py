"""Calendar API routes."""
import logging
from fastapi import APIRouter, Depends, HTTPException
from src.main import get_vault, get_calendar
from src.auth import verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calendar", tags=["calendar"], dependencies=[Depends(verify_api_key)])


@router.get("/events")
async def get_events():
    calendar = get_calendar()
    if not calendar or not calendar.is_initialized:
        raise HTTPException(503, "Calendar service not enabled")

    events = await calendar.get_todays_events(all_calendars=True)
    return events


@router.post("/sync")
async def sync_calendar():
    vault = get_vault()
    calendar = get_calendar()

    if not calendar or not calendar.is_initialized:
        raise HTTPException(503, "Calendar service not enabled")

    habits_synced = 0
    tasks_synced = 0
    errors = 0

    for habit in vault.get_habits_needing_sync():
        try:
            event_id = await calendar.sync_habit(habit)
            if event_id:
                vault.update_google_event_id(habit["path"], event_id)
                habits_synced += 1
            else:
                errors += 1
        except Exception as e:
            logger.error(f"Error syncing habit: {e}")
            errors += 1

    for task in vault.get_tasks_needing_sync():
        try:
            event_id = await calendar.sync_task(task)
            if event_id:
                vault.update_google_event_id(task["path"], event_id)
                tasks_synced += 1
            else:
                errors += 1
        except Exception as e:
            logger.error(f"Error syncing task: {e}")
            errors += 1

    return {
        "habits_synced": habits_synced,
        "tasks_synced": tasks_synced,
        "errors": errors,
    }
