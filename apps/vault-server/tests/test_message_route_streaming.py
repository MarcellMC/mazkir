"""Tests for SSE streaming on the /message endpoint (Task 8 — P5)."""

import json
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# AgentService unit tests — stream_callback threading
# ---------------------------------------------------------------------------

def test_handle_message_accepts_stream_callback(mock_services):
    """stream_callback kwarg is accepted and forwarded into _run_agent_turn."""
    import pytz
    from src.services.agent_service import AgentService, AgentResponse
    from src.services.memory_service import ConversationContext
    from unittest.mock import patch

    claude = mock_services["claude"]
    vault = mock_services["vault"]
    memory = mock_services["memory"]

    memory.assemble_context.return_value = ConversationContext(
        messages=[], summary="", vault_snapshot="", knowledge=""
    )

    agent = AgentService(claude=claude, vault=vault, memory=memory)

    captured_chunks: list[str] = []

    # Patch _handle_message_inner to invoke _stream_callback as if it were
    # the final iteration sending chunks, then return an AgentResponse.
    def fake_inner(text, chat_id, attachments, reply_to, forwarded_from):
        # Simulate the agent flushing chunks via the callback
        if agent._stream_callback is not None:
            agent._stream_callback("chunk1")
            agent._stream_callback("chunk2")
        return AgentResponse(response="done", iterations=1)

    with patch.object(agent, "_handle_message_inner", side_effect=fake_inner):
        result = agent.handle_message(
            text="hi",
            chat_id=1,
            stream_callback=lambda t: captured_chunks.append(t),
        )

    assert result.response == "done"
    assert captured_chunks == ["chunk1", "chunk2"]


def test_stream_callback_cleared_after_call(mock_services):
    """_stream_callback is reset to None after handle_message returns."""
    from src.services.agent_service import AgentService, AgentResponse
    from src.services.memory_service import ConversationContext
    from unittest.mock import patch

    agent = AgentService(
        claude=mock_services["claude"],
        vault=mock_services["vault"],
        memory=mock_services["memory"],
    )
    mock_services["memory"].assemble_context.return_value = ConversationContext(
        messages=[], summary="", vault_snapshot="", knowledge=""
    )

    with patch.object(
        agent,
        "_handle_message_inner",
        return_value=AgentResponse(response="ok", iterations=1),
    ):
        agent.handle_message(text="hi", chat_id=1, stream_callback=lambda t: None)

    assert agent._stream_callback is None


def test_stream_callback_cleared_on_exception(mock_services):
    """_stream_callback is reset even when _handle_message_inner raises."""
    from src.services.agent_service import AgentService
    from src.services.memory_service import ConversationContext
    from unittest.mock import patch

    agent = AgentService(
        claude=mock_services["claude"],
        vault=mock_services["vault"],
        memory=mock_services["memory"],
    )
    mock_services["memory"].assemble_context.return_value = ConversationContext(
        messages=[], summary="", vault_snapshot="", knowledge=""
    )

    with patch.object(
        agent, "_handle_message_inner", side_effect=RuntimeError("boom")
    ):
        try:
            agent.handle_message(text="hi", chat_id=1, stream_callback=lambda t: None)
        except RuntimeError:
            pass

    assert agent._stream_callback is None


# ---------------------------------------------------------------------------
# _run_agent_turn unit test — only final iteration flushes chunks
# ---------------------------------------------------------------------------

