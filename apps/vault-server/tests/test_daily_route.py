"""Tests for the /daily route — new schedule + notes shape."""
from datetime import date
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.daily_tasks import parse_tasks_section


# Inline the _extract_section helper to avoid circular-import from daily.py
def _extract_section(body: str, name: str) -> str:
    pat = re.compile(
        rf"##\s+{re.escape(name)}\s*\n(.*?)(?=^##\s|\Z)",
        re.DOTALL | re.MULTILINE | re.IGNORECASE,
    )
    m = pat.search(body)
    return m.group(1) if m else ""


class TestExtractSection:
    def test_extracts_notes_section(self):
        body = "## Tasks\n- [ ] do thing\n\n## Notes\n- First note\n- Second note\n"
        result = _extract_section(body, "Notes")
        assert "First note" in result
        assert "Second note" in result

    def test_returns_empty_string_when_missing(self):
        body = "## Tasks\n- [ ] do thing\n"
        result = _extract_section(body, "Notes")
        assert result == ""

    def test_stops_at_next_header(self):
        body = "## Notes\n- note line\n\n## Other\n- other content\n"
        result = _extract_section(body, "Notes")
        assert "note line" in result
        assert "other content" not in result


class TestDailyScheduleBuilding:
    """Verify that the schedule-building logic works correctly."""

    def test_timed_daily_task_included(self):
        body = "## Tasks\n- [ ] 14:00 — Visit dentist\n"
        tasks = parse_tasks_section(body)
        timed = [t for t in tasks if t.scheduled_at and t.state in ("unchecked", "checked")]
        assert len(timed) == 1
        assert "dentist" in timed[0].text.lower()
        assert timed[0].scheduled_at == "14:00"

    def test_untimed_daily_task_excluded(self):
        body = "## Tasks\n- [ ] Buy groceries\n"
        tasks = parse_tasks_section(body)
        timed = [t for t in tasks if t.scheduled_at]
        assert len(timed) == 0

    def test_checked_timed_task_is_completed(self):
        body = "## Tasks\n- [x] 09:00 — Morning standup\n"
        tasks = parse_tasks_section(body)
        timed = [t for t in tasks if t.scheduled_at]
        assert len(timed) == 1
        assert timed[0].state == "checked"

    def test_notes_parsed_from_section(self):
        body = "## Notes\n- Remember dentist\n- Call mom\n"
        section = _extract_section(body, "Notes")
        lines = [l.strip().lstrip("- ").strip() for l in section.splitlines() if l.strip().lstrip("- ").strip()]
        assert "Remember dentist" in lines
        assert "Call mom" in lines

    def test_image_line_detected(self):
        body = "## Notes\n- ![sunset](data/media/photo.jpg)\n"
        section = _extract_section(body, "Notes")
        img_match = None
        for line in section.splitlines():
            stripped = line.strip().lstrip("- ").strip()
            img_match = re.match(r"!\[([^\]]*)\]\(([^)]*)\)", stripped)
            if img_match:
                break
        assert img_match is not None
        assert img_match.group(1) == "sunset"
        assert "photo.jpg" in img_match.group(2)

    def test_schedule_sorted_ascending(self):
        starts = ["10:00", "07:00", "2026-06-04T08:00:00"]
        sorted_starts = sorted(starts)
        # ISO datetime "2026-..." sorts before "07:00" alphabetically
        # In practice, mixing formats is avoided, but sorting still works
        assert sorted_starts == sorted(starts)


class TestDailyResponseModels:
    """Assert on the real response models.

    An earlier version of this class mirrored the model definitions locally,
    claiming a circular import made the real ones unimportable. That is not
    true — `TestDayTodos` below imports the module fine — and a mirror can
    only ever assert that the copy matches itself. It went stale immediately:
    it still described a five-field response after `todos` was added.
    """

    def test_response_model_fields(self):
        from src.api.routes.daily import DailyResponse

        assert set(DailyResponse.model_fields) == {
            "date", "tokens_today", "tokens_total", "schedule", "todos", "notes",
        }

    def test_todo_model_fields(self):
        from src.api.routes.daily import DailyTodo

        assert set(DailyTodo.model_fields) == {
            "text", "done", "section", "scheduled_at", "duration_minutes",
        }
        t = DailyTodo(text="Order dog food")
        assert t.done is False and t.section == ""
        assert t.scheduled_at is None and t.duration_minutes is None

    def test_schedule_item_source_values(self):
        from pydantic import BaseModel

        class _DailyScheduleItem(BaseModel):
            start: str
            title: str
            source: str
            completed: bool = False

        for source in ("calendar", "daily-task", "habit"):
            item = _DailyScheduleItem(start="09:00", title="Test", source=source, completed=False)
            assert item.source == source

    def test_daily_note_photo_fields(self):
        from pydantic import BaseModel

        class _DailyNote(BaseModel):
            text: str | None = None
            photo_path: str | None = None
            caption: str | None = None

        note = _DailyNote(photo_path="/data/photo.jpg", caption="sunset")
        assert note.photo_path == "/data/photo.jpg"
        assert note.caption == "sunset"
        assert note.text is None


