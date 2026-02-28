"""Goal API routes."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from src.main import get_vault
from src.auth import verify_api_key
from src.api.routes import item_name

router = APIRouter(prefix="/goals", tags=["goals"], dependencies=[Depends(verify_api_key)])


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
