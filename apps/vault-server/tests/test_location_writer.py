"""Trips spec §4.2, §4.3, §6.5: trips become proposed blocks, merged with yours."""

from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock

import pytest

from src.services.agent_service import AgentService
from src.services.approval import resolve_state
from src.services.events_service import EventsService
from src.services.fast_lane.places import Place
from src.services.location.model import Leg, Stop, Trip
from src.services.location.records import new_record
from src.services.location.writer import apply_blocks, plan_blocks
from tests.location_fixtures import TZ, t


@pytest.fixture
def store(tmp_path):
    events = EventsService(events_path=tmp_path / "events")
    agent = AgentService(claude=MagicMock(), vault=MagicMock(), memory=MagicMock(), calendar=None,
                         events=events, media_path=tmp_path / "media")
    return events, agent.run_tool


def stop(sid, start, end, from_home=300.0, place_id=None):
    return Stop(sid, start, end, 32.0, 34.0, 8.0, from_home, place_id)


def record(left, back, stops=(), legs=None, purpose=None, named=None, distance=1100.0, tid="1a2b3c4d"):
    legs = legs or [Leg(left, back, distance, "walk")]
    trip = Trip(tid, "home", left, "location", list(stops), legs, back, "location" if back else None,
                distance, 500.0)
    rec = new_record(trip)
    rec["purpose"] = purpose
    for s in stops:
        rec["stops"][s.id] = {"status": "unnamed", "name": None, "place": None, "options": [], "asked_at": None}
    for sid, (name, place) in (named or {}).items():
        rec["stops"][sid].update({"status": "named", "name": name, "place": place})
    return rec


def apply(rec, store, places=()):
    events, run_tool = store
    return apply_blocks(rec, plan_blocks(rec, list(places)), run_tool=run_tool, events=events, tz=TZ)


WALK = {"name": "Dog walk", "destination": None, "source": "guess"}


def test_unnamed_stops_get_no_block():
    stops = [stop("s1", t(8, 7, 40), t(8, 7, 46)), stop("s2", t(8, 8, 30), t(8, 8, 36)),
             stop("s3", t(8, 9, 10), t(8, 9, 14))]
    rec = record(t(8, 7, 20), t(8, 10, 10), stops, purpose=WALK)
    specs = plan_blocks(rec, [])
    assert [(s.part, s.name) for s in specs] == [("trip", "Dog walk")]


def test_named_stop_inside_an_activity_overlaps_it():
    stops = [stop("s1", t(9, 8, 0), t(9, 8, 4)), stop("s2", t(9, 8, 10), t(9, 8, 25))]
    rec = record(t(9, 7, 50), t(9, 9, 0), stops, purpose={"name": "Walk with Dana", "destination": None},
                 named={"s2": ("Coffee at Gan Meir", "Gan Meir")})
    specs = plan_blocks(rec, [])
    assert [s.part for s in specs] == ["trip", "stop:s2"]
    assert specs[0].start < specs[1].start < specs[1].end < specs[0].end
    assert specs[1].place_text == "Gan Meir"


def test_travel_trip_becomes_legs_and_stops():           # 7 Nov morning
    s1 = stop("s1", t(7, 8, 4), t(7, 9, 14), 1750, place_id="gan-meir")
    legs = [Leg(t(7, 7, 54), t(7, 8, 4), 1750, "walk"), Leg(t(7, 9, 14), t(7, 9, 50), 1750, "walk")]
    rec = record(t(7, 7, 54), t(7, 9, 50), [s1], legs, {"name": "Coffee at Gan Meir", "destination": "Gan Meir"},
                 named={"s1": ("Café at Gan Meir", "Gan Meir")})
    specs = plan_blocks(rec, [Place("gan-meir", "Gan Meir")])
    assert [s.name for s in specs] == ["Walk to Gan Meir", "Café at Gan Meir", "Walk home"]
    assert specs[1].place_id == "gan-meir"
    assert [s.part for s in specs] == ["leg:1", "stop:s1", "leg:2"]


