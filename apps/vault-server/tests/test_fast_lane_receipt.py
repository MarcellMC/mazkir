# tests/test_fast_lane_receipt.py
"""Spec §8.2: what the receipt says, and which buttons each line gets."""

import datetime as dt

from src.services.fast_lane.receipt import (
    ran_summary, receipt_text, render_receipt, when_label,
)

NOW = dt.datetime(2026, 9, 28, 0, 48)


def line(id=0, **kw):
    base = {"id": id, "kind": "block", "outcome": "fact", "text": "Dog walk", "status": "done", "reason": "",
            "start": "2026-09-27T23:15:00", "end": "2026-09-27T23:35:00", "end_precision": "exact",
            "day": None, "date": "2026-09-27", "event_id": "evt_1",
            "calendar_sync": {"ok": False, "attempted": False, "reason": "deferred"},
            "habit": None, "habit_candidate": None, "place_text": None,
            "pending": [], "undo": [{"kind": "created"}]}
    base.update(kw)
    return base


def turn(*lines, created="2026-09-28T00:48:00+03:00"):
    return {"turn_id": "tabc12345", "chat_id": 1, "message_id": 7, "created_at": created,
            "text": "Dog walk 23:15-23:35", "lines": list(lines)}


def test_when_label():
    assert when_label("2026-09-27T23:15:00", "2026-09-27T23:35:00", NOW) == "yest 23:15–23:35"
    assert when_label("2026-09-28T09:00:00", "2026-09-28T09:30:00", NOW, "assumed") == "09:00–~09:30"
    assert when_label("2026-09-28T00:10:00", None, NOW) == "00:10→"
    assert when_label("2026-09-25T10:00:00", "2026-09-25T11:00:00", NOW) == "Fri 10:00–11:00"
    assert when_label("2026-08-07T10:00:00", "2026-08-07T11:00:00", NOW) == "7 Aug 10:00–11:00"
    assert when_label(None, None, NOW) == ""


def test_a_fact_line_with_its_edit_button_and_the_turns_undo():
    r = render_receipt(turn(line()), NOW)
    [l] = r["lines"]
    assert (l["glyph"], l["when"], l["text"], l["sync"]) == ("✓", "yest 23:15–23:35", "Dog walk", "⏳ calendar")
    assert l["buttons"] == [{"label": "✎", "data": "block:edit:2026-09-27:evt_1"}]
    assert r["undo"] == "rcpt:tabc12345:u:un" and r["open_question"] is None


def test_a_proposal_offers_approve_dismiss_and_edit():
    r = render_receipt(turn(line(outcome="proposal", status="pending", reason="overlaps Sleep")), NOW)
    [l] = r["lines"]
    assert l["glyph"] == "●" and l["reason"] == "overlaps Sleep"
    assert [b["data"] for b in l["buttons"]] == ["rcpt:tabc12345:0:ok", "rcpt:tabc12345:0:no",
                                                 "block:edit:2026-09-27:evt_1"]


def test_a_question_offers_no_buttons_and_asks_for_a_reply():
    open_q = line(kind="question", outcome="question", status="question", event_id=None, start=None, end=None,
                  calendar_sync=None, text="Watched a match", reason="no time given", undo=[])
    r = render_receipt(turn(open_q), NOW)
    assert r["lines"][0]["buttons"] == []
    assert r["open_question"] == "Watched a match · no time given. Reply with one."
    assert r["undo"] is None
    which = line(kind="question", outcome="question", status="question", event_id=None, calendar_sync=None,
                 text="Gym ended", reason="which block?", undo=[])
    assert render_receipt(turn(which), NOW)["open_question"] == "Gym ended · which block?"


def test_failed_lines_say_why_and_undone_lines_say_so():
    r = render_receipt(turn(line(status="failed", reason="No todo matches 'milk'"), line(1, status="undone")), NOW)
    assert r["lines"][0]["glyph"] == "✗" and r["lines"][0]["buttons"] == []
    assert r["lines"][1]["glyph"] == "↶"
    assert "No todo matches 'milk'" in receipt_text(r)


def test_the_habit_line_is_the_game_layer():
    habit = {"name": "Dog Walk", "completions_today": 2, "daily_target": 2, "tokens_earned": 5,
             "new_streak": 6, "longest_streak": 6, "prior": {"streak": 5, "longest_streak": 5}}
    [l] = render_receipt(turn(line(habit=habit)), NOW)["lines"]
    assert l["detail"] == "🎯 Dog Walk 2/2 · +5 🪙 · streak 6 · longest ever"


def test_a_fuzzy_habit_and_an_unknown_place_offer_a_tap():
    [l] = render_receipt(turn(line(habit_candidate={"path": "20-habits/dog-walk.md", "name": "Dog Walk"},
                                   place_text="the new cafe")), NOW)["lines"]
    assert {"label": "Dog Walk?", "data": "rcpt:tabc12345:0:hb"} in l["buttons"]
    assert {"label": "+ place", "data": "rcpt:tabc12345:0:pl"} in l["buttons"]


def test_undo_expires_after_a_day():
    r = render_receipt(turn(line(), created="2026-09-26T23:00:00+03:00"), NOW)
    assert r["undo"] is None


def test_a_todo_shows_its_day():
    [l] = render_receipt(turn(line(kind="todo", start=None, end=None, day="2026-09-29", event_id=None,
                                   calendar_sync=None, text="Buy milk")), NOW)["lines"]
    assert l["when"] == "tmrw" and l["buttons"] == []


def test_ran_summary_lists_what_ran_for_the_fallthrough_skill():
    assert ran_summary(turn(line(), line(1, status="failed")), NOW) == ["✓ yest 23:15–23:35 Dog walk (block)"]


def test_a_line_whose_block_is_gone_but_its_google_entry_stayed_offers_no_edit():
    # Undo removed the block and kept only the Google id it could not delete:
    # ✎ would open a block that no longer exists.
    orphaned = line(undo=[{"kind": "created", "ids": ["evt_1"], "google_orphan": "g1"}],
                    undo_note="can't undo: removed here, but its Google entry stays")
    [l] = render_receipt(turn(orphaned), NOW)["lines"]
    assert all(not b["data"].startswith("block:edit:") for b in l["buttons"])


TICK = {"name": "Dog Walk", "completions_today": 1, "daily_target": 2, "tokens_earned": 5,
        "new_streak": 3, "longest_streak": 6, "prior": {"streak": 2, "longest_streak": 6}}


def test_ran_summary_tells_the_skill_a_block_ticked_its_habit():
    """Final re-review: without it a mixed turn's skill ticks a 1/2 habit to 2/2."""
    assert ran_summary(turn(line(habit=TICK)), NOW) == [
        "✓ yest 23:15–23:35 Dog walk (block; habit already ticked: 🎯 Dog Walk 1/2 · +5 🪙 · streak 3)"]


def test_ran_summary_tells_the_skill_a_tick_habit_line_ticked_it():
    tick = line(kind="habit", start=None, end=None, event_id=None, calendar_sync=None, text="Dog Walk",
                habit=TICK)
    [said] = ran_summary(turn(tick), NOW)
    assert said.endswith("Dog Walk (habit; habit already ticked: 🎯 Dog Walk 1/2 · +5 🪙 · streak 3)")
