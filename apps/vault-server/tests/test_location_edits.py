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


# --- fix round 1 ----------------------------------------------------------------

def approve(deps, rec, part, google=None):
    frag = fragments(rec["blocks"][part])[0]
    updates = {"state": "approved"}
    if google:
        updates["source_ids"] = {"calendar_id": google}
    deps.events.update_event(date=frag["date"], event_id=frag["event_id"], updates=updates)
    return frag["event_id"]


class FakeCalendar:
    def __init__(self, ok=True):
        self.ok = ok
        self.cancelled: list[str] = []

    async def cancel_event(self, event_id):
        self.cancelled.append(event_id)
        return self.ok


def by_name(deps, name, day="2026-11-13"):
    return [e for e in deps.events.get_events(day) if e.get("name") == name]


def test_split_keeps_an_approved_block_in_place(tmp_path):            # finding 1
    deps, _ = closed_trip(tmp_path)
    apply_answer(TRIP, "s1", "Café", None, deps)
    event_id = approve(deps, deps.records.get(TRIP), "stop:s1")
    out = apply_edit(TRIP, "split_stop", {"stop_id": "s1", "at": "10:27"}, deps)
    rec = out["record"]
    assert "stop:s1" not in rec["blocks"] and rec["blocks"]["stop:s1a"]["event_id"] == event_id
    [cafe] = by_name(deps, "Café")
    assert cafe["id"] == event_id and resolve_state(cafe) == "approved"
    assert (cafe["start_time"][11:16], cafe["end_time"][11:16]) == ("10:18", "10:27")
    assert cafe["trip"]["part"] == "stop:s1a"
    assert out["cancelled"] == []


def test_merge_extends_the_first_approved_block_and_cancels_the_other(tmp_path):   # finding 1
    deps, _ = closed_trip(tmp_path)
    deps.calendar = FakeCalendar()
    apply_answer(TRIP, "s1", "Market", None, deps)
    apply_answer(TRIP, "s2", "Bakery", None, deps)
    rec = deps.records.get(TRIP)
    market = approve(deps, rec, "stop:s1")
    approve(deps, rec, "stop:s2", google="g-bakery")
    out = apply_edit(TRIP, "merge_stops", {"stop_ids": ["s1", "s2"]}, deps)
    [m] = by_name(deps, "Market")
    assert m["id"] == market and resolve_state(m) == "approved" and m["end_time"][11:16] == "10:58"
    [b] = by_name(deps, "Bakery")                                        # never hard-deleted
    assert resolve_state(b) == "dismissed"
    assert deps.calendar.cancelled == ["g-bakery"]
    assert out["cancelled"] == ["stop:s2"] and out["calendar_failed"] == []
    assert not any(line["text"] == "Bakery" for line in out["receipt"]["lines"])


def test_remove_cancels_an_approved_block(tmp_path):                  # finding 1
    deps, _ = closed_trip(tmp_path)
    deps.calendar = FakeCalendar(ok=False)
    apply_answer(TRIP, "s2", "Bakery", None, deps)
    approve(deps, deps.records.get(TRIP), "stop:s2", google="g-bakery")
    out = apply_edit(TRIP, "remove_stop", {"stop_id": "s2"}, deps)
    [b] = by_name(deps, "Bakery")
    assert resolve_state(b) == "dismissed"
    assert out["cancelled"] == ["stop:s2"] and out["calendar_failed"] == ["stop:s2"]
    assert "g-bakery" not in json.dumps({k: v for k, v in out.items() if k != "record"})


def test_remove_without_google_just_dismisses(tmp_path):               # finding 1
    deps, _ = closed_trip(tmp_path)
    apply_answer(TRIP, "s2", "Bakery", None, deps)
    approve(deps, deps.records.get(TRIP), "stop:s2")
    out = apply_edit(TRIP, "remove_stop", {"stop_id": "s2"}, deps)
    [b] = by_name(deps, "Bakery")
    assert resolve_state(b) == "dismissed" and out["cancelled"] == ["stop:s2"]


def _open_until_s2(tmp_path):
    deps, clock = make_deps(tmp_path)
    evs = events_of(two_stops())
    second = next(i for i, e in enumerate(evs) if e.kind == "STOPPED" and e.stop_id == "s2")
    run(deps, clock, evs[:second])
    clock["now"] = t(13, 10, 46)
    return deps, clock, evs, second


