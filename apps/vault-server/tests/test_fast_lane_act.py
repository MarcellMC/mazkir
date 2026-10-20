"""Spec §7.5–7.6: calls run in order through the executor; failures stay on their line."""

import datetime as dt
import os
import time
from unittest.mock import MagicMock

import pytest
from zoneinfo import ZoneInfo

from src.services.events_service import EventsService
from src.services.fast_lane.act import (
    _record, apply_result, find_repeat, load_turn, new_turn_id, prune, run_lines, run_step, save_turn,
)
from src.services.fast_lane.actions import PlanInputs, PlannedLine, Step, plan_turn
from src.services.fast_lane.receipt import render_receipt
from src.services.fast_lane.contract import Clause, ParseResult, TimeWords
from src.services.fast_lane.time_resolver import ClauseTime, ResolverContext, resolve

TZ = ZoneInfo("Asia/Jerusalem")


def make_agent(tmp_path, vault):
    from src.services.agent_service import AgentService
    events = EventsService(tmp_path / "events")
    agent = AgentService(claude=MagicMock(), vault=vault, memory=MagicMock(),
                         media_path=tmp_path / "media", events=events)
    return agent, events


def create(name, start, end):
    return Step("create_event", {"name": name, "date": start[:10], "start_time": start, "end_time": end,
                                 "_fast": {"defer_calendar_sync": True, "fields": {"intent": "record"}}})


def test_steps_run_in_order_and_results_land_on_their_lines(tmp_path, vault_service):
    agent, events = make_agent(tmp_path, vault_service)
    lines = [PlannedLine("block", "fact", "Gym", steps=(create("Gym", "2026-01-10T18:00:00", "2026-01-10T19:00:00"),)),
             PlannedLine("todo", "fact", "Buy milk", steps=(Step("daily_add_task", {"text": "Buy milk", "date": "2026-01-10"}),))]
    gym, milk = run_lines(lines, run_tool=agent.run_tool, events=events)
    assert gym["status"] == "done" and gym["date"] == "2026-01-10"
    assert events.get_events("2026-01-10")[0]["id"] == gym["event_id"]
    assert gym["calendar_sync"]["reason"] == "deferred"
    assert gym["undo"][0]["kind"] == "created" and gym["undo"][0]["ids"] == [gym["event_id"]]
    assert milk["status"] == "done" and milk["day"] == "2026-01-10"
    assert milk["undo"] == [{"kind": "todo_added", "date": "2026-01-10", "text": "Buy milk"}]


def test_a_failing_step_marks_its_line_and_the_rest_still_run(tmp_path, vault_service):
    agent, events = make_agent(tmp_path, vault_service)
    lines = [PlannedLine("todo", "fact", "call the plumber",
                         steps=(Step("daily_check_todo", {"text": "call the plumber", "date": "2026-01-10"}),)),
             PlannedLine("block", "fact", "Gym", steps=(create("Gym", "2026-01-10T18:00:00", "2026-01-10T19:00:00"),))]
    failed, gym = run_lines(lines, run_tool=agent.run_tool, events=events)
    assert failed["status"] == "failed" and "call the plumber" in failed["reason"] and failed["undo"] == []
    assert gym["status"] == "done"


def test_a_block_from_last_night_is_written_to_yesterdays_file(tmp_path, vault_service):
    agent, events = make_agent(tmp_path, vault_service)
    now = dt.datetime(2026, 9, 28, 0, 48, tzinfo=TZ)
    c = Clause(op="log_block", intent="record", stated=True, evidence="Dog walk 23:15-23:35", name="Dog walk",
               time=TimeWords(start="23:15", end="23:35"))
    [r] = resolve([ClauseTime(op="log_block", name="Dog walk", start="23:15", end="23:35")],
                  ResolverContext(now=now))
    lines = plan_turn(ParseResult((c,), None), [r], PlanInputs(now=now, message_id=7))
    [rec] = run_lines(lines, run_tool=agent.run_tool, events=events)
    assert rec["date"] == "2026-09-27"
    assert [e["name"] for e in events.get_events("2026-09-27")] == ["Dog walk"]
    assert events.get_events("2026-09-28") == []


