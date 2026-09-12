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
    events = MagicMock()

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

    vault.read_daily_note.return_value = {"content": ""}

    return claude, vault, memory, calendar, events


@pytest.fixture
def agent(mock_services, tmp_path):
    claude, vault, memory, calendar, events = mock_services
    return AgentService(
        claude=claude, vault=vault, memory=memory, calendar=calendar, events=events,
        media_path=tmp_path / "media",
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
        score, action = agent._check_confidence("list_tasks", {})
        assert action == "auto_execute"

    def test_write_tool_passes_with_high_confidence(self, agent):
        params = {"name": "test", "_confidence": 0.95, "_reasoning": "clear intent"}
        score, action = agent._check_confidence("create_task", params)
        assert action == "auto_execute"
        assert score == 0.95
        assert "_confidence" not in params
        assert "_reasoning" not in params

    def test_write_tool_fails_with_low_confidence(self, agent):
        params = {"name": "test", "_confidence": 0.5, "_reasoning": "unsure"}
        _, action = agent._check_confidence("create_task", params)
        assert action == "needs_confirmation"

    def test_destructive_tool_fails_with_low_confidence(self, agent):
        params = {"task_name": "buy milk", "_confidence": 0.6, "_reasoning": "maybe"}
        _, action = agent._check_confidence("complete_task", params)
        assert action == "needs_confirmation"

    def test_missing_confidence_defaults_low(self, agent):
        params = {"task_name": "test"}
        score, action = agent._check_confidence("complete_task", params)
        assert action == "needs_confirmation"
        assert score == 0.0

    def test_confidence_at_threshold_passes(self, agent):
        # write tools have threshold 0.85; CONFIDENCE_THRESHOLD == 0.85 still passes
        params = {"name": "test", "_confidence": CONFIDENCE_THRESHOLD}
        _, action = agent._check_confidence("create_task", params)
        assert action == "auto_execute"


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
        meta_files = list(agent.media_path.rglob("metadata.json"))
        assert len(meta_files) == 1
        entries = json.loads(meta_files[0].read_text())
        assert len(entries) == 1
        assert entries[0]["filename"] == "test_meta.jpg"


class TestDeleteArchiveTools:
    def test_delete_task_tool_registered(self, agent):
        assert "delete_task" in agent.tools
        assert agent.tools["delete_task"]["risk"] == "destructive"

    def test_archive_task_tool_registered(self, agent):
        assert "archive_task" in agent.tools
        assert agent.tools["archive_task"]["risk"] == "destructive"

    def test_delete_habit_tool_registered(self, agent):
        assert "delete_habit" in agent.tools
        assert agent.tools["delete_habit"]["risk"] == "destructive"

    def test_archive_goal_tool_registered(self, agent):
        assert "archive_goal" in agent.tools
        assert agent.tools["archive_goal"]["risk"] == "destructive"

    def test_delete_task_calls_vault(self, agent, mock_services):
        vault = mock_services[1]
        vault.list_active_tasks.return_value = [
            {"path": "40-tasks/active/buy-milk.md", "metadata": {"name": "Buy milk"}},
        ]
        vault.read_file.return_value = {
            "path": "40-tasks/active/buy-milk.md",
            "metadata": {"name": "Buy milk"},
        }
        result = agent._tool_delete_task({"task_name": "buy milk"})
        assert result["ok"] is True
        assert result["data"]["deleted"] == "Buy milk"
        vault.delete_file.assert_called_once_with("40-tasks/active/buy-milk.md")

    def test_delete_task_not_found(self, agent, mock_services):
        vault = mock_services[1]
        vault.list_active_tasks.return_value = []
        result = agent._tool_delete_task({"task_name": "nonexistent"})
        assert result["ok"] is False
        assert "error" in result

    def test_archive_task_calls_vault(self, agent, mock_services):
        vault = mock_services[1]
        vault.list_active_tasks.return_value = [
            {"path": "40-tasks/active/buy-milk.md", "metadata": {"name": "Buy milk"}},
        ]
        vault.archive_task.return_value = {
            "task_name": "Buy milk",
            "archive_path": "40-tasks/archive/buy-milk.md",
        }
        result = agent._tool_archive_task({"task_name": "buy milk"})
        assert result["ok"] is True
        assert result["data"]["archived_to"] == "40-tasks/archive/buy-milk.md"
        vault.archive_task.assert_called_once_with("40-tasks/active/buy-milk.md")

    def test_delete_habit_calls_vault(self, agent, mock_services):
        vault = mock_services[1]
        vault.list_active_habits.return_value = [
            {"path": "20-habits/workout.md", "metadata": {"name": "Workout"}},
        ]
        vault.read_file.return_value = {
            "path": "20-habits/workout.md",
            "metadata": {"name": "Workout"},
        }
        result = agent._tool_delete_habit({"habit_name": "workout"})
        assert result["ok"] is True
        assert result["data"]["deleted"] == "Workout"
        vault.delete_file.assert_called_once_with("20-habits/workout.md")

    def test_archive_goal_calls_vault(self, agent, mock_services):
        vault = mock_services[1]
        vault.list_active_goals.return_value = [
            {"path": "30-goals/2026/get-fit.md", "metadata": {"name": "Get fit"}},
        ]
        vault.read_file.return_value = {
            "path": "30-goals/2026/get-fit.md",
            "metadata": {"name": "Get fit"},
        }
        result = agent._tool_archive_goal({"goal_name": "get fit"})
        assert result["ok"] is True
        assert result["data"]["archived"] == "Get fit"
        vault.update_file.assert_called_once_with(
            "30-goals/2026/get-fit.md", {"status": "archived"}
        )


class TestDailySectionTools:
    def test_read_daily_section_tool_registered(self, agent):
        assert "read_daily_section" in agent.tools
        assert agent.tools["read_daily_section"]["risk"] == "safe"

    def test_edit_daily_section_tool_registered(self, agent):
        assert "edit_daily_section" in agent.tools
        assert agent.tools["edit_daily_section"]["risk"] == "write"

    def test_read_daily_section_calls_vault(self, agent, mock_services):
        vault = mock_services[1]
        vault.read_daily_section.return_value = "Some notes here"
        result = agent._tool_read_daily_section({"section": "Notes"})
        assert result["data"]["content"] == "Some notes here"
        vault.read_daily_section.assert_called_once()

    def test_edit_daily_section_calls_vault(self, agent, mock_services):
        vault = mock_services[1]
        vault.replace_daily_section.return_value = {"path": "10-daily/2026-03-06.md", "section": "Notes"}
        result = agent._tool_edit_daily_section({"section": "Notes", "content": "Updated notes"})
        assert result["ok"] is True
        assert "path" in result["data"]
        vault.replace_daily_section.assert_called_once()


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

        assert result["ok"] is True
        assert "path" in result["data"]
        vault.append_to_daily_section.assert_called_once()

    def test_attach_to_daily_forwards_optional_date(self, agent, mock_services):
        vault = mock_services[1]
        vault.append_to_daily_section.return_value = {
            "path": "10-daily/2026-06-17.md",
            "section": "Notes",
        }

        result = agent._tool_attach_to_daily({
            "vault_path": "photo.jpg",
            "caption": "Band practice form",
            "date": "2026-06-17",
        })
        assert result["ok"] is True
        assert vault.append_to_daily_section.call_args.kwargs["date"] == "2026-06-17"

    def test_attach_to_daily_defaults_date_to_none(self, agent, mock_services):
        vault = mock_services[1]
        vault.append_to_daily_section.return_value = {
            "path": "10-daily/2026-03-04.md",
            "section": "Notes",
        }

        result = agent._tool_attach_to_daily({
            "vault_path": "photo.jpg",
            "caption": "A note",
        })
        assert result["ok"] is True
        assert vault.append_to_daily_section.call_args.kwargs["date"] is None

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

        assert result["ok"] is True
        assert "path" in result["data"]
        call_args = vault.append_to_daily_section.call_args
        content = call_args.kwargs.get("content") or call_args[0][1] if len(call_args[0]) > 1 else call_args.kwargs["content"]
        # Coordinates render as a map link, not raw numbers
        assert "[Tel Aviv](https://www.google.com/maps?q=32.08,34.78)" in content
        assert "\U0001f4cd" in content

    def test_attach_to_daily_location_without_name_uses_map_label(self, agent, mock_services):
        vault = mock_services[1]
        vault.append_to_daily_section.return_value = {
            "path": "10-daily/2026-03-04.md",
            "section": "Notes",
        }

        result = agent._tool_attach_to_daily({
            "vault_path": "data/media/2026-03-04/photo.jpg",
            "caption": "Street photo",
            "location": {"lat": 32.08, "lng": 34.78},
            "section": "Notes",
        })

        assert result["ok"] is True
        call_args = vault.append_to_daily_section.call_args
        content = call_args.kwargs.get("content") or call_args[0][1] if len(call_args[0]) > 1 else call_args.kwargs["content"]
        assert "[Map](https://www.google.com/maps?q=32.08,34.78)" in content

    def test_attach_to_daily_emits_wikilink_embed(self, mock_services):
        claude, vault, memory, calendar, events = mock_services
        agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)
        agent.vault.append_to_daily_section.return_value = {
            "path": "10-daily/2026-06-04.md",
            "section": "Notes",
        }
        result = agent._tool_attach_to_daily({
            "vault_path": "data/media/2026-06-04/photo_xyz.jpg",
            "caption": "A nice picture",
        })
        assert result["ok"] is True
        kwargs = agent.vault.append_to_daily_section.call_args
        # The content arg may be passed positionally or as kwarg — handle both
        content = (
            kwargs.kwargs.get("content")
            or (kwargs.args[1] if len(kwargs.args) > 1 else "")
        )
        assert "![[photo_xyz.jpg]]" in content
        assert "![](" not in content  # no old-style relative path
        assert "../../" not in content  # no relative-path leakage


