"""Token API routes."""
from fastapi import APIRouter, Depends
from src.main import get_vault
from src.auth import verify_api_key

router = APIRouter(prefix="/tokens", tags=["tokens"], dependencies=[Depends(verify_api_key)])


@router.get("")
async def get_tokens():
    vault = get_vault()
    ledger = vault.read_token_ledger()
    meta = ledger["metadata"]
    return {
        "total": meta.get("total_tokens", 0),
        "today": meta.get("tokens_today", 0),
        "all_time": meta.get("all_time_tokens", 0),
    }
