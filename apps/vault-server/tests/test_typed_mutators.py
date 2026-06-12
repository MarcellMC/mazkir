"""Tests for the typed mutators update_task / update_habit / update_goal."""

import pytest
from unittest.mock import MagicMock

from src.services.agent_service import AgentService


@pytest.fixture
def agent(mock_services):
    return AgentService(**mock_services)


def test_update_task_appends_note_to_body(agent):
    agent.vault.list_active_tasks.return_value = [
        {"path": "40-tasks/active/migdal.md", "metadata": {"name": "Migdal docs"}}
    ]
    agent.vault.read_file.return_value = {
        "metadata": {"name": "Migdal docs", "priority": 2},
        "content": "Existing body text.\n",
    }
    agent.vault.append_history_line = lambda body, line: body + f"HIST:{line}\n"

    result = agent._tool_update_task({
        "name": "Migdal docs",
        "append_note": "Got the missing-docs message from Migdal.",
    })

    assert result["ok"] is True
    args, _ = agent.vault.write_file.call_args
    written_body = args[2]
    assert "Got the missing-docs message from Migdal." in written_body


def test_update_task_changes_priority_and_logs_history(agent):
    agent.vault.list_active_tasks.return_value = [
        {"path": "40-tasks/active/x.md", "metadata": {"name": "X", "priority": 2}}
    ]
    agent.vault.read_file.return_value = {
        "metadata": {"name": "X", "priority": 2},
        "content": "body\n",
    }
    agent.vault.append_history_line = lambda body, line: body + f"HIST:{line}\n"

    result = agent._tool_update_task({
        "name": "X",
        "priority": 4,
    })

    assert result["ok"] is True
    args, _ = agent.vault.write_file.call_args
    written_meta = args[1]
    written_body = args[2]
    assert written_meta["priority"] == 4
    assert "HIST:Priority changed: 2 (low) → 4 (high)" in written_body


def test_update_task_priority_labels_min_and_max(agent):
    """Priority changes are self-labeling (5=highest … 1=lowest) so the
    agent's reply and the UI can't disagree about which end is 'high'."""
    agent.vault.list_active_tasks.return_value = [
        {"path": "40-tasks/active/x.md", "metadata": {"name": "X", "priority": 3}}
    ]
    agent.vault.read_file.return_value = {
        "metadata": {"name": "X", "priority": 3},
        "content": "body\n",
    }
    agent.vault.append_history_line = lambda body, line: body + f"HIST:{line}\n"

    result = agent._tool_update_task({"name": "X", "priority": 5})
    assert result["data"]["changes"] == ["Priority changed: 3 (medium) → 5 (highest)"]

    result = agent._tool_update_task({"name": "X", "priority": 1})
    assert result["data"]["changes"] == ["Priority changed: 3 (medium) → 1 (lowest)"]


def test_update_task_returns_ambiguous_match_error(agent):
    agent.vault.list_active_tasks.return_value = [
        {"path": "40-tasks/active/migdal-insurance.md", "metadata": {"name": "Migdal insurance"}},
        {"path": "40-tasks/active/migdal-bank.md", "metadata": {"name": "Migdal bank"}},
    ]

    result = agent._tool_update_task({"name": "migdal", "priority": 4})

    assert result["ok"] is False
    assert result["error"]["code"] == "AMBIGUOUS_MATCH"


def test_update_task_returns_path_not_found_error(agent):
    agent.vault.list_active_tasks.return_value = []
    result = agent._tool_update_task({"name": "nonexistent", "priority": 4})
    assert result["ok"] is False
    assert result["error"]["code"] == "PATH_NOT_FOUND"


def test_update_habit_changes_scheduled_at(agent):
    agent.vault.list_active_habits.return_value = [
        {"path": "20-habits/workout.md", "metadata": {"name": "Workout"}}
    ]
    agent.vault.read_file.return_value = {
        "metadata": {"name": "Workout", "scheduled_at": "07:00"},
        "content": "body\n",
    }
    agent.vault.append_history_line = lambda body, line: body + f"HIST:{line}\n"

    result = agent._tool_update_habit({
        "name": "Workout",
        "scheduled_at": "08:30",
    })

    assert result["ok"] is True
    args, _ = agent.vault.write_file.call_args
    assert args[1]["scheduled_at"] == "08:30"


def test_update_habit_returns_path_not_found(agent):
    agent.vault.list_active_habits.return_value = []
    result = agent._tool_update_habit({"name": "ghost", "scheduled_at": "09:00"})
    assert result["ok"] is False
    assert result["error"]["code"] == "PATH_NOT_FOUND"


def test_update_goal_changes_progress(agent):
    agent.vault.list_active_goals.return_value = [
        {"path": "30-goals/2026/learn-ai.md", "metadata": {"name": "Learn AI"}}
    ]
    agent.vault.read_file.return_value = {
        "metadata": {"name": "Learn AI", "progress": 20},
        "content": "body\n",
    }
    agent.vault.append_history_line = lambda body, line: body + f"HIST:{line}\n"

    result = agent._tool_update_goal({"name": "Learn AI", "progress": 40})
    assert result["ok"] is True
    args, _ = agent.vault.write_file.call_args
    assert args[1]["progress"] == 40
