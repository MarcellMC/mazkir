"""The block-ticks-its-habit hook runs only with the fast lane `on`, and says so in the result.

Final review C1: registered on create_event/update_event in every mode and
invisible to the agent, the hook let an agent that logged a habit block and
then ticked the habit (as it always had) tick it twice. Off and shadow now
behave as before the fast lane; in `on` the tick is in the tool's result.
"""

import datetime as dt
from unittest.mock import MagicMock

import pytest

from src.services.events_service import EventsService
from tests.test_fast_lane_habits import with_dog_walk


def _agent(vault_service, tmp_path):
    from src.services.agent_service import AgentService
    events = EventsService(tmp_path / "events")
    agent = AgentService(claude=MagicMock(), vault=vault_service, memory=MagicMock(),
                         media_path=tmp_path / "media", events=events)
    return agent, events


def _today_block(name="Dog walk"):
    # 00:00-00:05 today: begun, ended, and on today, so `completions_today` sees it.
    today = dt.date.today().isoformat()
    return {"name": name, "date": today, "start_time": f"{today}T00:00:00",
            "end_time": f"{today}T00:05:00", "_confidence": 0.95, "_reasoning": "x"}


def _run(agent, name, params):
    return agent._execute_tool(name, params, confidence=0.99, action="auto_execute")


@pytest.mark.parametrize("mode", ["off", "shadow"])
def test_outside_on_a_habit_block_ticks_nothing(mode, vault_service, tmp_path, habit_hook_mode):
    habit_hook_mode(mode)
    with_dog_walk(vault_service)
    agent, events = _agent(vault_service, tmp_path)
    before = vault_service.read_file("20-habits/dog-walk.md")["metadata"]
    created = _run(agent, "create_event", _today_block())
    assert created["ok"] and "habit" not in created["data"]
    assert vault_service.read_file("20-habits/dog-walk.md")["metadata"] == before
    assert not any(e.get("habit_completion") for e in events.get_events(dt.date.today().isoformat()))


@pytest.mark.parametrize("mode", ["off", "shadow"])
def test_outside_on_logging_a_walk_then_ticking_it_counts_once(mode, vault_service, tmp_path, habit_hook_mode):
    """The reviewer's double-tick repro: create_event, then complete_habit, in one turn."""
    habit_hook_mode(mode)
    with_dog_walk(vault_service)        # daily_target 2, so a second tick would be accepted
    agent, _ = _agent(vault_service, tmp_path)
    _run(agent, "create_event", _today_block())
    ticked = _run(agent, "complete_habit", {"habit_name": "Dog Walk", "_confidence": 0.99, "_reasoning": "x"})
    assert ticked["ok"] and ticked["data"]["completions_today"] == 1


def test_on_a_habit_block_ticks_once_and_the_result_says_so(vault_service, tmp_path, habit_hook_mode):
    habit_hook_mode("on")
    with_dog_walk(vault_service)
    agent, events = _agent(vault_service, tmp_path)
    created = _run(agent, "create_event", _today_block())
    habit = created["data"]["habit"]
    assert habit["name"] == "Dog Walk" and habit["completions_today"] == 1
    ticks = [e for e in events.get_events(dt.date.today().isoformat()) if e.get("habit_completion")]
    assert len(ticks) == 1


def test_on_an_edit_that_makes_a_block_a_habit_reports_the_tick(vault_service, tmp_path, habit_hook_mode):
    habit_hook_mode("on")
    with_dog_walk(vault_service)
    agent, _ = _agent(vault_service, tmp_path)
    created = _run(agent, "create_event", _today_block("Errand"))
    assert "habit" not in created["data"]
    updated = _run(agent, "update_event", {"event_id": created["data"]["event_id"], "name": "Dog walk",
                                           "_confidence": 0.95, "_reasoning": "x"})
    assert updated["ok"] and updated["data"]["habit"]["name"] == "Dog Walk"


def test_the_event_tools_tell_the_agent_not_to_tick_again(vault_service, tmp_path):
    agent, _ = _agent(vault_service, tmp_path)
    for name in ("create_event", "update_event"):
        description = agent.tools[name]["schema"]["description"]
        assert "complete_habit" in description and "`habit`" in description
