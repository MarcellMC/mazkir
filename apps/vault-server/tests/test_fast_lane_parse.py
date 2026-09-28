import datetime as dt
import json
import re
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from src.services.fast_lane.context import BlockView, FastContext
from src.services.fast_lane.contract import OPS, validate
from src.services.fast_lane.parse import (
    SYSTEM_PROMPT, ParseFailure, build_user_content, parse_message, warm_up,
)

TZ = ZoneInfo("Asia/Jerusalem")
NOW = dt.datetime(2026, 9, 8, 0, 48, tzinfo=TZ)


def reply(text, stop_reason="end_turn"):
    """The shape of an Anthropic Messages response, as far as the parse reads it."""
    return SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(text=text)])


def test_the_prompt_names_every_operation():
    for op in OPS:
        assert op in SYSTEM_PROMPT


def test_every_example_in_the_prompt_obeys_the_contract():
    pairs = re.findall(r"^Message \(sent \d\d:\d\d\): (.*)\nOutput: (.*)$", SYSTEM_PROMPT, re.MULTILINE)
    assert len(pairs) >= 10
    for message, output in pairs:
        result = validate(json.loads(output), message)
        assert result.dropped == (), message


def test_user_content_carries_the_moment_the_day_and_the_message_last():
    ctx = FastContext(
        now=NOW, chat_id=1, text="Dog walk 23:15-23:35",
        reply_to="Logged!", reply_from="assistant",
        recent_turns=(("user", "hi"), ("assistant", "hello")),
        blocks=(BlockView("e1", "2026-09-07", "Gym", dt.datetime(2026, 9, 7, 21, 30, tzinfo=TZ), None),),
        hashtags=("dev",),
    )
    content = build_user_content(ctx)
    assert content.startswith("Now: Tuesday 2026-09-08 00:48")
    assert "09-07 21:30–open Gym" in content
    assert "replies to (assistant): Logged!" in content
    assert "#dev" in content
    assert content.endswith("Message:\nDog walk 23:15-23:35")


def test_parse_message_validates_the_answer():
    claude = MagicMock()
    claude.create_fast_parse.return_value = reply(json.dumps({"clauses": [
        {"op": "log_block", "intent": "record", "stated": True, "evidence": "Dog walk 23:15-23:35",
         "name": "Dog walk", "time": {"start": "23:15", "end": "23:35"}}], "fallthrough_skill": None}))
    result = parse_message(FastContext(now=NOW, chat_id=1, text="Dog walk 23:15-23:35"),
                           claude, model="m", timeout_s=5)
    assert result.route == "fast"
    assert claude.create_fast_parse.call_args.kwargs["model"] == "m"


@pytest.mark.parametrize("behaviour", [RuntimeError("timeout"), reply("null"), reply("not json"), None])
def test_parse_message_failures_hand_the_message_on(behaviour):
    claude = MagicMock()
    if isinstance(behaviour, Exception):
        claude.create_fast_parse.side_effect = behaviour
    else:
        claude.create_fast_parse.return_value = behaviour
    with pytest.raises(ParseFailure):
        parse_message(FastContext(now=NOW, chat_id=1, text="x"), claude, model="m", timeout_s=5)


def test_a_truncated_parse_says_it_hit_max_tokens():
    claude = MagicMock()
    claude.create_fast_parse.return_value = reply('{"clauses": [{"op": "log_block", "intent": "rec',
                                                  stop_reason="max_tokens")
    with pytest.raises(ParseFailure, match="max_tokens"):
        parse_message(FastContext(now=NOW, chat_id=1, text="x"), claude, model="m", timeout_s=5)


def test_warm_up_never_raises():
    claude = MagicMock()
    claude.create_fast_parse.side_effect = RuntimeError("down")
    warm_up(claude, "m", 20)
    assert claude.create_fast_parse.called


def test_prompt_does_not_use_assistant_just_asked_header():
    """Examples must use context formats that build_user_content actually produces."""
    assert "The assistant just asked" not in SYSTEM_PROMPT
