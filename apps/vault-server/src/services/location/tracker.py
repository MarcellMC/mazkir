"""Points → stays, stops and trips: a state machine fed one fix at a time (trips spec §4).

Pure code, no I/O. The runtime feeds it every live-location point inside the
ingest request and persists `to_dict()` after each one; `scripts/
location_rebuild.py` replays raw files through it, which is how the
thresholds are tuned.

The rules, in the order the plan (Task 3) numbers them:

1.  A fix at or before the last one seen is ignored. A fix with accuracy worse
    than 30 m is seen (it keeps the share alive) but never moves the state.
2.  The newest good fix waits for the next one: if the speed into it and out
    of it are both above 150 km/h it was a GPS jump, and it is dropped.
3.  A stay is fixes within the radius of their running centre for 3 minutes:
    40 m at home, 75 m elsewhere.
4.  Leaving is 3 good fixes in a row beyond the threshold, spanning a minute.
    At home the threshold is the radius itself; elsewhere it is
    max(radius, 3 × spread + accuracy). The departure is the last fix inside;
    when the fixes before and after it are more than 10 minutes apart, it is
    stamped "before" — you left some time before then.
5.  With no trip open, leaving a stay starts one (LEFT).
6.  With a trip open, a stay reaching 3 minutes is a stop (STOPPED), and
    leaving it is LEFT_STOP.
7.  Home wins: 3 good fixes back within home's radius, spanning a minute, end
    whatever stop was open (LEFT_STOP) and the trip (BACK_HOME).
8.  Only leaving ends a stay. A gap in points never does.
9.  Legs run between stops; their mode is the median segment speed.
10. No fix for 30 minutes means the share ended (SHARE_ENDED, once).
11. Midnight is not special.
12. Without a known home a trip never closes; the runtime handles that.
"""

from __future__ import annotations

import copy
import datetime as dt
import statistics
from dataclasses import dataclass
from typing import Any, Callable
from uuid import uuid4

from src.services.fast_lane.places import PAUSE_KIND, Place, nearest
from src.services.geo import haversine_m
from src.services.location.model import Fix, Leg, Stop, TrackerEvent, Trip

# Fixes kept per stay for its spread; the centre is a running mean over all.
_KEEP_FIXES = 200
# A segment shorter than this is GPS jitter, not distance travelled.
_MIN_SEGMENT_M = 10.0


@dataclass(frozen=True)
class Params:
    accuracy_max_m: float = 30
    outlier_kmh: float = 150
    stay_min_s: float = 180
    home_radius_m: float = 40
    stay_radius_m: float = 75
    leave_points: int = 3
    leave_min_s: float = 60
    silence_s: float = 600
    share_ended_s: float = 1800
    walk_kmh: float = 7
    ride_kmh: float = 25


def _dist(a: Fix | tuple[float, float], b: Fix | tuple[float, float]) -> float:
    alat, alng = (a.lat, a.lng) if isinstance(a, Fix) else a
    blat, blng = (b.lat, b.lng) if isinstance(b, Fix) else b
    return haversine_m(alat, alng, blat, blng)


def _kmh(a: Fix, b: Fix) -> float:
    seconds = (b.ts - a.ts).total_seconds()
    return _dist(a, b) / seconds * 3.6 if seconds > 0 else float("inf")


