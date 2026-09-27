import datetime as dt
from zoneinfo import ZoneInfo

from src.services.fast_lane.time_resolver import (
    ClauseTime, ResolverContext, logical_date, resolve,
)

TZ = ZoneInfo("Asia/Jerusalem")


def at(y, mo, d, h, mi):
    return dt.datetime(y, mo, d, h, mi, tzinfo=TZ)


def ctx(now, **kw):
    return ResolverContext(now=now, **kw)


def log(name, start=None, end=None, duration=None, day=None, intent="record", stated=True,
        after=None, with_=None, op="log_block"):
    return ClauseTime(op=op, intent=intent, stated=stated, name=name, start=start, end=end,
                      duration=duration, day=day, after=after, with_=with_)


def test_logical_date_keeps_the_small_hours_with_last_night():
    assert logical_date(at(2026, 9, 8, 3, 0), 5) == dt.date(2026, 9, 7)
    assert logical_date(at(2026, 9, 8, 5, 0), 5) == dt.date(2026, 9, 8)


def test_a_block_reported_after_midnight_lands_on_the_evening_before():
    [r] = resolve([log("Dog walk", "23:15", "23:35")], ctx(at(2026, 9, 8, 0, 48)))
    assert r.outcome == "fact"
    assert (r.placement.start, r.placement.end) == (at(2026, 9, 7, 23, 15), at(2026, 9, 7, 23, 35))
    assert (r.placement.start_precision, r.placement.end_precision) == ("exact", "exact")
    assert r.placement.logical_date == dt.date(2026, 9, 7)


def test_twelve_hour_times_take_the_reading_still_going_on():
    # Sent 04:17: "around 3:00-3:20, then 3:30-5:00". Tonight's reading is
    # still running; yesterday afternoon's is 11 h older, so tonight wins.
    clauses = [log("Dog walk", "around 3:00", "3:20"), log("Visit friends", "3:30", "5:00")]
    walk, visit = resolve(clauses, ctx(at(2026, 9, 3, 4, 17)))
    assert (walk.outcome, visit.outcome) == ("fact", "fact")
    assert walk.placement.start == at(2026, 9, 3, 3, 0)
    assert walk.placement.start_precision == "approx"
    assert (visit.placement.start, visit.placement.end) == (at(2026, 9, 3, 3, 30), at(2026, 9, 3, 5, 0))
    assert visit.placement.end_precision == "expected"
    assert walk.placement.logical_date == dt.date(2026, 9, 2)


def test_the_same_message_hours_later_asks_which_it_was():
    clauses = [log("Dog walk", "around 3:00", "3:20"), log("Visit friends", "3:30", "5:00")]
    walk, visit = resolve(clauses, ctx(at(2026, 9, 3, 10, 0)))
    assert walk.outcome == visit.outcome == "question"
    starts = {p.start for p in walk.alternatives}
    assert starts == {at(2026, 9, 3, 3, 0), at(2026, 9, 2, 15, 0)}


def test_a_recent_time_beats_the_same_time_twelve_hours_earlier():
    [r] = resolve([log("Dog walk", "11:40", "12:00")], ctx(at(2026, 9, 14, 12, 11)))
    assert r.outcome == "fact"
    assert r.placement.start == at(2026, 9, 14, 11, 40)


def test_a_night_listed_in_order_including_a_plan():
    clauses = [
        log("Dog walk", "3:00", "3:30"), log("Bar", "3:30", "5:00"),
        log("Visit friends", "5:00", "7:20"),
        log("Sleep", "7:45", duration="7hr", intent="plan"),
    ]
    walk, bar, visit, sleep = resolve(clauses, ctx(at(2026, 9, 4, 7, 30)))
    assert [r.outcome for r in (walk, bar, visit)] == ["fact", "fact", "fact"]
    assert walk.placement.start == at(2026, 9, 4, 3, 0)
    assert visit.placement.end == at(2026, 9, 4, 7, 20)
    assert sleep.outcome == "plan"
    assert (sleep.placement.start, sleep.placement.end) == (at(2026, 9, 4, 7, 45), at(2026, 9, 4, 14, 45))
    assert sleep.placement.end_precision == "inferred"


def test_a_block_already_under_way_ends_as_expected():
    [r] = resolve([log("Gym", "21:30", "22:45")], ctx(at(2026, 8, 20, 21, 35)))
    assert r.outcome == "fact"
    assert r.placement.end_precision == "expected"


