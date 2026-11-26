"""Final review 8: the ledger scripts read a trip as edited, and skip one joined into another."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from src.services.location.edits import apply_edit
from src.services.location.pipeline import apply_answer
from tests.test_location_edits import TRIP, closed_trip

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _script(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _split(tmp_path, monkeypatch, join=False):
    from src.config import settings
    deps, _ = closed_trip(tmp_path)
    second = apply_edit(TRIP, "split_trip", {"at": "s2", "stop_side": "second"}, deps)["split_into"]
    apply_answer(TRIP, None, "Market run", None, deps)
    apply_answer(second, None, "Bakery run", None, deps)
    if join:
        apply_edit(TRIP, "join_trips", {"other_trip_id": second}, deps)
    monkeypatch.setattr(settings, "location_data_path", deps.records.dir.parent)
    monkeypatch.setattr(settings, "events_data_path", tmp_path / "data" / "events")
    monkeypatch.setattr(settings, "logs_dir", tmp_path / "logs")
    return deps, second


def test_trips_report_uses_the_edited_trip_and_skips_a_joined_one(tmp_path, monkeypatch, capsys):
    deps, second = _split(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["x", "2026-11-13"])
    _script("location_trips_report").main()
    out = capsys.readouterr().out
    assert "2 trip(s)" in out
    assert out.index(f"trip {TRIP}") < out.index(f"trip {second}")
    assert "10:43–" in out                                     # the second trip starts at the split
    apply_edit(TRIP, "join_trips", {"other_trip_id": second}, deps)
    _script("location_trips_report").main()
    out = capsys.readouterr().out
    assert f"trip {second}" not in out


def test_labels_skip_a_joined_trip_and_date_a_split_one_by_its_own_start(tmp_path, monkeypatch, capsys):
    deps, second = _split(tmp_path, monkeypatch)
    monkeypatch.setattr("src.services.location.history._is_confirmed", lambda *a: True)
    monkeypatch.setattr(sys, "argv", ["x", "--from", "2026-11-13", "--to", "2026-11-13"])
    _script("location_labels_from_ledger").main()
    out = capsys.readouterr().out
    assert "10:09  Market run" in out and "10:43  Bakery run" in out
    labels = json.loads((tmp_path / "data" / "eval" / "location" / "2026-11-13.json").read_text())
    assert len(labels["trips"]) == 2


def test_labels_skip_a_joined_trip(tmp_path, monkeypatch, capsys):
    deps, second = _split(tmp_path, monkeypatch, join=True)
    monkeypatch.setattr("src.services.location.history._is_confirmed", lambda *a: True)
    monkeypatch.setattr(sys, "argv", ["x", "--from", "2026-11-13", "--to", "2026-11-13"])
    _script("location_labels_from_ledger").main()
    out = capsys.readouterr().out
    assert "Bakery run" not in out and "1 label(s) added" in out
