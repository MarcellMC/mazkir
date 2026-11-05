"""What the location spike measured (spec §4.5). Pure functions over raw points.

The spike exists because the Bot API does not say how often Telegram sends a
live-location update, whether it sends anything while you stand still, or
what arrives when a share ends (spec §2.2). Nothing here infers an answer:
it reports what came in, so the owner can read it.

Defaults are the spec's: moving means an implied speed above 1 km/h, a
silence is a gap of more than 15 minutes, waking hours are 07:00–23:00.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from src.services.geo import haversine_m

MOVING_KMH = 1.0
SILENCE_S = 900
WAKING = (7, 23)
_SESSION_KINDS = ("live", "live_start")


@dataclass(frozen=True)
class Point:
    source: str
    kind: str
    message_id: int | None
    ts: dt.datetime
    received_at: dt.datetime | None
    lat: float
    lng: float
    accuracy_m: float | None
    live_period: int | None
    raw: dict


@dataclass
class Session:
    message_id: int | None
    started: dt.datetime
    live_period: int | None
    expires_at: dt.datetime | None
    last_point: dt.datetime
    n_points: int
    last_fields: list[str]


def _parse(ts: str | None) -> dt.datetime | None:
    if not ts:
        return None
    try:
        return dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def normalise(lines: list[dict]) -> list[Point]:
    """Parse, drop exact redeliveries, and order by `ts`.

    A redelivery (grammY re-fetching updates after a crash) is the same
    source, message, instant and position; it is one observation, not two.
    """
    seen: set[tuple] = set()
    points: list[Point] = []
    for raw in lines:
        ts = _parse(raw.get("ts"))
        if ts is None or raw.get("lat") is None or raw.get("lng") is None:
            continue
        key = (raw.get("source"), raw.get("message_id"), ts, raw["lat"], raw["lng"])
        if key in seen:
            continue
        seen.add(key)
        points.append(Point(
            source=str(raw.get("source", "")), kind=str(raw.get("kind", "")), message_id=raw.get("message_id"),
            ts=ts, received_at=_parse(raw.get("received_at")), lat=float(raw["lat"]), lng=float(raw["lng"]),
            accuracy_m=raw.get("accuracy_m"), live_period=raw.get("live_period"), raw=raw,
        ))
    points.sort(key=lambda p: p.ts)
    return points


def _by_session(points: list[Point]) -> dict[tuple, list[Point]]:
    groups: dict[tuple, list[Point]] = {}
    for p in points:
        if p.kind in _SESSION_KINDS:
            groups.setdefault((p.source, p.message_id), []).append(p)
    return groups


def share_sessions(points: list[Point]) -> list[Session]:
    sessions = []
    for group in _by_session(points).values():
        first, last = group[0], group[-1]
        period = next((p.live_period for p in group if p.live_period is not None), None)
        sessions.append(Session(
            message_id=first.message_id, started=first.ts, live_period=period,
            expires_at=first.ts + dt.timedelta(seconds=period) if period is not None else None,
            last_point=last.ts, n_points=len(group), last_fields=sorted(last.raw),
        ))
    sessions.sort(key=lambda s: s.started)
    return sessions


def _pairs(points: list[Point]):
    """Consecutive points of the same session, with a positive time between them."""
    for group in _by_session(points).values():
        for a, b in zip(group, group[1:]):
            seconds = (b.ts - a.ts).total_seconds()
            if seconds > 0:
                yield a, b, seconds


def _is_moving(a: Point, b: Point, seconds: float) -> bool:
    return haversine_m(a.lat, a.lng, b.lat, b.lng) / seconds * 3.6 > MOVING_KMH


def intervals(points: list[Point]) -> list[tuple[float, bool]]:
    return [(seconds, _is_moving(a, b, seconds)) for a, b, seconds in _pairs(points)]


def _rank(sorted_values: list[float], pct: int) -> float:
    return sorted_values[max(0, math.ceil(pct / 100 * len(sorted_values)) - 1)]


def summary(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "p50": None, "p90": None, "max": None}
    s = sorted(values)
    return {"n": len(s), "p50": _rank(s, 50), "p90": _rank(s, 90), "max": s[-1]}


def silences(points: list[Point], min_gap_s: float = SILENCE_S) -> list[tuple[dt.datetime, dt.datetime, float]]:
    out = [(a.ts, b.ts, haversine_m(a.lat, a.lng, b.lat, b.lng))
           for a, b, seconds in _pairs(points) if seconds > min_gap_s]
    return sorted(out)


def still_scatter_m(points: list[Point]) -> list[float]:
    """Per run of ≥ 3 points joined by still intervals: p90 distance from the run's centroid."""
    out = []
    for group in _by_session(points).values():
        run = [group[0]] if group else []
        for a, b in zip(group, group[1:]):
            seconds = (b.ts - a.ts).total_seconds()
            if seconds > 0 and not _is_moving(a, b, seconds):
                run.append(b)
                continue
            out.extend(_scatter(run))
            run = [b]
        out.extend(_scatter(run))
    return out


