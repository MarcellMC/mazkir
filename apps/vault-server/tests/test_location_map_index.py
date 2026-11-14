"""Building the map index from OSM data (map spec §4.4)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from src.services.location.map_index import build_index, classify

FIXTURE = Path(__file__).parent / "fixtures" / "map_small.osm"


def _rows(db: Path) -> list[sqlite3.Row]:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        return con.execute("SELECT * FROM features").fetchall()
    finally:
        con.close()


def test_classify_by_key_not_by_value():
    assert classify({"shop": "pottery_studio"}) == ("place", "pottery_studio")
    assert classify({"highway": "residential"}) is None
    assert classify({"amenity": "cafe", "addr:housenumber": "5"}) == ("place", "cafe")
    assert classify({"addr:housenumber": "5"}) == ("address", "address")
    assert classify({"highway": "bus_stop"}) == ("transit_stop", "bus_stop")
    assert classify({"place": "neighbourhood"}) == ("area", "neighbourhood")
    assert classify({"building": "yes"}) is None
    assert classify({"leisure": "park", "amenity": "cafe"}) == ("place", "cafe")   # amenity is first


def test_build_counts_and_skips_roads(tmp_path):
    db = tmp_path / "index.sqlite"
    counts = build_index(FIXTURE, db)
    assert counts["place"] >= 4
    assert counts["address"] == 1 and counts["area"] == 1 and counts["transit_stop"] == 1
    rows = _rows(db)
    assert not [r for r in rows if r["kind"] in ("residential", "yes")]
    con = sqlite3.connect(db)
    assert con.execute("SELECT count(*) FROM features_rtree").fetchone()[0] == len(rows)


def test_areas_have_outlines_and_size(tmp_path):
    db = tmp_path / "index.sqlite"
    build_index(FIXTURE, db)
    [dog] = [r for r in _rows(db) if r["kind"] == "dog_park"]
    assert dog["osm"].startswith("w") and 700 < dog["area_m2"] < 1200
    rings = json.loads(dog["rings"])
    assert rings[0]["outer"] is True and len(rings[0]["points"]) >= 4


def test_names_are_kept_as_written(tmp_path):
    db = tmp_path / "index.sqlite"
    build_index(FIXTURE, db)
    [cafe] = [r for r in _rows(db) if r["name"] == "קפה ברזילי" and r["street"]]   # the index keeps duplicates
    assert cafe["name_en"] is None and cafe["street"] == "ברזילי" and cafe["osm"].startswith("n")
    [hood] = [r for r in _rows(db) if r["grp"] == "area"]
    assert hood["name_en"] == "Neve Sha'anan"
