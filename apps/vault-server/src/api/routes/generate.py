from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Any

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
    params: dict[str, Any] | None = None


@router.post("")
async def generate_image(request: GenerateRequest):
    gen = get_generation()
    if not gen:
        raise HTTPException(status_code=503, detail="Generation service not available (no REPLICATE_API_TOKEN)")

    from src.services.generation_service import GenerationRequest, StyleConfig

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
        params=request.params,
    )

    result = await gen.generate(gen_request)
    return result
