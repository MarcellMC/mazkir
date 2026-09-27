import datetime as dt
import json
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from src.services.fast_lane.context import (
    assemble_fast_context, clean_turn_text, typical_minutes,
)

TZ = ZoneInfo("Asia/Jerusalem")


def events_with(by_date):
    events = MagicMock()
    events.get_events.side_effect = lambda day: by_date.get(day, [])
    return events


def test_clean_turn_text_drops_tool_records():
    text = "Logged! 🐕\n\n[Tools I called this turn, as time-management:\n create_event(...) → ok]"
    assert clean_turn_text(text) == "Logged! 🐕"
    assert clean_turn_text("plain") == "plain"


def test_typical_minutes_is_the_median_per_name():
    by_date = {
        "2026-09-10": [{"name": "Dog walk", "start_time": "2026-09-10T23:00:00", "end_time": "2026-09-10T23:30:00"}],
        "2026-09-09": [{"name": "dog walk", "start_time": "2026-09-09T11:00:00", "end_time": "2026-09-09T11:20:00"},
                       {"name": "Dog walk", "start_time": "2026-09-09T22:00:00", "end_time": "2026-09-09T22:40:00"},
                       {"name": "Open", "start_time": "2026-09-09T22:00:00", "end_time": None}],
    }
    assert typical_minutes(events_with(by_date), dt.date(2026, 9, 10)) == {"dog walk": 30}


def test_assemble_reads_the_day_and_never_raises(tmp_path):
    memory = MagicMock()
    memory.load_conversation.return_value = {"messages": [
        {"role": "user", "content": "one"}, {"role": "assistant", "content": "two"},
        {"role": "user", "content": "three"}, {"role": "assistant", "content": "four [Tools I called this turn x]"},
        {"role": "user", "content": "five"},
    ]}
    by_date = {
        "2026-09-07": [{"id": "e1", "name": "Dog walk", "start_time": "2026-09-07T23:15:00",
                        "end_time": "2026-09-07T23:35:00"}],
        "2026-09-08": [{"id": "e2", "name": "Skipped", "state": "dismissed",
                        "start_time": "2026-09-08T00:10:00", "end_time": "2026-09-08T00:20:00"}],
    }
    vault = MagicMock()
    vault.read_daily_note.side_effect = RuntimeError("no note")   # a failing source costs context only
    vault.list_active_habits.return_value = [{"metadata": {"name": "Workout", "aliases": ["gym"]}}]
    places = tmp_path / "places.json"
    places.write_text(json.dumps({"places": [{"id": "p1", "name": "Home", "aliases": ["дом"]}]}))

    ctx = assemble_fast_context(
        text="#dev session 00:20-00:40", chat_id=1, now=dt.datetime(2026, 9, 8, 0, 48, tzinfo=TZ),
        memory=memory, events=events_with(by_date), vault=vault,
        reply_to={"text": "Logged!", "from": "assistant"},
        attachments=[{"type": "photo"}], places_path=places,
    )
    assert [t[1] for t in ctx.recent_turns] == ["two", "three", "four", "five"]
    assert [b.name for b in ctx.blocks] == ["Dog walk"]          # yesterday's, because it's before 05:00
    assert ctx.blocks[0].start == dt.datetime(2026, 9, 7, 23, 15, tzinfo=TZ)
    assert ctx.todos == ()
    assert ctx.habits[0].line() == "Workout (gym)"
    assert ctx.places == ("Home", "дом")
    assert ctx.hashtags == ("dev",)
    assert ctx.reply_to == "Logged!" and ctx.reply_from == "assistant"
    assert ctx.has_photo is True
