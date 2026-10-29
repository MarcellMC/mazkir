# tests/test_fast_lane_agent.py
"""Spec §5.5, §8.1: the parse's skill skips the router; the skill hears what ran; tools report stages."""

import logging
from unittest.mock import MagicMock

from src.services.skill_executor import SkillExecutor
from src.services.skill_registry import Skill


def _skill(name):
    return Skill(name=name, description=name, system_prompt=f"You are {name}.", tools=[],
                 model="claude-haiku-4-5", max_iterations=3, next_skills=[])


def test_a_skill_chosen_by_the_parse_skips_the_router():
    skill = _skill("knowledge-management")
    registry = MagicMock()
    registry.list.return_value = [skill]
    registry.get.side_effect = lambda n: skill if n == "knowledge-management" else None
    router = MagicMock()
    seen = {}

    def run_loop(*, skill, **kwargs):
        seen["skill"] = skill
        return "answer", "end_turn"

    executor = SkillExecutor(skill_registry=registry, router=router, tools={}, run_loop=run_loop,
                             build_base_system_prompt=lambda context: "base")
    result = executor.run(chat_id=1, user_msg="explain attention", context_messages=[], messages=[],
                          skill="knowledge-management")
    router.pick.assert_not_called()
    assert seen["skill"] == "knowledge-management" and result.response_text == "answer"


def test_an_unknown_skill_still_goes_to_the_router(caplog):
    skill = _skill("mazkir")
    registry = MagicMock()
    registry.list.return_value = [skill]
    registry.get.side_effect = lambda n: skill if n == "mazkir" else None
    router = MagicMock()
    router.pick.return_value = MagicMock(skill="mazkir", reason="r")
    executor = SkillExecutor(skill_registry=registry, router=router, tools={},
                             run_loop=lambda **kw: ("hi", "end_turn"),
                             build_base_system_prompt=lambda context: "base")
    with caplog.at_level(logging.WARNING, logger="src.services.skill_executor"):
        executor.run(chat_id=1, user_msg="hi", context_messages=[], messages=[], skill="no-such-skill")
    router.pick.assert_called_once()
    assert any("no-such-skill" in r.getMessage() for r in caplog.records)


def test_the_skill_is_told_what_the_fast_lane_already_did(mock_services, tmp_path):
    from src.services.agent_service import AgentResponse, AgentService
    agent = AgentService(claude=mock_services["claude"], vault=mock_services["vault"],
                         memory=mock_services["memory"], media_path=tmp_path)
    seen = {}

    def fake_turn(chat_id, log_text, messages, system, **kw):
        seen["log_text"], seen["last"] = log_text, messages[-1]["content"]
        return AgentResponse(response="done", iterations=1)

    agent._run_agent_turn = fake_turn
    agent.handle_message(text="Dog walk 23:15-23:35, and what is GQA?", chat_id=1,
                         prior_actions=["✓ yest 23:15–23:35 Dog walk (block)"])
    assert "do not redo" in seen["last"] and "Dog walk (block)" in seen["last"]
    assert seen["log_text"] == "Dog walk 23:15-23:35, and what is GQA?"


def test_the_skill_path_logs_the_users_exact_words_and_hears_the_note(mock_services, tmp_path):
    """turn_trace joins on the exact user_text: the note is input, never the logged text."""
    from src.services.agent_service import AgentService
    skill = _skill("knowledge-management")
    registry = MagicMock()
    registry.list.return_value = [skill]
    registry.get.side_effect = lambda n: skill if n == "knowledge-management" else None
    router = MagicMock()
    agent = AgentService(claude=mock_services["claude"], vault=mock_services["vault"],
                         memory=mock_services["memory"], media_path=tmp_path,
                         skill_registry=registry, router=router)
    seen = {}

    def fake_loop(chat_id, log_text, messages, system, **kw):
        seen["log_text"], seen["last"], seen["model"] = log_text, messages[-1]["content"], kw.get("model")
        return "done", "end_turn"

    agent._skill_executor._run_loop = fake_loop
    text = "Dog walk 23:15-23:35, and what is GQA?"
    response = agent.handle_message(text=text, chat_id=1, skill="knowledge-management",
                                    prior_actions=["✓ yest 23:15–23:35 Dog walk (block)"])
    router.pick.assert_not_called()
    assert response.response == "done"
    assert seen["log_text"] == text
    assert "do not redo" in seen["last"] and seen["last"].endswith(text)


