"""Tests for Anthropic prompt caching on the static prefix."""

from unittest.mock import MagicMock


def test_claude_create_sends_cache_control_when_static_prefix_provided():
    from src.services.claude_service import ClaudeService
    cs = ClaudeService.__new__(ClaudeService)
    cs.client = MagicMock()
    cs.client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="ok")],
        stop_reason="end_turn",
        usage=MagicMock(
            cache_creation_input_tokens=12,
            cache_read_input_tokens=0,
            input_tokens=100,
            output_tokens=10,
        ),
    )

    cs.create(
        system="dynamic tail",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        cache_static_prefix="big static thing",
    )

    args, kwargs = cs.client.messages.create.call_args
    system_blocks = kwargs["system"]
    assert isinstance(system_blocks, list)
    assert system_blocks[0]["text"] == "big static thing"
    assert system_blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert system_blocks[1]["text"] == "dynamic tail"
    assert "cache_control" not in system_blocks[1]


def test_claude_create_falls_back_to_string_when_no_prefix():
    """When no cache prefix, the system arg is a plain string (existing behavior)."""
    from src.services.claude_service import ClaudeService
    cs = ClaudeService.__new__(ClaudeService)
    cs.client = MagicMock()
    cs.client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="ok")], stop_reason="end_turn",
        usage=MagicMock(input_tokens=100, output_tokens=10),
    )

    cs.create(system="just a string", messages=[{"role": "user", "content": "hi"}], tools=[])

    args, kwargs = cs.client.messages.create.call_args
    assert kwargs["system"] == "just a string"
