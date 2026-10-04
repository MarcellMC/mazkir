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


# --- Edits and chains ---


def edit(start=None, end=None, target=(None, None), intent="record", op="edit_block"):
    return ClauseTime(op=op, intent=intent, start=start, end=end, target_start=target[0], target_end=target[1])


def test_a_new_start_past_the_blocks_end_moves_the_whole_block():
    [r] = resolve([edit("15:20", target=(at(9, 2, 13, 15), at(9, 2, 13, 45)), intent="plan")],
                  ctx(at(9, 2, 15, 16)))
    assert (r.outcome, r.placement.start, r.placement.end) == ("plan", at(9, 2, 15, 20), at(9, 2, 15, 50))


def test_a_new_start_inside_the_block_moves_only_the_start():
    [r] = resolve([edit("04:00", target=(at(9, 29, 1, 13), at(9, 29, 8, 0)))], ctx(at(9, 29, 11, 14)))
    assert (r.outcome, r.placement.start, r.placement.end) == ("fact", at(9, 29, 4, 0), at(9, 29, 8, 0))


def test_a_clause_after_an_edit_with_only_an_end_starts_where_the_edit_ends():
    ended = edit(end="2:00", target=(at(9, 5, 23, 0), None), op="end_block")
    _, bar = resolve([ended, log("Bar", end="3:00", after=0)], ctx(at(9, 6, 1, 58)))
    assert (bar.outcome, bar.placement.start, bar.placement.end) == ("fact", at(9, 6, 2, 0), at(9, 6, 3, 0))


def test_a_clause_after_a_block_with_only_an_end_starts_where_that_block_ends():
    _, shower = resolve([log("Dog walk", "20:00", "20:30"), log("Shower", end="21:15", after=0)],
                        ctx(at(9, 6, 22, 0)))
    assert (shower.placement.start, shower.placement.end) == (at(9, 6, 20, 30), at(9, 6, 21, 15))


def test_before_that_places_a_clause_earlier_the_same_night():
    clauses = [log("Bar", "03:48", "04:17", day="September 7th"), log("Restaurant", "00:33", "02:35"),
               log("Cycling", after=1), log("Cycling from home", "00:17", "00:33")]
    bar, restaurant, cycling, from_home = resolve(clauses, ctx(at(9, 8, 0, 57)))
    assert [r.outcome for r in (bar, restaurant, cycling, from_home)] == ["fact"] * 4
    assert (bar.placement.start, restaurant.placement.start) == (at(9, 7, 3, 48), at(9, 7, 0, 33))
    assert cycling.placement.start == at(9, 7, 2, 35)
    assert (from_home.placement.start, from_home.placement.end) == (at(9, 7, 0, 17), at(9, 7, 0, 33))


def test_a_list_running_past_midnight_stays_in_order():
    walk, bar = resolve([log("Dog walk", "23:00", "23:30"), log("Bar", "00:10", "01:00")], ctx(at(9, 8, 2, 0)))
    assert (walk.placement.start, bar.placement.start) == (at(9, 7, 23, 0), at(9, 8, 0, 10))


def test_earlier_in_the_day_after_an_evening_block():
    gym, lunch = resolve([log("Gym", "18:00", "19:00"), log("Lunch", "13:00", "13:30")], ctx(at(9, 8, 20, 0)))
    assert (gym.placement.start, lunch.placement.start) == (at(9, 8, 18, 0), at(9, 8, 13, 0))
    assert lunch.outcome == "fact"


# --- An end with nothing open, and waking up ---


def ended(name, end, target=(None, None)):
    return ClauseTime(op="end_block", name=name, end=end, target_start=target[0], target_end=target[1])


def test_an_end_with_nothing_open_is_a_new_block_ending_then():
    [r] = resolve([ended("Gym", "16:50")], ctx(at(4, 8, 19, 47), typical_minutes={"gym": 70}))
    assert (r.outcome, r.placement.start, r.placement.end) == ("fact", at(4, 8, 15, 40), at(4, 8, 16, 50))
    assert r.placement.start_precision == "assumed"
    [now] = resolve([ended("Gym", "now")], ctx(at(4, 28, 20, 59)))
    assert (now.outcome, now.placement.end) == ("fact", at(4, 28, 20, 59))