def test_an_update_keeps_before_and_after_for_undo(tmp_path, vault_service):
    agent, events = make_agent(tmp_path, vault_service)
    walk = events.create_event("2026-01-10", "Dog walk", "2026-01-10T13:00:00", None)
    step = Step("update_event", {"event_id": walk["id"], "date": "2026-01-10", "end_time": "2026-01-10T13:30:00",
                                 "_fast": {"defer_calendar_sync": True, "fields": {"end_precision": "exact"}}})
    [rec] = run_lines([PlannedLine("edit", "fact", "Dog walk", steps=(step,))], run_tool=agent.run_tool, events=events)
    [undo] = rec["undo"]
    assert undo["kind"] == "edited" and undo["before"]["end_time"] is None
    assert undo["after"]["end_time"] == "2026-01-10T13:30:00"


def test_questions_and_proposals_wait(tmp_path, vault_service):
    agent, events = make_agent(tmp_path, vault_service)
    proposal = create("Nap", "2026-01-10T14:00:00", "2026-01-10T14:30:00")
    proposal.params["proposed"] = True
    lines = [PlannedLine("question", "question", "Walk", reason="no time given"),
             PlannedLine("propose", "proposal", "End Work at 13:00?", pending=(create("x", "2026-01-10T01:00:00", "2026-01-10T02:00:00"),)),
             PlannedLine("block", "proposal", "Nap", steps=(proposal,))]
    asked, offered, nap = run_lines(lines, run_tool=agent.run_tool, events=events)
    assert asked["status"] == "question" and offered["status"] == "pending" and nap["status"] == "pending"
    assert offered["pending"][0]["tool"] == "create_event"
    assert [e["name"] for e in events.get_events("2026-01-10")] == ["Nap"]   # only the proposal was written


def test_turn_files_round_trip_find_repeats_and_prune(tmp_path):
    turn = {"turn_id": "t0123abcd", "chat_id": 1, "message_id": 7, "created_at": "2026-09-28T00:48:00+03:00",
            "text": "x", "lines": []}
    save_turn(tmp_path, turn)
    assert load_turn(tmp_path, "t0123abcd") == turn
    assert find_repeat(tmp_path, 1, 7)["turn_id"] == "t0123abcd"
    assert find_repeat(tmp_path, 1, 8) is None and find_repeat(tmp_path, 1, None) is None
    old = time.time() - 25 * 3600
    os.utime(tmp_path / "t0123abcd.json", (old, old))
    assert find_repeat(tmp_path, 1, 7) is None
    prune(tmp_path)
    assert load_turn(tmp_path, "t0123abcd") is None


def test_load_turn_refuses_anything_but_a_turn_id(tmp_path):
    assert load_turn(tmp_path, "../../etc/passwd") is None
    assert load_turn(tmp_path, "t0123abcd.json") is None


def test_load_turn_refuses_other_shapes_and_new_ids_are_valid(tmp_path):
    assert load_turn(tmp_path, "") is None and load_turn(tmp_path, None) is None
    (tmp_path / "t0123abcd\n.json").write_text("{}")
    assert load_turn(tmp_path, "t0123abcd\n") is None
    assert load_turn(tmp_path, "T0123ABCD") is None and load_turn(tmp_path, "t0123abcd/../x") is None
    with pytest.raises(ValueError):
        save_turn(tmp_path, {"turn_id": "../escape"})
    tid = new_turn_id()
    save_turn(tmp_path, {"turn_id": tid, "lines": []})
    assert load_turn(tmp_path, tid) == {"turn_id": tid, "lines": []}


def _habit_ok(name="Meditate"):
    def run_tool(tool, params):
        assert tool == "complete_habit" and params == {"habit_name": name}
        return {"ok": True, "data": {
            "habit": name, "old_streak": 2, "new_streak": 3, "longest_streak": 5, "tokens_earned": 1,
            "completions_today": 1, "daily_target": 1, "path": "20-habits/meditate.md",
            "completed_at": "2026-01-10T09:00:00", "prior": {"longest_streak": 5}}}
    return run_tool


