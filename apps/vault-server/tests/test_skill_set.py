"""Guards the real skill set in memory/00-system/skills/ against the live tool registry."""
from pathlib import Path
from unittest.mock import Mock

from src.config import settings
from src.services.agent_service import AgentService
from src.services.skill_registry import SkillRegistry

EXPECTED = {"mazkir", "time-management", "knowledge-management", "motivation-management", "engineering"}


def _registry() -> SkillRegistry:
    r = SkillRegistry(skills_dir=settings.skills_dir)
    r.load()
    return r


def _known_tools() -> set[str]:
    agent = AgentService(
        claude=Mock(), vault=Mock(), memory=Mock(),
        calendar=Mock(), events=Mock(), media_path=Path("/tmp/mazkir-test-media"),
    )
    return set(agent.tools.keys())


def test_real_skill_set_loads():
    names = {s.name for s in _registry().list()}
    assert names == EXPECTED, f"got {names}"


def test_mazkir_is_conversational_with_read_tools():
    m = _registry().get("mazkir")
    assert m is not None
    assert "read_knowledge" in m.tools
    assert "search_knowledge" in m.tools


def test_time_management_has_event_and_task_tools():
    t = _registry().get("time-management")
    assert t is not None
    assert "create_event" in t.tools
    assert "create_task" in t.tools
    # A tool registered in AgentService but absent from every skill's
    # `tools:` frontmatter is unreachable through the skill loop, which is
    # the live dispatch path. `delete_event` shipped in exactly that state
    # because the container that added it could not mount the vault.
    assert "update_event" in t.tools
    assert "delete_event" in t.tools
    assert "list_events" in t.tools


def test_knowledge_management_can_read_and_save():
    k = _registry().get("knowledge-management")
    assert k is not None
    assert "read_knowledge" in k.tools
    assert "save_knowledge" in k.tools


def test_skills_reference_only_known_tools_and_skills():
    registry = _registry()
    warnings = registry.validate(_known_tools(), {s.name for s in registry.list()})
    assert warnings == [], warnings


def test_engineering_can_propose_coding_sessions():
    e = _registry().get("engineering")
    assert e is not None
    assert "propose_coding_session" in e.tools
