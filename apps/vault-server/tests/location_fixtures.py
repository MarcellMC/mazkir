"""Synthetic tracks for the location trips tests (no real coordinates).

Positions are metres north/east of a fixed home; one fix every 30 s unless a
test says otherwise, as Telegram sent on the spike's dense days.
"""

from __future__ import annotations

import datetime as dt
import math
from zoneinfo import ZoneInfo

from src.services.location.model import Fix

TZ = "Asia/Jerusalem"
ZONE = ZoneInfo(TZ)
HOME = (32.0, 34.0)
_M_LAT = 111_195.0
_M_LNG = 111_195.0 * math.cos(math.radians(32.0))


def at(north_m: float, east_m: float = 0.0) -> tuple[float, float]:
    return HOME[0] + north_m / _M_LAT, HOME[1] + east_m / _M_LNG


def t(day: int, hh: int, mm: int, ss: int = 0) -> dt.datetime:
    return dt.datetime(2026, 11, day, hh, mm, ss, tzinfo=ZONE)


class Track:
    """Builds fixes in order: stay somewhere, walk somewhere, go silent."""

    def __init__(self, start: dt.datetime, north_m: float = 0.0, east_m: float = 0.0, step_s: int = 30):
        self.now = start
        self.pos = (north_m, east_m)
        self.step = dt.timedelta(seconds=step_s)
        self.fixes: list[Fix] = []

    def _fix(self, accuracy: float = 10.0) -> None:
        lat, lng = at(*self.pos)
        self.fixes.append(Fix(self.now, lat, lng, accuracy))

    def stay(self, minutes: float, jitter_m: float = 3.0, accuracy: float = 10.0) -> "Track":
        n = int(minutes * 60 / self.step.total_seconds())
        base = self.pos
        for i in range(n):
            angle = i * 2.399963  # golden angle: spreads the jitter evenly
            r = jitter_m * ((i % 7) / 6)
            self.pos = (base[0] + r * math.cos(angle), base[1] + r * math.sin(angle))
            self._fix(accuracy)
            self.now += self.step
        self.pos = base
        return self

    def walk_to(self, north_m: float, east_m: float = 0.0, kmh: float = 5.0) -> "Track":
        start = self.pos
        dist = math.hypot(north_m - start[0], east_m - start[1])
        seconds = dist / (kmh / 3.6)
        n = max(1, math.ceil(seconds / self.step.total_seconds()))
        for i in range(1, n + 1):
            f = i / n
            self.pos = (start[0] + (north_m - start[0]) * f, start[1] + (east_m - start[1]) * f)
            self._fix()
            self.now += self.step
        return self

    def silent(self, minutes: float) -> "Track":
        self.now += dt.timedelta(minutes=minutes)
        return self

    def point(self, north_m: float, east_m: float = 0.0, accuracy: float = 10.0) -> "Track":
        saved = self.pos
        self.pos = (north_m, east_m)
        self._fix(accuracy)
        self.pos = saved
        self.now += self.step
        return self


def feed_all(tracker, fixes, flush: bool = True):
    """Every event from feeding `fixes`, flushing the one-fix outlier buffer at the end."""
    events = []
    for f in fixes:
        events.extend(tracker.feed(f))
    if flush and fixes:
        events.extend(e for e in tracker.tick(fixes[-1].ts + dt.timedelta(seconds=61))
                      if e.kind != "SHARE_ENDED")
    return events
