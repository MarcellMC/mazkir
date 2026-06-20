"""SkillRegistry — loads Mazkir sub-agent skill definitions from markdown files.

A "skill" is a markdown file with YAML frontmatter declaring:

    name: mazkir
    description: Short, one-line summary used by the router
    when_to_use: |
        Multi-line guidance for the router
    tools: [tool_a, tool_b]
    model: claude-haiku-4-5 | claude-sonnet-4-6 | ...
    max_iterations: 3
    next_skills: [time-management, knowledge-management]   # allowed handoff targets

The body of the file becomes the skill's system prompt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import frontmatter

logger = logging.getLogger(__name__)

DEFAULT_MAX_ITERATIONS = 5


@dataclass
class Skill:
    name: str
    description: str
    system_prompt: str
    tools: list[str]
    model: str
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    next_skills: list[str] = field(default_factory=list)
    when_to_use: str = ""
    source_path: Optional[Path] = None


class SkillRegistry:
    """Loads and stores `Skill` definitions from a directory of markdown files."""

    def __init__(self, skills_dir: Path):
        self.skills_dir = Path(skills_dir)
        self._skills: dict[str, Skill] = {}

    def load(self) -> None:
        """Scan `skills_dir` for *.md files and parse them into Skill objects.

        Missing directory, empty directory, and malformed files are all
        non-fatal: a warning is logged and the file is skipped.
        """
        self._skills.clear()

        if not self.skills_dir.exists():
            logger.warning("Skills directory does not exist: %s", self.skills_dir)
            return

        for path in sorted(self.skills_dir.glob("*.md")):
            try:
                post = frontmatter.load(str(path))
            except Exception as e:
                logger.warning("Failed to parse skill %s: %s", path, e)
                continue

            meta = dict(post.metadata)
            required = ("name", "description", "tools", "model")
            if not all(k in meta for k in required):
                logger.warning(
                    "Skill %s missing required frontmatter fields (%s); skipping",
                    path, required,
                )
                continue

            skill = Skill(
                name=meta["name"],
                description=meta["description"],
                system_prompt=post.content.strip(),
                tools=list(meta["tools"]),
                model=meta["model"],
                max_iterations=int(meta.get("max_iterations", DEFAULT_MAX_ITERATIONS)),
                next_skills=list(meta.get("next_skills", [])),
                when_to_use=str(meta.get("when_to_use", "")).strip(),
                source_path=path,
            )
            self._skills[skill.name] = skill

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def list(self) -> list[Skill]:
        return list(self._skills.values())

    def validate(
        self,
        known_tools: set[str],
        known_skills: set[str],
    ) -> list[str]:
        """Return a list of warning messages for unresolved tool / skill references.

        Warnings are logged at WARNING level and also returned so callers can
        surface them in startup logs / health checks.
        """
        warnings: list[str] = []
        for skill in self._skills.values():
            for t in skill.tools:
                if t not in known_tools:
                    msg = f"Skill {skill.name!r} references unknown tool {t!r}"
                    logger.warning(msg)
                    warnings.append(msg)
            for n in skill.next_skills:
                if n not in known_skills:
                    msg = f"Skill {skill.name!r} declares unknown next_skill {n!r}"
                    logger.warning(msg)
                    warnings.append(msg)
        return warnings
