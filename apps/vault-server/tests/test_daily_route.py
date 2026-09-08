"""Tests for the /daily route — blocks, gaps, coverage, todos and notes."""
from datetime import date
import re


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


class TestDailyResponseModels:
    """Assert on the real response models.

    An earlier version of this class mirrored the model definitions locally,
    claiming a circular import made the real ones unimportable. That is not
    true — `TestDayTodos` below imports the module fine — and a mirror can
    only ever assert that the copy matches itself. It went stale immediately:
    it still described a five-field response after `todos` was added.
    """

    def test_todo_model_fields(self):
        from src.api.routes.daily import DailyTodo

        assert set(DailyTodo.model_fields) == {
            "text", "done", "section", "scheduled_at", "duration_minutes",
        }
        t = DailyTodo(text="Order dog food")
        assert t.done is False and t.section == ""
        assert t.scheduled_at is None and t.duration_minutes is None

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


class TestDailyBlocks:
    def test_block_model_fields(self):
        from src.api.routes.daily import DailyBlock

        assert set(DailyBlock.model_fields) == {
            "id", "start", "end", "title", "source", "type", "completed",
            "activity", "category", "state", "habit_progress",
        }

    def test_response_model_replaces_schedule_with_blocks(self):
        from src.api.routes.daily import DailyResponse

        fields = set(DailyResponse.model_fields)
        assert "schedule" not in fields
        assert fields == {
            "date", "tokens_today", "tokens_total",
            "blocks", "gaps", "coverage", "todos", "notes",
        }

    def test_builds_blocks_and_gaps_from_events(self):
        from src.api.routes.daily import _build_blocks_and_coverage

        events = [
            {"id": "e1", "name": "Dog walk", "start_time": "2026-08-29T07:00",
             "end_time": "2026-08-29T07:40", "source": "habit", "type": "habit",
             "state": "suggested", "activity": None, "category": None},
            {"id": "e2", "name": "Standup", "start_time": "2026-08-29T09:05",
             "end_time": "2026-08-29T10:00", "source": "calendar", "type": "calendar",
             "state": "suggested", "activity": None, "category": None},
        ]
        blocks, gaps, coverage = _build_blocks_and_coverage(
            events, "2026-08-29", elapsed_minutes=600,
        )
        assert [b.title for b in blocks] == ["Dog walk", "Standup"]
        assert [b.start for b in blocks] == ["07:00", "09:05"]
        assert coverage.covered_minutes == 95
        assert [(g.start, g.end) for g in gaps] == [("00:00", "07:00"), ("07:40", "09:05")]

    def test_blocks_sort_by_start_time(self):
        from src.api.routes.daily import _build_blocks_and_coverage

        events = [
            {"id": "b", "name": "Later", "start_time": "2026-08-29T12:00",
             "end_time": "2026-08-29T13:00", "source": "calendar", "type": "calendar"},
            {"id": "a", "name": "Earlier", "start_time": "2026-08-29T09:00",
             "end_time": "2026-08-29T10:00", "source": "calendar", "type": "calendar"},
        ]
        blocks, _, _ = _build_blocks_and_coverage(events, "2026-08-29", elapsed_minutes=1440)
        assert [b.title for b in blocks] == ["Earlier", "Later"]

    def test_a_block_from_another_day_is_clipped_out(self):
        """Storage splits at midnight; a stray event from a neighbouring day
        must not distort this day's coverage."""
        from src.api.routes.daily import _build_blocks_and_coverage

        events = [{"id": "x", "name": "Yesterday", "start_time": "2026-08-28T22:00",
                   "end_time": "2026-08-28T23:00", "source": "calendar", "type": "calendar"}]
        blocks, _, coverage = _build_blocks_and_coverage(events, "2026-08-29", elapsed_minutes=1440)
        assert blocks == []
        assert coverage.covered_minutes == 0

    def test_a_block_spanning_midnight_is_clipped_to_the_end_of_the_day(self):
        """Spec §4: "Block spanning midnight → rendered clipped to the day."
        `minutes_into_day` returns None for an end on the next date, and the
        block was dropped outright: a 22:00→01:00 shift produced no blocks,
        zero coverage and one 00:00–24:00 gap — the whole day read as
        unaccounted. Ship 1 displayed this event."""
        from src.api.routes.daily import _build_blocks_and_coverage

        events = [{"id": "x", "name": "Late shift", "start_time": "2026-08-29T22:00",
                   "end_time": "2026-08-30T01:00", "source": "calendar",
                   "type": "calendar"}]
        blocks, gaps, coverage = _build_blocks_and_coverage(
            events, "2026-08-29", elapsed_minutes=1440)
        assert [(b.start, b.end, b.title) for b in blocks] == [
            ("22:00", "24:00", "Late shift")]
        assert coverage.covered_minutes == 120
        assert [(g.start, g.end) for g in gaps] == [("00:00", "22:00")]

    def test_a_block_ending_days_later_is_still_clipped_to_this_day(self):
        from src.api.routes.daily import _build_blocks_and_coverage

        events = [{"id": "x", "name": "Conference", "start_time": "2026-08-29T09:00",
                   "end_time": "2026-09-01T17:00", "source": "calendar",
                   "type": "calendar"}]
        blocks, _, coverage = _build_blocks_and_coverage(
            events, "2026-08-29", elapsed_minutes=1440)
        assert [(b.start, b.end) for b in blocks] == [("09:00", "24:00")]
        assert coverage.covered_minutes == 900

    def test_an_end_before_the_day_is_still_dropped(self):
        """A later end is a span; an earlier one is corrupt data, and
        clipping it would invent an interval that never happened."""
        from src.api.routes.daily import _build_blocks_and_coverage

        events = [{"id": "x", "name": "Backwards", "start_time": "2026-08-29T09:00",
                   "end_time": "2026-08-28T17:00", "source": "calendar",
                   "type": "calendar"}]
        blocks, _, coverage = _build_blocks_and_coverage(
            events, "2026-08-29", elapsed_minutes=1440)
        assert blocks == []
        assert coverage.covered_minutes == 0

    def test_habit_progress_is_surfaced(self):
        """Carried forward from Phase 1: the bot could only render a binary
        box because completions_today never reached it."""
        from src.api.routes.daily import _build_blocks_and_coverage

        events = [{"id": "h", "name": "Dog walk", "start_time": "2026-08-29T07:00",
                   "end_time": "2026-08-29T07:40", "source": "habit", "type": "habit",
                   "habit": {"name": "Dog walk", "completed": False,
                             "completions_today": 1, "daily_target": 2}}]
        blocks, _, _ = _build_blocks_and_coverage(events, "2026-08-29", elapsed_minutes=1440)
        assert blocks[0].habit_progress == "1/2"