class TestEventTools:
    def test_list_events_tool_registered(self, agent):
        assert "list_events" in agent.tools
        assert agent.tools["list_events"]["risk"] == "safe"

    def test_attach_photo_to_event_tool_registered(self, agent):
        assert "attach_photo_to_event" in agent.tools
        assert agent.tools["attach_photo_to_event"]["risk"] == "write"

    def test_create_event_tool_registered(self, agent):
        assert "create_event" in agent.tools
        assert agent.tools["create_event"]["risk"] == "write"

    def test_list_events_calls_service(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.get_events.return_value = [
            {"id": "evt_abc", "name": "Lunch", "start_time": "12:00", "photos": []},
        ]
        result = agent._tool_list_events({})
        assert len(result["data"]["events"]) == 1
        events_mock.get_events.assert_called_once()

    def test_create_event_calls_service(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.create_event.return_value = {"id": "evt_new", "path": "data/events/2026-03-04.json"}

        # Disable calendar to test basic path
        agent.calendar = None
        result = agent._tool_create_event({
            "name": "Coffee break",
            "start_time": "15:00",
        })
        assert result["ok"] is True
        assert result["data"]["event_id"] == "evt_new"
        events_mock.create_event.assert_called_once()

    def test_create_event_syncs_to_gcal(self, agent, mock_services):
        from unittest.mock import AsyncMock
        events_mock = mock_services[4]
        calendar_mock = mock_services[3]
        events_mock.create_event.return_value = {"id": "evt_new", "path": "data/events/2026-03-04.json"}

        calendar_mock.create_event = AsyncMock(return_value="gcal_event_123")

        result = agent._tool_create_event({
            "name": "Lunch",
            "start_time": "12:30",
            "end_time": "13:30",
        })
        assert result["ok"] is True
        assert result["data"]["event_id"] == "evt_new"
        assert result["data"].get("calendar_synced") is True
        # source_ids should have been passed to events service
        call_kwargs = events_mock.create_event.call_args
        assert call_kwargs.kwargs.get("source_ids") == {"calendar_id": "gcal_event_123"}

    def test_create_event_gcal_failure_still_persists(self, agent, mock_services):
        events_mock = mock_services[4]
        calendar_mock = mock_services[3]
        events_mock.create_event.return_value = {"id": "evt_new", "path": "data/events/2026-03-04.json"}
        calendar_mock.create_event = MagicMock(side_effect=Exception("GCal error"))

        result = agent._tool_create_event({
            "name": "Dinner",
            "start_time": "19:00",
        })
        assert result["ok"] is True
        assert result["data"]["event_id"] == "evt_new"
        assert "calendar_synced" not in result["data"]
        events_mock.create_event.assert_called_once()

    def test_create_event_no_calendar_skips_silently(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.create_event.return_value = {"id": "evt_new", "path": "data/events/2026-03-04.json"}
        agent.calendar = None

        result = agent._tool_create_event({
            "name": "Walk",
            "start_time": "10:00",
        })
        assert result["ok"] is True
        assert result["data"]["event_id"] == "evt_new"
        assert "calendar_synced" not in result["data"]

    # --- calendar_sync: same shape as the sync_to_calendar post-hook ---

    def test_create_event_reports_calendar_success(self, agent, mock_services):
        from unittest.mock import AsyncMock
        events_mock = mock_services[4]
        calendar_mock = mock_services[3]
        events_mock.create_event.return_value = {"id": "evt_new", "path": "p.json"}
        calendar_mock.create_event = AsyncMock(return_value="gcal_event_123")

        result = agent._tool_create_event({
            "name": "Lunch", "start_time": "12:30", "end_time": "13:00",
        })

        assert result["data"]["calendar_sync"] == {
            "ok": True,
            "attempted": True,
            "event_id": "gcal_event_123",
        }

    def test_create_event_reports_calendar_failure(self, agent, mock_services):
        """A silent failure here was a hole in the never-report-an-unconfirmed-
        write guarantee: create_event emitted nothing at all when GCal blew up,
        under a key the reporting rule does not name."""
        events_mock = mock_services[4]
        calendar_mock = mock_services[3]
        events_mock.create_event.return_value = {"id": "evt_new", "path": "p.json"}
        calendar_mock.create_event = MagicMock(side_effect=Exception("GCal error"))

        result = agent._tool_create_event({
            "name": "Dinner", "start_time": "19:00", "end_time": "20:00",
        })

        sync = result["data"]["calendar_sync"]
        assert sync["ok"] is False
        assert sync["attempted"] is True
        assert "GCal error" in sync["reason"]

    def test_create_event_reports_when_gcal_returns_no_id(self, agent, mock_services):
        from unittest.mock import AsyncMock
        events_mock = mock_services[4]
        calendar_mock = mock_services[3]
        events_mock.create_event.return_value = {"id": "evt_new", "path": "p.json"}
        calendar_mock.create_event = AsyncMock(return_value=None)

        result = agent._tool_create_event({
            "name": "Walk", "start_time": "10:00", "end_time": "10:30",
        })

        sync = result["data"]["calendar_sync"]
        assert sync["ok"] is False
        assert sync["attempted"] is True
        assert sync["reason"] == "no_event_created"

    def test_create_event_without_calendar_is_not_a_failure(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.create_event.return_value = {"id": "evt_new", "path": "p.json"}
        agent.calendar = None

        result = agent._tool_create_event({
            "name": "Walk", "start_time": "10:00", "end_time": "10:30",
        })

        assert result["data"]["calendar_sync"] == {
            "ok": False,
            "attempted": False,
            "reason": "calendar_not_configured",
        }

    def test_create_event_for_a_photo_is_not_a_calendar_failure(self, agent, mock_services):
        events_mock = mock_services[4]
        calendar_mock = mock_services[3]
        events_mock.create_event.return_value = {"id": "evt_new", "path": "p.json"}

        result = agent._tool_create_event({
            "name": "Sunset",
            "start_time": "20:00",
            "end_time": "20:15",
            "photo_path": "media/2026-08-17/sunset.jpg",
        })

        assert result["data"]["calendar_sync"]["attempted"] is False
        assert result["data"]["calendar_sync"]["reason"] == "not_applicable"
        calendar_mock.create_event.assert_not_called()

    # --- activity vs category: two axes, one tool parameter ---

    def test_create_event_passes_activity_through(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.create_event.return_value = {"id": "evt_new", "path": "p.json"}
        agent.calendar = None

        agent._tool_create_event({
            "name": "Dog walk", "start_time": "07:00", "activity": "walk",
        })

        assert events_mock.create_event.call_args.kwargs["activity"] == "walk"

    def test_create_event_accepts_the_deprecated_category_alias(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.create_event.return_value = {"id": "evt_new", "path": "p.json"}
        agent.calendar = None

        agent._tool_create_event({
            "name": "Dog walk", "start_time": "07:00", "category": "walk",
        })

        assert events_mock.create_event.call_args.kwargs["activity"] == "walk"

    def test_create_event_prefers_activity_over_the_alias(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.create_event.return_value = {"id": "evt_new", "path": "p.json"}
        agent.calendar = None

        agent._tool_create_event({
            "name": "Dog walk", "start_time": "07:00",
            "activity": "walk", "category": "legacy",
        })

        assert events_mock.create_event.call_args.kwargs["activity"] == "walk"

    def test_update_event_passes_activity_through(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.update_event.return_value = {"updated": True, "event": {}}

        agent._tool_update_event({"event_id": "evt_1", "activity": "walk"})

        assert events_mock.update_event.call_args.kwargs["updates"]["activity"] == "walk"

    def test_update_event_prefers_activity_over_the_alias(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.update_event.return_value = {"updated": True, "event": {}}

        agent._tool_update_event({
            "event_id": "evt_1", "activity": "walk", "category": "legacy",
        })

        assert events_mock.update_event.call_args.kwargs["updates"]["activity"] == "walk"

    def test_event_schemas_name_the_field_they_actually_write(self, agent):
        """The parameter was called `category` while writing `activity`. Now
        that an event carries both as separate axes, the old name pointed the
        model at the wrong facet and left the real one unreachable."""
        for tool in ("create_event", "update_event"):
            props = agent.tools[tool]["schema"]["input_schema"]["properties"]
            assert "activity" in props, tool
            assert "category" not in props, tool

    def test_create_event_with_explicit_date(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.create_event.return_value = {"id": "evt_new", "path": "data/events/2026-03-20.json"}
        agent.calendar = None

        result = agent._tool_create_event({
            "name": "Future event",
            "date": "2026-03-20",
            "start_time": "14:00",
        })
        # Verify date was passed through and time was normalized
        call_kwargs = events_mock.create_event.call_args
        assert call_kwargs.kwargs["date"] == "2026-03-20"
        assert call_kwargs.kwargs["start_time"] == "2026-03-20T14:00:00"

    def test_create_event_writes_schedule_line(self, agent, mock_services):
        vault = mock_services[1]
        events_mock = mock_services[4]
        agent.calendar = None
        events_mock.create_event.return_value = {"id": "evt_new", "path": "data/events/2026-06-07.json"}
        vault.read_daily_note.return_value = {"content": "## Tasks\n- [ ]\n\n## Food\n"}

        result = agent._tool_create_event({
            "name": "Pub meeting",
            "date": "2026-06-07",
            "start_time": "20:00",
            "end_time": "22:30",
            "location": {"name": "Shnitt brewery"},
            "wikilinks": ["Momentick"],
        })

        assert result["ok"] is True
        vault.write_daily_note.assert_called_once()
        written_date, written_body = vault.write_daily_note.call_args[0]
        assert written_date == "2026-06-07"
        assert "## Schedule" in written_body
        assert "- 20:00–22:30 Pub meeting @ Shnitt brewery [[Momentick]]" in written_body
        assert "10-daily/2026-06-07.md" in result["_items"]

    def test_create_event_appends_to_existing_schedule(self, agent, mock_services):
        vault = mock_services[1]
        events_mock = mock_services[4]
        agent.calendar = None
        events_mock.create_event.return_value = {"id": "evt_2", "path": "data/events/2026-06-07.json"}
        vault.read_daily_note.return_value = {
            "content": "## Schedule\n- 09:00 Standup\n\n## Food\n"
        }

        result = agent._tool_create_event({
            "name": "Afternoon walk",
            "date": "2026-06-07",
            "start_time": "15:00",
            "end_time": "15:45",
        })

        assert result["ok"] is True
        _, written_body = vault.write_daily_note.call_args[0]
        # The existing start-only line round-trips untouched — an end is
        # optional in the *format*; it is only a newly created block that
        # has to be complete before it earns a line.
        assert "- 09:00 Standup" in written_body
        assert "- 15:00–15:45 Afternoon walk" in written_body

    def test_create_event_skips_schedule_for_an_incomplete_block(self, agent, mock_services):
        """'Just got back from the dog walk' records an end and no start.
        `render_schedule_section` has no null handling, so writing one
        anyway appended `- None-16:40 Dog walk`, which `parse_schedule_section`
        cannot re-parse and which is therefore silently dropped the next
        time anything rewrites the section: written wrong, then lost."""
        vault = mock_services[1]
        events_mock = mock_services[4]
        agent.calendar = None
        events_mock.create_event.return_value = {"id": "evt_i", "path": "data/events/2026-09-08.json"}
        vault.read_daily_note.return_value = {"content": "## Schedule\n- 09:00 Standup\n"}

        result = agent._tool_create_event({
            "name": "Dog walk", "date": "2026-09-08", "end_time": "16:40",
        })

        assert result["ok"] is True
        vault.write_daily_note.assert_not_called()

    def test_create_event_skips_schedule_when_there_is_no_time_at_all(self, agent, mock_services):
        vault = mock_services[1]
        events_mock = mock_services[4]
        agent.calendar = None
        events_mock.create_event.return_value = {"id": "evt_n", "path": "data/events/2026-09-08.json"}

        result = agent._tool_create_event({"name": "Nap", "date": "2026-09-08"})

        assert result["ok"] is True
        vault.write_daily_note.assert_not_called()

    def test_create_event_skips_schedule_for_photo(self, agent, mock_services):
        vault = mock_services[1]
        events_mock = mock_services[4]
        agent.calendar = None
        events_mock.create_event.return_value = {"id": "evt_p", "path": "data/events/2026-06-07.json"}

        result = agent._tool_create_event({
            "name": "Lunch photo",
            "date": "2026-06-07",
            "start_time": "12:00",
            "photo_path": "memory/00-system/media/2026-06-07/lunch.jpg",
        })

        assert result["ok"] is True
        vault.write_daily_note.assert_not_called()

    def test_create_event_schedule_failure_does_not_break_result(self, agent, mock_services):
        vault = mock_services[1]
        events_mock = mock_services[4]
        agent.calendar = None
        events_mock.create_event.return_value = {"id": "evt_new", "path": "data/events/2026-06-07.json"}
        vault.read_daily_note.side_effect = Exception("vault down")

        result = agent._tool_create_event({
            "name": "Pub meeting",
            "date": "2026-06-07",
            "start_time": "20:00",
        })

        assert result["ok"] is True
        assert result["data"]["event_id"] == "evt_new"

    def test_update_event_tool_registered(self, agent):
        assert "update_event" in agent.tools
        assert agent.tools["update_event"]["risk"] == "write"

    def test_update_event_calls_service(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.update_event.return_value = {"updated": True, "event_id": "evt_abc"}
        events_mock._file_path.return_value = "data/events/2026-03-04.json"

        result = agent._tool_update_event({
            "event_id": "evt_abc",
            "end_time": "13:00",
        })
        assert result["ok"] is True
        assert result["data"]["updated"] is True
        events_mock.update_event.assert_called_once()

    def test_update_event_normalizes_times(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.update_event.return_value = {"updated": True, "event_id": "evt_abc"}
        events_mock._file_path.return_value = "data/events/2026-03-19.json"
        # Bare HH:MM anchors to the day the event is actually stored under,
        # which is what the resolver reports — not to today.
        events_mock.resolve_event_date.return_value = "2026-03-19"

        agent._tool_update_event({
            "event_id": "evt_abc",
            "date": "2026-03-19",
            "start_time": "12:00",
            "end_time": "13:00",
        })
        call_kwargs = events_mock.update_event.call_args
        updates = call_kwargs.kwargs.get("updates") or call_kwargs[0][2]
        assert updates["start_time"] == "2026-03-19T12:00:00"
        assert updates["end_time"] == "2026-03-19T13:00:00"

    def test_update_event_not_found(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.update_event.return_value = {"error": "Event nonexistent not found"}
        events_mock._file_path.return_value = "data/events/2026-03-04.json"
        result = agent._tool_update_event({"event_id": "nonexistent", "name": "X"})
        assert result["ok"] is False
        assert "error" in result

    def test_update_event_resolves_the_date_before_updating(self, agent, mock_services):
        """The date hint is not where the event has to be.

        `list_events` hands out IDs for any date; defaulting the hint to today
        made every update to an event on another day fail with PATH_NOT_FOUND
        even though the ID was valid.
        """
        events_mock = mock_services[4]
        events_mock.resolve_event_date.return_value = "2026-09-08"
        events_mock.update_event.return_value = {"updated": True, "event": {}, "date": "2026-09-08"}
        events_mock._file_path.return_value = "data/events/2026-09-08.json"

        result = agent._tool_update_event({"event_id": "evt_abc", "name": "Dog walk"})

        assert result["ok"] is True
        assert events_mock.update_event.call_args.kwargs["date"] == "2026-09-08"

    def test_update_event_unresolvable_id_never_reaches_the_service(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.resolve_event_date.return_value = None

        result = agent._tool_update_event({"event_id": "evt_nope", "name": "X"})

        assert result["ok"] is False
        assert result["error"]["code"] == "PATH_NOT_FOUND"
        events_mock.update_event.assert_not_called()

    def test_update_event_forwards_new_date_and_anchors_times_to_it(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.resolve_event_date.return_value = "2026-09-08"
        events_mock.update_event.return_value = {
            "updated": True, "event": {}, "date": "2026-09-07", "moved_from": "2026-09-08",
        }
        events_mock._file_path.side_effect = lambda d: f"data/events/{d}.json"

        result = agent._tool_update_event({
            "event_id": "evt_abc",
            "new_date": "2026-09-07",
            "start_time": "16:30",
        })

        kwargs = events_mock.update_event.call_args.kwargs
        assert kwargs["new_date"] == "2026-09-07"
        assert kwargs["updates"]["start_time"] == "2026-09-07T16:30:00"
        # Both days changed, so both files are affected items.
        assert result["_items"] == [
            "data/events/2026-09-07.json",
            "data/events/2026-09-08.json",
        ]

    def test_moved_calendar_event_reports_that_gcal_did_not_move(self, agent, mock_services):
        """CalendarService has no move call, so the upstream entry stays put.

        Reporting a clean move would be a lie the user only discovers when
        the old day re-merges the event back. The moved event carries real
        start/end times — a moved event stays complete, EventsService only
        detaches its source_ids — so `is_complete` is True and calendar_id
        reads as empty; without a guard for `moved_from` the sync block
        would read that as "not in the calendar yet" and issue a real
        create_event call, leaving an orphaned duplicate at the new date
        while still reporting cross_date_move_not_supported.
        """
        from unittest.mock import AsyncMock
        events_mock = mock_services[4]
        events_mock.resolve_event_date.return_value = "2026-09-08"
        events_mock.update_event.return_value = {
            "updated": True,
            "date": "2026-09-07",
            "moved_from": "2026-09-08",
            "event": {
                "start_time": "2026-09-07T10:00:00",
                "end_time": "2026-09-07T10:30:00",
                "moved_from_source_ids": {"calendar_id": "gcal_123"},
            },
        }
        events_mock._file_path.side_effect = lambda d: f"data/events/{d}.json"
        agent.calendar.is_initialized = True
        agent.calendar.create_event = AsyncMock(return_value="gcal_new")
        agent.calendar.update_event = AsyncMock(return_value=True)

        result = agent._tool_update_event({"event_id": "evt_abc", "new_date": "2026-09-07"})

        agent.calendar.create_event.assert_not_awaited()
        agent.calendar.update_event.assert_not_awaited()
        sync = result["data"]["calendar_sync"]
        assert sync["ok"] is False
        # attempted: True — the prompt tells the agent to stay quiet about
        # attempted: false, and this is something the user has to hear.
        assert sync["attempted"] is True
        assert sync["event_id"] == "gcal_123"
        assert sync["reason"] == "cross_date_move_not_supported"
        assert "2026-09-08" in sync["detail"]

    def test_same_day_update_of_a_startless_block_says_so(self, agent, mock_services):
        """A same-day edit now always carries a calendar_sync verdict — an
        empty stored event has no start, so the verdict is 'no_start_time'
        rather than silence."""
        events_mock = mock_services[4]
        events_mock.resolve_event_date.return_value = "2026-09-08"
        events_mock.update_event.return_value = {
            "updated": True, "event": {}, "date": "2026-09-08",
        }
        events_mock._file_path.side_effect = lambda d: f"data/events/{d}.json"

        result = agent._tool_update_event({"event_id": "evt_abc", "start_time": "16:30"})

        assert result["data"]["calendar_sync"]["reason"] == "no_start_time"


class TestDeleteEventTool:
    def test_delete_event_tool_registered_as_destructive(self, agent):
        assert "delete_event" in agent.tools
        assert agent.tools["delete_event"]["risk"] == "destructive"
        # Destructive tools always render a preview and ask, whatever the
        # model's confidence.
        assert agent.tools["delete_event"]["preview"] is True
        assert agent.tools["delete_event"]["confidence_threshold"] == 0.95
        # Event writes share one file per day — never dispatched concurrently.
        assert agent.tools["delete_event"]["safe_for_parallel"] is False

    def test_delete_event_removes_the_event(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.resolve_event_date.return_value = "2026-09-07"
        events_mock.get_events.return_value = [{"id": "evt_dup", "name": "Dog walk", "source_ids": {}}]
        events_mock.delete_event.return_value = {
            "deleted": True, "event": {"name": "Dog walk"}, "date": "2026-09-07",
        }
        events_mock._file_path.side_effect = lambda d: f"data/events/{d}.json"
        agent.calendar = None

        result = agent._tool_delete_event({"event_id": "evt_dup"})

        assert result["ok"] is True
        assert result["data"]["deleted"] is True
        assert events_mock.delete_event.call_args.kwargs["date"] == "2026-09-07"
        assert result["_items"] == ["data/events/2026-09-07.json"]

    def test_delete_event_unknown_id(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.resolve_event_date.return_value = None

        result = agent._tool_delete_event({"event_id": "evt_nope"})

        assert result["ok"] is False
        assert result["error"]["code"] == "PATH_NOT_FOUND"
        events_mock.delete_event.assert_not_called()

    def test_delete_event_also_deletes_the_calendar_entry(self, agent, mock_services):
        """A duplicate deleted only from the store returns on the next merge.

        Deleting the calendar entry too is what makes the delete stick — and
        the duplicate calendar event is the case this tool exists for.
        """
        events_mock = mock_services[4]
        events_mock.resolve_event_date.return_value = "2026-09-07"
        events_mock.get_events.return_value = [
            {"id": "evt_dup", "name": "Dog walk", "source_ids": {"calendar_id": "gcal_dup"}},
        ]
        events_mock.delete_event.return_value = {
            "deleted": True, "event": {"name": "Dog walk"}, "date": "2026-09-07",
        }
        events_mock._file_path.side_effect = lambda d: f"data/events/{d}.json"
        from unittest.mock import AsyncMock
        agent.calendar.is_initialized = True
        agent.calendar.delete_event = AsyncMock(return_value=True)

        result = agent._tool_delete_event({"event_id": "evt_dup"})

        agent.calendar.delete_event.assert_awaited_once_with("gcal_dup")
        assert result["data"]["calendar_sync"] == {
            "ok": True, "attempted": True, "event_id": "gcal_dup",
        }
        assert "reappears_from_source" not in result["data"]

    def test_failed_calendar_delete_warns_that_it_comes_back(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.resolve_event_date.return_value = "2026-09-07"
        events_mock.get_events.return_value = [
            {"id": "evt_dup", "name": "Dog walk", "source_ids": {"calendar_id": "gcal_dup"}},
        ]
        events_mock.delete_event.return_value = {
            "deleted": True, "event": {"name": "Dog walk"}, "date": "2026-09-07",
        }
        events_mock._file_path.side_effect = lambda d: f"data/events/{d}.json"
        from unittest.mock import AsyncMock
        agent.calendar.is_initialized = True
        agent.calendar.delete_event = AsyncMock(return_value=False)

        result = agent._tool_delete_event({"event_id": "evt_dup"})

        assert result["data"]["calendar_sync"]["ok"] is False
        assert result["data"]["calendar_sync"]["reason"] == "delete_failed"
        assert result["data"]["reappears_from_source"] is True

    def test_note_derived_event_is_flagged_as_regenerating(self, agent, mock_services):
        """A checkbox in the daily note is re-merged into an event every read.

        Deleting the row clears it until the next merge; the checkbox is what
        has to change, and the agent must not promise otherwise.
        """
        events_mock = mock_services[4]
        events_mock.resolve_event_date.return_value = "2026-09-07"
        events_mock.get_events.return_value = [
            {"id": "evt_note", "name": "Dog walk", "source_ids": {"note_line": "abc123"}},
        ]
        events_mock.delete_event.return_value = {
            "deleted": True, "event": {"name": "Dog walk"}, "date": "2026-09-07",
        }
        events_mock._file_path.side_effect = lambda d: f"data/events/{d}.json"
        agent.calendar = None

        result = agent._tool_delete_event({"event_id": "evt_note"})

        assert result["data"]["reappears_from_source"] is True
        assert result["data"]["calendar_sync"]["attempted"] is False

    def test_delete_event_preview_names_the_event(self, agent, mock_services):
        """`evt_7a8857a4` is not something a user can approve or refuse."""
        from src.services.preview import render_preview

        events_mock = mock_services[4]
        events_mock.resolve_event_date.return_value = "2026-09-07"
        events_mock.get_events.return_value = [{
            "id": "evt_dup",
            "name": "Dog walk",
            "start_time": "2026-09-07T16:30:00",
            "source_ids": {"calendar_id": "gcal_dup"},
        }]

        text = render_preview(
            "delete_event", {"event_id": "evt_dup"}, ctx={"events": events_mock},
        )

        assert "Dog walk" in text
        assert "2026-09-07 16:30" in text
        assert "Google Calendar" in text

    def test_delete_event_preview_falls_back_to_the_id(self, agent):
        from src.services.preview import render_preview

        text = render_preview("delete_event", {"event_id": "evt_dup"}, ctx={"events": None})

        assert "evt_dup" in text

    def test_delete_event_preview_resolves_a_block_reference(self, agent, mock_services):
        """block_reference is reachable on delete_event now that the schema
        allows it — the preview must not fall back to a bare `?` for it."""
        from src.services.preview import render_preview

        events_mock = mock_services[4]
        events_mock.resolve_event_date.return_value = "2026-09-08"
        events_mock.get_events.return_value = [{
            "id": "evt_dup",
            "name": "Lunch",
            "start_time": "2026-09-08T13:00:00",
            "source_ids": {},
        }]

        text = render_preview(
            "delete_event", {"block_reference": "lunch"}, ctx={"events": events_mock},
        )

        assert "Lunch" in text
        assert "2026-09-08 13:00" in text

    def test_delete_event_preview_names_the_reference_when_unresolvable(self, agent):
        """A destructive action's confirmation must never say only `?` —
        naming what the user typed is strictly more information, even when
        nothing could be matched to it."""
        from src.services.preview import render_preview

        text = render_preview(
            "delete_event", {"block_reference": "gym"}, ctx={"events": None},
        )

        assert "gym" in text

    def test_attach_photo_calls_service(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.attach_photo.return_value = {"attached": True, "event_id": "evt_abc"}
        events_mock._file_path.return_value = "data/events/2026-03-04.json"

        result = agent._tool_attach_photo_to_event({
            "event_id": "evt_abc",
            "photo_path": "data/media/2026-03-04/photo.jpg",
            "caption": "Sunset",
        })
        assert result["ok"] is True
        assert result["data"]["attached"] is True
        # No date passed → service receives None and locates the event by ID.
        assert events_mock.attach_photo.call_args.kwargs["date"] is None

    def test_attach_photo_forwards_optional_date(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.attach_photo.return_value = {
            "attached": True, "event_id": "evt_abc", "date": "2026-06-17",
        }
        events_mock._file_path.return_value = "data/events/2026-06-17.json"

        result = agent._tool_attach_photo_to_event({
            "event_id": "evt_abc",
            "photo_path": "photo.jpg",
            "date": "2026-06-17",
        })
        assert result["ok"] is True
        assert events_mock.attach_photo.call_args.kwargs["date"] == "2026-06-17"
        # _items reflect the resolved date returned by the service.
        events_mock._file_path.assert_called_with("2026-06-17")


class TestTracingSpans:
    """Spans should be emitted around handle_message, _run_loop, and _execute_tool."""

    def test_handle_message_emits_expected_spans(self, agent, monkeypatch):
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        monkeypatch.setattr(trace, "_TRACER_PROVIDER", provider, raising=False)
        monkeypatch.setattr(
            trace._TRACER_PROVIDER_SET_ONCE, "_done", False, raising=False
        )
        trace.set_tracer_provider(provider)

        # Mock Claude to immediately end_turn so the loop runs once.
        class _Stop:
            stop_reason = "end_turn"
            content = [type("C", (), {"type": "text", "text": "ok"})()]

        monkeypatch.setattr(agent.claude, "create", lambda **_: _Stop())

        agent.handle_message("hello", chat_id=1)

        names = {s.name for s in exporter.get_finished_spans()}
        assert "agent.handle_message" in names
        assert "agent.loop" in names

    def test_handle_confirmation_continues_original_trace(self, agent, monkeypatch):
        """The resumed confirmation flow shares the original turn's trace_id."""
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )
        from src.services import agent_service as agent_service_module

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        monkeypatch.setattr(
            agent_service_module, "_tracer", provider.get_tracer("mazkir.agent.test"),
        )

        # Turn 1: Claude requests a destructive tool with low confidence,
        # which trips the gate and stores a pending action.
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "delete_task"
        tool_block.id = "tool_low"
        tool_block.input = {"name": "old", "_confidence": 0.4, "_reasoning": "vague"}
        first_response = MagicMock()
        first_response.stop_reason = "tool_use"
        first_response.content = [tool_block]
        agent.claude.create.return_value = first_response

        result1 = agent.handle_message("delete old", chat_id=42)
        assert result1.awaiting_confirmation is True
        action_id = result1.pending_action_id

        # Capture the original trace_id from handle_message.
        orig_spans = [s for s in exporter.get_finished_spans() if s.name == "agent.handle_message"]
        assert len(orig_spans) == 1
        original_trace_id = orig_spans[0].context.trace_id

        # Turn 2: user confirms. Claude returns end_turn immediately so the
        # resumed loop completes.
        end_block = MagicMock()
        end_block.type = "text"
        end_block.text = "done"
        end_response = MagicMock()
        end_response.stop_reason = "end_turn"
        end_response.content = [end_block]
        agent.claude.create.return_value = end_response

        # Stub the tool handler to avoid touching the vault.
        agent.tools["delete_task"]["handler"] = lambda **_: {"deleted": "old"}

        agent.handle_confirmation(chat_id=42, action_id=action_id, user_response="yes")

        confirm_spans = [s for s in exporter.get_finished_spans() if s.name == "agent.handle_confirmation"]
        assert len(confirm_spans) == 1
        assert confirm_spans[0].context.trace_id == original_trace_id


class TestSavePhotoFilesystemSpans:
    """_save_photo should emit fs.write spans for the photo and the sidecar."""

    def test_save_photo_emits_two_fs_write_spans(self, agent, monkeypatch):
        import base64
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        monkeypatch.setattr(trace, "_TRACER_PROVIDER", provider, raising=False)
        monkeypatch.setattr(
            trace._TRACER_PROVIDER_SET_ONCE, "_done", False, raising=False
        )
        trace.set_tracer_provider(provider)

        agent._save_photo(
            {
                "data": base64.b64encode(b"fake-image-data").decode(),
                "filename": "photo_span_test.jpg",
            }
        )

        spans = [s for s in exporter.get_finished_spans() if s.name.startswith("fs.")]
        assert len(spans) == 2
        assert all(s.name == "fs.write" for s in spans)
        assert all(s.attributes["fs.store"] == "media" for s in spans)
        assert all(s.attributes["fs.bytes"] > 0 for s in spans)


def test_complete_task_returns_real_values_not_placeholders(mock_services):
    """Regression: agent_service.py dict-unpacking iterated keys not values."""
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)
    agent.vault.list_active_tasks.return_value = [
        {"path": "40-tasks/active/x.md", "metadata": {"name": "X"}},
    ]
    agent.vault.read_file.return_value = {
        "path": "40-tasks/active/x.md",
        "metadata": {"name": "X", "google_event_id": None},
    }
    agent.vault.complete_task.return_value = {
        "task_name": "X",
        "tokens_earned": 5,
        "archive_path": "40-tasks/archive/x.md",
    }

    result = agent._tool_complete_task({"task_name": "X"})

    payload = result["data"] if "data" in result else result
    assert payload["task"] == "X"
    assert payload["tokens_earned"] == 5
    assert payload["archived_to"] == "40-tasks/archive/x.md"


def test_execute_tool_runs_pre_hooks_and_blocks_on_error(mock_services, tmp_path):
    """When a pre-hook returns an error, the handler is not called."""
    from src.services.hooks import register_hook, HOOK_REGISTRY
    from src.services.tool_response import err, ErrorCode

    HOOK_REGISTRY.clear()
    register_hook(
        "always_block",
        lambda p, c: err(ErrorCode.SCHEMA_INVALID, "blocked by test"),
    )

    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(
        claude=claude, vault=vault, memory=memory, calendar=calendar, events=events,
        media_path=tmp_path / "media",
    )
    handler_called = []
    agent.tools["list_tasks"]["pre_hooks"] = ["always_block"]
    agent.tools["list_tasks"]["handler"] = lambda p: handler_called.append(True) or {"data": []}

    result = agent._execute_tool_inner("list_tasks", {}, risk="safe")

    assert handler_called == []
    assert result["ok"] is False
    assert result["error"]["code"] == "SCHEMA_INVALID"


def test_update_item_tool_removed():
    """update_item retired in favor of typed update_task/_habit/_goal."""
    from src.services.agent_service import AgentService
    from unittest.mock import MagicMock
    agent = AgentService(
        claude=MagicMock(), vault=MagicMock(), memory=MagicMock(),
        calendar=None, events=None,
    )
    assert "update_item" not in agent.tools
    assert "update_task" in agent.tools
    assert "update_habit" in agent.tools
    assert "update_goal" in agent.tools


def test_complete_task_idempotent_when_already_done(mock_services):
    """Re-completing a done task returns ALREADY_DONE, no double-credit."""
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)
    agent.vault.list_active_tasks.return_value = [
        {"path": "40-tasks/active/x.md", "metadata": {"name": "X", "status": "done"}},
    ]
    agent.vault.read_file.return_value = {
        "path": "40-tasks/active/x.md",
        "metadata": {"name": "X", "status": "done"},
    }

    result = agent._tool_complete_task({"task_name": "X"})

    assert result["ok"] is False
    assert result["error"]["code"] == "ALREADY_DONE"
    agent.vault.complete_task.assert_not_called()


def test_complete_habit_idempotent_when_done_today(mock_services):
    # Idempotency is now sourced from the `## Completion Log` body (Task 6/7),
    # not the `last_completed` frontmatter field alone. With no `daily_target`
    # set, the default target is 1, so one logged entry for today is enough
    # to trigger ALREADY_DONE on a second attempt.
    from datetime import date
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)
    today = date.today().isoformat()
    agent.vault.list_active_habits.return_value = [
        {
            "path": "20-habits/workout.md",
            "metadata": {"name": "Workout", "last_completed": today, "streak": 5},
        }
    ]
    agent.vault.read_file.return_value = {
        "path": "20-habits/workout.md",
        "metadata": {"name": "Workout", "last_completed": today, "streak": 5},
        "content": f"# Workout\n\n## Completion Log\n- {today}T06:00:00\n",
    }

    result = agent._tool_complete_habit({"habit_name": "Workout"})

    assert result["ok"] is False
    assert result["error"]["code"] == "ALREADY_DONE"


def test_archive_goal_idempotent_when_already_archived(mock_services):
    """Re-archiving an already-archived goal returns ALREADY_DONE."""
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)
    agent.vault.list_active_goals.return_value = [
        {"path": "30-goals/2026/x.md", "metadata": {"name": "X", "status": "archived"}},
    ]
    agent.vault.read_file.return_value = {
        "path": "30-goals/2026/x.md",
        "metadata": {"name": "X", "status": "archived"},
    }

    result = agent._tool_archive_goal({"goal_name": "X"})

    assert result["ok"] is False
    assert result["error"]["code"] == "ALREADY_DONE"


def test_delete_task_idempotent_when_target_absent(mock_services):
    """Deleting a non-existent task returns PATH_NOT_FOUND."""
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)
    agent.vault.list_active_tasks.return_value = []

    result = agent._tool_delete_task({"task_name": "ghost"})

    assert result["ok"] is False
    assert result["error"]["code"] == "PATH_NOT_FOUND"


def test_delete_task_uses_resolver_for_fuzzy_match(mock_services):
    """delete_task should match 'walke' to 'Walk the dog' via fuzzy resolver."""
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)

    agent.vault.list_active_tasks.return_value = [
        {"path": "40-tasks/active/walk-dog.md", "metadata": {"name": "Walk the dog"}}
    ]
    # vault.read_file is needed because new pattern calls it after resolver
    agent.vault.read_file.return_value = {
        "path": "40-tasks/active/walk-dog.md",
        "metadata": {"name": "Walk the dog"},
    }

    result = agent._tool_delete_task({"task_name": "walke the dog"})
    assert result.get("ok") is True or "deleted" in (result.get("data") or result)
    agent.vault.delete_file.assert_called_once_with("40-tasks/active/walk-dog.md")


def test_delete_task_ambiguous_returns_candidates(mock_services):
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)

    agent.vault.list_active_tasks.return_value = [
        {"path": "40-tasks/active/a.md", "metadata": {"name": "Project Alpha review"}},
        {"path": "40-tasks/active/b.md", "metadata": {"name": "Project Alpha summary"}},
    ]
    result = agent._tool_delete_task({"task_name": "alpha"})
    assert result["ok"] is False
    assert result["error"]["code"] == "AMBIGUOUS_MATCH"
    assert "candidates" in result["error"]["details"]


def test_list_tasks_returns_normalized_ok_shape(mock_services):
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)
    agent.vault.list_active_tasks.return_value = [
        {"path": "40-tasks/active/x.md", "metadata": {"name": "X", "priority": 3, "status": "active"}}
    ]
    agent.vault.read_daily_note.return_value = {"metadata": {}, "content": ""}
    result = agent._tool_list_tasks({})
    assert result["ok"] is True
    assert "data" in result
    # Grouped shape: all four keys present
    assert "daily_pending" in result["data"]
    assert "daily_done_today" in result["data"]
    assert "file_tier_by_priority" in result["data"]
    assert "overdue" in result["data"]
    assert "_items" in result


def test_search_knowledge_returns_normalized_ok_shape(mock_services):
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)
    agent.memory.search_knowledge.return_value = [{"path": "k.md", "name": "k", "tags": [], "score": 1}]
    result = agent._tool_search_knowledge({"query": "test"})
    assert result["ok"] is True
    assert "results" in result["data"]


def test_create_task_tool_schema_exposes_scheduling_fields(mock_services):
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)
    props = agent.tools["create_task"]["schema"]["input_schema"]["properties"]
    assert "scheduled_at" in props
    assert "duration_minutes" in props
    assert "due_soft" in props


def test_create_task_handler_passes_scheduling_fields_through(mock_services):
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)
    agent.vault.create_task.return_value = {
        "path": "40-tasks/active/x.md",
        "metadata": {"name": "X", "scheduled_at": "2026-06-05T14:00"},
    }
    result = agent._tool_create_task({
        "name": "X",
        "priority": 3,
        "scheduled_at": "2026-06-05T14:00",
        "duration_minutes": 60,
        "due_soft": "2026-06-08",
    })
    assert result["ok"] is True
    kwargs = agent.vault.create_task.call_args.kwargs
    assert kwargs.get("scheduled_at") == "2026-06-05T14:00"
    assert kwargs.get("duration_minutes") == 60
    assert kwargs.get("due_soft") == "2026-06-08"


def test_create_task_tool_schema_exposes_description(mock_services):
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)
    props = agent.tools["create_task"]["schema"]["input_schema"]["properties"]
    assert "description" in props


def test_create_task_handler_passes_description_through(mock_services):
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)
    agent.vault.create_task.return_value = {
        "path": "40-tasks/active/x.md",
        "metadata": {"name": "X"},
    }
    result = agent._tool_create_task({
        "name": "X",
        "description": "Step 1. Step 2.",
    })
    assert result["ok"] is True
    kwargs = agent.vault.create_task.call_args.kwargs
    assert kwargs.get("description") == "Step 1. Step 2."


def test_create_habit_tool_schema_exposes_scheduling_fields(mock_services):
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)
    props = agent.tools["create_habit"]["schema"]["input_schema"]["properties"]
    assert "scheduled_at" in props
    assert "duration_minutes" in props


def test_create_goal_tool_schema_exposes_start_date(mock_services):
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)
    props = agent.tools["create_goal"]["schema"]["input_schema"]["properties"]
    assert "start_date" in props


def test_complete_habit_uses_resolver_for_fuzzy_match(mock_services):
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)
    agent.vault.list_active_habits.return_value = [
        {"path": "20-habits/morning-workout.md", "metadata": {"name": "Morning workout"}}
    ]
    agent.vault.read_file.return_value = {
        "path": "20-habits/morning-workout.md",
        "metadata": {"name": "Morning workout"},
    }
    agent.vault.complete_habit.return_value = {
        "habit_name": "Morning workout",
        "streak": 8,
        "tokens_earned": 5,
    }

    result = agent._tool_complete_habit({"habit_name": "workout"})
    assert result["ok"] is True


def test_complete_habit_ambiguous_returns_candidates(mock_services):
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)
    agent.vault.list_active_habits.return_value = [
        {"path": "20-habits/morning-workout.md", "metadata": {"name": "Morning workout"}},
        {"path": "20-habits/evening-workout.md", "metadata": {"name": "Evening workout"}},
    ]
    result = agent._tool_complete_habit({"habit_name": "workout"})
    assert result["ok"] is False
    assert result["error"]["code"] == "AMBIGUOUS_MATCH"


def test_list_tasks_returns_grouped_object(mock_services):
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)
    agent.vault.list_active_tasks.return_value = [
        {"path": "40-tasks/active/x.md", "metadata": {"name": "X", "priority": 3, "status": "active"}}
    ]
    agent.vault.read_daily_note.return_value = {
        "metadata": {},
        "content": "## Tasks\n- [ ] Walk dog\n- [x] Done thing\n",
    }
    result = agent._tool_list_tasks({})
    assert result["ok"] is True
    data = result["data"]
    assert "daily_pending" in data
    assert "daily_done_today" in data
    assert "file_tier_by_priority" in data
    assert "overdue" in data
    # Daily pending has the unchecked item with sequential number starting at 1
    assert any(t["text"] == "Walk dog" for t in data["daily_pending"])
    assert data["daily_pending"][0]["n"] == 1
    # Daily done has the checked item
    assert any(t["text"] == "Done thing" for t in data["daily_done_today"])
    # File-tier grouped by priority — priority 3 has 1 item, numbered after daily tasks
    assert 3 in data["file_tier_by_priority"]
    assert len(data["file_tier_by_priority"][3]) == 1
    assert data["file_tier_by_priority"][3][0]["n"] == 2


def test_list_tasks_flags_overdue(mock_services):
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)
    agent.vault.list_active_tasks.return_value = [
        {"path": "40-tasks/active/old.md", "metadata": {"name": "Old", "priority": 4, "status": "active", "due_date": "2020-01-01"}}
    ]
    agent.vault.read_daily_note.return_value = {"metadata": {}, "content": "## Tasks\n"}
    result = agent._tool_list_tasks({})
    assert len(result["data"]["overdue"]) == 1
    assert result["data"]["overdue"][0]["name"] == "Old"