def test_tracker_stop_absorbs_an_added_stop(tmp_path):                 # finding 2 (the probe)
    deps, clock, evs, second = _open_until_s2(tmp_path)
    lat, lng = at(1400)
    apply_edit(TRIP, "add_stop", {"start": "10:43", "end": "10:46", "ref": "location:7", "name": "Bakery"}, deps,
               resolve=lambda h: {"kind": "anchor", "lat": lat, "lng": lng, "accuracy_m": 10})
    assert "stop:x1" in deps.records.get(TRIP)["blocks"]
    rec = run(deps, clock, evs[second:second + 1])                       # STOPPED s2, from 10:43
    assert stop_ids(rec) == ["s1", "s2"]
    assert rec["edits"][0]["absorbed_by"] == "s2"
    assert rec["stops"]["s2"]["name"] == "Bakery"
    assert "stop:x1" not in rec["blocks"] and "stop:s2" in rec["blocks"]
    assert not [i for i in deps.outbox.serve() if i["kind"] == "question"]   # answered already
    rec = run(deps, clock, evs[second + 1:])
    assert stop_ids(rec) == ["s1", "s2"]
    [bakery] = by_name(deps, "Bakery")
    assert bakery["trip"]["part"] == "stop:s2" and bakery["end_time"][11:16] == "10:58"


def test_an_unanswered_added_stop_leaves_the_tracker_stop_to_be_asked(tmp_path):   # finding 2
    deps, clock, evs, second = _open_until_s2(tmp_path)
    lat, lng = at(1400)
    apply_edit(TRIP, "add_stop", {"start": "10:43", "end": "10:46", "ref": "location:7"}, deps,
               resolve=lambda h: {"kind": "anchor", "lat": lat, "lng": lng, "accuracy_m": 10})
    rec = run(deps, clock, evs[second:second + 1])
    assert stop_ids(rec) == ["s1", "s2"]
    assert rec["stops"]["s2"]["status"] == "asked"


def test_arrival_line_ids_survive_an_edit(tmp_path):                  # finding 3
    deps, _ = closed_trip(tmp_path)
    rt = LocationRuntime(tmp_path / "loc", deps, synchronous=True)
    apply_answer(TRIP, "s2", "Bakery", None, deps)
    sent = rt.render_arrival(TRIP)
    bakery = next(line for line in sent["lines"] if line["text"] == "Bakery")
    data = bakery["buttons"][0]["data"]                                # trip:<id>:<n>:ok
    apply_edit(TRIP, "add_stop", {"start": "10:37", "end": "10:41", "name": "Kiosk"}, deps)  # a line before it
    line = data.split(":")[2]
    out = rt.tap(TRIP, line, "ok")
    rec = deps.records.get(TRIP)
    frag = fragments(rec["blocks"]["stop:s2"])[0]
    assert out["approvals"] == [(frag["date"], frag["event_id"], "approved")]
    # the trip line keeps its number too, and the new line gets one never used before
    ids = rec["line_ids"]
    assert len(set(ids.values())) == len(ids) and ids["stop:x1"] == max(ids.values())


def test_arrival_line_gone_after_its_stop_is_removed(tmp_path):        # finding 3
    deps, _ = closed_trip(tmp_path)
    rt = LocationRuntime(tmp_path / "loc", deps, synchronous=True)
    apply_answer(TRIP, "s2", "Bakery", None, deps)
    sent = rt.render_arrival(TRIP)
    line = next(x for x in sent["lines"] if x["text"] == "Bakery")["buttons"][0]["data"].split(":")[2]
    apply_edit(TRIP, "remove_stop", {"stop_id": "s2"}, deps)
    out = rt.tap(TRIP, line, "ok")
    assert out["toast"] == "That line is gone — refresh /day." and out["approvals"] == []


def test_old_record_without_line_ids_keeps_its_drawn_order(tmp_path):  # finding 3
    deps, _ = closed_trip(tmp_path)
    rt = LocationRuntime(tmp_path / "loc", deps, synchronous=True)
    apply_answer(TRIP, "s2", "Bakery", None, deps)
    rec = deps.records.get(TRIP)
    rec.pop("line_ids", None)
    rec["arrival_lines"] = ["trip", "stop:s2"]                          # as an old message drew it
    deps.records.save(rec)
    out = rt.tap(TRIP, "2", "ok")
    frag = fragments(rec["blocks"]["stop:s2"])[0]
    assert out["approvals"] == [(frag["date"], frag["event_id"], "approved")]


def test_restore_block_of_a_stop_no_longer_planned_refused(tmp_path):  # finding 4
    deps, _ = closed_trip(tmp_path)
    apply_answer(TRIP, "s2", "Bakery", None, deps)
    approve(deps, deps.records.get(TRIP), "stop:s2")
    apply_edit(TRIP, "remove_stop", {"stop_id": "s2"}, deps)
    with pytest.raises(ValueError):
        apply_edit(TRIP, "restore_block", {"part": "stop:s2"}, deps)
    [b] = by_name(deps, "Bakery")
    assert resolve_state(b) == "dismissed"


def test_split_of_an_asked_stop_asks_at_home(tmp_path):               # finding 5
    deps, clock = make_deps(tmp_path)
    evs = events_of(two_stops())
    first_left = next(i for i, e in enumerate(evs) if e.kind == "LEFT_STOP")
    run(deps, clock, evs[:first_left])                                  # at s1, its question live
    assert deps.records.get(TRIP)["stops"]["s1"]["status"] == "asked"
    clock["now"] = t(13, 10, 30)
    rec = apply_edit(TRIP, "split_stop", {"stop_id": "s1", "at": "10:25"}, deps)["record"]
    assert rec["stops"]["s1a"]["status"] == "later"
    assert not [i for i in deps.outbox.serve() if i["kind"] == "question"]


