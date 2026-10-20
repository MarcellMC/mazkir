# tests/test_fast_lane_undo.py
"""Spec §7.6: undo reverses a turn from its snapshots; what you changed since is left alone."""

import datetime as dt
from unittest.mock import AsyncMock, MagicMock

from src.services.events_service import EventsService
from src.services.fast_lane.act import run_lines
from src.services.fast_lane.actions import PlannedLine, Step
from src.services.fast_lane.undo import undo_turn

CREATED = "2026-01-10T12:00:00+02:00"
NOW = dt.datetime(2026, 1, 10, 12, 30)


def make_agent(tmp_path, vault):
    from src.services.agent_service import AgentService
    events = EventsService(tmp_path / "events")
    agent = AgentService(claude=MagicMock(), vault=vault, memory=MagicMock(),
                         media_path=tmp_path / "media", events=events)
    return agent, events


def create(name, start, end):
    return Step("create_event", {"name": name, "date": start[:10], "start_time": start, "end_time": end,
                                 "_fast": {"defer_calendar_sync": True, "fields": {"intent": "record"}}})


def turn_of(records):
    return {"turn_id": "t0000beef", "chat_id": 1, "message_id": 7, "created_at": CREATED, "text": "x",
            "lines": records}


def run(agent, events, *lines):
    return turn_of(run_lines(list(lines), run_tool=agent.run_tool, events=events))


def test_undo_removes_a_created_block_and_its_google_entry(tmp_path, vault_service):
    agent, events = make_agent(tmp_path, vault_service)
    turn = run(agent, events, PlannedLine("block", "fact", "Gym", steps=(create("Gym", "2026-01-10T08:00:00", "2026-01-10T09:00:00"),)))
    event_id = turn["lines"][0]["event_id"]
    events.update_event("2026-01-10", event_id, {"source_ids": {"calendar_id": "g1"}})   # the deferred sync ran
    calendar = MagicMock(is_initialized=True)
    calendar.delete_event = AsyncMock(return_value=True)
    turn, toast = undo_turn(turn, events=events, vault=vault_service, calendar=calendar, now=NOW)
    assert turn["lines"][0]["status"] == "undone" and toast == "Undone 1"
    assert events.get_events("2026-01-10") == []
    calendar.delete_event.assert_awaited_once_with("g1")


def test_undo_restores_an_edited_block(tmp_path, vault_service):
    agent, events = make_agent(tmp_path, vault_service)
    walk = events.create_event("2026-01-10", "Dog walk", "2026-01-10T07:00:00", None)
    step = Step("update_event", {"event_id": walk["id"], "date": "2026-01-10", "end_time": "2026-01-10T07:30:00",
                                 "_fast": {"defer_calendar_sync": True, "fields": {"end_precision": "exact"}}})
    turn = run(agent, events, PlannedLine("edit", "fact", "Dog walk", steps=(step,)))
    turn, _ = undo_turn(turn, events=events, vault=vault_service, calendar=None, now=NOW)
    [stored] = events.get_events("2026-01-10")
    assert turn["lines"][0]["status"] == "undone"
    assert stored["end_time"] is None and stored.get("end_precision") is None
    assert "end_time" not in (stored.get("user_set") or {})
    assert "date" not in stored     # act's snapshot key never lands on the stored row


def test_undo_refuses_a_block_changed_since(tmp_path, vault_service):
    agent, events = make_agent(tmp_path, vault_service)
    turn = run(agent, events,
               PlannedLine("block", "fact", "Gym", steps=(create("Gym", "2026-01-10T08:00:00", "2026-01-10T09:00:00"),)),
               PlannedLine("todo", "fact", "Buy milk", steps=(Step("daily_add_task", {"text": "Buy milk", "date": "2026-01-10"}),)))
    gym_id = turn["lines"][0]["event_id"]
    events.update_event("2026-01-10", gym_id, {"end_time": "2026-01-10T09:30:00"})   # you fixed it in /day
    turn, toast = undo_turn(turn, events=events, vault=vault_service, calendar=None, now=NOW)
    assert turn["lines"][0]["status"] == "done"
    assert turn["lines"][0]["undo_note"] == "can't undo: changed since"
    assert turn["lines"][1]["status"] == "undone" and toast == "Undone 1, 1 kept"
    assert [e["id"] for e in events.get_events("2026-01-10")] == [gym_id]
    assert "Buy milk" not in vault_service.read_daily_note("2026-01-10")["content"]


