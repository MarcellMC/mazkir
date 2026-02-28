import sys
from types import ModuleType
from unittest.mock import AsyncMock, patch

import pytest

# Create a mock replicate module so the lazy import inside generate() works
_mock_replicate = ModuleType("replicate")
_mock_replicate.async_run = AsyncMock()  # type: ignore[attr-defined]
sys.modules["replicate"] = _mock_replicate

from src.services.generation_service import GenerationService, GenerationRequest, StyleConfig


@pytest.fixture
def gen_service():
    return GenerationService(api_token="test-token")


class TestGenerationService:
    def test_build_prompt_for_micro_icon(self, gen_service):
        request = GenerationRequest(
            type="micro_icon",
            event_name="Gym workout",
            activity_category="gym",
            style=StyleConfig(line_style="clean_vector"),
        )
        prompt = gen_service.build_prompt(request)
        assert "gym" in prompt.lower()
        assert "icon" in prompt.lower()

    def test_build_prompt_for_route_sketch(self, gen_service):
        request = GenerationRequest(
            type="route_sketch",
            event_name="Walk to park",
            activity_category="walk",
            style=StyleConfig(line_style="loose_ink"),
        )
        prompt = gen_service.build_prompt(request)
        assert "route" in prompt.lower() or "path" in prompt.lower()

    def test_build_prompt_for_keyframe_scene(self, gen_service):
        request = GenerationRequest(
            type="keyframe_scene",
            event_name="Café Xoho",
            location_name="Dizengoff Street, Tel Aviv",
            style=StyleConfig(preset="tel-aviv"),
        )
        prompt = gen_service.build_prompt(request)
        assert "tel aviv" in prompt.lower() or "café" in prompt.lower()

    @pytest.mark.asyncio
    async def test_generate_calls_replicate(self, gen_service):
        request = GenerationRequest(
            type="micro_icon",
            event_name="Gym",
            style=StyleConfig(),
        )

        mock_output = ["https://replicate.delivery/output.png"]
        with patch.object(_mock_replicate, "async_run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = mock_output
            result = await gen_service.generate(request)

        assert result["image_url"] == "https://replicate.delivery/output.png"
        assert result["approach"] == "ai_raster"

    @pytest.mark.asyncio
    async def test_generate_returns_error_on_failure(self, gen_service):
        request = GenerationRequest(
            type="micro_icon",
            event_name="Gym",
            style=StyleConfig(),
        )

        with patch.object(_mock_replicate, "async_run", new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = Exception("API error")
            result = await gen_service.generate(request)

        assert "error" in result
