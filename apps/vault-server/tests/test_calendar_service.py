"""Tests for CalendarService allowlist behavior."""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import MagicMock


def test_calendar_include_defaults_to_mazkir_only_when_empty():
    """When calendar_include is None (empty env var), default include = ['Mazkir']."""
    from src.services.calendar_service import CalendarService

    cs = CalendarService(
        credentials_path=MagicMock(),
        token_path=MagicMock(),
        calendar_include=None,
    )
    assert cs._calendar_include == ["Mazkir"]


def test_calendar_include_defaults_to_mazkir_only_when_empty_list():
    """When calendar_include is empty list, default include = ['Mazkir']."""
    from src.services.calendar_service import CalendarService

    cs = CalendarService(
        credentials_path=MagicMock(),
        token_path=MagicMock(),
        calendar_include=[],
    )
    assert cs._calendar_include == ["Mazkir"]


def test_calendar_include_respects_explicit_list():
    """An explicit list of calendar names is honored as-is."""
    from src.services.calendar_service import CalendarService

    cs = CalendarService(
        credentials_path=MagicMock(),
        token_path=MagicMock(),
        calendar_include=["Mazkir", "Work", "Personal"],
    )
    assert sorted(cs._calendar_include) == sorted(["Mazkir", "Work", "Personal"])


def test_calendar_include_skips_non_listed_calendars():
    """get_todays_events filters non-listed calendars when all_calendars=True."""
    from src.services.calendar_service import CalendarService

    cs = CalendarService(
        credentials_path=MagicMock(),
        token_path=MagicMock(),
        calendar_include=["Mazkir"],
    )
    cs._service = MagicMock()
    cs._initialized = True
    cs._calendar_id = "mazkir-cal-id"

    # Mock calendarList: returns Mazkir + Holidays + Work
    cs._service.calendarList().list().execute.return_value = {
        "items": [
            {"id": "mazkir-cal-id", "summary": "Mazkir"},
            {"id": "holidays-cal-id", "summary": "Israeli Holidays"},
            {"id": "work-cal-id", "summary": "Work"},
        ]
    }
    # events().list().execute returns empty
    cs._service.events().list().execute.return_value = {"items": []}

    asyncio.run(cs.get_todays_events(all_calendars=True))

    # Collect calendarIds queried via events().list()
    called_calendar_ids = [
        call.kwargs.get("calendarId")
        for call in cs._service.events().list.call_args_list
        if call.kwargs.get("calendarId") is not None
    ]
    assert "mazkir-cal-id" in called_calendar_ids
    assert "holidays-cal-id" not in called_calendar_ids
    assert "work-cal-id" not in called_calendar_ids


class TestUpdateEvent:
    """`CalendarService.update_event` — the write the class was missing.

    Exercised directly against a mocked `_service`, not just through the
    `AsyncMock` standing in for it in the agent tests, which proves nothing
    about the method's own body.
    """

    def _service(self, calendar_id="cal_123"):
        from src.services.calendar_service import CalendarService

        cs = CalendarService(
            credentials_path=MagicMock(),
            token_path=MagicMock(),
            timezone="Asia/Jerusalem",
        )
        cs._initialized = True
        cs._calendar_id = calendar_id
        cs._service = MagicMock()
        return cs

    def test_only_supplied_fields_appear_in_the_body(self):
        cs = self._service()
        patch_mock = cs._service.events.return_value.patch
        patch_mock.return_value.execute.return_value = {}

        asyncio.run(cs.update_event(event_id="evt_1", name="Morning sync"))

        body = patch_mock.call_args.kwargs["body"]
        assert body == {"summary": "Morning sync"}

    def test_all_none_call_issues_no_request_and_returns_true(self):
        cs = self._service()

        result = asyncio.run(cs.update_event(event_id="evt_1"))

        assert result is True
        cs._service.events.return_value.patch.assert_not_called()

    def test_patch_targets_the_configured_calendar(self):
        cs = self._service(calendar_id="cal_999")
        patch_mock = cs._service.events.return_value.patch
        patch_mock.return_value.execute.return_value = {}

        asyncio.run(cs.update_event(event_id="evt_1", start_time="2026-09-08T10:00:00"))

        assert patch_mock.call_args.kwargs["calendarId"] == "cal_999"
        assert patch_mock.call_args.kwargs["eventId"] == "evt_1"

    def test_http_error_returns_false_rather_than_raising(self):
        import httplib2
        from googleapiclient.errors import HttpError

        cs = self._service()
        resp = httplib2.Response({"status": 404})
        cs._service.events.return_value.patch.return_value.execute.side_effect = HttpError(
            resp, b"not found"
        )

        result = asyncio.run(cs.update_event(event_id="evt_1", name="X"))

        assert result is False


