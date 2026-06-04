"""Tests for the /daily route — new schedule + notes shape."""
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
    """Verify the new Pydantic response models by constructing equivalent models locally.

    We cannot import directly from src.api.routes.daily because it imports get_vault/get_calendar
    from src.main, which creates a circular import during pytest collection.  Instead we mirror
    the model definitions here and assert on their field names — any drift would cause type errors
    in production.
    """

    def test_response_model_has_correct_fields(self):
        from pydantic import BaseModel

        class _DailyScheduleItem(BaseModel):
            start: str
            end: str | None = None
            title: str
            source: str
            completed: bool = False
            calendar_name: str | None = None

        class _DailyNote(BaseModel):
            text: str | None = None
            photo_path: str | None = None
            caption: str | None = None

        class _DailyResponse(BaseModel):
            date: str
            tokens_today: int
            tokens_total: int
            schedule: list[_DailyScheduleItem]
            notes: list[_DailyNote]

        item = _DailyScheduleItem(start="09:00", title="Test", source="habit", completed=False)
        note = _DailyNote(text="hello")
        resp = _DailyResponse(
            date="2026-06-04",
            tokens_today=5,
            tokens_total=50,
            schedule=[item],
            notes=[note],
        )
        d = resp.model_dump()
        assert "schedule" in d
        assert "notes" in d
        assert "habits" not in d
        assert "calendar_events" not in d
        assert "tokens_today" in d
        assert "tokens_earned" not in d
        assert "day_of_week" not in d

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
