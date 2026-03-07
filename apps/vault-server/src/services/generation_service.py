"""Image generation service using Replicate API (direct httpx, no replicate client)."""

import asyncio
import logging
import time
from typing import Any

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

REPLICATE_API_BASE = "https://api.replicate.com/v1"

# Default Replicate models per generation type
DEFAULT_MODELS = {
    "micro_icon": "stability-ai/sdxl:39ed52f2a78e934b3ba6e2a89f5b1c712de7dfea535525255b1aa35c5565e08b",
    "keyframe_scene": "stability-ai/sdxl:39ed52f2a78e934b3ba6e2a89f5b1c712de7dfea535525255b1aa35c5565e08b",
    "route_sketch": "stability-ai/sdxl:39ed52f2a78e934b3ba6e2a89f5b1c712de7dfea535525255b1aa35c5565e08b",
    "full_day_map": "stability-ai/sdxl:39ed52f2a78e934b3ba6e2a89f5b1c712de7dfea535525255b1aa35c5565e08b",
}


class StyleConfig(BaseModel):
    preset: str | None = None
    palette: list[str] | None = None
    line_style: str = "clean_vector"
    texture: str = "clean"
    art_reference: str | None = None


class GenerationRequest(BaseModel):
    type: str  # 'micro_icon' | 'keyframe_scene' | 'route_sketch' | 'full_day_map'
    event_name: str = ""
    activity_category: str | None = None
    location_name: str | None = None
    style: StyleConfig = StyleConfig()
    approach: str = "ai_raster"
    reference_images: list[str] | None = None
    prompt_override: str | None = None
    width: int | None = None
    height: int | None = None
    reference_image: str | None = None
    prompt_strength: float | None = None
    params: dict[str, Any] | None = None


class GenerationService:
    def __init__(self, api_token: str):
        self.api_token = api_token

    async def upload_file(self, file_path: str) -> str:
        """Upload a local file to Replicate's file hosting, return the serving URL."""
        from pathlib import Path

        file_data = Path(file_path).read_bytes()
        file_name = Path(file_path).name

        headers = {
            "Authorization": f"Bearer {self.api_token}",
        }

        async with httpx.AsyncClient(base_url=REPLICATE_API_BASE, headers=headers, timeout=60) as client:
            resp = await client.post(
                "/files",
                files={"content": (file_name, file_data, "application/octet-stream")},
            )
            resp.raise_for_status()
            data = resp.json()

        return data["urls"]["get"]

    async def generate(self, request: GenerationRequest) -> dict[str, Any]:
        """Generate an image using Replicate HTTP API directly."""
        start = time.time()
        prompt = self.build_prompt(request)
        model = DEFAULT_MODELS.get(request.type, DEFAULT_MODELS["micro_icon"])

        try:
            # Parse model ref: "owner/name:version"
            model_base, version_id = model.split(":", 1)

            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
            }

            async with httpx.AsyncClient(base_url=REPLICATE_API_BASE, headers=headers, timeout=120) as client:
                # Create prediction
                width = self._clamp_dimension(request.width) if request.width else self._get_width(request.type)
                height = self._clamp_dimension(request.height) if request.height else self._get_height(request.type)

                prediction_input: dict[str, Any] = {
                    "prompt": prompt,
                    "width": width,
                    "height": height,
                    "num_outputs": 1,
                }

                if request.reference_image:
                    image_url = await self.upload_file(request.reference_image)
                    prediction_input["image"] = image_url
                    prediction_input["prompt_strength"] = request.prompt_strength or 0.7

                resp = await client.post("/predictions", json={
                    "version": version_id,
                    "input": prediction_input,
                })
                resp.raise_for_status()
                prediction = resp.json()

                # Poll until completed or failed
                while prediction["status"] not in ("succeeded", "failed", "canceled"):
                    await asyncio.sleep(1)
                    poll = await client.get(f"/predictions/{prediction['id']}")
                    poll.raise_for_status()
                    prediction = poll.json()

                if prediction["status"] != "succeeded":
                    error = prediction.get("error", "Generation failed")
                    raise RuntimeError(error)

                output = prediction["output"]

            image_url = output[0] if isinstance(output, list) else str(output)
            elapsed = int((time.time() - start) * 1000)

            return {
                "image_url": image_url,
                "format": "png",
                "approach": request.approach,
                "model": model_base,
                "prompt": prompt,
                "generation_time_ms": elapsed,
                "params": request.params or {},
            }

        except Exception as e:
            logger.error(f"Generation failed: {e}")
            return {
                "error": str(e),
                "prompt": prompt,
                "approach": request.approach,
            }

    def build_prompt(self, request: GenerationRequest) -> str:
        """Build a generation prompt based on request type and style."""
        if request.prompt_override:
            return request.prompt_override

        parts = []

        if request.type == "micro_icon":
            parts.append(f"Minimal vector icon of {request.event_name}")
            if request.activity_category:
                parts.append(f"representing {request.activity_category} activity")
            parts.append("simple, clean, flat design, single color")

        elif request.type == "route_sketch":
            parts.append(f"Hand-drawn route sketch map for {request.event_name}")
            if request.location_name:
                parts.append(f"in {request.location_name}")
            parts.append("illustrated path, minimalist")

        elif request.type == "keyframe_scene":
            parts.append(f"Illustrated scene card for {request.event_name}")
            if request.location_name:
                parts.append(f"at {request.location_name}")
            parts.append("atmospheric, detailed, warm lighting")

        elif request.type == "full_day_map":
            parts.append("Illustrated day journey map showing connected stops")
            parts.append("bird's eye view, illustrated style")

        # Apply style
        style = request.style
        if style.preset == "tel-aviv":
            parts.append("Tel Aviv Mediterranean style, warm tones, Bauhaus architecture")
        if style.line_style:
            line_desc = {
                "loose_ink": "loose ink drawing style",
                "clean_vector": "clean vector art",
                "crosshatch": "crosshatch pen illustration",
                "watercolor_edge": "watercolor edges, soft blending",
            }.get(style.line_style, "")
            if line_desc:
                parts.append(line_desc)
        if style.texture and style.texture != "clean":
            parts.append(f"{style.texture.replace('_', ' ')} texture")
        if style.art_reference:
            parts.append(f"inspired by {style.art_reference}")

        return ", ".join(parts)

    @staticmethod
    def _get_width(gen_type: str) -> int:
        if gen_type == "micro_icon":
            return 256
        if gen_type == "route_sketch":
            return 512
        return 768

    @staticmethod
    def _get_height(gen_type: str) -> int:
        if gen_type == "micro_icon":
            return 256
        if gen_type == "route_sketch":
            return 512
        return 768

    @staticmethod
    def _clamp_dimension(value: int) -> int:
        """Clamp to multiple of 64, min 64, max 1024."""
        clamped = max(64, min(1024, value))
        return round(clamped / 64) * 64
