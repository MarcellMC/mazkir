"""Trips spec §5.2 item 1: your confirmed history, scored against this trip."""

import datetime as dt
import json

from src.services.events_service import EventsService
from src.services.location.history import ConfirmedTrip, load_confirmed, score_history
from src.services.location.model import Leg, Stop, Trip
from src.services.location.records import TripRecords, new_record
from tests.location_fixtures import TZ, t


def confirmed(purpose, starts, origin="home", mode="walk", max_m=300.0, destination=None, places=()):
    return [ConfirmedTrip(purpose, destination, s, 1200.0, origin, mode, 800.0, max_m, tuple(places)) for s in starts]


def dog_walks(n=14, last=None):
    last = last or t(12, 20, 0)
    starts = []
    for i in range(n):
        starts.append(last - dt.timedelta(hours=12 * i, minutes=(i % 3) * 20))
    return confirmed("Dog walk", starts)


def trip_at(left: dt.datetime, mode="walk", max_m=150.0, origin="home") -> Trip:
    return Trip("1a2b3c4d", origin, left, "location", legs=[Leg(left, None, 400.0, mode)], max_from_home_m=max_m)


def test_needs_three_confirmed():
    two = confirmed("Dog walk", [t(12, 8, 0), t(12, 20, 0)])
    assert score_history(trip_at(t(13, 8, 0)), two, t(13, 8, 5), TZ) == []


def test_morning_loop_ranks_the_twice_daily_purpose_first():
    band = confirmed("Band practice", [t(d, 11, 25) for d in (2, 4, 6, 9)], max_m=220, destination="Band practice")
    ranked = score_history(trip_at(t(13, 8, 15)), dog_walks(last=t(12, 20, 0)) + band, t(13, 8, 20), TZ)
    top = ranked[0]
    assert top.purpose == "Dog walk" and top.id == "h1" and "14 confirmed" in top.evidence
    assert [c.id for c in ranked] == [f"h{i}" for i in range(1, len(ranked) + 1)]
    if len(ranked) > 1:
        assert ranked[1].score < top.score


def test_spacing_counts():
    history = dog_walks(last=t(12, 20, 0))
    soon = score_history(trip_at(t(12, 21, 0)), history, t(12, 21, 5), TZ)
    later = score_history(trip_at(t(13, 7, 30)), history, t(13, 7, 35), TZ)
    soon_score = next((c.score for c in soon if c.purpose == "Dog walk"), 0.0)
    later_score = next(c.score for c in later if c.purpose == "Dog walk")
    assert soon_score < later_score


def test_a_known_place_counts_for_a_stop():
    gym = confirmed("Workout", [t(d, 18, 0) for d in (3, 5, 8, 10)], places=("gym",), destination="Gym", max_m=900)
    trip = trip_at(t(13, 18, 0), max_m=900)
    at_gym = Stop("s1", t(13, 18, 10), None, 0, 0, 10, 900, "gym")
    elsewhere = Stop("s1", t(13, 18, 10), None, 0, 0, 10, 900, "cafe")
    a = score_history(trip, gym, t(13, 18, 15), TZ, stop=at_gym)[0].score
    b = next((c.score for c in score_history(trip, gym, t(13, 18, 15), TZ, stop=elsewhere)), 0.0)
    assert a > b


def test_evidence_has_no_coordinates():
    trip = trip_at(t(13, 8, 15))
    for c in score_history(trip, dog_walks(), t(13, 8, 20), TZ):
        assert "32." not in c.evidence and "34." not in c.evidence
        assert "usually" in c.evidence and "on foot" in c.evidence


def test_labels_and_approved_records_are_confirmed(tmp_path):
    labels = tmp_path / "labels"
    labels.mkdir()
    (labels / "2026-11-09.json").write_text(json.dumps({"date": "2026-11-09", "trips": [
        {"start": "2026-11-09T08:29:00+02:00", "end": "2026-11-09T08:49:00+02:00", "purpose": "Dog walk",
         "destination": None, "features": {"origin": "home", "mode": "walk", "distance_m": 600,
                                            "max_from_home_m": 201, "stops": 1}, "not_a_trip": False},
        {"start": "2026-11-09T12:00:00+02:00", "end": None, "purpose": "Lunch", "destination": None,
         "features": None, "not_a_trip": False},
    ]}))
    events = EventsService(events_path=tmp_path / "events")
    records = TripRecords(tmp_path / "loc")
    run = new_record(trip_at(t(12, 7, 0)))
    run["purpose"] = {"name": "Run", "destination": None, "source": "guess"}
    e = events.create_event(date="2026-11-12", name="Run", start_time="2026-11-12T07:00:00", proposed=True)
    events.update_event(date="2026-11-12", event_id=e["id"], updates={"state": "approved"})
    run["blocks"] = {"trip": {"date": "2026-11-12", "event_id": e["id"]}}
    records.save(run)
    unconfirmed = new_record(trip_at(t(12, 9, 0)))
    unconfirmed["id"] = "bbbbbbbb"
    unconfirmed["purpose"] = {"name": "Swim", "destination": None, "source": "guess"}
    records.save(unconfirmed)
    got = load_confirmed(labels, records, events, TZ, t(13, 9, 0))
    assert sorted(c.purpose for c in got) == ["Dog walk", "Run"]


def test_approving_a_leg_does_not_confirm_the_trip(tmp_path):           # I-10
    events = EventsService(events_path=tmp_path / "events")
    records = TripRecords(tmp_path / "loc")
    rec = new_record(trip_at(t(12, 7, 0)))
    rec["purpose"] = {"name": "Coffee at Gan Meir", "destination": "Gan Meir", "source": "guess"}
    leg = events.create_event(date="2026-11-12", name="Walk to Gan Meir", start_time="2026-11-12T07:00:00", proposed=True)
    events.update_event(date="2026-11-12", event_id=leg["id"], updates={"state": "approved"})
    rec["blocks"] = {"leg:1": {"date": "2026-11-12", "event_id": leg["id"]}}
    records.save(rec)
    assert load_confirmed(tmp_path / "none", records, events, TZ, t(13, 9, 0)) == []
    stop = events.create_event(date="2026-11-12", name="Coffee at Gan Meir", start_time="2026-11-12T07:10:00", proposed=True)
    events.update_event(date="2026-11-12", event_id=stop["id"], updates={"state": "approved"})
    rec["blocks"]["stop:s1"] = {"date": "2026-11-12", "event_id": stop["id"]}
    records.save(rec)
    assert [c.purpose for c in load_confirmed(tmp_path / "none", records, events, TZ, t(13, 9, 0))] == ["Coffee at Gan Meir"]
