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


def test_small_hours_are_tonight_and_a_block_still_going_on_ends_as_expected():
    # Sent 04:17: "around 3:00-3:20, then 3:30-5:00". The hours are 24-hour,
    # so this is tonight, and the visit is still running.
    clauses = [log("Dog walk", "around 3:00", "3:20"), log("Visit friends", "3:30", "5:00")]
    walk, visit = resolve(clauses, ctx(at(2026, 9, 3, 4, 17)))
    assert (walk.outcome, visit.outcome) == ("fact", "fact")
    assert walk.placement.start == at(2026, 9, 3, 3, 0)
    assert walk.placement.start_precision == "approx"
    assert (visit.placement.start, visit.placement.end) == (at(2026, 9, 3, 3, 30), at(2026, 9, 3, 5, 0))
    assert visit.placement.end_precision == "expected"
    assert walk.placement.logical_date == dt.date(2026, 9, 2)


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


# --- Fix round 1: I1-I4 (spec §6.2 rules 3 and 9, §6.4 refinement) ---


def test_an_unambiguous_clock_does_not_get_a_24h_away_reading():
    [r] = resolve([log("Gym", "14:00", "15:30")], ctx(at(2026, 9, 20, 21, 0)))
    assert r.outcome == "fact"
    assert (r.placement.start, r.placement.end) == (at(2026, 9, 20, 14, 0), at(2026, 9, 20, 15, 30))


def test_a_plan_with_an_unambiguous_clock_does_not_ask_today_vs_tomorrow():
    [r] = resolve([log("Party", "20:00", intent="plan")], ctx(at(2026, 9, 20, 2, 0)))
    assert r.outcome == "plan"
    assert r.placement.start == at(2026, 9, 20, 20, 0)


def test_a_start_end_pair_seeded_on_its_end_survives_an_ambiguous_start():
    [r] = resolve([log("Work", "9:00", "17:00")], ctx(at(2026, 9, 20, 17, 30)))
    assert r.outcome == "fact"
    assert (r.placement.start, r.placement.end) == (at(2026, 9, 20, 9, 0), at(2026, 9, 20, 17, 0))


def test_a_short_ambiguous_start_end_pair_is_not_offered_a_bogus_alternative():
    [r] = resolve([log("Lunch", "12:30", "13:00")], ctx(at(2026, 9, 20, 13, 15)))
    assert r.outcome == "fact"
    assert (r.placement.start, r.placement.end) == (at(2026, 9, 20, 12, 30), at(2026, 9, 20, 13, 0))


def test_the_correct_reading_is_offered_even_hours_later():
    [r] = resolve([log("Work", "8:00", "17:00")], ctx(at(2026, 9, 20, 23, 0)))
    assert r.outcome == "fact"
    assert (r.placement.start, r.placement.end) == (at(2026, 9, 20, 8, 0), at(2026, 9, 20, 17, 0))


def test_a_now_start_with_an_end_clock_is_not_ignored():
    [r] = resolve([log("Meeting", start="now", end="18:00", op="start_block")],
                  ctx(at(2026, 9, 20, 14, 0)))
    assert r.outcome == "fact"
    assert r.placement.start == at(2026, 9, 20, 14, 0)
    assert r.placement.start_precision == "inferred"
    assert r.placement.end == at(2026, 9, 20, 18, 0)
    assert r.placement.end_precision == "expected"


def test_a_now_start_on_the_tail_of_a_chain_anchors_it():
    clauses = [log("Eating", duration="30 mins"), log("Dishes", start="now", after=0)]
    eat, dishes = resolve(clauses, ctx(at(2026, 9, 20, 20, 0)))
    assert dishes.placement.start == at(2026, 9, 20, 20, 0)
    assert dishes.placement.end is None
    assert (eat.placement.start, eat.placement.end) == (at(2026, 9, 20, 19, 30), at(2026, 9, 20, 20, 0))


def edit(op="edit_block", start=None, end=None, shift=None, target=(None, None), stated=True):
    return ClauseTime(op=op, stated=stated, start=start, end=end, shift=shift,
                      target_start=target[0], target_end=target[1])


