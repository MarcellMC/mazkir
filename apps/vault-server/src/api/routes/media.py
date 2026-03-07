"""Serve media files from data/media/ directory."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from src.config import settings

router = APIRouter(prefix="/media", tags=["media"])


@router.get("/{date}/{filename}")
async def get_media_file(date: str, filename: str):
    """Serve a photo file from data/media/{date}/{filename}."""
    file_path = settings.media_path / date / filename
    if not file_path.is_file():
        raise HTTPException(404, f"File not found: {date}/{filename}")
    if not file_path.resolve().is_relative_to(settings.media_path.resolve()):
        raise HTTPException(403, "Access denied")
    return FileResponse(file_path)
