"""Per-chat handles for map places and anchors (spec §7): the agent sees m<n>, never coordinates or OSM ids."""

from __future__ import annotations

import datetime as dt
import json

from src.services.location.handles import Handles

UTC = dt.timezone.utc
T0 = dt.datetime(2026, 11, 25, 10, 0, tzinfo=UTC)


class Clock:
    def __init__(self, at: dt.datetime) -> None:
        self.at = at

    def __call__(self) -> dt.datetime:
        return self.at


def _place(h: Handles, chat: int, osm: str = "node/1", label: str = "Dog park") -> str:
    return h.place(chat, osm=osm, label=label, kind="leisure", lat=32.08, lng=34.78)


def test_same_osm_in_same_chat_returns_same_handle(tmp_path):
    h = Handles(tmp_path / "handles.json", now=Clock(T0))
    first = _place(h, 1, osm="node/1")
    again = _place(h, 1, osm="node/1")
    assert first == "m1"
    assert again == first


def test_different_osm_gets_next_number(tmp_path):
    h = Handles(tmp_path / "handles.json", now=Clock(T0))
    assert _place(h, 1, osm="node/1") == "m1"
    assert _place(h, 1, osm="node/2", label="Cafe") == "m2"


def test_each_chat_has_its_own_numbering(tmp_path):
    h = Handles(tmp_path / "handles.json", now=Clock(T0))
    assert _place(h, 1, osm="node/1") == "m1"
    assert _place(h, 2, osm="node/9") == "m1"
    assert h.resolve(2, "m1")["osm"] == "node/9"
    assert h.resolve(1, "m1")["osm"] == "node/1"


def test_resolve_returns_map_place(tmp_path):
    h = Handles(tmp_path / "handles.json", now=Clock(T0))
    handle = _place(h, 1)
    got = h.resolve(1, handle)
    assert got == {"kind": "map", "osm": "node/1", "label": "Dog park", "lat": 32.08, "lng": 34.78}


def test_resolve_unknown_handle_is_none(tmp_path):
    h = Handles(tmp_path / "handles.json", now=Clock(T0))
    assert h.resolve(1, "m7") is None


def test_resolve_after_ttl_is_none(tmp_path):
    clock = Clock(T0)
    h = Handles(tmp_path / "handles.json", now=clock)
    handle = _place(h, 1)
    clock.at = T0 + dt.timedelta(hours=25)
    assert h.resolve(1, handle) is None


def test_expired_number_is_not_reused(tmp_path):
    clock = Clock(T0)
    h = Handles(tmp_path / "handles.json", now=clock)
    assert _place(h, 1, osm="node/1") == "m1"
    clock.at = T0 + dt.timedelta(hours=25)
    # the old m1 has expired; a new place must not take its number
    assert _place(h, 1, osm="node/2") == "m2"
    assert h.resolve(1, "m1") is None


def test_reregistering_refreshes_the_ttl(tmp_path):
    clock = Clock(T0)
    h = Handles(tmp_path / "handles.json", now=clock)
    handle = _place(h, 1)
    clock.at = T0 + dt.timedelta(hours=20)
    assert _place(h, 1) == handle
    clock.at = T0 + dt.timedelta(hours=30)  # 10 h after the refresh
    assert h.resolve(1, handle) is not None


def test_anchor_returns_key_and_resolves_with_position(tmp_path):
    h = Handles(tmp_path / "handles.json", now=Clock(T0))
    key = h.anchor(1, "photo:IMG_0001.jpg", 32.1, 34.8, accuracy_m=12.5)
    assert key == "photo:IMG_0001.jpg"
    assert h.resolve(1, key) == {
        "kind": "anchor",
        "lat": 32.1,
        "lng": 34.8,
        "accuracy_m": 12.5,
    }


def test_anchor_without_accuracy_omits_it(tmp_path):
    h = Handles(tmp_path / "handles.json", now=Clock(T0))
    key = h.anchor(1, "location:42", 32.1, 34.8)
    got = h.resolve(1, key)
    assert got == {"kind": "anchor", "lat": 32.1, "lng": 34.8}


def test_anchor_expires(tmp_path):
    clock = Clock(T0)
    h = Handles(tmp_path / "handles.json", now=clock)
    key = h.anchor(1, "location:42", 32.1, 34.8)
    clock.at = T0 + dt.timedelta(hours=25)
    assert h.resolve(1, key) is None


def test_survives_a_new_handles_on_same_path(tmp_path):
    path = tmp_path / "handles.json"
    clock = Clock(T0)
    handle = _place(Handles(path, now=clock), 1)
    fresh = Handles(path, now=clock)
    assert fresh.resolve(1, handle)["osm"] == "node/1"
    assert _place(fresh, 1, osm="node/2") == "m2"  # counter persisted too


def test_corrupt_file_reads_as_empty(tmp_path):
    path = tmp_path / "handles.json"
    path.write_text("{not json", encoding="utf-8")
    h = Handles(path, now=Clock(T0))
    assert h.resolve(1, "m1") is None
    assert _place(h, 1) == "m1"


def test_missing_file_reads_as_empty(tmp_path):
    h = Handles(tmp_path / "nope" / "handles.json", now=Clock(T0))
    assert h.resolve(1, "m1") is None


def test_expired_entries_are_dropped_on_write(tmp_path):
    path = tmp_path / "handles.json"
    clock = Clock(T0)
    h = Handles(path, now=clock)
    _place(h, 1, osm="node/1")
    clock.at = T0 + dt.timedelta(hours=25)
    _place(h, 1, osm="node/2")
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert "node/1" not in json.dumps(stored)


def test_file_holds_no_coordinates_in_logs_only_storage(tmp_path):
    # storage holds what resolve needs; nothing else is written to disk besides the file itself
    path = tmp_path / "handles.json"
    h = Handles(path, now=Clock(T0))
    _place(h, 1)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["handles.json"]
