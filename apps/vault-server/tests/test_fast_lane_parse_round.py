"""The parse round after the first paid replay (2026-09-29).

The model invented `tags` without end ("query", "request", …) until it ran
out of tokens, on messages as short as "3": 22 of 276 parses failed that way.
Tags now come from the clause's own words, in code. The parse also sees the
same skill catalog the router reads, and the replay scores names fuzzily and
can re-run chosen rows.
"""

import datetime as dt
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from src.services.fast_lane.context import FastContext, skills_of
from src.services.fast_lane.contract import PARSE_SCHEMA, validate
from src.services.fast_lane.parse import build_user_content
from src.services.fast_lane.replay import Message, _blocks_before, _same_name, select_rows

TZ = ZoneInfo("Asia/Jerusalem")
NOW = dt.datetime(2026, 9, 28, 20, 45, tzinfo=TZ)


def item(evidence, op="log_block", **kw):
    base = {"op": op, "intent": "record", "stated": True, "evidence": evidence, "name": "x", "target": None,
            "place": None, "people": [], "project": None, "time": None}
    return {**base, **kw}


def test_the_model_is_not_asked_for_tags():
    clause = PARSE_SCHEMA["properties"]["clauses"]["items"]
    assert "tags" not in clause["properties"] and "tags" not in clause["required"]


def test_tags_come_from_the_clauses_own_words():
    message = "Had a 45 min #dev-session, then #buy milk"
    result = validate({"clauses": [item("Had a 45 min #dev-session"), item("#buy milk", op="add_todo")],
                       "fallthrough_skill": None}, message)
    assert result.clauses[0].tags == ("dev-session", "dev")
    assert result.clauses[1].tags == ("buy",)


def test_tags_the_model_sends_anyway_are_ignored():
    result = validate({"clauses": [item("list my tasks", op="other", tags=["query", "request", "priorities"])],
                       "fallthrough_skill": "time-management"}, "list my tasks")
    assert result.clauses[0].tags == ()


def test_the_parse_reply_is_capped_short():
    from src.services.claude_service import ClaudeService
    claude = ClaudeService.__new__(ClaudeService)
    claude.client = MagicMock()
    claude.create_fast_parse(system="s", content="c", schema={}, model="m", timeout_s=5)
    kwargs = claude.client.with_options.return_value.messages.create.call_args.kwargs
    assert kwargs["max_tokens"] == 1500


def test_skills_of_reads_the_catalog_the_router_reads(tmp_path):
    (tmp_path / "time-management.md").write_text(
        "---\nname: time-management\ndescription: Blocks, tasks and the calendar.\n"
        "when_to_use: |\n  Scheduling, reminders,\n  task files\ntools: [create_task]\nmodel: m\n---\nprompt\n",
        encoding="utf-8")
    assert skills_of(tmp_path) == ("time-management: Blocks, tasks and the calendar. Use for: Scheduling, reminders, task files",)


def test_the_parse_sees_the_skill_catalog():
    ctx = FastContext(now=NOW, chat_id=1, text="list my tasks",
                      skills=("time-management: Blocks, tasks and the calendar.",))
    content = build_user_content(ctx)
    assert "Skills for fallthrough_skill:\n- time-management: Blocks, tasks and the calendar." in content
    assert content.endswith("Message:\nlist my tasks")


def test_names_match_through_wording_differences():
    assert _same_name("Washed the dishes", "Wash dishes")
    assert _same_name("Evening Dog Walk", "dog walk")
    assert not _same_name("Dog walk", "Dog food")
    assert not _same_name("Gym", None)


def test_select_rows_by_id_and_limit():
    messages = [Message(id=f"t000{k}", ts=NOW, text="x") for k in range(1, 5)]
    golden = {m.id: {"expected": {"route": "fast"}} for m in messages}
    golden["t0002"] = {"expected": None}
    assert [m.id for _, m in select_rows(messages, golden)] == ["t0001", "t0003", "t0004"]
    assert [m.id for _, m in select_rows(messages, golden, ids={"t0003", "t0002"})] == ["t0003"]
    assert [m.id for _, m in select_rows(messages, golden, limit=2)] == ["t0001", "t0003"]


def test_replayed_blocks_keep_their_ids_from_either_result_shape():
    earlier = [
        Message(id="t0001", ts=NOW - dt.timedelta(hours=2), text="x", old_tools=[
            {"name": "create_event", "params": {"name": "Gym", "date": "2026-09-28", "start_time": "18:00"},
             "result": {"ok": True, "data": {"event_id": "evt_new"}}},
            {"name": "create_event", "params": {"name": "Walk", "date": "2026-09-28", "start_time": "19:00"},
             "result": {"event_id": "evt_old"}},
        ]),
    ]
    blocks = _blocks_before(Message(id="t0002", ts=NOW, text="y"), earlier)
    assert [b.id for b in blocks] == ["evt_new", "evt_old"]


