"""HTTP client for vault-server API."""
import httpx
import logging

logger = logging.getLogger(__name__)


class VaultAPIClient:
    """Client for communicating with vault-server."""

    def __init__(self, base_url: str = "http://localhost:8000", api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.headers = {}
        if api_key:
            self.headers["X-API-Key"] = api_key
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.headers,
            timeout=30.0,
        )

    async def close(self):
        await self._client.aclose()

    # Daily
    async def get_daily(self) -> dict:
        r = await self._client.get("/daily")
        r.raise_for_status()
        return r.json()

    # Tasks
    async def list_tasks(self) -> list:
        r = await self._client.get("/tasks")
        r.raise_for_status()
        return r.json()

    async def create_task(self, **kwargs) -> dict:
        r = await self._client.post("/tasks", json=kwargs)
        r.raise_for_status()
        return r.json()

    async def complete_task(self, name: str) -> dict:
        r = await self._client.patch(f"/tasks/{name}", json={"completed": True})
        r.raise_for_status()
        return r.json()

    # Habits
    async def list_habits(self) -> list:
        r = await self._client.get("/habits")
        r.raise_for_status()
        return r.json()

    async def create_habit(self, **kwargs) -> dict:
        r = await self._client.post("/habits", json=kwargs)
        r.raise_for_status()
        return r.json()

    async def complete_habit(self, name: str) -> dict:
        r = await self._client.patch(f"/habits/{name}", json={"completed": True})
        r.raise_for_status()
        return r.json()

    # Goals
    async def list_goals(self) -> list:
        r = await self._client.get("/goals")
        r.raise_for_status()
        return r.json()

    async def create_goal(self, **kwargs) -> dict:
        r = await self._client.post("/goals", json=kwargs)
        r.raise_for_status()
        return r.json()

    # Tokens
    async def get_tokens(self) -> dict:
        r = await self._client.get("/tokens")
        r.raise_for_status()
        return r.json()

    # Calendar
    async def get_calendar_events(self) -> list:
        r = await self._client.get("/calendar/events")
        r.raise_for_status()
        return r.json()

    async def sync_calendar(self) -> dict:
        r = await self._client.post("/calendar/sync")
        r.raise_for_status()
        return r.json()

    # Message (NL)
    async def send_message(self, text: str, chat_id: int = 0) -> dict:
        """Send a natural language message to the agent loop."""
        r = await self._client.post(
            "/message", json={"text": text, "chat_id": chat_id},
        )
        r.raise_for_status()
        return r.json()

    async def send_confirmation(
        self, chat_id: int, action_id: str, response: str,
    ) -> dict:
        """Send a confirmation response for a pending action."""
        r = await self._client.post(
            "/message/confirm",
            json={"chat_id": chat_id, "action_id": action_id, "response": response},
        )
        r.raise_for_status()
        return r.json()
