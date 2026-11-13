"""Location points from the bot (L0 spike, then location awareness).

The bot posts every live-location update, the message that starts a live
share, and every one-off check-in here. Each is appended to
`data/locations/raw/{date}.jsonl` first (L0, spec 2026-11-05 §4.3).

With `LOCATION_AWARENESS=on` (spec 2026-11-10), the point then feeds the trip
tracker, and the response carries `notify[]`: messages for the bot to send,
each acknowledged with `POST /locations/outbox/{id}/ack`. Buttons on those
messages come back as `POST /locations/trips/{id}/tap`. With it off, the
response is exactly L0's.

Coordinates never go to a span or a log line. The `location.ingest` span
carries only the kind, the accuracy and the gap since the previous point.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from src.auth import verify_api_key
from src.config import settings
from src.services.location_store import append_point
from src.services.tracing_helpers import with_span_status
from src.tracing_setup import get_tracer

logger = logging.getLogger(__name__)

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
    # The chat the share is in: where a "sharing stopped" message goes.
    chat_id: int | None = None


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
    runtime = _runtime()
    if runtime is None:
        return {"ok": True}
    try:
        notify = runtime.feed(record)
    except Exception as exc:
        # The raw point is stored, so a rebuild recovers everything; ingest never fails on this.
        from src.services.location.model import safe_error
        logger.error("location awareness: feeding a point failed: %s", safe_error(exc))
        notify = []
    return {"ok": True, "notify": notify}


def _runtime():
    if settings.location_awareness != "on":
        return None
    from src.services.location.runtime import get_runtime
    return get_runtime()


def _runtime_or_404():
    runtime = _runtime()
    if runtime is None:
        raise HTTPException(404, "Location awareness is off")
    return runtime


_ID = r"^[0-9a-f]{8}$"


@router.post("/outbox/{item_id}/ack")
def ack_outbox(item_id: str = Path(pattern=_ID)) -> dict:
    return {"ok": _runtime_or_404().ack(item_id)}


class TapBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line: str = Field(pattern=r"^[a-z0-9]{1,6}$")
    action: str = Field(pattern=r"^(ok|no|p|t|a[0-2])$")


@router.post("/trips/{trip_id}/tap")
async def tap_trip(body: TapBody, trip_id: str = Path(pattern=_ID)) -> dict:
    """A button on a trip message (spec §6.2, §6.3).

    Answers are applied by the runtime. Approvals go through the day view's
    own `set_event_state`, so ✓ here does exactly what ✓ in /day does: the
    Google entry, the `## Schedule` line, and a habit tick.
    """
    runtime = _runtime_or_404()
    try:
        result = await asyncio.to_thread(runtime.tap, trip_id, body.line, body.action)
    except KeyError:
        raise HTTPException(404, "That trip is gone")
    from src.api.routes import events as events_route

    toast = result.get("toast")
    for day, event_id, state in result.get("approvals") or []:
        try:
            outcome = await events_route.set_event_state(
                dt.date.fromisoformat(day), event_id, events_route.SetStateBody(state=state))
        except HTTPException as exc:
            logger.warning("trip tap: %s on a block failed: %s", state, exc.detail)
            continue
        habit = (outcome or {}).get("habit")
        if habit:
            toast = f"✓ {habit['name']} · +{habit['tokens_earned']} tokens · streak {habit['new_streak']}"
    receipt = result.get("receipt")
    if result.get("rerender"):
        receipt = await asyncio.to_thread(runtime.render_arrival, trip_id)
    return {"receipt": receipt, "toast": toast, "open_question": result.get("open_question")}
