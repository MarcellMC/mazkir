"""Thin wrapper around the Anthropic Claude API."""

import anthropic


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
    ) -> anthropic.types.Message:
        """Claude API call with tool-use support.

        Args:
            system: System prompt.
            messages: Conversation messages.
            tools: Tool definitions (optional).
            model: Model to use.
            max_tokens: Max tokens in response.

        Returns:
            Raw Anthropic Message response.
        """
        kwargs: dict = {
            "model": model,
            "system": system,
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
