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


def _launchable_coding_tasks():
    from pathlib import Path

    coding_tasks = MagicMock()
    coding_tasks.worktrees_path = Path("/tmp/agent-sessions")
    coding_tasks.find_recent_trace_id.return_value = None
    coding_tasks.assemble_brief.return_value = "brief"
    coding_tasks.launch.side_effect = lambda task: {
        **task, "status": "running", "worktree_path": "/tmp/x",
    }
    return coding_tasks


def test_session_choices_cover_every_lane():
    from src.services.tool_handlers.coding_handoff import SESSION_CHOICES

    values = [c["value"] for c in SESSION_CHOICES]
    assert values == [
        "autonomous",
        "handoff-checkpoints",
        "handoff-run-through",
        "handoff-wait",
    ]
    assert all(c["label"] for c in SESSION_CHOICES)


def test_propose_passes_the_chosen_mode_to_launch():
    coding_tasks = _launchable_coding_tasks()

    propose_coding_session(
        coding_tasks,
        {"task_description": "fix it", "session_mode": "autonomous"},
        chat_id=42,
    )

    assert coding_tasks.launch.call_args[0][0]["session_mode"] == "autonomous"


def test_propose_defaults_to_handoff_checkpoints():
    """Hand-off is the lane that matches how these tasks actually get used."""
    coding_tasks = _launchable_coding_tasks()

    propose_coding_session(coding_tasks, {"task_description": "fix it"}, chat_id=42)

    assert coding_tasks.launch.call_args[0][0]["session_mode"] == "handoff-checkpoints"
