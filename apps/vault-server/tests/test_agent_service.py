"""Tests for AgentService — tool registry, confidence gate, loop control."""

from unittest.mock import MagicMock

import pytest

from src.services.agent_service import AgentService, AgentResponse, CONFIDENCE_THRESHOLD


@pytest.fixture
def mock_services(tmp_path):
    """Create mock service dependencies."""
    claude = MagicMock()
    vault = MagicMock()
    memory = MagicMock()
    calendar = MagicMock()

    # Set vault_path so data_path resolves
    vault.vault_path = tmp_path / "vault"
    vault.vault_path.mkdir()

    from src.services.memory_service import ConversationContext
    memory.assemble_context.return_value = ConversationContext(
        messages=[],
        summary="",
        vault_snapshot="No data.",
        knowledge="",
    )
    memory.save_turn = MagicMock()
    memory.summarize_and_decay = MagicMock()

    return claude, vault, memory, calendar


@pytest.fixture
def agent(mock_services):
    claude, vault, memory, calendar = mock_services
    return AgentService(
        claude=claude, vault=vault, memory=memory, calendar=calendar,
    )


class TestToolRegistry:
    def test_tools_are_registered(self, agent):
        assert len(agent.tools) > 0

    def test_all_tools_have_required_fields(self, agent):
        for name, tool in agent.tools.items():
            assert "schema" in tool
            assert "handler" in tool
            assert "risk" in tool
            assert tool["risk"] in ("safe", "write", "destructive")

    def test_safe_tools_exist(self, agent):
        safe = [n for n, t in agent.tools.items() if t["risk"] == "safe"]
        assert "list_tasks" in safe
        assert "list_habits" in safe
        assert "search_knowledge" in safe

    def test_destructive_tools_exist(self, agent):
        destructive = [n for n, t in agent.tools.items() if t["risk"] == "destructive"]
        assert "complete_task" in destructive
        assert "complete_habit" in destructive


class TestConfidenceGate:
    def test_safe_tools_always_pass(self, agent):
        assert agent._check_confidence("list_tasks", {}) is True

    def test_write_tool_passes_with_high_confidence(self, agent):
        params = {"name": "test", "_confidence": 0.95, "_reasoning": "clear intent"}
        assert agent._check_confidence("create_task", params) is True
        assert "_confidence" not in params
        assert "_reasoning" not in params

    def test_write_tool_fails_with_low_confidence(self, agent):
        params = {"name": "test", "_confidence": 0.5, "_reasoning": "unsure"}
        assert agent._check_confidence("create_task", params) is False

    def test_destructive_tool_fails_with_low_confidence(self, agent):
        params = {"task_name": "buy milk", "_confidence": 0.6, "_reasoning": "maybe"}
        assert agent._check_confidence("complete_task", params) is False

    def test_missing_confidence_defaults_low(self, agent):
        params = {"task_name": "test"}
        assert agent._check_confidence("complete_task", params) is False

    def test_confidence_at_threshold_passes(self, agent):
        params = {"name": "test", "_confidence": CONFIDENCE_THRESHOLD}
        assert agent._check_confidence("create_task", params) is True


class TestAgentResponse:
    def test_response_dataclass(self):
        r = AgentResponse(response="hello")
        assert r.response == "hello"
        assert r.awaiting_confirmation is False
        assert r.pending_action_id is None

    def test_confirmation_response(self):
        r = AgentResponse(
            response="Confirm?",
            awaiting_confirmation=True,
            pending_action_id="abc123",
        )
        assert r.awaiting_confirmation is True
        assert r.pending_action_id == "abc123"