def test_the_note_sits_between_the_trailing_trace_and_the_users_words(mock_services, tmp_path):
    """The note is about *this* message, so it goes directly before its words;
    the previous reply's trace comes first, as it does without a note."""
    from src.services.agent_service import AgentResponse, AgentService
    from src.services.memory_service import ConversationContext
    mock_services["memory"].assemble_context.return_value = ConversationContext(
        messages=[], summary="", vault_snapshot="", knowledge="",
        trailing_trace="[Record of your previous reply — tools that actually ran: none]")
    agent = AgentService(claude=mock_services["claude"], vault=mock_services["vault"],
                         memory=mock_services["memory"], media_path=tmp_path)
    seen = {}

    def fake_turn(chat_id, log_text, messages, system, **kw):
        seen["log_text"], seen["last"] = log_text, messages[-1]["content"]
        return AgentResponse(response="done", iterations=1)

    agent._run_agent_turn = fake_turn
    text = "Dog walk 23:15-23:35, and what is GQA?"
    agent.handle_message(text=text, chat_id=1, prior_actions=["✓ yest 23:15–23:35 Dog walk (block)"])
    last = seen["last"]
    assert last.startswith("[Record of your previous reply")
    assert last.index("Record of your previous reply") < last.index("Already done") < last.index(text)
    assert last.endswith(text) and seen["log_text"] == text


def test_without_prior_actions_the_message_is_untouched(mock_services, tmp_path):
    from src.services.agent_service import AgentResponse, AgentService
    agent = AgentService(claude=mock_services["claude"], vault=mock_services["vault"],
                         memory=mock_services["memory"], media_path=tmp_path)
    seen = {}

    def fake_turn(chat_id, log_text, messages, system, **kw):
        seen["last"] = messages[-1]["content"]
        return AgentResponse(response="done", iterations=1)

    agent._run_agent_turn = fake_turn
    agent.handle_message(text="what is GQA?", chat_id=1)
    assert "Already done" not in str(seen["last"])


def test_tool_calls_report_a_stage_in_plain_words(mock_services, tmp_path):
    from src.services.agent_service import AgentService
    agent = AgentService(claude=mock_services["claude"], vault=mock_services["vault"],
                         memory=mock_services["memory"], media_path=tmp_path)
    # The stage is about the call, not its outcome: stub the handlers so the
    # mocked vault's MagicMocks never reach the span's JSON output.
    for name in ("list_tasks", "create_goal"):
        agent.tools[name]["handler"] = lambda params: {"ok": True, "data": {}}
    stages = []
    agent._stage_callback = stages.append
    agent._execute_tool("list_tasks", {})
    agent._execute_tool("create_goal", {"name": "x"})
    assert stages == ["Checking your tasks…", "Working…"]


def test_the_fast_lanes_own_tool_calls_report_no_stage(mock_services, tmp_path):
    """The fast lane emits its own stages, and `_stage_callback` lives on the
    shared instance: a `run_tool` call reporting through it would leak
    "Working…" into whichever message's stream is open at the time."""
    from src.services.agent_service import AgentService
    agent = AgentService(claude=mock_services["claude"], vault=mock_services["vault"],
                         memory=mock_services["memory"], media_path=tmp_path)
    agent.tools["list_tasks"]["handler"] = lambda params: {"ok": True, "data": {}}
    stages = []
    agent._stage_callback = stages.append
    agent.run_tool("list_tasks", {})
    assert stages == []


def test_a_failing_stage_callback_never_reaches_the_tool(mock_services, tmp_path):
    from src.services.agent_service import AgentService
    agent = AgentService(claude=mock_services["claude"], vault=mock_services["vault"],
                         memory=mock_services["memory"], media_path=tmp_path)

    def boom(_stage):
        raise RuntimeError("bot gone")

    agent._stage_callback = boom
    result = agent._execute_tool("list_tasks", {})
    assert isinstance(result, dict)