def test_create_task_post_hook_includes_sync_to_calendar(mock_services):
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)
    assert "sync_to_calendar" in agent.tools["create_task"]["post_hooks"]
    assert "sync_to_calendar" in agent.tools["update_habit"]["post_hooks"]
    assert "sync_to_calendar" in agent.tools["complete_task"]["post_hooks"]
    # safe (read) tools should NOT have it
    assert "sync_to_calendar" not in agent.tools["list_tasks"].get("post_hooks", [])


def test_execute_tool_includes_calendar_in_ctx(mock_services, monkeypatch):
    """When a tool runs, calendar is in the ctx for hooks to use."""
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)

    captured = {}

    def _fake_execute(*, name, params, risk, tools, ctx):
        captured["ctx"] = ctx
        return {"ok": True, "data": {}, "_items": []}

    monkeypatch.setattr("src.services.tool_executor.execute_tool", _fake_execute)
    agent._execute_tool_inner("list_tasks", {}, risk="safe")
    assert "calendar" in captured["ctx"]
    assert captured["ctx"]["calendar"] is calendar


class TestReadKnowledge:
    def test_read_knowledge_registered_safe(self, agent):
        assert "read_knowledge" in agent.tools
        assert agent.tools["read_knowledge"]["risk"] == "safe"

    def test_read_knowledge_by_path_returns_body(self, agent, mock_services):
        vault = mock_services[1]
        vault.read_file.return_value = {
            "path": "60-knowledge/notes/ml-basics.md",
            "metadata": {"name": "ML basics", "tags": ["ml"], "links": ["stats"], "source": "chat"},
            "content": "Gradient descent is...",
        }
        result = agent._tool_read_knowledge({"path": "60-knowledge/notes/ml-basics.md"})
        assert result["ok"] is True
        assert result["data"]["content"] == "Gradient descent is..."
        assert result["data"]["name"] == "ML basics"
        assert result["data"]["tags"] == ["ml"]
        assert result["_items"] == ["60-knowledge/notes/ml-basics.md"]
        vault.read_file.assert_called_once_with("60-knowledge/notes/ml-basics.md")

    def test_read_knowledge_requires_path_or_name(self, agent):
        result = agent._tool_read_knowledge({})
        assert result["ok"] is False
        assert result["error"]["code"] == "SCHEMA_INVALID"

    def test_read_knowledge_path_not_found(self, agent, mock_services):
        vault = mock_services[1]
        vault.read_file.side_effect = FileNotFoundError("nope")
        result = agent._tool_read_knowledge({"path": "60-knowledge/notes/ghost.md"})
        assert result["ok"] is False
        assert result["error"]["code"] == "PATH_NOT_FOUND"

    def test_read_knowledge_by_name_resolves(self, agent, mock_services):
        from pathlib import Path
        vault = mock_services[1]
        vault.list_files.side_effect = lambda subdir: (
            [Path("60-knowledge/notes/ml-basics.md")] if subdir == "60-knowledge/notes" else []
        )
        vault.read_file.return_value = {
            "path": "60-knowledge/notes/ml-basics.md",
            "metadata": {"name": "ML basics", "tags": [], "links": [], "source": ""},
            "content": "body",
        }
        result = agent._tool_read_knowledge({"name": "ML basics"})
        assert result["ok"] is True
        assert result["data"]["path"] == "60-knowledge/notes/ml-basics.md"

    def test_read_knowledge_by_name_not_found(self, agent, mock_services):
        vault = mock_services[1]
        vault.list_files.return_value = []
        result = agent._tool_read_knowledge({"name": "does not exist"})
        assert result["ok"] is False
        assert result["error"]["code"] == "PATH_NOT_FOUND"

    def test_read_knowledge_by_name_ambiguous(self, agent, mock_services):
        from pathlib import Path
        vault = mock_services[1]
        vault.list_files.side_effect = lambda subdir: (
            [Path("60-knowledge/notes/ml-a.md"), Path("60-knowledge/notes/ml-b.md")]
            if subdir == "60-knowledge/notes" else []
        )
        vault.read_file.return_value = {
            "path": "60-knowledge/notes/ml-a.md",
            "metadata": {"name": "ML basics", "tags": [], "links": [], "source": ""},
            "content": "body",
        }
        result = agent._tool_read_knowledge({"name": "ML basics"})
        assert result["ok"] is False
        assert result["error"]["code"] == "AMBIGUOUS_MATCH"
        assert "candidates" in result["error"]["details"]
        assert len(result["error"]["details"]["candidates"]) == 2


