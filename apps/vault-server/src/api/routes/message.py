"""Natural language message API route."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import pytz
from src.main import get_vault, get_claude, get_calendar
from src.auth import verify_api_key
from src.config import settings
from src.api.routes import item_name

router = APIRouter(tags=["message"], dependencies=[Depends(verify_api_key)])

tz = pytz.timezone(settings.vault_timezone)


class MessageRequest(BaseModel):
    text: str


@router.post("/message")
async def handle_message(body: MessageRequest):
    vault = get_vault()
    claude = get_claude()
    calendar = get_calendar()

    if not claude:
        raise HTTPException(503, "Claude service not configured")

    # Get context for intent parsing
    habits = vault.list_active_habits()
    habit_names = [item_name(h) for h in habits]
    tasks = vault.list_active_tasks()
    task_names = [item_name(t) for t in tasks]

    # Parse intent
    intent_result = claude.parse_intent(body.text, habit_names, task_names)
    intent = intent_result.get("intent")
    data = intent_result.get("data", {})

    # Route to handler
    if intent == "HABIT_COMPLETION":
        return await _handle_habit_completion(data, vault, calendar)
    elif intent == "HABIT_CREATION":
        return await _handle_habit_creation(data, vault, calendar)
    elif intent == "TASK_CREATION":
        return await _handle_task_creation(data, vault, calendar)
    elif intent == "TASK_COMPLETION":
        return await _handle_task_completion(data, vault, calendar)
    elif intent == "GOAL_CREATION":
        return await _handle_goal_creation(data, vault)
    elif intent == "QUERY":
        return _handle_query(data, body.text, vault, claude)
    else:
        response = claude.chat(body.text)
        return {"intent": "GENERAL_CHAT", "response": response}


async def _handle_habit_completion(data, vault, calendar):
    habit_name = data.get("habit_name", "").lower()
    if not habit_name:
        return {"intent": "HABIT_COMPLETION", "error": "No habit name identified"}

    habits = vault.list_active_habits()
    matched = None
    for h in habits:
        h_name = h["metadata"].get("name", "").lower()
        if habit_name in h_name or h_name in habit_name:
            matched = h
            break

    if not matched:
        available = [h["metadata"].get("name") for h in habits]
        return {"intent": "HABIT_COMPLETION", "error": f"Not found: {habit_name}", "available": available}

    meta = matched["metadata"]
    today = datetime.now(tz).strftime("%Y-%m-%d")

    if meta.get("last_completed") == today:
        return {"intent": "HABIT_COMPLETION", "already_completed": True, "name": meta["name"], "streak": meta.get("streak", 0)}

    new_streak = meta.get("streak", 0) + 1
    tokens_per = meta.get("tokens_per_completion", 5)

    vault.update_file(matched["path"], {
        "streak": new_streak,
        "last_completed": today,
        "longest_streak": max(meta.get("longest_streak", 0), new_streak),
    })

    token_result = vault.update_tokens(tokens_per, f"Completed {meta['name']}")

    google_event_id = meta.get("google_event_id")
    if calendar and calendar.is_initialized and google_event_id:
        try:
            await calendar.mark_event_complete(google_event_id, today)
        except Exception:
            pass

    return {
        "intent": "HABIT_COMPLETION",
        "name": meta["name"],
        "old_streak": new_streak - 1,
        "new_streak": new_streak,
        "tokens_earned": tokens_per,
        "new_token_total": token_result["new_total"],
    }


async def _handle_habit_creation(data, vault, calendar):
    name = data.get("habit_name", "").strip()
    if not name:
        return {"intent": "HABIT_CREATION", "error": "No habit name"}

    result = vault.create_habit(
        name=name,
        frequency=data.get("frequency", "daily"),
        category=data.get("category", "personal"),
    )

    if calendar and calendar.is_initialized:
        try:
            event_id = await calendar.sync_habit(result)
            if event_id:
                vault.update_google_event_id(result["path"], event_id)
        except Exception:
            pass

    return {
        "intent": "HABIT_CREATION",
        "name": name,
        "frequency": data.get("frequency", "daily"),
        "path": result["path"],
    }


async def _handle_task_creation(data, vault, calendar):
    name = (data.get("task_name") or data.get("task_description", "")).strip()
    if not name:
        return {"intent": "TASK_CREATION", "error": "No task name"}

    priority = data.get("priority", 3)
    due_date = data.get("due_date")
    category = data.get("category", "personal")

    result = vault.create_task(
        name=name,
        priority=priority,
        due_date=due_date,
        category=category,
        tokens_on_completion=5 if priority <= 2 else 10 if priority <= 3 else 15,
    )

    if calendar and calendar.is_initialized and due_date:
        try:
            event_id = await calendar.sync_task(result)
            if event_id:
                vault.update_google_event_id(result["path"], event_id)
        except Exception:
            pass

    return {
        "intent": "TASK_CREATION",
        "name": name,
        "priority": priority,
        "due_date": due_date,
        "path": result["path"],
    }


async def _handle_task_completion(data, vault, calendar):
    task_name = data.get("task_name", "").strip()
    if not task_name:
        return {"intent": "TASK_COMPLETION", "error": "No task name"}

    task = vault.find_task_by_name(task_name)
    if not task:
        tasks = vault.list_active_tasks()
        names = [item_name(t) for t in tasks[:5]]
        return {"intent": "TASK_COMPLETION", "error": f"Not found: {task_name}", "available": names}

    google_event_id = task["metadata"].get("google_event_id")
    result = vault.complete_task(task["path"])

    if calendar and calendar.is_initialized and google_event_id:
        try:
            await calendar.mark_event_complete(google_event_id)
        except Exception:
            pass

    return {
        "intent": "TASK_COMPLETION",
        "task_name": result["task_name"],
        "tokens_earned": result["tokens_earned"],
    }


async def _handle_goal_creation(data, vault):
    name = data.get("goal_name", "").strip()
    if not name:
        return {"intent": "GOAL_CREATION", "error": "No goal name"}

    result = vault.create_goal(
        name=name,
        priority=data.get("priority", "medium"),
        target_date=data.get("target_date"),
        category=data.get("category", "personal"),
    )

    return {
        "intent": "GOAL_CREATION",
        "name": name,
        "priority": data.get("priority", "medium"),
        "path": result["path"],
    }


def _handle_query(data, original_message, vault, claude):
    query_type = data.get("query_type", "general")

    if query_type == "streaks":
        habits = vault.list_active_habits()
        habits.sort(key=lambda h: h["metadata"].get("streak", 0), reverse=True)
        return {
            "intent": "QUERY",
            "query_type": "streaks",
            "data": [
                {"name": h["metadata"].get("name"), "streak": h["metadata"].get("streak", 0), "longest": h["metadata"].get("longest_streak", 0)}
                for h in habits[:10]
            ],
        }
    elif query_type == "tokens":
        ledger = vault.read_token_ledger()
        meta = ledger["metadata"]
        return {
            "intent": "QUERY",
            "query_type": "tokens",
            "data": {"total": meta.get("total_tokens", 0), "today": meta.get("tokens_today", 0), "all_time": meta.get("all_time_tokens", 0)},
        }
    else:
        response = claude.chat(original_message)
        return {"intent": "QUERY", "query_type": "general", "response": response}
