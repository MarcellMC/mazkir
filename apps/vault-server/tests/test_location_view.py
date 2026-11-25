"""Repair spec §7.1-7.3: reading a trip, finding places and visits (plan Task 11).

Whatever these return goes to the model: no coordinate, no OSM id.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src.services.fast_lane.places import Place, load_places, save_places
from src.services.location.handles import Handles
from src.services.location.map_index import build_index
from src.services.location.view import find_place, find_visit, get_trip, logical_day
from src.services.location_store import append_point
from tests.location_fixtures import HOME, TZ, Track, at, t
from tests.test_location_edits import TRIP, closed_trip

FIXTURE = Path(__file__).parent / "fixtures" / "map_small.osm"
CHAT = 156175834
LAT_M, LNG_M = 111195.0, 94300.0
BARZILAY = (32.02, 34.80)


@pytest.fixture(scope="module")
def index(tmp_path_factory):
    db = tmp_path_factory.mktemp("map") / "index.sqlite"
    build_index(FIXTURE, db)
    return db


def handles_for(tmp_path):
    return Handles(tmp_path / "handles.json")


def assert_clean(result) -> None:
    """The coordinate check: no OSM id and no long decimal anywhere in what is returned."""
    text = json.dumps(result, ensure_ascii=False)
    assert not re.search(r"\d+\.\d{4,}", text), text
    assert not re.search(r"(node|way|relation)/\d+", text), text
    assert '"osm"' not in text and '"lat"' not in text and '"lng"' not in text


def move_stop_to(deps, stop_id, lat, lng):
    rec = deps.records.get(TRIP)
    for s in rec["trip"]["stops"]:
        if s["id"] == stop_id:
            s["lat"], s["lng"] = lat, lng
    deps.records.save(rec)


# --- get_trip --------------------------------------------------------------------

def test_get_trip_by_id(tmp_path):
    deps, _ = closed_trip(tmp_path)
    out = get_trip(deps, handles_for(tmp_path), CHAT, trip_id=TRIP)
    [trip] = out["trips"]
    assert trip["id"] == TRIP and trip["closed"] is True
    assert [s["id"] for s in trip["stops"]] == ["s1", "s2"]
    assert trip["stops"][0]["status"] == "later"
    assert trip["left"].startswith("2026-11-13T10:") and trip["back"].startswith("2026-11-13T11:")
    assert trip["blocks"][0]["part"] == "trip" and trip["blocks"][0]["state"] == "pending"
    assert trip["split_from"] is None and trip["joined_into"] is None
    assert_clean(out)


def test_get_trip_default_is_the_latest(tmp_path):
    deps, _ = closed_trip(tmp_path)
    assert get_trip(deps, handles_for(tmp_path), CHAT)["trips"][0]["id"] == TRIP


def test_get_trip_by_date_uses_the_logical_day(tmp_path):
    deps, _ = closed_trip(tmp_path)
    assert [x["id"] for x in get_trip(deps, handles_for(tmp_path), CHAT, date="2026-11-13")["trips"]] == [TRIP]
    assert get_trip(deps, handles_for(tmp_path), CHAT, date="2026-11-12")["trips"] == []
    # A trip at 01:30 belongs to the day before (boundary 05:00).
    assert logical_day(t(13, 1, 30), TZ, 5).isoformat() == "2026-11-12"
    assert logical_day(t(13, 5, 0), TZ, 5).isoformat() == "2026-11-13"
    rec = deps.records.get(TRIP)
    rec["trip"]["left_at"] = t(13, 1, 30).isoformat()
    deps.records.save(rec)
    assert [x["id"] for x in get_trip(deps, handles_for(tmp_path), CHAT, date="2026-11-12")["trips"]] == [TRIP]
    assert get_trip(deps, handles_for(tmp_path), CHAT, date="2026-11-13")["trips"] == []


def test_dismissed_blocks_are_listed(tmp_path):
    deps, _ = closed_trip(tmp_path)
    rec = deps.records.get(TRIP)
    ref = rec["blocks"]["trip"]
    deps.run_tool("update_event", {"event_id": ref["event_id"], "date": ref["date"]})  # no-op update
    day = ref["date"]
    events = deps.events.get_events(day)
    for e in events:
        if e["id"] == ref["event_id"]:
            e["state"] = "dismissed"
    deps.events.save_events(day, events)
    [trip] = get_trip(deps, handles_for(tmp_path), CHAT, trip_id=TRIP)["trips"]
    assert [(b["part"], b["state"]) for b in trip["blocks"]] == [("trip", "dismissed")]


def test_map_places_at_a_stop_are_handles(tmp_path, index):
    deps, _ = closed_trip(tmp_path)
    deps.map_index = index
    move_stop_to(deps, "s1", 32.05, 34.80)             # the pharmacy
    handles = handles_for(tmp_path)
    out = get_trip(deps, handles, CHAT, trip_id=TRIP)
    seen = out["trips"][0]["stops"][0]["map"]
    assert seen and seen[0]["label"] == "Super-Pharm"
    assert re.fullmatch(r"m\d+", seen[0]["ref"])
    assert seen[0]["distance_m"] % 10 == 0
    assert handles.resolve(CHAT, seen[0]["ref"])["label"] == "Super-Pharm"
    assert_clean(out)


# --- find_place ------------------------------------------------------------------

def test_find_place_returns_handles_not_ids(tmp_path, index):
    deps, _ = closed_trip(tmp_path)
    deps.map_index = index
    move_stop_to(deps, "s2", 32.05, 34.80)
    out = find_place(deps, handles_for(tmp_path), CHAT, "super", near=f"stop:{TRIP}:s2")
    assert out["near"] == f"stop:{TRIP}:s2"
    [p] = out["places"]
    assert p["label"] == "Super-Pharm" and re.fullmatch(r"m\d+", p["ref"])
    assert p["group"] == "place" and p["distance_m"] == 0
    assert_clean(out)


def test_find_place_default_near_is_the_latest_trip_farthest_stop(tmp_path, index):
    deps, _ = closed_trip(tmp_path)
    deps.map_index = index
    move_stop_to(deps, "s2", 32.05, 34.80)
    out = find_place(deps, handles_for(tmp_path), CHAT, "pharm")
    assert out["near"] == f"trip:{TRIP}"
    assert [p["label"] for p in out["places"]] == ["Super-Pharm"]


def test_user_place_outranks_a_map_place_of_the_same_name(tmp_path, index):
    deps, _ = closed_trip(tmp_path)
    deps.map_index = index
    move_stop_to(deps, "s2", 32.05, 34.80)
    save_places(deps.places_path, [*load_places(deps.places_path),
                                   Place("super-pharm", "Super-Pharm", (), None, 32.0502, 34.80, 60.0)])
    out = find_place(deps, handles_for(tmp_path), CHAT, "super-pharm", near=f"stop:{TRIP}:s2")
    assert out["places"][0]["ref"] == "place:super-pharm"
    assert out["places"][0]["group"] == "yours"
    assert_clean(out)


def test_find_place_far_away_and_nothing_found(tmp_path, index):
    deps, _ = closed_trip(tmp_path)
    deps.map_index = index
    out = find_place(deps, handles_for(tmp_path), CHAT, "pharm", near="home")   # home is ~5 km from it
    assert out["places"] == []


def test_find_place_near_a_photo_anchor(tmp_path, index):
    deps, _ = closed_trip(tmp_path)
    deps.map_index = index
    handles = handles_for(tmp_path)
    handles.anchor(CHAT, "photo:img1.jpg", 32.05, 34.80, 12.0)
    out = find_place(deps, handles, CHAT, "super", near="photo:img1.jpg")
    assert [p["label"] for p in out["places"]] == ["Super-Pharm"]
    with pytest.raises(KeyError, match="search again"):
        find_place(deps, handles, CHAT, "super", near="photo:other.jpg")
    assert_clean(out)


# --- find_visit ------------------------------------------------------------------

def visit_deps(tmp_path, spans, place=(0.0, 0.0), accuracy=10.0):
    """A deps whose raw points sit at the place during `spans` (minutes after 10:00 on the 13th)."""
    deps, _ = closed_trip(tmp_path)
    rec = deps.records.get(TRIP)
    # Points far from home in a day with no trips of their own: write them to a later day's file.
    base = t(14, 10, 0)
    lat, lng = at(5000, 5000)
    import datetime as dt
    for a, b in spans:
        k = a
        while k <= b:
            ts = base + dt.timedelta(minutes=k)
            acc = accuracy[k % len(accuracy)] if isinstance(accuracy, (list, tuple)) else accuracy
            append_point(tmp_path / "loc", {"source": "telegram", "kind": "live", "ts": ts, "lat": lat, "lng": lng,
                                             "accuracy_m": acc}, TZ)
            k += 1
    handles = handles_for(tmp_path)
    handles.anchor(CHAT, "location:7", lat, lng)
    return deps, handles


def test_visit_with_a_silence_inside_is_one(tmp_path):
    deps, handles = visit_deps(tmp_path, [(0, 2), (6, 8)])            # 4 min of silence inside 8
    out = find_visit(deps, handles, CHAT, "location:7", date="2026-11-14")
    [v] = out["visits"]
    assert v["start"].endswith("10:00+02:00") and v["end"].endswith("10:08+02:00")
    assert v["quality"] == "good" and v["stop_id"] is None
    assert out["closest"]["distance_m"] == 0
    assert_clean(out)


def test_a_two_minute_stay_is_no_visit(tmp_path):
    deps, handles = visit_deps(tmp_path, [(0, 2)])
    out = find_visit(deps, handles, CHAT, "location:7", date="2026-11-14")
    assert out["visits"] == []
    assert out["closest"]["distance_m"] == 0                          # says how close it came
    assert_clean(out)


def test_a_silence_over_ten_minutes_splits(tmp_path):
    deps, handles = visit_deps(tmp_path, [(0, 4), (20, 24)])
    out = find_visit(deps, handles, CHAT, "location:7", date="2026-11-14")
    assert len(out["visits"]) == 2
    assert_clean(out)


def test_poor_accuracy_is_poor_quality(tmp_path):
    deps, handles = visit_deps(tmp_path, [(0, 6)], accuracy=45.0)
    out = find_visit(deps, handles, CHAT, "location:7", date="2026-11-14")
    [v] = out["visits"]
    assert v["quality"] == "poor"
    assert_clean(out)


def test_quality_is_good_when_half_the_points_are_good(tmp_path):
    # accuracy alternates 10 / 45 m: exactly half are <= 30 m
    deps, handles = visit_deps(tmp_path, [(0, 7)], accuracy=[10.0, 45.0])
    out = find_visit(deps, handles, CHAT, "location:7", date="2026-11-14")
    assert out["visits"][0]["quality"] == "good"
    assert_clean(out)
    # one good point in four: poor
    deps, handles = visit_deps(tmp_path / "b", [(0, 7)], accuracy=[10.0, 45.0, 45.0, 45.0])
    out = find_visit(deps, handles, CHAT, "location:7", date="2026-11-14")
    assert out["visits"][0]["quality"] == "poor"
    assert_clean(out)


def test_no_visit_reports_the_closest_approach(tmp_path):
    deps, handles = visit_deps(tmp_path, [(0, 6)])
    handles.anchor(CHAT, "location:8", *at(5300, 5000))               # 300 m away
    out = find_visit(deps, handles, CHAT, "location:8", date="2026-11-14")
    assert out["visits"] == [] and out["closest"]["distance_m"] == 300
    assert_clean(out)


def test_visit_lands_in_a_stop_of_the_trip(tmp_path):
    deps, _ = closed_trip(tmp_path)
    s1 = next(s for s in deps.records.get(TRIP)["trip"]["stops"] if s["id"] == "s1")
    handles = handles_for(tmp_path)
    handles.anchor(CHAT, "location:1", s1["lat"], s1["lng"])
    # the recorded track itself rests there for 17 minutes
    from tests.test_location_edits import record_points, two_stops
    record_points(two_stops(), tmp_path)
    out = find_visit(deps, handles, CHAT, "location:1", trip_id=TRIP)
    assert out["visits"] and out["visits"][0]["stop_id"] == "s1"
    assert_clean(out)


def test_unknown_ref_is_search_again(tmp_path):
    deps, _ = closed_trip(tmp_path)
    with pytest.raises(KeyError, match="search again"):
        find_visit(deps, handles_for(tmp_path), CHAT, "m99", trip_id=TRIP)


def test_no_fixes_at_all_returns_a_clean_empty_result(tmp_path):
    deps, _ = closed_trip(tmp_path)
    handles = handles_for(tmp_path)
    handles.anchor(CHAT, "location:3", *at(500, 0))
    out = find_visit(deps, handles, CHAT, "location:3", date="2026-11-20")
    assert out == {"visits": [], "closest": None}
    assert_clean(out)