def test_older_messages_come_from_the_conversation_files(tmp_path):
    from src.services.fast_lane.replay import load_conversation_messages
    day = tmp_path / "2026-03-02"
    day.mkdir()
    (day / "7.md").write_text(
        "---\nchat_id: 7\n---\n\n### 22:02 [user]\nDog walk 21:00-21:30\n\n### 22:02 [assistant]\nLogged it.\n\n"
        '### 22:10 [user]\n(replying to assistant: "Logged it.") make it 21:15\n\n### 22:10 [assistant]\nMoved.\n',
        encoding="utf-8")
    later = tmp_path / "2026-05-02"
    later.mkdir()
    (later / "7.md").write_text("---\nchat_id: 7\n---\n\n### 09:00 [user]\nin the turn log already\n", encoding="utf-8")
    msgs = load_conversation_messages(tmp_path, 7, TZ, before=dt.date(2026, 5, 2))
    assert [(m.id, m.text, m.old_reply) for m in msgs] == [
        ("c0001", "Dog walk 21:00-21:30", "Logged it."), ("c0002", "make it 21:15", "Moved.")]
    assert msgs[1].reply_to == "Logged it." and msgs[1].ts == dt.datetime(2026, 3, 2, 22, 10, tzinfo=TZ)


def test_new_rows_are_appended_blind_to_the_old_router():
    from src.services.fast_lane.replay import new_skeleton_rows
    msgs = [Message(id="t0001", ts=NOW, text="x", old_skill="mazkir"),
            Message(id="t0002", ts=NOW, text="y", old_skill="time-management")]
    rows = new_skeleton_rows(msgs, {"t0001": {}})
    assert [r["id"] for r in rows] == ["t0002"]
    assert "skill" not in rows[0]["old"] and rows[0]["expected"] is None


def test_a_label_can_accept_a_second_name_or_op():
    from src.services.fast_lane.contract import Clause, ParseResult
    from src.services.fast_lane.replay import score_row
    expected = {"route": "fast", "clauses": [
        {"op": "tick_habit", "name": "Gym", "also_names": ["Workout"], "expect": {"outcome": "fact"}},
        {"op": "start_block", "name": "Dog walk", "also_ops": ["log_block"], "expect": {"outcome": "fact"}}]}
    got = ParseResult((Clause("tick_habit", "record", True, "Gym", name="Workout"),
                       Clause("log_block", "record", True, "went for a dog walk", name="Dog walk")), None)
    score = score_row(expected, got, [None, None], NOW)
    assert (score.matched, score.expected_clauses) == (2, 2)


def test_the_parse_asks_for_no_thinking():
    """Sonnet 5 thinks unless told not to: 99 of 100 parses in the 2026-09-29 sample failed on it."""
    from src.services.claude_service import ClaudeService
    claude = ClaudeService.__new__(ClaudeService)
    claude.client = MagicMock()
    claude.create_fast_parse(system="s", content="c", schema={}, model="m", timeout_s=5)
    kwargs = claude.client.with_options.return_value.messages.create.call_args.kwargs
    assert kwargs["thinking"] == {"type": "disabled"}


def test_the_reply_is_read_from_its_text_block_not_the_first_block():
    from types import SimpleNamespace
    from src.services.fast_lane.parse import _decode
    thinking = SimpleNamespace(type="thinking", thinking="")
    text = SimpleNamespace(type="text", text='{"clauses": [], "fallthrough_skill": "mazkir"}')
    reply = SimpleNamespace(stop_reason="end_turn", content=[thinking, text])
    assert _decode(reply) == {"clauses": [], "fallthrough_skill": "mazkir"}


def test_a_reply_with_no_text_block_is_a_parse_failure():
    import pytest
    from types import SimpleNamespace
    from src.services.fast_lane.contract import ParseFailure
    from src.services.fast_lane.parse import _decode
    reply = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="thinking", thinking="")])
    with pytest.raises(ParseFailure, match="no text"):
        _decode(reply)


def _scored(label, clause):
    from src.services.fast_lane.contract import ParseResult
    from src.services.fast_lane.replay import score_row
    score = score_row({"route": "fast", "clauses": [label]}, ParseResult((clause,), None), [None], NOW)
    return score.matched


def _label(op, **time):
    return {"op": op, "name": "Dog walk", "target": "Dog walk", "time": time, "expect": {}}


def test_starting_and_logging_with_only_a_start_are_the_same_write():
    """The resolver places both from the start; the ops differ only in name (2026-09-29 Sonnet sample)."""
    from src.services.fast_lane.contract import Clause, TimeWords
    got = Clause("log_block", "record", True, "Dog walk at 12:00", name="Dog walk", time=TimeWords(start="12:00"))
    assert _scored(_label("start_block", start="12:00"), got) == 1


def test_ending_and_setting_only_the_end_of_a_block_are_the_same_write():
    from src.services.fast_lane.contract import Clause, TimeWords
    got = Clause("edit_block", "record", True, "walk until 15:45", target="Dog walk", time=TimeWords(end="15:45"))
    assert _scored(_label("end_block", end="15:45"), got) == 1