def test_the_stage_callback_lasts_one_message(mock_services, tmp_path):
    from src.services.agent_service import AgentResponse, AgentService
    agent = AgentService(claude=mock_services["claude"], vault=mock_services["vault"],
                         memory=mock_services["memory"], media_path=tmp_path)
    seen = {}

    def fake_turn(chat_id, log_text, messages, system, **kw):
        seen["during"] = agent._stage_callback
        return AgentResponse(response="done", iterations=1)

    agent._run_agent_turn = fake_turn
    cb = MagicMock()
    agent.handle_message(text="hi", chat_id=1, stage_callback=cb)
    assert seen["during"] is cb and agent._stage_callback is None


def test_the_router_is_its_own_named_span(monkeypatch):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    import src.services.router_service as router_module
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(router_module, "_tracer", provider.get_tracer("test"))
    claude = MagicMock()
    claude.create_router_choice.return_value = {"skill": "mazkir", "reason": "chat"}
    decision = router_module.RouterService(claude).pick("hi", [], [_skill("mazkir")])
    [span] = [s for s in exporter.get_finished_spans() if s.name == "router.pick"]
    assert decision.skill == "mazkir" and span.attributes["router.skill"] == "mazkir"


# ── Task 14b: the fast lane and the skill log one message under one text ──

def _fast_ctx(text, *, reply_to=None, attachments=None):
    import datetime as dt
    from zoneinfo import ZoneInfo
    from src.services.fast_lane.context import assemble_fast_context
    events = MagicMock()
    events.get_events.return_value = []
    return assemble_fast_context(
        text=text, chat_id=7, now=dt.datetime(2026, 9, 8, 12, 0, tzinfo=ZoneInfo("Asia/Jerusalem")),
        memory=MagicMock(load_conversation=MagicMock(return_value={"messages": []})),
        events=events, vault=MagicMock(), reply_to=reply_to, attachments=attachments,
    )


def _fast_log(monkeypatch, ctx, route, tool_name):
    """What `_log_turn` emits and saves for a turn whose one step was `tool_name`."""
    import src.services.fast_lane.turn as turn_module
    from src.services.fast_lane.actions import PlannedLine
    logged = []
    monkeypatch.setattr(turn_module, "emit_agent_turn", logged.append)
    step = MagicMock(tool=tool_name, params={"name": "Dog walk"})
    line = MagicMock(spec=PlannedLine, steps=[step])
    memory = MagicMock()
    deps = MagicMock(memory=memory)
    turn_module._log_turn(ctx, deps, [line], [{"steps": [{"ok": True}]}], "receipt", route=route)
    [record] = logged
    return record, memory


def _agent_log_text(mock_services, tmp_path, **kwargs):
    """The text the agent loop remembers this message by (what the skill logs)."""
    from src.services.agent_service import AgentResponse, AgentService
    agent = AgentService(claude=mock_services["claude"], vault=mock_services["vault"],
                         memory=mock_services["memory"], media_path=tmp_path)
    seen = {}

    def fake_turn(chat_id, log_text, messages, system, **kw):
        seen["log_text"] = log_text
        return AgentResponse(response="done", iterations=1)

    agent._run_agent_turn = fake_turn
    agent.handle_message(chat_id=7, **kwargs)
    return seen["log_text"]


def _skill_record(text, tool_name):
    return {"chat_id": 7, "skill": "time-management", "user_text": text,
            "tools": [{"name": tool_name, "params": {}, "result_summary": {"ok": True}}]}