# --- fix round 2 ----------------------------------------------------------------

def walk_with_approved_legs(tmp_path):
    """Walk → Gan Meir via Market (s1) and Bakery (s2), every leg approved."""
    deps, clock = closed_trip(tmp_path)
    deps.calendar = FakeCalendar()
    apply_answer(TRIP, None, "Walk", "Gan Meir", deps)
    apply_answer(TRIP, "s1", "Market", None, deps)
    apply_answer(TRIP, "s2", "Bakery", None, deps)
    rec = deps.records.get(TRIP)
    legs = {p: approve(deps, rec, p) for p in rec["blocks"] if p.startswith("leg:")}
    assert sorted(legs) == ["leg:s1-s2", "leg:s2-home", "leg:start-s1"]
    return deps, legs


def state_of(deps, rec, part):
    return resolve_state(block(deps, rec, part))


def assert_legs_sound(deps, out):
    """No approved leg orphaned, no leg drawn twice."""
    rec = out["record"]
    drawn = [line["text"] for line in out["receipt"]["lines"] if line["text"].startswith("Walk")]
    assert len(drawn) == len(set(drawn)), drawn
    for part, ref in rec["blocks"].items():
        if part.startswith("leg:") and not ref.get("cancelled"):
            assert part in rec["arrival_lines"], part          # every live leg is planned and drawn


def test_remove_stop_hands_its_approved_leg_to_the_joined_leg(tmp_path):
    deps, legs = walk_with_approved_legs(tmp_path)
    out = apply_edit(TRIP, "remove_stop", {"stop_id": "s2"}, deps)
    rec = out["record"]
    assert_legs_sound(deps, out)
    # s1→s2 is now the joined leg s1→home: the same event, still approved, times updated in place
    assert rec["blocks"]["leg:s1-home"]["event_id"] == legs["leg:s1-s2"]
    assert state_of(deps, rec, "leg:s1-home") == "approved"
    e = block(deps, rec, "leg:s1-home")
    assert (e["start_time"][11:16], e["end_time"][11:16], e["name"]) == ("10:35", "11:15", "Walk home")
    # s2→home led out of the removed stop: cancelled, reversibly, never deleted
    assert rec["blocks"]["leg:s2-home"]["cancelled"] is True
    assert state_of(deps, rec, "leg:s2-home") == "dismissed"
    assert out["cancelled"] == ["leg:s2-home"]
    assert state_of(deps, rec, "leg:start-s1") == "approved"


def test_merge_stops_moves_the_leg_out_and_cancels_the_one_inside(tmp_path):
    deps, legs = walk_with_approved_legs(tmp_path)
    out = apply_edit(TRIP, "merge_stops", {"stop_ids": ["s1", "s2"]}, deps)
    rec = out["record"]
    assert_legs_sound(deps, out)
    assert rec["blocks"]["leg:s1-home"]["event_id"] == legs["leg:s2-home"]
    assert state_of(deps, rec, "leg:s1-home") == "approved"
    assert state_of(deps, rec, "leg:s1-s2") == "dismissed" and out["cancelled"] == ["leg:s1-s2"]
    assert rec["blocks"]["leg:start-s1"]["event_id"] == legs["leg:start-s1"]


def test_split_stop_moves_both_legs_onto_the_halves(tmp_path):
    deps, legs = walk_with_approved_legs(tmp_path)
    out = apply_edit(TRIP, "split_stop", {"stop_id": "s1", "at": "10:27"}, deps)
    rec = out["record"]
    assert_legs_sound(deps, out)
    assert rec["blocks"]["leg:start-s1a"]["event_id"] == legs["leg:start-s1"]
    # s1b (8 unnamed minutes) is no leg break, so the leg into s2 now starts at s1a
    assert rec["blocks"]["leg:s1a-s2"]["event_id"] == legs["leg:s1-s2"]
    assert {state_of(deps, rec, p) for p in ("leg:start-s1a", "leg:s1a-s2", "leg:s2-home")} == {"approved"}
    assert block(deps, rec, "leg:s1a-s2")["start_time"][11:16] == "10:27"
    assert "leg:start-s1" not in rec["blocks"] and "leg:s1-s2" not in rec["blocks"]
    assert out["cancelled"] == []
    assert block(deps, rec, "leg:s1a-s2")["trip"]["part"] == "leg:s1a-s2"


