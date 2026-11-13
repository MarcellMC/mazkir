"""Plan Task 12: the runtime — tracker state, the inbox, the worker and the clock."""

from __future__ import annotations

import datetime as dt
import json

from src.services.fast_lane.places import load_places
from src.services.location.runtime import LocationRuntime
from tests.location_fixtures import Track, t
from tests.location_pipeline_fixtures import make_deps


def points(track, kind="live"):
    return [{"source": "telegram", "kind": kind, "ts": f.ts, "lat": f.lat, "lng": f.lng,
             "accuracy_m": f.accuracy_m, "chat_id": 156175834} for f in track.fixes]


def walk_out():
    return Track(t(13, 9, 0)).stay(10).walk_to(400)


def test_feed_turns_points_into_a_trip_and_serves_the_outbox(tmp_path):
    deps, _ = make_deps(tmp_path)
    rt = LocationRuntime(tmp_path / "loc", deps, synchronous=True)
    for p in points(walk_out()):
        rt.feed(p)
    [rec] = deps.records.all()
    assert rec["trip"]["origin"] == "home" and rec["blocks"]["trip"]
    assert json.loads((tmp_path / "loc" / "state.json").read_text())["chat_id"] == 156175834


def test_check_ins_do_not_reach_the_tracker(tmp_path):
    deps, _ = make_deps(tmp_path)
    rt = LocationRuntime(tmp_path / "loc", deps, synchronous=True)
    for p in points(walk_out(), kind="check_in"):
        rt.feed(p)
    assert deps.records.all() == [] and rt.tracker.last_fix_ts is None


def test_inbox_survives_a_restart(tmp_path):                         # Review Focus 3
    deps, _ = make_deps(tmp_path)
    crashing = make_deps(tmp_path)[0]
    crashing.run_tool = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("crash"))
    rt = LocationRuntime(tmp_path / "loc", crashing, synchronous=True)
    for p in points(walk_out()):
        rt.feed(p)
    inbox = json.loads((tmp_path / "loc" / "inbox.json").read_text())["events"]
    assert [e["event"]["kind"] for e in inbox] == ["LEFT"]
    LocationRuntime(tmp_path / "loc", deps, synchronous=True)
    assert json.loads((tmp_path / "loc" / "inbox.json").read_text())["events"] == []
    assert deps.records.all()[0]["blocks"]["trip"]


def test_tracker_state_survives_a_restart(tmp_path):
    deps, _ = make_deps(tmp_path)
    rt = LocationRuntime(tmp_path / "loc", deps, synchronous=True)
    for p in points(walk_out()):
        rt.feed(p)
    rt2 = LocationRuntime(tmp_path / "loc", deps, synchronous=True)
    assert rt2.tracker.trip is not None and rt2.tracker.trip.id == rt.tracker.trip.id


def test_share_stopped_notice_once(tmp_path):
    deps, _ = make_deps(tmp_path)
    rt = LocationRuntime(tmp_path / "loc", deps, synchronous=True)
    track = walk_out()
    for p in points(track):
        rt.feed(p)
    later = track.fixes[-1].ts + dt.timedelta(minutes=31)
    notices = rt.tick(later)
    assert [n["text"] for n in notices] == ["Location sharing stopped — share again to keep your day filling in"]
    assert rt.tick(later + dt.timedelta(minutes=5)) == []


def test_home_is_found_and_announced(tmp_path):
    deps, _ = make_deps(tmp_path)
    deps.places_path.write_text('{"places": []}')
    from src.services.location_store import append_point
    for day in (10, 11, 12):
        for f in Track(t(day, 1, 0)).stay(240).fixes:
            append_point(tmp_path / "loc", {"source": "telegram", "kind": "live", "ts": f.ts, "lat": f.lat,
                                            "lng": f.lng, "accuracy_m": 8}, "Asia/Jerusalem")
    rt = LocationRuntime(tmp_path / "loc", deps, synchronous=True)
    rt.tick(t(13, 9, 0))
    assert any(p.id == "home" for p in load_places(deps.places_path))
    assert rt.tracker.home is not None
    assert [i["receipt"]["text"] for i in deps.outbox.serve()] == ["I found home — trips from here will fill your day."]