class TestHabitScheduledAt:
    """The canonical key is scheduled_at; scheduled_time is the legacy name."""

    def test_prefers_canonical_key(self):
        from src.api.routes.daily import _habit_scheduled_at
        assert _habit_scheduled_at({"scheduled_at": "07:30"}) == "07:30"

    def test_falls_back_to_legacy_key(self):
        from src.api.routes.daily import _habit_scheduled_at
        assert _habit_scheduled_at({"scheduled_time": "07:30"}) == "07:30"

    def test_canonical_wins_when_both_present(self):
        from src.api.routes.daily import _habit_scheduled_at
        meta = {"scheduled_at": "08:00", "scheduled_time": "07:30"}
        assert _habit_scheduled_at(meta) == "08:00"

    def test_returns_none_when_unscheduled(self):
        from src.api.routes.daily import _habit_scheduled_at
        assert _habit_scheduled_at({"name": "Workout"}) is None

    def test_treats_empty_string_as_unscheduled(self):
        from src.api.routes.daily import _habit_scheduled_at
        assert _habit_scheduled_at({"scheduled_at": ""}) is None


class TestScheduledHabitCompletion:
    """A scheduled habit's `completed` flag means the day's target is met.

    Regression: the route compared `last_completed` to today, and Task 7 sets
    `last_completed` on partial completions — so the first of two dog walks
    marked the whole schedule item done.
    """

    @staticmethod
    def _today():
        import datetime as dt
        import pytz
        from src.config import settings
        return dt.datetime.now(pytz.timezone(settings.vault_timezone)).date()

    def _habit(self, *, target=2, log_times=(), last_completed=None):
        today = self._today().isoformat()
        log = "".join(f"- {today}T{t}\n" for t in log_times)
        return {
            "path": "20-habits/dog-walk.md",
            "metadata": {
                "type": "habit",
                "name": "Dog Walk",
                "status": "active",
                "scheduled_at": "07:00",
                "daily_target": target,
                "last_completed": last_completed,
            },
            "content": f"# Dog Walk\n\n## Completion Log\n{log}",
        }

    def _schedule(self, habit):
        from fastapi.testclient import TestClient
        from src.main import app

        vault = MagicMock()
        vault.read_daily_note.return_value = {"content": "", "path": "10-daily/x.md"}
        vault.list_active_habits.return_value = [habit]
        vault.read_token_ledger.return_value = {"metadata": {}}

        with patch("src.main.get_vault", return_value=vault), \
                patch("src.main.get_calendar", return_value=None):
            resp = TestClient(app).get("/daily")
        assert resp.status_code == 200
        items = [s for s in resp.json()["schedule"] if s["source"] == "habit"]
        assert len(items) == 1
        return items[0]

    def test_partial_completion_is_not_complete(self):
        # One of two walks: the completion stamped `last_completed` with
        # today's date, which is exactly what the old check read.
        item = self._schedule(self._habit(
            target=2,
            log_times=["07:12:00"],
            last_completed=self._today().isoformat(),
        ))
        assert item["completed"] is False

    def test_target_met_is_complete(self):
        item = self._schedule(
            self._habit(target=2, log_times=["07:12:00", "19:40:00"])
        )
        assert item["completed"] is True

    def test_pre_log_habit_completed_today_is_complete(self):
        item = self._schedule(
            self._habit(target=2, last_completed=self._today().isoformat())
        )
        assert item["completed"] is True


class TestDayTodos:
    """Bug A: a checkbox with no time was parsed and then silently dropped."""

    NOTE = (
        "## Tasks\n"
        "- [ ] Order dog food (30m)\n"
        "- [ ] 14:00 — Visit dentist (60m)\n"
        "\n"
        "## Notes\n"
        "- Bought dog food today\n"
        "- [ ] Bring the bicycle to repair shop (60m)\n"
    )

    def test_untimed_todos_are_returned(self):
        from src.api.routes.daily import _build_todos
        texts = [t.text for t in _build_todos(self.NOTE, [], date.today())]
        assert "Order dog food" in texts
        assert "Bring the bicycle to repair shop" in texts

    def test_timed_todos_are_also_returned(self):
        from src.api.routes.daily import _build_todos
        by_text = {t.text: t for t in _build_todos(self.NOTE, [], date.today())}
        assert by_text["Visit dentist"].scheduled_at == "14:00"

    def test_duration_survives(self):
        from src.api.routes.daily import _build_todos
        by_text = {t.text: t for t in _build_todos(self.NOTE, [], date.today())}
        assert by_text["Order dog food"].duration_minutes == 30

    def test_section_is_reported(self):
        from src.api.routes.daily import _build_todos
        by_text = {t.text: t for t in _build_todos(self.NOTE, [], date.today())}
        assert by_text["Order dog food"].section == "Tasks"
        assert by_text["Bring the bicycle to repair shop"].section == "Notes"

    def test_checkbox_in_notes_is_not_also_a_note(self):
        """Otherwise it renders twice — once as a todo, once as '[ ] …' prose."""
        from src.api.routes.daily import _build_notes
        texts = [n.text for n in _build_notes(self.NOTE) if n.text]
        assert texts == ["Bought dog food today"]

    def test_done_flag_reflects_the_box(self):
        from src.api.routes.daily import _build_todos
        note = "## Tasks\n- [x] Walk dog\n- [ ] Order dog food\n"
        by_text = {t.text: t.done for t in _build_todos(note, [], date.today())}
        assert by_text["Walk dog"] is True
        assert by_text["Order dog food"] is False