def test_an_end_after_midnight_is_the_nearest_one_after_the_start():
    # "Ended at 00:30" for a walk that started 23:15: 75 minutes, not 25 hours.
    [r] = resolve([edit("end_block", end="00:30", target=(at(2026, 9, 7, 23, 15), at(2026, 9, 7, 23, 35)))],
                  ctx(at(2026, 9, 8, 0, 50)))
    assert r.outcome == "fact"
    assert (r.placement.start, r.placement.end) == (at(2026, 9, 7, 23, 15), at(2026, 9, 8, 0, 30))
    assert (r.placement.start_precision, r.placement.end_precision) == (None, "exact")


def test_back_home_now_closes_the_block():
    [r] = resolve([edit("end_block", end="now", target=(at(2026, 9, 9, 5, 0), None))],
                  ctx(at(2026, 9, 9, 5, 30)))
    assert r.placement.end == at(2026, 9, 9, 5, 30)


def test_a_shift_moves_both_ends():
    [r] = resolve([edit(shift="back 30 mins", target=(at(2026, 8, 16, 16, 0), at(2026, 8, 16, 16, 30)))],
                  ctx(at(2026, 8, 16, 16, 31)))
    assert (r.placement.start, r.placement.end) == (at(2026, 8, 16, 15, 30), at(2026, 8, 16, 16, 0))


def test_new_times_land_nearest_the_block_they_replace():
    target = (at(2026, 9, 13, 1, 0), at(2026, 9, 13, 8, 0))
    [r] = resolve([edit(start="01:35", end="06:35", target=target)], ctx(at(2026, 9, 13, 8, 5)))
    assert (r.placement.start, r.placement.end) == (at(2026, 9, 13, 1, 35), at(2026, 9, 13, 6, 35))


def test_an_edit_without_its_block_asks_which():
    [r] = resolve([edit(shift="back 30 mins")], ctx(at(2026, 9, 1, 12, 0)))
    assert (r.outcome, r.reason) == ("question", "which block?")


def test_a_rename_needs_no_placement():
    [r] = resolve([edit(target=(at(2026, 9, 14, 9, 27), at(2026, 9, 14, 11, 2)))], ctx(at(2026, 9, 14, 11, 8)))
    assert r.outcome == "fact"
    assert r.placement is None


# --- Fix round 1: edits must reapply rule 1/2 validity ---


def test_an_edit_landing_after_the_message_is_a_proposal():
    [r] = resolve([edit(start="9", target=(at(2026, 9, 10, 8, 50), None))], ctx(at(2026, 9, 10, 8, 55)))
    assert (r.outcome, r.reason) == ("proposal", "starts after the message")
    assert r.placement.start == at(2026, 9, 10, 9, 0)


def test_a_plan_edit_landing_before_the_message_is_a_proposal():
    c = ClauseTime(op="edit_block", intent="plan", start="10:00",
                   target_start=at(2026, 9, 10, 11, 0), target_end=at(2026, 9, 10, 12, 0))
    [r] = resolve([c], ctx(at(2026, 9, 10, 10, 30)))
    assert (r.outcome, r.reason) == ("proposal", "starts before the message")


def test_an_edited_end_crossing_midnight_is_too_long_not_ends_before_it_starts():
    [r] = resolve([edit(end="08:00", target=(at(2026, 9, 10, 9, 0), at(2026, 9, 10, 10, 0)))],
                  ctx(at(2026, 9, 10, 12, 0)))
    assert (r.outcome, r.reason) == ("proposal", "longer than 16 hours")


# --- Final fix F1: relative times sit at now + delta, never on a clock ---


def test_a_start_some_minutes_ago_is_placed_from_the_message_time():
    [r] = resolve([log("Dog walk", start="15 mins ago", op="start_block")], ctx(at(2026, 9, 20, 16, 0)))
    assert r.outcome == "fact"
    assert (r.placement.start, r.placement.end) == (at(2026, 9, 20, 15, 45), None)
    assert r.placement.start_precision == "inferred"
    assert r.placement.logical_date == dt.date(2026, 9, 20)


