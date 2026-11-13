"""Home is where most nights were spent (trips spec §4.2)."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from zoneinfo import ZoneInfo

from src.services.geo import haversine_m
from src.services.location.model import Fix

NIGHT_HOURS = (1, 5)          # 01:00–05:00 local
NIGHT_SPREAD_M = 75.0         # a night that wandered more than this is not a night spent somewhere
CLUSTER_M = 75.0
MIN_NIGHTS = 3
ACCURACY_MAX_M = 30.0


def _p90(values: list[float]) -> float:
    values = sorted(values)
    return values[min(len(values) - 1, int(0.9 * len(values)))]


def find_home(fixes: list[Fix], tz: str, today: dt.date, days: int = 14) -> tuple[float, float] | None:
    """The centre of the nights most often spent in one place, if at least 3 were."""
    zone = ZoneInfo(tz)
    first = today - dt.timedelta(days=days)
    by_night: dict[dt.date, list[Fix]] = defaultdict(list)
    for f in fixes:
        if f.accuracy_m is not None and f.accuracy_m > ACCURACY_MAX_M:
            continue
        local = f.ts.astimezone(zone)
        if NIGHT_HOURS[0] <= local.hour < NIGHT_HOURS[1] and first <= local.date() <= today:
            by_night[local.date()].append(f)

    centroids: list[tuple[float, float]] = []
    for night in by_night.values():
        lat = sum(f.lat for f in night) / len(night)
        lng = sum(f.lng for f in night) / len(night)
        if _p90([haversine_m(f.lat, f.lng, lat, lng) for f in night]) <= NIGHT_SPREAD_M:
            centroids.append((lat, lng))

    best: list[tuple[float, float]] = []
    for c in centroids:
        cluster = [o for o in centroids if haversine_m(*c, *o) <= CLUSTER_M]
        if len(cluster) > len(best):
            best = cluster
    if len(best) < MIN_NIGHTS:
        return None
    return sum(c[0] for c in best) / len(best), sum(c[1] for c in best) / len(best)
