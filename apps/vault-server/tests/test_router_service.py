"""Tests for RouterService — picks a skill given user message + skill list."""

from unittest.mock import MagicMock

import pytest

from src.services.router_service import RouterService, RouterDecision
from src.services.skill_registry import Skill


def _mk_skill(name: str, desc: str = "", when_to_use: str = "") -> Skill:
    return Skill(
        name=name,
        description=desc,
        system_prompt="",
        tools=[],
        model="claude-haiku-4-5",
        when_to_use=when_to_use,
    )


@pytest.fixture
def skills():
    return [
        _mk_skill("capture", "Fast inbox captures"),
        _mk_skill("manager", "Deliberate planning"),
        _mk_skill("recall", "Read-only retrieval"),
    ]


def test_router_returns_skill_picked_by_llm(skills):
    claude = MagicMock()
    claude.create_router_choice.return_value = {
        "skill": "manager",
        "reason": "user asked to complete multiple tasks",
    }
    router = RouterService(claude=claude, fallback_skill="manager")
    decision = router.pick("Complete all my P1 tasks", recent_messages=[], skills=skills)
    assert isinstance(decision, RouterDecision)
    assert decision.skill == "manager"
    assert "complete" in decision.reason.lower()


def test_router_falls_back_when_llm_returns_unknown_skill(skills):
    claude = MagicMock()
    claude.create_router_choice.return_value = {"skill": "nonsense", "reason": "x"}
    router = RouterService(claude=claude, fallback_skill="manager")
    decision = router.pick("foo", recent_messages=[], skills=skills)
    assert decision.skill == "manager"
    assert "fallback" in decision.reason.lower()


def test_router_falls_back_when_llm_errors(skills):
    claude = MagicMock()
    claude.create_router_choice.side_effect = RuntimeError("LLM down")
    router = RouterService(claude=claude, fallback_skill="manager")
    decision = router.pick("foo", recent_messages=[], skills=skills)
    assert decision.skill == "manager"
    assert "fallback" in decision.reason.lower()


def test_router_passes_skill_descriptions_to_llm(skills):
    claude = MagicMock()
    claude.create_router_choice.return_value = {"skill": "capture", "reason": "ok"}
    router = RouterService(claude=claude, fallback_skill="manager")
    router.pick("save this", recent_messages=[], skills=skills)

    args, kwargs = claude.create_router_choice.call_args
    payload = kwargs.get("skill_catalog") or (args[1] if len(args) > 1 else None)
    assert payload is not None
    names = [s["name"] for s in payload]
    assert "capture" in names
    assert "manager" in names
    assert "recall" in names