def test_a_plan_in_some_minutes_starts_after_the_message():
    [r] = resolve([log("Dog walk", start="in 20 minutes", intent="plan", op="start_block")],
                  ctx(at(2026, 9, 20, 14, 0)))
    assert r.outcome == "plan"
    assert r.placement.start == at(2026, 9, 20, 14, 20)
    assert r.placement.start_precision == "inferred"


def test_minutes_ago_never_asks_which_twelve_hour_reading():
    [r] = resolve([log("Dog walk", start="10 minutes ago", duration="10 min")], ctx(at(2026, 9, 20, 14, 0)))
    assert r.outcome == "fact"
    assert (r.placement.start, r.placement.end) == (at(2026, 9, 20, 13, 50), at(2026, 9, 20, 14, 0))
    assert r.alternatives == ()


def test_an_end_some_minutes_ago_is_placed_from_the_message_time():
    [r] = resolve([log("Dog walk", end="10 minutes ago", duration="30 mins")], ctx(at(2026, 9, 20, 14, 0)))
    assert r.outcome == "fact"
    assert (r.placement.start, r.placement.end) == (at(2026, 9, 20, 13, 20), at(2026, 9, 20, 13, 50))
    assert (r.placement.start_precision, r.placement.end_precision) == ("inferred", "inferred")


def test_a_record_in_some_minutes_is_flagged_not_placed_as_a_fact():
    [r] = resolve([log("Dog walk", start="in 20 minutes", op="start_block")], ctx(at(2026, 9, 20, 14, 0)))
    assert (r.outcome, r.reason) == ("proposal", "starts after the message")
    assert r.placement.start == at(2026, 9, 20, 14, 20)


def test_russian_minutes_ago():
    [r] = resolve([log("Dog walk", start="15 минут назад", op="start_block")], ctx(at(2026, 9, 20, 16, 0)))
    assert (r.outcome, r.placement.start) == ("fact", at(2026, 9, 20, 15, 45))


def test_hebrew_in_some_minutes():
    [r] = resolve([log("Dog walk", start="בעוד 20 דקות", intent="plan", op="start_block")],
                  ctx(at(2026, 9, 20, 14, 0)))
    assert (r.outcome, r.placement.start) == ("plan", at(2026, 9, 20, 14, 20))


def test_an_edit_ended_some_minutes_ago():
    [r] = resolve([edit("end_block", end="10 minutes ago", target=(at(2026, 9, 20, 13, 0), None))],
                  ctx(at(2026, 9, 20, 14, 0)))
    assert r.outcome == "fact"
    assert r.placement.end == at(2026, 9, 20, 13, 50)
    assert r.placement.end_precision == "inferred"


# --- Final fix F2: a night word keeps only readings inside that night ---


def test_last_night_across_midnight_has_one_reading():
    # Sent 10:00 on 20 Sep: the 23:00 start can only be the night of the 19th.
    [r] = resolve([log("Visit friends", "23:00", "1:00", day="last night")], ctx(at(2026, 9, 20, 10, 0)))
    assert r.outcome == "fact"
    assert (r.placement.start, r.placement.end) == (at(2026, 9, 19, 23, 0), at(2026, 9, 20, 1, 0))
    assert r.alternatives == ()
    assert r.placement.logical_date == dt.date(2026, 9, 19)


def test_last_night_at_two_is_two_in_the_morning():
    [r] = resolve([log("Dog walk", "2", day="last night")], ctx(at(2026, 9, 20, 10, 0)))
    assert r.outcome == "fact"
    assert r.placement.start == at(2026, 9, 20, 2, 0)
    assert r.alternatives == ()


def test_tonight_at_eleven_is_eleven_at_night():
    [r] = resolve([log("Dog walk", "11", day="tonight", intent="plan")], ctx(at(2026, 9, 20, 15, 0)))
    assert (r.outcome, r.placement.start) == ("plan", at(2026, 9, 20, 23, 0))