class TestCodingHandoffTool:
    def test_propose_coding_session_registered_as_write_with_forced_preview(self, agent):
        assert "propose_coding_session" in agent.tools
        entry = agent.tools["propose_coding_session"]
        assert entry["risk"] == "write"
        assert entry["preview"] is True

    def test_current_chat_id_set_and_cleared_around_handle_message(self, agent, mock_services):
        claude = mock_services[0]
        assert agent._current_chat_id is None

        captured_chat_id = []

        def _capture_and_respond(*args, **kwargs):
            # Invoked mid-loop, inside the try block of handle_message — this
            # proves _current_chat_id is set to the caller's chat_id *during*
            # the call, not just before/after it.
            captured_chat_id.append(agent._current_chat_id)
            mock_response = MagicMock()
            mock_response.stop_reason = "end_turn"
            text_block = MagicMock()
            text_block.type = "text"
            text_block.text = "Hello! How can I help?"
            mock_response.content = [text_block]
            return mock_response

        claude.create.side_effect = _capture_and_respond

        result = agent.handle_message("hello", chat_id=42)

        assert result.response == "Hello! How can I help?"
        assert captured_chat_id == [42], (
            "chat_id was not set on agent._current_chat_id during handle_message"
        )
        assert agent._current_chat_id is None, (
            "chat_id was not cleared after handle_message returned"
        )

    def test_confirmation_flow_sets_chat_id_so_coding_task_persists_it(self, agent):
        """Regression test for the bug where every coding-handoff task was
        persisted with chat_id=None.

        propose_coding_session is registered with preview=True, so it NEVER
        auto-executes inside the initial handle_message call -- it always
        defers to _handle_confirmation_inner, invoked later from a separate
        /message/confirm request. handle_message's `finally` block clears
        self._current_chat_id back to None before that second call happens,
        so unless _handle_confirmation_inner sets it again itself, the tool
        handler reads a stale None instead of the confirming user's chat_id.
        """
        coding_tasks = MagicMock()
        coding_tasks.launch.return_value = {
            "id": "ct_abc123",
            "branch": "coding-agent/ct_abc123",
            "worktree_path": "/tmp/worktrees/ct_abc123",
            "status": "running",
        }
        agent.coding_tasks = coding_tasks

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "propose_coding_session"
        tool_block.id = "tool_propose"
        tool_block.input = {
            "task_description": "fix the rollover bug",
            "conversation_excerpt": "rollover duplicated tasks",
            "likely_area": "unknown",
            "_confidence": 0.99,
            "_reasoning": "clear, unambiguous request",
        }
        first_response = MagicMock()
        first_response.stop_reason = "tool_use"
        first_response.content = [tool_block]
        agent.claude.create.return_value = first_response

        result1 = agent.handle_message("please fix this in a sandboxed session", chat_id=99)
        assert result1.awaiting_confirmation is True
        action_id = result1.pending_action_id

        # handle_message's finally block must have already cleared this --
        # otherwise the test below wouldn't be exercising the bug at all.
        assert agent._current_chat_id is None

        end_block = MagicMock()
        end_block.type = "text"
        end_block.text = "Launched the coding session."
        end_response = MagicMock()
        end_response.stop_reason = "end_turn"
        end_response.content = [end_block]
        agent.claude.create.return_value = end_response

        agent.handle_confirmation(chat_id=99, action_id=action_id, user_response="yes")

        coding_tasks.save_task.assert_called_once()
        saved_task = coding_tasks.save_task.call_args[0][0]
        assert saved_task["chat_id"] == 99, (
            f"expected the confirming user's chat_id (99) on the persisted "
            f"task, got {saved_task['chat_id']!r}"
        )


