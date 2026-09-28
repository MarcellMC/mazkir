import datetime as dt
import json
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import src.services.fast_lane.context as context_module
from src.services.fast_lane.context import (
    FastContext, assemble_fast_context, clean_turn_text, complete_fast_context, typical_minutes,
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
    assert typical_minutes(events_with(by_date), dt.date(2026, 9, 11)) == {"dog walk": 30}


def test_typical_minutes_reads_only_the_days_before():
    # The day itself is the future to a replayed message, and the file the
    # agent may be writing while the shadow reads (final fixes F6 and F10b).
    by_date = {
        "2026-09-10": [{"name": "Dog walk", "start_time": "2026-09-10T08:00:00", "end_time": "2026-09-10T09:00:00"}],
        "2026-09-09": [{"name": "Dog walk", "start_time": "2026-09-09T11:00:00", "end_time": "2026-09-09T11:20:00"}],
    }
    events = events_with(by_date)
    assert typical_minutes(events, dt.date(2026, 9, 10), days=3) == {"dog walk": 20}
    assert [c.args[0] for c in events.get_events.call_args_list] == ["2026-09-09", "2026-09-08", "2026-09-07"]


def test_the_snapshot_on_the_loop_reads_no_history_and_no_habits(monkeypatch):
    calls = []   # recorded, not raised: the snapshot's own guard would swallow a raise
    monkeypatch.setattr(context_module, "typical_minutes", lambda *a, **kw: calls.append(a) or {})
    vault = MagicMock()
    ctx = assemble_fast_context(
        text="Dog walk", chat_id=1, now=dt.datetime(2026, 9, 8, 12, 0, tzinfo=TZ),
        memory=MagicMock(load_conversation=MagicMock(return_value={"messages": []})),
        events=events_with({}), vault=vault,
    )
    assert calls == []
    assert not vault.list_active_habits.called
    assert ctx.habits == () and ctx.typical_minutes == {}


def test_complete_fast_context_adds_habits_and_history_to_a_new_context():
    by_date = {
        "2026-09-08": [{"name": "Dog walk", "start_time": "2026-09-08T08:00:00", "end_time": "2026-09-08T09:00:00"}],
        "2026-09-07": [{"name": "Dog walk", "start_time": "2026-09-07T11:00:00", "end_time": "2026-09-07T11:20:00"}],
    }
    vault = MagicMock()
    vault.list_active_habits.return_value = [{"metadata": {"name": "Workout", "aliases": ["gym"]}}]
    snapshot = FastContext(now=dt.datetime(2026, 9, 8, 12, 0, tzinfo=TZ), chat_id=1, text="Dog walk")
    ctx = complete_fast_context(snapshot, events=events_with(by_date), vault=vault)
    assert ctx.habits[0].line() == "Workout (gym)"
    assert ctx.typical_minutes == {"dog walk": 20}
    assert snapshot.habits == () and snapshot.typical_minutes == {}   # the snapshot itself is untouched


def test_complete_fast_context_never_raises():
    vault = MagicMock()
    vault.list_active_habits.side_effect = RuntimeError("disk")
    events = MagicMock()
    events.get_events.side_effect = RuntimeError("disk")
    snapshot = FastContext(now=dt.datetime(2026, 9, 8, 12, 0, tzinfo=TZ), chat_id=1, text="x")
    ctx = complete_fast_context(snapshot, events=events, vault=vault)
    assert ctx.habits == () and ctx.typical_minutes == {}


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
    assert ctx.habits == ()   # read later, in the shadow's thread (complete_fast_context)
    assert ctx.places == ("Home", "дом")
    assert ctx.hashtags == ("dev",)
    assert ctx.reply_to == "Logged!" and ctx.reply_from == "assistant"
    assert ctx.has_photo is True


def test_todos_distinguish_timed_from_untimed():
    vault = MagicMock()
    vault.read_daily_note.return_value = {"content": """## Tasks
- [ ] 09:00 — Team meeting
- [ ] Buy milk
- [x] Done thing
"""}
    ctx = assemble_fast_context(
        text="", chat_id=1, now=dt.datetime(2026, 9, 8, 0, 48, tzinfo=TZ),
        memory=MagicMock(load_conversation=MagicMock(return_value={"messages": []})),
        events=events_with({}), vault=vault,
    )
    assert ctx.todos == ("09:00 Team meeting", "Buy milk")