def test_absorb_judges_overlap_by_your_edited_times(tmp_path):         # the pin probe
    logs: list[dict] = []
    deps, clock = make_deps(tmp_path, logs=logs)
    evs = events_of(two_stops())
    second = next(i for i, e in enumerate(evs) if e.kind == "STOPPED" and e.stop_id == "s2")
    run(deps, clock, evs[:second])
    clock["now"] = t(13, 10, 46)
    apply_edit(TRIP, "set_stop_times", {"stop_id": "s1", "end": "10:26"}, deps)   # tracker says 10:35
    lat, lng = at(760)
    apply_edit(TRIP, "add_stop", {"start": "10:30", "end": "10:34", "ref": "location:7", "name": "Kiosk"}, deps,
               resolve=lambda h: {"kind": "anchor", "lat": lat, "lng": lng, "accuracy_m": 10})
    approve(deps, deps.records.get(TRIP), "stop:x1")
    rec = run(deps, clock, evs[second:second + 1])
    assert stop_ids(rec) == ["s1", "x1", "s2"]
    assert not rec["edits"][1].get("absorbed_by")
    [kiosk] = by_name(deps, "Kiosk")
    assert resolve_state(kiosk) == "approved" and not rec["blocks"]["stop:x1"].get("cancelled")
    assert not [line for line in logs if line["event"] == "ABSORB"]


def test_no_absorb_into_a_stop_you_named(tmp_path):
    deps, clock, evs, second = _open_until_s2(tmp_path)
    apply_answer(TRIP, "s1", "Market", None, deps)
    clock["now"] = t(13, 10, 37)
    rec = deps.records.get(TRIP)
    # an added stop the tracker's s1 (10:18–10:35) would cover, were it not answered
    rec.setdefault("edits", []).append({"op": "add_stop", "id": "x1", "start": t(13, 10, 30).isoformat(),
                                        "end": t(13, 10, 34).isoformat(), "lat": at(760)[0], "lng": at(760)[1],
                                        "spread_m": 5, "from_home_m": 760})
    rec["stops"]["x1"] = {"status": "named", "name": "Kiosk", "answered": True}
    deps.records.save(rec)
    rec = run(deps, clock, evs[second:second + 1])
    assert not rec["edits"][0].get("absorbed_by")
    assert rec["stops"]["s1"]["name"] == "Market"


def test_absorb_log_line_carries_names_only(tmp_path):
    logs: list[dict] = []
    deps, clock = make_deps(tmp_path, logs=logs)
    evs = events_of(two_stops())
    second = next(i for i, e in enumerate(evs) if e.kind == "STOPPED" and e.stop_id == "s2")
    run(deps, clock, evs[:second])
    clock["now"] = t(13, 10, 46)
    lat, lng = at(1400)
    apply_edit(TRIP, "add_stop", {"start": "10:43", "end": "10:46", "ref": "location:7", "name": "Bakery"}, deps,
               resolve=lambda h: {"kind": "anchor", "lat": lat, "lng": lng, "accuracy_m": 10})
    run(deps, clock, evs[second:second + 1])
    [line] = [x for x in logs if x["event"] == "ABSORB"]
    assert line["stop_ids"] == ["x1", "s2"] and line["cancelled"] == [] and line["calendar_failed"] == []
    text = json.dumps(line, default=str)
    assert '"lat"' not in text and not re.search(r"\d+\.\d{4,}", text)


# --- Task 10: splitting and joining trips ---------------------------------------

def owners(deps):
    """event_id → the trip records that hold it in their blocks: never more than one."""
    out: dict[str, list[str]] = {}
    for rec in deps.records.all():
        for ref in (rec.get("blocks") or {}).values():
            if ref.get("gone"):
                continue
            for frag in fragments(ref):
                out.setdefault(frag["event_id"], []).append(rec["id"])
    return out


def assert_no_event_owned_twice(deps):
    twice = {k: v for k, v in owners(deps).items() if len(v) > 1}
    assert not twice, twice


def named_errands(deps):
    apply_answer(TRIP, None, "Errands", None, deps)
    apply_answer(TRIP, "s1", "Market", None, deps)
    apply_answer(TRIP, "s2", "Bakery", None, deps)


