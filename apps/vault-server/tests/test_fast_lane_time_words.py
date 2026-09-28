import datetime as dt

import pytest

from src.services.fast_lane.time_words import (
    Clock, DayRef, is_now, parse_clock, parse_day, parse_duration, parse_relative, parse_shift,
    weekday_date,
)


@pytest.mark.parametrize("text,expected", [
    ("23:15", Clock(23, 15, False, False)),
    ("3:00", Clock(3, 0, True, False)),        # 03:00 or 15:00
    ("around 3:00", Clock(3, 0, True, True)),
    ("~7:45", Clock(7, 45, True, True)),
    ("03:00", Clock(3, 0, False, False)),      # a leading zero means the 24-hour clock
    ("00:30", Clock(0, 30, False, False)),
    ("12:30", Clock(12, 30, True, False)),     # noon or half past midnight
    ("7pm", Clock(19, 0, False, False)),
    ("7:30 am", Clock(7, 30, False, False)),
    ("12am", Clock(0, 0, False, False)),
    ("15.00", Clock(15, 0, False, False)),
    ("at 3", Clock(3, 0, True, False)),
    ("3ish", Clock(3, 0, True, True)),
])
def test_parse_clock(text, expected):
    assert parse_clock(text) == expected


@pytest.mark.parametrize("text", [None, "", "now", "just returned", "25:00", "later", "finished"])
def test_parse_clock_rejects_non_clocks(text):
    assert parse_clock(text) is None


@pytest.mark.parametrize("text", ["now", "Just now", "just returned", "сейчас", "только что"])
def test_is_now(text):
    assert is_now(text)


@pytest.mark.parametrize("text,minutes", [
    ("30 mins", 30), ("45 min", 45), ("7hr", 420), ("1hr", 60), ("1h30", 90),
    ("1.5h", 90), ("2 hours", 120), ("90m", 90), ("half an hour", 30),
    ("an hour", 60), ("30 минут", 30), ("час", 60), (None, None), ("soon", None),
])
def test_parse_duration(text, minutes):
    assert parse_duration(text) == minutes


@pytest.mark.parametrize("text,minutes", [
    ("back 30 mins", -30), ("30 min earlier", -30), ("+15m", 15), ("-30m", -30),
    ("15 minutes later", 15), ("30 mins", None), (None, None),
])
def test_parse_shift(text, minutes):
    assert parse_shift(text) == minutes


TUESDAY = dt.date(2026, 9, 8)


@pytest.mark.parametrize("text,intent,expected", [
    ("yesterday", "record", DayRef("date", date=dt.date(2026, 9, 7))),
    ("today", "record", DayRef("date", date=TUESDAY)),
    ("tomorrow", "plan", DayRef("date", date=dt.date(2026, 9, 9))),
    ("вчера", "record", DayRef("date", date=dt.date(2026, 9, 7))),
    ("אתמול", "record", DayRef("date", date=dt.date(2026, 9, 7))),
    ("last night", "record", DayRef("night", night_offset=-1)),
    ("tonight", "plan", DayRef("night", night_offset=0)),
    ("вчера ночью", "record", DayRef("night", night_offset=-1)),
    ("September 7th", "record", DayRef("date", date=dt.date(2026, 9, 7))),
    ("7 Sep", "record", DayRef("date", date=dt.date(2026, 9, 7))),
    ("2026-09-07", "record", DayRef("date", date=dt.date(2026, 9, 7))),
    ("14.10", "plan", DayRef("date", date=dt.date(2026, 10, 14))),
    ("14.10", "record", DayRef("date", date=dt.date(2025, 10, 14))),   # a record is in the past
    ("Friday", "plan", DayRef("weekday", weekday=4)),
    ("пятницу", "plan", DayRef("weekday", weekday=4)),
    (None, "record", None),
    ("soonish", "record", None),
    ("February 29th", "plan", None),  # 2026-02-29 doesn't exist; year shift would land on 2027-02-29 (not a leap year)
    ("February 29th", "record", None),  # 2026-02-29 doesn't exist; year shift would land on 2025-02-29 (not a leap year)
])
def test_parse_day(text, intent, expected):
    assert parse_day(text, TUESDAY, intent) == expected


def test_weekday_date_points_forward_for_plans_and_back_for_records():
    assert weekday_date(4, dt.date(2026, 5, 12), "plan") == dt.date(2026, 5, 15)
    assert weekday_date(4, TUESDAY, "record") == dt.date(2026, 9, 4)
    assert weekday_date(1, TUESDAY, "record") == TUESDAY


# --- Final fix F1: relative times ("15 mins ago", "in 20 minutes") ---


@pytest.mark.parametrize("text,minutes", [
    ("15 mins ago", -15), ("10 minutes ago", -10), ("2 hours ago", -120), ("1h ago", -60),
    ("around 20 min ago", -20), ("in 20 minutes", 20), ("in 1 hour", 60), ("in 5 min", 5),
    ("15 минут назад", -15), ("2 часа назад", -120), ("через 20 минут", 20), ("через 1 час", 60),
    ("לפני 10 דקות", -10), ("לפני 2 שעות", -120), ("בעוד 20 דקות", 20), ("בעוד 1 שעה", 60),
])
def test_parse_relative(text, minutes):
    assert parse_relative(text) == dt.timedelta(minutes=minutes)


@pytest.mark.parametrize("text", [None, "", "now", "15:00", "at 3", "30 mins", "in the evening", "back 30 mins"])
def test_parse_relative_needs_a_direction_and_a_number(text):
    assert parse_relative(text) is None


@pytest.mark.parametrize("text", [
    "15 mins ago", "in 20 minutes", "10 minutes ago", "2h ago", "30 минут назад", "через 20 минут",
    "לפני 10 דקות", "בעוד 20 דקות", "20 min",
])
def test_parse_clock_never_reads_a_duration_as_a_clock(text):
    assert parse_clock(text) is None
