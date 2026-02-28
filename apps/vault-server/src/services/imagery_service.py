"""Search open-source imagery APIs for contextual photos by location."""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"


class ImageryService:
    def __init__(self):
        self._client = httpx.AsyncClient(timeout=10.0)

    async def search_all(
        self, lat: float, lng: float, radius: int = 500, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Search all imagery sources and combine results."""
        results = await self.search_wikimedia(lat, lng, radius=radius, limit=limit)
        return results

    async def search_wikimedia(
        self, lat: float, lng: float, radius: int = 500, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Search Wikimedia Commons for geotagged images near a point."""
        try:
            data = await self._fetch_json(WIKIMEDIA_API, params={
                "action": "query",
                "list": "geosearch",
                "gscoord": f"{lat}|{lng}",
                "gsradius": str(min(radius, 10000)),
                "gslimit": str(limit),
                "gsnamespace": "6",  # File namespace
                "format": "json",
            })

            results = []
            for item in data.get("query", {}).get("geosearch", []):
                title = item.get("title", "")
                results.append({
                    "title": title,
                    "page_id": item.get("pageid"),
                    "lat": item.get("lat"),
                    "lng": item.get("lon"),
                    "distance_meters": item.get("dist"),
                    "thumbnail_url": self._wikimedia_thumb_url(title),
                    "source": "wikimedia",
                })

            return results

        except Exception as e:
            logger.warning(f"Wikimedia search failed: {e}")
            return []

    async def _fetch_json(self, url: str, params: dict | None = None) -> dict:
        """Fetch JSON from a URL."""
        response = await self._client.get(url, params=params)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _wikimedia_thumb_url(title: str, width: int = 300) -> str:
        """Generate a Wikimedia Commons thumbnail URL from a file title."""
        filename = title.replace("File:", "").replace(" ", "_")
        return f"https://commons.wikimedia.org/wiki/Special:FilePath/{filename}?width={width}"

    async def close(self):
        await self._client.aclose()