def test_split_closed_trip_at_a_stop(tmp_path):
    deps, _ = closed_trip(tmp_path)
    named_errands(deps)
    bakery = approve(deps, deps.records.get(TRIP), "stop:s2")
    out = apply_edit(TRIP, "split_trip", {"at": "s1"}, deps)
    first = out["record"]
    new_id = out["split_into"]
    second = deps.records.get(new_id)
    assert re.fullmatch(r"[0-9a-f]{8}", new_id) and new_id != TRIP
    # the first ends where s1 ends, closed; the second starts there
    t1, t2 = trip_of(first), trip_of(second)
    assert stop_ids(first) == ["s1"] and stop_ids(second) == ["s2"]
    assert t1.back_at == t1.stop("s1").end == t2.left_at
    assert first["closed"] is True and first["split_into"] == new_id
    assert second["split_from"] == TRIP and second["closed"] is True
    assert first["edits"][-1] == {"op": "window", "end": t1.back_at.isoformat()}
    assert {"op": "window", "start": t2.left_at.isoformat()}.items() <= second["edits"][-1].items()
    # what you said about each stop went with it; the purpose stayed with the first
    assert "s2" not in first["stops"] and second["stops"]["s2"]["name"] == "Bakery"
    assert first["purpose"]["name"] == "Errands" and not (second.get("purpose") or {}).get("name")
    # blocks went with their stops: the approved Bakery block is the second's, still approved
    assert "stop:s2" not in first["blocks"] and second["blocks"]["stop:s2"]["event_id"] == bakery
    [b] = by_name(deps, "Bakery")
    assert resolve_state(b) == "approved" and b["trip"] == {"id": new_id, "part": "stop:s2"}
    assert out["cancelled"] == []
    # the first's trip block ends at the cut; the second has a pending trip proposal of its own
    assert block(deps, first, "trip")["end_time"][11:16] == hm(t1.back_at)
    own = block(deps, second, "trip")
    assert own["proposed"] is True and resolve_state(own) == "pending" and own["trip"]["id"] == new_id
    assert second["trip_question"] is not None                  # the second asks on its own
    assert deps.outbox.find(TRIP, "arrival") and deps.outbox.find(new_id, "arrival")
    assert_no_event_owned_twice(deps)


def test_split_at_a_stop_into_the_second_with_the_purpose(tmp_path):
    deps, _ = closed_trip(tmp_path)
    named_errands(deps)
    out = apply_edit(TRIP, "split_trip", {"at": "s2", "stop_side": "second", "purpose_to": "second"}, deps)
    first, second = out["record"], deps.records.get(out["split_into"])
    assert stop_ids(first) == ["s1"] and stop_ids(second) == ["s2"]
    assert hm(trip_of(first).back_at) == "10:43" == hm(trip_of(second).left_at)
    assert second["purpose"]["name"] == "Errands" and not first.get("purpose")
    assert first["trip_question"] is not None                    # now the first has none: it asks
    assert block(deps, second, "trip")["name"] == "Errands"
    assert_no_event_owned_twice(deps)


def test_split_by_time(tmp_path):
    deps, _ = closed_trip(tmp_path)
    out = apply_edit(TRIP, "split_trip", {"at": "10:39"}, deps)       # walking from s1 to s2
    first, second = out["record"], deps.records.get(out["split_into"])
    assert stop_ids(first) == ["s1"] and stop_ids(second) == ["s2"]
    assert hm(trip_of(first).back_at) == "10:39" == hm(trip_of(second).left_at)
    assert_no_event_owned_twice(deps)


def test_split_by_a_time_inside_a_stop_goes_to_its_edge(tmp_path):
    deps, _ = closed_trip(tmp_path)
    out = apply_edit(TRIP, "split_trip", {"at": "10:50"}, deps)       # inside s2: s2 stays first
    first = out["record"]
    assert stop_ids(first) == ["s1", "s2"] and hm(trip_of(first).back_at) == "10:58"
    assert stop_ids(deps.records.get(out["split_into"])) == []
    deps, _ = closed_trip(tmp_path / "b")
    out = apply_edit(TRIP, "split_trip", {"at": "10:50", "stop_side": "second"}, deps)
    assert hm(trip_of(out["record"]).back_at) == "10:43"
    assert stop_ids(deps.records.get(out["split_into"])) == ["s2"]


def test_split_refused_outside_the_trip(tmp_path):
    deps, _ = closed_trip(tmp_path)
    for when in ("09:00", "11:40"):
        with pytest.raises(ValueError):
            apply_edit(TRIP, "split_trip", {"at": when}, deps)
    with pytest.raises(KeyError):
        apply_edit(TRIP, "split_trip", {"at": "s9"}, deps)
    with pytest.raises(ValueError):
        apply_edit(TRIP, "split_trip", {"at": "s1", "stop_side": "middle"}, deps)
    rec = deps.records.get(TRIP)
    assert not rec.get("split_into") and len(deps.records.all()) == 1


def test_split_never_cancels_an_approved_leg(tmp_path):
    deps, legs = walk_with_approved_legs(tmp_path)
    out = apply_edit(TRIP, "split_trip", {"at": "s1"}, deps)
    first, second = out["record"], deps.records.get(out["split_into"])
    assert out["cancelled"] == []
    for event_id in legs.values():
        held = owners(deps)[event_id]
        assert len(held) == 1
        e = next(e for e in deps.events.get_events("2026-11-13") if e["id"] == event_id)
        assert resolve_state(e) == "approved" and e["trip"]["id"] == held[0]
    # the leg out of s1 starts at the cut: it is the second's
    assert legs["leg:s1-s2"] in [r["event_id"] for r in second["blocks"].values()]
    assert first["blocks"]["leg:start-s1"]["event_id"] == legs["leg:start-s1"]
    assert_no_event_owned_twice(deps)


