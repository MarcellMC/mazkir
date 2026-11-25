"""Stops after the first live walk (2026-11-14).

A stop is named after the place, never after the trip; a stop you stop at
often is recognised; any stop question can wait until you are home; names
follow your habits and history; an open trip is visible to the agent.
"""

from __future__ import annotations

import copy
import json

from src.services.location.messages import arrival_receipt, question_receipt
from src.services.location.pipeline import apply_answer, handle_event
from src.services.location.runtime import LocationRuntime
from src.services.location.tracker import Tracker
from tests.location_fixtures import HOME, TZ, Track, feed_all, t
from tests.location_pipeline_fixtures import FakeModel, guess, make_deps, seed_dog_walk_labels


def events_for(track, trip_id="1a2b3c4d"):
    return feed_all(Tracker(HOME, [], new_id=lambda: trip_id), track.fixes)


def run(deps, clock, events, trip_id="1a2b3c4d"):
    for ev in events:
        clock["now"] = ev.ts
        handle_event(ev, deps)
    return deps.records.get(trip_id)


def walk_with_a_stop(day=13, hour=16):
    return Track(t(day, hour, 0)).stay(10).walk_to(700).stay(6).walk_to(0).stay(5)


def _habit(name, aliases=None):
    meta = {"name": name, "frequency": "daily", "daily_target": 2}
    if aliases:
        meta["aliases"] = aliases
    return {"metadata": meta, "path": f"20-habits/{name.lower().replace(' ', '-')}.md"}


def _say(deps, text, hour=16, minute=4):
    day = deps.conversations_dir / "2026-11-13"
    day.mkdir(parents=True, exist_ok=True)
    (day / "156175834.md").write_text(f"---\ntype: conversation\n---\n\n### {hour}:{minute:02d} [user]\n{text}\n")


# 1. A stop is named after the place, never after the trip ---------------------------------

def test_the_trips_own_activity_never_names_a_stop(tmp_path):
    # 14 Nov: "Dog walking" said mid-walk named both stops "Dog walking" / "Dog walk".
    deps, clock = make_deps(tmp_path)
    _say(deps, "Dog walking")
    deps.claude.by_subject = {"stop": [guess("Dog walking", cites=["c1"], destination=None)]}
    rec = run(deps, clock, events_for(walk_with_a_stop())[:2])
    assert rec["stops"]["s1"]["status"] == "asked"
    assert [o["name"] for o in rec["stops"]["s1"]["options"]] == []
    assert [b for b in deps.events.get_events("2026-11-13") if (b.get("trip") or {}).get("part") == "stop:s1"] == []


def test_a_strong_guess_about_the_place_is_offered_not_named(tmp_path):
    deps, clock = make_deps(tmp_path)
    deps.vault.read_daily_note.return_value = {"content": "- [ ] coffee with Dana\n"}
    deps.claude.by_subject = {"stop": [guess("Coffee with Dana", cites=["c1"], destination="Café")]}
    rec = run(deps, clock, events_for(walk_with_a_stop())[:2])
    assert rec["stops"]["s1"]["status"] == "asked"
    assert rec["stops"]["s1"]["options"][0] == {"name": "Coffee with Dana", "destination": "Café", "osm": None}


def test_a_stop_left_unanswered_stays_unnamed_with_no_block(tmp_path):
    deps, clock = make_deps(tmp_path)
    deps.vault.read_daily_note.return_value = {"content": "- [ ] coffee with Dana\n"}
    deps.claude.by_subject = {"stop": [guess("Coffee with Dana", cites=["c1"], destination="Café")]}
    rec = run(deps, clock, events_for(walk_with_a_stop()))
    assert rec["stops"]["s1"]["status"] == "later"      # asked, never answered, left
    parts = [(b.get("trip") or {}).get("part") for b in deps.events.get_events("2026-11-13")]
    assert parts == ["trip"]


# 2. A stop you stop at often is recognised -------------------------------------------------

