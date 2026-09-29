"""The owner's rules and the replay's findings, 2026-09-29 (spec §6.2, §6.4).

Each test is built from a kind of message the labelled history showed the
resolver getting wrong, in generic words.
"""

import datetime as dt
from zoneinfo import ZoneInfo

from src.services.fast_lane.time_resolver import ClauseTime, ResolverContext, resolve

TZ = ZoneInfo("Asia/Jerusalem")


def at(mo, d, h, mi):
    return dt.datetime(2026, mo, d, h, mi, tzinfo=TZ)


def ctx(now, **kw):
    return ResolverContext(now=now, **kw)


def log(name, start=None, end=None, duration=None, day=None, intent="record", stated=True,
        after=None, with_=None, op="log_block"):
    return ClauseTime(op=op, intent=intent, stated=stated, name=name, start=start, end=end,
                      duration=duration, day=day, after=after, with_=with_)


# --- 24-hour clocks: an hour without am/pm is read as written ---


def test_a_time_without_am_pm_is_the_24_hour_one_even_hours_later():
    walk, visit = resolve([log("Dog walk", "around 3:00", "3:20"), log("Visit friends", "3:30", "5:00")],
                          ctx(at(9, 3, 10, 0)))
    assert (walk.outcome, visit.outcome) == ("fact", "fact")
    assert (walk.placement.start, visit.placement.end) == (at(9, 3, 3, 0), at(9, 3, 5, 0))


def test_a_clear_start_is_never_given_a_twelve_hour_end():
    [r] = resolve([log("Reading", "09:30", "12:30")], ctx(at(9, 13, 22, 13)))
    assert r.outcome == "fact"
    assert (r.placement.start, r.placement.end) == (at(9, 13, 9, 30), at(9, 13, 12, 30))


def test_a_morning_list_is_read_as_the_morning():
    clauses = [log("Breakfast", "11:30", "12:30"), log("Free time", "12:30", "15:00"),
               log("Bike ride", "15:00", op="start_block", intent="plan")]
    breakfast, free, ride = resolve(clauses, ctx(at(9, 8, 14, 53)))
    assert (breakfast.outcome, free.outcome, ride.outcome) == ("fact", "fact", "plan")
    assert breakfast.placement.start == at(9, 8, 11, 30)
    assert ride.placement.start == at(9, 8, 15, 0)


def test_a_date_is_the_day_a_range_across_midnight_starts():
    [r] = resolve([log("Visit friends", "23:00", "00:30", day="August 31st")], ctx(at(9, 2, 4, 39)))
    assert r.outcome == "fact"
    assert (r.placement.start, r.placement.end) == (at(8, 31, 23, 0), at(9, 1, 0, 30))
