"""One JSON record per trip: what the tracker saw and what Mazkir decided (plan Task 4).

`data/locations/trips/{id}.json`. Local only — a record holds the trip's
stop centres. The shape is fixed by `new_record`; every later step reads and
writes these keys.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import threading
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.services.location.model import Trip

TRIP_ID = re.compile(r"^[0-9a-f]{8}$")


def new_record(trip: Trip) -> dict[str, Any]:
    return {"id": trip.id, "trip": trip.to_dict(), "closed": False, "inbox": [],
            "purpose": None, "stops": {}, "trip_question": None,
            "blocks": {}, "merged": {}, "arrival_item": None, "confirmed": False}


def _logical_day(ts: dt.datetime, tz: str, boundary_hour: int) -> dt.date:
    return (ts.astimezone(ZoneInfo(tz)) - dt.timedelta(hours=boundary_hour)).date()


class TripRecords:
    def __init__(self, root: Path):
        self.dir = Path(root) / "trips"
        self._lock = threading.RLock()

    def _path(self, trip_id: str) -> Path | None:
        # The id builds a file path, and taps carry it from the bot.
        return self.dir / f"{trip_id}.json" if TRIP_ID.match(trip_id or "") else None

    def get(self, trip_id: str) -> dict[str, Any] | None:
        path = self._path(trip_id)
        if path is None or not path.exists():
            return None
        with self._lock:
            return json.loads(path.read_text(encoding="utf-8"))

    def save(self, rec: dict[str, Any]) -> None:
        path = self._path(rec["id"])
        if path is None:
            raise ValueError(f"not a trip id: {rec['id']!r}")
        with self._lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
            tmp.replace(path)

    def all(self) -> list[dict[str, Any]]:
        if not self.dir.exists():
            return []
        out = []
        for path in sorted(self.dir.glob("*.json")):
            try:
                out.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return out

    def open_ids(self) -> list[str]:
        return [r["id"] for r in self.all() if not r.get("closed")]

    def on_day(self, day: dt.date, tz: str) -> list[dict[str, Any]]:
        zone = ZoneInfo(tz)
        return [r for r in self.all()
                if dt.datetime.fromisoformat(r["trip"]["left_at"]).astimezone(zone).date() == day]

    def questions_on(self, day: dt.date, tz: str, boundary_hour: int) -> int:
        n = 0
        for rec in self.all():
            stamps = [s.get("asked_at") for s in (rec.get("stops") or {}).values()]
            stamps.append((rec.get("trip_question") or {}).get("asked_at"))
            n += sum(1 for s in stamps
                     if s and _logical_day(dt.datetime.fromisoformat(s), tz, boundary_hour) == day)
        return n