def test_undo_unticks_a_checked_todo(tmp_path, vault_service):
    agent, events = make_agent(tmp_path, vault_service)
    vault_service.write_daily_note("2026-01-10", "## Tasks\n- [ ] Call the plumber\n")
    turn = run(agent, events, PlannedLine("todo", "fact", "call the plumber",
                                          steps=(Step("daily_check_todo", {"text": "call the plumber", "date": "2026-01-10"}),)))
    undo_turn(turn, events=events, vault=vault_service, calendar=None, now=NOW)
    assert "- [ ] Call the plumber" in vault_service.read_daily_note("2026-01-10")["content"]


def test_undo_takes_back_a_habit_tick(tmp_path, vault_service):
    agent, events = make_agent(tmp_path, vault_service)
    turn = run(agent, events, PlannedLine("habit", "fact", "Workout",
                                          steps=(Step("complete_habit", {"habit_name": "Workout"}),)))
    assert vault_service.read_file("20-habits/workout.md")["metadata"]["streak"] == 6
    turn, _ = undo_turn(turn, events=events, vault=vault_service, calendar=None, now=NOW)
    assert turn["lines"][0]["status"] == "undone"
    assert vault_service.read_file("20-habits/workout.md")["metadata"]["streak"] == 5


def test_a_rollover_says_why_it_stays(tmp_path, vault_service):
    agent, events = make_agent(tmp_path, vault_service)
    turn = run(agent, events, PlannedLine("rollover", "fact", "Rolled over", steps=(Step("daily_rollover", {}),)))
    turn, _ = undo_turn(turn, events=events, vault=vault_service, calendar=None, now=NOW)
    assert turn["lines"][0]["undo_note"] == "can't undo: a rollover can't be undone from here"


def test_undo_is_refused_after_a_day(tmp_path, vault_service):
    agent, events = make_agent(tmp_path, vault_service)
    turn = run(agent, events, PlannedLine("block", "fact", "Gym", steps=(create("Gym", "2026-01-10T08:00:00", "2026-01-10T09:00:00"),)))
    turn, toast = undo_turn(turn, events=events, vault=vault_service, calendar=None, now=NOW + dt.timedelta(days=1))
    assert toast == "Too late to undo — it has been a day" and turn["lines"][0]["status"] == "done"


# --- forward notes from the Task 11 reviews -----------------------------------


def test_a_tick_the_hook_made_on_a_created_block_goes_with_the_block(tmp_path, vault_service):
    """The post-hook ticks Workout while writing the block; there is no separate
    habit record, only `habit_completion` on the block. Undo takes both back (§9.3)."""
    agent, events = make_agent(tmp_path, vault_service)
    turn = run(agent, events, PlannedLine("block", "fact", "Workout",
                                          steps=(create("Workout", "2026-01-10T08:00:00", "2026-01-10T09:00:00"),)))
    assert [u["kind"] for u in turn["lines"][0]["undo"]] == ["created"]
    meta = vault_service.read_file("20-habits/workout.md")["metadata"]
    assert meta["streak"] == 6
    turn, toast = undo_turn(turn, events=events, vault=vault_service, calendar=None, now=NOW)
    assert toast == "Undone 1"
    assert events.get_events("2026-01-10") == []
    meta = vault_service.read_file("20-habits/workout.md")["metadata"]
    assert meta["streak"] == 5 and str(meta["last_completed"]) == "2026-02-27"


