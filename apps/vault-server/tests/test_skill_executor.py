"""Tests for the extracted SkillExecutor."""

from unittest.mock import MagicMock

import pytest

from src.services.skill_executor import SkillExecutor, MAX_HOPS
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


def test_router_picks_skill_and_executor_uses_its_tools():
    skill = _mk_skill("manager", ["list_tasks"])
    registry = MagicMock()
    registry.list.return_value = [skill]
    registry.get.side_effect = lambda n: skill if n == "manager" else None

    router = MagicMock()
    router.pick.return_value = MagicMock(skill="manager", reason="planning intent")

    tools = {"list_tasks": {"schema": {"name": "list_tasks"}}}
    captured = {}
    def fake_run_loop(*, system, tool_schemas, max_iterations, **kwargs):
        captured["tool_schemas"] = tool_schemas
        captured["system"] = system
        captured["max_iterations"] = max_iterations
        return "ok", "end_turn"

    executor = SkillExecutor(
        skill_registry=registry,
        router=router,
        tools=tools,
        run_loop=fake_run_loop,
        build_base_system_prompt=lambda context: "base prompt",
    )
    result = executor.run(
        chat_id=1,
        user_msg="What's on my plate",
        context_messages=[],
        messages=[],
    )

    assert [s["name"] for s in captured["tool_schemas"]] == ["list_tasks"]
    assert "You are the manager skill" in captured["system"]
    assert captured["max_iterations"] == 3
    assert result.response_text == "ok"
    assert result.iterations == 1


def test_executor_passes_skill_model_to_run_loop():
    skill = Skill(
        name="manager",
        description="manager skill",
        system_prompt="You are the manager skill.",
        tools=["list_tasks"],
        model="claude-sonnet-4-6",
        max_iterations=3,
    )
    registry = MagicMock()
    registry.list.return_value = [skill]
    registry.get.side_effect = lambda n: skill if n == "manager" else None

    router = MagicMock()
    router.pick.return_value = MagicMock(skill="manager", reason="planning intent")

    captured = {}
    def fake_run_loop(*, model, **kwargs):
        captured["model"] = model
        return "ok", "end_turn"

    executor = SkillExecutor(
        skill_registry=registry,
        router=router,
        tools={"list_tasks": {"schema": {"name": "list_tasks"}}},
        run_loop=fake_run_loop,
        build_base_system_prompt=lambda context: "base prompt",
    )
    executor.run(chat_id=1, user_msg="hi", context_messages=[], messages=[])

    assert captured["model"] == "claude-sonnet-4-6"


def test_next_skill_handoff_runs_second_skill():
    capture_skill = _mk_skill("capture", ["save_knowledge"], next_skills=["manager"])
    manager_skill = _mk_skill("manager", ["list_tasks"])

    registry = MagicMock()
    registry.list.return_value = [capture_skill, manager_skill]
    registry.get.side_effect = lambda n: {"capture": capture_skill, "manager": manager_skill}.get(n)

    router = MagicMock()
    router.pick.return_value = MagicMock(skill="capture", reason="")

    call_log = []
    def fake_run_loop(*, system, **kwargs):
        skill_name = "capture" if "capture skill" in system else "manager"
        call_log.append(skill_name)
        if skill_name == "capture":
            return "saved. next_skill: manager", "end_turn"
        return "done", "end_turn"

    executor = SkillExecutor(
        skill_registry=registry,
        router=router,
        tools={"save_knowledge": {"schema": {"name": "save_knowledge"}}, "list_tasks": {"schema": {"name": "list_tasks"}}},
        run_loop=fake_run_loop,
        build_base_system_prompt=lambda context: "base prompt",
    )
    executor.run(chat_id=1, user_msg="Save this and then schedule it", context_messages=[], messages=[])
    assert call_log == ["capture", "manager"]


