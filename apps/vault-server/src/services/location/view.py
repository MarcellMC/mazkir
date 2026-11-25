"""What the agent may read about a trip: get_trip, find_place, find_visit (repair spec §7.1-7.3).

Everything returned here goes to the model. No coordinate and no OSM id is in it: a map
feature is a handle (``m<n>``) the server resolves, a place of the user's is ``place:<id>``,
and distances are rounded to 10 m.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Any
from zoneinfo import ZoneInfo

from src.services.approval import resolve_state
from src.services.fast_lane.places import PAUSE_KIND, Place, load_places
from src.services.geo import haversine_m
from src.services.location.edits import trip_of
from src.services.location.map_lookup import _fold, _match_rank, kind_words, map_area, map_near, map_search
from src.services.location.raw import load_fixes
from src.services.location.writer import fragments

NEAR_RADIUS_M = 3000.0
MAX_RESULTS = 8
VISIT_MIN_S = 180
VISIT_SILENCE_S = 600
VISIT_RADIUS_M = 40.0
GOOD_ACCURACY_M = 30.0


def logical_day(ts: dt.datetime, tz: str, boundary_hour: int) -> dt.date:
    """The day a moment belongs to: the day starts at `boundary_hour`, not at midnight."""
    return (ts.astimezone(ZoneInfo(tz)) - dt.timedelta(hours=boundary_hour)).date()


def _m(metres: float | None) -> int | None:
    """Rounded to 10 m, as an integer (so it can never look like a coordinate)."""
    return None if metres is None else int(round(metres / 10) * 10)


def _hm(ts: dt.datetime | None, zone: ZoneInfo) -> str | None:
    return ts.astimezone(zone).isoformat(timespec="minutes") if ts else None


def _records(deps) -> list[dict[str, Any]]:
    return sorted(deps.records.all(), key=lambda r: trip_of(r).left_at)


def _chosen(deps, trip_id: str | None, date: str | None) -> list[dict[str, Any]]:
    if trip_id:
        rec = deps.records.get(trip_id)
        if rec is None:
            raise KeyError("search again")
        return [rec]
    if date:
        day = dt.date.fromisoformat(date)
        return [r for r in _records(deps)
                if logical_day(trip_of(r).left_at, deps.tz, deps.boundary_hour) == day]
    recs = _records(deps)
    return recs[-1:]


# --- get_trip -------------------------------------------------------------------

def _block_view(deps, part: str, ref: dict[str, Any]) -> dict[str, Any]:
    frags = fragments(ref)
    events = []
    for frag in frags:
        found = next((e for e in deps.events.get_events(frag["date"]) if e.get("id") == frag["event_id"]), None)
        if found is not None:
            events.append(found)
    first = events[0] if events else {}
    return {"part": part, "event_id": frags[0]["event_id"], "date": frags[0]["date"],
            "name": first.get("name"), "start": first.get("start_time"),
            "end": (events[-1] if events else {}).get("end_time"),
            "state": resolve_state(first) if first else "missing"}


def _mode(trip) -> str | None:
    modes = [leg.mode for leg in trip.legs if leg.mode]
    return max(set(modes), key=modes.count) if modes else None


def _stop_view(rec: dict[str, Any], stop, deps, handles, chat_id: int, zone: ZoneInfo) -> dict[str, Any]:
    info = (rec.get("stops") or {}).get(stop.id) or {}
    seen = []
    for m in map_near(deps.map_index, stop.lat, stop.lng, stop.spread_m):
        ref = handles.place(chat_id, osm=m.osm, label=m.label, kind=m.kind, lat=m.lat, lng=m.lng)
        seen.append({"ref": ref, "label": m.label, "kind": kind_words(m.kind), "distance_m": _m(m.distance_m)})
    return {"id": stop.id, "start": _hm(stop.start, zone), "end": _hm(stop.end, zone),
            "minutes": round((stop.end - stop.start).total_seconds() / 60) if stop.end else None,
            "from_home_m": _m(stop.from_home_m), "status": info.get("status") or "unnamed",
            "name": info.get("name"), "place": info.get("place"),
            "street": bool(info.get("street")), "map": seen,
            "area": map_area(deps.map_index, stop.lat, stop.lng)}


def _trip_view(rec: dict[str, Any], deps, handles, chat_id: int) -> dict[str, Any]:
    zone = ZoneInfo(deps.tz)
    trip = trip_of(rec)
    purpose = rec.get("purpose") or {}
    return {
        "id": rec["id"], "closed": bool(rec.get("closed")),
        "left": _hm(trip.left_at, zone), "left_precision": trip.start_precision,
        "back": _hm(trip.back_at, zone), "back_precision": trip.end_precision,
        "mode": _mode(trip), "distance_m": _m(trip.distance_m), "farthest_from_home_m": _m(trip.max_from_home_m),
        "purpose": {"name": purpose.get("name"), "destination": purpose.get("destination"),
                    "confirmed": bool(rec.get("confirmed"))},
        "stops": [_stop_view(rec, s, deps, handles, chat_id, zone) for s in trip.stops],
        "legs": [{"start": _hm(leg.start, zone), "end": _hm(leg.end, zone), "mode": leg.mode,
                  "distance_m": _m(leg.distance_m)} for leg in trip.legs],
        "blocks": [_block_view(deps, part, ref) for part, ref in (rec.get("blocks") or {}).items()],
        "split_from": rec.get("split_from"), "split_into": rec.get("split_into"),
        "joined_into": rec.get("joined_into"),
    }


def get_trip(deps, handles, chat_id: int, *, trip_id: str | None = None, date: str | None = None) -> dict[str, Any]:
    """One trip, or the trips of a logical day (the latest trip with neither)."""
    return {"trips": [_trip_view(r, deps, handles, chat_id) for r in _chosen(deps, trip_id, date)]}


# --- find_place -----------------------------------------------------------------

def _home(deps) -> Place | None:
    return next((p for p in load_places(deps.places_path) if p.id == "home" and p.lat is not None), None)


def _anchor(deps, handles, chat_id: int, near: str | None) -> tuple[str, float, float]:
    """(what we searched around, lat, lng); KeyError("search again") when it cannot be found."""
    if near is None:
        recs = _records(deps)
        near = f"trip:{recs[-1]['id']}" if recs else "home"
    if near == "home":
        home = _home(deps)
        if home is None:
            raise KeyError("search again")
        return near, home.lat, home.lng
    kind, _, rest = near.partition(":")
    if kind in ("trip", "stop"):
        trip_id, _, stop_id = rest.partition(":")
        rec = deps.records.get(trip_id)
        if rec is None:
            raise KeyError("search again")
        trip = trip_of(rec)
        if kind == "stop":
            stop = trip.stop(stop_id)
        else:
            stop = max(trip.stops, key=lambda s: s.from_home_m or 0.0, default=None)
        if stop is None:
            raise KeyError("search again")
        return near, stop.lat, stop.lng
    if kind in ("photo", "location"):
        found = handles.resolve(chat_id, near)
        if not found or found.get("lat") is None:
            raise KeyError("search again")
        return near, found["lat"], found["lng"]
    raise KeyError("search again")


def find_place(deps, handles, chat_id: int, query: str, near: str | None = None) -> dict[str, Any]:
    """Places of the user's, then the map, within 3 km of `near`, at most 8."""
    near_ref, lat, lng = _anchor(deps, handles, chat_id, near)
    q = _fold(query)
    mine: list[tuple[int, float, dict[str, Any], str | None]] = []
    for p in load_places(deps.places_path):
        if p.kind == PAUSE_KIND or p.lat is None or p.lng is None or not q:
            continue
        rank = _match_rank(q, p.name, *p.aliases)
        dist = haversine_m(lat, lng, p.lat, p.lng)
        if rank is None or dist > NEAR_RADIUS_M:
            continue
        mine.append((rank, dist, {"ref": f"place:{p.id}", "label": p.name,
                                  "kind": kind_words(p.kind) if p.kind else "Your place", "group": "yours",
                                  "area": map_area(deps.map_index, p.lat, p.lng), "distance_m": _m(dist)}, p.osm))
    mine.sort(key=lambda h: (h[0], h[1]))
    results = [h[2] for h in mine]
    taken = {h[3] for h in mine if h[3]}
    for m in map_search(deps.map_index, query, lat, lng, NEAR_RADIUS_M, MAX_RESULTS):
        if m.osm in taken:
            continue
        ref = handles.place(chat_id, osm=m.osm, label=m.label, kind=m.kind, lat=m.lat, lng=m.lng)
        results.append({"ref": ref, "label": m.label, "kind": "Address" if m.group == "address" else kind_words(m.kind),
                        "group": m.group, "area": map_area(deps.map_index, m.lat, m.lng),
                        "distance_m": _m(m.distance_m)})
    return {"places": results[:MAX_RESULTS], "near": near_ref}


