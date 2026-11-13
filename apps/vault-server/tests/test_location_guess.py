"""Trips spec §5.3: one structured Haiku call; anything not from history must cite a real line."""

import json
from types import SimpleNamespace

from src.services.fast_lane.places import Place
from src.services.location.context import ContextLine
from src.services.location.guess import GUESS_SCHEMA, build_content, describe_trip, guess
from src.services.location.history import HistoryCandidate
from src.services.location.model import Leg, Stop, Trip
from tests.location_fixtures import TZ, t

KW = {"model": "claude-haiku-4-5-20251001", "timeout_s": 8.0}
H1 = HistoryCandidate("h1", "Dog walk", None, 0.9, 14, "Dog walk: 14 confirmed, usually 07–10 and 19–21")


def g(purpose, likelihood="strong", history_id=None, cites=(), destination=None):
    return {"purpose": purpose, "likelihood": likelihood, "history_id": history_id,
            "cites": list(cites), "destination": destination}


class Fake:
    def __init__(self, payload=None, error=None, stop_reason="end_turn"):
        self.payload, self.error, self.stop_reason, self.calls = payload, error, stop_reason, []

    def create_fast_parse(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        return SimpleNamespace(stop_reason=self.stop_reason,
                               content=[SimpleNamespace(type="text", text=json.dumps(self.payload))])


def trip_with_stop(lat=32.0853, lng=34.7818, place_id=None):
    left = t(10, 10, 16)
    stop = Stop("s1", t(10, 10, 24), None, lat, lng, 8.0, 700.0, place_id)
    return Trip("1a2b3c4d", "home", left, "location", [stop], [Leg(left, stop.start, 700.0, "walk")],
                distance_m=720.0, max_from_home_m=705.0)


def test_history_guess_takes_the_candidate_purpose():
    kept, _ = guess("trip", "…", [H1], [], Fake({"guesses": [g("walk", history_id="h1")]}), **KW)
    assert kept[0].purpose == "Dog walk" and kept[0].history_id == "h1"


def test_unknown_history_id_is_dropped():
    kept, dropped = guess("trip", "…", [H1], [], Fake({"guesses": [g("Run", history_id="h7")]}), **KW)
    assert kept == [] and dropped == [{"purpose": "Run", "reason": "unknown history id"}]


def test_new_purpose_must_cite_a_real_line():
    lines = [ContextLine("c1", "conversation", "[yesterday 21:40] user: Dana's for dinner")]
    fake = Fake({"guesses": [g("Dinner at Dana's", cites=["c1"]), g("Gym", cites=[]), g("Bar", cites=["c9"])]})
    kept, dropped = guess("stop", "…", [], lines, fake, **KW)
    assert [k.purpose for k in kept] == ["Dinner at Dana's"]
    assert {d["reason"] for d in dropped} == {"cites nothing", "cites a line that does not exist"}


def test_at_most_three_are_kept():
    fake = Fake({"guesses": [g(f"P{i}", cites=["c1"]) for i in range(5)]})
    kept, _ = guess("stop", "…", [], [ContextLine("c1", "todo", "x")], fake, **KW)
    assert len(kept) == 3


def test_failure_is_no_guess():
    kept, dropped = guess("trip", "…", [], [], Fake(error=TimeoutError("slow")), **KW)
    assert kept == [] and dropped[0]["purpose"] is None
    assert guess("trip", "…", [], [], Fake({"guesses": []}, stop_reason="max_tokens"), **KW)[0] == []


def test_the_call_uses_the_schema_and_model():
    fake = Fake({"guesses": []})
    guess("trip", "…", [H1], [], fake, **KW)
    assert fake.calls[0]["schema"] is GUESS_SCHEMA and fake.calls[0]["model"] == KW["model"]


def test_content_has_no_coordinates():
    trip = trip_with_stop()
    content = build_content("stop", describe_trip(trip, trip.stops[0], [], t(10, 10, 28), TZ), [H1], [])
    assert "32.08" not in content and "34.78" not in content
    assert "700 m from home" in content and "h1" in content


def test_describe_names_a_known_place():
    trip = trip_with_stop(place_id="gan-meir")
    text = describe_trip(trip, trip.stops[0], [Place("gan-meir", "Gan Meir")], t(10, 10, 28), TZ)
    assert "Gan Meir" in text and "Stopped since 10:24 (4 min)" in text