def test_tonight_at_three_is_not_three_this_afternoon():
    [r] = resolve([log("Dog walk", "3", day="tonight", intent="plan")], ctx(at(2026, 9, 20, 15, 0)))
    assert (r.outcome, r.placement.start) == ("plan", at(2026, 9, 21, 3, 0))


def test_a_night_that_ends_after_the_boundary_is_still_that_night():
    # Sleep runs past 05:00; the night word binds the start, not the end.
    [r] = resolve([log("Sleep", "23:00", "9:00", day="last night")], ctx(at(2026, 9, 20, 10, 0)))
    assert r.outcome == "fact"
    assert (r.placement.start, r.placement.end) == (at(2026, 9, 19, 23, 0), at(2026, 9, 20, 9, 0))


# --- Final fix F4: a day-only or length-only edit gets a real placement ---


def test_moving_a_block_to_tomorrow_keeps_its_clock_times():
    c = ClauseTime(op="edit_block", intent="plan", day="tomorrow",
                   target_start=at(2026, 9, 20, 15, 0), target_end=at(2026, 9, 20, 15, 30))
    [r] = resolve([c], ctx(at(2026, 9, 20, 10, 0)))
    assert r.outcome == "plan"
    assert (r.placement.start, r.placement.end) == (at(2026, 9, 21, 15, 0), at(2026, 9, 21, 15, 30))
    assert (r.placement.start_precision, r.placement.end_precision) == (None, None)
    assert r.placement.logical_date == dt.date(2026, 9, 21)


def test_a_record_moved_past_the_message_is_a_proposal():
    c = ClauseTime(op="edit_block", day="tomorrow",
                   target_start=at(2026, 9, 20, 9, 0), target_end=at(2026, 9, 20, 9, 30))
    [r] = resolve([c], ctx(at(2026, 9, 20, 10, 0)))
    assert (r.outcome, r.reason) == ("proposal", "starts after the message")
    assert r.placement.start == at(2026, 9, 21, 9, 0)


def test_changing_only_the_length_keeps_the_start():
    c = ClauseTime(op="edit_block", duration="45 min",
                   target_start=at(2026, 9, 20, 9, 0), target_end=at(2026, 9, 20, 9, 30))
    [r] = resolve([c], ctx(at(2026, 9, 20, 10, 0)))
    assert r.outcome == "fact"
    assert (r.placement.start, r.placement.end) == (at(2026, 9, 20, 9, 0), at(2026, 9, 20, 9, 45))
    assert (r.placement.start_precision, r.placement.end_precision) == (None, "inferred")


def test_a_day_or_length_edit_without_its_block_asks_which():
    for c in (ClauseTime(op="edit_block", day="tomorrow"), ClauseTime(op="edit_block", duration="45 min")):
        [r] = resolve([c], ctx(at(2026, 9, 20, 10, 0)))
        assert (r.outcome, r.reason) == ("question", "which block?")


def test_a_length_edit_on_a_block_with_no_start_asks():
    c = ClauseTime(op="edit_block", duration="45 min", target_end=at(2026, 9, 20, 9, 30))
    [r] = resolve([c], ctx(at(2026, 9, 20, 10, 0)))
    assert r.outcome == "question"
    assert r.placement is None and r.reason


# --- Final fix F7: the run-together typo "06:35:07:35" is a start and an end ---


def test_a_run_together_start_and_end_is_split():
    [r] = resolve([log("Reading", "06:35:07:35")], ctx(at(2026, 9, 20, 8, 0)))
    assert r.outcome == "fact"
    assert (r.placement.start, r.placement.end) == (at(2026, 9, 20, 6, 35), at(2026, 9, 20, 7, 35))
    assert (r.placement.start_precision, r.placement.end_precision) == ("exact", "exact")


def test_a_clock_start_with_an_end_pinned_to_the_message_is_today():
    # Both day readings end at the same instant, so recency ties; the one
    # 24 h too long must not win the tie and turn a plain log into a proposal.
    for end in ("15 mins ago", "now"):
        [r] = resolve([log("Gym", "13:00", end)], ctx(at(2026, 9, 20, 14, 0)))
        assert r.outcome == "fact", end
        assert r.placement.start == at(2026, 9, 20, 13, 0)