def _pending(agent, action_id, tool_name, params):
    from src.services.agent_service import PendingAction

    agent.pending_confirmations[action_id] = PendingAction(
        chat_id=42,
        messages=[],
        assistant_response=MagicMock(content=[]),
        executed_results=[],
        pending_calls=[{"id": "tu_1", "name": tool_name, "input": params}],
        parent_span_context=None,
    )


def test_choice_answer_is_injected_as_session_mode(agent, monkeypatch):
    """The gate's answer IS the lane. Without injection the tool would run
    with its default no matter which button was pressed."""
    captured = {}

    def fake_execute(name, params, **kwargs):
        captured["params"] = params
        return {"ok": True, "data": {}, "_items": []}

    monkeypatch.setattr(agent, "_execute_tool", fake_execute)
    monkeypatch.setattr(
        agent, "_run_agent_turn",
        lambda *a, **kw: AgentResponse(response="done"),
    )
    _pending(agent, "act_1", "propose_coding_session",
             {"task_description": "fix it", "_confidence": 0.9})

    agent.handle_confirmation(42, "act_1", "autonomous")

    assert captured["params"]["session_mode"] == "autonomous"


def test_plain_yes_still_confirms_without_a_mode(agent, monkeypatch):
    captured = {}

    def fake_execute(name, params, **kwargs):
        captured["params"] = params
        return {"ok": True, "data": {}, "_items": []}

    monkeypatch.setattr(agent, "_execute_tool", fake_execute)
    monkeypatch.setattr(
        agent, "_run_agent_turn",
        lambda *a, **kw: AgentResponse(response="done"),
    )
    _pending(agent, "act_2", "delete_task",
             {"name": "old task", "_confidence": 0.99})

    agent.handle_confirmation(42, "act_2", "yes")

    assert "session_mode" not in captured["params"]


def test_a_declining_answer_still_cancels(agent, monkeypatch):
    """A choice value must not make every answer affirmative."""
    executed = []
    monkeypatch.setattr(
        agent, "_execute_tool",
        lambda name, params, **kwargs: executed.append(name),
    )
    monkeypatch.setattr(
        agent, "_run_agent_turn",
        lambda *a, **kw: AgentResponse(response="cancelled"),
    )
    _pending(agent, "act_3", "propose_coding_session",
             {"task_description": "fix it", "_confidence": 0.9})

    agent.handle_confirmation(42, "act_3", "no")

    assert executed == []


def test_the_chosen_option_is_stated_back_to_the_model(agent, monkeypatch):
    """After a confirmed tool runs, the agent takes another turn -- but it
    only sees the tool result, never which option the user picked. A real
    session launched with 'autonomous' and the follow-up reply asked the
    user to choose a mode all over again, which reads as the button having
    done nothing."""
    captured = {}
    monkeypatch.setattr(
        agent, "_execute_tool",
        lambda name, params, **kw: {"ok": True, "data": {"id": "ct_1"}, "_items": []},
    )

    def fake_turn(chat_id, original_text, messages, system, **kw):
        captured["messages"] = messages
        return AgentResponse(response="done")

    monkeypatch.setattr(agent, "_run_agent_turn", fake_turn)
    _pending(agent, "act_1", "propose_coding_session",
             {"task_description": "fix it", "_confidence": 0.9})

    agent.handle_confirmation(42, "act_1", "autonomous")

    last = captured["messages"][-1]
    text_blocks = [b for b in last["content"] if b.get("type") == "text"]
    assert text_blocks, "the model must be told which option was chosen"
    note = " ".join(b["text"] for b in text_blocks).lower()
    assert "autonomous" in note
    assert "already" in note or "do not ask" in note


def test_a_plain_yes_adds_no_choice_note(agent, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        agent, "_execute_tool",
        lambda name, params, **kw: {"ok": True, "data": {}, "_items": []},
    )

    def fake_turn(chat_id, original_text, messages, system, **kw):
        captured["messages"] = messages
        return AgentResponse(response="done")

    monkeypatch.setattr(agent, "_run_agent_turn", fake_turn)
    _pending(agent, "act_2", "delete_task", {"name": "old", "_confidence": 0.99})

    agent.handle_confirmation(42, "act_2", "yes")

    last = captured["messages"][-1]
    assert all(b.get("type") == "tool_result" for b in last["content"])


def test_static_guidelines_forbid_unverified_write_claims():
    from src.services.agent_service import AgentService

    text = "\n".join(AgentService._static_guidelines())

    # Check that the section exists
    assert "## Reporting writes" in text
    assert "calendar_sync" in text
    assert "ok: true" in text

    # Pin the semantic guidance to prevent inversion
    assert "Never report an action as done unless the tool result says ok: true" in text
    assert "quote that, not your requested value" in text
    assert "tell the user the calendar was NOT updated" in text

    # A calendar failure is only reported when a sync was actually attempted:
    # "no calendar configured" / "a delete" / "a task with no due date" are
    # normal, not failures, and must not be announced as calendar problems.
    assert "ok: false AND attempted: true" in text
    assert "attempted: false means there was nothing to sync" in text
    assert "That is not a failure" in text


def _habit_file(name="Dog Walk", target=2, streak=3, log=""):
    return {
        "metadata": {
            "type": "habit",
            "name": name,
            "daily_target": target,
            "streak": streak,
            "longest_streak": 5,
            "last_completed": None,
            "tokens_per_completion": 5,
            "google_event_id": None,
        },
        "content": f"# {name}\n\n## Completion Log\n{log}\n",
    }


@pytest.fixture
def _resolve_ok(monkeypatch):
    """complete_habit resolves the name through resolver.resolve_item."""
    monkeypatch.setattr(
        "src.services.resolver.resolve_item",
        lambda kind, name, vault: {
            "ok": True, "data": {"path": "20-habits/dog-walk.md"}
        },
    )


def test_second_completion_of_the_day_is_allowed(agent, mock_services, _resolve_ok):
    """Regression: dog walking needs two completions a day."""
    import datetime as dt
    _, vault, _, _, _ = mock_services
    today = dt.date.today().isoformat()
    vault.read_file.return_value = _habit_file(log=f"- {today}T07:12:00\n")

    result = agent._tool_complete_habit({"habit_name": "Dog Walk"})

    assert result["ok"] is True
    assert result["data"]["completions_today"] == 2


def test_completion_beyond_the_daily_target_is_rejected(agent, mock_services, _resolve_ok):
    import datetime as dt
    _, vault, _, _, _ = mock_services
    today = dt.date.today().isoformat()
    vault.read_file.return_value = _habit_file(
        log=f"- {today}T07:12:00\n- {today}T19:40:00\n"
    )

    result = agent._tool_complete_habit({"habit_name": "Dog Walk"})

    assert result["ok"] is False
    assert result["error"]["code"] == "ALREADY_DONE"


def test_streak_advances_only_when_the_target_is_met(agent, mock_services, _resolve_ok):
    import datetime as dt
    _, vault, _, _, _ = mock_services
    today = dt.date.today().isoformat()

    vault.read_file.return_value = _habit_file(log="")
    first = agent._tool_complete_habit({"habit_name": "Dog Walk"})
    assert first["data"]["new_streak"] == 3  # unchanged: 1 of 2

    vault.read_file.return_value = _habit_file(log=f"- {today}T07:12:00\n")
    second = agent._tool_complete_habit({"habit_name": "Dog Walk"})
    assert second["data"]["new_streak"] == 4  # 2 of 2 — target met


def test_tokens_are_awarded_on_every_completion(agent, mock_services, _resolve_ok):
    _, vault, _, _, _ = mock_services
    vault.read_file.return_value = _habit_file(log="")

    result = agent._tool_complete_habit({"habit_name": "Dog Walk"})

    assert result["data"]["tokens_earned"] == 5
    vault.update_tokens.assert_called_once()

    # Pin what actually gets written: a regression that swapped write_file's
    # metadata/content args, dropped the `{**meta}` spread, or wrote the
    # stale `body` instead of the appended `new_body` would leave every
    # other assertion in this suite green, since `vault` is a MagicMock.
    vault.write_file.assert_called_once()
    write_path, metadata, content = vault.write_file.call_args[0]
    assert write_path == "20-habits/dog-walk.md"
    assert metadata["type"] == "habit"
    assert metadata["tokens_per_completion"] == 5  # preserved, never touched
    assert "## Completion Log" in content
    assert content.count("- ") >= 1  # the newly appended log line is present


def test_habit_without_daily_target_behaves_as_before(agent, mock_services, _resolve_ok):
    import datetime as dt
    _, vault, _, _, _ = mock_services
    today = dt.date.today().isoformat()
    habit = _habit_file(target=None, log=f"- {today}T07:12:00\n")
    del habit["metadata"]["daily_target"]
    vault.read_file.return_value = habit

    result = agent._tool_complete_habit({"habit_name": "Dog Walk"})

    assert result["ok"] is False
    assert result["error"]["code"] == "ALREADY_DONE"


def test_last_completed_backfill_blocks_second_completion_on_transition_day(
    agent, mock_services, _resolve_ok
):
    """Regression: habits completed before the Completion Log existed carry
    only `last_completed`. Without a backfill, an empty log reads as zero
    completions today, so a habit already done today would be allowed a
    second (duplicate) completion — double tokens and streak N -> N+2 in a
    single day, for every habit already in the live vault on ship day.
    """
    import datetime as dt
    _, vault, _, _, _ = mock_services
    today = dt.date.today().isoformat()
    habit = _habit_file(target=2, log="")  # empty log: pre-Task-6 habit
    habit["metadata"]["last_completed"] = today  # already completed today

    vault.read_file.return_value = habit

    result = agent._tool_complete_habit({"habit_name": "Dog Walk"})

    assert result["ok"] is False
    assert result["error"]["code"] == "ALREADY_DONE"


def test_a_broken_daily_target_does_not_lock_the_habit(agent, mock_services, _resolve_ok):
    """`daily_target` is hand-edited YAML. A typo'd -1 made the habit
    permanently uncompletable (0 >= -1); `two` raised ValueError."""
    _, vault, _, _, _ = mock_services

    for broken in (-1, 0, "two"):
        habit = _habit_file(target=broken, log="")
        vault.read_file.return_value = habit

        result = agent._tool_complete_habit({"habit_name": "Dog Walk"})

        assert result["ok"] is True, broken
        assert result["data"]["daily_target"] == 1, broken
        assert result["data"]["completions_today"] == 1, broken


def test_list_habits_guards_a_broken_daily_target(agent, mock_services):
    _, vault, _, _, _ = mock_services
    vault.list_active_habits.return_value = [{
        "path": "20-habits/dog-walk.md",
        "metadata": {"type": "habit", "name": "Dog Walk", "daily_target": -1},
        "content": "",
    }]

    habit = agent._tool_list_habits({})["data"]["habits"][0]

    assert habit["daily_target"] == 1


def test_list_habits_applies_the_transition_day_backfill(agent, mock_services):
    """list_habits must agree with complete_habit about the same habit: a
    pre-log habit already done today is done, not 0 of 1."""
    import datetime as dt
    _, vault, _, _, _ = mock_services
    today = dt.date.today().isoformat()
    vault.list_active_habits.return_value = [{
        "path": "20-habits/dog-walk.md",
        "metadata": {
            "type": "habit", "name": "Dog Walk",
            "daily_target": 2, "last_completed": today,
        },
        "content": "# Dog Walk\n",
    }]

    habit = agent._tool_list_habits({})["data"]["habits"][0]

    assert habit["completions_today"] == 2


def test_list_habits_reports_completion_progress(agent, mock_services):
    import datetime as dt
    _, vault, _, _, _ = mock_services
    today = dt.date.today().isoformat()
    vault.list_active_habits.return_value = [{
        "path": "20-habits/dog-walk.md",
        "metadata": {
            "type": "habit", "name": "Dog Walk",
            "daily_target": 2, "streak": 3, "frequency": "daily",
        },
        "content": f"## Completion Log\n- {today}T07:12:00\n",
    }]

    result = agent._tool_list_habits({})
    habit = result["data"]["habits"][0]

    assert habit["completions_today"] == 1
    assert habit["daily_target"] == 2


class TestSkillInTurnAudit:
    def test_emit_turn_audit_records_skill(self, agent, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            "src.services.agent_service.emit_agent_turn",
            lambda record: captured.update(record),
        )

        agent._emit_turn_audit(
            chat_id=123,
            user_text="add two todos",
            tools_audit=[],
            assistant_text="Added both.",
            items_referenced=[],
            awaiting_confirmation=False,
            pending_action_id=None,
            prior_action_id=None,
            iters=1,
            stop_reason="end_turn",
            skill="time-management",
        )

        assert captured["skill"] == "time-management"

    def test_emit_turn_audit_skill_defaults_to_none(self, agent, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            "src.services.agent_service.emit_agent_turn",
            lambda record: captured.update(record),
        )

        agent._emit_turn_audit(
            chat_id=123,
            user_text="hi",
            tools_audit=[],
            assistant_text="hello",
            items_referenced=[],
            awaiting_confirmation=False,
            pending_action_id=None,
            prior_action_id=None,
            iters=1,
            stop_reason="end_turn",
        )

        assert captured["skill"] is None