def test_a_partial_line_still_takes_back_the_step_that_ran(tmp_path, vault_service):
    agent, events = make_agent(tmp_path, vault_service)
    turn = run(agent, events, PlannedLine("block", "fact", "Gym", steps=(
        create("Gym", "2026-01-10T18:00:00", "2026-01-10T19:00:00"),
        Step("daily_check_todo", {"text": "call the plumber", "date": "2026-01-10"}))))
    assert turn["lines"][0]["status"] == "done" and turn["lines"][0]["reason"].startswith("block written;")
    turn, toast = undo_turn(turn, events=events, vault=vault_service, calendar=None, now=NOW)
    assert turn["lines"][0]["status"] == "undone" and toast == "Undone 1"
    assert events.get_events("2026-01-10") == []


def test_lines_are_undone_newest_first(tmp_path, vault_service):
    """An edit to a block this same turn wrote: the edit is reversed first, so the
    created block is back to what the turn wrote and is not mistaken for changed."""
    agent, events = make_agent(tmp_path, vault_service)
    first = run_lines([PlannedLine("block", "fact", "Gym",
                                   steps=(create("Gym", "2026-01-10T08:00:00", "2026-01-10T09:00:00"),))],
                      run_tool=agent.run_tool, events=events)
    gym_id = first[0]["event_id"]
    edit = Step("update_event", {"event_id": gym_id, "date": "2026-01-10", "end_time": "2026-01-10T09:30:00",
                                 "_fast": {"defer_calendar_sync": True, "fields": {}}})
    second = run_lines([PlannedLine("edit", "fact", "Gym", steps=(edit,))], run_tool=agent.run_tool, events=events)
    second[0]["id"] = 1
    turn, toast = undo_turn(turn_of(first + second), events=events, vault=vault_service, calendar=None, now=NOW)
    assert [l["status"] for l in turn["lines"]] == ["undone", "undone"] and toast == "Undone 2"
    assert events.get_events("2026-01-10") == []


def test_an_edit_that_moved_a_block_to_another_day_moves_it_back(tmp_path, vault_service):
    agent, events = make_agent(tmp_path, vault_service)
    walk = events.create_event("2026-01-10", "Dog walk", "2026-01-10T07:00:00", "2026-01-10T07:30:00",
                               source_ids={"calendar_id": "g7"})
    [original] = events.get_events("2026-01-10")
    step = Step("update_event", {"event_id": walk["id"], "date": "2026-01-10",
                                 "start_time": "2026-01-11T07:00:00", "end_time": "2026-01-11T07:30:00",
                                 "_fast": {"defer_calendar_sync": True, "fields": {}}})
    turn = run(agent, events, PlannedLine("edit", "fact", "Dog walk", steps=(step,)))
    assert events.get_events("2026-01-10") == [] and len(events.get_events("2026-01-11")) == 1
    turn, toast = undo_turn(turn, events=events, vault=vault_service, calendar=None, now=NOW)
    assert toast == "Undone 1"
    assert events.get_events("2026-01-11") == []
    [stored] = events.get_events("2026-01-10")
    assert stored["start_time"] == "2026-01-10T07:00:00"
    assert stored["source_ids"] == {"calendar_id": "g7"} and not stored.get("moved_from_source_ids")
    assert stored.get("source") == original.get("source")


def test_a_created_block_with_a_google_entry_is_kept_when_google_is_unreachable(tmp_path, vault_service):
    """Deleting only Mazkir's copy would merge it straight back from Google."""
    agent, events = make_agent(tmp_path, vault_service)
    turn = run(agent, events, PlannedLine("block", "fact", "Gym", steps=(create("Gym", "2026-01-10T08:00:00", "2026-01-10T09:00:00"),)))
    event_id = turn["lines"][0]["event_id"]
    events.update_event("2026-01-10", event_id, {"source_ids": {"calendar_id": "g1"}})
    turn, toast = undo_turn(turn, events=events, vault=vault_service, calendar=None, now=NOW)
    assert turn["lines"][0]["status"] == "done" and toast == "Nothing undone, 1 kept"
    assert turn["lines"][0]["undo_note"].startswith("can't undo: ")
    assert len(events.get_events("2026-01-10")) == 1


