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


class TestSetState:
    """POST /events/{date}/{id}/state — spec §2.3."""

    def _install(self, monkeypatch, events):
        """Stub the events service and the source merge, returning the fake so
        tests can inspect what was saved."""
        import src.main as main
        import src.api.routes.events as events_route

        class FakeEvents:
            def __init__(self):
                self.saved = {}

            def get_events(self, date):
                return [dict(e) for e in events]

            def reconcile(self, date, fresh, available=None):
                return [dict(e) for e in events]

            def save_events(self, date, evts):
                self.saved[date] = evts

        fake = FakeEvents()
        monkeypatch.setattr(main, "get_events", lambda: fake)

        async def no_sources(date):
            return [], set()

        monkeypatch.setattr(events_route, "_merge_from_sources", no_sources)
        return fake

    def _client(self):
        from fastapi.testclient import TestClient
        from src.main import app
        return TestClient(app)

    def test_approving_a_calendar_block_stores_approved(self, monkeypatch):
        fake = self._install(monkeypatch, [
            {"id": "e1", "name": "Standup", "source": "calendar",
             "source_ids": {"calendar_id": "g1"}},
        ])

        r = self._client().post("/events/2026-09-10/e1/state",
                                json={"state": "approved"})

        assert r.status_code == 200
        assert r.json()["state"] == "approved"
        assert fake.saved["2026-09-10"][0]["state"] == "approved"

    def test_dismissing_a_calendar_block_stores_dismissed(self, monkeypatch):
        fake = self._install(monkeypatch, [
            {"id": "e1", "name": "Standup", "source": "calendar",
             "source_ids": {"calendar_id": "g1"}},
        ])

        r = self._client().post("/events/2026-09-10/e1/state",
                                json={"state": "dismissed"})

        assert r.json()["state"] == "dismissed"
        assert fake.saved["2026-09-10"][0]["state"] == "dismissed"

    def test_dismissing_never_touches_google(self, monkeypatch):
        """§2.5 and §9: dismissal is local in this ship. cancel and delete are
        deferred, and a dismissal must not quietly become either."""
        import src.main as main

        calls = []
        self._install(monkeypatch, [
            {"id": "e1", "name": "Standup", "source": "calendar",
             "source_ids": {"calendar_id": "g1"}, "calendar_id": "g1"},
        ])

        class LoudCalendar:
            async def delete_event(self, *a, **kw):
                calls.append("delete")

            async def update_event(self, *a, **kw):
                calls.append("update")

        monkeypatch.setattr(main, "get_calendar", lambda: LoudCalendar())

        self._client().post("/events/2026-09-10/e1/state",
                            json={"state": "dismissed"})

        assert calls == []

    def test_approving_an_unfired_habit_ticks_it_and_stores_nothing(self, monkeypatch):
        """Ticking makes `completed` true, so resolve_state derives approved on
        the next merge. Storing a state row as well is the §2.1 stale-row bug,
        because habit_slug ids are not stable."""
        import src.main as main
        import src.api.routes.events as events_route

        fake = self._install(monkeypatch, [
            {"id": "e1", "name": "Dog walk", "source": "habit",
             "source_ids": {"habit_slug": "dog-walk"}, "completed": False,
             "habit": {"name": "Dog walk"},
             "start_time": "2026-09-10T19:00", "end_time": "2026-09-10T20:00"},
        ])

        class FakeVault:
            def list_active_habits(self):
                return [{"metadata": {"name": "Dog walk"},
                         "path": "20-habits/dog-walk.md"}]

        monkeypatch.setattr(main, "get_vault", lambda: FakeVault())

        seen = {}

        def fake_complete(vault, path, now=None):
            seen["path"] = path
            seen["now"] = now
            return {"already_completed": False, "name": "Dog walk",
                    "tokens_earned": 5, "new_streak": 13,
                    "date": now.date().isoformat()}

        monkeypatch.setattr(events_route, "complete_habit", fake_complete)

        r = self._client().post("/events/2026-09-10/e1/state",
                                json={"state": "approved"})

        assert r.json()["habit"]["tokens_earned"] == 5
        assert r.json()["habit"]["new_streak"] == 13
        assert seen["path"] == "20-habits/dog-walk.md"
        assert fake.saved == {}          # no state row written

    def test_approving_a_habit_block_stamps_the_blocks_date(self, monkeypatch):
        """The reason Task 6 exists. Confirming Monday's block records Monday,
        not today."""
        import src.main as main
        import src.api.routes.events as events_route

        self._install(monkeypatch, [
            {"id": "e1", "name": "Dog walk", "source": "habit",
             "source_ids": {"habit_slug": "dog-walk"}, "completed": False,
             "habit": {"name": "Dog walk"},
             "start_time": "2026-09-07T19:00", "end_time": "2026-09-07T20:00"},
        ])

        class FakeVault:
            def list_active_habits(self):
                return [{"metadata": {"name": "Dog walk"},
                         "path": "20-habits/dog-walk.md"}]

        monkeypatch.setattr(main, "get_vault", lambda: FakeVault())

        seen = {}

        def fake_complete(vault, path, now=None):
            seen["now"] = now
            return {"already_completed": False, "name": "Dog walk",
                    "tokens_earned": 5, "new_streak": 2,
                    "date": now.date().isoformat()}

        monkeypatch.setattr(events_route, "complete_habit", fake_complete)

        self._client().post("/events/2026-09-07/e1/state",
                            json={"state": "approved"})

        assert seen["now"].date().isoformat() == "2026-09-07"

    def test_dismissing_a_ticked_habit_is_refused(self, monkeypatch):
        """§2.4: nothing in this ship unticks a habit. Unreachable from /day,
        so refuse rather than invent a reverse path."""
        fake = self._install(monkeypatch, [
            {"id": "e1", "name": "Dog walk", "source": "habit",
             "source_ids": {"habit_slug": "dog-walk"}, "completed": True,
             "habit": {"name": "Dog walk"}},
        ])

        r = self._client().post("/events/2026-09-10/e1/state",
                                json={"state": "dismissed"})

        assert r.status_code == 409
        assert "untick" in r.json()["detail"].lower()
        assert fake.saved == {}

    def test_approving_an_already_approved_block_is_a_no_op(self, monkeypatch):
        fake = self._install(monkeypatch, [
            {"id": "e1", "name": "Dog walk", "source": "manual", "source_ids": {}},
        ])

        r = self._client().post("/events/2026-09-10/e1/state",
                                json={"state": "approved"})

        assert r.status_code == 200
        assert r.json()["state"] == "approved"
        assert fake.saved == {}

    def test_unknown_event_is_404(self, monkeypatch):
        self._install(monkeypatch, [])

        r = self._client().post("/events/2026-09-10/nope/state",
                                json={"state": "approved"})

        assert r.status_code == 404

    def test_an_invalid_state_is_rejected(self, monkeypatch):
        self._install(monkeypatch, [
            {"id": "e1", "source": "calendar", "source_ids": {"calendar_id": "g1"}},
        ])

        r = self._client().post("/events/2026-09-10/e1/state",
                                json={"state": "suggested"})

        assert r.status_code == 422
