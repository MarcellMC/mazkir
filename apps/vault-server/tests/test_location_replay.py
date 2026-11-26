"""Plan Task 16: the replay's matching and measures (trips spec §9)."""

import datetime as dt
import importlib.util
from pathlib import Path

from tests.location_fixtures import t


def _script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "location_replay.py"
    spec = importlib.util.spec_from_file_location("location_replay", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def trip(a, b, detected=None):
    start, end = t(9, 10, a), t(9, 10, b)
    return {"left_at": start.isoformat(), "back_at": end.isoformat(),
            "detected_at": (detected or start + dt.timedelta(minutes=1)).isoformat()}


def label(a, b, purpose="Dog walk"):
    return {"start": t(9, 10, a).isoformat(), "end": t(9, 10, b).isoformat(), "purpose": purpose}


def test_measures_count_missed_and_invented():
    mod = _script()
    m = mod.measures(mod.match_trips([trip(10, 20), trip(30, 35)], [label(10, 21), label(50, 59)]))
    assert (m["found"], m["missed"], m["invented"]) == (1, 1, 1)


def test_errors_and_leaving_delay():
    mod = _script()
    m = mod.measures(mod.match_trips([trip(10, 20, detected=t(9, 10, 12))], [label(9, 22)]))
    assert m["leaving_p50_min"] == 3.0
    assert m["start_err_p50_min"] == 1.0 and m["end_err_p50_min"] == 2.0


def test_one_trip_can_cover_two_labels():
    mod = _script()
    m = mod.measures(mod.match_trips([trip(0, 50)], [label(0, 20, "Alex's"), label(20, 50, "Gan Meir")]))
    assert (m["found"], m["missed"], m["invented"]) == (2, 0, 0)


def test_map_flag_prints_labels_not_coordinates(tmp_path):
    from src.services.location.map_index import build_index
    from src.services.location.model import Trip

    mod = _script()
    index = tmp_path / "index.sqlite"
    build_index(Path(__file__).parent / "fixtures" / "map_small.osm", index)
    start = t(14, 16, 23)
    trip = Trip.from_dict({
        "id": "be630ac6", "origin": "home", "left_at": t(14, 15, 56).isoformat(), "start_precision": "location",
        "stops": [{"id": "s1", "start": start.isoformat(), "end": (start + dt.timedelta(minutes=9)).isoformat(),
                   "lat": 32.02, "lng": 34.80, "spread_m": 20.0, "from_home_m": 690.0, "place_id": None}],
        "legs": [], "back_at": t(14, 16, 46).isoformat(), "end_precision": "location",
        "distance_m": 1460.0, "max_from_home_m": 714.0})
    lines = mod.map_lines([trip], index, "Asia/Jerusalem")
    assert lines == ["    11-14 16:23  stop s1  map: קפה ברזילי  area: -"]
    assert "32.02" not in "\n".join(lines) and "34.8" not in "\n".join(lines)


def _synthetic_trip():
    from src.services.location.model import Stop, Trip

    s = t(9, 10, 10)
    def stop(sid, a, b, place_id=None):
        return Stop(sid, t(9, 10, a), t(9, 10, b), 32.0, 34.8, 20.0, 300.0, place_id)
    return Trip.from_dict({
        "id": "aa000001", "origin": "home", "left_at": s.isoformat(), "start_precision": "location",
        "stops": [stop("s1", 12, 20).to_dict(), stop("s2", 30, 40, "gym").to_dict()],
        "legs": [], "back_at": t(9, 10, 50).isoformat(), "end_precision": "location",
        "distance_m": 1000.0, "max_from_home_m": 400.0})


def _confirmed(n=4):
    from src.services.location.history import ConfirmedTrip

    return [ConfirmedTrip("Dog walk", None, t(d, 9, 10), 1800.0, "home", "walk", 1000.0, 400.0) for d in range(1, n + 1)]


def test_question_measures_every_trip_and_stop_is_asked():
    from src.services.fast_lane.places import Place

    mod = _script()
    gym = Place(id="gym", name="Gym", lat=32.0, lng=34.8, radius_m=50.0)
    m = mod.question_measures([_synthetic_trip()], [gym], lambda tr: [], "UTC")
    # The trip is never named without asking; the stop on the user's own place is named by it
    # (answered), the other one is asked; none is left unasked.
    assert m["trips_named_without_question"] == 0
    assert m["stops_never_asked"] == 0
    assert m["stops"] == 2 and m["stops_asked"] == 1 and m["stops_named_by_place"] == 1
    assert m["questions"] == 2   # one stop, one trip


def test_question_measures_use_real_history_not_constants(monkeypatch):
    """A trip with one strong history candidate still counts as asked. Before the repair, `decide`
    named it silently; if it does again, the measure must show it."""
    import src.services.location.decide as decide_mod

    mod = _script()
    seen = []
    real = decide_mod.decide

    def spy(guesses, history, **kw):
        seen.append(history)
        return real(guesses, history, **kw)

    monkeypatch.setattr(decide_mod, "decide", spy)
    m = mod.question_measures([_synthetic_trip()], [], lambda tr: _confirmed(), "UTC")
    assert any(h for h in seen), "decide was never given the history candidates"
    assert m["trips_named_without_question"] == 0 and m["questions"] >= 1

    # A decide that names a strong history candidate silently (the old rule) must be caught.
    def old_decide(guesses, history, *, known_place, may_ask, at_stop=False, map_options=()):
        if history and not at_stop and history[0].score >= 0.75:
            return decide_mod.Decision("name", history[0].purpose)
        return real(guesses, history, known_place=known_place, may_ask=may_ask, at_stop=at_stop,
                    map_options=map_options)

    monkeypatch.setattr(decide_mod, "decide", old_decide)
    strong = mod.question_measures([_synthetic_trip()], [], lambda tr: _confirmed(), "UTC")
    assert strong["trips_named_without_question"] == 1


def test_early_starts_checks_trips_begun_across_a_silence():
    from src.services.location.model import Fix, Trip

    mod = _script()
    home = (32.0, 34.8)
    d = _synthetic_trip().to_dict()

    def trip(left, precision="before"):
        return Trip.from_dict({**d, "left_at": left.isoformat(), "start_precision": precision})

    inside = Fix(t(9, 6, 0), 32.0, 34.8)
    away = Fix(t(9, 10, 20), 32.01, 34.8)   # about 1.1 km north, hours after the last point inside
    fixes = [inside, away]
    # The old behaviour: stamped at the last point inside, hours before the first point away.
    assert mod.early_starts([trip(t(9, 6, 0))], fixes, home, 40.0) == (1, 1)
    # Fixed: stamped at the first point away.
    assert mod.early_starts([trip(t(9, 10, 20))], fixes, home, 40.0) == (1, 0)
    # A trip stamped at a point is not part of this measure.
    assert mod.early_starts([trip(t(9, 6, 0), "location")], fixes, home, 40.0) == (0, 0)
