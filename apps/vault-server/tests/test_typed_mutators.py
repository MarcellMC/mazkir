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
    assert "HIST:Priority changed: 2 → 4" in written_body


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