class TestGetDailyRoute:
    """Route-level coverage for `get_daily` itself. `_build_blocks_and_coverage`
    is exercised in isolation everywhere else, but `?date=`, the three
    `elapsed` branches, the date-or-today default, and the events wiring had
    no coverage at all — this is the integration point Tasks 7-8 consume.
    """

    @staticmethod
    def _vault():
        from unittest.mock import MagicMock
        vault = MagicMock()
        vault.read_daily_note.return_value = {"content": "", "path": "10-daily/x.md"}
        vault.list_active_habits.return_value = []
        vault.read_token_ledger.return_value = {"metadata": {}}
        return vault

    def test_date_elapsed_branches_and_no_schedule_key(self):
        import datetime as dt
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        import pytz
        from src.config import settings
        from src.main import app

        tz = pytz.timezone(settings.vault_timezone)

        async def _no_events(target_date):
            return {"date": target_date.isoformat(), "events": [], "summary": {}}

        vault = self._vault()
        with patch("src.main.get_vault", return_value=vault), \
                patch("src.api.routes.events.get_events_preview", side_effect=_no_events):
            client = TestClient(app)
            now_before = dt.datetime.now(tz)
            today = now_before.date()
            past = (today - dt.timedelta(days=1)).isoformat()
            future = (today + dt.timedelta(days=1)).isoformat()

            past_body = client.get("/daily", params={"date": past}).json()
            future_body = client.get("/daily", params={"date": future}).json()
            today_body = client.get("/daily").json()
            now_after = dt.datetime.now(tz)

        # `date` echoes back, including the untouched date-or-today default.
        assert past_body["date"] == past
        assert future_body["date"] == future
        assert today_body["date"] == today.isoformat()

        # elapsed = 1440 for a past date: one full-day gap, nothing covered.
        assert past_body["gaps"] == [{"start": "00:00", "end": "24:00", "minutes": 1440}]
        assert past_body["coverage"] == {
            "covered_minutes": 0, "unaccounted_minutes": 1440, "elapsed_minutes": 1440,
        }

        # elapsed = 0 for a future date: no gaps at all, not one big one.
        assert future_body["gaps"] == []
        assert future_body["coverage"] == {
            "covered_minutes": 0, "unaccounted_minutes": 0, "elapsed_minutes": 0,
        }

        # elapsed = now for today: one gap ending at (about) the wall clock.
        assert len(today_body["gaps"]) == 1
        end = today_body["gaps"][0]["end"]
        gap_end_minutes = int(end[:2]) * 60 + int(end[3:])
        lo = now_before.hour * 60 + now_before.minute
        hi = now_after.hour * 60 + now_after.minute
        assert lo <= gap_end_minutes <= hi
        assert lo <= today_body["coverage"]["elapsed_minutes"] <= hi

        for body in (past_body, future_body, today_body):
            assert "schedule" not in body

    def test_elapsed_minutes_three_cases(self):
        """`elapsed_minutes` is what lets the bot draw the now-divider
        without any timezone math of its own: past day -> 1440, future day
        -> 0, today -> strictly between the two."""
        from src.api.routes.daily import _build_blocks_and_coverage

        _, _, past = _build_blocks_and_coverage([], "2026-08-29", elapsed_minutes=1440)
        _, _, future = _build_blocks_and_coverage([], "2026-08-29", elapsed_minutes=0)
        _, _, today = _build_blocks_and_coverage([], "2026-08-29", elapsed_minutes=600)

        assert past.elapsed_minutes == 1440
        assert future.elapsed_minutes == 0
        assert today.elapsed_minutes == 600
        assert 0 < today.elapsed_minutes < 1440

    def test_traversal_date_is_rejected(self):
        from fastapi.testclient import TestClient
        from src.main import app

        resp = TestClient(app).get("/daily", params={"date": "../../../../etc/passwd"})
        assert resp.status_code == 422


