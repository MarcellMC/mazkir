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


def _agent_with_two_daily_bodies(yesterday_body: str, today_body: str, yesterday_date="2026-06-03", today_date="2026-06-04"):
    """Helper: vault.read_daily_note returns yesterday_body or today_body
    based on the date argument; write_daily_note is a mock."""
    claude = MagicMock()
    vault = MagicMock()
    memory = MagicMock()

    def _read(date_str):
        if date_str == yesterday_date:
            return {"metadata": {}, "content": yesterday_body}
        if date_str == today_date:
            return {"metadata": {}, "content": today_body}
        return {"metadata": {}, "content": ""}

    vault.read_daily_note.side_effect = _read
    vault.write_daily_note = MagicMock()
    return AgentService(claude=claude, vault=vault, memory=memory), vault


def test_daily_rollover_copies_unchecked_items():
    agent, vault = _agent_with_two_daily_bodies(
        yesterday_body="## Tasks\n- [ ] Order phone\n- [x] Walk dog\n",
        today_body="## Tasks\n",
    )
    result = agent._tool_daily_rollover({
        "from_date": "2026-06-03",
        "to_date": "2026-06-04",
    })
    assert result["ok"] is True
    assert vault.write_daily_note.call_count == 2

    written = {call.args[0]: call.args[1] for call in vault.write_daily_note.call_args_list}
    # Yesterday: Order phone is now strikethrough/moved
    assert "~~Order phone~~" in written["2026-06-03"]
    assert "moved to [[2026-06-04#Tasks]]" in written["2026-06-03"]
    # Yesterday: Walk dog is still checked (not touched)
    assert "- [x] Walk dog" in written["2026-06-03"]
    # Today: Order phone copied with first-original annotation
    assert "- [ ] Order phone" in written["2026-06-04"]
    assert "moved from [[2026-06-03#Tasks]]" in written["2026-06-04"]


def test_daily_rollover_chain_anchor_walks_back_to_first_original():
    """Item already rolled once: today's copy should anchor to the original
    date, not the intermediate date."""
    agent, vault = _agent_with_two_daily_bodies(
        yesterday_body="## Tasks\n- [ ] Plan picnic — moved from [[2026-05-21#Tasks]]\n",
        today_body="## Tasks\n",
        yesterday_date="2026-06-03",
        today_date="2026-06-04",
    )
    result = agent._tool_daily_rollover({
        "from_date": "2026-06-03",
        "to_date": "2026-06-04",
    })
    assert result["ok"] is True
    written = {call.args[0]: call.args[1] for call in vault.write_daily_note.call_args_list}
    # Today's annotation points to the original 2026-05-21, not yesterday
    assert "moved from [[2026-05-21#Tasks]]" in written["2026-06-04"]


def test_daily_rollover_idempotent_skips_already_rolled():
    """Today already has a 'moved from' copy of yesterday's task. Re-running
    rollover should not duplicate it."""
    agent, vault = _agent_with_two_daily_bodies(
        yesterday_body="## Tasks\n- [ ] ~~Order phone~~ — moved to [[2026-06-04#Tasks]]\n",
        today_body="## Tasks\n- [ ] Order phone — moved from [[2026-06-03#Tasks]]\n",
    )
    result = agent._tool_daily_rollover({
        "from_date": "2026-06-03",
        "to_date": "2026-06-04",
    })
    assert result["ok"] is True
    # No writes — both files already in the target state
    assert vault.write_daily_note.call_count == 0


def test_daily_rollover_does_not_copy_checked_items():
    agent, vault = _agent_with_two_daily_bodies(
        yesterday_body="## Tasks\n- [x] Already done\n",
        today_body="## Tasks\n",
    )
    result = agent._tool_daily_rollover({
        "from_date": "2026-06-03",
        "to_date": "2026-06-04",
    })
    assert result["ok"] is True
    # No unchecked items to roll → no writes
    assert vault.write_daily_note.call_count == 0


