"""Tests for SkillRegistry — parses skill markdown files from vault."""

import pytest
from pathlib import Path

from src.services.skill_registry import Skill, SkillRegistry


def _write_skill(dir: Path, name: str, content: str) -> Path:
    dir.mkdir(parents=True, exist_ok=True)
    path = dir / f"{name}.md"
    path.write_text(content)
    return path


SAMPLE_CAPTURE = """---
name: capture
description: Fast inbox-style captures
when_to_use: |
  - User dumps text or a photo with no clear intent
tools: [save_knowledge, create_task]
model: claude-haiku-4-5
max_iterations: 3
next_skills: [manager, recall]
---

# Capture skill system prompt

You receive quick captures from the user.
"""


def test_registry_loads_skill_from_markdown(tmp_path):
    _write_skill(tmp_path, "capture", SAMPLE_CAPTURE)
    registry = SkillRegistry(skills_dir=tmp_path)
    registry.load()

    skill = registry.get("capture")
    assert isinstance(skill, Skill)
    assert skill.name == "capture"
    assert skill.description == "Fast inbox-style captures"
    assert skill.tools == ["save_knowledge", "create_task"]
    assert skill.model == "claude-haiku-4-5"
    assert skill.max_iterations == 3
    assert skill.next_skills == ["manager", "recall"]
    assert "You receive quick captures" in skill.system_prompt


def test_registry_lists_all_skills(tmp_path):
    _write_skill(tmp_path, "capture", SAMPLE_CAPTURE)
    _write_skill(tmp_path, "recall", SAMPLE_CAPTURE.replace("capture", "recall"))
    registry = SkillRegistry(skills_dir=tmp_path)
    registry.load()
    names = sorted(s.name for s in registry.list())
    assert names == ["capture", "recall"]


def test_registry_get_missing_returns_none(tmp_path):
    registry = SkillRegistry(skills_dir=tmp_path)
    registry.load()
    assert registry.get("nonexistent") is None


def test_registry_load_empty_dir_succeeds(tmp_path):
    registry = SkillRegistry(skills_dir=tmp_path)
    registry.load()
    assert registry.list() == []


def test_registry_load_missing_dir_succeeds(tmp_path):
    registry = SkillRegistry(skills_dir=tmp_path / "does-not-exist")
    registry.load()  # warns but does not raise
    assert registry.list() == []


def test_registry_skips_invalid_frontmatter(tmp_path):
    (tmp_path / "broken.md").write_text("not valid frontmatter")
    registry = SkillRegistry(skills_dir=tmp_path)
    registry.load()
    assert registry.get("broken") is None


def test_skill_defaults_when_optional_fields_absent(tmp_path):
    minimal = """---
name: minimal
description: A test skill
tools: []
model: claude-haiku-4-5
---

Body.
"""
    _write_skill(tmp_path, "minimal", minimal)
    registry = SkillRegistry(skills_dir=tmp_path)
    registry.load()
    skill = registry.get("minimal")
    assert skill.max_iterations == 5  # default
    assert skill.next_skills == []     # default
    assert skill.when_to_use == ""     # default


def test_validate_warns_on_unknown_tool(tmp_path, caplog):
    content = """---
name: bad
description: refs missing tool
tools: [nonexistent_tool]
model: claude-haiku-4-5
---
body
"""
    _write_skill(tmp_path, "bad", content)
    registry = SkillRegistry(skills_dir=tmp_path)
    registry.load()
    known_tools = {"save_knowledge", "create_task"}
    with caplog.at_level("WARNING"):
        warnings = registry.validate(known_tools=known_tools, known_skills={"bad"})
    assert any("nonexistent_tool" in w for w in warnings)


def test_validate_warns_on_unknown_next_skill(tmp_path):
    content = """---
name: bad
description: bad handoff target
tools: [save_knowledge]
model: claude-haiku-4-5
next_skills: [missing_skill]
---
body
"""
    _write_skill(tmp_path, "bad", content)
    registry = SkillRegistry(skills_dir=tmp_path)
    registry.load()
    warnings = registry.validate(known_tools={"save_knowledge"}, known_skills={"bad"})
    assert any("missing_skill" in w for w in warnings)


def test_validate_passes_when_references_resolve(tmp_path):
    content = """---
name: ok
description: ok
tools: [save_knowledge]
model: claude-haiku-4-5
next_skills: []
---
body
"""
    _write_skill(tmp_path, "ok", content)
    registry = SkillRegistry(skills_dir=tmp_path)
    registry.load()
    warnings = registry.validate(known_tools={"save_knowledge"}, known_skills={"ok"})
    assert warnings == []