class _Stay:
    """A place you are (or may be) staying: confirmed after 3 minutes."""

    def __init__(self, fix: Fix, is_home: bool, home: tuple[float, float] | None):
        self.is_home = is_home
        self.home = home
        self.first_ts = fix.ts
        self.last_inside_ts = fix.ts
        self.n = 0
        self.sum_lat = 0.0
        self.sum_lng = 0.0
        self.fixes: list[Fix] = []
        self.confirmed = False
        self.stop_id: str | None = None
        self.add(fix)

    @property
    def centre(self) -> tuple[float, float]:
        if self.is_home and self.home is not None:
            return self.home
        return self.sum_lat / self.n, self.sum_lng / self.n

    def add(self, fix: Fix) -> None:
        self.n += 1
        self.sum_lat += fix.lat
        self.sum_lng += fix.lng
        self.fixes.append(fix)
        del self.fixes[:-_KEEP_FIXES]
        self.last_inside_ts = fix.ts

    def spread_m(self) -> float:
        centre = self.centre
        distances = sorted(_dist(f, centre) for f in self.fixes)
        return distances[min(len(distances) - 1, int(0.9 * len(distances)))] if distances else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"is_home": self.is_home, "first_ts": self.first_ts.isoformat(),
                "last_inside_ts": self.last_inside_ts.isoformat(), "n": self.n,
                "sum_lat": self.sum_lat, "sum_lng": self.sum_lng,
                "fixes": [f.to_dict() for f in self.fixes], "confirmed": self.confirmed,
                "stop_id": self.stop_id}

    @classmethod
    def from_dict(cls, d: dict[str, Any], home: tuple[float, float] | None) -> "_Stay":
        stay = cls.__new__(cls)
        stay.is_home, stay.home = d["is_home"], home
        stay.first_ts = dt.datetime.fromisoformat(d["first_ts"])
        stay.last_inside_ts = dt.datetime.fromisoformat(d["last_inside_ts"])
        stay.n, stay.sum_lat, stay.sum_lng = d["n"], d["sum_lat"], d["sum_lng"]
        stay.fixes = [Fix.from_dict(f) for f in d["fixes"]]
        stay.confirmed, stay.stop_id = d["confirmed"], d.get("stop_id")
        return stay


