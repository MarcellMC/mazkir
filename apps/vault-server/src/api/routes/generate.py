import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from src.auth import verify_api_key
from src.main import get_generation

router = APIRouter(
    prefix="/generate", tags=["generate"], dependencies=[Depends(verify_api_key)]
)


class GenerateRequest(BaseModel):
    type: str  # 'micro_icon' | 'keyframe_scene' | 'route_sketch' | 'full_day_map'
    event_name: str = ""
    activity_category: str | None = None
    location_name: str | None = None
    style: dict[str, Any] | None = None
    approach: str = "ai_raster"
    reference_images: list[str] | None = None
    prompt_override: str | None = None
    width: int | None = None
    height: int | None = None
    reference_image: str | None = None
    prompt_strength: float | None = None
    params: dict[str, Any] | None = None


@router.post("")
async def generate_image(request: GenerateRequest):
    gen = get_generation()
    if not gen:
        raise HTTPException(status_code=503, detail="Generation service not available (no REPLICATE_API_TOKEN)")

    from src.config import settings
    from src.services.generation_service import GenerationRequest, StyleConfig

    # Resolve reference_image path — event photos store paths like
    # "attachments/photo.jpg" but actual files are in data/media/{date}/
    reference_image = request.reference_image
    if reference_image and not Path(reference_image).is_file():
        filename = Path(reference_image).name
        # Search media_path for the file
        matches = list(settings.media_path.rglob(filename))
        if matches:
            reference_image = str(matches[0])

    style = StyleConfig(**(request.style or {}))
    gen_request = GenerationRequest(
        type=request.type,
        event_name=request.event_name,
        activity_category=request.activity_category,
        location_name=request.location_name,
        style=style,
        approach=request.approach,
        reference_images=request.reference_images,
        prompt_override=request.prompt_override,
        width=request.width,
        height=request.height,
        reference_image=reference_image,
        prompt_strength=request.prompt_strength,
        params=request.params,
    )

    result = await gen.generate(gen_request)
    return result


@router.post("/upload")
async def upload_reference_image(file: UploadFile = File(...)):
    """Upload a reference image, save to temp location, return path."""
    if not file.filename:
        raise HTTPException(400, "No filename provided")

    suffix = Path(file.filename).suffix or ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix="ref_") as tmp:
        shutil.copyfileobj(file.file, tmp)
        return {"path": tmp.name}
