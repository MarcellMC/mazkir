from unittest.mock import AsyncMock, patch

import pytest

from src.services.imagery_service import ImageryService


@pytest.fixture
def imagery_service():
    return ImageryService()


class TestImageryService:
    @pytest.mark.asyncio
    async def test_search_wikimedia_returns_images(self, imagery_service):
        """Wikimedia search returns image results with URL and metadata."""
        mock_response = {
            "query": {
                "geosearch": [
                    {
                        "pageid": 123,
                        "title": "File:Tel Aviv Beach.jpg",
                        "lat": 32.08,
                        "lon": 34.77,
                        "dist": 150.0,
                    }
                ]
            }
        }

        with patch.object(imagery_service, "_fetch_json", new_callable=AsyncMock) as mock:
            mock.return_value = mock_response
            results = await imagery_service.search_wikimedia(32.08, 34.77, radius=500)

        assert len(results) == 1
        assert results[0]["title"] == "File:Tel Aviv Beach.jpg"
        assert results[0]["source"] == "wikimedia"

    @pytest.mark.asyncio
    async def test_search_returns_empty_on_error(self, imagery_service):
        """Gracefully returns empty list on API error."""
        with patch.object(imagery_service, "_fetch_json", new_callable=AsyncMock) as mock:
            mock.side_effect = Exception("Network error")
            results = await imagery_service.search_wikimedia(32.08, 34.77)

        assert results == []

    @pytest.mark.asyncio
    async def test_search_all_combines_sources(self, imagery_service):
        """search_all combines Wikimedia results."""
        with patch.object(imagery_service, "search_wikimedia", new_callable=AsyncMock) as mock_wiki:
            mock_wiki.return_value = [{"title": "test.jpg", "source": "wikimedia"}]
            results = await imagery_service.search_all(32.08, 34.77)

        assert len(results) >= 1
