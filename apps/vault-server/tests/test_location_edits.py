"""Repair spec §7.4: trip edits as an overlay over the tracker's trip (plan Task 9)."""

from __future__ import annotations

import json
import re

import pytest

from src.services.approval import resolve_state
from src.services.fast_lane.places import learn_place, load_places
from src.services.geo import haversine_m
from src.services.location.edits import apply_edit, trip_of
from src.services.location.pipeline import apply_answer, handle_event
from src.services.location.runtime import LocationRuntime
from src.services.location.tracker import Tracker
from src.services.location.where import _stop_at
from src.services.location.writer import fragments
from src.services.location_store import append_point
from tests.location_fixtures import HOME, TZ, Track, at, feed_all, t
from tests.location_pipeline_fixtures import make_deps

TRIP = "1a2b3c4d"


def two_stops():
    """s1 10:18–10:35:30 (8 min at 700 m, then 8 min at 760 m: the tracker makes it one stop),
    s2 10:43–10:58:30 at 1400 m, home 11:15."""
    return Track(t(13, 10, 0)).stay(10).walk_to(700).stay(8).walk_to(760).stay(8).walk_to(1400).stay(15) \
        .walk_to(0).stay(5)


def record_points(track, tmp_path):
    for f in track.fixes:
        append_point(tmp_path / "loc", {"source": "telegram", "kind": "live", "ts": f.ts, "lat": f.lat,
                                         "lng": f.lng, "accuracy_m": f.accuracy_m}, TZ)


def events_of(track):
    return feed_all(Tracker(HOME, [], new_id=lambda: TRIP), track.fixes)


def run(deps, clock, evs):
    for ev in evs:
        clock["now"] = ev.ts
        handle_event(ev, deps)
    return deps.records.get(TRIP)


def closed_trip(tmp_path, logs=None):
    deps, clock = make_deps(tmp_path, logs=logs)
    deps.raw_dir = tmp_path / "loc" / "raw"
    track = two_stops()
    record_points(track, tmp_path)
    run(deps, clock, events_of(track))
    clock["now"] = t(13, 12, 0)
    return deps, clock


def stop_ids(rec):
    return [s.id for s in trip_of(rec).stops]


def block(deps, rec, part):
    ref = rec["blocks"][part]
    frag = fragments(ref)[0]
    return next(e for e in deps.events.get_events(frag["date"]) if e["id"] == frag["event_id"])


def hm(ts):
    return ts.strftime("%H:%M")


# --- the overlay ----------------------------------------------------------------

def test_trip_of_without_edits_is_the_tracker_trip(tmp_path):
    deps, _ = closed_trip(tmp_path)
    rec = deps.records.get(TRIP)
    assert trip_of(rec).to_dict() == {**rec["trip"], "id": TRIP}
    assert stop_ids(rec) == ["s1", "s2"]


# --- one test per op ------------------------------------------------------------

def test_add_stop_from_raw_points(tmp_path):
    deps, _ = closed_trip(tmp_path)
    out = apply_edit(TRIP, "add_stop", {"start": t(13, 10, 37).isoformat(), "end": t(13, 10, 41).isoformat(),
                                        "name": "Kiosk"}, deps)
    rec = out["record"]
    assert stop_ids(rec) == ["s1", "x1", "s2"]
    x1 = trip_of(rec).stop("x1")
    assert (hm(x1.start), hm(x1.end)) == ("10:37", "10:41")
    # the centre of the points walked between 760 m and 1400 m
    assert 760 < haversine_m(*HOME, x1.lat, x1.lng) < 1400
    assert rec["stops"]["x1"]["source"] == "agent_edit" and rec["stops"]["x1"]["name"] == "Kiosk"
    assert block(deps, rec, "stop:x1")["name"] == "Kiosk"
    assert block(deps, rec, "stop:x1")["proposed"] is True
    [edit] = rec["edits"]
    assert edit["op"] == "add_stop" and edit["id"] == "x1"