def test_an_approved_fuzzy_habit_lands_on_its_line_and_drops_the_question_button():
    """Task 10 forward note: after ✓ on a fuzzy habit, the line shows the tick, not a "<name>?" button."""
    step = Step("complete_habit", {"habit_name": "Meditate"})
    line = PlannedLine("propose", "proposal", "Meditate", pending=(step,), reason="did you mean Meditate?",
                       habit_candidate={"path": "20-habits/meditate.md", "name": "Meditate"})
    [rec] = run_lines([line], run_tool=_habit_ok(), events=None)
    assert rec["status"] == "pending" and rec["habit"] is None
    res = run_step(Step(**rec["pending"][0]), run_tool=_habit_ok(), events=None)
    apply_result(rec, res, done_status="approved")
    assert rec["status"] == "approved" and rec["habit"]["name"] == "Meditate"
    assert rec["habit_candidate"] is None
    assert rec["undo"] == [{"kind": "habit", "path": "20-habits/meditate.md",
                            "completed_at": "2026-01-10T09:00:00", "prior": {"longest_streak": 5}}]
    turn = {"turn_id": "t0123abcd", "created_at": "2026-01-10T09:00:00", "lines": [rec]}
    [shown] = render_receipt(turn, dt.datetime(2026, 1, 10, 9, 1))["lines"]
    assert not any(b["data"].endswith(":hb") for b in shown["buttons"])
    assert shown["detail"].startswith("🎯 Meditate 1/1")


def test_a_block_line_keeps_its_habit_candidate_until_a_habit_is_ticked():
    line = PlannedLine("block", "fact", "Run", steps=(Step("daily_rollover", {}),),
                       habit_candidate={"path": "20-habits/running.md", "name": "Running"})
    [rec] = run_lines([line], run_tool=lambda t, p: {"ok": True, "data": {}}, events=None)
    assert rec["status"] == "done" and rec["habit_candidate"]["name"] == "Running"
    assert rec["undo"] == [{"kind": "none", "why": "a rollover can't be undone from here"}]


def test_a_later_step_failing_keeps_the_written_block_live_and_undoable(tmp_path, vault_service):
    """Review fix: the block was written, so the line stays done; only the cross-out failed."""
    agent, events = make_agent(tmp_path, vault_service)
    line = PlannedLine("block", "fact", "Gym", steps=(
        create("Gym", "2026-01-10T18:00:00", "2026-01-10T19:00:00"),
        Step("daily_check_todo", {"text": "call the plumber", "date": "2026-01-10"})))
    [rec] = run_lines([line], run_tool=agent.run_tool, events=events)
    assert rec["status"] == "done"
    assert rec["reason"].startswith("block written; couldn't cross out the todo: ")
    assert "call the plumber" in rec["reason"]
    assert rec["event_id"] == events.get_events("2026-01-10")[0]["id"] and rec["date"] == "2026-01-10"
    assert [u["kind"] for u in rec["undo"]] == ["created"]
    turn = {"turn_id": "t0123abcd", "created_at": "2026-01-10T19:05:00", "lines": [rec]}
    receipt = render_receipt(turn, dt.datetime(2026, 1, 10, 19, 6))
    assert any(b["data"].startswith("block:edit:2026-01-10:") for b in receipt["lines"][0]["buttons"])
    assert receipt["undo"] == "rcpt:t0123abcd:u:un"


def test_a_first_step_failing_still_fails_the_line():
    line = PlannedLine("block", "fact", "Gym", steps=(Step("create_event", {}), Step("daily_rollover", {})))
    calls = []

    def run_tool(tool, params):
        calls.append(tool)
        return {"ok": False, "error": {"code": "SCHEMA_INVALID", "message": "no start"}}
    [rec] = run_lines([line], run_tool=run_tool, events=None)
    assert rec["status"] == "failed" and rec["reason"] == "no start" and calls == ["create_event"]


