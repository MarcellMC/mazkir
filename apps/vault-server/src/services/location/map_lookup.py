"""What the map shows at a stop (map spec §4.5).

A pure read of the local index: no position ever leaves the machine. Each
call opens the file read-only, so an update swapping in a new index
(`os.replace`) is seen whole or not at all. A missing or broken index is
no map: `[]`, and the stop is asked about as it would be without one.

Street furniture (a bench, a parking spot, a recycling bin) is indexed but
never offered: nobody goes out to a bench, and "never filler" is the rule for
buttons (user, 2026-11-14). The same label is offered once.

Ranking:
1. containing areas of up to 1 ha, smallest first (the dog park before the
   park around it), at distance 0;
2. everything else by distance to its point or outline. A larger containing
   area counts as 20 m, so a café beside the stop beats the campus around it.
"""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

from src.services.geo import haversine_m

logger = logging.getLogger(__name__)

RADIUS_EXTRA_M = 30.0
RADIUS_CAP_M = 80.0
SMALL_AREA_M2 = 10_000.0
BIG_AREA_DISTANCE_M = 20.0
MAX_RESULTS = 8
AREA_NAME_RADIUS_M = 1500.0

_LAT_M = 111_195.0
_warned = False

# Values under a place key that are not somewhere you go (seen as filler in the 2026-11-14 replay).
NOT_A_DESTINATION = frozenset({
    "bench", "waste_basket", "waste_disposal", "recycling", "drinking_water", "bicycle_parking",
    "motorcycle_parking", "parking", "parking_entrance", "parking_space", "vending_machine", "post_box",
    "telephone", "charging_station", "fountain", "clock", "grit_bin", "shelter", "bicycle_repair_station",
    "compressed_air", "water_point", "letter_box", "picnic_table", "loading_dock",
})

KIND_WORDS = {
    "cafe": "Café", "dog_park": "Dog park", "pharmacy": "Pharmacy", "convenience": "Convenience store",
    "park": "Park", "playground": "Playground", "supermarket": "Supermarket", "restaurant": "Restaurant",
    "bar": "Bar", "pub": "Pub", "bakery": "Bakery", "fitness_centre": "Gym", "sauna": "Sauna",
    "bus_stop": "Bus stop", "fast_food": "Fast food", "ice_cream": "Ice cream", "kiosk": "Kiosk",
    "greengrocer": "Greengrocer", "butcher": "Butcher", "deli": "Deli", "clothes": "Clothes shop",
    "hairdresser": "Hairdresser", "doctors": "Doctor", "dentist": "Dentist", "clinic": "Clinic",
    "hospital": "Hospital", "school": "School", "kindergarten": "Kindergarten", "library": "Library",
    "post_office": "Post office", "bank": "Bank", "atm": "ATM", "fuel": "Petrol station",
    "pitch": "Sports pitch", "sports_centre": "Sports centre", "swimming_pool": "Swimming pool",
    "garden": "Garden", "community_centre": "Community centre", "place_of_worship": "Place of worship",
    "veterinary": "Vet", "pet": "Pet shop", "marketplace": "Market", "cinema": "Cinema",
    "theatre": "Theatre", "museum": "Museum", "hotel": "Hotel", "books": "Bookshop",
}


@dataclass(frozen=True)
class MapPlace:
    osm: str
    group: str
    kind: str
    label: str
    name: str | None
    street: str | None
    distance_m: float
    # The feature's own position, for the per-chat handle table (repair spec §7). Never in
    # `to_dict`: that dict goes into trip records and the decisions log.
    lat: float | None = field(default=None, repr=False, compare=False)
    lng: float | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("lat")
        d.pop("lng")
        return d


def kind_words(kind: str) -> str:
    return KIND_WORDS.get(kind) or kind.replace("_", " ").capitalize()


def _connect(index: Path | None) -> sqlite3.Connection | None:
    global _warned
    if index is None or not Path(index).exists():
        return None
    try:
        con = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        con.execute("SELECT 1 FROM features LIMIT 1")
        return con
    except sqlite3.Error as exc:
        if not _warned:
            from src.services.location.model import safe_error
            logger.warning("map index unreadable: %s", safe_error(exc))
            _warned = True
        return None


def _box(lat: float, lng: float, radius_m: float) -> tuple[float, float, float, float]:
    dlat = radius_m / _LAT_M
    dlng = radius_m / (_LAT_M * max(math.cos(math.radians(lat)), 0.01))
    return lat - dlat, lat + dlat, lng - dlng, lng + dlng


