"""Build the local map index from an OpenStreetMap file (map spec §4.4).

One SQLite file holds what a stop can be: places, addresses, area names and
transit stops. An R*Tree over each row's bounding box answers "what is near
here" without a server. The full download is kept next to it, so a new
index format is a rebuild, never a new download.

What is kept is a rule about OpenStreetMap's keys, not a list of
activities: anything filed under `amenity`, `shop`, `leisure`, `tourism`,
`healthcare`, `office`, `craft` or `sport` is a place, whatever its value.

Rows (`features`):
- `osm`: `n<id>` for a node, `w<id>` / `r<id>` for an area built from a way
  or a multipolygon relation.
- `grp` / `kind`: from `classify`.
- `name`, `name_en`, `street`, `housenumber`, `city`: as tagged.
- `lat`, `lng`: the node, or the centroid of an area's largest outer ring.
- `area_m2`: an area's size (outer rings minus inner ones), NULL for a node.
- `rings`: JSON `[{"outer": bool, "points": [[lat, lng], ...]}, ...]`, NULL
  for a node.

Open ways (a café drawn as a line) are rare and skipped.
"""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path

INDEX_VERSION = 1

PLACE_KEYS = ("amenity", "shop", "leisure", "tourism", "healthcare", "office", "craft", "sport")
AREA_PLACES = ("suburb", "quarter", "neighbourhood", "city")
_PUBLIC_TRANSPORT = ("platform", "station")
_RAILWAY = ("station", "halt", "tram_stop")
_BATCH = 10_000

_LAT_M = 111_195.0


def classify(tags: dict[str, str]) -> tuple[str, str] | None:
    """(group, kind) for what a stop can be, or None. Place, then transit stop, then address, then area."""
    for key in PLACE_KEYS:
        if tags.get(key):
            return "place", tags[key]
    if tags.get("highway") == "bus_stop":
        return "transit_stop", "bus_stop"
    if tags.get("public_transport") in _PUBLIC_TRANSPORT:
        return "transit_stop", tags["public_transport"]
    if tags.get("railway") in _RAILWAY:
        return "transit_stop", tags["railway"]
    if tags.get("addr:housenumber"):
        return "address", "address"
    if tags.get("place") in AREA_PLACES:
        return "area", tags["place"]
    return None


def _local(points: list[tuple[float, float]], lat0: float) -> list[tuple[float, float]]:
    k = _LAT_M * math.cos(math.radians(lat0))
    return [(lng * k, lat * _LAT_M) for lat, lng in points]


def _ring_area_centroid(points: list[tuple[float, float]]) -> tuple[float, float, float]:
    """(area in m², centroid lat, centroid lng) of one closed ring."""
    lat0 = points[0][0]
    xy = _local(points, lat0)
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(xy, xy[1:]):
        cross = x1 * y2 - x2 * y1
        a += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(a) < 1e-9:
        lat = sum(p[0] for p in points) / len(points)
        lng = sum(p[1] for p in points) / len(points)
        return 0.0, lat, lng
    cx, cy = cx / (3 * a), cy / (3 * a)
    k = _LAT_M * math.cos(math.radians(lat0))
    return abs(a) / 2, cy / _LAT_M, cx / k


_SCHEMA = """
CREATE TABLE features (
    id INTEGER PRIMARY KEY, osm TEXT NOT NULL, grp TEXT NOT NULL, kind TEXT NOT NULL,
    name TEXT, name_en TEXT, street TEXT, housenumber TEXT, city TEXT,
    lat REAL NOT NULL, lng REAL NOT NULL, area_m2 REAL, rings TEXT);
CREATE VIRTUAL TABLE features_rtree USING rtree(id, min_lat, max_lat, min_lng, max_lng);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _row(osm: str, group: str, kind: str, tags: dict[str, str], lat: float, lng: float,
         area_m2: float | None, rings: list | None) -> tuple:
    return (osm, group, kind, tags.get("name"), tags.get("name:en"), tags.get("addr:street"),
            tags.get("addr:housenumber"), tags.get("addr:city"), lat, lng, area_m2,
            json.dumps(rings, ensure_ascii=False) if rings is not None else None)


def build_index(src: Path, dest: Path) -> dict[str, int]:
    """Read `src` (.osm or .osm.pbf) and write a fresh index to `dest`. Returns the row count per group."""
    import osmium

    dest = Path(dest)
    if dest.exists():
        dest.unlink()
    con = sqlite3.connect(dest)
    counts = {"place": 0, "address": 0, "area": 0, "transit_stop": 0}
    try:
        con.executescript(_SCHEMA)
        batch: list[tuple[tuple, tuple[float, float, float, float]]] = []

        def flush() -> None:
            for row, box in batch:
                cur = con.execute(
                    "INSERT INTO features (osm, grp, kind, name, name_en, street, housenumber, city,"
                    " lat, lng, area_m2, rings) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", row)
                con.execute("INSERT INTO features_rtree VALUES (?,?,?,?,?)", (cur.lastrowid, *box))
            con.commit()
            batch.clear()

        processor = (osmium.FileProcessor(str(src)).with_locations().with_areas()
                     .with_filter(osmium.filter.EmptyTagFilter()))
        for obj in processor:
            if obj.is_node():
                tags = dict(obj.tags)
                kind = classify(tags)
                if kind is None or not obj.location.valid():
                    continue
                lat, lng = obj.location.lat, obj.location.lon
                batch.append((_row(f"n{obj.id}", *kind, tags, lat, lng, None, None), (lat, lat, lng, lng)))
            elif obj.is_area():
                tags = dict(obj.tags)
                kind = classify(tags)
                if kind is None:
                    continue
                rings: list[dict] = []
                size = 0.0
                best: tuple[float, float, float] | None = None
                for outer in obj.outer_rings():
                    pts = [(n.lat, n.lon) for n in outer]
                    a, clat, clng = _ring_area_centroid(pts)
                    rings.append({"outer": True, "points": [[la, lo] for la, lo in pts]})
                    size += a
                    if best is None or a > best[0]:
                        best = (a, clat, clng)
                    for inner in obj.inner_rings(outer):
                        ipts = [(n.lat, n.lon) for n in inner]
                        size -= _ring_area_centroid(ipts)[0]
                        rings.append({"outer": False, "points": [[la, lo] for la, lo in ipts]})
                if best is None:
                    continue
                lats = [p[0] for r in rings for p in r["points"]]
                lngs = [p[1] for r in rings for p in r["points"]]
                osm = f"{'w' if obj.from_way() else 'r'}{obj.orig_id()}"
                batch.append((_row(osm, *kind, tags, best[1], best[2], max(size, 0.0), rings),
                              (min(lats), max(lats), min(lngs), max(lngs))))
            else:
                continue
            counts[kind[0]] += 1
            if len(batch) >= _BATCH:
                flush()
        flush()
        con.execute("INSERT INTO meta VALUES ('index_version', ?)", (str(INDEX_VERSION),))
        con.commit()
    finally:
        con.close()
    return counts
