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
