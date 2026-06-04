"""Tests for the four daily-tier tools."""

import pytest
from unittest.mock import MagicMock

from src.services.agent_service import AgentService


def _agent_with_daily_body(daily_body: str):
    claude = MagicMock()
    vault = MagicMock()
    memory = MagicMock()
    vault.read_daily_note.return_value = {"metadata": {}, "content": daily_body}
    vault.write_daily_note = MagicMock()
    return AgentService(claude=claude, vault=vault, memory=memory)


def test_daily_add_task_appends_to_section():
    agent = _agent_with_daily_body("## Tasks\n- [ ] Existing\n\n## Notes\nstuff\n")
    result = agent._tool_daily_add_task({"text": "Buy milk"})
    assert result["ok"] is True
    args, _ = agent.vault.write_daily_note.call_args
    new_body = args[1]
    assert "- [ ] Existing" in new_body
    assert "- [ ] Buy milk" in new_body
    assert "## Notes" in new_body  # other sections preserved


def test_daily_add_task_with_time_and_duration():
    agent = _agent_with_daily_body("## Tasks\n\n")
    result = agent._tool_daily_add_task({
        "text": "Visit dentist",
        "scheduled_at": "14:00",
        "duration_minutes": 60,
    })
    assert result["ok"] is True
    new_body = agent.vault.write_daily_note.call_args.args[1]
    assert "14:00 — Visit dentist (60m)" in new_body


def test_daily_add_task_creates_section_if_missing():
    agent = _agent_with_daily_body("Some body text.\n")
    result = agent._tool_daily_add_task({"text": "First task"})
    assert result["ok"] is True
    new_body = agent.vault.write_daily_note.call_args.args[1]
    assert "## Tasks" in new_body
    assert "- [ ] First task" in new_body


def test_daily_add_task_default_date_is_today():
    agent = _agent_with_daily_body("## Tasks\n")
    result = agent._tool_daily_add_task({"text": "Today's task"})
    assert result["ok"] is True
    # vault.read_daily_note called with today's date
    import datetime as dt
    today = dt.date.today().isoformat()
    agent.vault.read_daily_note.assert_called_with(today)


def test_daily_add_task_with_explicit_date():
    agent = _agent_with_daily_body("## Tasks\n")
    result = agent._tool_daily_add_task({"text": "Future task", "date": "2026-12-25"})
    assert result["ok"] is True
    agent.vault.read_daily_note.assert_called_with("2026-12-25")


def test_daily_check_task_by_text_substring():
    agent = _agent_with_daily_body("## Tasks\n- [ ] Buy milk\n- [ ] Walk dog\n")
    result = agent._tool_daily_set_task_state({"text": "milk", "state": "checked"})
    assert result["ok"] is True
    new_body = agent.vault.write_daily_note.call_args.args[1]
    assert "- [x] Buy milk" in new_body
    assert "- [ ] Walk dog" in new_body


def test_daily_uncheck_task():
    agent = _agent_with_daily_body("## Tasks\n- [x] Buy milk\n")
    result = agent._tool_daily_set_task_state({"text": "milk", "state": "unchecked"})
    assert result["ok"] is True
    new_body = agent.vault.write_daily_note.call_args.args[1]
    assert "- [ ] Buy milk" in new_body


def test_daily_set_state_to_moved():
    agent = _agent_with_daily_body("## Tasks\n- [ ] Order phone\n")
    result = agent._tool_daily_set_task_state({"text": "Order", "state": "moved"})
    assert result["ok"] is True
    new_body = agent.vault.write_daily_note.call_args.args[1]
    assert "~~Order phone~~" in new_body


def test_daily_set_state_ambiguous_returns_error():
    agent = _agent_with_daily_body("## Tasks\n- [ ] Buy milk\n- [ ] Buy bread\n")
    result = agent._tool_daily_set_task_state({"text": "Buy", "state": "checked"})
    assert result["ok"] is False
    assert result["error"]["code"] == "AMBIGUOUS_MATCH"
    candidates = result["error"]["details"]["candidates"]
    assert "Buy milk" in candidates
    assert "Buy bread" in candidates


def test_daily_set_state_no_match_returns_path_not_found():
    agent = _agent_with_daily_body("## Tasks\n- [ ] Buy milk\n")
    result = agent._tool_daily_set_task_state({"text": "nonexistent", "state": "checked"})
    assert result["ok"] is False
    assert result["error"]["code"] == "PATH_NOT_FOUND"
