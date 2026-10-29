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