def test_a_create_result_missing_its_ids_fails_the_line_instead_of_raising():
    ok_but_empty = lambda tool, params: {"ok": True, "data": {"path": "x/2026-01-10.json"}}
    res = run_step(Step("create_event", {}), run_tool=ok_but_empty, events=None)
    assert res["ok"] is False and res["undo"] == [] and "event_id" in res["reason"]
    res = run_step(Step("create_event", {}), run_tool=lambda t, p: {"ok": True, "data": {"event_id": "e1"}},
                   events=None)
    assert res["ok"] is False and "path" in res["reason"]


def test_find_repeat_skips_a_file_that_vanishes_mid_scan(tmp_path, monkeypatch):
    save_turn(tmp_path, {"turn_id": "t0123abcd", "chat_id": 1, "message_id": 7, "lines": []})
    real_stat = type(tmp_path).stat

    def flaky(self, *a, **kw):
        if self.name == "t0123abcd.json":
            raise FileNotFoundError(self)
        return real_stat(self, *a, **kw)
    monkeypatch.setattr(type(tmp_path), "stat", flaky)
    assert find_repeat(tmp_path, 1, 7) is None


def test_each_step_that_ran_is_recorded_and_a_raise_is_a_failed_step():
    calls = []

    def run_tool(tool, params):
        calls.append(tool)
        if tool == "daily_add_task":
            raise RuntimeError("boom")
        return _habit_ok()(tool, params)

    line = PlannedLine("habit", "fact", "Meditate", steps=(
        Step("complete_habit", {"habit_name": "Meditate"}), Step("daily_add_task", {"text": "x"}),
        Step("daily_rollover", {})))
    [rec] = run_lines([line], run_tool=run_tool, events=None)
    assert calls == ["complete_habit", "daily_add_task"]
    assert rec["steps"] == [
        {"tool": "complete_habit", "ok": True, "reason": "", "code": None},
        {"tool": "daily_add_task", "ok": False, "reason": "error: RuntimeError", "code": "EXCEPTION"},
    ]
    assert rec["status"] == "done" and rec["undo"][0]["kind"] == "habit"
    assert "couldn't add the todo: error: RuntimeError" in rec["reason"]


def test_update_turn_serialises_read_modify_write_so_undo_markers_survive(tmp_path):
    """Spec §7.6: a sync patch straddling an undo must not erase `undone`."""
    import threading
    import time as _time

    from src.services.fast_lane.act import load_turn, save_turn, update_turn

    turn = {"turn_id": "t0000cafe", "chat_id": 1, "message_id": 1, "created_at": "2026-01-10T20:00:00",
            "lines": [{"id": 0, "status": "done", "calendar_sync": {"reason": "deferred"}},
                      {"id": 1, "status": "done", "calendar_sync": {"reason": "deferred"}}]}
    save_turn(tmp_path, turn)
    undo_started = threading.Event()

    def undo(t):                        # load → seconds of Google calls → save, all under the lock
        undo_started.set()
        _time.sleep(0.2)
        for line in t["lines"]:
            line.update(status="undone", undo_note="undone")

    def patch(t):
        t["lines"][1]["calendar_sync"] = {"ok": True, "attempted": True}

    undoer = threading.Thread(target=update_turn, args=(tmp_path, "t0000cafe", undo))
    undoer.start()
    assert undo_started.wait(1)
    update_turn(tmp_path, "t0000cafe", patch)     # straddles the undo: must wait for it
    undoer.join()
    stored = load_turn(tmp_path, "t0000cafe")
    assert [line["status"] for line in stored["lines"]] == ["undone", "undone"]
    assert stored["lines"][1]["calendar_sync"]["ok"] is True


def test_update_turn_on_a_missing_turn_saves_the_default_or_returns_none(tmp_path):
    from src.services.fast_lane.act import load_turn, update_turn

    assert update_turn(tmp_path, "t0000dead", lambda t: None) is None
    out = update_turn(tmp_path, "t0000dead", lambda t: t.update(response="x"),
                      default={"turn_id": "t0000dead", "lines": []})
    assert out["response"] == "x" and load_turn(tmp_path, "t0000dead")["response"] == "x"