def test_a_hook_tick_is_not_retracted_twice_when_google_refuses(tmp_path, vault_service):
    """Retract, then Google refuses: a second undo must not hit the habit again."""
    agent, events = make_agent(tmp_path, vault_service)
    turn = run(agent, events, PlannedLine("block", "fact", "Workout",
                                          steps=(create("Workout", "2026-01-10T08:00:00", "2026-01-10T09:00:00"),)))
    event_id = turn["lines"][0]["event_id"]
    events.update_event("2026-01-10", event_id, {"source_ids": {"calendar_id": "g1"}})
    calendar = MagicMock(is_initialized=True)
    calendar.delete_event = AsyncMock(return_value=False)
    turn, _ = undo_turn(turn, events=events, vault=vault_service, calendar=calendar, now=NOW)
    assert turn["lines"][0]["undo_note"] == "can't undo: Google refused to delete it"
    calendar.delete_event = AsyncMock(return_value=True)
    turn, toast = undo_turn(turn, events=events, vault=vault_service, calendar=calendar, now=NOW)
    assert toast == "Undone 1" and events.get_events("2026-01-10") == []
    assert vault_service.read_file("20-habits/workout.md")["metadata"]["streak"] == 5


# --- review round 1 -------------------------------------------------------------


def _ticked_workout_with_google_entry(tmp_path, vault_service):
    agent, events = make_agent(tmp_path, vault_service)
    turn = run(agent, events, PlannedLine("block", "fact", "Workout",
                                          steps=(create("Workout", "2026-01-10T08:00:00", "2026-01-10T09:00:00"),)))
    event_id = turn["lines"][0]["event_id"]
    events.update_event("2026-01-10", event_id, {"source_ids": {"calendar_id": "g1"}})
    assert vault_service.read_file("20-habits/workout.md")["metadata"]["streak"] == 6
    return turn, events


def _nothing_changed(turn, events, vault_service, note):
    assert turn["lines"][0]["status"] == "done" and turn["lines"][0]["undo_note"] == note
    [stored] = events.get_events("2026-01-10")
    assert stored["habit_completion"] and stored["source_ids"] == {"calendar_id": "g1"}
    assert vault_service.read_file("20-habits/workout.md")["metadata"]["streak"] == 6


def test_a_ticked_block_google_cant_reach_is_left_whole(tmp_path, vault_service):
    turn, events = _ticked_workout_with_google_entry(tmp_path, vault_service)
    turn, toast = undo_turn(turn, events=events, vault=vault_service, calendar=None, now=NOW)
    _nothing_changed(turn, events, vault_service, "can't undo: Google Calendar isn't reachable")
    assert toast == "Nothing undone, 1 kept"


def test_a_ticked_block_in_another_calendar_is_left_whole(tmp_path, vault_service):
    turn, events = _ticked_workout_with_google_entry(tmp_path, vault_service)
    events.update_event("2026-01-10", turn["lines"][0]["event_id"], {"calendar": "Work"})
    calendar = MagicMock(is_initialized=True)
    calendar.delete_event = AsyncMock(return_value=True)
    turn, _ = undo_turn(turn, events=events, vault=vault_service, calendar=calendar, now=NOW)
    _nothing_changed(turn, events, vault_service, "can't undo: it lives in another calendar")
    calendar.delete_event.assert_not_awaited()


def test_a_ticked_block_google_refuses_is_left_whole(tmp_path, vault_service):
    turn, events = _ticked_workout_with_google_entry(tmp_path, vault_service)
    calendar = MagicMock(is_initialized=True)
    calendar.delete_event = AsyncMock(return_value=False)
    turn, _ = undo_turn(turn, events=events, vault=vault_service, calendar=calendar, now=NOW)
    _nothing_changed(turn, events, vault_service, "can't undo: Google refused to delete it")


