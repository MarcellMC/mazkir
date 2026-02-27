"""API key authentication."""
from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader
from src.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str | None = Security(api_key_header)):
    if not settings.api_key:
        return  # No auth configured, allow all
    if api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
