from fastapi import APIRouter, Depends, HTTPException, Query

from src.auth import verify_api_key
from src.main import get_imagery

router = APIRouter(
    prefix="/imagery", tags=["imagery"], dependencies=[Depends(verify_api_key)]
)


@router.get("/search")
async def search_imagery(
    lat: float = Query(..., description="Latitude"),
    lng: float = Query(..., description="Longitude"),
    radius: int = Query(500, description="Search radius in meters"),
    limit: int = Query(5, description="Max results"),
):
    imagery = get_imagery()
    if not imagery:
        raise HTTPException(status_code=503, detail="Imagery service not available")

    results = await imagery.search_all(lat, lng, radius=radius, limit=limit)
    return {"results": results}