def test_a_ticked_block_google_raises_on_is_left_whole(tmp_path, vault_service):
    turn, events = _ticked_workout_with_google_entry(tmp_path, vault_service)
    calendar = MagicMock(is_initialized=True)
    calendar.delete_event = AsyncMock(side_effect=ConnectionError("503"))
    turn, _ = undo_turn(turn, events=events, vault=vault_service, calendar=calendar, now=NOW)
    _nothing_changed(turn, events, vault_service, "can't undo: Google refused to delete it: 503")


def test_a_ticked_block_with_a_google_entry_goes_whole(tmp_path, vault_service):
    turn, events = _ticked_workout_with_google_entry(tmp_path, vault_service)
    calendar = MagicMock(is_initialized=True)
    calendar.delete_event = AsyncMock(return_value=True)
    turn, toast = undo_turn(turn, events=events, vault=vault_service, calendar=calendar, now=NOW)
    assert toast == "Undone 1" and events.get_events("2026-01-10") == []
    assert vault_service.read_file("20-habits/workout.md")["metadata"]["streak"] == 5
    calendar.delete_event.assert_awaited_once_with("g1")


def test_googles_offset_echo_of_an_untouched_block_is_not_a_change(tmp_path, vault_service, monkeypatch):
    from src.config import settings
    monkeypatch.setattr(settings, "vault_timezone", "Asia/Jerusalem")   # +02:00 in January
    agent, events = make_agent(tmp_path, vault_service)
    turn = run(agent, events, PlannedLine("block", "fact", "Gym", steps=(create("Gym", "2026-01-10T08:00:00", "2026-01-10T09:00:00"),)))
    events.update_event("2026-01-10", turn["lines"][0]["event_id"],
                        {"start_time": "2026-01-10T08:00:00+02:00", "end_time": "2026-01-10T07:00:00Z"})
    turn, toast = undo_turn(turn, events=events, vault=vault_service, calendar=None, now=NOW)
    assert toast == "Undone 1" and events.get_events("2026-01-10") == []


def test_an_offset_time_that_really_moved_is_still_a_change(tmp_path, vault_service, monkeypatch):
    from src.config import settings
    monkeypatch.setattr(settings, "vault_timezone", "Asia/Jerusalem")
    agent, events = make_agent(tmp_path, vault_service)
    turn = run(agent, events, PlannedLine("block", "fact", "Gym", steps=(create("Gym", "2026-01-10T08:00:00", "2026-01-10T09:00:00"),)))
    events.update_event("2026-01-10", turn["lines"][0]["event_id"],
                        {"start_time": "2026-01-10T08:00:00+03:00"})   # 07:00 here
    turn, _ = undo_turn(turn, events=events, vault=vault_service, calendar=None, now=NOW)
    assert turn["lines"][0]["undo_note"] == "can't undo: changed since"
    assert len(events.get_events("2026-01-10")) == 1


def test_an_added_todo_already_gone_is_not_called_undone(tmp_path, vault_service):
    agent, events = make_agent(tmp_path, vault_service)
    turn = run(agent, events, PlannedLine("todo", "fact", "Buy milk",
                                          steps=(Step("daily_add_task", {"text": "Buy milk", "date": "2026-01-10"}),)))
    vault_service.write_daily_note("2026-01-10", "## Tasks\n")   # you deleted it yourself
    turn, toast = undo_turn(turn, events=events, vault=vault_service, calendar=None, now=NOW)
    assert turn["lines"][0]["status"] == "done"
    assert turn["lines"][0]["undo_note"] == "can't undo: the todo isn't there any more"
    assert toast == "Nothing undone, 1 kept"


