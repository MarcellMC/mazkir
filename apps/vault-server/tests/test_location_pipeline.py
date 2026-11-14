"""Plan Task 12: each tracker event, end to end through the real parts."""

from __future__ import annotations

import json
import re

from src.services.fast_lane.places import load_places, nearest
from src.services.location.pipeline import apply_answer, handle_event
from src.services.location.tracker import Tracker
from tests.location_fixtures import HOME, Track, at, feed_all, t
from tests.location_pipeline_fixtures import FakeModel, guess, make_deps, seed_dog_walk_labels


def events_for(track, places=()):
    tr = Tracker(HOME, list(places), new_id=lambda: "1a2b3c4d")
    return feed_all(tr, track.fixes)


def run(deps, clock, events):
    for ev in events:
        clock["now"] = ev.ts
        handle_event(ev, deps)
    return deps.records.get("1a2b3c4d")


def loop_without_stops():
    return Track(t(13, 7, 40)).stay(10).walk_to(250).walk_to(0).stay(5)


def loop_with_a_stop():
    return Track(t(13, 10, 0)).stay(10).walk_to(700).stay(6).walk_to(0).stay(5)


def test_routine_loop_is_named_silently_and_gets_an_arrival_message(tmp_path):
    model = FakeModel({"trip": [guess("x", history_id="h1")]})
    deps, clock = make_deps(tmp_path, model)
    seed_dog_walk_labels(deps.labels_dir)
    rec = run(deps, clock, events_for(loop_without_stops()))
    assert rec["purpose"]["name"] == "Dog walk" and rec["closed"] is True
    assert [i["kind"] for i in deps.outbox.serve()] == ["arrival"]
    [e] = deps.events.get_events("2026-11-13")
    assert e["name"] == "Dog walk" and e["proposed"] is True


def test_unknown_stop_asks_once(tmp_path):
    deps, clock = make_deps(tmp_path)
    evs = events_for(loop_with_a_stop())
    stopped = [e for e in evs if e.kind == "STOPPED"]
    run(deps, clock, evs[:2])
    run(deps, clock, stopped)                     # a redelivered event
    kinds = [i["kind"] for i in deps.outbox.serve()]
    assert kinds == ["question"]
    rec = deps.records.get("1a2b3c4d")
    assert rec["stops"]["s1"]["status"] == "asked" and rec["stops"]["s1"]["asked_at"]


def test_a_stop_gets_no_history_purpose_without_a_destination(tmp_path):
    model = FakeModel({"stop": [guess("x", history_id="h1")]})
    deps, clock = make_deps(tmp_path, model)
    seed_dog_walk_labels(deps.labels_dir)
    rec = run(deps, clock, events_for(loop_with_a_stop())[:2])
    assert rec["stops"]["s1"]["status"] == "asked"


def test_stop_already_left_is_not_asked(tmp_path):
    deps, clock = make_deps(tmp_path)
    for i in range(6):                            # the daily cap is reached
        deps.records.save({"id": f"{i:08x}", "trip": {"left_at": t(13, 6, 0).isoformat()}, "closed": True,
                           "stops": {"s1": {"status": "asked", "asked_at": t(13, 6, i).isoformat()}}})
    rec = run(deps, clock, events_for(loop_with_a_stop()))
    assert rec["stops"]["s1"]["status"] == "unnamed"
    assert [i["kind"] for i in deps.outbox.serve()] == ["arrival"]


def test_model_failure_means_ask(tmp_path):
    deps, clock = make_deps(tmp_path, FakeModel(error=TimeoutError("slow")))
    rec = run(deps, clock, events_for(loop_with_a_stop())[:2])
    assert rec["stops"]["s1"]["status"] == "asked"


