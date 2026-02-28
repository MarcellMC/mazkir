"""Habit API routes."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import pytz
from src.main import get_vault, get_calendar
from src.auth import verify_api_key
from src.config import settings

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

    today = datetime.now(tz).strftime("%Y-%m-%d")

    return [
        {
            "name": h["metadata"].get("name", "Unknown"),
            "frequency": h["metadata"].get("frequency", "daily"),
            "streak": h["metadata"].get("streak", 0),
            "longest_streak": h["metadata"].get("longest_streak", 0),
            "last_completed": h["metadata"].get("last_completed"),
            "completed_today": h["metadata"].get("last_completed") == today,
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

    meta = matched["metadata"]
    today = datetime.now(tz).strftime("%Y-%m-%d")

    # Check already completed
    if meta.get("last_completed") == today:
        return {
            "already_completed": True,
            "name": meta["name"],
            "streak": meta.get("streak", 0),
        }

    # Update streak
    new_streak = meta.get("streak", 0) + 1
    tokens_per = meta.get("tokens_per_completion", 5)

    vault.update_file(matched["path"], {
        "streak": new_streak,
        "last_completed": today,
        "longest_streak": max(meta.get("longest_streak", 0), new_streak),
    })

    token_result = vault.update_tokens(tokens_per, f"Completed {meta['name']}")

    # Mark calendar event complete
    google_event_id = meta.get("google_event_id")
    if calendar and calendar.is_initialized and google_event_id:
        try:
            await calendar.mark_event_complete(google_event_id, today)
        except Exception:
            pass

    return {
        "already_completed": False,
        "name": meta["name"],
        "old_streak": new_streak - 1,
        "new_streak": new_streak,
        "tokens_earned": tokens_per,
        "new_token_total": token_result["new_total"],
    }
