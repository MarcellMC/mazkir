"""Token API routes."""
from datetime import datetime
from fastapi import APIRouter, Depends
import pytz
from src.main import get_vault
from src.auth import verify_api_key
from src.config import settings

router = APIRouter(prefix="/tokens", tags=["tokens"], dependencies=[Depends(verify_api_key)])

tz = pytz.timezone(settings.vault_timezone)


@router.get("")
async def get_tokens():
    vault = get_vault()
    ledger = vault.read_token_ledger()
    meta = ledger["metadata"]

    # Reset tokens_today if ledger wasn't updated today
    today = datetime.now(tz).strftime("%Y-%m-%d")
    last_updated = str(meta.get("updated", ""))
    tokens_today = meta.get("tokens_today", 0) if last_updated == today else 0

    return {
        "total": meta.get("total_tokens", 0),
        "today": tokens_today,
        "all_time": meta.get("all_time_tokens", 0),
    }