class Tracker:
    def __init__(self, home: tuple[float, float] | None, places: list[Place], params: Params = Params(),
                 new_id: Callable[[], str] = lambda: uuid4().hex[:8]):
        self.home = home
        self.places = places
        self.params = params
        self.new_id = new_id
        self._last_seen: dt.datetime | None = None
        self._pending: Fix | None = None       # rule 2: the newest good fix, not yet judged
        self._prev: Fix | None = None          # the last good fix processed
        self._stay: _Stay | None = None        # where you are, or may be
        self._outside: list[Fix] = []          # rule 4: fixes beyond the stay's threshold
        self._home_run: list[Fix] = []         # rule 7: fixes back inside home's radius
        self._trip: Trip | None = None
        self._speeds: list[float] = []         # current leg's segment speeds (km/h)
        self._ended = False                    # rule 10: SHARE_ENDED sent for this silence

    # --- public --------------------------------------------------------------

    @property
    def trip(self) -> Trip | None:
        return self._trip

    @property
    def last_fix_ts(self) -> dt.datetime | None:
        return self._last_seen

    def set_home(self, home: tuple[float, float]) -> None:
        self.home = home
        if self._stay is not None:
            self._stay.home = home

    def feed(self, fix: Fix) -> list[TrackerEvent]:
        if self._last_seen is not None and fix.ts <= self._last_seen:
            return []
        self._last_seen = fix.ts
        self._ended = False
        if fix.accuracy_m is not None and fix.accuracy_m > self.params.accuracy_max_m:
            return []
        events: list[TrackerEvent] = []
        pending, self._pending = self._pending, fix
        if pending is not None and not self._is_outlier(pending, fix):
            events.extend(self._process(pending))
        return events

    def tick(self, now: dt.datetime) -> list[TrackerEvent]:
        events: list[TrackerEvent] = []
        if self._pending is not None and (now - self._pending.ts).total_seconds() >= 60:
            pending, self._pending = self._pending, None
            events.extend(self._process(pending))
        if (self._last_seen is not None and not self._ended
                and (now - self._last_seen).total_seconds() >= self.params.share_ended_s):
            self._ended = True
            stop = self._open_stop()
            if stop is not None:
                stop.end = self._stay.last_inside_ts
            events.append(self._event("SHARE_ENDED", self._last_seen))
        return events

    # --- the rules -----------------------------------------------------------

    def _is_outlier(self, fix: Fix, after: Fix) -> bool:
        if self._prev is None:
            return False
        limit = self.params.outlier_kmh
        return _kmh(self._prev, fix) > limit and _kmh(fix, after) > limit

    def _process(self, fix: Fix) -> list[TrackerEvent]:
        events: list[TrackerEvent] = []
        prev, self._prev = self._prev, fix
        if self._trip is not None and prev is not None:
            self._measure(prev, fix)
        if self._trip is not None and self.home is not None:
            back = self._check_home(prev, fix)
            if back:
                return back
        if self._stay is not None and self._stay.confirmed:
            events.extend(self._in_stay(fix))
        else:
            events.extend(self._moving(fix))
        return events

    def _measure(self, prev: Fix, fix: Fix) -> None:
        trip = self._trip
        if self.home is not None:
            trip.max_from_home_m = max(trip.max_from_home_m, _dist(fix, self.home))
        if self._open_stop() is not None:
            return
        segment = _dist(prev, fix)
        if segment < _MIN_SEGMENT_M:
            return
        leg = trip.legs[-1]
        leg.distance_m += segment
        trip.distance_m += segment
        self._speeds.append(_kmh(prev, fix))
        leg.mode = self._mode()

    def _mode(self) -> str | None:
        if not self._speeds:
            return None
        speed = statistics.median(self._speeds)
        if speed <= self.params.walk_kmh:
            return "walk"
        if speed <= self.params.ride_kmh:
            return "ride"
        return "vehicle"

    def _check_home(self, prev: Fix | None, fix: Fix) -> list[TrackerEvent]:
        if _dist(fix, self.home) > self.params.home_radius_m:
            self._home_run = []
            return []
        if not self._home_run:
            self._home_run_gap = (fix.ts - prev.ts).total_seconds() if prev is not None else 0.0
            self._home_run_before = prev.ts if prev is not None else fix.ts
        self._home_run.append(fix)
        span = (self._home_run[-1].ts - self._home_run[0].ts).total_seconds()
        if len(self._home_run) < self.params.leave_points or span < self.params.leave_min_s:
            return []
        events: list[TrackerEvent] = []
        trip = self._trip
        arrived = self._home_run[0].ts
        stop = self._open_stop()
        if stop is not None:
            stop.end = min(self._stay.last_inside_ts, self._home_run_before)
            events.append(self._event("LEFT_STOP", fix.ts, stop.id))
        if trip.legs and trip.legs[-1].end is None:
            trip.legs[-1].end = arrived
        trip.back_at = arrived
        trip.end_precision = "before" if self._home_run_gap > self.params.silence_s else "location"
        events.append(self._event("BACK_HOME", fix.ts))
        home_stay = _Stay(self._home_run[0], True, self.home)
        for f in self._home_run[1:]:
            home_stay.add(f)
        home_stay.confirmed = True
        self._stay, self._outside, self._home_run, self._trip, self._speeds = home_stay, [], [], None, []
        return events

    def _radius(self, stay: _Stay) -> float:
        return self.params.home_radius_m if stay.is_home else self.params.stay_radius_m

    def _threshold(self, stay: _Stay, fix: Fix) -> float:
        if stay.is_home:
            return self.params.home_radius_m
        return max(self.params.stay_radius_m, 3 * stay.spread_m() + (fix.accuracy_m or 0.0))

    def _in_stay(self, fix: Fix) -> list[TrackerEvent]:
        stay = self._stay
        d = _dist(fix, stay.centre)
        if d <= self._threshold(stay, fix):
            self._outside = []
            if d <= self._radius(stay):
                stay.add(fix)
            stop = self._open_stop()
            if stop is None and stay.stop_id is not None:
                # The share came back where it ended: the stop goes on (rule 10).
                reopened = self._trip.stop(stay.stop_id) if self._trip else None
                if reopened is not None:
                    reopened.end = None
            return []
        self._outside.append(fix)
        span = (self._outside[-1].ts - self._outside[0].ts).total_seconds()
        if len(self._outside) < self.params.leave_points or span < self.params.leave_min_s:
            return []
        return self._leave(stay)

    def _leave(self, stay: _Stay) -> list[TrackerEvent]:
        events: list[TrackerEvent] = []
        departed = stay.last_inside_ts
        gap = (self._outside[0].ts - departed).total_seconds()
        precision = "before" if gap > self.params.silence_s else "location"
        now = self._outside[-1].ts
        if self._trip is None:
            self._trip = Trip(id=self.new_id(), origin=self._origin(stay), left_at=departed,
                              start_precision=precision, legs=[Leg(departed, None)])
            if self.home is not None:
                self._trip.max_from_home_m = max(_dist(f, self.home) for f in self._outside)
            events.append(self._event("LEFT", now))
        else:
            stop = self._trip.stop(stay.stop_id)
            if stop is not None:
                stop.end = departed
                events.append(self._event("LEFT_STOP", now, stop.id))
            self._trip.legs.append(Leg(departed, None))
        self._speeds = []
        # What lay outside may be the start of the next stay (the shop next door).
        seed = [f for f in self._outside if _dist(f, self._outside[-1]) <= self.params.stay_radius_m]
        self._stay = self._new_stay(seed[0])
        for f in seed[1:]:
            self._stay.add(f)
        self._outside = []
        events.extend(self._confirm_if_due())
        return events

    def _moving(self, fix: Fix) -> list[TrackerEvent]:
        stay = self._stay
        if stay is None or _dist(fix, stay.centre) > self._radius(stay):
            self._stay = self._new_stay(fix)
        else:
            stay.add(fix)
        return self._confirm_if_due()

    def _confirm_if_due(self) -> list[TrackerEvent]:
        stay = self._stay
        if stay.confirmed or (stay.last_inside_ts - stay.first_ts).total_seconds() < self.params.stay_min_s:
            return []
        stay.confirmed = True
        if self._trip is None:
            return []
        centre = stay.centre
        place = nearest(centre[0], centre[1], self.places)
        stop = Stop(id=f"s{len(self._trip.stops) + 1}", start=stay.first_ts, end=None,
                    lat=centre[0], lng=centre[1], spread_m=stay.spread_m(),
                    from_home_m=_dist(centre, self.home) if self.home is not None else None,
                    place_id=place.id if place is not None else None)
        self._trip.stops.append(stop)
        if self._trip.legs and self._trip.legs[-1].end is None:
            self._trip.legs[-1].end = stop.start
        stay.stop_id = stop.id
        return [self._event("STOPPED", stay.last_inside_ts, stop.id)]

    def _new_stay(self, fix: Fix) -> _Stay:
        is_home = self.home is not None and _dist(fix, self.home) <= self.params.home_radius_m
        return _Stay(fix, is_home, self.home)

    def _origin(self, stay: _Stay) -> str:
        if stay.is_home:
            return "home"
        centre = stay.centre
        place = nearest(centre[0], centre[1], self.places)
        return place.id if place is not None and place.kind != PAUSE_KIND else "stay"

    def _open_stop(self) -> Stop | None:
        if self._trip is None or self._stay is None or self._stay.stop_id is None:
            return None
        stop = self._trip.stop(self._stay.stop_id)
        return stop if stop is not None and stop.end is None else None

    def _event(self, kind: str, ts: dt.datetime, stop_id: str | None = None) -> TrackerEvent:
        return TrackerEvent(kind, ts, copy.deepcopy(self._trip), stop_id)

    # --- persistence ---------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_seen": self._last_seen.isoformat() if self._last_seen else None,
            "pending": self._pending.to_dict() if self._pending else None,
            "prev": self._prev.to_dict() if self._prev else None,
            "stay": self._stay.to_dict() if self._stay else None,
            "outside": [f.to_dict() for f in self._outside],
            "home_run": [f.to_dict() for f in self._home_run],
            "home_run_gap": getattr(self, "_home_run_gap", 0.0),
            "home_run_before": (self._home_run_before.isoformat()
                                if getattr(self, "_home_run_before", None) else None),
            "trip": self._trip.to_dict() if self._trip else None,
            "speeds": list(self._speeds),
            "ended": self._ended,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any], home: tuple[float, float] | None, places: list[Place],
                  params: Params = Params(), new_id: Callable[[], str] = lambda: uuid4().hex[:8]) -> "Tracker":
        tr = cls(home, places, params, new_id)
        tr._last_seen = dt.datetime.fromisoformat(d["last_seen"]) if d.get("last_seen") else None
        tr._pending = Fix.from_dict(d["pending"]) if d.get("pending") else None
        tr._prev = Fix.from_dict(d["prev"]) if d.get("prev") else None
        tr._stay = _Stay.from_dict(d["stay"], home) if d.get("stay") else None
        tr._outside = [Fix.from_dict(f) for f in d.get("outside") or []]
        tr._home_run = [Fix.from_dict(f) for f in d.get("home_run") or []]
        tr._home_run_gap = d.get("home_run_gap") or 0.0
        tr._home_run_before = (dt.datetime.fromisoformat(d["home_run_before"])
                               if d.get("home_run_before") else None)
        tr._trip = Trip.from_dict(d["trip"]) if d.get("trip") else None
        tr._speeds = list(d.get("speeds") or [])
        tr._ended = bool(d.get("ended"))
        return tr