def test_waking_with_no_sleep_open_proposes_a_sleep_from_your_bedtime():
    [r] = resolve([ended("Sleep", "11:00")], ctx(at(9, 8, 14, 53), bedtime=dt.time(1, 30)))
    assert (r.outcome, r.placement.start, r.placement.end) == ("proposal", at(9, 8, 1, 30), at(9, 8, 11, 0))
    assert "bedtime" in r.reason
    [late] = resolve([log("Sleep", end="08:00")], ctx(at(9, 8, 9, 0), bedtime=dt.time(23, 15)))
    assert (late.outcome, late.placement.start) == ("proposal", at(9, 7, 23, 15))


def test_waking_without_a_known_bedtime_assumes_eight_hours():
    [r] = resolve([ended("Sleep", "11:00")], ctx(at(9, 8, 14, 53)))
    assert (r.outcome, r.placement.start) == ("proposal", at(9, 8, 3, 0))


def test_a_sleep_with_its_length_given_is_not_a_guess():
    [r] = resolve([log("Sleep", end="08:00", duration="7 hours")], ctx(at(9, 8, 9, 0), bedtime=dt.time(23, 15)))
    assert (r.outcome, r.placement.start) == ("fact", at(9, 8, 1, 0))


# --- Plans with no time, windows, and one interval for several activities ---


def test_plans_with_no_time_are_proposed_back_to_back_from_now():
    clauses = [log("Meal prep", intent="plan"), log("Eating", intent="plan", after=0),
               log("Dog walk", intent="plan", after=1)]
    prep, eating, walk = resolve(clauses, ctx(at(9, 12, 21, 2), typical_minutes={"dog walk": 45}))
    assert [r.outcome for r in (prep, eating, walk)] == ["proposal"] * 3
    assert (prep.placement.start, prep.placement.end) == (at(9, 12, 21, 2), at(9, 12, 21, 32))
    assert (eating.placement.start, walk.placement.start, walk.placement.end) == (
        at(9, 12, 21, 32), at(9, 12, 22, 2), at(9, 12, 22, 47))


def test_a_list_to_schedule_later_is_proposed_in_order_without_links():
    laundry, plants = resolve([log("Hang laundry", intent="plan"), log("Water the plants", intent="plan")],
                              ctx(at(9, 13, 15, 20)))
    assert (laundry.placement.start, plants.placement.start) == (at(9, 13, 15, 20), at(9, 13, 15, 50))
    assert plants.outcome == "proposal"


def test_an_untimed_plan_after_a_timed_one_follows_it():
    gym, shower = resolve([log("Gym", "18:00", "19:00", intent="plan"), log("Shower", intent="plan", after=0)],
                          ctx(at(9, 13, 15, 0)))
    assert (gym.outcome, shower.outcome) == ("plan", "plan")
    assert shower.placement.start == at(9, 13, 19, 0)


def test_a_record_with_no_time_still_asks():
    [r] = resolve([log("Bar hopping")], ctx(at(9, 12, 20, 0)))
    assert r.outcome == "question"


def test_a_window_proposes_your_usual_length_at_its_start():
    [r] = resolve([log("Dog walk", "somewhere between 20:30", "22:30", intent="plan")],
                  ctx(at(5, 12, 16, 8), typical_minutes={"dog walk": 30}))
    assert (r.outcome, r.placement.start, r.placement.end) == ("proposal", at(5, 12, 20, 30), at(5, 12, 21, 0))
    assert "window" in r.reason


def test_a_window_shorter_than_the_activity_is_the_whole_window():
    [r] = resolve([log("Gym", "sometime between 18:00", "18:45", intent="plan")],
                  ctx(at(5, 12, 16, 8), typical_minutes={"gym": 70}))
    assert (r.placement.start, r.placement.end) == (at(5, 12, 18, 0), at(5, 12, 18, 45))


def test_several_activities_given_one_interval_ask_how_it_was_split():
    clauses = [log("Meal prep", "23:00", "00:00"), log("Eating", "23:00", "00:00"), log("Watching", "23:00", "00:00")]
    rs = resolve(clauses, ctx(at(9, 6, 0, 1)))
    assert [r.outcome for r in rs] == ["question"] * 3
    assert all("split" in r.reason for r in rs)
    assert rs[0].placement.start == at(9, 5, 23, 0)