def test_split_result_has_no_coordinates(tmp_path):
    logs: list[dict] = []
    deps, _ = closed_trip(tmp_path, logs=logs)
    out = apply_edit(TRIP, "split_trip", {"at": "s1"}, deps)
    shown = json.dumps({k: v for k, v in out.items() if k != "record"}, ensure_ascii=False, default=str)
    assert '"lat"' not in shown and '"lng"' not in shown and not re.search(r"\d+\.\d{4,}", shown)
    edits = [line for line in logs if line["event"] == "EDIT"]
    assert edits and all(not re.search(r"\d+\.\d{4,}", json.dumps(x, default=str)) for x in edits)


# --- Review Focus 5: split the open trip, then the tracker carries on --------------

def test_split_open_trip_then_home(tmp_path):
    deps, clock, evs, second = _open_until_s2(tmp_path)
    apply_answer(TRIP, "s1", "Market", None, deps)
    out = apply_edit(TRIP, "split_trip", {"at": "s1"}, deps)
    new_id = out["split_into"]
    first = deps.records.get(TRIP)
    assert first["closed"] is True and deps.records.get(new_id)["closed"] is False
    before = (trip_of(first).to_dict(), first["blocks"], first["stops"], first.get("purpose"))
    run(deps, clock, evs[second:])                                  # STOPPED s2 … BACK_HOME
    first, tail = deps.records.get(TRIP), deps.records.get(new_id)
    assert tail["closed"] is True and stop_ids(tail) == ["s2"]
    assert (trip_of(first).to_dict(), first["blocks"], first["stops"], first.get("purpose")) == before
    # s2 was handled on the record it was split into: asked there, never on the first
    assert "s2" in tail["stops"] and "s2" not in first["stops"]
    # every record in the chain carries the tracker's trip; the windows keep them apart
    assert first["trip"] == tail["trip"] and first["trip"]["back_at"] is not None
    assert deps.outbox.find(new_id, "arrival") is not None
    assert_no_event_owned_twice(deps)


def test_tracker_events_follow_the_split_chain(tmp_path):
    deps, clock, evs, second = _open_until_s2(tmp_path)
    mid = apply_edit(TRIP, "split_trip", {"at": "s1"}, deps)["split_into"]
    left_s2 = next(i for i, e in enumerate(evs) if e.kind == "LEFT_STOP" and e.stop_id == "s2")
    run(deps, clock, evs[second:left_s2 + 1])                       # at s2 and away again: on `mid`
    clock["now"] = evs[left_s2].ts
    last = apply_edit(mid, "split_trip", {"at": "s2"}, deps)["split_into"]
    run(deps, clock, evs[left_s2 + 1:])                             # BACK_HOME goes to the last one
    a, b, c = (deps.records.get(i) for i in (TRIP, mid, last))
    assert a["split_into"] == mid and b["split_from"] == TRIP and b["split_into"] == last
    assert c["split_from"] == mid
    assert stop_ids(a) == ["s1"] and stop_ids(b) == ["s2"] and stop_ids(c) == []
    assert all(r["closed"] for r in (a, b, c))
    assert trip_of(c).back_at is not None and a["trip"] == b["trip"] == c["trip"]
    assert_no_event_owned_twice(deps)


# --- joining --------------------------------------------------------------------

OTHER = "5e6f7a8b"
THIRD = "9c0d1e2f"


def three_trips():
    """TRIP (two_stops, home 11:15), OTHER out 12:00 to a stop at 500 m, THIRD out 13:20."""
    return two_stops().stay(40).walk_to(500).stay(10).walk_to(0).stay(40).walk_to(300).stay(6) \
        .walk_to(0).stay(5)


def run_three(tmp_path, upto=None):
    deps, clock = make_deps(tmp_path)
    ids = iter([TRIP, OTHER, THIRD])
    evs = feed_all(Tracker(HOME, [], new_id=lambda: next(ids)), three_trips().fixes)
    if upto is not None:
        evs = evs[:upto(evs)]
    for ev in evs:
        clock["now"] = ev.ts
        handle_event(ev, deps)
    return deps, clock, evs


def test_join_two_closed_trips(tmp_path):
    deps, _, _ = run_three(tmp_path)
    apply_answer(TRIP, "s1", "Market", None, deps)
    apply_answer(OTHER, "s1", "Kiosk", None, deps)
    other_back = trip_of(deps.records.get(OTHER)).back_at
    out = apply_edit(TRIP, "join_trips", {"other_trip_id": OTHER}, deps)
    first, other = out["record"], deps.records.get(OTHER)
    assert out["trip_id"] == TRIP
    assert stop_ids(first) == ["s1", "s2", "js1"]
    assert trip_of(first).back_at == other_back
    assert first["stops"]["js1"]["name"] == "Kiosk"
    assert other["joined_into"] == TRIP and other["blocks"] == {}
    assert first["edits"][-1]["op"] == "join"
    assert [s["id"] for s in first["edits"][-1]["trip"]["stops"]] == ["js1"]
    # one arrival message for the joined trip
    assert deps.outbox.find(TRIP, "arrival") is not None and deps.outbox.find(OTHER, "arrival") is None
    # the other's pending guesses are gone; the joined trip's own blocks cover its stop
    assert not [e for e in deps.events.get_events("2026-11-13") if (e.get("trip") or {}).get("id") == OTHER]
    assert block(deps, first, "stop:js1")["name"] == "Kiosk"
    assert block(deps, first, "trip")["end_time"][11:16] == hm(other_back)
    assert_no_event_owned_twice(deps)