def _xy(lat: float, lng: float, lat0: float, lng0: float) -> tuple[float, float]:
    return (lng - lng0) * _LAT_M * math.cos(math.radians(lat0)), (lat - lat0) * _LAT_M


def _inside(x: float, y: float, ring: list[tuple[float, float]]) -> bool:
    hit = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


def _segment(x: float, y: float, a: tuple[float, float], b: tuple[float, float]) -> float:
    (x1, y1), (x2, y2) = a, b
    dx, dy = x2 - x1, y2 - y1
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))


def _area_distance(lat: float, lng: float, rings_json: str) -> tuple[bool, float]:
    """(contains, metres to the outline) for an area row."""
    rings = json.loads(rings_json)
    local = [(r["outer"], [_xy(p[0], p[1], lat, lng) for p in r["points"]]) for r in rings]
    contains = any(_inside(0.0, 0.0, pts) for outer, pts in local if outer) and \
        not any(_inside(0.0, 0.0, pts) for outer, pts in local if not outer)
    edge = min((_segment(0.0, 0.0, a, b) for _, pts in local for a, b in zip(pts, pts[1:])), default=math.inf)
    return contains, edge


def _label(row: sqlite3.Row) -> str:
    if row["grp"] == "address":
        return row["street"] or "an address"
    return row["name_en"] or row["name"] or kind_words(row["kind"])


def _query(con: sqlite3.Connection, lat: float, lng: float, radius_m: float, groups: tuple[str, ...]):
    lo_lat, hi_lat, lo_lng, hi_lng = _box(lat, lng, radius_m)
    marks = ",".join("?" * len(groups))
    return con.execute(
        f"SELECT f.* FROM features_rtree r JOIN features f ON f.id = r.id "
        f"WHERE r.max_lat >= ? AND r.min_lat <= ? AND r.max_lng >= ? AND r.min_lng <= ? AND f.grp IN ({marks})",
        (lo_lat, hi_lat, lo_lng, hi_lng, *groups)).fetchall()


def _ranked(rows, lat: float, lng: float, radius_m: float) -> list[tuple[tuple, MapPlace]]:
    out = []
    for row in rows:
        if row["grp"] == "place" and row["kind"] in NOT_A_DESTINATION:
            continue
        if row["rings"]:
            contains, edge = _area_distance(lat, lng, row["rings"])
            if contains and (row["area_m2"] or 0) <= SMALL_AREA_M2:
                key, dist = (0, row["area_m2"] or 0), 0.0
            elif contains:
                key, dist = (1, BIG_AREA_DISTANCE_M), BIG_AREA_DISTANCE_M
            elif edge <= radius_m:
                key, dist = (1, edge), edge
            else:
                continue
        else:
            dist = haversine_m(lat, lng, row["lat"], row["lng"])
            if dist > radius_m:
                continue
            key = (1, dist)
        out.append((key, MapPlace(row["osm"], row["grp"], row["kind"], _label(row), row["name_en"] or row["name"],
                                  row["street"], round(dist, 1), row["lat"], row["lng"])))
    out.sort(key=lambda kv: kv[0])
    seen: set[str] = set()
    unique = []
    for key, place in out:
        if place.label.casefold() not in seen:
            seen.add(place.label.casefold())
            unique.append((key, place))
    return unique


def map_near(index: Path | None, lat: float, lng: float, spread_m: float,
             radius_m: float | None = None) -> list[MapPlace]:
    """Places at a stop, best first; addresses only when no place is near. [] without a usable index.

    `radius_m` replaces the stop's radius (spread + 30 m, capped at 80 m) when given: a photo or a
    location message looks within `max(40 m, its GPS accuracy)`, uncapped (repair spec §8).
    """
    con = _connect(index)
    if con is None:
        return []
    radius = radius_m if radius_m is not None else min((spread_m or 0.0) + RADIUS_EXTRA_M, RADIUS_CAP_M)
    try:
        places = _ranked(_query(con, lat, lng, radius, ("place",)), lat, lng, radius)
        if not places:
            places = _ranked(_query(con, lat, lng, radius, ("address",)), lat, lng, radius)
        return [p for _, p in places[:MAX_RESULTS]]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def map_area(index: Path | None, lat: float, lng: float) -> str | None:
    """The nearest neighbourhood, quarter, suburb or city within 1.5 km, by its English name if it has one."""
    con = _connect(index)
    if con is None:
        return None
    try:
        rows = _query(con, lat, lng, AREA_NAME_RADIUS_M, ("area",))
        best = min(((haversine_m(lat, lng, r["lat"], r["lng"]), r) for r in rows), default=None,
                   key=lambda x: x[0])
        if best is None or best[0] > AREA_NAME_RADIUS_M:
            return None
        return best[1]["name_en"] or best[1]["name"]
    except sqlite3.Error:
        return None
    finally:
        con.close()


