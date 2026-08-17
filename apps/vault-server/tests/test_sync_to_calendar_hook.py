"""Tests for sync_to_calendar post-hook."""

from unittest.mock import MagicMock

import pytest

from src.services.hooks.sync_to_calendar import sync_to_calendar


def test_hook_noop_when_calendar_missing_from_ctx():
    ctx = {"vault": MagicMock(), "tool": {"schema": {"name": "create_task"}}}
    # Should not raise even with no calendar
    sync_to_calendar(
        params={"name": "X"},
        output={"ok": True, "data": {}, "_items": ["40-tasks/active/x.md"]},
        ctx=ctx,
    )


def test_hook_noop_when_calendar_uninitialized():
    calendar = MagicMock(is_initialized=False)
    vault = MagicMock()
    sync_to_calendar(
        params={"name": "X"},
        output={"ok": True, "data": {}, "_items": ["40-tasks/active/x.md"]},
        ctx={
            "calendar": calendar,
            "vault": vault,
            "tool": {"schema": {"name": "create_task"}},
        },
    )
    calendar.sync_task.assert_not_called()


def test_hook_noop_when_output_not_ok():
    calendar = MagicMock(is_initialized=True)
    vault = MagicMock()
    sync_to_calendar(
        params={"name": "X"},
        output={"ok": False, "error": {"code": "PATH_NOT_FOUND"}, "_items": []},
        ctx={
            "calendar": calendar,
            "vault": vault,
            "tool": {"schema": {"name": "create_task"}},
        },
    )
    calendar.sync_task.assert_not_called()
    calendar.sync_habit.assert_not_called()


def test_hook_syncs_task_after_create():
    calendar = MagicMock(is_initialized=True)
    vault = MagicMock()
    vault.read_file.return_value = {
        "metadata": {"type": "task", "name": "X", "due_date": "2026-06-10"},
        "content": "",
    }

    sync_to_calendar(
        params={"name": "X"},
        output={"ok": True, "data": {}, "_items": ["40-tasks/active/x.md"]},
        ctx={
            "calendar": calendar,
            "vault": vault,
            "tool": {"schema": {"name": "create_task"}},
        },
    )
    calendar.sync_task.assert_called_once()


def test_hook_syncs_habit():
    calendar = MagicMock(is_initialized=True)
    vault = MagicMock()
    vault.read_file.return_value = {
        "metadata": {"type": "habit", "name": "Workout"},
        "content": "",
    }
    sync_to_calendar(
        params={"name": "Workout"},
        output={"ok": True, "data": {}, "_items": ["20-habits/workout.md"]},
        ctx={
            "calendar": calendar,
            "vault": vault,
            "tool": {"schema": {"name": "create_habit"}},
        },
    )
    calendar.sync_habit.assert_called_once()


def test_hook_marks_event_complete_when_completing_task_with_event_id():
    calendar = MagicMock(is_initialized=True)
    vault = MagicMock()
    vault.read_file.return_value = {
        "metadata": {"type": "task", "name": "X", "google_event_id": "evt-123", "status": "done"},
        "content": "",
    }
    sync_to_calendar(
        params={"task_name": "X"},
        output={"ok": True, "data": {"task": "X"}, "_items": ["40-tasks/archive/x.md"]},
        ctx={
            "calendar": calendar,
            "vault": vault,
            "tool": {"schema": {"name": "complete_task"}},
        },
    )
    calendar.mark_event_complete.assert_called_once_with("evt-123")
    calendar.sync_task.assert_not_called()


def test_hook_failure_logs_but_does_not_raise():
    calendar = MagicMock(is_initialized=True)
    calendar.sync_task.side_effect = RuntimeError("GCal down")
    vault = MagicMock()
    vault.read_file.return_value = {
        "metadata": {"type": "task", "name": "X"},
        "content": "",
    }
    # MUST NOT raise
    sync_to_calendar(
        params={"name": "X"},
        output={"ok": True, "data": {}, "_items": ["40-tasks/active/x.md"]},
        ctx={
            "calendar": calendar,
            "vault": vault,
            "tool": {"schema": {"name": "create_task"}},
        },
    )


