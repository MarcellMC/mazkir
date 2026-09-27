import datetime as dt

import pytest

from src.services.fast_lane.time_words import (
    Clock, DayRef, is_now, parse_clock, parse_day, parse_duration, parse_shift, weekday_date,
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