def test_add_stop_from_a_handle(tmp_path):
    deps, _ = closed_trip(tmp_path)
    lat, lng = at(1000)
    resolved = {"kind": "map", "osm": "n42", "label": "Kiosk Ha'Shuk", "place_kind": "shop", "lat": lat,
                "lng": lng, "accuracy_m": None}
    out = apply_edit(TRIP, "add_stop", {"start": "10:37", "end": "10:41", "ref": "m1"}, deps,
                     resolve=lambda h: resolved if h == "m1" else None)
    rec = out["record"]
    x1 = trip_of(rec).stop("x1")
    assert haversine_m(lat, lng, x1.lat, x1.lng) < 1
    # named after the place you said you were at, and the place learned with its map id
    assert rec["stops"]["x1"]["name"] == "Kiosk Ha'Shuk"
    assert any(p.osm == "n42" for p in load_places(tmp_path / "places.json"))


def test_add_stop_outside_trip_refused(tmp_path):
    deps, _ = closed_trip(tmp_path)
    with pytest.raises(ValueError):
        apply_edit(TRIP, "add_stop", {"start": t(13, 11, 20).isoformat(), "end": t(13, 11, 30).isoformat()}, deps)
    with pytest.raises(ValueError):
        apply_edit(TRIP, "add_stop", {"start": t(13, 10, 0).isoformat(), "end": t(13, 10, 5).isoformat()}, deps)
    assert not deps.records.get(TRIP).get("edits")


def test_add_stop_over_a_stop_refused(tmp_path):
    deps, _ = closed_trip(tmp_path)
    with pytest.raises(ValueError):
        apply_edit(TRIP, "add_stop", {"start": "10:30", "end": "10:40"}, deps)


def test_unresolvable_ref_says_search_again(tmp_path):
    deps, _ = closed_trip(tmp_path)
    with pytest.raises(KeyError, match="search again"):
        apply_edit(TRIP, "add_stop", {"start": "10:37", "end": "10:41", "ref": "m9"}, deps, resolve=lambda h: None)
    with pytest.raises(KeyError, match="search again"):
        apply_edit(TRIP, "name_stop", {"stop_id": "s1", "name": "Café", "ref": "place:nowhere"}, deps)


def test_unknown_trip_or_stop_is_a_key_error(tmp_path):
    deps, _ = closed_trip(tmp_path)
    with pytest.raises(KeyError):
        apply_edit("ffffffff", "remove_stop", {"stop_id": "s1"}, deps)
    with pytest.raises(KeyError):
        apply_edit(TRIP, "remove_stop", {"stop_id": "s9"}, deps)


def test_unknown_op_refused(tmp_path):
    deps, _ = closed_trip(tmp_path)
    with pytest.raises(ValueError):
        apply_edit(TRIP, "teleport", {}, deps)


def test_name_stop_with_a_map_ref(tmp_path):
    deps, _ = closed_trip(tmp_path)
    lat, lng = at(700)
    resolved = {"kind": "map", "osm": "n7", "label": "Café Nimrod", "place_kind": "cafe", "lat": lat, "lng": lng}
    out = apply_edit(TRIP, "name_stop", {"stop_id": "s1", "name": "Coffee", "ref": "m3"}, deps,
                     resolve=lambda h: resolved)
    rec = out["record"]
    assert rec["stops"]["s1"]["status"] == "named" and rec["stops"]["s1"]["place"] == "Café Nimrod"
    assert not rec.get("edits")                       # an answer, not an overlay edit
    assert any(p.osm == "n7" for p in load_places(tmp_path / "places.json"))
    assert "stop:s1" in rec["blocks"]


def test_name_stop_with_one_of_your_places(tmp_path):
    deps, _ = closed_trip(tmp_path)
    learn_place(tmp_path / "places.json", "Gym", *at(1400), 20)
    out = apply_edit(TRIP, "name_stop", {"stop_id": "s2", "name": "Workout", "ref": "place:gym"}, deps)
    assert out["record"]["stops"]["s2"]["place"] == "Gym"


