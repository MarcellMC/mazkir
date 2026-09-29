"""A1's carry-overs, a todo's day, and the one way an instant reaches the ledger."""

import datetime as dt
from zoneinfo import ZoneInfo

from src.services.fast_lane.time_resolver import ClauseTime, ResolverContext, resolve, to_wire
from src.services.fast_lane.time_words import Clock, parse_clock, parse_relative

TZ = ZoneInfo("Asia/Jerusalem")


def ctx(h, m, day=28):
    return ResolverContext(now=dt.datetime(2026, 9, day, h, m, tzinfo=TZ))


def at(h, m, day=28):
    return dt.datetime(2026, 9, day, h, m, tzinfo=TZ)


def test_a_clause_with_its_own_relative_start_ignores_its_after_link():
    walk = ClauseTime(op="log_block", name="Walk", start="13:00", end="13:30")
    shower = ClauseTime(op="log_block", name="Shower", start="10 min ago", after=0)
    _, r = resolve([walk, shower], ctx(14, 0))
    assert r.outcome == "fact" and r.placement.start == at(13, 50)


def test_an_after_link_to_an_edit_starts_where_the_edit_ends():
    end_walk = ClauseTime(op="end_block", target_start=at(13, 0), end="20 min ago")
    shower = ClauseTime(op="log_block", name="Shower", duration="10 min", after=0)
    edit, r = resolve([end_walk, shower], ctx(14, 30))
    assert edit.placement.end == at(14, 10)
    assert (r.placement.start, r.placement.end) == (at(14, 10), at(14, 20))
    assert r.outcome == "fact"


def test_russian_oclock_is_a_clock_not_a_length():
    assert parse_clock("в 3 часа") == Clock(3, 0, ambiguous=True, hedged=False)
    assert parse_clock("at 11 o'clock").hour == 11
    assert parse_clock("3 часа") is None          # a length stays a length


def test_amounts_written_as_words():
    minutes = lambda n: dt.timedelta(minutes=n)
    assert parse_relative("an hour ago") == minutes(-60)
    assert parse_relative("half an hour ago") == minutes(-30)
    assert parse_relative("in an hour") == minutes(60)
    assert parse_relative("час назад") == minutes(-60)
    assert parse_relative("через полчаса") == minutes(30)
    assert parse_relative("לפני שעה") == minutes(-60)
    assert parse_relative("לפני חצי שעה") == minutes(-30)


def test_a_todo_for_tomorrow_names_its_day():
    todo = ClauseTime(op="add_todo", intent="plan", name="Buy milk", day="tomorrow")
    [r] = resolve([todo], ctx(21, 0))
    assert r.outcome == "fact" and r.placement.logical_date == dt.date(2026, 9, 29)
    assert r.placement.start is None and r.placement.end is None


def test_a_todo_without_a_day_has_no_placement():
    [r] = resolve([ClauseTime(op="add_todo", intent="plan", name="Buy milk")], ctx(21, 0))
    assert r.placement is None


def test_to_wire_writes_local_wall_clock_without_an_offset():
    assert to_wire(at(14, 5)) == "2026-09-28T14:05:00"


def test_to_wire_turns_a_time_the_clocks_skipped_into_the_real_moment():
    # 2026-03-27: Israel's clocks jump from 02:00 to 03:00, so 02:30 was never shown.
    assert to_wire(dt.datetime(2026, 3, 27, 2, 30, tzinfo=TZ)) == "2026-03-27T03:30:00"
