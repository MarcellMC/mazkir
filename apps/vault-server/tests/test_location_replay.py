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