def test_name_trip(tmp_path):
    deps, _ = closed_trip(tmp_path)
    out = apply_edit(TRIP, "name_trip", {"name": "Errands"}, deps)
    rec = out["record"]
    assert rec["purpose"]["name"] == "Errands" and rec["confirmed"] is True
    assert block(deps, rec, "trip")["name"] == "Errands"


def test_split_stop(tmp_path):
    deps, _ = closed_trip(tmp_path)
    apply_answer(TRIP, "s1", "Café", None, deps)
    out = apply_edit(TRIP, "split_stop", {"stop_id": "s1", "at": t(13, 10, 27).isoformat()}, deps)
    rec = out["record"]
    assert stop_ids(rec) == ["s1a", "s1b", "s2"]
    a, b = trip_of(rec).stop("s1a"), trip_of(rec).stop("s1b")
    assert (hm(a.start), hm(a.end), hm(b.start), hm(b.end)) == ("10:18", "10:27", "10:27", "10:35")
    # each half's centre from its own points: 700 m and 760 m out
    assert abs(haversine_m(*HOME, a.lat, a.lng) - 700) < 10
    assert abs(haversine_m(*HOME, b.lat, b.lng) - 760) < 10
    assert rec["stops"]["s1a"]["name"] == "Café" and rec["stops"]["s1a"]["source"] == "agent_edit"
    assert rec["stops"]["s1b"]["status"] == "later" and rec["stops"]["s1b"]["source"] == "agent_edit"
    assert "stop:s1" not in rec["blocks"]
    assert block(deps, rec, "stop:s1a")["name"] == "Café"
    [edit] = rec["edits"]
    assert edit["ids"] == ["s1a", "s1b"] and len(edit["centres"]) == 2


def test_split_stop_outside_the_stop_refused(tmp_path):
    deps, _ = closed_trip(tmp_path)
    with pytest.raises(ValueError):
        apply_edit(TRIP, "split_stop", {"stop_id": "s1", "at": t(13, 10, 40).isoformat()}, deps)


def test_merge_stops(tmp_path):
    deps, _ = closed_trip(tmp_path)
    apply_answer(TRIP, "s1", "Market", None, deps)
    apply_answer(TRIP, "s2", "Bakery", None, deps)
    out = apply_edit(TRIP, "merge_stops", {"stop_ids": ["s2", "s1"]}, deps)
    rec = out["record"]
    assert stop_ids(rec) == ["s1"]
    s1 = trip_of(rec).stop("s1")
    assert (hm(s1.start), hm(s1.end)) == ("10:18", "10:58")
    assert rec["stops"]["s1"]["name"] == "Market" and rec["stops"]["s1"]["source"] == "agent_edit"
    assert "stop:s2" not in rec["blocks"]
    assert block(deps, rec, "stop:s1")["end_time"][11:16] == "10:58"
    assert rec["edits"] == [{"op": "merge_stops", "stop_ids": ["s1", "s2"], "id": "s1"}]


def test_merge_stops_only_adjacent(tmp_path):
    deps, _ = closed_trip(tmp_path)
    apply_edit(TRIP, "add_stop", {"start": "10:37", "end": "10:41"}, deps)
    with pytest.raises(ValueError):
        apply_edit(TRIP, "merge_stops", {"stop_ids": ["s1", "s2"]}, deps)