def test_unnamed_stops_never_split_a_leg():
    s1 = stop("s1", t(6, 19, 50), t(6, 19, 55))
    s2 = stop("s2", t(6, 20, 10), None, 2400)
    rec = record(t(6, 19, 36), None, [s1, s2], [Leg(t(6, 19, 36), t(6, 20, 10), 2400, "vehicle")],
                 {"name": "Alex's birthday", "destination": "Alex's"}, named={"s2": ("Alex's birthday", "Alex's")})
    assert [s.name for s in plan_blocks(rec, [])] == ["Drive to Alex's", "Alex's birthday"]


def test_short_leg_folds_into_the_shop():                # 9 Nov 20:29
    s1 = stop("s1", t(9, 20, 29), t(9, 20, 32), 48)
    legs = [Leg(t(9, 20, 28), t(9, 20, 29), 50, "walk"), Leg(t(9, 20, 32), t(9, 20, 33), 50, "walk")]
    rec = record(t(9, 20, 28), t(9, 20, 33), [s1], legs, {"name": "Convenience store", "destination": "Convenience store"})
    specs = plan_blocks(rec, [])
    assert [s.name for s in specs] == ["Convenience store"]
    assert (specs[0].start, specs[0].end) == (t(9, 20, 28), t(9, 20, 33))


def test_unknown_trips_are_named_trip():
    assert plan_blocks(record(t(9, 18, 2), None), [])[0].name == "Trip"
    assert plan_blocks(record(t(9, 18, 2), t(9, 18, 40)), [])[0].name == "Trip 1.1 km"
    assert plan_blocks(record(t(9, 18, 2), t(9, 18, 40), distance=350), [])[0].name == "Trip 350 m"


def test_trip_block_is_a_pending_proposal(store):
    events, _ = store
    rec = apply(record(t(9, 20, 0), t(9, 20, 13), purpose=WALK), store)
    [e] = events.get_events("2026-11-09")
    assert e["proposed"] is True and e["trip"] == {"id": "1a2b3c4d", "part": "trip"}
    assert resolve_state(e) == "pending" and e["name"] == "Dog walk"
    assert e["start_time"] == "2026-11-09T20:00:00" and e["end_time"] == "2026-11-09T20:13:00"
    assert rec["blocks"]["trip"] == {"date": "2026-11-09", "event_id": e["id"]}


def test_an_ongoing_trip_is_an_open_block_then_closes(store):
    events, _ = store
    rec = apply(record(t(9, 20, 0), None), store)
    assert events.get_events("2026-11-09")[0]["end_time"] is None
    rec["trip"]["back_at"] = t(9, 20, 13).isoformat()
    rec["purpose"] = WALK
    apply(rec, store)
    [e] = events.get_events("2026-11-09")
    assert e["end_time"] == "2026-11-09T20:13:00" and e["name"] == "Dog walk" and e["user_set"] == {}


def test_apply_twice_writes_once(store):
    events, _ = store
    rec = record(t(9, 20, 0), t(9, 20, 13), purpose=WALK)
    apply(rec, store)
    apply(rec, store)
    assert len(events.get_events("2026-11-09")) == 1


def test_completes_your_block_and_keeps_your_name(store):    # "Dog walk 10:24" with no end
    events, _ = store
    events.create_event(date="2026-11-06", name="Dog walk", start_time="2026-11-06T10:24:00")
    rec = apply(record(t(6, 10, 24), t(6, 10, 38), purpose={"name": "Walk", "destination": None}), store)
    [e] = events.get_events("2026-11-06")
    assert e["name"] == "Dog walk" and e["end_time"] == "2026-11-06T10:38:00"
    assert e["start_time"] == "2026-11-06T10:24:00" and e["end_precision"] == "location"
    assert rec["merged"]["trip"]["filled"] == {"end_time": None} and "trip" not in rec["blocks"]


def test_message_time_inferred_start_is_replaced(store):
    events, _ = store
    events.create_event(date="2026-11-06", name="Dog walk", start_time="2026-11-06T10:35:00",
                        fields={"start_precision": "inferred"})
    apply(record(t(6, 10, 24), t(6, 10, 38), purpose=WALK), store)
    [e] = events.get_events("2026-11-06")
    assert e["start_time"] == "2026-11-06T10:24:00" and e["start_precision"] == "location"


