"""Plan Task 5: the labels come from the spec's table (§2.1), not from hand-labelling."""

import importlib.util
from pathlib import Path


def _script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "location_seed_labels.py"
    spec = importlib.util.spec_from_file_location("location_seed_labels", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_label_rows_cover_the_spec_table():
    rows = _script().ROWS
    assert len(rows) == 17
    assert any(r["purpose"] == "Convenience store" and r["start"].endswith("20:29") for r in rows)
    assert all(not r["destination"] for r in rows if r["purpose"] == "Dog walk")
    assert sum(r["purpose"] == "Dog walk" for r in rows) == 10


def test_match_picks_the_trip_overlapping_most():
    mod = _script()
    trips = [{"left_at": "2026-11-09T19:59:00+02:00", "back_at": "2026-11-09T20:14:00+02:00"},
             {"left_at": "2026-11-09T20:28:00+02:00", "back_at": "2026-11-09T20:34:00+02:00"}]
    row = next(r for r in mod.ROWS if r["purpose"] == "Convenience store")
    assert mod.best_match(row, trips) is trips[1]
    assert mod.best_match({**row, "start": "2026-11-09T12:00", "end": "2026-11-09T12:05"}, trips) is None
