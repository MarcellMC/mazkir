"""Trips spec §6.2, §6.3: the question at a stop and the message when you are back."""

import json

import pytest

from src.services.events_service import EventsService
from src.services.location.decide import Option
from src.services.location.messages import arrival_receipt, notice_receipt, question_receipt
from src.services.location.model import Leg, Stop, Trip
from src.services.location.records import new_record
from tests.location_fixtures import TZ, t


def rec_with_stop(place_from_home=700.0):
    left = t(10, 10, 16)
    stop = Stop("s1", t(10, 10, 24), None, 32.0853, 34.7818, 8.0, place_from_home)
    trip = Trip("1a2b3c4d", "home", left, "location", [stop], [Leg(left, stop.start, 700.0, "walk")],
                distance_m=1100.0, max_from_home_m=705.0)
    return new_record(trip)


def buttons(receipt):
    return [b for line in receipt["lines"] for b in line["buttons"]]


def test_every_callback_fits_64_bytes():
    r = question_receipt(rec_with_stop(), "s1", [Option("A" * 80)] * 3, t(10, 10, 28), TZ)
    assert all(len(b["data"].encode()) <= 64 for b in buttons(r))
    assert all(len(b["label"]) <= 32 for b in buttons(r))


def test_stop_question_offers_pause_and_type():
    r = question_receipt(rec_with_stop(), "s1", [Option("Coffee"), Option("Sauna")], t(10, 10, 28), TZ)
    assert [b["label"] for b in buttons(r)] == ["Coffee", "Sauna", "Just a pause", "✎ Something else", "Later"]
    assert [b["data"] for b in buttons(r)] == ["trip:1a2b3c4d:s1:a0", "trip:1a2b3c4d:s1:a1",
                                                "trip:1a2b3c4d:s1:p", "trip:1a2b3c4d:s1:t", "trip:1a2b3c4d:s1:l"]
    assert "since 10:24" in r["lines"][0]["text"] and "700 m from home" in r["lines"][0]["text"]
    assert r["open_question"].endswith("[trip 1a2b3c4d · stop s1]")
    assert r["undo"] is None and r["turn_id"] == "1a2b3c4d"


def test_trip_question_has_no_pause_button():
    rec = rec_with_stop()
    rec["trip"]["back_at"] = t(10, 10, 54).isoformat()
    r = question_receipt(rec, None, [Option("Run")], t(10, 10, 55), TZ)
    assert [b["label"] for b in buttons(r)] == ["Run", "✎ Something else"]
    assert buttons(r)[0]["data"] == "trip:1a2b3c4d:trip:a0"
    assert "10:16–10:54, 1.1 km" in r["lines"][0]["text"] and r["open_question"].endswith("[trip 1a2b3c4d]")


@pytest.fixture
def events(tmp_path):
    return EventsService(events_path=tmp_path / "ev")


def test_arrival_lines_follow_block_state(events):
    rec = rec_with_stop()
    a = events.create_event(date="2026-11-10", name="Walk to café", start_time="2026-11-10T10:16:00",
                            end_time="2026-11-10T10:24:00", proposed=True)
    b = events.create_event(date="2026-11-10", name="Coffee", start_time="2026-11-10T10:24:00",
                            end_time="2026-11-10T11:00:00", proposed=True)
    events.update_event(date="2026-11-10", event_id=a["id"], updates={"state": "approved"})
    rec["blocks"] = {"leg:1": {"date": "2026-11-10", "event_id": a["id"]},
                     "stop:s1": {"date": "2026-11-10", "event_id": b["id"]}}
    r = arrival_receipt(rec, events, TZ)
    lines = r["lines"]
    assert [l["glyph"] for l in lines[:2]] == ["✓", "●"]
    assert lines[0]["buttons"] == []
    assert [x["label"] for x in lines[1]["buttons"]] == ["✓", "✎"]
    assert lines[1]["buttons"][1]["data"] == f"block:edit:2026-11-10:{b['id']}"
    assert lines[1]["when"] == "10:24–11:00"
    assert [x["data"] for x in lines[-1]["buttons"]] == ["trip:1a2b3c4d:all:ok", "trip:1a2b3c4d:all:no"]
    assert lines[-1]["detail"] == "trip 1a2b3c4d"
    assert rec["arrival_lines"] == ["leg:1", "stop:s1"]


def test_the_trip_line_says_how_long_and_how_far(events):
    rec = rec_with_stop()
    rec["trip"]["back_at"] = t(10, 13, 6).isoformat()
    rec["trip"]["stops"][0]["end"] = t(10, 12, 0).isoformat()
    e = events.create_event(date="2026-11-10", name="Dog walk", start_time="2026-11-10T10:16:00",
                            end_time="2026-11-10T13:06:00", proposed=True)
    rec["blocks"] = {"trip": {"date": "2026-11-10", "event_id": e["id"]}}
    assert arrival_receipt(rec, events, TZ)["lines"][0]["detail"] == "2 h 50 min, 1.1 km, 1 stop"


def test_a_merged_block_says_what_location_filled(events):
    rec = rec_with_stop()
    e = events.create_event(date="2026-11-10", name="Dog walk", start_time="2026-11-10T10:16:00",
                            end_time="2026-11-10T10:40:00")
    rec["merged"] = {"trip": {"date": "2026-11-10", "event_id": e["id"], "filled": {"end_time": None},
                              "disagree": None}}
    line = arrival_receipt(rec, events, TZ)["lines"][0]
    assert line["reason"] == "end from location" and [b["label"] for b in line["buttons"]] == ["✓", "✎"]
    rec["merged"]["trip"]["disagree"] = {"field": "end_time", "location_value": "10:52"}
    assert arrival_receipt(rec, events, TZ)["lines"][0]["reason"].endswith("location says back 10:52")


def test_an_open_trip_question_comes_first(events):
    rec = rec_with_stop()
    rec["trip"]["back_at"] = t(10, 10, 54).isoformat()
    rec["trip_question"] = {"options": [Option("Run").to_dict()], "asked_at": t(10, 10, 55).isoformat()}
    r = arrival_receipt(rec, events, TZ)
    assert r["lines"][0]["buttons"][0]["data"] == "trip:1a2b3c4d:trip:a0"
    assert r["open_question"].endswith("[trip 1a2b3c4d]")


def test_receipt_text_has_no_coordinates(events):
    rec = rec_with_stop()
    payload = json.dumps([arrival_receipt(rec, events, TZ),
                          question_receipt(rec, "s1", [Option("Coffee")], t(10, 10, 28), TZ)])
    assert "32.08" not in payload and "34.78" not in payload


def test_notice():
    assert notice_receipt("Location sharing stopped")["text"] == "Location sharing stopped"
    assert notice_receipt("x")["lines"] == []


def test_a_split_block_shows_its_whole_span(events):                    # I-6d
    rec = rec_with_stop()
    a = events.create_event(date="2026-11-09", name="Bar", start_time="2026-11-09T23:10:00",
                            end_time="2026-11-09T23:59:59", proposed=True)
    b = events.create_event(date="2026-11-10", name="Bar", start_time="2026-11-10T00:00:00",
                            end_time="2026-11-10T04:10:00", proposed=True)
    rec["blocks"] = {"stop:s1": {"date": "2026-11-09", "event_id": a["id"],
                                 "fragments": [{"date": "2026-11-09", "event_id": a["id"]},
                                               {"date": "2026-11-10", "event_id": b["id"]}]}}
    assert arrival_receipt(rec, events, TZ)["lines"][0]["when"] == "23:10–04:10"
