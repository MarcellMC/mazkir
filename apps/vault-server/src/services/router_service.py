"""RouterService — classifies a user message and picks one Skill to handle it.

The router is a small Haiku LLM call. It receives the user message + recent
conversation tail + the skill catalog (name, description, when_to_use), and
returns a single skill name. On any error or unknown response, falls back to
the configured fallback skill (typically "manager", the broadest toolbox).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.services.skill_registry import Skill

logger = logging.getLogger(__name__)


@dataclass
class RouterDecision:
    skill: str
    reason: str


class RouterService:
    def __init__(self, claude, fallback_skill: str = "manager"):
        self.claude = claude
        self.fallback_skill = fallback_skill

    def pick(
        self,
        user_msg: str,
        recent_messages: list[dict],
        skills: list[Skill],
    ) -> RouterDecision:
        catalog = [
            {
                "name": s.name,
                "description": s.description,
                "when_to_use": s.when_to_use,
            }
            for s in skills
        ]
        known = {s.name for s in skills}

        try:
            choice = self.claude.create_router_choice(
                user_msg=user_msg,
                recent_messages=recent_messages,
                skill_catalog=catalog,
            )
        except Exception as e:
            logger.warning("Router LLM call failed: %s — falling back to %s", e, self.fallback_skill)
            return RouterDecision(
                skill=self.fallback_skill,
                reason=f"fallback: router error ({e})",
            )

        picked = choice.get("skill")
        reason = choice.get("reason", "")

        if picked not in known:
            logger.warning(
                "Router picked unknown skill %r — falling back to %s",
                picked, self.fallback_skill,
            )
            return RouterDecision(
                skill=self.fallback_skill,
                reason=f"fallback: router picked unknown skill {picked!r}",
            )

        return RouterDecision(skill=picked, reason=reason)
