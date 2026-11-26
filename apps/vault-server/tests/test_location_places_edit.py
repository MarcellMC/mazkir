"""Repair spec §7.5: fixing a place of the user's, and a street is never learned (plan Task 11)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src.services.fast_lane.places import Place, load_places, save_places
from src.services.geo import haversine_m
from src.services.location.handles import Handles
from src.services.location.map_index import build_index
from src.services.location.pipeline import apply_answer
from src.services.location.places_edit import edit_place
from tests.test_location_edits import TRIP, closed_trip

FIXTURE = Path(__file__).parent / "fixtures" / "map_small.osm"
CHAT = 156175834


def setup(tmp_path):
    deps, _ = closed_trip(tmp_path)
    save_places(deps.places_path, [*load_places(deps.places_path),
                                   Place("alex", "Alex's", ("alex",), None, 32.0, 34.0, 60.0)])
    return deps, Handles(tmp_path / "handles.json")


def no_coordinates(result) -> None:
    text = json.dumps(result, ensure_ascii=False)
    assert not re.search(r"\d+\.\d{4,}", text), text
    assert '"lat"' not in text and '"lng"' not in text and '"osm"' not in text


def alex(deps):
    return next(p for p in load_places(deps.places_path) if p.id == "alex")


def test_forget(tmp_path):
    deps, h = setup(tmp_path)
    out = edit_place(deps, h, CHAT, "place:alex", "forget", None)
    assert out["op"] == "forget" and out["label"] == "Alex's"
    assert all(p.id != "alex" for p in load_places(deps.places_path))
    no_coordinates(out)


def test_rename_and_alias(tmp_path):
    deps, h = setup(tmp_path)
    assert edit_place(deps, h, CHAT, "place:alex", "rename", "Alex Cafe")["label"] == "Alex Cafe"
    assert alex(deps).name == "Alex Cafe"
    out = edit_place(deps, h, CHAT, "place:alex", "add_alias", "the cafe")
    assert out["aliases"] == ["alex", "the cafe"] and alex(deps).aliases == ("alex", "the cafe")
    assert edit_place(deps, h, CHAT, "place:alex", "add_alias", "the cafe")["aliases"] == ["alex", "the cafe"]


def test_move_to_a_stop(tmp_path):
    deps, h = setup(tmp_path)
    stop = next(s for s in deps.records.get(TRIP)["trip"]["stops"] if s["id"] == "s2")
    out = edit_place(deps, h, CHAT, "place:alex", "move_to", f"{TRIP}:s2")
    moved = alex(deps)
    assert (moved.lat, moved.lng) == (stop["lat"], stop["lng"])
    assert out["moved_m"] % 10 == 0 and out["moved_m"] > 1000
    no_coordinates(out)
    with pytest.raises(KeyError, match="search again"):
        edit_place(deps, h, CHAT, "place:alex", "move_to", f"{TRIP}:s9")


def test_unknown_or_foreign_ref_is_search_again(tmp_path):
    deps, h = setup(tmp_path)
    for ref in ("place:nobody", "m3", "place:home"):
        with pytest.raises(KeyError, match="search again"):
            edit_place(deps, h, CHAT, ref, "forget", None)
    assert len(load_places(deps.places_path)) == 2           # home and alex survive


def test_a_value_is_needed(tmp_path):
    deps, h = setup(tmp_path)
    with pytest.raises(ValueError):
        edit_place(deps, h, CHAT, "place:alex", "rename", None)


def test_a_street_answer_is_not_learned(tmp_path):
    deps, _ = closed_trip(tmp_path)
    index = tmp_path / "index.sqlite"
    build_index(FIXTURE, index)
    deps.map_index = index
    rec = deps.records.get(TRIP)
    for s in rec["trip"]["stops"]:
        if s["id"] == "s1":
            s["lat"], s["lng"] = 32.03, 34.80                   # the fixture's address on Ha'Yarkon
    deps.records.save(rec)
    before = load_places(deps.places_path)
    out = apply_answer(TRIP, "s1", "Walk", "Ha'Yarkon", deps)
    assert out["street"] is True and out["conflict"] is None
    assert load_places(deps.places_path) == before
    info = deps.records.get(TRIP)["stops"]["s1"]
    assert info["place"] == "Ha'Yarkon" and info["street"] is True
    # a place that is not a street is still learned
    out = apply_answer(TRIP, "s2", "Visit", "Alex's", deps)
    assert "street" not in out
    assert any(p.name == "Alex's" for p in load_places(deps.places_path))
