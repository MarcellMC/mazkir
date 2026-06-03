"""Thin wrapper around the Anthropic Claude API."""

import json
import logging
import re

import anthropic

logger = logging.getLogger(__name__)


class ClaudeService:
    """Claude API client for tool-use and simple completions."""

    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)

    def create(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 4096,
        *,
        cache_static_prefix: str | None = None,
    ) -> anthropic.types.Message:
        """Claude API call with tool-use support.

        Args:
            system: Dynamic system prompt tail (current date, vault snapshot).
            messages: Conversation messages.
            tools: Tool definitions (optional).
            model: Model to use.
            max_tokens: Max tokens in response.
            cache_static_prefix: Static system prompt prefix (skill instructions +
                base guidelines + tool docs).  When provided the system arg is sent
                as a two-block list: the static prefix with ``cache_control`` set to
                ``{"type": "ephemeral"}`` followed by the dynamic tail without
                caching.  This enables Anthropic prompt caching (~10 % input cost
                reduction on cache hits).  When omitted the system arg is forwarded
                as-is (plain string — existing behaviour).

        Returns:
            Raw Anthropic Message response.
        """
        if cache_static_prefix is not None:
            system_arg: str | list[dict] = [
                {
                    "type": "text",
                    "text": cache_static_prefix,
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "text",
                    "text": system,
                },
            ]
        else:
            system_arg = system

        kwargs: dict = {
            "model": model,
            "system": system_arg,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
        return self.client.messages.create(**kwargs)

    def complete(
        self,
        prompt: str,
        system: str = "",
        model: str = "claude-haiku-4-5-20251001",
        max_tokens: int = 1024,
    ) -> str:
        """Simple single-turn completion. Used for summarization, etc.

        Args:
            prompt: User prompt.
            system: System prompt (optional).
            model: Model to use (defaults to Haiku for cost).
            max_tokens: Max tokens.

        Returns:
            Claude's response as plain text.
        """
        response = self.client.messages.create(
            model=model,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
        return response.content[0].text

    def create_router_choice(
        self,
        user_msg: str,
        recent_messages: list[dict],
        skill_catalog: list[dict],
    ) -> dict:
        """Call Haiku with a structured prompt asking for a single skill name.

        Returns {"skill": <name>, "reason": <short string>}.
        """
        catalog_lines = "\n".join(
            f"- {s['name']}: {s['description']}\n  use when: {s['when_to_use']}"
            for s in skill_catalog
        )
        system = (
            "You are a router for the Mazkir personal assistant. "
            "Pick exactly one skill to handle the user's message.\n\n"
            f"Available skills:\n{catalog_lines}\n\n"
            "Respond as a JSON object: {\"skill\": \"<name>\", \"reason\": \"<one short sentence>\"}. "
            "Pick the single best match. When uncertain, pick 'manager'."
        )
        msgs = list(recent_messages) + [{"role": "user", "content": user_msg}]

        response = self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=128,
            system=system,
            messages=msgs,
        )
        text = response.content[0].text.strip()
        # Extract the first JSON object, ignoring any surrounding markdown fences
        # or trailing prose the model may append.
        m = re.search(r"\{.*?\}", text, re.DOTALL)
        if m:
            text = m.group(0)
        return json.loads(text)