def test_a_reply_mixed_turn_after_the_same_words_coalesces_end_to_end(mock_services, tmp_path, monkeypatch):
    from src.services.turn_trace import attach_traces
    # 1. an earlier plain fast-route "walked": its own record and its own pair
    first, first_memory = _fast_log(monkeypatch, _fast_ctx("walked"), "fast", "fast_first")
    [(_, first_pair_text, _, _)] = [c.args for c in first_memory.save_turn.call_args_list]
    assert first_pair_text == "walked" == _agent_log_text(mock_services, tmp_path, text="walked")
    # 2. an ordinary turn between
    between = _skill_record("two", "tool_two")
    # 3. a mixed turn replying to a message, with the same raw words
    reply = {"text": "Logged a dog walk", "from": "assistant"}
    second, second_memory = _fast_log(monkeypatch, _fast_ctx("walked", reply_to=reply), "mixed", "fast_second")
    second_memory.save_turn.assert_not_called()
    skill_text = _agent_log_text(mock_services, tmp_path, text="walked", reply_to=reply)
    assert second["user_text"] == skill_text and second["route"] == "mixed"

    messages = [{"role": "user", "content": first_pair_text}, {"role": "assistant", "content": "receipt"},
                {"role": "user", "content": "two"}, {"role": "assistant", "content": "B"},
                {"role": "user", "content": skill_text}, {"role": "assistant", "content": "Done."}]
    out, trailing = attach_traces(messages, [first, between, second, _skill_record(skill_text, "skill_tool")])

    assert "fast_first" in out[2]["content"] and "fast_second" not in out[2]["content"]
    assert "tool_two" in out[4]["content"]
    assert "fast_second" in trailing and "skill_tool" in trailing and "fast_first" not in trailing


def test_a_photo_mixed_turn_coalesces_end_to_end(mock_services, tmp_path, monkeypatch):
    from src.services.turn_trace import attach_traces
    attachments = [{"type": "photo", "filename": "walk.jpg"}]
    fast, _ = _fast_log(monkeypatch, _fast_ctx("dog walk, and what is GQA?", attachments=attachments),
                        "mixed", "fast_tool")
    skill_text = _agent_log_text(mock_services, tmp_path, text="dog walk, and what is GQA?",
                                 attachments=attachments)
    assert skill_text.startswith("(photo: walk.jpg)") and fast["user_text"] == skill_text

    _, trailing = attach_traces([{"role": "user", "content": skill_text}, {"role": "assistant", "content": "Done."}],
                                [fast, _skill_record(skill_text, "skill_tool")])
    assert trailing.index("fast_tool") < trailing.index("skill_tool")


def test_conversation_log_text_matches_the_old_prefixes():
    from src.services.conversation_text import conversation_log_text
    assert conversation_log_text("hi", None, None) == "hi"
    assert conversation_log_text("hi", [{"type": "photo"}, {"type": "location", "latitude": 1.5, "longitude": 2}],
                                 {"text": "x" * 60, "from": "assistant"}) == (
        f'(replying to assistant: "{"x" * 50}") (photo: photo, location: 1.5, 2) hi')
    assert conversation_log_text("", [{"type": "photo", "filename": "a.jpg"}], None) == "(photo: a.jpg)"


def _note_for(mock_services, tmp_path, **kw):
    from src.services.agent_service import AgentResponse, AgentService
    agent = AgentService(claude=mock_services["claude"], vault=mock_services["vault"],
                         memory=mock_services["memory"], media_path=tmp_path)
    seen = {}

    def fake_turn(chat_id, log_text, messages, system, **_):
        seen["last"] = messages[-1]["content"]
        return AgentResponse(response="done", iterations=1)

    agent._run_agent_turn = fake_turn
    agent.handle_message(text="Dog walk 23:15-23:35", chat_id=1,
                         prior_actions=["✓ yest 23:15–23:35 Dog walk (block)"], **kw)
    return str(seen["last"])


def test_an_ordinary_mixed_turn_gets_the_plain_note(mock_services, tmp_path):
    note = _note_for(mock_services, tmp_path)
    assert "do not redo" in note and "only with the attachment" not in note


def test_a_turn_whose_words_are_all_done_is_told_to_handle_only_the_attachment(mock_services, tmp_path):
    """Final re-review: the router would otherwise pick a skill for text already written."""
    note = _note_for(mock_services, tmp_path, text_handled=True)
    assert "fully handled" in note and "only with the attachment" in note
    assert "Dog walk (block)" in note