_FINALS = str.maketrans("ךםןףץ", "כמנפצ")
_NIQQUD = re.compile("[\u0591-\u05c7]")
_PUNCT = re.compile(r"[^\w\s]|_")


def _fold(text: str | None) -> str:
    """Comparable form: casefolded, no niqqud or punctuation, Hebrew final letters as their medial forms."""
    text = unicodedata.normalize("NFC", _NIQQUD.sub("", unicodedata.normalize("NFD", text or "")))
    return " ".join(_PUNCT.sub(" ", text.casefold().translate(_FINALS)).split())


def _match_rank(query: str, *fields: str | None) -> int | None:
    """0 exact, 1 prefix, 2 substring, over the best field; None when none match."""
    best = None
    for field in fields:
        f = _fold(field)
        if not f:
            continue
        rank = 0 if f == query else 1 if f.startswith(query) else 2 if query in f else None
        if rank is not None and (best is None or rank < best):
            best = rank
    return best


def map_search(index: Path | None, query: str, lat: float, lng: float, radius_m: float = 3000,
               limit: int = 8) -> list[MapPlace]:
    """Places and addresses near a point whose name (or street) matches: exact, prefix, substring, then nearest."""
    q = _fold(query)
    con = _connect(index) if q else None
    if con is None:
        return []
    try:
        hits = []
        for row in _query(con, lat, lng, radius_m, ("place", "address")):
            if row["grp"] == "place" and row["kind"] in NOT_A_DESTINATION:
                continue
            fields = (row["street"],) if row["grp"] == "address" else (row["name"], row["name_en"])
            rank = _match_rank(q, *fields)
            if rank is None:
                continue
            dist = haversine_m(lat, lng, row["lat"], row["lng"])
            if dist > radius_m:
                continue
            hits.append((rank, dist, MapPlace(row["osm"], row["grp"], row["kind"], _label(row),
                                              row["name_en"] or row["name"], row["street"], round(dist, 1),
                                              row["lat"], row["lng"])))
        hits.sort(key=lambda h: (h[0], h[1]))
        out, streets = [], set()
        for _, _, place in hits:
            if place.group == "address":
                if _fold(place.street) in streets:
                    continue
                streets.add(_fold(place.street))
            out.append(place)
        return out[:limit]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def nearest_address(index: Path | None, lat: float, lng: float,
                    radius_m: float = 60) -> tuple[str, str | None] | None:
    """(street, house number or None) of the nearest address within `radius_m`."""
    con = _connect(index)
    if con is None:
        return None
    try:
        best = None
        for row in _query(con, lat, lng, radius_m, ("address",)):
            if not row["street"]:
                continue
            dist = haversine_m(lat, lng, row["lat"], row["lng"])
            if dist <= radius_m and (best is None or dist < best[0]):
                best = (dist, row)
        if best is None:
            return None
        return best[1]["street"], best[1]["housenumber"] or None
    except sqlite3.Error:
        return None
    finally:
        con.close()


def map_address(index: Path | None, lat: float, lng: float, radius_m: float = 60) -> str | None:
    """'<street> <number>' of the nearest address, or the street alone when it has no number."""
    found = nearest_address(index, lat, lng, radius_m)
    if found is None:
        return None
    street, number = found
    return f"{street} {number}" if number else street


def street_named(index: Path | None, name: str, lat: float, lng: float, radius_m: float = 300) -> bool:
    """True when the name is a street here (an address has it) and no place nearby carries it (spec §7.5)."""
    q = _fold(name)
    con = _connect(index) if q else None
    if con is None:
        return False
    try:
        rows = _query(con, lat, lng, radius_m, ("place", "address"))
        near = [r for r in rows if haversine_m(lat, lng, r["lat"], r["lng"]) <= radius_m]
        if any(r["grp"] == "place" and q in (_fold(r["name"]), _fold(r["name_en"])) for r in near):
            return False
        return any(r["grp"] == "address" and _fold(r["street"]) == q for r in near)
    except sqlite3.Error:
        return False
    finally:
        con.close()
