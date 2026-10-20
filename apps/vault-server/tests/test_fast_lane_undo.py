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