def test_pause_answer_makes_a_pause_spot_and_no_block(tmp_path):
    deps, clock = make_deps(tmp_path)
    run(deps, clock, events_for(loop_with_a_stop()))
    apply_answer("1a2b3c4d", "s1", None, None, deps, pause=True)
    rec = deps.records.get("1a2b3c4d")
    assert rec["stops"]["s1"]["status"] == "unnamed"
    centre = rec["trip"]["stops"][0]
    assert nearest(centre["lat"], centre["lng"], load_places(deps.places_path)).kind == "pause"
    assert all(p != "stop:s1" for p in rec["blocks"])


def test_a_stop_answer_names_it_and_learns_the_place(tmp_path):
    deps, clock = make_deps(tmp_path)
    run(deps, clock, events_for(loop_with_a_stop()))
    apply_answer("1a2b3c4d", "s1", "Sauna", "Sauna on Ben Yehuda", deps)
    rec = deps.records.get("1a2b3c4d")
    # Naming a stop does not confirm why the trip happened (final review I-10).
    assert rec["stops"]["s1"]["status"] == "named" and rec["confirmed"] is False
    assert "stop:s1" in rec["blocks"]
    assert any(p.name == "Sauna on Ben Yehuda" and p.lat for p in load_places(deps.places_path))


def test_a_trip_answer_sets_the_purpose(tmp_path):
    deps, clock = make_deps(tmp_path)
    run(deps, clock, events_for(loop_without_stops()))
    rec = deps.records.get("1a2b3c4d")
    assert rec["trip_question"] and rec["purpose"] is None
    apply_answer("1a2b3c4d", None, "Run", None, deps)
    rec = deps.records.get("1a2b3c4d")
    assert rec["purpose"]["name"] == "Run" and rec["purpose"]["source"] == "answer"
    assert deps.events.get_events("2026-11-13")[0]["name"] == "Run"


def test_your_block_names_the_trip(tmp_path):
    deps, clock = make_deps(tmp_path)
    deps.events.create_event(date="2026-11-13", name="Dog walk", start_time="2026-11-13T07:50:00")
    rec = run(deps, clock, events_for(loop_without_stops()))
    assert rec["purpose"] == {"name": "Dog walk", "destination": None, "source": "user_block"}
    assert rec["trip_question"] is None


def test_decision_log_has_no_coordinates(tmp_path):
    logs: list[dict] = []
    deps, clock = make_deps(tmp_path, logs=logs)
    run(deps, clock, events_for(loop_with_a_stop()))
    assert logs and {l["event"] for l in logs} >= {"LEFT", "STOPPED", "BACK_HOME"}
    text = json.dumps(logs)
    assert not re.search(r"\b3[24]\.\d{3}", text)
    lat, lng = at(700)
    assert f"{lat:.4f}" not in text


# --- final review fixes --------------------------------------------------------

def test_an_answer_during_a_slow_guess_is_kept(tmp_path):                 # I-3
    import threading
    import time

    deps, clock = make_deps(tmp_path)
    evs = events_for(loop_with_a_stop())
    run(deps, clock, evs[:2])                      # LEFT, STOPPED (asked)
    left_stop = next(e for e in evs if e.kind == "LEFT_STOP")
    release = threading.Event()

    class Slow:
        def create_fast_parse(self, **kw):
            release.wait(2)
            return FakeModel().create_fast_parse(**kw)

    deps.claude = Slow()
    worker = threading.Thread(target=handle_event, args=(left_stop, deps))
    worker.start()
    time.sleep(0.05)                               # the worker holds the trip, mid-guess
    answer = threading.Thread(target=apply_answer, args=("1a2b3c4d", "s1", "Café", None, deps))
    answer.start()
    time.sleep(0.05)
    release.set()
    worker.join(3)
    answer.join(3)
    rec = deps.records.get("1a2b3c4d")
    assert rec["stops"]["s1"]["status"] == "named" and rec["stops"]["s1"]["name"] == "Café"
    assert [e["name"] for e in deps.events.get_events("2026-11-13")].count("Café") == 1