# --- find_visit -----------------------------------------------------------------

def _target(deps, handles, chat_id: int, ref: str) -> tuple[float, float]:
    if ref.startswith("place:"):
        pid = ref[len("place:"):]
        p = next((p for p in load_places(deps.places_path) if p.id == pid and p.lat is not None), None)
        if p is None:
            raise KeyError("search again")
        return p.lat, p.lng
    found = handles.resolve(chat_id, ref)
    if not found or found.get("lat") is None:
        raise KeyError("search again")
    return found["lat"], found["lng"]


def _window(deps, recs: list[dict[str, Any]], date: str | None) -> tuple[dt.datetime, dt.datetime]:
    zone = ZoneInfo(deps.tz)
    if date:
        day = dt.date.fromisoformat(date)
        start = dt.datetime.combine(day, dt.time(deps.boundary_hour), tzinfo=zone)
        return start, start + dt.timedelta(days=1)
    trip = trip_of(recs[0])
    return trip.left_at, trip.back_at or deps.now()


def find_visit(deps, handles, chat_id: int, ref: str, *, trip_id: str | None = None,
               date: str | None = None) -> dict[str, Any]:
    """When the raw points of a trip or day were near a place. Reads only."""
    lat, lng = _target(deps, handles, chat_id, ref)
    recs = _chosen(deps, trip_id, date)
    if not date and not recs:
        return {"visits": [], "closest": None}
    start, end = _window(deps, recs, date)
    zone = ZoneInfo(deps.tz)
    fixes = [f for f in load_fixes(deps.raw_dir.parent, start.astimezone(zone).date(), end.astimezone(zone).date())
             if start <= f.ts <= end]
    fixes.sort(key=lambda f: f.ts)

    runs: list[list[tuple[Any, float]]] = []
    run: list[tuple[Any, float]] = []
    closest: tuple[float, dt.datetime] | None = None
    for f in fixes:
        d = haversine_m(lat, lng, f.lat, f.lng)
        if closest is None or d < closest[0]:
            closest = (d, f.ts)
        if d <= max(VISIT_RADIUS_M, f.accuracy_m or 0.0):
            if run and (f.ts - run[-1][0].ts).total_seconds() > VISIT_SILENCE_S:
                runs.append(run)
                run = []
            run.append((f, d))
        elif run:
            runs.append(run)
            run = []
    if run:
        runs.append(run)

    trips = [trip_of(r) for r in (recs if recs else _records(deps))]
    visits = []
    for r in runs:
        first, last = r[0][0].ts, r[-1][0].ts
        if (last - first).total_seconds() < VISIT_MIN_S:
            continue
        good = sum(1 for f, _ in r if (f.accuracy_m or 0.0) <= GOOD_ACCURACY_M)
        found = next(((t.id, s.id) for t in trips for s in t.stops
                      if s.start <= last and (s.end or last) >= first), None)
        visits.append({"start": _hm(first, zone), "end": _hm(last, zone),
                       "closest_m": _m(min(d for _, d in r)), "stop_id": found[1] if found else None,
                       "trip_id": found[0] if found else None,
                       "quality": "good" if good * 2 >= len(r) else "poor"})
    return {"visits": visits,
            "closest": {"distance_m": _m(closest[0]), "at": _hm(closest[1], zone)} if closest else None}
