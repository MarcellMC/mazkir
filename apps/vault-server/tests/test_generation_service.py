from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest

from src.services.generation_service import GenerationService, GenerationRequest, StyleConfig


@pytest.fixture
def gen_service():
    return GenerationService(api_token="test-token")


def _mock_httpx_client(prediction_output):
    """Create a mock httpx.AsyncClient that simulates Replicate API responses."""
    mock_client = AsyncMock()

    # POST /predictions → created prediction
    create_resp = MagicMock()
    create_resp.json.return_value = {
        "id": "pred123",
        "status": "succeeded",
        "output": prediction_output,
    }
    create_resp.raise_for_status = MagicMock()
    mock_client.post.return_value = create_resp

    return mock_client


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
    async def test_generate_calls_replicate_api(self, gen_service):
        request = GenerationRequest(
            type="micro_icon",
            event_name="Gym",
            style=StyleConfig(),
        )

        mock_client = _mock_httpx_client(["https://replicate.delivery/output.png"])

        with patch("src.services.generation_service.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await gen_service.generate(request)

        assert result["image_url"] == "https://replicate.delivery/output.png"
        assert result["approach"] == "ai_raster"
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_returns_error_on_failure(self, gen_service):
        request = GenerationRequest(
            type="micro_icon",
            event_name="Gym",
            style=StyleConfig(),
        )

        with patch("src.services.generation_service.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.side_effect = Exception("API error")
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await gen_service.generate(request)

        assert "error" in result
