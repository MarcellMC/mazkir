"""Raw L0 points as tracker fixes (the live stream only; check-ins are separate)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from src.services.location.model import Fix
from src.services.location_report import normalise
from src.services.location_store import load_points

LIVE_KINDS = ("live", "live_start")


def point_to_fix(point: dict[str, Any]) -> Fix | None:
    """A stored or posted point as a Fix, or None when it is not part of a live share."""
    if point.get("kind") not in LIVE_KINDS:
        return None
    ts = point["ts"]
    if isinstance(ts, str):
        ts = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return Fix(ts, float(point["lat"]), float(point["lng"]), point.get("accuracy_m"))


def load_fixes(root: Path, first: dt.date, last: dt.date) -> list[Fix]:
    """Every live fix in the raw files from `first` to `last`, deduplicated and in time order."""
    lines: list[dict] = []
    day = first
    while day <= last:
        points, _ = load_points(root, day)
        lines.extend(points)
        day += dt.timedelta(days=1)
    return [Fix(p.ts, p.lat, p.lng, p.accuracy_m) for p in normalise(lines) if p.kind in LIVE_KINDS]
