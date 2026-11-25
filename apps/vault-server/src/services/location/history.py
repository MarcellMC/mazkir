"""Your confirmed history, scored against a trip (trips spec §5.2 item 1).

Code, not the model: each purpose you have confirmed at least 3 times is
compared with this trip on where it started, the hour, the spacing since it
last happened, the mode, how far it has gone, and the place of a stop. Any
recurring outing learns itself this way; nothing here names an activity.

Confirmed means: a label (spec §2.1, `data/eval/location/`), or a trip record
whose purpose you answered, merged with a block of yours, or approved.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from src.services.location.edits import trip_of
from src.services.location.model import Stop, Trip

logger = logging.getLogger(__name__)

MIN_CONFIRMED = 3
MIN_SCORE = 0.4
MAX_CANDIDATES = 5
HOUR_WINDOW_MIN = 90
SPACING_TOLERANCE = 0.4
DISTANCE_FACTOR = 1.5


@dataclass(frozen=True)
class ConfirmedTrip:
    purpose: str
    destination: str | None
    start: dt.datetime
    duration_s: float
    origin: str
    mode: str | None
    distance_m: float
    max_from_home_m: float
    stop_places: tuple[str, ...] = ()


@dataclass(frozen=True)
class HistoryCandidate:
    id: str
    purpose: str
    destination: str | None
    score: float
    count: int
    evidence: str


def _longest_mode(trip: Trip) -> str | None:
    legs = [leg for leg in trip.legs if leg.mode]
    return max(legs, key=lambda leg: leg.distance_m).mode if legs else None


def _from_labels(labels_dir: Path, since: dt.datetime) -> list[ConfirmedTrip]:
    out: list[ConfirmedTrip] = []
    if not labels_dir.exists():
        return out
    for path in sorted(labels_dir.glob("*.json")):
        try:
            rows = json.loads(path.read_text(encoding="utf-8")).get("trips", [])
        except (OSError, ValueError):
            logger.warning("unreadable labels file %s", path.name)
            continue
        for row in rows:
            f = row.get("features")
            if row.get("not_a_trip") or not f or not row.get("start"):
                continue
            start = dt.datetime.fromisoformat(row["start"])
            if start < since:
                continue
            end = dt.datetime.fromisoformat(row["end"]) if row.get("end") else start
            out.append(ConfirmedTrip(row["purpose"], row.get("destination"), start,
                                     (end - start).total_seconds(), f.get("origin") or "home", f.get("mode"),
                                     float(f.get("distance_m") or 0), float(f.get("max_from_home_m") or 0)))
    return out


def _is_confirmed(rec: dict, events, cache: dict[str, list[dict]]) -> bool:
    """Whether you confirmed this trip's purpose (spec §5.2).

    Your trip-level answer, your own block it merged with, ✓ All, or ✓ on the
    block that carries the purpose: the trip's own block, or the stop named
    as it. Approving a leg, or answering about a stop, says nothing about why
    the whole trip happened, so a silent guess cannot confirm itself that way.
    """
    if rec.get("confirmed"):
        return True
    purpose = ((rec.get("purpose") or {}).get("name") or "").strip().casefold()
    for part, ref in (rec.get("blocks") or {}).items():
        for frag in ref.get("fragments") or [ref]:
            day = frag.get("date")
            if day not in cache:
                cache[day] = events.get_events(day) if events is not None else []
            e = next((x for x in cache[day] if x.get("id") == frag.get("event_id")), None)
            if e is None or e.get("state") != "approved":
                continue
            if part == "trip" or (e.get("name") or "").strip().casefold() == purpose:
                return True
    return False


def load_confirmed(labels_dir: Path, records, events, tz: str, now: dt.datetime, days: int = 60) -> list[ConfirmedTrip]:
    since = now - dt.timedelta(days=days)
    out = _from_labels(Path(labels_dir), since)
    cache: dict[str, list[dict]] = {}
    for rec in records.all():
        purpose = rec.get("purpose")
        if rec.get("joined_into") or not purpose or not purpose.get("name"):
            continue
        trip = trip_of(rec)
        if trip.left_at < since or not _is_confirmed(rec, events, cache):
            continue
        end = trip.back_at or trip.left_at
        out.append(ConfirmedTrip(purpose["name"], purpose.get("destination"), trip.left_at,
                                 (end - trip.left_at).total_seconds(), trip.origin, _longest_mode(trip),
                                 trip.distance_m, trip.max_from_home_m,
                                 tuple(s.place_id for s in trip.stops if s.place_id)))
    return out


def _minutes(ts: dt.datetime, zone: ZoneInfo) -> int:
    local = ts.astimezone(zone)
    return local.hour * 60 + local.minute


def _circular(a: int, b: int) -> int:
    d = abs(a - b) % 1440
    return min(d, 1440 - d)


def _hour_ranges(hours: list[int]) -> str:
    """[7, 8, 10, 19, 20, 21] → "07–10 and 19–21"."""
    groups: list[list[int]] = []
    for h in sorted(set(hours)):
        if groups and h - groups[-1][-1] <= 2:
            groups[-1].append(h)
        else:
            groups.append([h])
    parts = [f"{g[0]:02d}" if g[0] == g[-1] else f"{g[0]:02d}–{g[-1]:02d}" for g in groups]
    return " and ".join(parts)


_MODE_WORDS = {"walk": "on foot", "ride": "by bike or bus", "vehicle": "by car or bus"}


def _ago(hours: float) -> str:
    return f"{hours:.0f} h ago" if hours < 48 else f"{hours / 24:.0f} d ago"


def score_history(trip: Trip, confirmed: list[ConfirmedTrip], now: dt.datetime, tz: str,
                  stop: Stop | None = None) -> list[HistoryCandidate]:
    zone = ZoneInfo(tz)
    groups: dict[str, list[ConfirmedTrip]] = {}
    for c in confirmed:
        groups.setdefault(c.purpose.strip().casefold(), []).append(c)

    trip_minutes = _minutes(trip.left_at, zone)
    trip_mode = _longest_mode(trip)
    scored: list[tuple[float, str, str | None, int, str]] = []
    for items in groups.values():
        if len(items) < MIN_CONFIRMED:
            continue
        items = sorted(items, key=lambda c: c.start)
        purpose = items[-1].purpose
        destination = next((c.destination for c in reversed(items) if c.destination), None)
        features: list[float] = []

        origin = Counter(c.origin for c in items).most_common(1)[0][0]
        features.append(1.0 if trip.origin == origin else 0.0)

        near_hour = min(_circular(trip_minutes, _minutes(c.start, zone)) for c in items)
        features.append(1.0 if near_hour <= HOUR_WINDOW_MIN else 0.0)

        before = [c.start for c in items if c.start <= trip.left_at]
        since_last_h = (trip.left_at - before[-1]).total_seconds() / 3600 if before else None
        if len(before) >= 2:
            spacing = statistics.median((b - a).total_seconds() / 3600 for a, b in zip(before, before[1:]))
            ok = spacing > 0 and abs(since_last_h - spacing) <= SPACING_TOLERANCE * spacing
            features.append(1.0 if ok else 0.0)

        modes = [c.mode for c in items if c.mode]
        usual_mode = Counter(modes).most_common(1)[0][0] if modes else None
        if usual_mode and trip_mode:
            features.append(1.0 if trip_mode == usual_mode else 0.0)

        farthest = max(c.max_from_home_m for c in items)
        features.append(1.0 if trip.max_from_home_m <= DISTANCE_FACTOR * max(farthest, 1.0) else 0.0)

        if stop is not None and stop.place_id:
            places = {p for c in items for p in c.stop_places}
            features.append(1.0 if stop.place_id in places else 0.0)

        score = sum(features) / len(features)
        if score < MIN_SCORE:
            continue
        parts = [f"{purpose}: {len(items)} confirmed",
                 f"usually {_hour_ranges([c.start.astimezone(zone).hour for c in items])}"]
        if since_last_h is not None:
            parts.append(f"last {_ago(since_last_h)}")
        if usual_mode:
            parts.append(_MODE_WORDS.get(usual_mode, usual_mode))
        parts.append("from home" if origin == "home" else f"from {origin}")
        if destination:
            parts.append(f"to {destination}")
        scored.append((score, purpose, destination, len(items), ", ".join(parts)))

    scored.sort(key=lambda s: (-s[0], -s[3]))
    return [HistoryCandidate(f"h{i}", purpose, destination, round(score, 3), count, evidence)
            for i, (score, purpose, destination, count, evidence) in enumerate(scored[:MAX_CANDIDATES], 1)]