def test_an_edit_that_moves_the_start_is_not_an_end():
    from src.services.fast_lane.contract import Clause, TimeWords
    got = Clause("edit_block", "record", True, "walk from 15:00", target="Dog walk", time=TimeWords(start="15:00"))
    assert _scored(_label("end_block", end="15:45"), got) == 0
    shifted = Clause("edit_block", "record", True, "back 30 mins", target="Dog walk", time=TimeWords(shift="back 30 mins"))
    assert _scored(_label("end_block", end="15:45"), shifted) == 0


def test_an_end_with_no_start_matches_a_block_logged_by_its_end():
    """end_block falls back to a new block with that end when nothing is open (spec §7.1)."""
    from src.services.fast_lane.contract import Clause, TimeWords
    got = Clause("end_block", "record", True, "just returned from the walk", target="Dog walk", time=TimeWords(end="now"))
    assert _scored(_label("log_block", end="just returned"), got) == 1
    with_start = Clause("log_block", "record", True, "walk 15:00-15:30", name="Dog walk",
                        time=TimeWords(start="15:00", end="15:30"))
    assert _scored(_label("end_block", end="15:30"), with_start) == 0


def test_ops_that_write_different_things_still_do_not_match():
    from src.services.fast_lane.contract import Clause, TimeWords
    todo = Clause("check_todo", "record", True, "walked the dog", target="Dog walk")
    assert _scored(_label("log_block", start="12:00"), todo) == 0
    edit = Clause("edit_block", "record", True, "move the walk to 18:00", target="Dog walk", time=TimeWords(start="18:00"))
    assert _scored(_label("log_block", start="18:00"), edit) == 0


def test_a_saved_parse_is_rebuilt_to_be_scored_again_for_free():
    from src.services.fast_lane.contract import TimeWords
    from src.services.fast_lane.replay import saved_parse
    row = {"id": "t0001", "route": "mixed", "fallthrough_skill": "time-management", "clauses": [
        {"op": "log_block", "intent": "record", "stated": True, "evidence": "Walk 15:00-15:30", "name": "Walk",
         "target": None, "tags": ["dev"], "place": None, "people": ["Ann"], "project": None,
         "time": {"start": "15:00", "end": "15:30", "duration": None, "shift": None, "day": None,
                  "after": None, "with_": 0}},
        {"op": "other", "intent": "record", "stated": True, "evidence": "and list my tasks", "name": None,
         "target": None, "tags": [], "place": None, "people": [], "project": None, "time": None}]}
    result = saved_parse(row)
    assert result.route == "mixed" and result.fallthrough_skill == "time-management"
    walk = result.clauses[0]
    assert walk.time == TimeWords(start="15:00", end="15:30", with_=0)
    assert walk.tags == ("dev",) and walk.people == ("Ann",)


def test_a_saved_parse_keeps_the_route_its_dropped_clauses_gave_it():
    from src.services.fast_lane.replay import saved_parse
    clause = {"op": "tick_habit", "intent": "record", "stated": True, "evidence": "gym", "name": "Gym",
              "target": None, "tags": [], "place": None, "people": [], "project": None, "time": None}
    assert saved_parse({"id": "t1", "route": "mixed", "fallthrough_skill": None, "clauses": [clause]}).route == "mixed"
    assert saved_parse({"id": "t1", "route": "fast", "fallthrough_skill": None, "clauses": [clause]}).route == "fast"


def test_a_saved_parse_failure_has_nothing_to_rebuild():
    from src.services.fast_lane.replay import saved_parse
    assert saved_parse({"id": "t1", "parse_failure": "timed out"}) is None


def test_your_bedtime_is_the_median_sleep_start_across_midnight():
    from src.services.fast_lane.context import typical_bedtime

    class Events:
        def get_events(self, day):
            starts = {"2026-09-27": "2026-09-27T23:30:00", "2026-09-26": "2026-09-26T00:30:00",
                      "2026-09-25": "2026-09-25T01:00:00"}
            if day not in starts:
                return [{"name": "Gym", "start_time": f"{day}T18:00:00", "end_time": f"{day}T19:00:00"}]
            return [{"name": "Sleep", "start_time": starts[day], "end_time": f"{day}T08:00:00"}]

    assert typical_bedtime(Events(), before=dt.date(2026, 9, 28)) == dt.time(0, 30)


def test_no_bedtime_without_three_nights():
    from src.services.fast_lane.context import typical_bedtime

    class Events:
        def get_events(self, day):
            return [{"name": "Sleep", "start_time": f"{day}T23:00:00", "end_time": f"{day}T23:59:00"}] \
                if day == "2026-09-27" else []

    assert typical_bedtime(Events(), before=dt.date(2026, 9, 28)) is None


def test_the_shadow_names_an_end_by_its_target():
    from src.services.fast_lane.contract import Clause, TimeWords
    from src.services.fast_lane.shadow import _clause_time
    c = Clause("end_block", "record", True, "Woke up at 11:00", target="Sleep", time=TimeWords(end="11:00"))
    assert _clause_time(c, [], {}).name == "Sleep"
