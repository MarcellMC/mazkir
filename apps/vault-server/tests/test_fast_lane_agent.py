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