def test_set_stop_times(tmp_path):
    deps, _ = closed_trip(tmp_path)
    apply_answer(TRIP, "s2", "Bakery", None, deps)
    out = apply_edit(TRIP, "set_stop_times", {"stop_id": "s2", "start": "10:45", "end": "10:55"}, deps)
    rec = out["record"]
    s2 = trip_of(rec).stop("s2")
    assert (hm(s2.start), hm(s2.end)) == ("10:45", "10:55")
    assert rec["trip"]["stops"][1]["start"].startswith("2026-11-13T10:43")     # the tracker's own, untouched
    e = block(deps, rec, "stop:s2")
    assert (e["start_time"][11:16], e["end_time"][11:16]) == ("10:45", "10:55")
    assert rec["stops"]["s2"]["source"] == "agent_edit"


def test_set_stop_times_over_a_neighbour_refused(tmp_path):
    deps, _ = closed_trip(tmp_path)
    with pytest.raises(ValueError):
        apply_edit(TRIP, "set_stop_times", {"stop_id": "s2", "start": "10:30"}, deps)


def test_remove_stop(tmp_path):
    deps, _ = closed_trip(tmp_path)
    apply_answer(TRIP, "s2", "Traffic light", None, deps)
    assert "stop:s2" in deps.records.get(TRIP)["blocks"]
    out = apply_edit(TRIP, "remove_stop", {"stop_id": "s2"}, deps)
    rec = out["record"]
    assert stop_ids(rec) == ["s1"]
    assert "stop:s2" not in rec["blocks"]
    assert not any(e.get("name") == "Traffic light" for e in deps.events.get_events("2026-11-13"))


def test_restore_block(tmp_path):
    deps, _ = closed_trip(tmp_path)
    apply_answer(TRIP, "s1", "Café", None, deps)
    rec = deps.records.get(TRIP)
    frag = fragments(rec["blocks"]["stop:s1"])[0]
    deps.events.update_event(date=frag["date"], event_id=frag["event_id"], updates={"state": "dismissed"})
    out = apply_edit(TRIP, "restore_block", {"part": "stop:s1"}, deps)
    e = block(deps, out["record"], "stop:s1")
    assert resolve_state(e) == "pending" and e["proposed"] is True
    assert not out["record"].get("edits")
    with pytest.raises(ValueError):
        apply_edit(TRIP, "restore_block", {"part": "stop:s1"}, deps)      # not dismissed
    with pytest.raises(KeyError):
        apply_edit(TRIP, "restore_block", {"part": "stop:s9"}, deps)


# --- Review Focus 1: a live tracker event never drops an edit ----------------

def test_edit_survives_tracker_event(tmp_path):
    deps, clock = make_deps(tmp_path)
    evs = events_of(two_stops())
    second = next(i for i, e in enumerate(evs) if e.kind == "STOPPED" and e.stop_id == "s2")
    run(deps, clock, evs[:second])                        # out, s1 left; not yet at s2
    apply_edit(TRIP, "set_stop_times", {"stop_id": "s1", "start": "10:20", "end": "10:34"}, deps)
    rec = run(deps, clock, evs[second:second + 1])        # the tracker rewrites rec["trip"]
    trip = trip_of(rec)
    assert (hm(trip.stop("s1").start), hm(trip.stop("s1").end)) == ("10:20", "10:34")
    assert trip.stop("s2") is not None
    rec = run(deps, clock, evs[second + 1:])              # and on to home
    trip = trip_of(rec)
    assert (hm(trip.stop("s1").start), hm(trip.stop("s1").end)) == ("10:20", "10:34")
    assert rec["closed"] is True


def test_added_stop_survives_tracker_event(tmp_path):
    deps, clock = make_deps(tmp_path)
    evs = events_of(two_stops())
    second = next(i for i, e in enumerate(evs) if e.kind == "STOPPED" and e.stop_id == "s2")
    run(deps, clock, evs[:second])
    lat, lng = at(1000)
    assert clock["now"] < t(13, 10, 38)                   # out of s1, walking, no later
    apply_edit(TRIP, "add_stop", {"start": "10:36", "end": "10:37", "ref": "location:5"}, deps,
               resolve=lambda h: {"kind": "anchor", "lat": lat, "lng": lng, "accuracy_m": 12})
    rec = run(deps, clock, evs[second:])
    assert stop_ids(rec) == ["s1", "x1", "s2"]


