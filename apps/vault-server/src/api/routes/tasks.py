"""Task API routes."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from src.main import get_vault, get_calendar
from src.auth import verify_api_key
from src.api.routes import item_name

router = APIRouter(prefix="/tasks", tags=["tasks"], dependencies=[Depends(verify_api_key)])


class TaskCreate(BaseModel):
    name: str
    priority: int = 3
    due_date: str | None = None
    category: str = "personal"
    tokens_on_completion: int = 5


class TaskComplete(BaseModel):
    completed: bool = True


def find_task_by_slug(vault, slug: str) -> dict | None:
    """Resolve a task by filename slug — exact stem match, then unique prefix.

    Prefix matching supports slugs truncated to fit Telegram's 64-byte
    callback_data limit.
    """
    tasks = vault.list_active_tasks()
    for task in tasks:
        if Path(task["path"]).stem == slug:
            return task
    prefixed = [t for t in tasks if Path(t["path"]).stem.startswith(slug)]
    if len(prefixed) == 1:
        return prefixed[0]
    return None


@router.get("")
async def list_tasks():
    vault = get_vault()
    tasks = vault.list_active_tasks()
    return [
        {
            "name": item_name(t),
            "priority": t["metadata"].get("priority", 3),
            "due_date": t["metadata"].get("due_date"),
            "category": t["metadata"].get("category", "personal"),
            "status": t["metadata"].get("status", "active"),
            "google_event_id": t["metadata"].get("google_event_id"),
            "path": t["path"],
        }
        for t in tasks
    ]


@router.post("", status_code=201)
async def create_task(body: TaskCreate):
    vault = get_vault()
    calendar = get_calendar()

    result = vault.create_task(
        name=body.name,
        priority=body.priority,
        due_date=body.due_date,
        category=body.category,
        tokens_on_completion=body.tokens_on_completion,
    )

    # Sync to calendar if enabled and task has due date
    if calendar and calendar.is_initialized and body.due_date:
        try:
            event_id = await calendar.sync_task(result)
            if event_id:
                vault.update_google_event_id(result["path"], event_id)
                result["metadata"]["google_event_id"] = event_id
        except Exception:
            pass  # Calendar sync is best-effort

    return {
        "name": result["metadata"]["name"],
        "priority": result["metadata"]["priority"],
        "due_date": result["metadata"].get("due_date"),
        "category": result["metadata"]["category"],
        "tokens_on_completion": result["metadata"].get("tokens_on_completion", 5),
        "path": result["path"],
        "google_event_id": result["metadata"].get("google_event_id"),
    }


@router.get("/{slug}")
async def get_task(slug: str):
    """Full task detail by filename slug (truncated prefixes accepted)."""
    vault = get_vault()
    task = find_task_by_slug(vault, slug)
    if not task:
        raise HTTPException(404, f"Task not found: {slug}")

    meta = task["metadata"]
    return {
        "name": item_name(task),
        "slug": Path(task["path"]).stem,
        "status": meta.get("status", "active"),
        "priority": meta.get("priority", 3),
        "due_date": meta.get("due_date"),
        "category": meta.get("category", "personal"),
        "tokens_on_completion": meta.get("tokens_on_completion"),
        "created": meta.get("created"),
        "updated": meta.get("updated"),
        "google_event_id": meta.get("google_event_id"),
        "path": task["path"],
        "content": task.get("content", ""),
    }


@router.patch("/{name}")
async def complete_task(name: str, body: TaskComplete):
    vault = get_vault()
    calendar = get_calendar()

    if not body.completed:
        raise HTTPException(400, "Only completion is supported via PATCH")

    # Accept either a filename slug (from inline keyboards) or a task name
    task = find_task_by_slug(vault, name) or vault.find_task_by_name(name)
    if not task:
        raise HTTPException(404, f"Task not found: {name}")

    google_event_id = task["metadata"].get("google_event_id")
    result = vault.complete_task(task["path"])

    # Mark calendar event complete
    if calendar and calendar.is_initialized and google_event_id:
        try:
            await calendar.mark_event_complete(google_event_id)
        except Exception:
            pass

    return {
        "task_name": result["task_name"],
        "tokens_earned": result["tokens_earned"],
        "archive_path": result["archive_path"],
    }