class TestHandleMessage:
    def test_simple_text_response(self, agent, mock_services):
        claude = mock_services[0]
        memory = mock_services[2]

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Hello! How can I help?"
        mock_response.content = [text_block]
        claude.create.return_value = mock_response

        result = agent.handle_message("hello", chat_id=123)

        assert result.response == "Hello! How can I help?"
        assert result.awaiting_confirmation is False
        memory.save_turn.assert_called_once()

    def test_tool_call_then_response(self, agent, mock_services):
        claude = mock_services[0]
        vault = mock_services[1]

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "list_tasks"
        tool_block.id = "tool_123"
        tool_block.input = {}
        mock_tool_response = MagicMock()
        mock_tool_response.stop_reason = "tool_use"
        mock_tool_response.content = [tool_block]

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "You have 2 tasks."
        mock_text_response = MagicMock()
        mock_text_response.stop_reason = "end_turn"
        mock_text_response.content = [text_block]

        claude.create.side_effect = [mock_tool_response, mock_text_response]

        vault.list_active_tasks.return_value = [
            {"path": "40-tasks/active/buy-milk.md", "metadata": {"name": "Buy milk"}},
        ]

        result = agent.handle_message("what tasks do I have?", chat_id=123)

        assert result.response == "You have 2 tasks."
        assert claude.create.call_count == 2

    def test_low_confidence_triggers_confirmation(self, agent, mock_services):
        claude = mock_services[0]

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "complete_task"
        tool_block.id = "tool_456"
        tool_block.input = {"task_name": "something", "_confidence": 0.4, "_reasoning": "vague"}
        mock_response = MagicMock()
        mock_response.stop_reason = "tool_use"
        mock_response.content = [tool_block]

        claude.create.return_value = mock_response

        result = agent.handle_message("maybe finish that thing", chat_id=123)

        assert result.awaiting_confirmation is True
        assert result.pending_action_id is not None

    def test_max_iterations_safety(self, agent, mock_services):
        claude = mock_services[0]
        vault = mock_services[1]
        agent.max_iterations = 2

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "list_tasks"
        tool_block.id = "tool_loop"
        tool_block.input = {}
        mock_response = MagicMock()
        mock_response.stop_reason = "tool_use"
        mock_response.content = [tool_block]

        vault.list_active_tasks.return_value = []
        claude.create.return_value = mock_response

        result = agent.handle_message("loop forever", chat_id=123)

        assert claude.create.call_count == 2
        assert result.response is not None