def test_join_from_the_later_trip_keeps_the_first(tmp_path):
    deps, _, _ = run_three(tmp_path)
    out = apply_edit(OTHER, "join_trips", {"other_trip_id": TRIP}, deps)
    assert out["trip_id"] == TRIP and deps.records.get(OTHER)["joined_into"] == TRIP


def test_join_refused_while_open(tmp_path):
    def at_other_stop(evs):
        return next(i for i, e in enumerate(evs) if e.kind == "STOPPED" and e.trip.id == OTHER) + 1
    deps, _, _ = run_three(tmp_path, upto=at_other_stop)
    with pytest.raises(ValueError, match="a trip is still open"):
        apply_edit(TRIP, "join_trips", {"other_trip_id": OTHER}, deps)
    assert not deps.records.get(OTHER).get("joined_into")


def test_join_refused_when_not_consecutive(tmp_path):
    deps, _, _ = run_three(tmp_path)
    with pytest.raises(ValueError):
        apply_edit(TRIP, "join_trips", {"other_trip_id": THIRD}, deps)      # OTHER came between
    with pytest.raises(ValueError):
        apply_edit(TRIP, "join_trips", {"other_trip_id": TRIP}, deps)
    with pytest.raises(KeyError):
        apply_edit(TRIP, "join_trips", {"other_trip_id": "ffffffff"}, deps)


def test_join_keeps_an_approved_block_of_the_joined_trip(tmp_path):
    deps, _, _ = run_three(tmp_path)
    apply_answer(OTHER, "s1", "Kiosk", None, deps)
    other = deps.records.get(OTHER)
    kiosk = approve(deps, other, "stop:s1")
    own_trip = approve(deps, other, "trip")
    approve(deps, deps.records.get(TRIP), "trip")                 # the first's trip block is yours too
    out = apply_edit(TRIP, "join_trips", {"other_trip_id": OTHER}, deps)
    first = out["record"]
    # its stop is planned in the joined trip: re-keyed there, the same event, still approved
    assert first["blocks"]["stop:js1"]["event_id"] == kiosk
    [k] = by_name(deps, "Kiosk")
    assert resolve_state(k) == "approved" and k["trip"] == {"id": TRIP, "part": "stop:js1"}
    # its trip block has nowhere to go (the first holds one you approved): it is yours now,
    # no trip's block; the writer's merge rules then treat it as a block of yours
    e = next(e for e in deps.events.get_events("2026-11-13") if e["id"] == own_trip)
    assert resolve_state(e) == "approved" and not e.get("proposed")
    assert own_trip not in owners(deps)
    assert_no_event_owned_twice(deps)


def test_history_skips_a_joined_trip(tmp_path):
    from src.services.location.history import load_confirmed

    deps, clock, _ = run_three(tmp_path)
    apply_answer(TRIP, None, "Errands", None, deps)
    apply_answer(OTHER, None, "Gym", None, deps)
    apply_edit(TRIP, "join_trips", {"other_trip_id": OTHER}, deps)
    purposes = [c.purpose for c in load_confirmed(deps.labels_dir, deps.records, deps.events, TZ, clock["now"])]
    assert "Gym" not in purposes and "Errands" in purposes


def test_join_result_has_no_coordinates(tmp_path):
    deps, _, _ = run_three(tmp_path)
    out = apply_edit(TRIP, "join_trips", {"other_trip_id": OTHER}, deps)
    shown = json.dumps({k: v for k, v in out.items() if k != "record"}, ensure_ascii=False, default=str)
    assert '"lat"' not in shown and not re.search(r"\d+\.\d{4,}", shown)


def test_a_joined_trip_answers_through_the_trip_it_joined(tmp_path):
    deps, _, _ = run_three(tmp_path)
    apply_edit(TRIP, "join_trips", {"other_trip_id": OTHER}, deps)
    rt = LocationRuntime(tmp_path / "loc", deps, synchronous=True)
    # a reply to the other trip's old message reaches the joined trip, its stop by its new id
    out = rt.answer(OTHER, "s1", "Kiosk", None)
    assert out["trip_id"] == TRIP and out["stop_id"] == "js1"
    assert deps.records.get(TRIP)["stops"]["js1"]["name"] == "Kiosk"
    other = deps.records.get(OTHER)
    assert other["blocks"] == {} and not other["stops"].get("s1", {}).get("answered")
    # a button on the old message does nothing there
    tap = rt.tap(OTHER, "trip", "a0")
    assert tap["toast"] == "That trip is part of another one now — see the latest message."
    assert deps.records.get(OTHER)["blocks"] == {}
    with pytest.raises(ValueError):
        apply_edit(OTHER, "remove_stop", {"stop_id": "s1"}, deps)