def test_an_undone_edit_reports_its_google_push_on_the_line(tmp_path, vault_service):
    agent, events = make_agent(tmp_path, vault_service)
    walk = events.create_event("2026-01-10", "Dog walk", "2026-01-10T07:00:00", "2026-01-10T07:30:00",
                               source_ids={"calendar_id": "g7"})
    step = Step("update_event", {"event_id": walk["id"], "date": "2026-01-10", "end_time": "2026-01-10T07:45:00",
                                 "_fast": {"defer_calendar_sync": True, "fields": {}}})
    turn = run(agent, events, PlannedLine("edit", "fact", "Dog walk", steps=(step,)))
    calendar = MagicMock(is_initialized=True)
    calendar.update_event = AsyncMock(return_value=False)
    turn, toast = undo_turn(turn, events=events, vault=vault_service, calendar=calendar, now=NOW)
    assert toast == "Undone 1"
    assert turn["lines"][0]["calendar_sync"] == {"ok": False, "attempted": True, "event_id": "g7",
                                                 "reason": "update_failed"}
    assert calendar.update_event.await_args.kwargs["end_time"] == "2026-01-10T07:30:00"


# --- review round 2: a retry sees only what is left ---------------------------


def test_a_retry_does_not_redo_a_todo_it_already_removed(tmp_path, vault_service):
    agent, events = make_agent(tmp_path, vault_service)
    turn = run(agent, events, PlannedLine("block", "fact", "Gym", steps=(
        create("Gym", "2026-01-10T08:00:00", "2026-01-10T09:00:00"),
        Step("daily_add_task", {"text": "Buy milk", "date": "2026-01-10"}))))
    events.update_event("2026-01-10", turn["lines"][0]["event_id"], {"source_ids": {"calendar_id": "g1"}})
    turn, _ = undo_turn(turn, events=events, vault=vault_service, calendar=None, now=NOW)   # todo goes, Google refuses
    assert turn["lines"][0]["undo_note"] == "can't undo: Google Calendar isn't reachable"
    assert "Buy milk" not in vault_service.read_daily_note("2026-01-10")["content"]
    assert [u["kind"] for u in turn["lines"][0]["undo"]] == ["created"]
    calendar = MagicMock(is_initialized=True)
    calendar.delete_event = AsyncMock(return_value=True)
    turn, toast = undo_turn(turn, events=events, vault=vault_service, calendar=calendar, now=NOW)
    assert turn["lines"][0]["status"] == "undone" and toast == "Undone 1"
    assert "undo_note" not in turn["lines"][0] and events.get_events("2026-01-10") == []


def _edit_that_ticks_workout(tmp_path, vault_service):
    agent, events = make_agent(tmp_path, vault_service)
    block = events.create_event("2026-01-10", "Workout", "2026-01-10T08:00:00", None)
    step = Step("update_event", {"event_id": block["id"], "date": "2026-01-10", "end_time": "2026-01-10T09:00:00",
                                 "_fast": {"defer_calendar_sync": True, "fields": {}}})
    turn = run(agent, events, PlannedLine("edit", "fact", "Workout", steps=(step,)))
    assert vault_service.read_file("20-habits/workout.md")["metadata"]["streak"] == 6
    return turn, events, block["id"]


def test_a_retry_after_a_failed_retract_goes_straight_to_the_tick(tmp_path, vault_service, monkeypatch):
    import src.services.fast_lane.undo as undo_module
    turn, events, block_id = _edit_that_ticks_workout(tmp_path, vault_service)
    real = undo_module.retract_completion
    monkeypatch.setattr(undo_module, "retract_completion", lambda *a: {"ok": False, "reason": "locked"})
    turn, _ = undo_turn(turn, events=events, vault=vault_service, calendar=None, now=NOW)
    assert turn["lines"][0]["undo_note"] == "can't undo: block restored; habit: locked"
    assert events.get_events("2026-01-10")[0]["end_time"] is None
    monkeypatch.setattr(undo_module, "retract_completion", real)
    turn, toast = undo_turn(turn, events=events, vault=vault_service, calendar=None, now=NOW)
    assert turn["lines"][0]["status"] == "undone" and toast == "Undone 1"
    assert vault_service.read_file("20-habits/workout.md")["metadata"]["streak"] == 5


