"""Skill loop orchestrator.

Owns the router→skill→handoff flow that used to live inline in
`AgentService._handle_via_skills`. The executor depends on injectable
collaborators (run_loop, build_base_system_prompt) so it can be unit-tested
without spinning up the whole agent.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from opentelemetry import trace as _otel_trace

from src.services.skill_registry import Skill

logger = logging.getLogger(__name__)

MAX_HOPS = 3

_tracer = _otel_trace.get_tracer("mazkir.skill_executor")


@dataclass
class SkillExecutorResult:
    response_text: str
    stop_reason: str
    iterations: int
    visited: list[str]


RunLoopFn = Callable[..., tuple[str, str]]
BuildBaseSystemPromptFn = Callable[[Any], str]


class SkillExecutor:
    """Runs the router→skill→handoff loop for skill-aware agent dispatch."""

    def __init__(
        self,
        *,
        skill_registry: Any,
        router: Any,
        tools: dict,
        run_loop: RunLoopFn,
        build_base_system_prompt: BuildBaseSystemPromptFn,
    ):
        self.skill_registry = skill_registry
        self.router = router
        self.tools = tools
        self._run_loop = run_loop
        self._build_base_system_prompt = build_base_system_prompt

    def run(
        self,
        *,
        chat_id: int,
        user_msg: str,
        context_messages: list[dict],
        messages: list[dict],
        context: Optional[Any] = None,
    ) -> SkillExecutorResult:
        """Route to a skill via the router and run with handoff support (MAX_HOPS cap)."""
        skills = self.skill_registry.list()
        decision = self.router.pick(
            user_msg=user_msg,
            recent_messages=context_messages[-10:],
            skills=skills,
        )

        visited: list[str] = []
        response_text = ""
        stop_reason = "end_turn"
        active: Optional[str] = decision.skill
        previous: Optional[str] = None
        reason: str = decision.reason

        while active and len(visited) < MAX_HOPS:
            if active in visited:
                logger.warning("Skill cycle detected — stopping at %s", active)
                break
            visited.append(active)

            skill = self.skill_registry.get(active)
            if skill is None:
                logger.warning("Router/handoff requested unknown skill %r", active)
                break

            tool_schemas = self._skill_tool_schemas(skill)
            system = self._build_skill_system_prompt(skill, context)

            with _tracer.start_as_current_span(
                f"skill.{skill.name}",
                attributes={
                    "skill.name": skill.name,
                    "skill.previous": previous or "",
                    "skill.routing_reason": reason,
                },
            ) as span:
                response_text, stop_reason = self._run_loop(
                    chat_id=chat_id,
                    log_text=user_msg,
                    messages=messages,
                    system=system,
                    tool_schemas=tool_schemas,
                    max_iterations=skill.max_iterations,
                )

                next_skill = self._extract_next_skill(response_text, skill.next_skills)
                if next_skill:
                    span.set_attribute("skill.next_skill", next_skill)

            if next_skill:
                previous = active
                active = next_skill
                reason = f"handoff from {previous}"
            else:
                active = None

        return SkillExecutorResult(
            response_text=response_text,
            stop_reason=stop_reason,
            iterations=len(visited),
            visited=visited,
        )

    def _skill_tool_schemas(self, skill: Skill) -> list[dict]:
        """Build the tool-schema list for a specific skill."""
        return [self.tools[t]["schema"] for t in skill.tools if t in self.tools]

    def _build_skill_system_prompt(self, skill: Skill, context: Any) -> str:
        """Prepend the skill's own system prompt to the base vault prompt."""
        base = self._build_base_system_prompt(context)
        return f"{skill.system_prompt}\n\n{base}"

    @staticmethod
    def _extract_next_skill(response_text: str, allowed: list[str]) -> Optional[str]:
        """Parse 'next_skill: <name>' from response_text if name is allowed."""
        m = re.search(r"next_skill:\s*([a-z_-]+)", response_text)
        if not m:
            return None
        name = m.group(1)
        if name not in allowed:
            logger.warning(
                "Skill emitted next_skill=%r not in allowed=%r", name, allowed
            )
            return None
        return name