def _scatter(run: list[Point]) -> list[float]:
    if len(run) < 3:
        return []
    lat = sum(p.lat for p in run) / len(run)
    lng = sum(p.lng for p in run) / len(run)
    return [_rank(sorted(haversine_m(lat, lng, p.lat, p.lng) for p in run), 90)]


def coverage(sessions: list[Session], day: dt.date, tz: str, waking: tuple[int, int] = WAKING) -> float:
    """Share of the day's waking minutes inside [started, last_point] of any session (a lower bound)."""
    zone = ZoneInfo(tz)
    lo = dt.datetime.combine(day, dt.time(waking[0]), zone)
    hi = dt.datetime.combine(day, dt.time(waking[1]), zone)
    spans = sorted((max(s.started, lo), min(s.last_point, hi)) for s in sessions)
    covered = dt.timedelta()
    cur_start = cur_end = None
    for start, end in spans:
        if end <= start:
            continue
        if cur_end is None or start > cur_end:
            if cur_end is not None:
                covered += cur_end - cur_start
            cur_start, cur_end = start, end
        else:
            cur_end = max(cur_end, end)
    if cur_end is not None:
        covered += cur_end - cur_start
    return covered / (hi - lo)


def ingest_health(points: list[Point], bot_log: list[dict], day: dt.date, tz: str) -> dict:
    zone = ZoneInfo(tz)
    failures = 0
    for rec in bot_log:
        ts = _parse(rec.get("ts"))
        if rec.get("event_type") == "location_ingest_failed" and ts and ts.astimezone(zone).date() == day:
            failures += 1
    lags = [(p.received_at - p.ts).total_seconds() for p in points if p.received_at is not None]
    return {"points": len(points), "failures": failures, "lag": summary(lags)}


def _hm(ts: dt.datetime, zone: ZoneInfo, day: dt.date | None = None) -> str:
    local = ts.astimezone(zone)
    return local.strftime("%H:%M") if day is None or local.date() == day else local.strftime("%Y-%m-%d %H:%M")


def _fmt(s: dict, unit: str) -> str:
    if not s["n"]:
        return "no points"
    return f"n={s['n']}  p50={s['p50']:.0f}{unit}  p90={s['p90']:.0f}{unit}  max={s['max']:.0f}{unit}"


def _day_block(day: dt.date, points: list[Point], skipped: int, bot_log: list[dict], tz: str) -> list[str]:
    zone = ZoneInfo(tz)
    sessions = share_sessions(points)
    check_ins = sum(1 for p in points if p.kind == "check_in")
    out = [f"== {day.isoformat()} ==", "Share sessions"]
    if not points:
        out.append("  no points")
    for s in sessions:
        period = (f"live_period {s.live_period}s (until {_hm(s.expires_at, zone, day)})"
                  if s.live_period is not None else "no live_period seen")
        out.append(f"  #{s.message_id}  started {_hm(s.started, zone, day)}  {period}  "
                   f"last point {_hm(s.last_point, zone, day)}  {s.n_points} points")
        out.append(f"      last update's fields: {', '.join(s.last_fields)}")
    out.append(f"  check-ins: {check_ins}")

    out.append(f"Silences (> {SILENCE_S // 60} min inside a share)")
    gaps = silences(points)
    out.extend([f"  {_hm(a, zone, day)}–{_hm(b, zone, day)}  {(b - a).total_seconds() / 60:.0f} min, "
                f"{d:.0f} m apart" for a, b, d in gaps] or ["  no points" if not points else "  none"])

    out.append("Coverage")
    out.append(f"  waking hours {WAKING[0]:02d}:00–{WAKING[1]:02d}:00 inside a share: "
               f"{coverage(sessions, day, tz):.0%} (a lower bound: share start to its last point)")

    health = ingest_health(points, bot_log, day, tz)
    out.append("Ingest health")
    out.append(f"  points {health['points']}, failed posts {health['failures']}, "
               f"lag {_fmt(health['lag'], 's')}")
    if skipped:
        out.append(f"  {skipped} unreadable line{'s' if skipped != 1 else ''} skipped")
    return out


def render_report(days: dict[dt.date, list[Point]], skipped: dict[dt.date, int], bot_log: list[dict],
                  tz: str) -> str:
    out: list[str] = []
    for day in sorted(days):
        out.extend(_day_block(day, days[day], skipped.get(day, 0), bot_log, tz))
        out.append("")
    every = sorted((p for pts in days.values() for p in pts), key=lambda p: p.ts)
    pairs = intervals(every)
    out.append("== All days ==")
    out.append("Sampling (seconds between points of one share)")
    out.append(f"  moving: {_fmt(summary([s for s, moving in pairs if moving]), 's')}")
    out.append(f"  still:  {_fmt(summary([s for s, moving in pairs if not moving]), 's')}")
    out.append("Accuracy")
    out.append(f"  horizontal_accuracy: {_fmt(summary([p.accuracy_m for p in every if p.accuracy_m is not None]), ' m')}")
    out.append(f"  still scatter (p90 from centroid, per still run): {_fmt(summary(still_scatter_m(every)), ' m')}")
    return "\n".join(out)