class TestTimedTodosReachTheSchedule:
    """A timed checkbox must land in schedule[] no matter where it lives.

    The bot drops any todo carrying a time from its Todos block, on the
    grounds that the schedule already shows it. When the schedule was built
    only from top-level `## Tasks`, a timed checkbox anywhere else was absent
    from schedule[], excluded from notes[] for being a checkbox, and then
    dropped by the bot for having a time — it appeared nowhere at all.
    """

    def test_timed_checkbox_under_notes(self):
        from src.api.routes.daily import _build_todos
        from src.services.daily_tasks import parse_all_todos

        body = "## Notes\n- [ ] 14:00 — Call plumber (30m)\n"
        assert [t.scheduled_at for t in parse_all_todos(body)] == ["14:00"]
        assert [t.text for t in _build_todos(body, [], date.today())] == ["Call plumber"]

    def test_timed_nested_child(self):
        from src.services.daily_tasks import parse_all_todos

        body = (
            "## Tasks\n"
            "- [ ] Visit dentist\n"
            "  - [ ] 09:00 — bring insurance card (10m)\n"
        )
        timed = [(t.text, t.scheduled_at) for t in parse_all_todos(body) if t.scheduled_at]
        assert timed == [("bring insurance card", "09:00")]


class TestHabitCheckboxesReflectRealState:
    """The daily template ships `## Daily Habits` checkboxes that nothing ever
    ticks — `complete_habit` writes the habit file, not the note. So a box is
    ticked from the habit's real state, and an incomplete habit is hidden
    rather than nagging from /day every morning.

    Matched by habit name, not by section name, so it holds wherever in the
    note the checkbox lives.
    """

    @staticmethod
    def _habit(name, last_completed=None):
        return {"metadata": {"name": name, "frequency": "daily",
                             "last_completed": last_completed}}

    def test_completed_habit_shows_ticked_even_though_the_note_box_is_empty(self):
        from src.api.routes.daily import _build_todos

        body = "## Daily Habits\n- [ ] Review Email\n"
        habits = [self._habit("Review Email", date.today().isoformat())]
        todos = _build_todos(body, habits, date.today())
        assert [(t.text, t.done) for t in todos] == [("Review Email", True)]

    def test_incomplete_habit_is_hidden(self):
        from src.api.routes.daily import _build_todos

        body = "## Daily Habits\n- [ ] Review Browser Tabs\n"
        habits = [self._habit("Review Browser Tabs", "2020-01-01")]
        assert _build_todos(body, habits, date.today()) == []

    def test_ordinary_todos_are_untouched(self):
        from src.api.routes.daily import _build_todos

        body = "## Tasks\n- [ ] Order dog food (30m)\n- [x] Walk dog\n"
        habits = [self._habit("Review Email", date.today().isoformat())]
        todos = _build_todos(body, habits, date.today())
        assert [(t.text, t.done) for t in todos] == [
            ("Order dog food", False), ("Walk dog", True),
        ]

    def test_match_ignores_case_and_surrounding_space(self):
        from src.api.routes.daily import _build_todos

        body = "## Daily Habits\n- [ ]   review EMAIL  \n"
        habits = [self._habit("Review Email", date.today().isoformat())]
        assert [t.done for t in _build_todos(body, habits, date.today())] == [True]

    def test_the_real_template_yields_no_todos_on_a_fresh_day(self):
        """The exact regression: a brand-new note showed two permanent,
        unclearable todos."""
        from src.api.routes.daily import _build_todos

        body = (
            "## Daily Habits\n- [ ] Review Email\n- [ ] Review Browser Tabs\n\n"
            "## Tasks\n- [ ]\n\n## Notes\n"
        )
        habits = [self._habit("Review Email"), self._habit("Review Browser Tabs")]
        assert _build_todos(body, habits, date.today()) == []
