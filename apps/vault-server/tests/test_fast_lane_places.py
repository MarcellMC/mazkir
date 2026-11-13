"""Spec §7.3: named places, matched by name or alias, bootstrapped from the ledger."""

import datetime as dt

from src.services.events_service import EventsService
from src.services.fast_lane.places import (
    Place, add_place, bootstrap_places, load_places, match_place, save_places,
)


def test_places_round_trip_and_match_by_name_or_alias(tmp_path):
    path = tmp_path / "places.json"
    save_places(path, [Place("gym", "Gym", ("the gym", "спортзал"), "sport")])
    places = load_places(path)
    assert places == [Place("gym", "Gym", ("the gym", "спортзал"), "sport")]
    assert match_place("at the gym", places).id == "gym"
    assert match_place("Спортзал", places).id == "gym"
    assert match_place("park", places) is None
    assert match_place(None, places) is None


def test_add_place_reuses_a_known_name_and_keeps_ids_unique(tmp_path):
    path = tmp_path / "places.json"
    first = add_place(path, "Park")
    assert add_place(path, "the park") == first
    second = add_place(path, "Park!")
    assert second.id == "park-2" and len(load_places(path)) == 2


def test_a_missing_file_is_no_places(tmp_path):
    assert load_places(tmp_path / "places.json") == []


def test_bootstrap_counts_location_names_already_in_the_ledger(tmp_path):
    events = EventsService(tmp_path / "events")
    for day in ("2026-09-26", "2026-09-27"):
        events.create_event(day, "Gym", f"{day}T18:00:00", f"{day}T19:00:00", location={"name": "Gym"})
    events.create_event("2026-09-27", "Cafe", "2026-09-27T10:00:00", "2026-09-27T11:00:00",
                        location={"name": "Cafe"})
    places = bootstrap_places(events, dt.date(2026, 9, 28), days=7, min_visits=2)
    assert [(p.id, p.name) for p in places] == [("gym", "Gym")]


# --- location trips, Task 2: coordinates, pause spots, home ----------------

import json

import pytest

from src.services.fast_lane.places import (
    PAUSE_KIND, PLACE_RADIUS_CAP_M, add_pause_spot, learn_place, nearest, set_home,
)


def test_coordinates_round_trip_and_old_entries_still_load(tmp_path):
    p = tmp_path / "places.json"
    p.write_text('{"places":[{"id":"abullafia","name":"Abullafia","aliases":[],"kind":null}]}')
    place, conflict = learn_place(p, "Alex's", 32.08, 34.78, spread_m=20)
    loaded = load_places(p)
    assert [x.id for x in loaded] == ["abullafia", "alex-s"]
    assert loaded[1].lat == 32.08 and loaded[1].radius_m == 60 and conflict is False
    assert "lat" not in json.loads(p.read_text())["places"][0]


def test_nearest_picks_the_containing_place():
    a = Place("a", "A", lat=32.0, lng=34.0, radius_m=60)
    assert nearest(32.0003, 34.0, [a]) == a          # ~33 m
    assert nearest(32.0010, 34.0, [a]) is None       # ~111 m
    assert nearest(32.0, 34.0, [Place("b", "B")]) is None   # no coordinates


def test_nearest_prefers_the_closer_centre():
    far = Place("far", "Far", lat=32.0004, lng=34.0, radius_m=100)
    near = Place("near", "Near", lat=32.0001, lng=34.0, radius_m=100)
    assert nearest(32.0, 34.0, [far, near]) == near


def test_learn_place_far_from_its_namesake_is_a_conflict(tmp_path):
    p = tmp_path / "places.json"
    learn_place(p, "Alex's", 32.08, 34.78, 20)
    place, conflict = learn_place(p, "Alex's", 32.10, 34.78, 20)   # ~2.2 km away
    assert conflict is True and load_places(p)[0].lat == 32.08


def test_a_named_place_without_coordinates_gains_them(tmp_path):
    p = tmp_path / "places.json"
    add_place(p, "Gym")
    place, conflict = learn_place(p, "the gym", 32.0, 34.0, 30)
    assert conflict is False and load_places(p)[0].lat == 32.0 and len(load_places(p)) == 1


def test_radius_grows_but_is_capped(tmp_path):
    p = tmp_path / "places.json"
    learn_place(p, "Park", 32.0, 34.0, 20)
    learn_place(p, "Park", 32.0005, 34.0, 50)        # ~56 m off, inside 60
    assert load_places(p)[0].radius_m == pytest.approx(105.6, abs=1)
    learn_place(p, "Park", 32.0009, 34.0, 100)
    assert load_places(p)[0].radius_m == PLACE_RADIUS_CAP_M == 150


def test_pause_spots_never_match_a_name(tmp_path):
    p = tmp_path / "places.json"
    spot = add_pause_spot(p, 32.0, 34.0, 10)
    assert spot.id == "pause-1" and spot.kind == PAUSE_KIND
    assert match_place("pause", load_places(p)) is None
    assert nearest(32.0, 34.0, load_places(p)).kind == "pause"
    assert add_pause_spot(p, 32.01, 34.0, 10).id == "pause-2"


def test_set_home_replaces_the_previous_home(tmp_path):
    p = tmp_path / "places.json"
    set_home(p, 32.0, 34.0)
    home = set_home(p, 32.001, 34.0)
    homes = [x for x in load_places(p) if x.id == "home"]
    assert homes == [home] and home.radius_m == 40 and home.name == "Home"
