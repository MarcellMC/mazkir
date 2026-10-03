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


# --- A past start with nothing else, and time words the history used ---


def test_a_past_start_with_nothing_else_gets_your_usual_length():
    [r] = resolve([log("Lunch", "12:30")], ctx(at(9, 13, 15, 0)))
    assert (r.outcome, r.placement.start, r.placement.end) == ("fact", at(9, 13, 12, 30), at(9, 13, 13, 0))
    assert r.placement.end_precision == "assumed"
    [gym] = resolve([log("Gym", "14:20")], ctx(at(9, 13, 21, 45), typical_minutes={"gym": 70}))
    assert gym.placement.end == at(9, 13, 15, 30)


def test_a_start_whose_usual_length_has_not_passed_stays_open():
    [r] = resolve([log("Lunch", "14:45")], ctx(at(9, 13, 15, 0)))
    assert (r.placement.start, r.placement.end) == (at(9, 13, 14, 45), None)
    [now] = resolve([log("Dog walk", "now", op="start_block")], ctx(at(9, 13, 15, 0)))
    assert now.placement.end is None


def test_a_plan_with_only_a_start_stays_open():
    [r] = resolve([log("Gym", "20:50", intent="plan", op="start_block")], ctx(at(9, 13, 20, 45)))
    assert (r.outcome, r.placement.end) == ("plan", None)


def test_the_next_hour_is_an_hour():
    [r] = resolve([log("Dev session", "21:30", duration="the next hour")], ctx(at(9, 14, 22, 21)))
    assert r.placement.end == at(9, 14, 22, 30)


def test_just_before_midnight_on_the_previous_day():
    [r] = resolve([log("Cooking", end="just before midnight", day="the previous day")], ctx(at(9, 8, 0, 11)))
    assert (r.outcome, r.placement.start, r.placement.end) == ("fact", at(9, 7, 23, 29), at(9, 7, 23, 59))
    assert r.placement.end_precision == "approx"


def test_an_end_on_the_next_day():
    [r] = resolve([log("Camping trip", "around 12:00", "around 14:00 next day", day="01.10.2026",
                       intent="plan")], ctx(at(9, 29, 3, 54)))
    assert (r.outcome, r.placement.start, r.placement.end) == ("plan", at(10, 1, 12, 0), at(10, 2, 14, 0))


def test_a_date_range_with_times_ends_on_its_last_day():
    [r] = resolve([log("Camping trip", "12:00", "14:00", day="01.10.2026 - 02.10.2026", intent="plan")],
                  ctx(at(9, 29, 3, 54)))
    assert (r.placement.start, r.placement.end) == (at(10, 1, 12, 0), at(10, 2, 14, 0))


def test_a_date_range_without_times_covers_the_whole_days():
    [r] = resolve([log("Visit family", day="30.08 - 06.09", intent="plan")], ctx(at(8, 22, 13, 15)))
    assert (r.outcome, r.placement.start, r.placement.end) == ("plan", at(8, 30, 0, 0), at(9, 7, 0, 0))
