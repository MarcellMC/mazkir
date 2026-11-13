"""Trip records: one JSON file per trip (plan Task 4)."""

import datetime as dt

from src.services.location.model import Leg, Trip
from src.services.location.records import TripRecords, new_record
from tests.location_fixtures import TZ, t


def trip(tid="1a2b3c4d", left=None):
    left = left or t(12, 22, 0)
    return Trip(tid, "home", left, "location", legs=[Leg(left, None)])


def test_save_get_and_open_ids(tmp_path):
    recs = TripRecords(tmp_path)
    rec = new_record(trip())
    recs.save(rec)
    assert recs.get("1a2b3c4d")["trip"]["origin"] == "home"
    assert recs.open_ids() == ["1a2b3c4d"]
    rec["closed"] = True
    recs.save(rec)
    assert recs.open_ids() == []
    assert recs.get("ffffffff") is None


def test_a_bad_id_never_builds_a_path(tmp_path):
    assert TripRecords(tmp_path).get("../../etc") is None


def test_on_day_is_by_left_at(tmp_path):
    recs = TripRecords(tmp_path)
    recs.save(new_record(trip("aaaaaaaa", t(12, 9, 0))))
    recs.save(new_record(trip("bbbbbbbb", t(13, 9, 0))))
    assert [r["id"] for r in recs.on_day(dt.date(2026, 11, 13), TZ)] == ["bbbbbbbb"]


def test_questions_on_uses_the_logical_day(tmp_path):
    recs = TripRecords(tmp_path)
    rec = new_record(trip())
    rec["stops"]["s1"] = {"status": "asked", "name": None, "place": None, "options": [],
                          "asked_at": t(13, 2, 0).isoformat()}
    recs.save(rec)
    assert recs.questions_on(dt.date(2026, 11, 12), TZ, 5) == 1
    assert recs.questions_on(dt.date(2026, 11, 13), TZ, 5) == 0


def test_trip_questions_count_too(tmp_path):
    recs = TripRecords(tmp_path)
    rec = new_record(trip())
    rec["trip_question"] = {"options": [], "asked_at": t(12, 23, 0).isoformat()}
    recs.save(rec)
    assert recs.questions_on(dt.date(2026, 11, 12), TZ, 5) == 1