def test_started_now_is_an_open_block():
    clauses = [log("Dev session", "04:30", "05:15", duration="45 min"),
               log("Sleep", start="now", op="start_block")]
    dev, sleep = resolve(clauses, ctx(at(2026, 9, 6, 5, 16)))
    assert (dev.outcome, dev.placement.start) == ("fact", at(2026, 9, 6, 4, 30))
    assert sleep.placement.start == at(2026, 9, 6, 5, 16)
    assert sleep.placement.end is None
    assert sleep.placement.start_precision == "inferred"


def test_a_chain_with_no_clock_ends_now_and_runs_backwards():
    # "Finished eating, 30 mins. Then brushed my teeth 10 mins", sent 01:56.
    clauses = [log("Eating", end="now", duration="30 mins"),
               log("Brush teeth", duration="10 mins", after=0)]
    eat, teeth = resolve(clauses, ctx(at(2026, 9, 15, 1, 56)))
    assert (teeth.placement.start, teeth.placement.end) == (at(2026, 9, 15, 1, 46), at(2026, 9, 15, 1, 56))
    assert (eat.placement.start, eat.placement.end) == (at(2026, 9, 15, 1, 16), at(2026, 9, 15, 1, 46))
    assert eat.outcome == teeth.outcome == "fact"


def test_just_back_with_no_length_assumes_your_usual_one():
    [r] = resolve([log("Dog walk", end="now")],
                  ctx(at(2026, 8, 16, 16, 29), typical_minutes={"dog walk": 30}))
    assert (r.placement.start, r.placement.end) == (at(2026, 8, 16, 15, 59), at(2026, 8, 16, 16, 29))
    assert (r.placement.start_precision, r.placement.end_precision) == ("assumed", "inferred")


def test_eating_while_watching_shares_the_interval():
    clauses = [log("Eating", "23:30", "00:00"), log("Watching videos", with_=0)]
    eat, watch = resolve(clauses, ctx(at(2026, 9, 6, 0, 3)))
    assert (watch.placement.start, watch.placement.end) == (eat.placement.start, eat.placement.end)


def test_an_explicit_date_places_early_hours_on_that_calendar_day():
    [r] = resolve([log("Bar", "03:48", "04:17", day="September 7th")], ctx(at(2026, 9, 8, 0, 57)))
    assert (r.placement.start, r.placement.end) == (at(2026, 9, 7, 3, 48), at(2026, 9, 7, 4, 17))


def test_a_plan_on_a_weekday_is_the_next_one():
    [r] = resolve([log("Party", "19:00", day="Friday", intent="plan")], ctx(at(2026, 5, 12, 1, 29)))
    assert r.outcome == "plan"
    assert r.placement.start == at(2026, 5, 15, 19, 0)


def test_the_soonest_plan_reading_wins_when_the_other_is_far_later():
    [r] = resolve([log("Band practice", "10:00", "13:00", day="today", intent="plan")],
                  ctx(at(2026, 8, 12, 1, 53)))
    assert r.outcome == "plan"
    assert r.placement.start == at(2026, 8, 12, 10, 0)


def test_times_that_disagree_become_a_proposal():
    [r] = resolve([log("Dev", "04:30", "05:15", duration="30 min")], ctx(at(2026, 9, 6, 5, 16)))
    assert r.outcome == "proposal"
    assert "disagree" in r.reason


def test_a_block_longer_than_sixteen_hours_becomes_a_proposal():
    [r] = resolve([log("Nap", "13:00", "07:00")], ctx(at(2026, 9, 10, 8, 0)))
    assert r.outcome == "proposal"
    assert "16 hours" in r.reason


def test_no_time_at_all_asks():
    [r] = resolve([log("Bar hopping")], ctx(at(2026, 9, 12, 20, 0)))
    assert r.outcome == "question"


def test_a_passing_mention_is_a_proposal():
    [r] = resolve([log("Bar hopping", start="now", stated=False, op="start_block")],
                  ctx(at(2026, 9, 23, 0, 58)))
    assert r.outcome == "proposal"
    assert r.placement.start == at(2026, 9, 23, 0, 58)


def test_ops_without_a_time_pass_through():
    tick = ClauseTime(op="tick_habit", name="Workout")
    other = ClauseTime(op="other")
    assert [r.outcome for r in resolve([tick, other], ctx(at(2026, 9, 1, 12, 0)))] == ["fact", "fact"]
