"""What the tracker produces: fixes in, stops, legs and trips out (trips spec §4).

Everything here round-trips through plain dicts, with datetimes as ISO strings
carrying their offset, because trip state is persisted after every point and
must survive a restart (`data/locations/state.json`, `trips/{id}.json`).

These objects hold coordinates. They stay on this machine: nothing that
leaves it (a span, a log line, the model's prompt, the vault) is built from
`lat`/`lng` — only from distances, durations and place names.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field
from typing import Any


def _ts(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse(value: str | None) -> dt.datetime | None:
    return dt.datetime.fromisoformat(value) if value else None


@dataclass(frozen=True)
class Fix:
    """One position Telegram sent."""
    ts: dt.datetime
    lat: float
    lng: float
    accuracy_m: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"ts": _ts(self.ts), "lat": self.lat, "lng": self.lng, "accuracy_m": self.accuracy_m}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Fix":
        return cls(_parse(d["ts"]), float(d["lat"]), float(d["lng"]), d.get("accuracy_m"))


@dataclass
class Stop:
    """A stay of at least 3 minutes inside a trip."""
    id: str
    start: dt.datetime
    end: dt.datetime | None
    lat: float
    lng: float
    spread_m: float
    from_home_m: float | None
    place_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["start"], d["end"] = _ts(self.start), _ts(self.end)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Stop":
        return cls(d["id"], _parse(d["start"]), _parse(d.get("end")), float(d["lat"]), float(d["lng"]),
                   float(d.get("spread_m") or 0.0), d.get("from_home_m"), d.get("place_id"))


@dataclass
class Leg:
    """Moving between two stays."""
    start: dt.datetime
    end: dt.datetime | None
    distance_m: float = 0.0
    mode: str | None = None          # "walk" | "ride" | "vehicle"

    def to_dict(self) -> dict[str, Any]:
        return {"start": _ts(self.start), "end": _ts(self.end), "distance_m": self.distance_m, "mode": self.mode}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Leg":
        return cls(_parse(d["start"]), _parse(d.get("end")), float(d.get("distance_m") or 0.0), d.get("mode"))


@dataclass
class Trip:
    """From leaving a stay to getting home (§4.2)."""
    id: str
    origin: str                       # "home" | a place id | "stay"
    left_at: dt.datetime
    start_precision: str              # "location" | "before"
    stops: list[Stop] = field(default_factory=list)
    legs: list[Leg] = field(default_factory=list)
    back_at: dt.datetime | None = None
    end_precision: str | None = None  # "location" | "before"
    distance_m: float = 0.0
    max_from_home_m: float = 0.0

    def stop(self, stop_id: str | None) -> Stop | None:
        return next((s for s in self.stops if s.id == stop_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "origin": self.origin, "left_at": _ts(self.left_at),
                "start_precision": self.start_precision,
                "stops": [s.to_dict() for s in self.stops], "legs": [leg.to_dict() for leg in self.legs],
                "back_at": _ts(self.back_at), "end_precision": self.end_precision,
                "distance_m": self.distance_m, "max_from_home_m": self.max_from_home_m}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Trip":
        return cls(d["id"], d["origin"], _parse(d["left_at"]), d["start_precision"],
                   [Stop.from_dict(s) for s in d.get("stops") or []],
                   [Leg.from_dict(leg) for leg in d.get("legs") or []],
                   _parse(d.get("back_at")), d.get("end_precision"),
                   float(d.get("distance_m") or 0.0), float(d.get("max_from_home_m") or 0.0))


@dataclass(frozen=True)
class TrackerEvent:
    """LEFT · STOPPED · LEFT_STOP · BACK_HOME · SHARE_ENDED, with the trip as it was then."""
    kind: str
    ts: dt.datetime
    trip: Trip | None
    stop_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "ts": _ts(self.ts), "trip": self.trip.to_dict() if self.trip else None,
                "stop_id": self.stop_id}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TrackerEvent":
        return cls(d["kind"], _parse(d["ts"]), Trip.from_dict(d["trip"]) if d.get("trip") else None,
                   d.get("stop_id"))
