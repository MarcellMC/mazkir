"""Spec §7.1: what a record does to the blocks already in the ledger."""

import datetime as dt
from zoneinfo import ZoneInfo

from src.services.events_service import EventsService
from src.services.fast_lane.matching import day_blocks, find_target, match_record

TZ = ZoneInfo("Asia/Jerusalem")


def at(h, m, day=28):
    return dt.datetime(2026, 9, day, h, m, tzinfo=TZ)


def block(id, name, start, end, **kw):
    return {"id": id, "name": name, "start_time": start, "end_time": end, "source": "manual",
            "date": (start or end)[:10], **kw}


def test_an_open_block_of_the_same_activity_is_closed():
    m = match_record("Dog walk", (), at(13, 0), at(13, 30), [block("a", "Dog walk", "2026-09-28T13:00:00", None)], TZ)
    assert m.kind == "close" and m.block["id"] == "a"


def test_a_plan_of_the_same_activity_within_two_hours_is_confirmed():
    gym = block("g", "Gym", "2026-09-28T18:00:00", "2026-09-28T19:00:00", intent="plan")
    assert match_record("Gym", (), at(18, 30), at(19, 30), [gym], TZ).kind == "confirm"
    assert match_record("Gym", (), at(21, 30), at(22, 0), [gym], TZ).kind == "create"


def test_a_pending_calendar_entry_counts_as_a_plan():
    gym = block("g", "Gym", "2026-09-28T18:00:00", "2026-09-28T19:00:00", source="calendar")
    assert match_record("Gym", (), at(18, 10), at(19, 5), [gym], TZ).kind == "confirm"


def test_a_fact_overlapping_by_half_is_updated():
    walk = block("w", "Dog walk", "2026-09-28T13:00:00", "2026-09-28T13:30:00")
    assert match_record("Dog walk", (), at(13, 10), at(13, 40), [walk], TZ).kind == "update"
    assert match_record("Dog walk", (), at(13, 25), at(14, 25), [walk], TZ).kind == "create"


def test_an_open_block_of_another_activity_gets_a_proposal_to_close_it():
    work = block("k", "Work", "2026-09-28T09:00:00", None)
    m = match_record("Lunch", (), at(13, 0), at(13, 30), [work], TZ)
    assert m.kind == "also_close_other" and m.block["id"] == "k"


def test_a_record_over_sleep_waits_as_a_proposal():
    sleep = block("s", "Sleep", "2026-09-28T01:00:00", "2026-09-28T09:00:00")
    assert match_record("Reading", (), at(3, 0), at(3, 30), [sleep], TZ).kind == "sleep"


def test_the_activity_tag_counts_as_the_same_activity():
    dev = block("d", "Evening coding", "2026-09-28T20:00:00", None, activity="dev")
    assert match_record("Mazkir", ("dev",), at(20, 0), at(22, 0), [dev], TZ).kind == "close"


def test_dismissed_blocks_never_match(tmp_path):
    events = EventsService(tmp_path)
    kept = events.create_event("2026-09-28", "Dog walk", "2026-09-28T13:00:00", None)
    gone = events.create_event("2026-09-28", "Gym", "2026-09-28T18:00:00", None)
    events.update_event("2026-09-28", gone["id"], {"state": "dismissed"})
    assert [b["id"] for b in day_blocks(events, ["2026-09-28"])] == [kept["id"]]
    assert day_blocks(events, ["2026-09-28"])[0]["date"] == "2026-09-28"


def test_edit_targets_prefer_the_replied_message_then_the_open_day_then_today():
    gym_today = block("t", "Gym", "2026-09-28T18:00:00", "2026-09-28T19:00:00")
    gym_friday = block("f", "Gym", "2026-09-26T18:00:00", "2026-09-26T19:00:00")
    walk = block("w", "Dog walk", "2026-09-28T13:00:00", "2026-09-28T13:30:00")
    assert find_target("it", reply_text="✓ 13:00–13:30 Dog walk", selected=[],
                       today=[gym_today, walk])["id"] == "w"
    assert find_target("the gym", reply_text=None, selected=[gym_friday], today=[gym_today])["id"] == "f"
    assert find_target("the gym", reply_text=None, selected=[], today=[gym_today, walk])["id"] == "t"
    assert find_target("the gym", reply_text=None, selected=[], today=[]) is None
    assert find_target("it", reply_text=None, selected=[], today=[gym_today, walk]) is None


def test_a_target_with_an_article_still_finds_its_block():
    gym = block("g", "Gym", "2026-09-28T18:00:00", "2026-09-28T19:00:00")
    assert find_target("the gym", reply_text=None, selected=[], today=[gym])["id"] == "g"
    assert find_target("my dog walk", reply_text=None, selected=[],
                       today=[block("w", "Dog walk", "2026-09-28T13:00:00", None)])["id"] == "w"


def test_a_proposal_counts_as_a_plan():
    walk = block("w", "Dog walk", "2026-09-28T21:00:00", "2026-09-28T21:30:00", proposed=True)
    assert match_record("Dog walk", (), at(21, 10), at(21, 40), [walk], TZ).kind == "confirm"


def test_a_plan_moves_a_nearby_plan_of_its_activity_instead_of_adding_one():
    gym = block("g", "Gym", "2026-09-28T18:00:00", "2026-09-28T19:00:00", intent="plan")
    m = match_record("Gym", (), at(18, 30), at(19, 30), [gym], TZ, intent="plan")
    assert (m.kind, m.block["id"]) == ("move", "g")
    assert match_record("Gym", (), at(21, 0), at(22, 0), [gym], TZ, intent="plan").kind == "create"


def test_a_plan_never_closes_or_updates_a_record():
    open_walk = block("w", "Dog walk", "2026-09-28T13:00:00", None)
    done_walk = block("d", "Dog walk", "2026-09-28T20:00:00", "2026-09-28T20:30:00")
    assert match_record("Dog walk", (), at(20, 0), at(20, 30), [open_walk, done_walk], TZ, intent="plan").kind == "create"


def test_an_end_prefers_the_open_block_of_its_name():
    done = block("a", "Dog walk", "2026-09-28T00:42:00", "2026-09-28T01:12:00")
    running = block("b", "Dog walk", "2026-09-28T14:25:00", None)
    assert find_target("Dog walk", reply_text=None, selected=[], today=[done, running], prefer_open=True)["id"] == "b"


def test_a_block_on_a_coming_day_is_found_only_by_its_name():
    trip = block("t", "Camping trip", "2026-09-29T12:00:00", "2026-09-30T14:00:00", intent="plan")
    gym = block("g", "Gym", "2026-09-30T18:00:00", None)
    assert find_target("the camping trip", reply_text=None, selected=[], today=[], later=[trip, gym])["id"] == "t"
    assert find_target("the gym session", reply_text=None, selected=[], today=[], later=[gym]) is None