def test_activities_running_alongside_share_the_interval_without_asking():
    eating, watching = resolve([log("Eating", "23:00", "00:00"), log("Watching", with_=0)], ctx(at(9, 6, 0, 1)))
    assert (eating.outcome, watching.outcome) == ("fact", "fact")


# --- Guards found by re-scoring the real parses ---


def test_a_plan_mentioned_in_passing_is_not_proposed():
    [r] = resolve([log("Picnic", day="today's", intent="plan", stated=False)], ctx(at(5, 21, 0, 23)))
    assert r.outcome == "question"


def test_a_plan_on_a_day_mazkir_cannot_read_is_not_proposed_today():
    [r] = resolve([log("Pill reminder", day="after 1 month", intent="plan")], ctx(at(9, 11, 3, 22)))
    assert r.outcome == "question"


def test_a_record_minutes_after_its_message_is_proposed_not_moved_to_yesterday():
    breakfast, ride = resolve([log("Breakfast", "11:30", "12:30"), log("Bike ride", "15:00", op="start_block")],
                              ctx(at(9, 8, 14, 53)))
    assert (breakfast.outcome, breakfast.placement.start) == ("fact", at(9, 8, 11, 30))
    assert (ride.outcome, ride.reason, ride.placement.start) == ("proposal", "starts after the message", at(9, 8, 15, 0))


def test_a_plan_minutes_before_its_message_is_proposed_not_moved_to_tomorrow():
    [r] = resolve([log("Gym", "20:50", intent="plan", op="start_block")], ctx(at(9, 8, 20, 55)))
    assert (r.outcome, r.placement.start) == ("proposal", at(9, 8, 20, 50))


def test_a_record_hours_after_its_message_is_still_yesterdays():
    [r] = resolve([log("Gym", "18:00", "19:00")], ctx(at(9, 8, 10, 0)))
    assert (r.outcome, r.placement.start) == ("fact", at(9, 7, 18, 0))


# --- A photo's caption ---


def test_a_caption_naming_an_activity_proposes_it_around_the_photo():
    [r] = resolve([log("Dinner")], ctx(at(9, 12, 20, 31), photo_at=at(9, 12, 20, 30)))
    assert (r.outcome, r.placement.start, r.placement.end) == ("proposal", at(9, 12, 20, 15), at(9, 12, 20, 45))
    assert "photo" in r.reason


def test_without_a_photo_an_untimed_record_still_asks():
    [r] = resolve([log("Dinner")], ctx(at(9, 12, 20, 31)))
    assert r.outcome == "question"


# --- From the messages of 2026-09-29 to 2026-10-04 ---


def test_a_plan_in_about_some_minutes_is_not_a_clock():
    [r] = resolve([log("Dog walk", "in about 15-20 mins", intent="plan")], ctx(at(9, 30, 1, 47)))
    assert (r.outcome, r.placement.start) == ("plan", at(9, 30, 2, 5))


def test_a_record_with_only_a_length_ends_at_the_message():
    [r] = resolve([log("Practice guitar", duration="10 mins")], ctx(at(9, 30, 18, 9)))
    assert (r.outcome, r.placement.start, r.placement.end) == ("fact", at(9, 30, 17, 59), at(9, 30, 18, 9))
    [y] = resolve([log("Practice guitar", duration="10 mins", day="yesterday")], ctx(at(9, 30, 18, 9)))
    assert y.outcome == "question"


def test_an_end_naming_its_own_day():
    [r] = resolve([log("Camping trip", "around 12", "around 14:00 on Saturday", day="Friday", intent="plan")],
                  ctx(at(9, 30, 18, 26)))
    assert (r.outcome, r.placement.start, r.placement.end) == ("plan", at(10, 2, 12, 0), at(10, 3, 14, 0))


def test_moving_a_block_a_day_later():
    [r] = resolve([ClauseTime(op="edit_block", shift="+1 day", intent="plan",
                              target_start=at(10, 1, 12, 0), target_end=at(10, 2, 14, 0))], ctx(at(9, 30, 18, 23)))
    assert (r.placement.start, r.placement.end) == (at(10, 2, 12, 0), at(10, 3, 14, 0))
