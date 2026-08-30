"""Tests for the /events route — source-availability tracking.

`_merge_from_sources` reports which upstream systems actually answered, so
`refresh_events` can tell "the calendar has nothing today" apart from "the
calendar failed to answer" — only the former means an unmatched persisted
event was genuinely deleted upstream.

Availability must be a positive signal from the source, not merely the
absence of an exception: `get_todays_events` swallows `HttpError` and
returns `[]` either way, `timeline.get_day` returns `[]`/empty when
`data/timeline/` doesn't exist, and `read_daily_note` catches
`FileNotFoundError` internally and returns an empty note. Each of those
looks identical to "the source answered and has nothing" unless gated on
something more than "the call didn't raise" — which is exactly the
condition that caused the Ship 2 data-loss bug (an expired OAuth token
looked identical to an empty calendar, and `refresh_events` deleted every
persisted calendar event for the day).
"""
import asyncio
import datetime as dt
from unittest.mock import MagicMock, patch

from src.api.routes import events as events_route


class TestMergeFromSourcesAvailability:
    def _run(self, calendar=None, vault=None, timeline=None):
        # Imported here, not at module level: importing `src.main` at
        # collection time (before any test executes) runs its module-level
        # `instrument_fastapi(app)` early and poisons the global OTel
        # tracer-provider state for the whole session — it made
        # test_agent_service.py's TestTracingSpans fail even though that
        # test runs first, because pytest imports every test module during
        # collection before executing any of them.
        import src.main  # noqa: F401 — break circular import (main imports routes)

        if vault is None:
            vault = MagicMock()
            vault.list_active_habits.return_value = []
            vault.read_daily_note.return_value = {"metadata": {}, "content": ""}
            vault.vault_path = MagicMock()
            vault.vault_path.exists.return_value = True

        with patch("src.main.get_vault", return_value=vault), \
                patch("src.main.get_calendar", return_value=calendar), \
                patch("src.main.get_timeline", return_value=timeline):
            _, available = asyncio.run(
                events_route._merge_from_sources(dt.date(2026, 8, 30))
            )
        return available

    # --- calendar ---

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
            return [], True

        calendar.get_todays_events_with_status = _events
        assert "calendar" in self._run(calendar=calendar)

    def test_calendar_that_fails_is_not_available(self):
        """The Critical this fix round exists for: get_todays_events itself
        swallows HttpError and returns [] regardless, so a failing calendar
        must be told apart via the ok flag, not by whether the call raised."""
        calendar = MagicMock()
        calendar.is_initialized = True

        async def _events(**kwargs):
            return [], False  # e.g. a 401/403/429 the calendar service swallowed

        calendar.get_todays_events_with_status = _events
        assert "calendar" not in self._run(calendar=calendar)

    # --- timeline ---

    def test_timeline_with_no_data_path_is_not_available(self):
        """timeline.get_day returns an empty structure, not an exception,
        when data/timeline/ doesn't exist — indistinguishable from a
        genuinely empty day unless gated on the path existing."""
        timeline = MagicMock()
        timeline.get_day.return_value = {"visits": [], "activities": []}
        timeline.data_path = MagicMock()
        timeline.data_path.exists.return_value = False
        assert "timeline" not in self._run(timeline=timeline)

    def test_timeline_with_a_data_path_is_available(self):
        timeline = MagicMock()
        timeline.get_day.return_value = {"visits": [], "activities": []}
        timeline.data_path = MagicMock()
        timeline.data_path.exists.return_value = True
        assert "timeline" in self._run(timeline=timeline)

    # --- daily note ---

    def test_missing_vault_directory_makes_daily_note_unavailable(self):
        """read_daily_note catches FileNotFoundError internally and returns
        an empty note either way, so the call succeeding says nothing about
        whether a note exists — gate on the vault directory resolving
        instead, which is the real "did this source answer" question. A
        missing note for `date` is legitimate information; a missing vault
        is not."""
        vault = MagicMock()
        vault.list_active_habits.return_value = []
        vault.read_daily_note.return_value = {"metadata": {}, "content": ""}
        vault.vault_path = MagicMock()
        vault.vault_path.exists.return_value = False
        assert "daily-note" not in self._run(vault=vault)

    def test_resolving_vault_directory_makes_daily_note_available(self):
        vault = MagicMock()
        vault.list_active_habits.return_value = []
        vault.read_daily_note.return_value = {"metadata": {}, "content": ""}
        vault.vault_path = MagicMock()
        vault.vault_path.exists.return_value = True
        assert "daily-note" in self._run(vault=vault)

    # --- habits ---
    #
    # `list_active_habits` calls `list_files("20-habits")`, which returns []
    # for a missing directory rather than raising — so "it didn't raise"
    # marks a renamed or missing habits directory as available, and every
    # persisted habit-derived event for the day looks deleted upstream.
    # These use a real tmp_path rather than a MagicMock vault_path, because
    # `MagicMock() / "20-habits"` yields another MagicMock whose `.exists()`
    # is truthy — the gate would pass without testing anything.

    def _real_vault(self, vault_path, habits=None, raises=False):
        vault = MagicMock()
        if raises:
            vault.list_active_habits.side_effect = OSError("vault unreadable")
        else:
            vault.list_active_habits.return_value = habits or []
        vault.read_daily_note.return_value = {"metadata": {}, "content": ""}
        vault.vault_path = vault_path
        return vault

    def test_missing_habits_directory_makes_habit_source_unavailable(self, tmp_path):
        assert "habit" not in self._run(vault=self._real_vault(tmp_path))

    def test_present_habits_directory_makes_habit_source_available(self, tmp_path):
        (tmp_path / "20-habits").mkdir()
        assert "habit" in self._run(vault=self._real_vault(tmp_path))

    def test_an_empty_habits_directory_is_still_available(self, tmp_path):
        """A vault with no habit files is real information — nothing is
        scheduled today — unlike a directory that isn't there at all."""
        (tmp_path / "20-habits").mkdir()
        assert "habit" in self._run(vault=self._real_vault(tmp_path, habits=[]))

    def test_a_vault_that_raises_makes_habit_source_unavailable(self, tmp_path):
        (tmp_path / "20-habits").mkdir()
        assert "habit" not in self._run(vault=self._real_vault(tmp_path, raises=True))
