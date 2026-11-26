"""How often you have stopped at this spot before: a usual stop or a new one.

Counted over trip records and rebuilt trips (`derived/`) from the last 30
days, one per trip. A usual stop is said so in the question and told to the
model, which can then guess what the place is; it is still asked about once,
since without a map Mazkir cannot know what is there.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path

from src.services.geo import haversine_m
from src.services.location.model import Stop

logger = logging.getLogger(__name__)

USUAL_VISITS = 2
VISIT_RADIUS_M = 50.0
WINDOW_DAYS = 30


def _trips(records, derived_dir: Path | None):
    from src.services.location.edits import trip_of

    for rec in records.all():
        if rec.get("trip") and not rec.get("joined_into"):       # a joined trip's stops are the other's now
            yield trip_of(rec).to_dict()           # with your edits: an added stop is a visit too
    if derived_dir is None or not Path(derived_dir).exists():
        return
    for path in sorted(Path(derived_dir).glob("*.json")):
        try:
            yield from json.loads(path.read_text(encoding="utf-8")).get("trips") or []
        except (OSError, ValueError):
            logger.warning("unreadable derived trips file %s", path.name)


def earlier_visits(stop: Stop, trip_id: str, left_at: dt.datetime, records, derived_dir: Path | None,
                   now: dt.datetime) -> int:
    since = now - dt.timedelta(days=WINDOW_DAYS)
    radius = max(VISIT_RADIUS_M, stop.spread_m or 0.0)
    seen: set[str] = set()
    for trip in _trips(records, derived_dir):
        try:
            started = dt.datetime.fromisoformat(trip["left_at"])
        except (KeyError, TypeError, ValueError):
            continue
        # The same trip can be both a record and a rebuilt one: one per start minute.
        key = started.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M")
        if trip.get("id") == trip_id or started >= left_at or started < since or key in seen:
            continue
        for s in trip.get("stops") or []:
            if s.get("lat") is None or s.get("lng") is None:
                continue
            if haversine_m(stop.lat, stop.lng, s["lat"], s["lng"]) <= radius:
                seen.add(key)
                break
    return len(seen)