def test_promote_daily_task_creates_file_with_today_when_no_chain():
    agent = _agent_with_daily_body("## Tasks\n- [ ] Order phone\n")
    agent.vault.create_task = MagicMock(return_value={
        "path": "40-tasks/active/order-phone.md",
        "metadata": {"name": "Order phone", "created": "2026-06-04"},
    })

    result = agent._tool_promote_daily_task({"text": "Order"})
    assert result["ok"] is True

    # vault.create_task called with name and (some) created date
    args = agent.vault.create_task.call_args
    kwargs = args.kwargs
    assert kwargs["name"] == "Order phone"
    # When no chain, created = today (handler default)
    import datetime as dt
    assert kwargs.get("created") == dt.date.today().isoformat()

    # Daily note rewritten with wikilink
    new_body = agent.vault.write_daily_note.call_args.args[1]
    assert "[[order-phone]]" in new_body
    assert "- [ ] Order phone" not in new_body


def test_promote_daily_task_uses_first_original_when_chain_present():
    agent = _agent_with_daily_body(
        "## Tasks\n- [ ] Order phone — moved from [[2026-05-21#Tasks]]\n"
    )
    agent.vault.create_task = MagicMock(return_value={
        "path": "40-tasks/active/order-phone.md",
        "metadata": {"name": "Order phone", "created": "2026-05-21"},
    })

    result = agent._tool_promote_daily_task({"text": "Order"})
    assert result["ok"] is True

    kwargs = agent.vault.create_task.call_args.kwargs
    assert kwargs.get("created") == "2026-05-21"


def test_promote_daily_task_ambiguous_returns_error():
    agent = _agent_with_daily_body(
        "## Tasks\n- [ ] Buy milk\n- [ ] Buy bread\n"
    )
    agent.vault.create_task = MagicMock()
    result = agent._tool_promote_daily_task({"text": "Buy"})
    assert result["ok"] is False
    assert result["error"]["code"] == "AMBIGUOUS_MATCH"
    agent.vault.create_task.assert_not_called()


def test_promote_daily_task_no_match_returns_path_not_found():
    agent = _agent_with_daily_body("## Tasks\n- [ ] Buy milk\n")
    agent.vault.create_task = MagicMock()
    result = agent._tool_promote_daily_task({"text": "nonexistent"})
    assert result["ok"] is False
    assert result["error"]["code"] == "PATH_NOT_FOUND"
    agent.vault.create_task.assert_not_called()


def test_daily_set_state_matches_child_subtask():
    agent = _agent_with_daily_body(
        "## Tasks\n- [ ] Plan picnic\n  - [ ] Buy bread\n  - [ ] Bring blanket\n"
    )
    result = agent._tool_daily_set_task_state({"text": "bread", "state": "checked"})
    assert result["ok"] is True
    new_body = agent.vault.write_daily_note.call_args.args[1]
    assert "- [x] Buy bread" in new_body
    # parent untouched
    assert "- [ ] Plan picnic" in new_body


def test_daily_set_state_ambiguous_across_levels():
    """A substring that matches both a top-level item and a child should return AMBIGUOUS_MATCH."""
    agent = _agent_with_daily_body(
        "## Tasks\n- [ ] Buy milk\n- [ ] Plan picnic\n  - [ ] Buy bread\n"
    )
    result = agent._tool_daily_set_task_state({"text": "Buy", "state": "checked"})
    assert result["ok"] is False
    assert result["error"]["code"] == "AMBIGUOUS_MATCH"
    candidates = result["error"]["details"]["candidates"]
    assert "Buy milk" in candidates
    assert "Buy bread" in candidates


def test_daily_set_state_still_no_match():
    agent = _agent_with_daily_body(
        "## Tasks\n- [ ] Plan picnic\n  - [ ] Buy bread\n"
    )
    result = agent._tool_daily_set_task_state({"text": "ghost", "state": "checked"})
    assert result["ok"] is False
    assert result["error"]["code"] == "PATH_NOT_FOUND"
