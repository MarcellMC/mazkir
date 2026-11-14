"""Trips spec §5.4: name it silently, ask with buttons, or stay quiet."""

from src.services.fast_lane.places import Place
from src.services.location.decide import QUESTION_CAP, Option, decide
from src.services.location.guess import Guess
from src.services.location.history import HistoryCandidate


def g(purpose, likelihood="strong", destination=None):
    return Guess(purpose, likelihood, None, ("c1",), destination)


def h(i, purpose, destination=None):
    return HistoryCandidate(f"h{i}", purpose, destination, 0.5, 4, "…")


KW = {"known_place": None, "may_ask": True, "questions_today": 0}


def names(d):
    return [o.name for o in d.options]


def test_rule_1_a_pause_spot_is_quiet():
    d = decide([g("Coffee")], [], **{**KW, "known_place": Place("pause-1", "pause", kind="pause")})
    assert d.action == "quiet" and d.reason == "pause spot"


def test_rule_2_one_strong_guess_names_it():
    d = decide([g("Dog walk"), g("Run", "unlikely")], [], **KW)
    assert (d.action, d.name) == ("name", "Dog walk")


def test_rule_2_keeps_the_destination():
    d = decide([g("Coffee at Gan Meir", destination="Gan Meir")], [], **KW)
    assert d.destination == "Gan Meir"


def test_two_strong_guesses_ask():
    d = decide([g("Coffee"), g("Sauna")], [], **KW)
    assert d.action == "ask" and names(d) == ["Coffee", "Sauna"]


def test_rule_3_a_known_place_is_never_asked_about():
    d = decide([], [], **{**KW, "known_place": Place("gym", "Gym")})
    assert (d.action, d.name, d.destination) == ("name", "Gym", "Gym")


def test_rule_3_a_strong_guess_beats_the_place_name():
    d = decide([g("Workout", destination="Gym")], [], **{**KW, "known_place": Place("gym", "Gym")})
    assert d.name == "Workout"


def test_rule_4_no_asking_allowed_is_quiet():
    d = decide([g("Coffee", "plausible"), g("Sauna", "plausible")], [], **{**KW, "may_ask": False})
    assert d.action == "quiet"


def test_rule_5_the_daily_cap():
    d = decide([], [h(1, "Dog walk")], **{**KW, "questions_today": QUESTION_CAP})
    assert d.action == "quiet" and d.reason == "daily cap" and QUESTION_CAP == 6


def test_rule_6_plausible_guesses_become_options_in_order():
    d = decide([g("Coffee", "plausible"), g("Sauna", "strong"), g("Bar", "unlikely")], [], **KW)
    assert d.action == "ask" and names(d) == ["Coffee", "Sauna"]


def test_rule_7_no_guess_offers_history():
    d = decide([], [h(1, "Dog walk"), h(2, "Band practice", "Band practice"), h(3, "Gym"), h(4, "Bar")], **KW)
    assert d.action == "ask" and names(d) == ["Dog walk", "Band practice", "Gym"]
    assert d.options[1].destination == "Band practice"


def test_rule_7_with_nothing_still_asks():
    d = decide([], [], **KW)
    assert d.action == "ask" and d.options == ()


def test_option_round_trips():
    o = Option("Coffee", "Gan Meir")
    assert Option.from_dict(o.to_dict()) == o
