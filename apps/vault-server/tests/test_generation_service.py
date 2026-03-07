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

    def test_build_prompt_returns_override_when_set(self, gen_service):
        request = GenerationRequest(
            type="micro_icon",
            event_name="Gym",
            style=StyleConfig(),
            prompt_override="custom prompt text",
        )
        prompt = gen_service.build_prompt(request)
        assert prompt == "custom prompt text"

    def test_build_prompt_ignores_empty_override(self, gen_service):
        request = GenerationRequest(
            type="micro_icon",
            event_name="Gym workout",
            style=StyleConfig(line_style="clean_vector"),
            prompt_override="",
        )
        prompt = gen_service.build_prompt(request)
        assert "icon" in prompt.lower()

    @pytest.mark.asyncio
    async def test_generate_uses_custom_dimensions(self, gen_service):
        request = GenerationRequest(
            type="micro_icon",
            event_name="Gym",
            style=StyleConfig(),
            width=512,
            height=768,
        )

        mock_client = _mock_httpx_client(["https://replicate.delivery/output.png"])

        with patch("src.services.generation_service.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            await gen_service.generate(request)

        call_json = mock_client.post.call_args[1]["json"]
        assert call_json["input"]["width"] == 512
        assert call_json["input"]["height"] == 768

    def test_clamp_dimension(self, gen_service):
        assert gen_service._clamp_dimension(100) == 128    # rounds up to nearest 64
        assert gen_service._clamp_dimension(1200) == 1024  # caps at 1024
        assert gen_service._clamp_dimension(768) == 768    # already valid
        assert gen_service._clamp_dimension(50) == 64      # minimum 64

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

    @pytest.mark.asyncio
    async def test_upload_file_returns_url(self, gen_service, tmp_path):
        test_file = tmp_path / "test.jpg"
        test_file.write_bytes(b"fake image data")

        upload_resp = MagicMock()
        upload_resp.json.return_value = {
            "urls": {"get": "https://replicate.delivery/files/test.jpg"},
        }
        upload_resp.raise_for_status = MagicMock()

        with patch("src.services.generation_service.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = upload_resp
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            url = await gen_service.upload_file(str(test_file))

        assert url == "https://replicate.delivery/files/test.jpg"
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_passes_image_and_prompt_strength(self, gen_service):
        request = GenerationRequest(
            type="keyframe_scene",
            event_name="Cafe",
            style=StyleConfig(),
            reference_image="/tmp/ref.jpg",
            prompt_strength=0.7,
        )

        mock_client = _mock_httpx_client(["https://replicate.delivery/output.png"])

        with patch("src.services.generation_service.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch.object(gen_service, "upload_file", return_value="https://replicate.delivery/ref.jpg"):
                await gen_service.generate(request)

        call_json = mock_client.post.call_args[1]["json"]
        assert call_json["input"]["image"] == "https://replicate.delivery/ref.jpg"
        assert call_json["input"]["prompt_strength"] == 0.7

    @pytest.mark.asyncio
    async def test_generate_without_reference_has_no_image_input(self, gen_service):
        request = GenerationRequest(
            type="micro_icon",
            event_name="Gym",
            style=StyleConfig(),
        )

        mock_client = _mock_httpx_client(["https://replicate.delivery/output.png"])

        with patch("src.services.generation_service.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            await gen_service.generate(request)

        call_json = mock_client.post.call_args[1]["json"]
        assert "image" not in call_json["input"]
        assert "prompt_strength" not in call_json["input"]
