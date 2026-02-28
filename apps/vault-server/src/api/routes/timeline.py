from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from src.auth import verify_api_key
from src.main import get_timeline

router = APIRouter(
    prefix="/timeline", tags=["timeline"], dependencies=[Depends(verify_api_key)]
)


@router.get("/{target_date}")
async def get_timeline_data(target_date: date):
    timeline = get_timeline()
    if not timeline:
        raise HTTPException(status_code=503, detail="Timeline service not available")
    return timeline.get_day(target_date)
