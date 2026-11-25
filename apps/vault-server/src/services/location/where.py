"""Where a photo or a location message was, in words (repair spec §8).

The model never gets the numbers: code looks the position up and hands it
places, a street and an area. The position itself stays on the server,
registered in the per-chat handle table under the photo's or the message's
anchor key (`photo:<file>`, `location:<message_id>`), so a later tool can
search around it or learn a place at it.

Order of what wins:
1. a trip stop at that moment: "at stop s3 of trip <id> (<name>)", with that
   stop's map places;
   (a location the user sends: only near the stop; a forwarded one: never);
2. home: "at home";
3. another place of the user's: its handle, then the street and the area;
4. the map: up to 5 places within `max(40 m, GPS accuracy)`, nearest first,
   then the street and the area;
5. no map copy: "no map here".

Only distances (rounded to 10 m), the GPS accuracy (rounded) and names are
written. Nothing here logs.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from src.services.fast_lane.places import PAUSE_KIND, Place, nearest
from src.services.geo import haversine_m
from src.services.location.guess import _metres
from src.services.location.handles import Handles
from src.services.location.map_lookup import kind_words, map_area, map_near, nearest_address
from src.services.location.edits import trip_of
from src.services.location.model import Stop

LOOKUP_MIN_M = 40.0
STOP_NEAR_M = 75.0       # a location you send is that stop only this close to it (or within its accuracy)
MAX_PLACES = 5
NO_MAP = "no map here"


def describe_where(
    lat: float,
    lng: float,
    *,
    accuracy_m: float | None,
    at: dt.datetime | None,
    chat_id: int,
    places: list[Place],
    map_index: Path | None,
    handles: Handles,
    records: Any = None,
    anchor_key: str,
    stop_near_only: bool = False,
) -> str:
    """The segment a photo or location line carries: "at home", "at stop …", or "where: …".

    A photo taken during a stop is that stop, by time alone (spec §8). A location the user
    sends (`stop_near_only`) is the stop only within `max(75 m, accuracy)` of its centre: a
    venue across town shared mid-stop is somewhere else. A forwarded location passes no `at`.
    """
    handles.anchor(chat_id, anchor_key, lat, lng, accuracy_m)
    gps = f" | GPS ±{round(accuracy_m)} m" if accuracy_m is not None else ""

    found = _stop_at(records, at)
    if found is not None and stop_near_only and \
            haversine_m(lat, lng, found[1].lat, found[1].lng) > max(STOP_NEAR_M, accuracy_m or 0.0):
        found = None
    if found is not None:
        trip_id, stop, name = found
        # The stop's own radius, so these are the places its question offered.
        parts = _map_parts(chat_id, stop.lat, stop.lng, map_index, handles, spread_m=stop.spread_m,
                           radius_m=None)
        head = f"at stop {stop.id} of trip {trip_id} ({name or 'unnamed'})"
        return head + (f"; where: {'; '.join(parts)}" if parts else "") + gps

    mine = nearest(lat, lng, [p for p in places if p.kind != PAUSE_KIND])
    if mine is not None and mine.id == "home":
        return "at home"
    if mine is not None:
        far = _metres(haversine_m(lat, lng, mine.lat, mine.lng))
        parts = [f"place:{mine.id} {mine.name} (yours, {far})", *_street_and_area(lat, lng, map_index)]
        return "where: " + "; ".join(parts) + gps

    if map_index is None or not Path(map_index).exists():
        return f"where: {NO_MAP}{gps}"
    parts = _map_parts(chat_id, lat, lng, map_index, handles, spread_m=0.0,
                       radius_m=max(LOOKUP_MIN_M, accuracy_m or 0.0))
    return "where: " + ("; ".join(parts) if parts else "nothing on the map here") + gps


def _map_parts(chat_id: int, lat: float, lng: float, map_index: Path | None, handles: Handles, *,
               spread_m: float, radius_m: float | None) -> list[str]:
    found = [p for p in map_near(map_index, lat, lng, spread_m, radius_m=radius_m) if p.group == "place"]
    named = []
    for p in found[:MAX_PLACES]:
        if p.lat is None or p.lng is None:
            continue
        handle = handles.place(chat_id, osm=p.osm, label=p.label, kind=p.kind, lat=p.lat, lng=p.lng)
        kind = kind_words(p.kind)
        what = f"{_lower(kind)}, " if kind != p.label else ""
        named.append(f"{handle} {p.label} ({what}{_metres(p.distance_m)})")
    out = [", ".join(named)] if named else []
    return out + _street_and_area(lat, lng, map_index)


def _street_and_area(lat: float, lng: float, map_index: Path | None) -> list[str]:
    out = []
    address = nearest_address(map_index, lat, lng)
    if address is not None:
        street, number = address
        out.append(f"on {street}, by number {number}" if number else f"on {street}")
    area = map_area(map_index, lat, lng)
    if area:
        out.append(f"in {area}")
    return out


def _lower(words: str) -> str:
    return words if words.isupper() else words[:1].lower() + words[1:]


def _stop_at(records: Any, at: dt.datetime | None) -> tuple[str, Stop, str | None] | None:
    """The trip stop holding `at`, with the stop's name; None without records or an aware `at`."""
    if records is None or at is None or at.tzinfo is None:
        return None
    for rec in records.all():
        try:
            trip = trip_of(rec)
        except (KeyError, TypeError, ValueError):
            continue
        if trip.left_at > at or (trip.back_at is not None and trip.back_at < at):
            continue
        for stop in trip.stops:
            end = stop.end or trip.back_at
            if stop.start <= at and (end is None or at <= end):
                info = (rec.get("stops") or {}).get(stop.id) or {}
                return trip.id, stop, info.get("name")
    return None