def test_a_failed_restore_leaves_the_tick(tmp_path, vault_service, monkeypatch):
    turn, events, block_id = _edit_that_ticks_workout(tmp_path, vault_service)
    monkeypatch.setattr(events, "update_event", lambda *a, **k: {"error": "disk full"})
    turn, _ = undo_turn(turn, events=events, vault=vault_service, calendar=None, now=NOW)
    assert turn["lines"][0]["undo_note"] == "can't undo: disk full"
    assert vault_service.read_file("20-habits/workout.md")["metadata"]["streak"] == 6
    assert not turn["lines"][0]["undo"][0].get("restored")


def test_a_second_tap_after_a_full_undo_does_nothing(tmp_path, vault_service):
    agent, events = make_agent(tmp_path, vault_service)
    turn = run(agent, events, PlannedLine("habit", "fact", "Workout",
                                          steps=(Step("complete_habit", {"habit_name": "Workout"}),)))
    turn, toast = undo_turn(turn, events=events, vault=vault_service, calendar=None, now=NOW)
    assert toast == "Undone 1"
    turn, toast = undo_turn(turn, events=events, vault=vault_service, calendar=None, now=NOW)
    assert toast == "Nothing to undo" and turn["lines"][0]["status"] == "undone"
    assert vault_service.read_file("20-habits/workout.md")["metadata"]["streak"] == 5


def _sync_lands_before_the_delete(events, google_id="g9"):
    """sync_block's calendar_id write landing between undo's read of the row and its delete_event."""
    real_delete = events.delete_event

    def delete_after_sync(date, event_id):
        events.update_event(date, event_id, {"source_ids": {"calendar_id": google_id}})
        return real_delete(date, event_id)

    events.delete_event = delete_after_sync


def test_a_google_entry_the_sync_wrote_mid_undo_goes_with_the_block(tmp_path, vault_service):
    agent, events = make_agent(tmp_path, vault_service)
    turn = run(agent, events, PlannedLine("block", "fact", "Gym", steps=(create("Gym", "2026-01-10T08:00:00", "2026-01-10T09:00:00"),)))
    _sync_lands_before_the_delete(events)
    calendar = MagicMock(is_initialized=True)
    calendar.delete_event = AsyncMock(return_value=True)
    turn, toast = undo_turn(turn, events=events, vault=vault_service, calendar=calendar, now=NOW)
    assert turn["lines"][0]["status"] == "undone" and toast == "Undone 1"
    calendar.delete_event.assert_awaited_once_with("g9")
    assert events.get_events("2026-01-10") == []


def test_a_mid_undo_google_entry_google_refuses_is_said_and_retried(tmp_path, vault_service):
    agent, events = make_agent(tmp_path, vault_service)
    turn = run(agent, events, PlannedLine("block", "fact", "Gym", steps=(create("Gym", "2026-01-10T08:00:00", "2026-01-10T09:00:00"),)))
    _sync_lands_before_the_delete(events)
    calendar = MagicMock(is_initialized=True)
    calendar.delete_event = AsyncMock(return_value=False)
    turn, toast = undo_turn(turn, events=events, vault=vault_service, calendar=calendar, now=NOW)
    line = turn["lines"][0]
    assert line["status"] == "done" and toast == "Nothing undone, 1 kept"
    assert "Google" in line["undo_note"] and events.get_events("2026-01-10") == []
    # the retry goes straight for the Google entry it left behind
    calendar.delete_event = AsyncMock(return_value=True)
    turn, toast = undo_turn(turn, events=events, vault=vault_service, calendar=calendar, now=NOW)
    assert turn["lines"][0]["status"] == "undone" and toast == "Undone 1"
    calendar.delete_event.assert_awaited_once_with("g9")


def test_no_calendar_at_all_still_leaves_no_silent_orphan(tmp_path, vault_service):
    agent, events = make_agent(tmp_path, vault_service)
    turn = run(agent, events, PlannedLine("block", "fact", "Gym", steps=(create("Gym", "2026-01-10T08:00:00", "2026-01-10T09:00:00"),)))
    _sync_lands_before_the_delete(events)
    turn, toast = undo_turn(turn, events=events, vault=vault_service, calendar=None, now=NOW)
    assert turn["lines"][0]["status"] == "done" and "Google" in turn["lines"][0]["undo_note"]
