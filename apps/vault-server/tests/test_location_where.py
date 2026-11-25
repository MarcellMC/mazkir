"""Photos and locations in words (repair spec §8): the model gets places, never numbers.

Made-up positions north of a point in the sea's latitude band: a café 10 m
north, a restaurant 25 m south, a bakery 55 m north, an address 8 m south,
a neighbourhood 300 m away.
"""

from __future__ import annotations

import datetime as dt
import re

import pytest

from src.services.fast_lane.places import Place
from src.services.location.handles import Handles
from src.services.location.map_index import build_index
from src.services.location.model import Stop, Trip
from src.services.location.records import TripRecords, new_record
from src.services.location.where import describe_where
from tests.location_fixtures import ZONE

LAT_M = 111_195.0
P = (32.1, 34.9)
CHAT = 7
COORD = re.compile(r"\d+\.\d{4,}")


def _north(m: float) -> tuple[float, float]:
    return P[0] + m / LAT_M, P[1]


OSM = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="mazkir-test">
  <node id="1" version="1" lat="{cafe[0]:.7f}" lon="{cafe[1]:.7f}">
    <tag k="amenity" v="cafe"/><tag k="name" v="Café X"/>
  </node>
  <node id="2" version="1" lat="{rest[0]:.7f}" lon="{rest[1]:.7f}">
    <tag k="amenity" v="restaurant"/><tag k="name" v="Restaurant Y"/>
  </node>
  <node id="3" version="1" lat="{bakery[0]:.7f}" lon="{bakery[1]:.7f}">
    <tag k="shop" v="bakery"/><tag k="name" v="Bakery Z"/>
  </node>
  <node id="4" version="1" lat="{addr[0]:.7f}" lon="{addr[1]:.7f}">
    <tag k="addr:street" v="Herzl"/><tag k="addr:housenumber" v="12"/>
  </node>
  <node id="5" version="1" lat="{area[0]:.7f}" lon="{area[1]:.7f}">
    <tag k="place" v="neighbourhood"/><tag k="name" v="Old North"/>
  </node>
</osm>
"""


@pytest.fixture(scope="module")
def index(tmp_path_factory):
    d = tmp_path_factory.mktemp("where")
    src = d / "where.osm"
    src.write_text(OSM.format(cafe=_north(10), rest=_north(-25), bakery=_north(55), addr=_north(-8),
                              area=_north(300)), encoding="utf-8")
    db = d / "index.sqlite"
    build_index(src, db)
    return db


@pytest.fixture
def handles(tmp_path):
    return Handles(tmp_path / "handles.json")


def _where(handles, index, places=(), accuracy=None, at=None, records=None, key="photo:p.jpg", pos=P):
    return describe_where(pos[0], pos[1], accuracy_m=accuracy, at=at, chat_id=CHAT, places=list(places),
                          map_index=index, handles=handles, records=records, anchor_key=key)


def test_at_home(handles, index):
    home = Place("home", "Home", (), "home", P[0], P[1], 40.0)
    out = _where(handles, index, places=[home])
    assert out == "at home"
    assert handles.resolve(CHAT, "m1") is None
    assert handles.resolve(CHAT, "photo:p.jpg")["kind"] == "anchor"


def test_near_places_and_address(handles, index):
    out = _where(handles, index, accuracy=15.0)
    assert out.startswith("where: ")
    assert "m1 Café X (café, 10 m)" in out
    assert "m2 Restaurant Y (restaurant, 20 m)" in out or "m2 Restaurant Y (restaurant, 30 m)" in out
    assert "Bakery Z" not in out
    assert "on Herzl, by number 12" in out
    assert "in Old North" in out
    assert out.endswith("| GPS ±15 m")
    assert not COORD.search(out)
    assert handles.resolve(CHAT, "m1")["label"] == "Café X"
    assert handles.resolve(CHAT, "photo:p.jpg")["accuracy_m"] == 15.0


def test_accuracy_widens_radius(handles, index):
    assert "Bakery Z" in _where(handles, index, accuracy=60.0)
    assert "Bakery Z" not in _where(handles, index, accuracy=None)


def test_a_place_of_yours_is_named_with_its_handle(handles, index):
    gym = Place("gym", "The gym", (), "sport", P[0], P[1], 60.0)
    out = _where(handles, index, places=[gym], key="location:42")
    assert out.startswith("where: place:gym The gym (yours, 0 m)")
    assert "Café X" not in out and "on Herzl, by number 12" in out and "in Old North" in out
    assert handles.resolve(CHAT, "location:42")["kind"] == "anchor"


def test_a_pause_spot_is_not_a_place(handles, index):
    pause = Place("pause-1", "pause", (), "pause", P[0], P[1], 60.0)
    assert "m1 Café X" in _where(handles, index, places=[pause])


def test_photo_during_stop(handles, index, tmp_path):
    records = TripRecords(tmp_path / "loc")
    start = dt.datetime(2026, 11, 20, 13, 0, tzinfo=ZONE)
    stop = Stop("s3", start, start + dt.timedelta(minutes=30), P[0], P[1], 10.0, 400.0)
    trip = Trip("abcd1234", "home", start - dt.timedelta(minutes=20), "location", [stop])
    records.save(new_record(trip))
    out = _where(handles, index, at=start + dt.timedelta(minutes=5), records=records,
                 pos=_north(500))   # the photo's own fix is off; the stop wins
    assert out.startswith("at stop s3 of trip abcd1234 (unnamed)")
    assert "m1 Café X (café, 10 m)" in out
    assert not COORD.search(out)

    rec = records.get("abcd1234")
    rec["stops"]["s3"] = {"status": "named", "name": "Coffee", "place": None}
    records.save(rec)
    assert _where(handles, index, at=start + dt.timedelta(minutes=5), records=records).startswith(
        "at stop s3 of trip abcd1234 (Coffee)")
    # Outside the stop: a fresh lookup.
    assert _where(handles, index, at=start + dt.timedelta(hours=2), records=records).startswith("where: ")


def test_no_map(handles):
    out = _where(handles, None)
    assert "no map here" in out
    assert not COORD.search(out)


def test_no_map_but_a_place_of_yours(handles):
    gym = Place("gym", "The gym", (), "sport", P[0], P[1], 60.0)
    assert _where(handles, None, places=[gym]).startswith("where: place:gym The gym (yours, 0 m)")
