"""Tests for streaming response from ClaudeService."""

from unittest.mock import MagicMock


def test_create_with_stream_returns_iterator_and_forwards_chunks():
    from src.services.claude_service import ClaudeService

    cs = ClaudeService.__new__(ClaudeService)
    cs.client = MagicMock()

    fake_events = [
        MagicMock(type="content_block_delta", delta=MagicMock(type="text_delta", text="Hello")),
        MagicMock(type="content_block_delta", delta=MagicMock(type="text_delta", text=" world")),
        MagicMock(type="message_stop"),
    ]
    fake_stream = MagicMock()
    fake_stream.__enter__ = MagicMock(return_value=fake_stream)
    fake_stream.__exit__ = MagicMock(return_value=None)
    fake_stream.__iter__ = MagicMock(return_value=iter(fake_events))
    fake_stream.get_final_message = MagicMock(return_value=MagicMock(
        content=[MagicMock(text="Hello world")],
        stop_reason="end_turn",
        usage=MagicMock(input_tokens=10, output_tokens=2,
                        cache_creation_input_tokens=0, cache_read_input_tokens=0),
    ))
    cs.client.messages.stream = MagicMock(return_value=fake_stream)

    chunks = []
    response = cs.create(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        stream=True,
        on_chunk=lambda text: chunks.append(text),
    )

    assert chunks == ["Hello", " world"]
    assert response.stop_reason == "end_turn"


def test_create_without_stream_unchanged_behavior():
    from src.services.claude_service import ClaudeService

    cs = ClaudeService.__new__(ClaudeService)
    cs.client = MagicMock()
    cs.client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="ok")], stop_reason="end_turn",
        usage=MagicMock(input_tokens=10, output_tokens=2),
    )

    chunks = []
    cs.create(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        on_chunk=lambda t: chunks.append(t),
    )
    assert chunks == []
    cs.client.messages.create.assert_called_once()
    cs.client.messages.stream.assert_not_called()
