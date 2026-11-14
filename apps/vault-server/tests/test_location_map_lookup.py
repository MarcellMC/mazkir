"""Looking map places up near a stop (map spec §4.5, with the 1 ha ranking amendment).

The fixture (tests/fixtures/map_small.osm) uses made-up coordinates: a 120 m
park with a 30 m dog park inside it, a 5 ha park with a café inside it, a
café with a bus stop 30 m away, an address, a pharmacy, a neighbourhood.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.services.location.map_index import build_index
from src.services.location.map_lookup import MapPlace, kind_words, map_area, map_near

FIXTURE = Path(__file__).parent / "fixtures" / "map_small.osm"
LAT_M, LNG_M = 111195.0, 94300.0

DOG_PARK = (32.0 + 60 / LAT_M, 34.8 + 60 / LNG_M)
NEAR_PARK_CAFE = (32.011 + 10 / LAT_M, 34.8011)
BARZILAY = (32.02, 34.80)
ADDRESS = (32.03, 34.80)
PHARMACY = (32.05, 34.80)


@pytest.fixture(scope="module")
def index(tmp_path_factory):
    db = tmp_path_factory.mktemp("map") / "index.sqlite"
    build_index(FIXTURE, db)
    return db


def test_dog_park_inside_park_comes_first(index):
    found = map_near(index, *DOG_PARK, spread_m=10)
    assert [p.label for p in found][:2] == ["Dog park", "Park"]
    assert found[0].distance_m == 0


def test_small_containing_area_ranks_first(index):
    # 25 m inside the dog park's edge, the park's own outline is ~45 m away: containment wins.
    found = map_near(index, 32.0 + 50 / LAT_M, 34.8 + 50 / LNG_M, spread_m=10)
    assert found[0].kind == "dog_park" and found[0].distance_m == 0


def test_big_containing_area_counts_as_20m(index):
    found = map_near(index, *NEAR_PARK_CAFE, spread_m=10)
    assert [p.label for p in found][:2] == ["Park Café", "Big Park"]
    assert found[1].distance_m == 20


def test_radius_is_spread_plus_30_capped_at_80(index):
    at_70 = (PHARMACY[0] - 70 / LAT_M, PHARMACY[1])
    at_90 = (PHARMACY[0] - 90 / LAT_M, PHARMACY[1])
    assert [p.label for p in map_near(index, *at_70, spread_m=45)] == ["Super-Pharm"]
    assert map_near(index, *at_70, spread_m=20) == []
    assert map_near(index, *at_90, spread_m=100) == []


def test_addresses_only_when_no_place(index):
    [only] = map_near(index, *ADDRESS, spread_m=10)
    assert only.group == "address" and only.label == "Ha'Yarkon"
    assert all(p.group != "address" for p in map_near(index, *DOG_PARK, spread_m=10))


def test_transit_and_areas_are_not_buttons(index):
    found = map_near(index, *BARZILAY, spread_m=20)
    assert [p.label for p in found] == ["קפה ברזילי"]
    assert all(p.group == "place" for p in map_near(index, *DOG_PARK, spread_m=80))


def test_labels(index):
    [cafe] = map_near(index, *BARZILAY, spread_m=5)
    assert cafe.label == "קפה ברזילי" and cafe.name == "קפה ברזילי" and cafe.kind == "cafe"
    assert map_near(index, *DOG_PARK, spread_m=10)[0].name is None
    assert kind_words("pottery_studio") == "Pottery studio"
    assert kind_words("dog_park") == "Dog park" and kind_words("cafe") == "Café"


def test_map_area_names_the_neighbourhood(index):
    assert map_area(index, *DOG_PARK) == "Neve Sha'anan"
    assert map_area(index, *BARZILAY) is None


def test_missing_or_corrupt_index_returns_nothing(tmp_path):
    bad = tmp_path / "bad.sqlite"
    bad.write_bytes(b"not a database at all" * 10)
    for idx in (None, tmp_path / "missing.sqlite", bad):
        assert map_near(idx, *DOG_PARK, spread_m=10) == []
        assert map_area(idx, *DOG_PARK) is None


def test_lookup_during_swap_sees_old_or_new(tmp_path):
    live = tmp_path / "index.sqlite"
    build_index(FIXTURE, live)
    before = map_near(live, *DOG_PARK, spread_m=10)
    fresh = tmp_path / "index.sqlite.part"
    build_index(FIXTURE, fresh)
    os.replace(fresh, live)
    after = map_near(live, *DOG_PARK, spread_m=10)
    assert before and [p.label for p in before] == [p.label for p in after]


def test_to_dict_has_no_coordinates(index):
    d = map_near(index, *BARZILAY, spread_m=5)[0].to_dict()
    assert set(d) == {"osm", "group", "kind", "label", "name", "street", "distance_m"}
    assert isinstance(MapPlace(**d), MapPlace)
