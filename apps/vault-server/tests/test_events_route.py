"""Tests for the /events route — source-availability tracking.

`_merge_from_sources` reports which upstream systems actually answered, so
`refresh_events` can tell "the calendar has nothing today" apart from "the
calendar failed to answer" — only the former means an unmatched persisted
event was genuinely deleted upstream. An absent or uninitialized calendar
client must not be reported as available: that is exactly the condition
that caused the Ship 2 data-loss bug (an expired OAuth token looked
identical to an empty calendar, and `refresh_events` deleted every
persisted calendar event for the day).
"""
import asyncio
import datetime as dt
from unittest.mock import MagicMock, patch

from src.api.routes import events as events_route


class TestMergeFromSourcesAvailability:
    def _run(self, calendar):
        # Imported here, not at module level: importing `src.main` at
        # collection time (before any test executes) runs its module-level
        # `instrument_fastapi(app)` early and poisons the global OTel
        # tracer-provider state for the whole session — it made
        # test_agent_service.py's TestTracingSpans fail even though that
        # test runs first, because pytest imports every test module during
        # collection before executing any of them.
        import src.main  # noqa: F401 — break circular import (main imports routes)

        vault = MagicMock()
        vault.list_active_habits.return_value = []
        vault.read_daily_note.return_value = {"metadata": {}, "content": ""}

        with patch("src.main.get_vault", return_value=vault), \
                patch("src.main.get_calendar", return_value=calendar), \
                patch("src.main.get_timeline", return_value=None):
            _, available = asyncio.run(
                events_route._merge_from_sources(dt.date(2026, 8, 30))
            )
        return available

    def test_absent_calendar_is_not_available(self):
        assert "calendar" not in self._run(calendar=None)

    def test_uninitialized_calendar_is_not_available(self):
        calendar = MagicMock()
        calendar.is_initialized = False
        assert "calendar" not in self._run(calendar=calendar)

    def test_initialized_calendar_that_answers_is_available(self):
        calendar = MagicMock()
        calendar.is_initialized = True

        async def _events(**kwargs):
            return []

        calendar.get_todays_events = _events
        assert "calendar" in self._run(calendar=calendar)