def test_run_agent_turn_streams_only_on_end_turn(mock_services):
    """Streaming chunks are forwarded only when stop_reason==end_turn (no tool calls)."""
    from src.services.agent_service import AgentService
    from src.services.memory_service import ConversationContext
    from unittest.mock import patch, MagicMock

    claude = mock_services["claude"]
    vault = mock_services["vault"]
    memory = mock_services["memory"]

    memory.assemble_context.return_value = ConversationContext(
        messages=[], summary="", vault_snapshot="", knowledge=""
    )

    # Make claude.create return an end_turn response and invoke on_chunk.
    def fake_create(system, messages, tools, cache_static_prefix=None,
                    stream=False, on_chunk=None):
        if on_chunk:
            on_chunk("Hello")
            on_chunk(" world")
        fake_resp = MagicMock()
        fake_resp.stop_reason = "end_turn"
        fake_resp.content = [MagicMock(text="Hello world")]
        fake_resp.usage = MagicMock(
            input_tokens=10, output_tokens=2,
            cache_creation_input_tokens=0, cache_read_input_tokens=0,
        )
        return fake_resp

    claude.create.side_effect = fake_create

    agent = AgentService(claude=claude, vault=vault, memory=memory)

    flushed: list[str] = []
    agent._stream_callback = lambda t: flushed.append(t)

    memory.save_turn = MagicMock()

    result = agent._run_agent_turn(
        chat_id=1,
        original_text="hi",
        messages=[{"role": "user", "content": "hi"}],
        system="sys",
        tool_schemas=[],
        max_iterations=10,
    )

    assert flushed == ["Hello", " world"]
    assert result.response == "Hello world"


# ---------------------------------------------------------------------------
# /message route SSE integration tests
# ---------------------------------------------------------------------------

def test_message_route_streams_sse_when_requested():
    """GET /message?stream=true returns SSE text chunks then a done event."""
    from fastapi.testclient import TestClient
    from unittest.mock import patch, MagicMock
    from src.services.agent_service import AgentResponse

    def fake_handle_message(text, chat_id, attachments=None, reply_to=None,
                            forwarded_from=None, stream_callback=None):
        if stream_callback is not None:
            stream_callback("Hello")
            stream_callback(" world")
        return AgentResponse(response="Hello world", iterations=1)

    with patch("src.api.routes.message.get_agent") as mock_get_agent:
        # We need to avoid importing src.main here; the route imports it lazily.
        # Instead patch the import inside the route module directly.
        pass  # patch set up below with nested context

    # Build the app without any real services wired up.
    from fastapi import FastAPI
    from src.api.routes.message import router

    app = FastAPI()
    app.include_router(router)

    agent_mock = MagicMock()
    agent_mock.handle_message.side_effect = fake_handle_message

    with patch("src.api.routes.message.get_agent", return_value=agent_mock):
        client = TestClient(app, raise_server_exceptions=True)
        with client.stream("POST", "/message?stream=true",
                           json={"text": "hi", "chat_id": 1}) as r:
            assert r.status_code == 200
            assert "text/event-stream" in r.headers.get("content-type", "")
            events = []
            for line in r.iter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[len("data: "):]))

    # Should have text chunks + done event
    text_events = [e for e in events if "text" in e]
    done_events = [e for e in events if e.get("done")]
    assert len(text_events) >= 1
    assert len(done_events) == 1
    assert done_events[0]["response"]["response"] == "Hello world"


def test_message_route_non_streaming_unchanged():
    """Without ?stream=true the non-streaming path is used and stream_callback is None."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from unittest.mock import patch, MagicMock
    from src.services.agent_service import AgentResponse

    received_callback: list = []

    def fake_handle_message(text, chat_id, attachments=None, reply_to=None,
                            forwarded_from=None, stream_callback=None):
        received_callback.append(stream_callback)
        return AgentResponse(response="ok", iterations=1)

    from src.api.routes.message import router
    app = FastAPI()
    app.include_router(router)

    agent_mock = MagicMock()
    agent_mock.handle_message.side_effect = fake_handle_message

    with patch("src.api.routes.message.get_agent", return_value=agent_mock):
        client = TestClient(app)
        r = client.post("/message", json={"text": "hi", "chat_id": 1})

    assert r.status_code == 200
    assert r.json()["response"] == "ok"
    # Non-streaming path must NOT pass a stream_callback
    assert len(received_callback) == 1
    assert received_callback[0] is None