def _earlier_visits(deps, rec, n):
    for i in range(n):
        old = copy.deepcopy(rec)
        old["id"] = f"0000000{i}"
        old["trip"]["id"] = old["id"]
        old["trip"]["left_at"] = t(10 + i % 3, 8, 0).isoformat()
        deps.records.save(old)


def test_a_usual_stop_says_so_in_the_question_and_to_the_model(tmp_path):
    deps, clock = make_deps(tmp_path)
    first = run(deps, clock, events_for(walk_with_a_stop(hour=8), "ffffffff")[:2], "ffffffff")
    (deps.records.dir / "ffffffff.json").unlink()
    _earlier_visits(deps, first, 3)
    deps.outbox = type(deps.outbox)(tmp_path / "loc" / "outbox2.json")
    model = FakeModel()
    deps.claude = model
    run(deps, clock, events_for(walk_with_a_stop())[:2])
    [q] = deps.outbox.serve()
    assert "usual stop" in q["receipt"]["lines"][0]["text"]
    assert "stopped here on 3 earlier trips" in model.calls[-1]["content"]


def test_a_new_spot_is_not_called_usual(tmp_path):
    deps, clock = make_deps(tmp_path)
    run(deps, clock, events_for(walk_with_a_stop())[:2])
    [q] = deps.outbox.serve()
    assert "usual stop" not in q["receipt"]["lines"][0]["text"]


# 3. Any stop question can wait until you are home -----------------------------------------

def _labels(receipt):
    return [b["label"] for line in receipt["lines"] for b in line["buttons"]]


def test_a_stop_question_offers_later(tmp_path):
    deps, clock = make_deps(tmp_path)
    run(deps, clock, events_for(walk_with_a_stop())[:2])
    [q] = deps.outbox.serve()
    assert "Later" in _labels(q["receipt"])
    assert any(b["data"].endswith(":s1:l") for line in q["receipt"]["lines"] for b in line["buttons"])


def _runtime(deps):
    rt = LocationRuntime.__new__(LocationRuntime)
    rt.deps = deps
    return rt


def test_later_moves_the_question_into_the_arrival_message(tmp_path):
    deps, clock = make_deps(tmp_path)
    evs = events_for(walk_with_a_stop())
    run(deps, clock, evs[:2])
    out = _runtime(deps).tap("1a2b3c4d", "s1", "l")
    assert "home" in out["toast"].lower()
    assert out["receipt"]["lines"][0]["buttons"] == []
    rec = run(deps, clock, evs[2:])
    assert rec["stops"]["s1"]["status"] == "later"
    [arrival] = [i for i in deps.outbox.serve() if i["kind"] == "arrival"]
    stop_lines = [line for line in arrival["receipt"]["lines"] if line["text"].startswith("📍")]
    assert len(stop_lines) == 1
    assert any(b["data"] == "trip:1a2b3c4d:s1:t" for b in stop_lines[0]["buttons"])
    assert "Later" not in _labels(arrival["receipt"])


def test_answering_a_later_stop_from_the_arrival_message_redraws_it(tmp_path):
    deps, clock = make_deps(tmp_path)
    evs = events_for(walk_with_a_stop())
    run(deps, clock, evs[:2])
    rt = _runtime(deps)
    rt.tap("1a2b3c4d", "s1", "l")
    run(deps, clock, evs[2:])
    out = rt.tap("1a2b3c4d", "s1", "p")
    assert out["rerender"] is True and out["receipt"] is None


def test_later_is_not_offered_once_you_are_home(tmp_path):
    deps, clock = make_deps(tmp_path)
    rec = run(deps, clock, events_for(walk_with_a_stop()))
    rec["stops"]["s1"]["status"] = "later"
    receipt = arrival_receipt(rec, deps.events, TZ)
    assert "Later" not in _labels(receipt)
    q = question_receipt(rec, "s1", [], t(13, 16, 30), TZ)
    assert "Later" not in _labels(q)


# 4. Names follow your habits and history ---------------------------------------------------

