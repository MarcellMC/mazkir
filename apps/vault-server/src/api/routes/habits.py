"""Habit API routes."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import pytz
from src.main import get_vault, get_calendar
from src.auth import verify_api_key
from src.config import settings
from src.api.routes import item_name
from src.services import habit_completion
from src.services.habit_completion import (
    completions_today,
    daily_target_of,
    is_complete_today,
)

router = APIRouter(prefix="/habits", tags=["habits"], dependencies=[Depends(verify_api_key)])

tz = pytz.timezone(settings.vault_timezone)


class HabitCreate(BaseModel):
    name: str
    frequency: str = "daily"
    category: str = "personal"
    difficulty: str = "medium"
    tokens_per_completion: int = 5


class HabitComplete(BaseModel):
    completed: bool = True


@router.get("")
async def list_habits():
    vault = get_vault()
    habits = vault.list_active_habits()

    today = datetime.now(tz).date()

    # `completed_today` means the day's target is met, not "touched today":
    # `last_completed` is stamped on partial completions too, so a habit with
    # daily_target: 2 would otherwise read as done after one of two.
    return [
        {
            "name": item_name(h),
            "frequency": h["metadata"].get("frequency", "daily"),
            "streak": h["metadata"].get("streak", 0),
            "longest_streak": h["metadata"].get("longest_streak", 0),
            "last_completed": h["metadata"].get("last_completed"),
            "completed_today": is_complete_today(h, today),
            "completions_today": completions_today(h, today),
            "daily_target": daily_target_of(h["metadata"]),
            "tokens_per_completion": h["metadata"].get("tokens_per_completion", 5),
            "path": h["path"],
        }
        for h in sorted(
            habits, key=lambda h: h["metadata"].get("streak", 0), reverse=True
        )
    ]


@router.post("", status_code=201)
async def create_habit(body: HabitCreate):
    vault = get_vault()
    calendar = get_calendar()

    result = vault.create_habit(
        name=body.name,
        frequency=body.frequency,
        category=body.category,
        difficulty=body.difficulty,
        tokens_per_completion=body.tokens_per_completion,
    )

    # Sync to calendar
    if calendar and calendar.is_initialized:
        try:
            event_id = await calendar.sync_habit(result)
            if event_id:
                vault.update_google_event_id(result["path"], event_id)
                result["metadata"]["google_event_id"] = event_id
        except Exception:
            pass

    return {
        "name": result["metadata"]["name"],
        "frequency": result["metadata"]["frequency"],
        "category": result["metadata"]["category"],
        "path": result["path"],
        "google_event_id": result["metadata"].get("google_event_id"),
    }


@router.patch("/{name}")
async def complete_habit(name: str, body: HabitComplete):
    vault = get_vault()
    calendar = get_calendar()

    if not body.completed:
        raise HTTPException(400, "Only completion is supported via PATCH")

    # Find matching habit
    habits = vault.list_active_habits()
    matched = None
    for h in habits:
        h_name = h["metadata"].get("name", "").lower()
        if name.lower() in h_name or h_name in name.lower():
            matched = h
            break

    if not matched:
        available = [h["metadata"].get("name") for h in habits]
        raise HTTPException(404, f"Habit not found: {name}. Available: {available}")

    # One implementation, shared with the agent's complete_habit tool: counts
    # today's Completion Log entries, honours daily_target, backfills the
    # transition day, awards tokens on every completion and advances the
    # streak only when the target is met.
    result = habit_completion.complete_habit(vault, matched["path"])

    if result["already_completed"]:
        return {
            "already_completed": True,
            "name": result["name"],
            "streak": result["new_streak"],
            "completions_today": result["completions_today"],
            "daily_target": result["daily_target"],
        }

    # Mark calendar event complete — best effort, as on the agent path.
    google_event_id = result["google_event_id"]
    if calendar and calendar.is_initialized and google_event_id:
        try:
            await calendar.mark_event_complete(google_event_id, result["date"])
        except Exception:
            pass

    return {
        "already_completed": False,
        "name": result["name"],
        "old_streak": result["old_streak"],
        "new_streak": result["new_streak"],
        "tokens_earned": result["tokens_earned"],
        "new_token_total": result["new_token_total"],
        "completions_today": result["completions_today"],
        "daily_target": result["daily_target"],
        "target_met": result["target_met"],
    }
