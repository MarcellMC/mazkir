"""Tests for the skill-aware agent loop in AgentService."""

from unittest.mock import MagicMock

import pytest

from src.services.skill_registry import Skill


def _mk_skill(name: str, tools: list[str], next_skills: list[str] | None = None) -> Skill:
    return Skill(
        name=name,
        description=f"{name} skill",
        system_prompt=f"You are the {name} skill.",
        tools=tools,
        model="claude-haiku-4-5",
        max_iterations=3,
        next_skills=next_skills or [],
    )


@pytest.fixture
def mock_services(tmp_path):
    """Create mock service dependencies (tuple form matching test_agent_service.py)."""
    from src.services.memory_service import ConversationContext

    claude = MagicMock()
    vault = MagicMock()
    memory = MagicMock()
    calendar = MagicMock()
    events = MagicMock()

    vault.vault_path = tmp_path / "vault"
    vault.vault_path.mkdir()

    memory.assemble_context.return_value = ConversationContext(
        messages=[],
        summary="",
        vault_snapshot="No data.",
        knowledge="",
    )
    memory.save_turn = MagicMock()
    memory.summarize_and_decay = MagicMock()

    return claude, vault, memory, calendar, events


def test_router_picks_skill_and_loop_uses_its_tools(mock_services, monkeypatch):
    from src.services.agent_service import AgentService
    claude, vault, memory, calendar, events = mock_services

    skill_registry = MagicMock()
    skill_registry.list.return_value = [_mk_skill("manager", ["list_tasks"])]
    skill_registry.get.side_effect = lambda n: _mk_skill("manager", ["list_tasks"]) if n == "manager" else None

    router = MagicMock()
    router.pick.return_value = MagicMock(skill="manager", reason="planning intent")

    agent = AgentService(
        claude=claude, vault=vault, memory=memory, calendar=calendar, events=events,
        skill_registry=skill_registry, router=router,
    )

    captured = {}
    def fake_run_loop(chat_id, log_text, messages, system, tool_schemas, max_iterations):
        captured["tool_schemas"] = tool_schemas
        captured["system"] = system
        captured["max_iterations"] = max_iterations
        return "ok", "end_turn"
    monkeypatch.setattr(agent, "_run_loop", fake_run_loop)

    agent.handle_message(chat_id=1, text="What's on my plate")

    schema_names = [s["name"] for s in captured["tool_schemas"]]
    assert schema_names == ["list_tasks"]
    assert "You are the manager skill" in captured["system"]
    assert captured["max_iterations"] == 3


def test_next_skill_handoff_runs_second_skill(mock_services, monkeypatch):
    from src.services.agent_service import AgentService
    claude, vault, memory, calendar, events = mock_services

    capture_skill = _mk_skill("capture", ["save_knowledge"], next_skills=["manager"])
    manager_skill = _mk_skill("manager", ["list_tasks"])

    skill_registry = MagicMock()
    skill_registry.list.return_value = [capture_skill, manager_skill]
    skill_registry.get.side_effect = lambda n: {"capture": capture_skill, "manager": manager_skill}.get(n)

    router = MagicMock()
    router.pick.return_value = MagicMock(skill="capture", reason="")

    agent = AgentService(
        claude=claude, vault=vault, memory=memory, calendar=calendar, events=events,
        skill_registry=skill_registry, router=router,
    )

    call_log = []
    def fake_run_loop(chat_id, log_text, messages, system, tool_schemas, max_iterations):
        skill_name = "capture" if "capture skill" in system else "manager"
        call_log.append(skill_name)
        if skill_name == "capture":
            return "saved. next_skill: manager", "end_turn"
        return "done", "end_turn"

    monkeypatch.setattr(agent, "_run_loop", fake_run_loop)
    agent.handle_message(chat_id=1, text="Save this and then schedule it")

    assert call_log == ["capture", "manager"]


def test_loop_caps_at_three_hops(mock_services, monkeypatch):
    from src.services.agent_service import AgentService
    claude, vault, memory, calendar, events = mock_services

    a = _mk_skill("a", [], next_skills=["b"])
    b = _mk_skill("b", [], next_skills=["c"])
    c = _mk_skill("c", [], next_skills=["a"])

    skill_registry = MagicMock()
    skill_registry.list.return_value = [a, b, c]
    skill_registry.get.side_effect = lambda n: {"a": a, "b": b, "c": c}.get(n)

    router = MagicMock()
    router.pick.return_value = MagicMock(skill="a", reason="")

    agent = AgentService(
        claude=claude, vault=vault, memory=memory, calendar=calendar, events=events,
        skill_registry=skill_registry, router=router,
    )

    call_log = []
    def fake_run_loop(chat_id, log_text, messages, system, tool_schemas, max_iterations):
        name = next(s for s in ("a", "b", "c") if f"{s} skill" in system)
        call_log.append(name)
        nxt = {"a": "b", "b": "c", "c": "a"}[name]
        return f"hop next_skill: {nxt}", "end_turn"

    monkeypatch.setattr(agent, "_run_loop", fake_run_loop)
    agent.handle_message(chat_id=1, text="go")

    assert len(call_log) <= 3