def test_a_guess_takes_your_habits_name(tmp_path):
    deps, clock = make_deps(tmp_path)
    deps.vault.list_active_habits.return_value = [_habit("Dog Walk")]
    _say(deps, "Dog walking")
    deps.claude.by_subject = {"trip": [guess("Dog walking", cites=["c1"])]}
    rec = run(deps, clock, events_for(Track(t(13, 16, 0)).stay(10).walk_to(250).walk_to(0).stay(5)))
    assert rec["trip_question"]["options"][0]["name"] == "Dog Walk"


def test_your_history_name_wins_over_the_habit_name(tmp_path):
    deps, clock = make_deps(tmp_path)
    seed_dog_walk_labels(deps.labels_dir)
    deps.vault.list_active_habits.return_value = [_habit("Dog Walk")]
    _say(deps, "Dog walking")
    deps.claude.by_subject = {"trip": [guess("dog walks", cites=["c1"])]}
    rec = run(deps, clock, events_for(Track(t(13, 16, 0)).stay(10).walk_to(250).walk_to(0).stay(5)))
    assert rec["trip_question"]["options"][0]["name"] == "Dog walk"


def test_an_answer_naming_the_trip_takes_the_usual_name_but_nothing_else_changes(tmp_path):
    deps, clock = make_deps(tmp_path)
    deps.vault.list_active_habits.return_value = [_habit("Dog Walk", aliases=["walk the dog"])]
    evs = events_for(Track(t(13, 16, 0)).stay(10).walk_to(250))
    run(deps, clock, evs)
    apply_answer("1a2b3c4d", None, "walking the dog", None, deps)
    assert deps.records.get("1a2b3c4d")["purpose"]["name"] == "Dog Walk"
    apply_answer("1a2b3c4d", None, "Walk to Barzilay", None, deps)
    assert deps.records.get("1a2b3c4d")["purpose"]["name"] == "Walk to Barzilay"


# 5. An open trip is visible to the agent ---------------------------------------------------

def test_list_events_shows_the_trip_a_block_belongs_to(tmp_path):
    deps, clock = make_deps(tmp_path)
    run(deps, clock, events_for(Track(t(13, 16, 0)).stay(10).walk_to(250)))
    from src.services.agent_service import AgentService
    from unittest.mock import MagicMock
    agent = AgentService(claude=MagicMock(), vault=deps.vault, memory=MagicMock(), calendar=None,
                         events=deps.events, media_path=tmp_path / "media")
    agent._reconciled_events = lambda date: (deps.events.get_events(date), False)
    out = agent._tool_list_events({"date": "2026-11-13"})
    [trip_block] = [e for e in out["data"]["events"] if e.get("trip")]
    assert trip_block["trip"] == {"id": "1a2b3c4d", "part": "trip"}
    assert trip_block["end_time"] is None


def test_the_decision_log_still_has_no_coordinates(tmp_path):
    logs: list[dict] = []
    deps, clock = make_deps(tmp_path, logs=logs)
    rec = run(deps, clock, events_for(walk_with_a_stop()))
    lat = f"{rec['trip']['stops'][0]['lat']:.4f}"
    assert lat not in json.dumps(logs)


def test_an_answer_saying_where_you_went_names_the_stop_after_the_place(tmp_path):     # 2026-11-15
    deps, clock = make_deps(tmp_path)
    rec = run(deps, clock, events_for(walk_with_a_stop())[:2])
    assert rec["stops"]["s1"]["status"] == "asked"
    apply_answer("1a2b3c4d", "s1", "Went to Chaser bar", "Chaser bar", deps)
    assert deps.records.get("1a2b3c4d")["stops"]["s1"]["name"] == "Chaser bar"


def test_a_purpose_that_says_more_than_the_place_is_kept(tmp_path):
    from src.services.location.names import title_for

    assert title_for("Went to Chaser bar", "Chaser bar") == "Chaser bar"
    assert title_for("at chaser bar", "Chaser bar") == "Chaser bar"
    assert title_for("I'm at Chaser bar", "Chaser bar") == "Chaser bar"
    assert title_for("Drinks with Alex at Chaser bar", "Chaser bar") == "Drinks with Alex at Chaser bar"
    assert title_for("Went to Chaser bar", None) == "Went to Chaser bar"