class TestHandleMessageWithAttachments:
    def test_photo_saved_to_disk(self, agent, mock_services, tmp_path):
        """Photo attachment is saved to data/media/{date}/ directory."""
        claude = mock_services[0]

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Photo saved!"
        mock_response.content = [text_block]
        claude.create.return_value = mock_response

        import base64
        photo_bytes = base64.b64encode(b"fake-image-data").decode()

        result = agent.handle_message(
            text="Save this",
            chat_id=123,
            attachments=[{
                "type": "photo",
                "data": photo_bytes,
                "mime_type": "image/jpeg",
                "filename": "photo_2026-03-04_14-30-00.jpg",
            }],
        )

        assert result.response == "Photo saved!"
        # Verify Claude was called with image content block
        call_args = claude.create.call_args
        messages = call_args.kwargs.get("messages", call_args[1].get("messages") if len(call_args) > 1 else None)
        last_user_msg = [m for m in messages if m["role"] == "user"][-1]
        # Content should be a list (multi-block) when photo is present
        assert isinstance(last_user_msg["content"], list)

    def test_location_included_in_text(self, agent, mock_services):
        """Location coordinates appear in the text sent to Claude."""
        claude = mock_services[0]

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Location noted!"
        mock_response.content = [text_block]
        claude.create.return_value = mock_response

        result = agent.handle_message(
            text="I'm here",
            chat_id=123,
            attachments=[{
                "type": "location",
                "latitude": 32.08,
                "longitude": 34.78,
            }],
        )

        assert result.response == "Location noted!"
        call_args = claude.create.call_args
        messages = call_args.kwargs.get("messages", call_args[1].get("messages") if len(call_args) > 1 else None)
        last_user_msg = [m for m in messages if m["role"] == "user"][-1]
        content = last_user_msg["content"]
        # Should contain location coordinates in text
        if isinstance(content, list):
            text_parts = [b["text"] for b in content if b.get("type") == "text"]
            assert any("32.08" in t and "34.78" in t for t in text_parts)
        else:
            assert "32.08" in content and "34.78" in content

    def test_reply_context_included(self, agent, mock_services):
        """Reply context appears in the text sent to Claude."""
        claude = mock_services[0]

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Got it!"
        mock_response.content = [text_block]
        claude.create.return_value = mock_response

        result = agent.handle_message(
            text="yes do it",
            chat_id=123,
            reply_to={"text": "Should I create the task?", "from": "assistant"},
        )

        call_args = claude.create.call_args
        messages = call_args.kwargs.get("messages", call_args[1].get("messages") if len(call_args) > 1 else None)
        last_user_msg = [m for m in messages if m["role"] == "user"][-1]
        content = last_user_msg["content"]
        text_content = content if isinstance(content, str) else " ".join(
            b.get("text", "") for b in content if isinstance(b, dict)
        )
        assert "Should I create the task?" in text_content

    def test_plain_text_still_works(self, agent, mock_services):
        """Existing text-only flow is unchanged."""
        claude = mock_services[0]

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Hello!"
        mock_response.content = [text_block]
        claude.create.return_value = mock_response

        result = agent.handle_message("hello", chat_id=123)
        assert result.response == "Hello!"


    def test_photo_exif_extracted_and_surfaced(self, agent, mock_services, tmp_path):
        """EXIF metadata is extracted and included in Claude context."""
        claude = mock_services[0]

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Nice photo!"
        mock_response.content = [text_block]
        claude.create.return_value = mock_response

        # Create a JPEG with EXIF GPS data
        from tests.test_exif_service import _make_jpeg_with_gps
        import base64
        photo_data = base64.b64encode(_make_jpeg_with_gps(32.0853, 34.7818)).decode()

        result = agent.handle_message(
            text="Check this out",
            chat_id=123,
            attachments=[{
                "type": "photo",
                "data": photo_data,
                "mime_type": "image/jpeg",
                "filename": "photo_test.jpg",
            }],
        )

        # Verify EXIF info surfaced in the text sent to Claude
        call_args = claude.create.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
        last_user = [m for m in messages if m["role"] == "user"][-1]
        content = last_user["content"]
        text_parts = [b["text"] for b in content if b.get("type") == "text"]
        combined = " ".join(text_parts)
        assert "32.08" in combined  # GPS lat
        assert "34.78" in combined  # GPS lng

    def test_photo_metadata_json_written(self, agent, mock_services, tmp_path):
        """Sidecar metadata.json is written when photo is saved."""
        claude = mock_services[0]

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Got it!"
        mock_response.content = [text_block]
        claude.create.return_value = mock_response

        import base64
        from PIL import Image
        import io
        img = Image.new("RGB", (10, 10), "red")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        photo_data = base64.b64encode(buf.getvalue()).decode()

        agent.handle_message(
            text="photo",
            chat_id=123,
            attachments=[{
                "type": "photo",
                "data": photo_data,
                "mime_type": "image/jpeg",
                "filename": "test_meta.jpg",
            }],
        )

        # Find the metadata.json in the media directory
        import json
        media_path = agent.data_path / "media"
        meta_files = list(media_path.rglob("metadata.json"))
        assert len(meta_files) == 1
        entries = json.loads(meta_files[0].read_text())
        assert len(entries) == 1
        assert entries[0]["filename"] == "test_meta.jpg"


class TestAttachToDaily:
    def test_attach_to_daily_tool_registered(self, agent):
        assert "attach_to_daily" in agent.tools
        assert agent.tools["attach_to_daily"]["risk"] == "write"

    def test_attach_to_daily_appends_to_note(self, agent, mock_services):
        vault = mock_services[1]

        vault.append_to_daily_section.return_value = {
            "path": "10-daily/2026-03-04.md",
            "section": "Notes",
        }

        result = agent._tool_attach_to_daily({
            "vault_path": "data/media/2026-03-04/photo_2026-03-04_14-30-00.jpg",
            "caption": "Dog walk stop",
            "wikilinks": ["City Watch"],
            "section": "Notes",
        })

        assert "path" in result
        vault.append_to_daily_section.assert_called_once()

    def test_attach_to_daily_with_location(self, agent, mock_services):
        vault = mock_services[1]

        vault.append_to_daily_section.return_value = {
            "path": "10-daily/2026-03-04.md",
            "section": "Notes",
        }

        result = agent._tool_attach_to_daily({
            "vault_path": "data/media/2026-03-04/photo.jpg",
            "caption": "Street photo",
            "location": {"lat": 32.08, "lng": 34.78, "name": "Tel Aviv"},
            "section": "Notes",
        })

        assert "path" in result
        call_args = vault.append_to_daily_section.call_args
        content = call_args.kwargs.get("content") or call_args[0][1] if len(call_args[0]) > 1 else call_args.kwargs["content"]
        assert "32.08" in content