class TestMirrorInvariantGuidelines:
    def test_static_prefix_forbids_unchecked_denial(self, agent):
        prefix = agent._build_static_prefix()
        assert "Never deny a past action without checking" in prefix

    def test_static_prefix_warns_that_tool_lists_change(self, agent):
        prefix = agent._build_static_prefix()
        assert "what you can do now, not what you did earlier" in prefix

    def test_static_prefix_forbids_reasoning_from_absence(self, agent):
        prefix = agent._build_static_prefix()
        assert "no record, not proof of inaction" in prefix


class TestListEventsReconciles:
    """`list_events` must show the day `/day` shows.

    It used to read `EventsService.get_events` — the raw persisted file —
    while `/day` rendered a reconciled view that is deliberately not
    persisted. A calendar block the user was looking at could be entirely
    absent from what the agent saw.
    """

    def test_list_events_uses_the_reconciled_view(self, agent, mock_services):
        from unittest.mock import patch
        events_mock = mock_services[4]
        events_mock.reconcile.return_value = [{
            "id": "evt_1", "name": "Standup",
            "start_time": "2026-09-08T10:00:00", "end_time": "2026-09-08T10:30:00",
            "source": "calendar", "source_ids": {"calendar_id": "gcal_1"},
        }]

        async def fake_merge(date):
            return [], {"calendar"}

        with patch("src.services.day_assembly.merge_from_sources", fake_merge):
            result = agent._tool_list_events({"date": "2026-09-08"})

        assert result["ok"] is True
        assert result["data"]["events"][0]["name"] == "Standup"
        events_mock.reconcile.assert_called_once()
        # Reading must not write: `/day` navigation relies on that, and the
        # agent listing a day is the same kind of read.
        events_mock.refresh_events.assert_not_called()

    def test_listed_events_report_completeness(self, agent, mock_services):
        from unittest.mock import patch
        events_mock = mock_services[4]
        events_mock.reconcile.return_value = [
            {"id": "evt_1", "name": "Standup",
             "start_time": "2026-09-08T10:00:00", "end_time": "2026-09-08T10:30:00"},
            {"id": "evt_2", "name": "Dog walk",
             "start_time": None, "end_time": "2026-09-08T16:40:00"},
        ]

        async def fake_merge(date):
            return [], set()

        with patch("src.services.day_assembly.merge_from_sources", fake_merge):
            result = agent._tool_list_events({"date": "2026-09-08"})

        by_id = {e["id"]: e for e in result["data"]["events"]}
        assert by_id["evt_1"]["complete"] is True
        assert by_id["evt_2"]["complete"] is False

    def test_listed_events_carry_their_date(self, agent, mock_services):
        from unittest.mock import patch
        events_mock = mock_services[4]
        events_mock.reconcile.return_value = [
            {"id": "evt_1", "name": "Standup", "start_time": "2026-09-08T10:00:00",
             "end_time": "2026-09-08T10:30:00"},
        ]

        async def fake_merge(date):
            return [], set()

        with patch("src.services.day_assembly.merge_from_sources", fake_merge):
            result = agent._tool_list_events({"date": "2026-09-08"})

        assert result["data"]["events"][0]["date"] == "2026-09-08"

    def test_merge_failure_falls_back_to_the_persisted_store(self, agent, mock_services):
        """A source outage must degrade to the stored day, never to nothing:
        an empty list would read to the agent as 'that block does not
        exist', which is the shape of the denial bug Ship 3 fixed."""
        from unittest.mock import patch
        events_mock = mock_services[4]
        events_mock.get_events.return_value = [
            {"id": "evt_1", "name": "Standup",
             "start_time": "2026-09-08T10:00:00", "end_time": "2026-09-08T10:30:00"},
        ]

        async def boom(date):
            raise RuntimeError("calendar unreachable")

        with patch("src.services.day_assembly.merge_from_sources", boom):
            result = agent._tool_list_events({"date": "2026-09-08"})

        assert result["ok"] is True
        assert result["data"]["events"][0]["id"] == "evt_1"
        assert result["data"]["degraded"] is True

    def test_reconcile_bug_propagates_rather_than_reading_as_degraded(self, agent, mock_services):
        """A bug in `reconcile` itself — pure local logic, not a source call —
        must surface as a real error, not be laundered into "the calendar was
        unavailable". Only `merge_from_sources` failures may degrade."""
        from unittest.mock import patch
        events_mock = mock_services[4]
        events_mock.reconcile.side_effect = KeyError("logical_id")

        async def fake_merge(date):
            return [], set()

        with patch("src.services.day_assembly.merge_from_sources", fake_merge):
            with pytest.raises(KeyError):
                agent._tool_list_events({"date": "2026-09-08"})

    def test_reconciled_events_with_no_events_service_is_degraded_not_a_crash(self, agent):
        agent.events = None
        events, degraded = agent._reconciled_events("2026-09-08")
        assert events == []
        assert degraded is True


