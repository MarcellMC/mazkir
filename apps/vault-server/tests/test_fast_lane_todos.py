"""Spec §7.3 and §7.6: tick a todo in any section; remove one to undo an add."""

from src.services.daily_tasks import remove_todo, set_todo_checked
from src.services.tool_handlers.daily import daily_check_todo

NOTE = "## Tasks\n- [ ] Buy milk\n- [ ] Call the plumber\n\n## Notes\n- [ ] Read chapter 3\n"


def test_remove_todo_deletes_only_the_matching_line():
    body, reason = remove_todo(NOTE, "call the plumber")
    assert reason == "ok"
    assert "plumber" not in body and "- [ ] Buy milk" in body and "- [ ] Read chapter 3" in body


def test_remove_todo_reaches_any_section():
    body, reason = remove_todo(NOTE, "read chapter")
    assert reason == "ok" and "Read chapter" not in body and "## Notes" in body


def test_remove_todo_refuses_ambiguous_and_missing():
    assert remove_todo("- [ ] Buy milk\n- [ ] Buy milk powder\n", "buy milk") == (None, "ambiguous")
    assert remove_todo(NOTE, "walk the dog") == (None, "not_found")


def test_set_todo_checked_still_matches_as_before():
    body, reason = set_todo_checked(NOTE, "buy milk")
    assert reason == "ok" and "- [x] Buy milk" in body


def test_daily_check_todo_checks_and_unchecks(vault_service):
    vault_service.write_daily_note("2026-09-28", NOTE)
    assert daily_check_todo(vault_service, {"text": "buy milk", "date": "2026-09-28"})["ok"]
    assert "- [x] Buy milk" in vault_service.read_daily_note("2026-09-28")["content"]
    assert daily_check_todo(vault_service, {"text": "buy milk", "date": "2026-09-28", "checked": False})["ok"]
    assert "- [ ] Buy milk" in vault_service.read_daily_note("2026-09-28")["content"]


def test_daily_check_todo_reports_a_missing_todo(vault_service):
    vault_service.write_daily_note("2026-09-28", NOTE)
    result = daily_check_todo(vault_service, {"text": "walk the dog", "date": "2026-09-28"})
    assert result["ok"] is False and result["error"]["code"] == "PATH_NOT_FOUND"


def test_the_tool_is_registered_as_a_write(tmp_path):
    from unittest.mock import MagicMock
    from src.services.agent_service import AgentService
    agent = AgentService(claude=MagicMock(), vault=MagicMock(), memory=MagicMock(), media_path=tmp_path)
    assert agent.tools["daily_check_todo"]["risk"] == "write"
    assert agent.tools["daily_check_todo"]["schema"]["input_schema"]["required"] == ["text"]


from unittest.mock import MagicMock

from src.services.tool_handlers.daily import daily_rollover


def _note_vault(notes: dict):
    vault = MagicMock()
    vault.read_daily_note.side_effect = lambda date: {"content": notes.get(date, "")}
    vault.write_daily_note.side_effect = lambda date, body: notes.__setitem__(date, body)
    return vault


def test_rollover_with_text_moves_only_that_todo():
    notes = {"2026-09-28": "## Tasks\n- [ ] Buy a drill\n- [ ] Call the plumber\n"}
    result = daily_rollover(_note_vault(notes), {"from_date": "2026-09-28", "to_date": "2026-09-29", "text": "drill"})
    assert result["ok"] and result["data"]["rolled"] == ["Buy a drill"]
    assert "- [ ] Call the plumber" in notes["2026-09-28"]
    assert "Buy a drill" in notes["2026-09-29"] and "plumber" not in notes["2026-09-29"]


def test_rollover_with_text_refuses_two_matches_and_none():
    notes = {"2026-09-28": "## Tasks\n- [ ] Buy milk\n- [ ] Buy milk powder\n"}
    vault = _note_vault(notes)
    two = daily_rollover(vault, {"from_date": "2026-09-28", "to_date": "2026-09-29", "text": "buy milk"})
    none = daily_rollover(vault, {"from_date": "2026-09-28", "to_date": "2026-09-29", "text": "drill"})
    assert (two["error"]["code"], none["error"]["code"]) == ("AMBIGUOUS_MATCH", "PATH_NOT_FOUND")
    assert notes["2026-09-28"].count("- [ ]") == 2 and "2026-09-29" not in notes


def test_rollover_without_text_still_moves_them_all():
    notes = {"2026-09-28": "## Tasks\n- [ ] Buy a drill\n- [ ] Call the plumber\n"}
    result = daily_rollover(_note_vault(notes), {"from_date": "2026-09-28", "to_date": "2026-09-29"})
    assert result["data"]["rolled"] == ["Buy a drill", "Call the plumber"]