def test_a_question_already_queued_is_not_queued_again(tmp_path):        # I-4, Review Focus 3
    deps, clock = make_deps(tmp_path)
    evs = events_for(loop_with_a_stop())
    run(deps, clock, evs[:1])
    real_save = deps.records.save
    stopped = evs[1]
    deps.records.save = lambda rec: (_ for _ in ()).throw(RuntimeError("crash"))
    try:
        handle_event(stopped, deps)                # the question is queued, then the process dies
    except RuntimeError:
        pass
    deps.records.save = real_save
    handle_event(stopped, deps)                    # the inbox replays it
    assert [i["kind"] for i in deps.outbox.serve()] == ["question"]


def test_blocks_written_before_a_crash_are_adopted_not_duplicated(tmp_path):   # I-4
    deps, clock = make_deps(tmp_path)
    evs = events_for(loop_without_stops())
    run(deps, clock, evs[:1])
    rec = deps.records.get("1a2b3c4d")
    rec["blocks"] = {}                             # the record never learned of its block
    deps.records.save(rec)
    run(deps, clock, evs[1:])
    assert len(deps.events.get_events("2026-11-13")) == 1


def test_an_older_event_never_rewinds_the_record(tmp_path):              # I-4 (stale inbox replay)
    deps, clock = make_deps(tmp_path)
    evs = events_for(loop_with_a_stop())
    run(deps, clock, evs)
    before = deps.records.get("1a2b3c4d")
    handle_event(evs[1], deps)                     # STOPPED again, long after BACK_HOME
    after = deps.records.get("1a2b3c4d")
    assert after["trip"] == before["trip"] and after["closed"] is True


def test_a_pause_spot_learned_today_is_not_asked_about_again(tmp_path):  # I-5
    from src.services.fast_lane.places import add_pause_spot
    deps, clock = make_deps(tmp_path)
    evs = events_for(loop_with_a_stop())          # the tracker knew no places
    stop = evs[1].trip.stops[0]
    add_pause_spot(deps.places_path, stop.lat, stop.lng, 10)
    model = deps.claude
    rec = run(deps, clock, evs[:2])
    assert rec["stops"]["s1"]["status"] == "unnamed" and model.calls == []
    assert deps.outbox.serve() == []


def test_leaving_a_stop_withdraws_its_unsent_question(tmp_path):         # I-8
    deps, clock = make_deps(tmp_path)
    evs = events_for(loop_with_a_stop())
    run(deps, clock, evs[:3])                     # LEFT, STOPPED (asked), LEFT_STOP — no point carried it
    assert [i["kind"] for i in deps.outbox.serve()] == []


def test_a_stop_answer_does_not_confirm_a_guessed_purpose(tmp_path):     # I-10
    deps, clock = make_deps(tmp_path)
    run(deps, clock, events_for(loop_with_a_stop()))
    rec = deps.records.get("1a2b3c4d")
    rec["purpose"] = {"name": "Run", "destination": None, "source": "guess"}
    deps.records.save(rec)
    apply_answer("1a2b3c4d", "s1", None, None, deps, pause=True)
    assert deps.records.get("1a2b3c4d")["confirmed"] is False
    apply_answer("1a2b3c4d", None, "Dog walk", None, deps)
    assert deps.records.get("1a2b3c4d")["confirmed"] is True


def test_the_span_never_carries_an_error_message(tmp_path, monkeypatch):   # promoted minor
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from src.services.location import pipeline as pipeline_mod

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(pipeline_mod, "get_tracer", lambda: provider.get_tracer("t"))
    deps, clock = make_deps(tmp_path)
    deps.run_tool = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bad point 32.0853, 34.7818"))
    import pytest
    with pytest.raises(RuntimeError):
        handle_event(events_for(loop_with_a_stop())[0], deps)
    text = repr([(s.status.description, [e.attributes for e in s.events]) for s in exporter.get_finished_spans()])
    assert "32.08" not in text and "RuntimeError" in text