class TestEventSpanAndAlerts:
    """A caller chooses the span and the alerts; the defaults are only a floor.

    Mazkir hardcoded a 30-minute span and a single 10-minute popup on
    everything it created. A monthly pill reminder wants ~5 minutes and
    earlier warning; a meeting with a commute wants two alerts. The agent is
    the part that knows which, so it has to be able to say.
    """

    def _svc(self):
        from src.services.calendar_service import CalendarService
        cs = CalendarService(
            credentials_path=MagicMock(), token_path=MagicMock(),
            timezone="Asia/Jerusalem",
        )
        return cs

    def test_duration_minutes_sets_the_end(self):
        body = self._svc()._build_event(
            "Give Matia Milpro pill", "2026-10-11", "22:00", duration_minutes=5,
        )
        assert body["start"]["dateTime"].startswith("2026-10-11T22:00:00")
        assert body["end"]["dateTime"].startswith("2026-10-11T22:05:00")

    def test_explicit_end_time_still_wins_over_duration(self):
        body = self._svc()._build_event(
            "Standup", "2026-10-11", "10:00", end_time="10:45", duration_minutes=5,
        )
        assert body["end"]["dateTime"].startswith("2026-10-11T10:45:00")

    def test_falls_back_to_the_default_span(self):
        body = self._svc()._build_event("Thing", "2026-10-11", "09:00")
        assert body["end"]["dateTime"].startswith("2026-10-11T09:30:00")

    def test_reminders_are_the_ones_asked_for(self):
        body = self._svc()._build_event(
            "Dentist", "2026-10-11", "09:00", duration_minutes=30,
            remind_minutes_before=[1440, 60],
        )
        overrides = body["reminders"]["overrides"]
        assert body["reminders"]["useDefault"] is False
        assert [o["minutes"] for o in overrides] == [1440, 60]
        assert {o["method"] for o in overrides} == {"popup"}

    def test_empty_reminder_list_means_no_alerts_not_the_default_one(self):
        # Distinguishable from "said nothing": an explicit empty list is a
        # decision, and silently substituting the 10-minute default would
        # overrule it.
        body = self._svc()._build_event(
            "Quiet thing", "2026-10-11", "09:00", remind_minutes_before=[],
        )
        assert body["reminders"] == {"useDefault": False, "overrides": []}

    def test_unspecified_reminders_keep_the_existing_default(self):
        body = self._svc()._build_event("Thing", "2026-10-11", "09:00")
        assert body["reminders"]["overrides"] == [{"method": "popup", "minutes": 10}]


class TestNoDecorativePrefix:
    def _svc(self):
        from src.services.calendar_service import CalendarService
        return CalendarService(
            credentials_path=MagicMock(), token_path=MagicMock(),
            timezone="Asia/Jerusalem",
        )

    def test_a_plain_event_keeps_its_own_name(self):
        body = self._svc()._build_event("Bar hopping", "2026-09-12", "15:00")
        assert body["summary"] == "Bar hopping"
        assert "📅" not in body["summary"]

    def test_ownership_is_still_recorded(self):
        """The prefix was the only visible marker that Mazkir made the entry,
        so the description has to keep carrying that."""
        body = self._svc()._build_event("Bar hopping", "2026-09-12", "15:00")
        assert "Managed by Mazkir" in body["description"]

    def test_the_completion_marker_is_untouched(self):
        """`✅` is parsed back as completion, unlike `📅`. Removing the
        decorative prefix must not have gone near it."""
        import inspect
        from src.services.calendar_service import CalendarService
        src = inspect.getsource(CalendarService.mark_event_complete)
        assert "✅" in src


class TestTheDayWindowIsARealDay:
    """`datetime(y, m, d, tzinfo=pytz_zone)` does not mean midnight local.

    A pytz zone attached directly hands back its *first* historical offset —
    LMT, +02:21 for Asia/Jerusalem — so the query window ran from 00:39
    today to 00:39 tomorrow. Two consequences, both silent: an event living
    entirely inside a day's first 39 minutes was never returned, and one from
    the next day's first 39 minutes was returned under today's date.

    The first is worse than a missing row. `EventsService.reconcile` deletes a
    persisted event when the source that would have produced it answered
    without it — so a block Mazkir had itself created and synced was dropped
    from the day for being invisible to the very query meant to find it.
    """

    def _service(self):
        from src.services.calendar_service import CalendarService

        cs = CalendarService(
            credentials_path=MagicMock(),
            token_path=MagicMock(),
            timezone="Asia/Jerusalem",
            calendar_include=["Mazkir"],
        )
        cs._service = MagicMock()
        cs._initialized = True
        cs._calendar_id = "mazkir-cal-id"
        cs._service.calendarList().list().execute.return_value = {
            "items": [{"id": "mazkir-cal-id", "summary": "Mazkir"}]
        }
        cs._service.events().list().execute.return_value = {"items": []}
        return cs

    def _window(self, cs):
        call = next(
            c for c in cs._service.events().list.call_args_list
            if c.kwargs.get("calendarId")
        )
        return call.kwargs["timeMin"], call.kwargs["timeMax"]

    def test_the_window_starts_at_local_midnight(self):
        from datetime import date

        cs = self._service()
        asyncio.run(cs.get_todays_events(all_calendars=True, target_date=date(2026, 9, 13)))

        time_min, time_max = self._window(cs)
        assert time_min == "2026-09-13T00:00:00+03:00"
        assert time_max == "2026-09-14T00:00:00+03:00"

    def test_a_dst_boundary_still_spans_exactly_one_day(self):
        """Israel leaves DST on 2026-10-25, so that day is 25 hours long and
        adding a bare 24 hours would stop the window an hour early."""
        from datetime import date

        cs = self._service()
        asyncio.run(cs.get_todays_events(all_calendars=True, target_date=date(2026, 10, 25)))

        time_min, time_max = self._window(cs)
        assert time_min.startswith("2026-10-25T00:00:00")
        assert time_max.startswith("2026-10-26T00:00:00")
