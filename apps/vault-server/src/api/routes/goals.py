"""Goal API routes."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from src.main import get_vault
from src.auth import verify_api_key
from src.api.routes import item_name

router = APIRouter(prefix="/goals", tags=["goals"], dependencies=[Depends(verify_api_key)])


def find_goal_by_slug(vault, slug: str) -> dict | None:
    """Resolve a goal by filename slug — exact stem match, then unique prefix.

    Prefix matching supports slugs truncated to fit Telegram's 64-byte
    callback_data limit.
    """
    goals = vault.list_active_goals()
    for goal in goals:
        if Path(goal["path"]).stem == slug:
            return goal
    prefixed = [g for g in goals if Path(g["path"]).stem.startswith(slug)]
    if len(prefixed) == 1:
        return prefixed[0]
    return None


class GoalCreate(BaseModel):
    name: str
    priority: str = "medium"
    target_date: str | None = None
    category: str = "personal"


@router.get("")
async def list_goals():
    vault = get_vault()
    goals = vault.list_active_goals()
    return [
        {
            "name": item_name(g),
            "status": g["metadata"].get("status", "unknown"),
            "priority": g["metadata"].get("priority", "medium"),
            "progress": g["metadata"].get("progress", 0),
            "target_date": g["metadata"].get("target_date"),
            "milestones": g["metadata"].get("milestones", []),
            "path": g["path"],
        }
        for g in goals
    ]


@router.get("/{slug}")
async def get_goal(slug: str):
    """Full goal detail by filename slug (truncated prefixes accepted)."""
    vault = get_vault()
    goal = find_goal_by_slug(vault, slug)
    if not goal:
        raise HTTPException(404, f"Goal not found: {slug}")

    meta = goal["metadata"]
    return {
        "name": item_name(goal),
        "slug": Path(goal["path"]).stem,
        "status": meta.get("status", "unknown"),
        "priority": meta.get("priority", "medium"),
        "progress": meta.get("progress", 0),
        "target_date": meta.get("target_date"),
        "category": meta.get("category", "personal"),
        "milestones": meta.get("milestones", []),
        "created": meta.get("created"),
        "updated": meta.get("updated"),
        "path": goal["path"],
        "content": goal.get("content", ""),
    }


@router.post("", status_code=201)
async def create_goal(body: GoalCreate):
    vault = get_vault()
    result = vault.create_goal(
        name=body.name,
        priority=body.priority,
        target_date=body.target_date,
        category=body.category,
    )
    return {
        "name": result["metadata"]["name"],
        "priority": result["metadata"]["priority"],
        "target_date": result["metadata"].get("target_date"),
        "category": result["metadata"]["category"],
        "path": result["path"],
    }