# --- Review Focus 2: a tap on a stop the overlay changed -----------------------

def test_tap_on_changed_stop(tmp_path):
    deps, _ = closed_trip(tmp_path)
    rt = LocationRuntime(tmp_path / "loc", deps, synchronous=True)
    rec = deps.records.get(TRIP)
    rec["stops"]["s1"]["options"] = [{"name": "Sauna", "destination": "Sauna"}]
    deps.records.save(rec)
    apply_edit(TRIP, "split_stop", {"stop_id": "s1", "at": "10:27"}, deps)
    out = rt.tap(TRIP, "s1", "a0")
    assert out["toast"] == "That stop changed — see the latest message."
    rec = deps.records.get(TRIP)
    assert rec["stops"]["s1"].get("name") != "Sauna" and rec["stops"]["s1a"].get("name") != "Sauna"
    with pytest.raises(KeyError):
        rt.tap(TRIP, "s9", "a0")                          # never a stop of this trip


# --- what leaves apply_edit ----------------------------------------------------

def test_edit_result_has_no_coordinates(tmp_path):
    logs: list[dict] = []
    deps, _ = closed_trip(tmp_path, logs=logs)
    outs = [
        apply_edit(TRIP, "add_stop", {"start": "10:37", "end": "10:41", "name": "Kiosk"}, deps),
        apply_edit(TRIP, "split_stop", {"stop_id": "s1", "at": "10:27"}, deps),
        apply_edit(TRIP, "set_stop_times", {"stop_id": "s2", "start": "10:45"}, deps),
        apply_edit(TRIP, "merge_stops", {"stop_ids": ["s1a", "s1b"]}, deps),
        apply_edit(TRIP, "remove_stop", {"stop_id": "x1"}, deps),
    ]
    for out in outs:
        shown = json.dumps({k: v for k, v in out.items() if k != "record"}, ensure_ascii=False, default=str)
        assert '"lat"' not in shown and '"lng"' not in shown
        assert not re.search(r"\d+\.\d{4,}", shown)
    edits = [line for line in logs if line["event"] == "EDIT"]
    assert [e["op"] for e in edits] == ["add_stop", "split_stop", "set_stop_times", "merge_stops", "remove_stop"]
    assert edits[1]["stop_ids"] == ["s1", "s1a", "s1b"]
    for line in edits:
        text = json.dumps(line, default=str)
        assert '"lat"' not in text and '"lng"' not in text and not re.search(r"\d+\.\d{4,}", text)


def test_edit_returns_the_arrival_receipt(tmp_path):
    deps, _ = closed_trip(tmp_path)
    out = apply_edit(TRIP, "add_stop", {"start": "10:37", "end": "10:41", "name": "Kiosk"}, deps)
    assert out["receipt"]["turn_id"] == TRIP
    assert any(line["text"] == "Kiosk" for line in out["receipt"]["lines"])
    # the unsent arrival message is redrawn in place
    [arrival] = [i for i in deps.outbox.serve() if i["kind"] == "arrival"]
    assert "Kiosk" in json.dumps(arrival["receipt"], ensure_ascii=False)


# --- readers go through the overlay -------------------------------------------

def test_a_photo_during_an_added_stop_finds_it(tmp_path):
    deps, _ = closed_trip(tmp_path)
    apply_edit(TRIP, "add_stop", {"start": "10:37", "end": "10:41", "name": "Kiosk"}, deps)
    found = _stop_at(deps.records, t(13, 10, 39))
    assert found is not None and found[1].id == "x1" and found[2] == "Kiosk"


def test_records_on_day_and_trip_id(tmp_path):
    deps, _ = closed_trip(tmp_path)
    [rec] = deps.records.on_day(t(13, 12, 0).date(), TZ)
    assert trip_of(rec).id == TRIP
