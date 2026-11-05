"""Raw location points, one JSON line each, one file per local calendar day.

Location spike (L0), `docs/specs/2026-11-05-location-check-in-design.md` §4.3.
Nothing here interprets a point: the raw file is the record, and everything
derived later (visits, places, reminders) can be rebuilt from it.

The file's date is the point's own `ts` in `VAULT_TIMEZONE`, by calendar day
rather than Mazkir's 05:00 logical day — the boundary is applied when visits
are derived, not when points are stored. It is never taken from a request
string, so a request cannot choose the path written to.
"""

from __future__ import annotations

import json
import threading
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# One lock for both the append and the gap memory: two concurrent edits must
# not interleave a line, and the gap must be measured against the point
# actually written just before.
_lock = threading.Lock()
_last_ts: dict[str, datetime] = {}


def raw_path(root: Path, day: date) -> Path:
    return Path(root) / "raw" / f"{day.isoformat()}.jsonl"


def file_date(ts: datetime, tz: str) -> date:
    return ts.astimezone(ZoneInfo(tz)).date()


def append_point(root: Path, point: dict, tz: str) -> float | None:
    """Append one point; return seconds since this process's previous point of the same source."""
    ts: datetime = point["ts"]
    path = raw_path(root, file_date(ts, tz))
    line = json.dumps({**point, "ts": ts.isoformat()}, default=str, ensure_ascii=False) + "\n"
    source = str(point.get("source", ""))
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as f:
            # A crash mid-append leaves a line with no newline; start a fresh
            # one, or this point would be glued onto it and lost with it.
            if f.tell() > 0:
                f.seek(-1, 2)
                if f.read(1) != b"\n":
                    f.write(b"\n")
            f.write(line.encode("utf-8"))
        previous = _last_ts.get(source)
        _last_ts[source] = ts
    return (ts - previous).total_seconds() if previous is not None else None


def load_points(root: Path, day: date) -> tuple[list[dict], int]:
    """Every readable line of that day's file, in file order, and how many were not."""
    path = raw_path(root, day)
    if not path.exists():
        return [], 0
    points: list[dict] = []
    skipped = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if isinstance(obj, dict):
            points.append(obj)
        else:
            skipped += 1
    return points, skipped


def _reset_for_tests() -> None:
    with _lock:
        _last_ts.clear()