class TestCreateEventIntervals:
    def test_start_and_duration_derives_the_end(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.create_event.return_value = {"id": "evt_1", "path": "data/events/2026-09-08.json"}
        agent.calendar = None

        agent._tool_create_event({
            "name": "Dog walk", "date": "2026-09-08",
            "start_time": "16:00", "duration_minutes": 40,
        })

        kwargs = events_mock.create_event.call_args.kwargs
        assert kwargs["start_time"] == "2026-09-08T16:00:00"
        assert kwargs["end_time"] == "2026-09-08T16:40:00"

    def test_end_and_duration_derives_the_start(self, agent, mock_services):
        """'Just got back from the 40-minute dog walk.'"""
        events_mock = mock_services[4]
        events_mock.create_event.return_value = {"id": "evt_1", "path": "p"}
        agent.calendar = None

        agent._tool_create_event({
            "name": "Dog walk", "date": "2026-09-08",
            "end_time": "16:40", "duration_minutes": 40,
        })

        kwargs = events_mock.create_event.call_args.kwargs
        assert kwargs["start_time"] == "2026-09-08T16:00:00"

    def test_contradictory_values_are_rejected(self, agent, mock_services):
        events_mock = mock_services[4]
        agent.calendar = None

        result = agent._tool_create_event({
            "name": "Gym", "date": "2026-09-08",
            "start_time": "18:00", "end_time": "19:00", "duration_minutes": 90,
        })

        assert result["ok"] is False
        assert result["error"]["code"] == "SCHEMA_INVALID"
        events_mock.create_event.assert_not_called()

    def test_one_endpoint_creates_an_incomplete_block(self, agent, mock_services):
        """'Just got back from the dog walk' — the end is now, the start is
        unknown, and inventing one is how a block gets shifted by its own
        length."""
        events_mock = mock_services[4]
        events_mock.create_event.return_value = {"id": "evt_1", "path": "p"}
        agent.calendar = None

        result = agent._tool_create_event({
            "name": "Dog walk", "date": "2026-09-08", "end_time": "16:40",
        })

        kwargs = events_mock.create_event.call_args.kwargs
        assert kwargs["start_time"] is None
        assert kwargs["end_time"] == "2026-09-08T16:40:00"
        assert result["data"]["complete"] is False
        # "no_start_time", not "incomplete": only a missing *start* leaves
        # Google nothing to be told. A start with no end is a reminder and
        # now syncs, which is the Milpro fix.
        assert result["data"]["calendar_sync"]["reason"] == "no_start_time"

    def test_date_description_explains_the_overnight_anchor(self, agent):
        """`date` defaults to today and derive_interval reads a reversed pair
        as "the end is the next day", so "slept 23:30 to 07:15" said at 08:00
        logs *tonight* unless the model knows to pass yesterday. Nothing said
        so; the description is half of where it now does (the other half is
        the rule in memory/00-system/skills/time-management.md)."""
        desc = agent.tools["create_event"]["schema"]["input_schema"]["properties"]["date"]["description"]
        assert "midnight" in desc.lower()
        assert "started" in desc.lower()

    def test_name_is_the_only_required_field(self, agent):
        schema = agent.tools["create_event"]["schema"]["input_schema"]
        assert schema["required"] == ["name"]
        assert "duration_minutes" in schema["properties"]

    def test_photo_with_only_a_start_is_a_complete_moment_not_a_block(self, agent, mock_services):
        """A photo is a moment with a known time, not an unfinished block —
        the one place a zero-length event is deliberately synthesised
        rather than stated. Without this it would land in the same 'needs
        a time' list as a genuinely incomplete capture."""
        events_mock = mock_services[4]
        events_mock.create_event.return_value = {"id": "evt_1", "path": "p"}
        agent.calendar = None

        result = agent._tool_create_event({
            "name": "Sunset", "date": "2026-09-08", "start_time": "20:00",
            "photo_path": "media/2026-09-08/sunset.jpg",
        })

        kwargs = events_mock.create_event.call_args.kwargs
        assert kwargs["start_time"] == "2026-09-08T20:00:00"
        assert kwargs["end_time"] == "2026-09-08T20:00:00"
        assert result["data"]["complete"] is True


class TestCreateEventMidnight:
    def test_sleep_splits_into_two_fragments(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.create_event.side_effect = [
            {"id": "evt_a", "path": "data/events/2026-09-08.json"},
            {"id": "evt_b", "path": "data/events/2026-09-09.json"},
        ]
        agent.calendar = None

        result = agent._tool_create_event({
            "name": "Sleep", "date": "2026-09-08",
            "start_time": "23:30", "end_time": "07:15",
        })

        assert events_mock.create_event.call_count == 2
        first, second = [c.kwargs for c in events_mock.create_event.call_args_list]
        assert first["date"] == "2026-09-08"
        assert first["start_time"] == "2026-09-08T23:30:00"
        assert first["end_time"] == "2026-09-08T23:59:59"
        assert second["date"] == "2026-09-09"
        assert second["start_time"] == "2026-09-09T00:00:00"
        assert second["end_time"] == "2026-09-09T07:15:00"
        assert first["logical_id"] == second["logical_id"]
        assert result["data"]["calendar_sync"]["reason"] == "crosses_midnight"
        assert result["data"]["calendar_sync"]["attempted"] is False


class TestUpdateEventDuration:
    """The second half of a partial capture.

    "Just got back from the dog walk" writes an end and no start; "it was 40
    minutes" is the sentence that finishes it, and before this it had nowhere
    to land — the model had to compute 16:40 minus 40 itself, the exact
    arithmetic §3.1 moved into Python after it shifted a block by its own
    length on 2026-08-16.
    """

    @staticmethod
    def _wire(mock_services, stored):
        events_mock = mock_services[4]
        events_mock.resolve_event_date.return_value = "2026-09-08"
        events_mock.get_events.return_value = [stored]
        events_mock.update_event.return_value = {
            "updated": True, "event": {}, "date": "2026-09-08",
        }
        events_mock._file_path.side_effect = lambda d: f"data/events/{d}.json"
        return events_mock

    def test_duration_against_a_known_end_derives_the_start(self, agent, mock_services):
        events_mock = self._wire(mock_services, {
            "id": "evt_1", "name": "Dog walk",
            "start_time": None, "end_time": "2026-09-08T16:40:00",
        })
        agent.calendar = None

        result = agent._tool_update_event({
            "event_id": "evt_1", "duration_minutes": 40,
        })

        assert result["ok"] is True
        updates = events_mock.update_event.call_args.kwargs["updates"]
        assert updates["start_time"] == "2026-09-08T16:00:00"
        assert updates["end_time"] == "2026-09-08T16:40:00"

    def test_duration_against_a_known_start_derives_the_end(self, agent, mock_services):
        events_mock = self._wire(mock_services, {
            "id": "evt_1", "name": "Nap",
            "start_time": "2026-09-08T14:00:00", "end_time": None,
        })
        agent.calendar = None

        agent._tool_update_event({"event_id": "evt_1", "duration_minutes": 25})

        updates = events_mock.update_event.call_args.kwargs["updates"]
        assert updates["end_time"] == "2026-09-08T14:25:00"

    def test_an_endpoint_supplied_in_the_same_call_counts_as_known(self, agent, mock_services):
        """Both halves can arrive in one sentence: 'the dog walk ended at
        16:40 and took 40 minutes'."""
        events_mock = self._wire(mock_services, {
            "id": "evt_1", "name": "Dog walk", "start_time": None, "end_time": None,
        })
        agent.calendar = None

        agent._tool_update_event({
            "event_id": "evt_1", "end_time": "16:40", "duration_minutes": 40,
        })

        updates = events_mock.update_event.call_args.kwargs["updates"]
        assert updates["start_time"] == "2026-09-08T16:00:00"

    def test_an_endpoint_named_in_the_call_outranks_a_stored_one(self, agent, mock_services):
        """"It ended at 16:40 and took 40 minutes" on a block that already
        has a start must move the start. Anchoring on the stored start would
        recompute the end the user had just stated."""
        events_mock = self._wire(mock_services, {
            "id": "evt_1", "name": "Dog walk",
            "start_time": "2026-09-08T15:00:00", "end_time": "2026-09-08T15:30:00",
        })
        agent.calendar = None

        agent._tool_update_event({
            "event_id": "evt_1", "end_time": "16:40", "duration_minutes": 40,
        })

        updates = events_mock.update_event.call_args.kwargs["updates"]
        assert updates["end_time"] == "2026-09-08T16:40:00"
        assert updates["start_time"] == "2026-09-08T16:00:00"

    def test_a_bare_duration_on_a_complete_block_keeps_the_start(self, agent, mock_services):
        """"Actually it was 90 minutes" with nothing else named: the start
        stays put and the end moves."""
        events_mock = self._wire(mock_services, {
            "id": "evt_1", "name": "Gym",
            "start_time": "2026-09-08T18:00:00", "end_time": "2026-09-08T19:00:00",
        })
        agent.calendar = None

        agent._tool_update_event({"event_id": "evt_1", "duration_minutes": 90})

        updates = events_mock.update_event.call_args.kwargs["updates"]
        assert updates["start_time"] == "2026-09-08T18:00:00"
        assert updates["end_time"] == "2026-09-08T19:30:00"

    def test_a_block_with_neither_endpoint_is_rejected(self, agent, mock_services):
        events_mock = self._wire(mock_services, {
            "id": "evt_1", "name": "Nap", "start_time": None, "end_time": None,
        })
        agent.calendar = None

        result = agent._tool_update_event({
            "event_id": "evt_1", "duration_minutes": 25,
        })

        assert result["ok"] is False
        assert result["error"]["code"] == "SCHEMA_INVALID"
        assert "start_time" in result["error"]["message"]
        assert "end_time" in result["error"]["message"]
        events_mock.update_event.assert_not_called()

    def test_three_disagreeing_values_are_rejected(self, agent, mock_services):
        """Same rule as create_event: two of the three are wrong and nothing
        here can tell which, so guessing would corrupt the day silently."""
        events_mock = self._wire(mock_services, {
            "id": "evt_1", "name": "Gym", "start_time": None, "end_time": None,
        })
        agent.calendar = None

        result = agent._tool_update_event({
            "event_id": "evt_1", "start_time": "18:00", "end_time": "19:00",
            "duration_minutes": 90,
        })

        assert result["ok"] is False
        assert result["error"]["code"] == "SCHEMA_INVALID"
        events_mock.update_event.assert_not_called()

    def test_derived_endpoints_are_pinned(self, agent, mock_services):
        """An unpinned endpoint is put back by the very next merge — the
        §1.2 revert, arriving via the duration path instead of the name."""
        events_mock = self._wire(mock_services, {
            "id": "evt_1", "name": "Dog walk",
            "start_time": None, "end_time": "2026-09-08T16:40:00",
        })
        agent.calendar = None

        agent._tool_update_event({"event_id": "evt_1", "duration_minutes": 40})

        pinned = events_mock.update_event.call_args.kwargs["user_set_fields"]
        assert set(pinned) == {"start_time", "end_time"}

    def test_new_date_with_a_duration_is_refused(self, agent, mock_services):
        """"That dog walk was yesterday, and it was 40 minutes."

        Both derived endpoints land in `updates`, anchored on a stored
        timestamp that still carries the OLD date, and
        `EventsService.update_event` re-dates for `new_date` only the fields
        `updates` does not already carry — so nothing is re-dated, the row
        never leaves its original file, and the tool returns ok with no
        `moved_from` for the agent to notice. It would report a move that
        did not happen.
        """
        events_mock = self._wire(mock_services, {
            "id": "evt_1", "name": "Dog walk",
            "start_time": "2026-09-08T16:00:00", "end_time": "2026-09-08T16:40:00",
        })
        agent.calendar = None

        result = agent._tool_update_event({
            "event_id": "evt_1", "new_date": "2026-09-07", "duration_minutes": 40,
        })

        assert result["ok"] is False
        assert result["error"]["code"] == "SCHEMA_INVALID"
        events_mock.update_event.assert_not_called()

    def test_a_bare_new_date_still_moves_the_event(self, agent, mock_services):
        """The guard must refuse only the combination — a move on its own
        re-dates correctly and still reports `moved_from`."""
        events_mock = self._wire(mock_services, {
            "id": "evt_1", "name": "Dog walk",
            "start_time": "2026-09-08T16:00:00", "end_time": "2026-09-08T16:40:00",
        })
        events_mock.update_event.return_value = {
            "updated": True, "event": {}, "date": "2026-09-07",
            "moved_from": "2026-09-08",
        }
        agent.calendar = None

        result = agent._tool_update_event({
            "event_id": "evt_1", "new_date": "2026-09-07",
        })

        assert result["ok"] is True
        assert events_mock.update_event.call_args.kwargs["new_date"] == "2026-09-07"
        assert result["data"]["moved_from"] == "2026-09-08"

    def test_duration_is_in_the_schema(self, agent):
        props = agent.tools["update_event"]["schema"]["input_schema"]["properties"]
        assert "duration_minutes" in props


class TestUpdateEventShiftAndReference:
    def test_shift_minutes_moves_both_ends(self, agent, mock_services):
        """'Move gym -30m'. A start-only update stretches the block instead
        — verified on c3ffcee: 18:00-19:00 became 17:30-19:00, 90 minutes."""
        events_mock = mock_services[4]
        events_mock.resolve_event_date.return_value = "2026-09-08"
        events_mock.get_events.return_value = [{
            "id": "evt_1", "name": "Gym",
            "start_time": "2026-09-08T18:00:00", "end_time": "2026-09-08T19:00:00",
        }]
        events_mock.update_event.return_value = {"updated": True, "event": {}, "date": "2026-09-08"}
        events_mock._file_path.side_effect = lambda d: f"data/events/{d}.json"
        agent.calendar = None

        agent._tool_update_event({"event_id": "evt_1", "shift_minutes": -30})

        updates = events_mock.update_event.call_args.kwargs["updates"]
        assert updates["start_time"] == "2026-09-08T17:30:00"
        assert updates["end_time"] == "2026-09-08T18:30:00"

    def test_shift_on_an_incomplete_block_is_rejected(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.resolve_event_date.return_value = "2026-09-08"
        events_mock.get_events.return_value = [{
            "id": "evt_1", "name": "Dog walk",
            "start_time": None, "end_time": "2026-09-08T16:40:00",
        }]
        agent.calendar = None

        result = agent._tool_update_event({"event_id": "evt_1", "shift_minutes": -30})

        assert result["ok"] is False
        assert result["error"]["code"] == "SCHEMA_INVALID"
        events_mock.update_event.assert_not_called()

    def test_edited_fields_are_pinned(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.resolve_event_date.return_value = "2026-09-08"
        events_mock.get_events.return_value = [{"id": "evt_1", "name": "Daily sync"}]
        events_mock.update_event.return_value = {"updated": True, "event": {}, "date": "2026-09-08"}
        events_mock._file_path.side_effect = lambda d: f"data/events/{d}.json"
        agent.calendar = None

        agent._tool_update_event({"event_id": "evt_1", "name": "Standup"})

        assert events_mock.update_event.call_args.kwargs["user_set_fields"] == ["name"]

    def test_revert_fields_are_forwarded(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.resolve_event_date.return_value = "2026-09-08"
        events_mock.get_events.return_value = [{"id": "evt_1", "name": "Standup"}]
        events_mock.update_event.return_value = {"updated": True, "event": {}, "date": "2026-09-08"}
        events_mock._file_path.side_effect = lambda d: f"data/events/{d}.json"
        agent.calendar = None

        agent._tool_update_event({"event_id": "evt_1", "revert_fields": ["name"]})

        assert events_mock.update_event.call_args.kwargs["revert_fields"] == ["name"]

    def test_block_reference_materialises_the_day(self, agent, mock_services):
        """An inferred block has no row to update. The edit is explicit
        write intent, so persisting the reconciled day here is correct —
        unlike navigation, which must never write."""
        from unittest.mock import patch
        events_mock = mock_services[4]
        events_mock.reconcile.return_value = [{
            "id": "evt_gym", "name": "Gym",
            "start_time": "2026-09-08T18:00:00", "end_time": "2026-09-08T19:00:00",
        }]
        events_mock.update_event.return_value = {"updated": True, "event": {}, "date": "2026-09-08"}
        events_mock._file_path.side_effect = lambda d: f"data/events/{d}.json"
        agent.calendar = None

        async def fake_merge(date):
            return [], {"calendar"}

        with patch("src.services.day_assembly.merge_from_sources", fake_merge):
            agent._tool_update_event({"block_reference": "gym", "name": "Workout"})

        events_mock.refresh_events.assert_called_once()
        assert events_mock.update_event.call_args.kwargs["event_id"] == "evt_gym"

    def test_ambiguous_reference_surfaces_candidates(self, agent, mock_services):
        from unittest.mock import patch
        events_mock = mock_services[4]
        events_mock.reconcile.return_value = [
            {"id": "evt_1", "name": "Dog walk", "start_time": "2026-09-08T08:00:00"},
            {"id": "evt_2", "name": "Evening walk", "start_time": "2026-09-08T19:00:00"},
        ]

        async def fake_merge(date):
            return [], set()

        with patch("src.services.day_assembly.merge_from_sources", fake_merge):
            result = agent._tool_update_event({"block_reference": "walk", "name": "X"})

        assert result["ok"] is False
        assert result["error"]["code"] == "AMBIGUOUS_MATCH"
        events_mock.update_event.assert_not_called()

    def test_reference_searches_the_selected_date_and_today(self, agent, mock_services):
        """A stale hint only matters when the block exists on that day and
        nowhere else, because both days are searched."""
        from unittest.mock import patch
        events_mock = mock_services[4]
        events_mock.reconcile.return_value = []

        async def fake_merge(date):
            return [], set()

        with patch("src.services.day_assembly.merge_from_sources", fake_merge):
            agent._tool_update_event({
                "block_reference": "gym", "name": "X", "selected_date": "2026-08-20",
            })

        searched = {c.args[0] for c in events_mock.reconcile.call_args_list}
        assert "2026-08-20" in searched
        assert len(searched) == 2

    def test_selected_date_reaches_the_resolver_via_handle_message(self, agent, mock_services):
        """`handle_message(selected_date=...)` stores it as `self._selected_date`;
        `_resolve_reference` must fall back to that when the tool call itself
        carries no `selected_date` param — the model never sets that param,
        so this fallback is the only way the hint actually reaches a tool
        call in production."""
        from unittest.mock import patch
        events_mock = mock_services[4]
        events_mock.reconcile.return_value = []

        # Simulate what handle_message does at the top of the method,
        # without driving the full agent/Claude loop.
        agent._selected_date = "2026-08-20"

        async def fake_merge(date):
            return [], set()

        with patch("src.services.day_assembly.merge_from_sources", fake_merge):
            agent._tool_update_event({"block_reference": "gym", "name": "X"})

        searched = {c.args[0] for c in events_mock.reconcile.call_args_list}
        assert "2026-08-20" in searched
        assert len(searched) == 2

    def test_delete_event_accepts_a_reference(self, agent, mock_services):
        from unittest.mock import patch
        events_mock = mock_services[4]
        events_mock.reconcile.return_value = [
            {"id": "evt_dup", "name": "Lunch", "start_time": "2026-09-08T13:00:00",
             "source_ids": {}},
        ]
        events_mock.resolve_event_date.return_value = "2026-09-08"
        events_mock.get_events.return_value = [
            {"id": "evt_dup", "name": "Lunch", "source_ids": {}},
        ]
        events_mock.delete_event.return_value = {
            "deleted": True, "event": {"name": "Lunch"}, "date": "2026-09-08",
        }
        events_mock._file_path.side_effect = lambda d: f"data/events/{d}.json"
        agent.calendar = None

        async def fake_merge(date):
            return [], set()

        with patch("src.services.day_assembly.merge_from_sources", fake_merge):
            result = agent._tool_delete_event({"block_reference": "lunch"})

        assert result["ok"] is True
        assert events_mock.delete_event.call_args.kwargs["event_id"] == "evt_dup"


class TestResolveReferenceMaterializesWithStableId:
    def test_block_reference_resolves_to_the_id_the_store_actually_holds(self, tmp_path):
        """`resolve_block` sees the id from the search-phase merge; the
        materialise phase re-merges independently and `MergerService`
        assigns a fresh random id to the same logical event (`id: str =
        Field(default_factory=lambda: str(uuid.uuid4())[:8])` — no builder
        overrides it). Returning the search-phase id is a PATH_NOT_FOUND
        waiting on the very next call, since that id was never persisted.
        `source_ids` is the stable identity reconcile itself matches on, so
        resolution must re-find by that after materialising — a real
        `EventsService` against `tmp_path` is required here because a mock
        with a fixed `reconcile.return_value` never generates a second,
        different id and so cannot see this bug."""
        from unittest.mock import MagicMock, patch
        from uuid import uuid4
        import datetime as dt
        from src.services.events_service import EventsService

        events = EventsService(events_path=tmp_path / "events")
        agent = AgentService(
            claude=MagicMock(), vault=MagicMock(), memory=MagicMock(),
            calendar=None, events=events, media_path=tmp_path / "media",
        )

        today = dt.date.today().isoformat()

        def _fresh_gym_event():
            return {
                "id": uuid4().hex[:8],
                "name": "Gym",
                "type": "habit",
                "start_time": f"{today}T18:00:00",
                "end_time": f"{today}T19:00:00",
                "duration_minutes": 60,
                "source": "habit",
                "source_ids": {"habit_slug": "gym"},
            }

        async def fake_merge(date):
            return [_fresh_gym_event()], {"habit"}

        with patch("src.services.day_assembly.merge_from_sources", fake_merge):
            result = agent._resolve_reference({"block_reference": "gym"})

        assert result["ok"] is True
        event_id = result["data"]["event_id"]
        stored_ids = {e["id"] for e in events.get_events(today)}
        assert event_id in stored_ids, (
            f"resolved id {event_id!r} was never persisted; store holds {stored_ids!r}"
        )


class TestUpdateEventCalendarSync:
    def _stored(self, **over):
        base = {
            "id": "evt_1", "name": "Standup",
            "start_time": "2026-09-08T10:00:00", "end_time": "2026-09-08T10:30:00",
            "source_ids": {"calendar_id": "gcal_1"}, "calendar": "Mazkir",
        }
        base.update(over)
        return base

    def _wire(self, mock_services, stored):
        events_mock = mock_services[4]
        events_mock.resolve_event_date.return_value = "2026-09-08"
        events_mock.get_events.return_value = [stored]
        events_mock.update_event.return_value = {
            "updated": True, "event": stored, "date": "2026-09-08",
        }
        events_mock._file_path.side_effect = lambda d: f"data/events/{d}.json"
        return events_mock

    def test_edit_patches_the_google_entry(self, agent, mock_services):
        """Without this the ledger changes, Google does not, and the next
        merge puts the old value back."""
        from unittest.mock import AsyncMock
        self._wire(mock_services, self._stored())
        agent.calendar.is_initialized = True
        agent.calendar.update_event = AsyncMock(return_value=True)

        result = agent._tool_update_event({"event_id": "evt_1", "name": "Morning sync"})

        agent.calendar.update_event.assert_awaited_once()
        assert result["data"]["calendar_sync"]["ok"] is True

    def test_event_in_another_calendar_is_not_patched(self, agent, mock_services):
        from unittest.mock import AsyncMock
        self._wire(mock_services, self._stored(calendar="Work"))
        agent.calendar.is_initialized = True
        agent.calendar.update_event = AsyncMock(return_value=True)

        result = agent._tool_update_event({"event_id": "evt_1", "name": "X"})

        agent.calendar.update_event.assert_not_awaited()
        assert result["data"]["calendar_sync"]["reason"] == "not_in_mazkir_calendar"

    def test_a_block_with_a_start_but_no_end_is_synced(self, agent, mock_services):
        """Deliberately inverted on 2026-09-12.

        This used to assert that a start-without-end block was NOT synced.
        That is the shape of every reminder — "give Matia the pill at 22:00"
        has no end — and refusing to sync it is why two reminders asked for
        on 2026-09-11 never reached Google while the agent reported success.
        `_build_event` defaults a missing end to start + the default span, so
        there was never anything Google could not accept.
        """
        from unittest.mock import AsyncMock
        self._wire(mock_services, self._stored(end_time=None, source_ids={}))
        agent.calendar.is_initialized = True
        agent.calendar.create_event = AsyncMock(return_value="gcal_new")

        result = agent._tool_update_event({"event_id": "evt_1", "name": "X"})

        agent.calendar.create_event.assert_awaited()
        assert result["data"]["calendar_sync"]["ok"] is True
        assert result["data"]["calendar_sync"]["event_id"] == "gcal_new"
        # The end really was absent — this is not a fixture that quietly had
        # one, which would make the test pass for the wrong reason.
        kwargs = agent.calendar.create_event.await_args.kwargs
        assert kwargs["end_time"] is None
        assert kwargs["start_time"] == "10:00"

    def test_a_block_with_no_start_is_still_not_synced(self, agent, mock_services):
        """The narrowing has to stop somewhere: an event known only by when
        it ended cannot be described to Google at all."""
        from unittest.mock import AsyncMock
        self._wire(mock_services, self._stored(start_time=None, source_ids={}))
        agent.calendar.is_initialized = True
        agent.calendar.create_event = AsyncMock(return_value="gcal_new")

        result = agent._tool_update_event({"event_id": "evt_1", "name": "X"})

        agent.calendar.create_event.assert_not_awaited()
        assert result["data"]["calendar_sync"]["reason"] == "no_start_time"

    def test_completing_a_block_creates_its_calendar_entry(self, agent, mock_services):
        """'Sync it once it's complete' needs no flag: the absence of a
        calendar_id already records that it is not in the calendar yet."""
        from unittest.mock import AsyncMock
        stored = self._stored(source_ids={}, calendar=None)
        events_mock = self._wire(mock_services, stored)
        events_mock.update_event.return_value = {
            "updated": True, "event": stored, "date": "2026-09-08",
        }
        agent.calendar.is_initialized = True
        agent.calendar.create_event = AsyncMock(return_value="gcal_new")

        result = agent._tool_update_event({
            "event_id": "evt_1", "end_time": "2026-09-08T10:30:00",
        })

        agent.calendar.create_event.assert_awaited_once()
        assert result["data"]["calendar_sync"]["event_id"] == "gcal_new"

    def test_completing_a_block_persists_the_new_calendar_id(self, agent, mock_services):
        """Without this, the presence of calendar_id never comes to be true,
        so every later edit re-takes the create branch and produces another
        duplicate Google Calendar entry."""
        from unittest.mock import AsyncMock
        stored = self._stored(source_ids={}, calendar=None)
        events_mock = self._wire(mock_services, stored)
        events_mock.update_event.return_value = {
            "updated": True, "event": stored, "date": "2026-09-08",
        }
        agent.calendar.is_initialized = True
        agent.calendar.create_event = AsyncMock(return_value="gcal_new")

        agent._tool_update_event({
            "event_id": "evt_1", "end_time": "2026-09-08T10:30:00",
        })

        # The first call is the ledger write itself; the second is this
        # sync block persisting the new calendar_id back into source_ids.
        assert events_mock.update_event.call_count == 2
        persist_updates = events_mock.update_event.call_args_list[-1].kwargs["updates"]
        assert persist_updates["source_ids"]["calendar_id"] == "gcal_new"

    def test_second_edit_after_completion_takes_the_patch_branch(self, agent, mock_services):
        """'Sync it once it's complete' must not repeat on every later edit
        — the completion write has to leave calendar_id behind for the next
        lookup to see, or every edit after the first creates a duplicate."""
        from unittest.mock import AsyncMock
        events_mock = mock_services[4]
        events_mock.resolve_event_date.return_value = "2026-09-08"
        events_mock._file_path.side_effect = lambda d: f"data/events/{d}.json"
        agent.calendar.is_initialized = True
        agent.calendar.create_event = AsyncMock(return_value="gcal_new")
        agent.calendar.update_event = AsyncMock(return_value=True)

        # The block is completed by this edit — no calendar_id yet.
        incomplete = self._stored(source_ids={}, calendar=None)
        events_mock.get_events.return_value = [incomplete]
        events_mock.update_event.return_value = {
            "updated": True, "event": incomplete, "date": "2026-09-08",
        }
        agent._tool_update_event({
            "event_id": "evt_1", "end_time": "2026-09-08T10:30:00",
        })
        agent.calendar.create_event.assert_awaited_once()
        agent.calendar.update_event.assert_not_awaited()

        # A second edit now finds calendar_id already present (what the
        # first call's persistence should have produced) and must patch.
        now_complete = self._stored(source_ids={"calendar_id": "gcal_new"}, calendar="Mazkir")
        events_mock.get_events.return_value = [now_complete]
        events_mock.update_event.return_value = {
            "updated": True, "event": now_complete, "date": "2026-09-08",
        }
        agent._tool_update_event({"event_id": "evt_1", "name": "Renamed"})

        agent.calendar.update_event.assert_awaited_once()
        assert agent.calendar.create_event.await_count == 1

    def test_photo_event_is_never_synced(self, agent, mock_services):
        """The update ladder must skip photo events for the same reason
        create_event does — they are deliberately never pushed to Google."""
        from unittest.mock import AsyncMock
        self._wire(mock_services, self._stored(source="photo"))
        agent.calendar.is_initialized = True
        agent.calendar.update_event = AsyncMock(return_value=True)
        agent.calendar.create_event = AsyncMock(return_value="gcal_new")

        result = agent._tool_update_event({"event_id": "evt_1", "name": "X"})

        agent.calendar.update_event.assert_not_awaited()
        agent.calendar.create_event.assert_not_awaited()
        assert result["data"]["calendar_sync"]["reason"] == "not_applicable"

    def test_midnight_crossing_block_is_not_synced(self, agent, mock_services):
        """Google stores a midnight-spanning interval as one event; the
        create path already refuses this, and an edit that produces one
        must refuse it too rather than push a value the day-fragmenting
        split can't represent."""
        from unittest.mock import AsyncMock
        self._wire(mock_services, self._stored(
            start_time="2026-09-08T23:30:00", end_time="2026-09-09T00:30:00",
            source_ids={}, calendar=None,
        ))
        agent.calendar.is_initialized = True
        agent.calendar.create_event = AsyncMock(return_value="gcal_new")

        result = agent._tool_update_event({"event_id": "evt_1", "name": "X"})

        agent.calendar.create_event.assert_not_awaited()
        assert result["data"]["calendar_sync"]["reason"] == "crosses_midnight"

    def test_patch_failure_without_exception_carries_a_reason(self, agent, mock_services):
        """attempted: true means the user has to be told something did not
        happen — a bare ok: False with no reason gives the agent nothing to
        say."""
        from unittest.mock import AsyncMock
        self._wire(mock_services, self._stored())
        agent.calendar.is_initialized = True
        agent.calendar.update_event = AsyncMock(return_value=False)

        result = agent._tool_update_event({"event_id": "evt_1", "name": "X"})

        sync = result["data"]["calendar_sync"]
        assert sync["ok"] is False
        assert sync["reason"] == "update_failed"

    def test_a_source_derived_block_is_never_created_in_the_calendar(self, agent, mock_services):
        """The create branch exists for blocks Mazkir owns. An inferred
        block — a timed checkbox, a habit, a location visit — is regenerated
        from its source on every merge, so creating a Google entry for it
        both duplicates the entry and gives the persisted event a second
        source_ids key, after which two fresh events match the one
        persisted row and the block renders twice forever.
        """
        from unittest.mock import AsyncMock
        self._wire(mock_services, self._stored(
            source_ids={"note_line": "h"}, calendar=None,
        ))
        agent.calendar.is_initialized = True
        agent.calendar.create_event = AsyncMock(return_value="gcal_new")

        result = agent._tool_update_event({"event_id": "evt_1", "name": "X"})

        agent.calendar.create_event.assert_not_awaited()
        assert result["data"]["calendar_sync"] == {
            "ok": False, "attempted": False, "reason": "derived_from_source",
        }

    def test_a_source_derived_block_with_a_calendar_id_is_still_patched(self, agent, mock_services):
        """The gate is on *creating*, not on syncing: a block that already
        carries a calendar_id genuinely is a calendar event, whatever else
        its source_ids say."""
        from unittest.mock import AsyncMock
        self._wire(mock_services, self._stored(
            source_ids={"note_line": "h", "calendar_id": "gcal_1"}, calendar="Mazkir",
        ))
        agent.calendar.is_initialized = True
        agent.calendar.update_event = AsyncMock(return_value=True)

        result = agent._tool_update_event({"event_id": "evt_1", "name": "X"})

        agent.calendar.update_event.assert_awaited_once()
        assert result["data"]["calendar_sync"]["ok"] is True

    def test_create_failure_without_exception_carries_a_reason(self, agent, mock_services):
        from unittest.mock import AsyncMock
        stored = self._stored(source_ids={}, calendar=None)
        events_mock = self._wire(mock_services, stored)
        events_mock.update_event.return_value = {
            "updated": True, "event": stored, "date": "2026-09-08",
        }
        agent.calendar.is_initialized = True
        agent.calendar.create_event = AsyncMock(return_value=None)

        result = agent._tool_update_event({
            "event_id": "evt_1", "end_time": "2026-09-08T10:30:00",
        })

        sync = result["data"]["calendar_sync"]
        assert sync["ok"] is False
        assert sync["reason"] == "create_failed"


class TestIncompleteBlocksInContext:
    """Push, not pull.

    Ship 3's lesson: the agent will not call a tool to discover something
    it does not know to look for. Bug B was one iteration and zero tool
    calls with two read tools in hand.
    """

    def test_incomplete_blocks_appear_in_the_prompt_tail(self, agent, mock_services):
        from types import SimpleNamespace
        events_mock = mock_services[4]
        events_mock.get_events.return_value = [
            {"id": "e1", "name": "Dog walk", "start_time": None,
             "end_time": "2026-09-08T16:40:00"},
            {"id": "e2", "name": "Standup", "start_time": "2026-09-08T10:00:00",
             "end_time": "2026-09-08T10:30:00"},
        ]
        # test_agent_service.py defines its OWN mock_services fixture, and
        # unlike conftest.py's it does not set `tz` — leaving `vault.tz` a
        # MagicMock that `datetime.now()` would silently accept, making the
        # test pass for the wrong reason.
        import pytz
        mock_services[1].tz = pytz.timezone("Asia/Jerusalem")
        ctx = SimpleNamespace(vault_snapshot="1 task", knowledge=None)

        prompt = agent._build_system_prompt(ctx)

        assert "Incomplete blocks today: 1" in prompt
        assert "Dog walk" in prompt
        assert "no start time" in prompt
        assert "Standup" not in prompt

    def test_no_line_when_every_block_is_complete(self, agent, mock_services):
        from types import SimpleNamespace
        events_mock = mock_services[4]
        events_mock.get_events.return_value = [
            {"id": "e2", "name": "Standup", "start_time": "2026-09-08T10:00:00",
             "end_time": "2026-09-08T10:30:00"},
        ]
        import pytz
        mock_services[1].tz = pytz.timezone("Asia/Jerusalem")
        ctx = SimpleNamespace(vault_snapshot="1 task", knowledge=None)

        assert "Incomplete blocks" not in agent._build_system_prompt(ctx)

    def test_a_failing_read_costs_the_line_not_the_turn(self, agent, mock_services):
        from types import SimpleNamespace
        import pytz
        mock_services[1].tz = pytz.timezone("Asia/Jerusalem")
        mock_services[4].get_events.side_effect = OSError("disk gone")
        ctx = SimpleNamespace(vault_snapshot="1 task", knowledge=None)

        prompt = agent._build_system_prompt(ctx)

        assert "Current date/time" in prompt
        assert "Incomplete blocks" not in prompt


class TestSelectedDateInPromptTail:
    """The hint is almost always redundant with 'Current date/time' — a
    plain /day with no argument returns today, so it must be suppressed
    exactly then, or the one time it is informative gets skimmed past."""

    def test_absent_when_selected_date_is_today(self, agent, mock_services):
        from types import SimpleNamespace
        import datetime
        import pytz
        mock_services[1].tz = pytz.timezone("Asia/Jerusalem")
        mock_services[4].get_events.return_value = []
        ctx = SimpleNamespace(vault_snapshot="1 task", knowledge=None)
        agent._selected_date = datetime.datetime.now().strftime("%Y-%m-%d")

        prompt = agent._build_system_prompt(ctx)

        assert "currently viewing" not in prompt

    def test_present_when_selected_date_differs_from_today(self, agent, mock_services):
        from types import SimpleNamespace
        import datetime
        import pytz
        mock_services[1].tz = pytz.timezone("Asia/Jerusalem")
        mock_services[4].get_events.return_value = []
        ctx = SimpleNamespace(vault_snapshot="1 task", knowledge=None)
        yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        agent._selected_date = yesterday

        prompt = agent._build_system_prompt(ctx)

        assert f"The user is currently viewing {yesterday}." in prompt


class TestReminderReachesTheCalendar:
    """The 2026-09-11 Milpro regression, pinned.

    "Add calendar reminder to give the next one after 1 month" produced two
    rows with `source_ids: {}` and `calendar_sync: {attempted: false, reason:
    "incomplete"}` — never sent to Google — while the agent replied "Done! 📅
    Reminder created". Verified against the Google API on 2026-09-12: the
    Mazkir calendar held only a Dog Walk that day.
    """

    def test_a_reminder_with_only_a_start_is_sent_to_google(self, agent, mock_services):
        from unittest.mock import AsyncMock
        events_mock = mock_services[4]
        events_mock.create_event.return_value = {"id": "evt_1", "path": "p"}
        agent.calendar = AsyncMock()
        agent.calendar.is_initialized = True
        agent.calendar.create_event = AsyncMock(return_value="gcal_pill")

        result = agent._tool_create_event({
            "name": "Give Matia Milpro pill",
            "date": "2026-10-11",
            "start_time": "22:00",
            "duration_minutes": 5,
            "remind_minutes_before": [10],
        })

        sync = result["data"]["calendar_sync"]
        assert sync["attempted"] is True
        assert sync["ok"] is True
        # The id has to land in source_ids, or the next merge treats the event
        # as never synced and creates a duplicate.
        assert events_mock.create_event.call_args.kwargs["source_ids"] == {
            "calendar_id": "gcal_pill",
        }

    def test_the_span_and_alerts_the_agent_chose_reach_google(self, agent, mock_services):
        """Mazkir used to impose 30 minutes and one 10-minute popup on
        everything. The agent is the part that knows a pill is five minutes
        and a dentist trip wants a day's warning, so its choice has to be
        forwarded rather than dropped."""
        from unittest.mock import AsyncMock
        events_mock = mock_services[4]
        events_mock.create_event.return_value = {"id": "evt_1", "path": "p"}
        agent.calendar = AsyncMock()
        agent.calendar.is_initialized = True
        agent.calendar.create_event = AsyncMock(return_value="gcal_1")

        agent._tool_create_event({
            "name": "Dentist", "date": "2026-10-11", "start_time": "09:00",
            "duration_minutes": 45, "remind_minutes_before": [1440, 60],
        })

        kwargs = agent.calendar.create_event.await_args.kwargs
        assert kwargs["duration_minutes"] == 45
        assert kwargs["remind_minutes_before"] == [1440, 60]
