"""Tests for NotesService."""
import datetime
import pytest
from src.services.notes_service import derive_kind, derive_sort_key


class TestDerive:
    def test_daily_kind_and_sort_key(self):
        assert derive_kind("2026-05-21") == "daily"
        assert derive_sort_key("2026-05-21") == "2026-05-21"

    def test_weekly_kind(self):
        assert derive_kind("2022-W34") == "weekly"

    def test_weekly_sort_key_is_last_day_of_iso_week(self):
        # ISO week 34 of 2022: Monday 2022-08-22 .. Sunday 2022-08-28
        assert derive_sort_key("2022-W34") == "2022-08-28"

    def test_weekly_sort_key_week_one(self):
        # ISO week 1 of 2023: ends Sunday 2023-01-08
        assert derive_sort_key("2023-W01") == "2023-01-08"

    def test_unknown_stem_is_daily_fallback(self):
        # Non-matching names sort by themselves, treated as daily
        assert derive_kind("random-note") == "daily"
        assert derive_sort_key("random-note") == "random-note"