class TestBlockCompletion:
    """`completed` was dead end to end: the merger discarded it, the route
    read it only from `habit`, and the bot never rendered it. A checked
    `- [x] 14:00 — Standup` rendered as an ordinary block and appeared
    nowhere else, since /day filters timed todos out of the Todos list."""

    @staticmethod
    def _event(**kw):
        e = {"id": "e1", "name": "Standup", "start_time": "2026-08-29T09:00",
             "end_time": "2026-08-29T10:00", "source": "calendar", "type": "calendar"}
        e.update(kw)
        return e

    def test_the_events_completed_field_reaches_the_block(self):
        from src.api.routes.daily import _build_blocks_and_coverage

        blocks, _, _ = _build_blocks_and_coverage(
            [self._event(completed=True)], "2026-08-29", elapsed_minutes=1440)
        assert blocks[0].completed is True

    def test_an_uncompleted_event_stays_uncompleted(self):
        from src.api.routes.daily import _build_blocks_and_coverage

        blocks, _, _ = _build_blocks_and_coverage(
            [self._event(completed=False)], "2026-08-29", elapsed_minutes=1440)
        assert blocks[0].completed is False

    def test_a_legacy_event_still_reads_completion_from_habit(self):
        """Events persisted before MergedEvent.completed existed carry it
        only inside `habit`."""
        from src.api.routes.daily import _build_blocks_and_coverage

        blocks, _, _ = _build_blocks_and_coverage(
            [self._event(source="habit", type="habit",
                         habit={"name": "Dog walk", "completed": True})],
            "2026-08-29", elapsed_minutes=1440)
        assert blocks[0].completed is True


class TestIncompleteBlocks:
    """A block missing an end used to be dropped by `continue`.

    That is Bug A's exact shape — written correctly, parsed correctly,
    invisible — and it is why partial capture needs its own array rather
    than relying on the timeline.
    """

    def test_block_missing_an_end_is_reported_not_dropped(self):
        from src.api.routes.daily import _build_blocks_and_coverage, _build_incomplete
        events = [{"id": "evt_1", "name": "Dog walk", "start_time": "2026-09-08T16:00:00",
                   "end_time": None, "source": "manual", "type": "manual"}]
        blocks, _, _ = _build_blocks_and_coverage(events, "2026-09-08", 1440)
        incomplete = _build_incomplete(events, "2026-09-08")
        assert blocks == []
        assert len(incomplete) == 1
        assert incomplete[0].title == "Dog walk"
        assert incomplete[0].missing == ["end_time"]
        assert incomplete[0].start == "16:00"

    def test_block_missing_a_start_reports_its_end(self):
        from src.api.routes.daily import _build_incomplete
        incomplete = _build_incomplete(
            [{"id": "evt_1", "name": "Dog walk", "start_time": None,
              "end_time": "2026-09-08T16:40:00", "source": "manual", "type": "manual"}],
            "2026-09-08",
        )
        assert incomplete[0].missing == ["start_time"]
        assert incomplete[0].end == "16:40"
        assert incomplete[0].start is None

    def test_incomplete_blocks_do_not_change_coverage(self):
        """The gap is the reason to finish the block. A half-block that
        quietly claimed the span would hide the very hole it represents."""
        from src.api.routes.daily import _build_blocks_and_coverage
        _, gaps_with, coverage_with = _build_blocks_and_coverage(
            [{"id": "evt_1", "name": "Dog walk", "start_time": "2026-09-08T16:00:00",
              "end_time": None, "source": "manual", "type": "manual"}],
            "2026-09-08", 1440,
        )
        _, gaps_without, coverage_without = _build_blocks_and_coverage(
            [], "2026-09-08", 1440,
        )
        assert coverage_with.covered_minutes == coverage_without.covered_minutes
        assert len(gaps_with) == len(gaps_without)

    def test_event_belonging_to_another_day_is_still_dropped(self):
        """Present-but-elsewhere and genuinely-absent both make
        `minutes_into_day` return None; only the second is incomplete."""
        from src.api.routes.daily import _build_blocks_and_coverage, _build_incomplete
        events = [{"id": "evt_1", "name": "Yesterday", "start_time": "2026-09-07T16:00:00",
                   "end_time": "2026-09-07T17:00:00", "source": "manual", "type": "manual"}]
        blocks, _, _ = _build_blocks_and_coverage(events, "2026-09-08", 1440)
        incomplete = _build_incomplete(events, "2026-09-08")
        assert blocks == []
        assert incomplete == []