def test_big_disagreement_is_reported_not_written(store):
    events, _ = store
    events.create_event(date="2026-11-06", name="Dog walk", start_time="2026-11-06T09:40:00",
                        end_time="2026-11-06T10:00:00")
    rec = apply(record(t(6, 9, 45), t(6, 10, 38), purpose=WALK), store)
    [e] = events.get_events("2026-11-06")
    assert rec["merged"]["trip"]["disagree"] == {"field": "end_time", "location_value": "10:38"}
    assert e["end_time"] == "2026-11-06T10:00:00"


def test_your_later_block_absorbs_the_trip_block(store):     # the reverse direction
    events, _ = store
    rec = apply(record(t(9, 10, 20), None, purpose=WALK), store)
    events.create_event(date="2026-11-09", name="Dog walk", start_time="2026-11-09T10:25:00")
    rec["trip"]["back_at"] = t(9, 10, 50).isoformat()
    apply(rec, store)
    [e] = events.get_events("2026-11-09")
    assert e["name"] == "Dog walk" and e.get("proposed") is not True and e["end_time"] == "2026-11-09T10:50:00"


def test_pinned_fields_are_not_overwritten(store):           # Review Focus 4
    events, _ = store
    rec = apply(record(t(9, 10, 20), None, purpose=WALK), store)
    eid = rec["blocks"]["trip"]["event_id"]
    events.update_event(date="2026-11-09", event_id=eid, updates={"start_time": "2026-11-09T10:15:00"},
                        user_set_fields=["start_time"])
    rec["trip"]["back_at"] = t(9, 10, 50).isoformat()
    apply(rec, store)
    e = events.get_events("2026-11-09")[0]
    assert e["start_time"] == "2026-11-09T10:15:00" and e["end_time"] == "2026-11-09T10:50:00"


def test_a_dismissed_block_is_left_alone(store):
    events, _ = store
    rec = apply(record(t(9, 10, 20), None, purpose=WALK), store)
    eid = rec["blocks"]["trip"]["event_id"]
    events.update_event(date="2026-11-09", event_id=eid, updates={"state": "dismissed"})
    rec["trip"]["back_at"] = t(9, 10, 50).isoformat()
    apply(rec, store)
    [e] = events.get_events("2026-11-09")
    assert e["end_time"] is None and e["state"] == "dismissed"


def test_parts_no_longer_planned_are_removed(store):
    events, _ = store
    s1 = stop("s1", t(7, 8, 4), t(7, 9, 14), 1750)
    legs = [Leg(t(7, 7, 54), t(7, 8, 4), 1750, "walk"), Leg(t(7, 9, 14), t(7, 9, 50), 1750, "walk")]
    rec = apply(record(t(7, 7, 54), t(7, 9, 50), [s1], legs), store)
    assert list(rec["blocks"]) == ["trip"]
    rec["purpose"] = {"name": "Coffee at Gan Meir", "destination": "Gan Meir"}
    rec["stops"]["s1"].update({"status": "named", "name": "Café at Gan Meir", "place": "Gan Meir"})
    rec = apply(rec, store)
    assert sorted(rec["blocks"]) == ["leg:1", "leg:2", "stop:s1"]
    assert sorted(e["name"] for e in events.get_events("2026-11-07")) == ["Café at Gan Meir", "Walk home", "Walk to Gan Meir"]


def test_cross_midnight_block_is_split(store):
    events, _ = store
    s1 = stop("s1", t(6, 20, 10), None, 2400)
    rec = record(t(6, 19, 36), None, [s1], [Leg(t(6, 19, 36), t(6, 20, 10), 2400, "vehicle")],
                 {"name": "Alex's birthday", "destination": "Alex's"}, named={"s1": ("Alex's birthday", "Alex's")})
    rec = apply(rec, store)
    s1_end = t(7, 7, 54)
    rec["trip"]["stops"][0]["end"] = s1_end.isoformat()
    rec = apply(rec, store)
    first = [e for e in events.get_events("2026-11-06") if e["name"] == "Alex's birthday"]
    second = [e for e in events.get_events("2026-11-07") if e["name"] == "Alex's birthday"]
    assert len(first) == 1 and len(second) == 1
    assert first[0]["logical_id"] and first[0]["logical_id"] == second[0]["logical_id"]
