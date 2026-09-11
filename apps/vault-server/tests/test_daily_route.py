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
        # Exact set, deliberately: this is the tripwire that catches a field
        # arriving without anyone deciding it should. Extend it only when the
        # design doc calls for the new field, never to make a run go green.
        assert fields == {
            "date", "tokens_today", "tokens_total",
            "blocks", "gaps", "coverage", "incomplete", "todos", "notes",
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

    def test_coverage_model_fields(self):
        from src.api.routes.daily import DayCoverage

        assert set(DayCoverage.model_fields) == {
            "covered_minutes", "unaccounted_minutes", "elapsed_minutes",
            "confirmed_minutes", "pending_minutes",
        }

    def test_pending_block_closes_the_gap_but_does_not_confirm(self):
        """THE test that pins §3. A pending block must not leave a gap over
        its own span — that would render two rows claiming the same time with
        opposite meanings — and must not count as confirmed either."""
        from src.api.routes.daily import _build_blocks_and_coverage

        events = [{
            "id": "e1", "name": "Standup", "source": "calendar",
            "source_ids": {"calendar_id": "g1"},
            "start_time": "2026-09-10T09:00", "end_time": "2026-09-10T10:00",
        }]

        blocks, gaps, coverage = _build_blocks_and_coverage(events, "2026-09-10", 720)

        assert [b.state for b in blocks] == ["pending"]
        assert coverage.confirmed_minutes == 0
        assert coverage.pending_minutes == 60
        # 09:00-10:00 is accounted for, so no gap covers it.
        assert not any(g.start <= "09:30" <= g.end for g in gaps)
        assert coverage.covered_minutes == 60
        assert coverage.unaccounted_minutes == 720 - 60

    def test_approved_block_counts_as_confirmed(self):
        from src.api.routes.daily import _build_blocks_and_coverage

        events = [{
            "id": "e1", "name": "Dog walk", "source": "manual",
            "source_ids": {},
            "start_time": "2026-09-10T07:00", "end_time": "2026-09-10T08:00",
        }]

        blocks, _gaps, coverage = _build_blocks_and_coverage(events, "2026-09-10", 720)

        assert [b.state for b in blocks] == ["approved"]
        assert coverage.confirmed_minutes == 60
        assert coverage.pending_minutes == 0

    def test_pending_minutes_excludes_time_already_confirmed(self):
        """Overlapping blocks of different states must not double-count: the
        confirmed hour wins and pending reports only what it adds."""
        from src.api.routes.daily import _build_blocks_and_coverage

        events = [
            {"id": "a", "name": "Lunch", "source": "manual", "source_ids": {},
             "start_time": "2026-09-10T12:00", "end_time": "2026-09-10T13:00"},
            {"id": "b", "name": "Lunch meeting", "source": "calendar",
             "source_ids": {"calendar_id": "g1"},
             "start_time": "2026-09-10T12:30", "end_time": "2026-09-10T14:00"},
        ]

        _blocks, _gaps, coverage = _build_blocks_and_coverage(events, "2026-09-10", 900)

        assert coverage.confirmed_minutes == 60      # 12:00-13:00
        assert coverage.pending_minutes == 60        # 13:00-14:00 only
        assert coverage.covered_minutes == 120       # 12:00-14:00

    def test_dismissed_block_is_omitted_and_its_time_reopens(self):
        """§2.5. A meeting you skipped means that hour really is unaccounted,
        and the gap is then the prompt to say what you did instead."""
        from src.api.routes.daily import _build_blocks_and_coverage

        events = [{
            "id": "e1", "name": "Standup", "source": "calendar",
            "source_ids": {"calendar_id": "g1"}, "state": "dismissed",
            "start_time": "2026-09-10T09:00", "end_time": "2026-09-10T10:00",
        }]

        blocks, gaps, coverage = _build_blocks_and_coverage(events, "2026-09-10", 720)

        assert blocks == []
        assert coverage.covered_minutes == 0
        assert any(g.start <= "09:30" <= g.end for g in gaps)

    def test_still_ahead_blocks_count_toward_neither(self):
        """day_coverage already clips to elapsed; assert it holds for both
        of the new numbers, not just the old one."""
        from src.api.routes.daily import _build_blocks_and_coverage

        events = [{
            "id": "e1", "name": "Guitar", "source": "manual", "source_ids": {},
            "start_time": "2026-09-10T21:00", "end_time": "2026-09-10T22:00",
        }]

        blocks, _gaps, coverage = _build_blocks_and_coverage(events, "2026-09-10", 720)

        assert len(blocks) == 1              # still rendered
        assert coverage.confirmed_minutes == 0
        assert coverage.pending_minutes == 0


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
        assert past_body["gaps"] == [{"start": "00:00", "end": "24:00", "minutes": 1440, "proposal": None}]
        assert past_body["coverage"] == {
            "covered_minutes": 0, "unaccounted_minutes": 1440, "elapsed_minutes": 1440,
            "confirmed_minutes": 0, "pending_minutes": 0,
        }

        # elapsed = 0 for a future date: no gaps at all, not one big one.
        assert future_body["gaps"] == []
        assert future_body["coverage"] == {
            "covered_minutes": 0, "unaccounted_minutes": 0, "elapsed_minutes": 0,
            "confirmed_minutes": 0, "pending_minutes": 0,
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

    def test_incomplete_blocks_reach_the_response(self):
        """The builders are covered in isolation, but the wiring was not:
        deleting `incomplete=incomplete` from `get_daily` left every server
        test passing, because the pydantic field defaults to []. A feature
        that ships invisible is Bug A's shape again — which is the very bug
        this array exists to fix."""
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from src.main import app

        async def _one_incomplete(target_date):
            return {
                "date": target_date.isoformat(),
                "events": [{
                    "id": "evt_1", "name": "Dog walk",
                    "start_time": "2026-09-08T16:00:00", "end_time": None,
                    "source": "manual", "type": "manual",
                }],
                "summary": {},
            }

        with patch("src.main.get_vault", return_value=self._vault()), \
                patch("src.api.routes.events.get_events_preview", side_effect=_one_incomplete):
            body = TestClient(app).get("/daily", params={"date": "2026-09-08"}).json()

        assert body["blocks"] == []
        assert len(body["incomplete"]) == 1
        assert body["incomplete"][0]["title"] == "Dog walk"
        assert body["incomplete"][0]["missing"] == ["end_time"]
        assert body["incomplete"][0]["start"] == "16:00"

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


class TestGapProposals:
    def test_gap_model_has_a_proposal_field(self):
        from src.api.routes.daily import DailyGap, GapProposal

        assert set(DailyGap.model_fields) == {"start", "end", "minutes", "proposal"}
        assert set(GapProposal.model_fields) == {"name", "days_seen"}

    def test_decorates_gaps_with_proposals(self):
        from src.api.routes.daily import DailyGap, _decorate_gaps

        gaps = [
            DailyGap(start="00:20", end="06:40", minutes=380),
            DailyGap(start="16:00", end="17:30", minutes=90),
        ]

        decorated = _decorate_gaps(gaps, history=[])

        assert decorated[0].proposal is not None
        assert decorated[0].proposal.name == "Sleep"
        assert decorated[1].proposal is None

    def test_a_gap_ending_at_2400_is_handled(self):
        """day_coverage emits "24:00" for a gap running to end of day, which
        is not a parseable clock time. It must not crash the decorator."""
        from src.api.routes.daily import DailyGap, _decorate_gaps

        gaps = [DailyGap(start="23:00", end="24:00", minutes=60)]

        assert _decorate_gaps(gaps, history=[])[0].proposal is None

    def test_history_is_read_from_the_days_before_the_target(self, tmp_path):
        """Reads the 14 date files before the one being viewed, and never the
        target's own — today's blocks are not evidence about today."""
        import datetime as dt
        from src.api.routes.daily import _load_history
        from src.services.events_service import EventsService

        svc = EventsService(tmp_path / "events")
        svc.save_events("2026-09-09", [{"id": "a", "name": "Sleep"}])
        svc.save_events("2026-09-10", [{"id": "b", "name": "Target day"}])

        history = _load_history(svc, dt.date(2026, 9, 10))

        assert len(history) == 14
        names = [e["name"] for day in history for e in day]
        assert "Sleep" in names
        assert "Target day" not in names

    def test_history_order_is_most_recent_first(self, tmp_path):
        import datetime as dt
        from src.api.routes.daily import _load_history
        from src.services.events_service import EventsService

        svc = EventsService(tmp_path / "events")
        svc.save_events("2026-09-09", [{"id": "a", "name": "Yesterday"}])
        svc.save_events("2026-09-08", [{"id": "b", "name": "Day before"}])

        history = _load_history(svc, dt.date(2026, 9, 10))

        assert history[0][0]["name"] == "Yesterday"
        assert history[1][0]["name"] == "Day before"


def _fake_day(blocks, gaps):
    """A DailyResponse with just the fields approve-all reads."""
    from src.api.routes.daily import DailyResponse, DayCoverage

    return DailyResponse(
        date="2026-09-10", tokens_today=0, tokens_total=0,
        blocks=blocks, gaps=gaps,
        coverage=DayCoverage(
            covered_minutes=0, unaccounted_minutes=0, elapsed_minutes=720,
            confirmed_minutes=0, pending_minutes=0,
        ),
        todos=[], notes=[],
    )


class TestApproveAll:
    def test_approves_pending_blocks_and_banks_guesses(self, monkeypatch):
        """§5.6: approve-all includes proposals, and says which were guesses."""
        from fastapi.testclient import TestClient
        from src.main import app
        from src.api.routes.daily import DailyBlock, DailyGap, GapProposal
        import src.api.routes.daily as daily_route

        blocks = [
            DailyBlock(id="e1", start="09:00", end="10:00", title="Standup",
                       source="calendar", type="event", state="pending"),
            DailyBlock(id="e2", start="07:00", end="08:00", title="Dog walk",
                       source="manual", type="event", state="approved"),
        ]
        gaps = [DailyGap(start="00:20", end="06:40", minutes=380,
                         proposal=GapProposal(name="Sleep", days_seen=11))]

        async def fake_get_daily(date=None):
            return _fake_day(blocks, gaps)

        approvals, fills = [], []

        async def fake_set_state(date, event_id, body):
            approvals.append(event_id)
            return {"ok": True, "state": "approved", "event_id": event_id,
                    "habit": None, "checkbox": None}

        async def fake_fill(date, body):
            fills.append((body.start, body.end, body.name))
            return {"ok": True, "event_id": "n1", "name": "Sleep", "was_guess": True}

        monkeypatch.setattr(daily_route, "get_daily", fake_get_daily)
        monkeypatch.setattr(daily_route, "_set_state_for_approve_all", fake_set_state)
        monkeypatch.setattr(daily_route, "_fill_gap_for_approve_all", fake_fill)

        body = TestClient(app).post("/daily/2026-09-10/approve-all").json()

        assert approvals == ["e1"]                    # not the approved e2
        assert fills == [("00:20", "06:40", None)]    # name recomputed server-side
        assert [a["was_guess"] for a in body["approved"]] == [False, True]
        assert body["failed"] == []

    def test_a_failure_does_not_strand_the_rest(self, monkeypatch):
        """A 409 on a ticked habit must not abort the approvals after it.

        The failing block is ordered *before* the succeeding one: if a
        failure aborted the loop, "good" would never be attempted and this
        test would still see an empty `approved` list pass silently — proving
        nothing about stranding.
        """
        from fastapi.testclient import TestClient
        from fastapi import HTTPException
        from src.main import app
        from src.api.routes.daily import DailyBlock
        import src.api.routes.daily as daily_route

        blocks = [
            DailyBlock(id="bad", start="09:00", end="10:00", title="Dog walk",
                       source="habit", type="habit", state="pending"),
            DailyBlock(id="good", start="10:00", end="11:00", title="Standup",
                       source="calendar", type="event", state="pending"),
        ]

        async def fake_get_daily(date=None):
            return _fake_day(blocks, [])

        async def fake_set_state(date, event_id, body):
            if event_id == "bad":
                raise HTTPException(409, "untick it in /habits")
            return {"ok": True, "state": "approved", "event_id": event_id,
                    "habit": None, "checkbox": None}

        monkeypatch.setattr(daily_route, "get_daily", fake_get_daily)
        monkeypatch.setattr(daily_route, "_set_state_for_approve_all", fake_set_state)

        body = TestClient(app).post("/daily/2026-09-10/approve-all").json()

        assert [a["event_id"] for a in body["approved"]] == ["good"]
        assert [f["event_id"] for f in body["failed"]] == ["bad"]
        assert "untick" in body["failed"][0]["reason"]

    def test_still_ahead_blocks_are_not_approved(self, monkeypatch):
        """A block that has not happened cannot be confirmed — the /day view
        gives it no buttons, and approve-all must agree.

        `_fake_day`'s `elapsed_minutes` is 720 (noon). This block starts at
        21:00 (1260 minutes), genuinely past elapsed, so it must be skipped.
        Asserting the state endpoint was never called at all (not merely that
        the response looks fine) is what makes this test actually prove the
        still-ahead block was excluded rather than approved and then hidden
        by a lenient assertion.
        """
        from fastapi.testclient import TestClient
        from src.main import app
        from src.api.routes.daily import DailyBlock
        import src.api.routes.daily as daily_route

        blocks = [DailyBlock(id="later", start="21:00", end="22:00", title="Guitar",
                             source="manual", type="event", state="pending")]

        async def fake_get_daily(date=None):
            return _fake_day(blocks, [])

        called = []

        async def fake_set_state(date, event_id, body):
            called.append(event_id)
            return {"ok": True, "state": "approved", "event_id": event_id,
                    "habit": None, "checkbox": None}

        monkeypatch.setattr(daily_route, "get_daily", fake_get_daily)
        monkeypatch.setattr(daily_route, "_set_state_for_approve_all", fake_set_state)

        TestClient(app).post("/daily/2026-09-10/approve-all")

        assert called == []


class TestGapFill:
    def _install(self, monkeypatch, history=None):
        import src.main as main

        class FakeEvents:
            def __init__(self):
                self.created = []

            def get_events(self, date):
                return (history or {}).get(date, [])

            def create_event(self, **kwargs):
                self.created.append(kwargs)
                return {"id": "n1", **kwargs}

        fake = FakeEvents()
        monkeypatch.setattr(main, "get_events", lambda: fake)
        return fake

    def test_a_named_fill_creates_that_block(self, monkeypatch):
        """A supplied name is trusted as-is; no proposal lookup happens."""
        from fastapi.testclient import TestClient
        from src.main import app

        fake = self._install(monkeypatch)

        body = TestClient(app).post(
            "/daily/2026-09-10/gaps/fill",
            json={"start": "16:00", "end": "17:30", "name": "Reading"},
        ).json()

        assert body["name"] == "Reading"
        assert body["was_guess"] is False
        assert fake.created[0]["name"] == "Reading"

    def test_an_unnamed_fill_recomputes_the_proposal(self, monkeypatch):
        """§4.2: the client sends only the interval. A client-supplied name is
        a client-supplied write, and a long one would not fit in 64 bytes."""
        from fastapi.testclient import TestClient
        from src.main import app

        fake = self._install(monkeypatch)

        body = TestClient(app).post(
            "/daily/2026-09-10/gaps/fill",
            json={"start": "00:20", "end": "06:40"},
        ).json()

        # Empty history, overnight gap -> the cold-start Sleep seed.
        assert body["name"] == "Sleep"
        assert body["was_guess"] is True
        assert fake.created[0]["name"] == "Sleep"

    def test_an_unnamed_fill_with_no_proposal_is_422(self, monkeypatch):
        """Nothing to guess and nothing supplied — the bot should have asked."""
        from fastapi.testclient import TestClient
        from src.main import app

        self._install(monkeypatch)

        r = TestClient(app).post(
            "/daily/2026-09-10/gaps/fill",
            json={"start": "16:00", "end": "17:30"},
        )

        assert r.status_code == 422
