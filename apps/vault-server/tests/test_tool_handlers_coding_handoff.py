from datetime import datetime, timezone
from unittest.mock import MagicMock

from src.services.tool_handlers.coding_handoff import (
    preview_coding_session,
    propose_coding_session,
)


def test_preview_shows_task_description_without_side_effects():
    coding_tasks = MagicMock()

    text = preview_coding_session({"task_description": "Fix the rollover bug"}, ctx={})

    assert "Fix the rollover bug" in text
    assert "isolated coding session" in text
    coding_tasks.launch.assert_not_called()


def test_propose_assembles_brief_and_launches():
    coding_tasks = MagicMock()
    coding_tasks.find_recent_trace_id.return_value = "trace-123"
    coding_tasks.worktrees_path = MagicMock()
    coding_tasks.worktrees_path.__truediv__.return_value = "/tmp/worktrees/ct_abc"
    coding_tasks.assemble_brief.return_value = "THE BRIEF"
    coding_tasks.launch.return_value = {
        "id": "ct_abc123", "branch": "coding-agent/ct_abc123",
        "worktree_path": "/tmp/worktrees/ct_abc123", "status": "running",
    }

    result = propose_coding_session(
        coding_tasks,
        {
            "task_description": "Fix the rollover bug",
            "conversation_excerpt": "rollover ran twice",
            "likely_area": "apps/vault-server/src/services/tool_handlers/daily.py",
        },
        chat_id=42,
    )

    assert result["ok"] is True
    assert result["data"]["id"] == "ct_abc123"
    assert result["data"]["status"] == "running"
    coding_tasks.save_task.assert_called_once()
    saved_task = coding_tasks.save_task.call_args[0][0]
    assert saved_task["chat_id"] == 42
    assert saved_task["task_description"] == "Fix the rollover bug"
    assert saved_task["trace_id"] == "trace-123"
    assert saved_task["prompt"] == "THE BRIEF"
    coding_tasks.launch.assert_called_once_with(saved_task)
