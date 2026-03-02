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


class TestKnowledgeCRUD:
    def test_save_knowledge_creates_note(self, memory_service, vault_path):
        result = memory_service.save_knowledge(
            name="Dentist location",
            content="Dentist is on Av. Roma 1234, Dr. Garcia.",
            tags=["health", "locations"],
            links=[],
            source="conversation",
        )
        assert result["path"].startswith("60-knowledge/notes/")
        assert (vault_path / result["path"]).exists()

    def test_save_knowledge_stores_metadata(self, memory_service):
        result = memory_service.save_knowledge(
            name="Test note",
            content="Some content.",
            tags=["test"],
            links=["[[gym]]"],
            source="conversation",
        )
        note = memory_service.vault.read_file(result["path"])
        assert note["metadata"]["name"] == "Test note"
        assert note["metadata"]["type"] == "knowledge"
        assert note["metadata"]["tags"] == ["test"]
        assert "[[gym]]" in note["metadata"]["links"]
        assert note["metadata"]["source"] == "conversation"

    def test_save_knowledge_insight(self, memory_service, vault_path):
        result = memory_service.save_knowledge(
            name="Health routine gap",
            content="User creates meal tasks after gym.",
            tags=["health"],
            links=["[[gym]]"],
            source="inferred",
        )
        assert result["path"].startswith("60-knowledge/insights/")

    def test_search_knowledge_finds_by_tag(self, memory_service):
        memory_service.save_knowledge(
            name="Gym schedule",
            content="Morning sessions work best.",
            tags=["health", "gym"],
            links=[],
            source="conversation",
        )
        memory_service.save_knowledge(
            name="Python tips",
            content="Use dataclasses.",
            tags=["programming"],
            links=[],
            source="conversation",
        )

        results = memory_service.search_knowledge("health gym")
        assert len(results) >= 1
        assert any("gym-schedule" in r["path"] for r in results)

    def test_search_knowledge_finds_by_name(self, memory_service):
        memory_service.save_knowledge(
            name="Dentist location",
            content="Av. Roma 1234",
            tags=["health"],
            links=[],
            source="conversation",
        )

        results = memory_service.search_knowledge("dentist")
        assert len(results) >= 1

    def test_search_knowledge_returns_empty_for_no_match(self, memory_service):
        results = memory_service.search_knowledge("quantum physics")
        assert results == []


class TestPreferences:
    def test_update_preference_creates_new(self, memory_service, vault_path):
        memory_service.update_preference(
            name="Task defaults",
            observation="User set priority to 1 for grocery task",
        )
        pref_path = vault_path / "00-system" / "preferences" / "task-defaults.md"
        assert pref_path.exists()

    def test_update_preference_increments_observations(self, memory_service):
        memory_service.update_preference("Task defaults", "First observation")
        memory_service.update_preference("Task defaults", "Second observation")

        pref_path = "00-system/preferences/task-defaults.md"
        data = memory_service.vault.read_file(pref_path)
        assert data["metadata"]["observations"] == 2

    def test_update_preference_appends_content(self, memory_service):
        memory_service.update_preference("Task defaults", "User prefers priority 1")
        memory_service.update_preference("Task defaults", "User prefers due dates")

        pref_path = "00-system/preferences/task-defaults.md"
        data = memory_service.vault.read_file(pref_path)
        assert "User prefers priority 1" in data["content"]
        assert "User prefers due dates" in data["content"]
