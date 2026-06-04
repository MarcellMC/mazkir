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