def test_hook_noop_on_delete_tools():
    """delete/archive tools may leave no item to sync — skip."""
    calendar = MagicMock(is_initialized=True)
    vault = MagicMock()
    sync_to_calendar(
        params={"task_name": "X"},
        output={"ok": True, "data": {}, "_items": ["40-tasks/active/x.md"]},
        ctx={
            "calendar": calendar,
            "vault": vault,
            "tool": {"schema": {"name": "delete_task"}},
        },
    )
    calendar.sync_task.assert_not_called()
    calendar.mark_event_complete.assert_not_called()


def _ctx(calendar, vault, tool_name="complete_habit"):
    return {
        "calendar": calendar,
        "vault": vault,
        "tool": {"schema": {"name": tool_name}},
    }


def _output(path="20-habits/dog-walk.md"):
    return {"ok": True, "data": {}, "_items": [path]}


def test_persists_new_event_id_to_the_habit_file():
    calendar = MagicMock()
    calendar.is_initialized = True
    calendar.sync_habit.return_value = "gcal_evt_1"

    vault = MagicMock()
    vault.read_file.return_value = {
        "metadata": {"type": "habit", "name": "Dog Walk", "google_event_id": None}
    }

    sync_to_calendar({}, _output(), _ctx(calendar, vault))

    vault.update_file.assert_called_once_with(
        "20-habits/dog-walk.md", {"google_event_id": "gcal_evt_1"}
    )


def test_existing_event_id_is_marked_complete_not_recreated():
    calendar = MagicMock()
    calendar.is_initialized = True

    vault = MagicMock()
    vault.read_file.return_value = {
        "metadata": {"type": "habit", "name": "Workout", "google_event_id": "gcal_old"}
    }

    sync_to_calendar({}, _output("20-habits/workout.md"), _ctx(calendar, vault))

    calendar.mark_event_complete.assert_called_once_with("gcal_old")
    calendar.sync_habit.assert_not_called()
    vault.update_file.assert_not_called()


def test_two_completions_create_only_one_calendar_event():
    """Regression: three dog walks produced three calendar entries."""
    calendar = MagicMock()
    calendar.is_initialized = True
    calendar.sync_habit.return_value = "gcal_evt_1"

    stored = {"type": "habit", "name": "Dog Walk", "google_event_id": None}
    vault = MagicMock()
    vault.read_file.side_effect = lambda p: {"metadata": dict(stored)}
    vault.update_file.side_effect = lambda p, updates: stored.update(updates)

    sync_to_calendar({}, _output(), _ctx(calendar, vault))
    sync_to_calendar({}, _output(), _ctx(calendar, vault))

    assert calendar.sync_habit.call_count == 1
    calendar.mark_event_complete.assert_called_once_with("gcal_evt_1")


def test_reports_when_calendar_is_not_configured():
    output = _output()
    sync_to_calendar({}, output, _ctx(None, MagicMock()))

    assert output["data"]["calendar_sync"] == {
        "ok": False,
        "reason": "calendar_not_configured",
    }


def test_reports_failure_when_sync_raises():
    calendar = MagicMock()
    calendar.is_initialized = True
    calendar.sync_habit.side_effect = RuntimeError("gcal down")

    vault = MagicMock()
    vault.read_file.return_value = {
        "metadata": {"type": "habit", "google_event_id": None}
    }

    output = _output()
    sync_to_calendar({}, output, _ctx(calendar, vault))

    assert output["data"]["calendar_sync"]["ok"] is False
    assert "gcal down" in output["data"]["calendar_sync"]["reason"]


def test_reports_success_with_the_event_id():
    calendar = MagicMock()
    calendar.is_initialized = True
    calendar.sync_habit.return_value = "gcal_evt_1"

    vault = MagicMock()
    vault.read_file.return_value = {
        "metadata": {"type": "habit", "google_event_id": None}
    }

    output = _output()
    sync_to_calendar({}, output, _ctx(calendar, vault))

    assert output["data"]["calendar_sync"] == {"ok": True, "event_id": "gcal_evt_1"}