def test_loop_caps_at_max_hops():
    a = _mk_skill("a", [], next_skills=["b"])
    b = _mk_skill("b", [], next_skills=["c"])
    c = _mk_skill("c", [], next_skills=["a"])

    registry = MagicMock()
    registry.list.return_value = [a, b, c]
    registry.get.side_effect = lambda n: {"a": a, "b": b, "c": c}.get(n)

    router = MagicMock()
    router.pick.return_value = MagicMock(skill="a", reason="")

    call_log = []
    def fake_run_loop(*, system, **kwargs):
        name = next(s for s in ("a", "b", "c") if f"{s} skill" in system)
        call_log.append(name)
        nxt = {"a": "b", "b": "c", "c": "a"}[name]
        return f"hop next_skill: {nxt}", "end_turn"

    executor = SkillExecutor(
        skill_registry=registry,
        router=router,
        tools={},
        run_loop=fake_run_loop,
        build_base_system_prompt=lambda context: "base prompt",
    )
    executor.run(chat_id=1, user_msg="go", context_messages=[], messages=[])
    assert len(call_log) <= MAX_HOPS
    assert MAX_HOPS == 3


def test_unknown_next_skill_is_ignored():
    capture = _mk_skill("capture", [], next_skills=[])
    registry = MagicMock()
    registry.list.return_value = [capture]
    registry.get.side_effect = lambda n: capture if n == "capture" else None

    router = MagicMock()
    router.pick.return_value = MagicMock(skill="capture", reason="")

    fake_run_loop = MagicMock(return_value=("text. next_skill: bogus", "end_turn"))
    executor = SkillExecutor(
        skill_registry=registry,
        router=router,
        tools={},
        run_loop=fake_run_loop,
        build_base_system_prompt=lambda context: "base prompt",
    )
    result = executor.run(chat_id=1, user_msg="x", context_messages=[], messages=[])
    assert result.iterations == 1


def test_pending_confirmation_is_propagated_to_result():
    skill = _mk_skill("engineering", ["propose_coding_session"])
    registry = MagicMock()
    registry.list.return_value = [skill]
    registry.get.side_effect = lambda n: skill if n == "engineering" else None

    router = MagicMock()
    router.pick.return_value = MagicMock(skill="engineering", reason="bug report")

    fake_run_loop = MagicMock(
        return_value=("Would spin up a session. Should I proceed?", "needs_confirmation", "act_123")
    )
    executor = SkillExecutor(
        skill_registry=registry,
        router=router,
        tools={"propose_coding_session": {"schema": {"name": "propose_coding_session"}}},
        run_loop=fake_run_loop,
        build_base_system_prompt=lambda context: "base prompt",
    )
    result = executor.run(chat_id=1, user_msg="X is broken", context_messages=[], messages=[])

    assert result.awaiting_confirmation is True
    assert result.pending_action_id == "act_123"


def test_pending_confirmation_stops_skill_handoff():
    engineering = _mk_skill("engineering", [], next_skills=["mazkir"])
    mazkir = _mk_skill("mazkir", [])
    registry = MagicMock()
    registry.list.return_value = [engineering, mazkir]
    registry.get.side_effect = lambda n: {"engineering": engineering, "mazkir": mazkir}.get(n)

    router = MagicMock()
    router.pick.return_value = MagicMock(skill="engineering", reason="")

    call_log = []
    def fake_run_loop(*, system, **kwargs):
        name = "engineering" if "engineering skill" in system else "mazkir"
        call_log.append(name)
        return "Should I proceed? next_skill: mazkir", "needs_confirmation", "act_9"

    executor = SkillExecutor(
        skill_registry=registry,
        router=router,
        tools={},
        run_loop=fake_run_loop,
        build_base_system_prompt=lambda context: "base prompt",
    )
    result = executor.run(chat_id=1, user_msg="fix it", context_messages=[], messages=[])

    assert call_log == ["engineering"]
    assert result.pending_action_id == "act_9"


def test_run_loop_may_return_legacy_two_tuple():
    skill = _mk_skill("manager", [])
    registry = MagicMock()
    registry.list.return_value = [skill]
    registry.get.side_effect = lambda n: skill if n == "manager" else None
    router = MagicMock()
    router.pick.return_value = MagicMock(skill="manager", reason="")

    executor = SkillExecutor(
        skill_registry=registry,
        router=router,
        tools={},
        run_loop=MagicMock(return_value=("ok", "end_turn")),
        build_base_system_prompt=lambda context: "base prompt",
    )
    result = executor.run(chat_id=1, user_msg="hi", context_messages=[], messages=[])

    assert result.awaiting_confirmation is False
    assert result.pending_action_id is None