# --- Task 10, fix round 1 ---------------------------------------------------------

def correct(deps, rec, part):
    """✎ on a block, never ✓: a field pinned, the block still a pending proposal."""
    frag = fragments(rec["blocks"][part])[0]
    e = block(deps, rec, part)
    deps.events.update_event(date=frag["date"], event_id=frag["event_id"],
                             updates={"start_time": e["start_time"]}, user_set_fields=["start_time"])
    return frag["event_id"]


def test_a_corrected_proposal_of_the_joined_trip_stays_a_proposal(tmp_path):   # finding 1
    deps, _, _ = run_three(tmp_path)
    other = deps.records.get(OTHER)
    corrected = correct(deps, other, "trip")
    approve(deps, deps.records.get(TRIP), "trip")       # the first's trip part is taken: nowhere to move it
    out = apply_edit(TRIP, "join_trips", {"other_trip_id": OTHER}, deps)
    first = out["record"]
    e = next(e for e in deps.events.get_events("2026-11-13") if e["id"] == corrected)
    assert e["proposed"] is True and resolve_state(e) == "pending"         # never approved without a ✓
    assert not (e.get("source_ids") or {}).get("calendar_id")
    assert owners(deps)[corrected] == [TRIP]
    part = next(p for p, ref in first["blocks"].items() if ref.get("event_id") == corrected)
    assert e["trip"] == {"id": TRIP, "part": part}
    line = next(x for x in out["receipt"]["lines"] if x["text"] == e["name"])
    assert line["buttons"] and line["buttons"][0]["data"].endswith(":ok")     # still asks for ✓
    assert_no_event_owned_twice(deps)


def test_a_dismissed_block_of_the_joined_trip_stays_dismissed(tmp_path):      # finding 1
    deps, _, _ = run_three(tmp_path)
    other = deps.records.get(OTHER)
    frag = fragments(other["blocks"]["trip"])[0]
    deps.events.update_event(date=frag["date"], event_id=frag["event_id"], updates={"state": "dismissed"})
    approve(deps, deps.records.get(TRIP), "trip")
    apply_edit(TRIP, "join_trips", {"other_trip_id": OTHER}, deps)
    e = next(e for e in deps.events.get_events("2026-11-13") if e["id"] == frag["event_id"])
    assert resolve_state(e) == "dismissed" and e.get("proposed") is True


def photo_on(deps, rec, part, path="IMG_1.jpg"):
    frag = fragments(rec["blocks"][part])[0]
    deps.events.attach_photo(frag["date"], frag["event_id"], path)


def test_a_photo_follows_onto_the_approved_leg_that_takes_its_place(tmp_path):   # finding 2, _follow_legs
    deps, clock = closed_trip(tmp_path)
    apply_answer(TRIP, None, "Walk", "Gan Meir", deps)
    apply_answer(TRIP, "s1", "Market", None, deps)
    apply_answer(TRIP, "s2", "Bakery", None, deps)
    rec = deps.records.get(TRIP)
    leg = approve(deps, rec, "leg:s1-s2")
    # a pending guess holding a photo sits where the approved leg goes once s2 is removed
    from src.services.location.edits import rekey_block
    rekey_block(rec, "leg:s2-home", "leg:s1-home", deps)
    photo_on(deps, rec, "leg:s1-home")
    deps.records.save(rec)
    out = apply_edit(TRIP, "remove_stop", {"stop_id": "s2"}, deps)
    rec = out["record"]
    assert rec["blocks"]["leg:s1-home"]["event_id"] == leg
    assert [p["path"] for p in block(deps, rec, "leg:s1-home").get("photos") or []] == ["IMG_1.jpg"]


def test_a_photo_follows_onto_the_approved_leg_a_split_or_join_settles(tmp_path):   # finding 2, _settle_legs
    from src.services.location.edits import _settle_legs, rekey_block
    from src.services.location.pipeline import _apply, _places

    deps, clock = closed_trip(tmp_path)
    apply_answer(TRIP, None, "Walk", "Gan Meir", deps)
    apply_answer(TRIP, "s1", "Market", None, deps)
    apply_answer(TRIP, "s2", "Bakery", None, deps)
    rec = deps.records.get(TRIP)
    leg = approve(deps, rec, "leg:s1-s2")
    rekey_block(rec, "leg:s1-s2", "leg:x9-s2", deps)       # the approved leg under a key no longer planned
    _apply(rec, deps, _places(deps))                         # … and a pending guess where it belongs
    photo_on(deps, rec, "leg:s1-s2")
    _settle_legs(rec, deps, _places(deps))
    assert rec["blocks"]["leg:s1-s2"]["event_id"] == leg
    assert [p["path"] for p in block(deps, rec, "leg:s1-s2").get("photos") or []] == ["IMG_1.jpg"]
