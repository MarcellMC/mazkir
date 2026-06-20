"""Notes API routes — feed for the time-management web app."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.auth import verify_api_key

router = APIRouter(prefix="/notes", tags=["notes"], dependencies=[Depends(verify_api_key)])


class CheckboxPatch(BaseModel):
    line: int
    checked: bool


def _svc():
    from src.main import get_notes
    return get_notes()


@router.get("")
async def list_notes():
    return {"notes": _svc().list_notes()}


@router.get("/featured")
async def featured_note():
    note = _svc().random_knowledge_note()
    if note is None:
        raise HTTPException(status_code=404, detail="no knowledge notes")
    return note


@router.get("/{note_id}")
async def get_note(note_id: str):
    try:
        return _svc().read_note(note_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="note not found")


@router.patch("/{note_id}/checkbox")
async def set_checkbox(note_id: str, patch: CheckboxPatch):
    try:
        return _svc().set_checkbox(note_id, patch.line, patch.checked)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="note not found")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
