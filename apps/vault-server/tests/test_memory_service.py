"""Tests for MemoryService conversation management."""

import datetime

import pytest

from src.services.memory_service import MemoryService


@pytest.fixture
def memory_service(vault_service, vault_path):
    """Create MemoryService with test vault."""
    # Create required directories
    (vault_path / "00-system" / "conversations").mkdir(parents=True, exist_ok=True)
    (vault_path / "00-system" / "preferences").mkdir(parents=True, exist_ok=True)
    (vault_path / "60-knowledge" / "notes").mkdir(parents=True, exist_ok=True)
    (vault_path / "60-knowledge" / "insights").mkdir(parents=True, exist_ok=True)

    service = MemoryService(
        vault=vault_service,
        vault_path=vault_path,
        timezone="Asia/Jerusalem",
    )
    return service


class TestConversationManagement:
    def test_load_conversation_returns_empty_for_new_chat(self, memory_service):
        result = memory_service.load_conversation(chat_id=123456)
        assert result["messages"] == []
        assert result["summary"] == ""

    def test_save_turn_creates_conversation_file(self, memory_service, vault_path):
        memory_service.save_turn(
            chat_id=123456,
            user_msg="hello",
            assistant_msg="hi there",
            items_referenced=[],
        )
        today = datetime.date.today().isoformat()
        conv_dir = vault_path / "00-system" / "conversations" / today
        conv_file = conv_dir / "123456.md"
        assert conv_file.exists()

    def test_save_turn_appends_messages(self, memory_service):
        memory_service.save_turn(123456, "first message", "first reply", [])
        memory_service.save_turn(123456, "second message", "second reply", [])

        result = memory_service.load_conversation(123456)
        assert len(result["messages"]) == 4  # 2 user + 2 assistant

    def test_save_turn_updates_frontmatter(self, memory_service):
        memory_service.save_turn(123456, "hello", "hi", [])
        memory_service.save_turn(123456, "create task", "done", ["40-tasks/active/test.md"])

        result = memory_service.load_conversation(123456)
        assert result["message_count"] == 4
        assert "40-tasks/active/test.md" in result["items_referenced"]

    def test_load_conversation_respects_window_size(self, memory_service):
        memory_service.window_size = 4  # 2 turns = 4 messages
        # Save 4 turns (8 messages)
        for i in range(4):
            memory_service.save_turn(123456, f"msg {i}", f"reply {i}", [])

        result = memory_service.load_conversation(123456)
        # Should return only last window_size messages
        assert len(result["messages"]) == 4
        # Oldest messages should be accessible via raw file
        assert result["message_count"] == 8

    def test_save_turn_tracks_items_referenced(self, memory_service):
        memory_service.save_turn(
            123456, "done with gym", "completed!",
            items_referenced=["20-habits/gym.md"],
        )
        memory_service.save_turn(
            123456, "create task buy milk", "created!",
            items_referenced=["40-tasks/active/buy-milk.md"],
        )

        result = memory_service.load_conversation(123456)
        assert "20-habits/gym.md" in result["items_referenced"]
        assert "40-tasks/active/buy-milk.md" in result["items_referenced"]


class TestConversationContext:
    def test_get_conversation_file_path(self, memory_service):
        today = datetime.date.today().isoformat()
        path = memory_service._get_conversation_path(123456)
        assert str(path).endswith(f"{today}/123456.md")

    def test_parse_conversation_messages(self, memory_service):
        memory_service.save_turn(123456, "hello", "hi there", [])
        result = memory_service.load_conversation(123456)

        assert result["messages"][0]["role"] == "user"
        assert result["messages"][0]["content"] == "hello"
        assert result["messages"][1]["role"] == "assistant"
        assert result["messages"][1]["content"] == "hi there"