def test_tap_on_a_stop_option_answers_it(tmp_path):
    deps, _ = make_deps(tmp_path)
    rt = LocationRuntime(tmp_path / "loc", deps, synchronous=True)
    for p in points(Track(t(13, 10, 0)).stay(10).walk_to(700).stay(6)):
        rt.feed(p)
    [rec] = deps.records.all()
    rec["stops"]["s1"]["options"] = [{"name": "Sauna", "destination": "Sauna"}]
    deps.records.save(rec)
    out = rt.tap(rec["id"], "s1", "a0")
    assert out["toast"] == "✓ Sauna" and out["approvals"] == []
    assert deps.records.get(rec["id"])["stops"]["s1"]["name"] == "Sauna"
    typed = rt.tap(rec["id"], "s1", "t")
    assert typed["open_question"].endswith("[trip %s · stop s1]" % rec["id"])


def test_tap_ok_on_a_line_returns_its_approval(tmp_path):
    deps, _ = make_deps(tmp_path)
    rt = LocationRuntime(tmp_path / "loc", deps, synchronous=True)
    for p in points(Track(t(13, 7, 40)).stay(10).walk_to(250).walk_to(0).stay(5)):
        rt.feed(p)
    [rec] = deps.records.all()
    rt.render_arrival(rec["id"])
    out = rt.tap(rec["id"], "1", "ok")
    ref = deps.records.get(rec["id"])["blocks"]["trip"]
    assert out["approvals"] == [(ref["date"], ref["event_id"], "approved")]
    assert rt.tap(rec["id"], "all", "no")["approvals"] == [(ref["date"], ref["event_id"], "dismissed")]


def test_not_right_on_your_block_restores_it(tmp_path):                   # I-2
    deps, _ = make_deps(tmp_path)
    deps.events.create_event(date="2026-11-13", name="Dog walk", start_time="2026-11-13T07:50:00")
    rt = LocationRuntime(tmp_path / "loc", deps, synchronous=True)
    for p in points(Track(t(13, 7, 40)).stay(10).walk_to(250).walk_to(0).stay(5)):
        rt.feed(p)
    [rec] = deps.records.all()
    assert deps.events.get_events("2026-11-13")[0]["end_time"]          # location filled the end
    rt.render_arrival(rec["id"])
    rt.tap(rec["id"], "all", "no")
    [e] = deps.events.get_events("2026-11-13")
    assert e["end_time"] is None and e.get("end_precision") is None
    assert deps.records.get(rec["id"])["merged"]["trip"]["rejected"] is True


def test_ok_on_your_block_asks_the_route_to_sync_it(tmp_path):            # I-1
    deps, _ = make_deps(tmp_path)
    e = deps.events.create_event(date="2026-11-13", name="Dog walk", start_time="2026-11-13T07:50:00")
    rt = LocationRuntime(tmp_path / "loc", deps, synchronous=True)
    for p in points(Track(t(13, 7, 40)).stay(10).walk_to(250).walk_to(0).stay(5)):
        rt.feed(p)
    [rec] = deps.records.all()
    rt.render_arrival(rec["id"])
    out = rt.tap(rec["id"], "1", "ok")
    assert out["syncs"] == [("2026-11-13", e["id"])]
    assert deps.events.get_events("2026-11-13")[0]["end_precision"] == "exact"


def test_ok_on_a_split_block_approves_every_fragment(tmp_path):          # I-6c
    deps, _ = make_deps(tmp_path)
    rt = LocationRuntime(tmp_path / "loc", deps, synchronous=True)
    for p in points(Track(t(9, 23, 45)).stay(10).walk_to(500).stay(1).walk_to(0).stay(5)):
        rt.feed(p)
    [rec] = deps.records.all()
    assert len(rec["blocks"]["trip"]["fragments"]) == 2
    rt.render_arrival(rec["id"])
    out = rt.tap(rec["id"], "1", "ok")
    assert sorted(a[0] for a in out["approvals"]) == ["2026-11-09", "2026-11-10"]
