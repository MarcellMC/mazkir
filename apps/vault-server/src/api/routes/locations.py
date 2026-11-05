"""Raw location points from the bot (location spike L0, spec §4.3).

The bot posts every live-location update, the message that starts a live
share, and every one-off check-in here. This route only appends them to
`data/locations/raw/{date}.jsonl`: no visits, no blocks, no model calls.

Coordinates never go to a span or a log line. The `location.ingest` span
carries only the kind, the accuracy and the gap since the previous point.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from src.auth import verify_api_key
from src.config import settings
from src.services.location_store import append_point
from src.services.tracing_helpers import with_span_status
from src.tracing_setup import get_tracer

router = APIRouter(prefix="/locations", tags=["locations"], dependencies=[Depends(verify_api_key)])


class LocationPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(pattern=r"^[a-z_]{1,32}$")
    kind: Literal["live", "live_start", "check_in"]
    message_id: int | None = None
    ts: AwareDatetime
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(None, ge=0)
    heading: int | None = None
    live_period: int | None = None
    venue_title: str | None = Field(None, max_length=200)


# Plain `def`: FastAPI runs it in the threadpool, so the file lock is never
# held on the event loop.
@router.post("/points")
def ingest_point(point: LocationPoint) -> dict:
    if settings.location_ingest != "log":
        raise HTTPException(404, "Location ingest is off")
    tz = settings.vault_timezone
    # exclude_none: the raw file records what Telegram sent, and an absent
    # field must stay absent — the report reads which fields a share's last
    # update carried to learn how a share ends (spec §2.2 item 3).
    record = {**point.model_dump(exclude_none=True), "received_at": dt.datetime.now(ZoneInfo(tz)).isoformat()}
    with get_tracer().start_as_current_span("location.ingest") as span:
        with with_span_status(span):
            gap = append_point(settings.location_data_path, record, tz)
            span.set_attribute("location.kind", point.kind)
            span.set_attribute("location.accuracy_m", point.accuracy_m if point.accuracy_m is not None else -1)
            span.set_attribute("location.gap_s", gap if gap is not None else -1)
    return {"ok": True}
