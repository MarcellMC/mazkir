import datetime as dt
import json
from zoneinfo import ZoneInfo

from src.services.fast_lane.contract import Clause, ParseResult, TimeWords
from src.services.fast_lane.replay import (
    context_for, expected_parse, load_messages, score_row, skeleton_row, summarize,
)
from src.services.fast_lane.time_resolver import ClauseResolution, Placement

TZ = ZoneInfo("Asia/Jerusalem")


def turn(ts, text, skill=None, tools=(), reply="ok", chat=1):
    return json.dumps({"ts": ts, "chat_id": chat, "user_text": text, "skill": skill,
                       "tools": list(tools), "assistant_text": reply})


def test_load_messages_merges_a_hop_and_strips_prefixes(tmp_path):
    path = tmp_path / "agent-turns.jsonl"
    path.write_text("\n".join([
        turn("2026-09-08T00:48:10+0300", "Dog walk 23:15-23:35", "mazkir", reply="next_skill: time-management"),
        turn("2026-09-08T00:48:30+0300", "Dog walk 23:15-23:35", "time-management",
             tools=[{"name": "create_event", "params": {"name": "Dog walk", "start_time": "23:15"}}]),
        turn("2026-09-08T00:50:00+0300", '(replying to assistant: "Logged!") Ended at 00:30'),
        turn("2026-09-08T00:51:00+0300", "(photo: a.jpg) Dinner"),
        turn("2026-09-08T00:52:00+0300", "someone else", chat=2),
        "not json",
    ]))
    messages = load_messages(path, 1, TZ)
    assert [m.text for m in messages] == ["Dog walk 23:15-23:35", "Ended at 00:30", "Dinner"]
    assert messages[0].old_skill == "time-management"
    assert [t["name"] for t in messages[0].old_tools] == ["create_event"]
    assert messages[1].reply_to == "Logged!" and messages[1].reply_from == "assistant"
    assert messages[2].has_photo is True
    assert messages[0].id == "t0001"


def test_context_for_rebuilds_the_blocks_created_earlier(tmp_path):
    path = tmp_path / "agent-turns.jsonl"
    path.write_text("\n".join([
        turn("2026-09-07T23:40:00+0300", "Dog walk 23:15-23:35", tools=[
            {"name": "create_event", "params": {"name": "Dog walk", "start_time": "23:15", "end_time": "23:35"},
             "result_summary": {"event_id": "evt_1"}}]),
        turn("2026-09-08T00:50:00+0300", "Ended at 00:30"),
    ]))
    first, second = load_messages(path, 1, TZ)
    ctx = context_for(second, [first], (), {})
    assert ctx.now == dt.datetime(2026, 9, 8, 0, 50, tzinfo=TZ)
    [block] = ctx.blocks
    assert (block.id, block.name, block.start) == ("evt_1", "Dog walk", dt.datetime(2026, 9, 7, 23, 15, tzinfo=TZ))
    assert ctx.recent_turns == (("user", "Dog walk 23:15-23:35"), ("assistant", "ok"))


def test_skeleton_row_starts_unlabelled(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text(turn("2026-09-08T00:48:10+0300", "Dog walk 23:15-23:35"))
    [msg] = load_messages(path, 1, TZ)
    row = skeleton_row(msg)
    assert row["expected"] is None and row["unclear"] is False and row["id"] == "t0001"


def test_scoring_matches_clauses_by_op_and_name():
    now = dt.datetime(2026, 9, 8, 0, 48, tzinfo=TZ)
    expected = {"route": "fast", "fallthrough_skill": None, "clauses": [
        {"op": "log_block", "intent": "record", "stated": True, "name": "Dog walk",
         "expect": {"outcome": "fact", "start": "2026-09-07T23:15", "end": "2026-09-07T23:35"}}]}
    result = ParseResult((Clause("log_block", "record", True, "x", name="dog walk"),), None)
    placement = Placement(dt.datetime(2026, 9, 7, 23, 15, tzinfo=TZ), dt.datetime(2026, 9, 7, 23, 35, tzinfo=TZ),
                          "exact", "exact", dt.date(2026, 9, 7))
    score = score_row(expected, result, [ClauseResolution("fact", placement)], now)
    assert (score.route_ok, score.matched, score.fields_ok, score.placed_ok, score.outcome_ok) == (True, 1, 1, 1, 1)
    assert score.future_records == 0 and score.wrong_date == 0


def test_a_future_record_is_counted():
    now = dt.datetime(2026, 9, 3, 4, 17, tzinfo=TZ)
    result = ParseResult((Clause("log_block", "record", True, "x", name="Walk"),), None)
    placement = Placement(dt.datetime(2026, 9, 3, 15, 0, tzinfo=TZ), None, "exact", None, dt.date(2026, 9, 3))
    score = score_row({"route": "fast", "clauses": []}, result, [ClauseResolution("fact", placement)], now)
    assert score.future_records == 1


def test_expected_parse_feeds_the_resolver_the_labelled_words():
    parsed = expected_parse({"fallthrough_skill": None, "clauses": [
        {"op": "log_block", "intent": "record", "stated": True, "name": "Dog walk",
         "time": {"start": "23:15", "end": "23:35", "after": None}}]}, "Dog walk 23:15-23:35")
    assert parsed.clauses[0].time == TimeWords(start="23:15", end="23:35")


def test_summarize_guards_empty_denominators():
    summary = summarize([], [])
    assert summary["rows"] == 0 and summary["clause_recall"] is None


# --- Final fix F10 ---


def test_scoring_reads_expected_times_written_with_an_offset():
    # 01:15 local on the 8th is 22:15 UTC on the 7th: same instant, same local date.
    now = dt.datetime(2026, 9, 8, 1, 30, tzinfo=TZ)
    placement = Placement(dt.datetime(2026, 9, 8, 1, 15, tzinfo=TZ), dt.datetime(2026, 9, 8, 1, 25, tzinfo=TZ),
                          "exact", "exact", dt.date(2026, 9, 7))
    result = ParseResult((Clause("log_block", "record", True, "x", name="Dog walk"),), None)
    for start, end in (("2026-09-08T01:15:00+03:00", "2026-09-08T01:25:00+03:00"),
                       ("2026-09-07T22:15:00+00:00", "2026-09-07T22:25:00+00:00")):
        expected = {"route": "fast", "clauses": [{"op": "log_block", "name": "Dog walk",
                                                  "expect": {"outcome": "fact", "start": start, "end": end}}]}
        score = score_row(expected, result, [ClauseResolution("fact", placement)], now)
        assert (score.placed, score.placed_ok, score.wrong_date) == (1, 1, 0), start


def test_a_line_with_a_missing_or_bad_timestamp_is_skipped(tmp_path):
    path = tmp_path / "agent-turns.jsonl"
    path.write_text("\n".join([
        turn("2026-09-08T00:48:10+0300", "Dog walk 23:15-23:35"),
        json.dumps({"chat_id": 1, "user_text": "no timestamp"}),
        turn("yesterday-ish", "bad timestamp"),
        turn(None, "null timestamp"),
        turn("2026-09-08T00:50:00+0300", "Ended at 00:30"),
    ]))
    assert [m.text for m in load_messages(path, 1, TZ)] == ["Dog walk 23:15-23:35", "Ended at 00:30"]
