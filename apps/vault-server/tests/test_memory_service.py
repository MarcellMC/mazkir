"""Tests for MemoryService."""

import datetime
from unittest.mock import MagicMock

import pytest

from src.services.memory_service import ConversationContext, MemoryService


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


class TestGraphIndex:
    def test_rebuild_graph_indexes_existing_files(self, memory_service, vault_path):
        """The conftest vault_path fixture creates sample habits/tasks/goals."""
        memory_service._rebuild_graph()
        assert len(memory_service.graph) > 0

    def test_graph_node_has_tags(self, memory_service, vault_path):
        memory_service._rebuild_graph()
        if "buy-groceries" in memory_service.graph:
            node = memory_service.graph["buy-groceries"]
            assert "tags" in node

    def test_graph_extracts_wikilinks(self, memory_service, vault_path):
        memory_service.save_knowledge(
            name="Morning routine",
            content="Start with [[gym]] then [[meditation]].",
            tags=["health"],
            links=["[[gym]]", "[[meditation]]"],
            source="conversation",
        )
        memory_service._rebuild_graph()
        assert "morning-routine" in memory_service.graph
        node = memory_service.graph["morning-routine"]
        assert "gym" in node["links_to"]

    def test_get_related_returns_neighbors(self, memory_service, vault_path):
        memory_service.save_knowledge("Node A", "Links to [[node-b]].", ["test"], ["[[node-b]]"], "conversation")
        memory_service.save_knowledge("Node B", "Links to [[node-c]].", ["test"], ["[[node-c]]"], "conversation")
        memory_service.save_knowledge("Node C", "End node.", ["test"], [], "conversation")
        memory_service._rebuild_graph()

        related = memory_service.get_related("node-a", depth=2)
        node_ids = [r["id"] for r in related]
        assert "node-a" in node_ids
        assert "node-b" in node_ids
        assert "node-c" in node_ids

    def test_get_related_respects_depth(self, memory_service, vault_path):
        memory_service.save_knowledge("A", "[[b]]", ["test"], ["[[b]]"], "conversation")
        memory_service.save_knowledge("B", "[[c]]", ["test"], ["[[c]]"], "conversation")
        memory_service.save_knowledge("C", "end", ["test"], [], "conversation")
        memory_service._rebuild_graph()

        related = memory_service.get_related("a", depth=1)
        node_ids = [r["id"] for r in related]
        assert "a" in node_ids
        assert "b" in node_ids
        assert "c" not in node_ids

    def test_get_related_returns_empty_for_unknown(self, memory_service):
        memory_service._rebuild_graph()
        related = memory_service.get_related("nonexistent-node", depth=1)
        assert related == []

    def test_get_most_connected(self, memory_service, vault_path):
        memory_service.save_knowledge("Hub", "Central topic.", ["test"], [], "conversation")
        memory_service.save_knowledge("Spoke 1", "About [[hub]].", ["test"], ["[[hub]]"], "conversation")
        memory_service.save_knowledge("Spoke 2", "Also [[hub]].", ["test"], ["[[hub]]"], "conversation")
        memory_service.save_knowledge("Spoke 3", "And [[hub]].", ["test"], ["[[hub]]"], "conversation")
        memory_service._rebuild_graph()

        top = memory_service.get_most_connected(limit=1)
        assert top[0]["id"] == "hub"

    def test_get_most_connected_filters_by_tag(self, memory_service, vault_path):
        memory_service.save_knowledge("Health hub", "Main.", ["health"], [], "conversation")
        memory_service.save_knowledge("H1", "[[health-hub]]", ["health"], ["[[health-hub]]"], "conversation")
        memory_service.save_knowledge("H2", "[[health-hub]]", ["health"], ["[[health-hub]]"], "conversation")
        memory_service.save_knowledge("Code hub", "Main.", ["code"], [], "conversation")
        memory_service.save_knowledge("C1", "[[code-hub]]", ["code"], ["[[code-hub]]"], "conversation")
        memory_service._rebuild_graph()

        top_health = memory_service.get_most_connected(tag="health", limit=1)
        assert top_health[0]["id"] == "health-hub"


class TestContextAssembly:
    def test_assemble_context_returns_dataclass(self, memory_service):
        ctx = memory_service.assemble_context(chat_id=123456)
        assert isinstance(ctx, ConversationContext)
        assert isinstance(ctx.messages, list)
        assert isinstance(ctx.summary, str)
        assert isinstance(ctx.vault_snapshot, str)
        assert isinstance(ctx.knowledge, str)

    def test_assemble_context_includes_conversation(self, memory_service):
        memory_service.save_turn(123456, "hello", "hi there", [])
        ctx = memory_service.assemble_context(123456)
        assert len(ctx.messages) == 2
        assert ctx.messages[0]["content"] == "hello"

    def test_assemble_context_includes_vault_snapshot(self, memory_service):
        ctx = memory_service.assemble_context(123456)
        assert "task" in ctx.vault_snapshot.lower() or "habit" in ctx.vault_snapshot.lower()

    def test_assemble_context_includes_preferences(self, memory_service):
        memory_service.update_preference("Test pref", "Some observation")
        ctx = memory_service.assemble_context(123456)
        assert "Test pref" in ctx.knowledge or "test pref" in ctx.knowledge.lower()


class TestConversationDecay:
    def test_summarize_and_decay_does_nothing_under_window(self, memory_service):
        memory_service.window_size = 10
        memory_service.save_turn(123456, "hello", "hi", [])
        before = memory_service.load_conversation(123456)
        memory_service.summarize_and_decay(123456)
        after = memory_service.load_conversation(123456)
        assert before["message_count"] == after["message_count"]

    def test_summarize_and_decay_compresses_when_over_window(self, memory_service):
        memory_service.window_size = 4

        mock_claude = MagicMock()
        mock_claude.complete.return_value = "User greeted and discussed tasks."
        memory_service._claude = mock_claude

        for i in range(4):
            memory_service.save_turn(123456, f"msg {i}", f"reply {i}", [])

        memory_service.summarize_and_decay(123456)

        result = memory_service.load_conversation(123456)
        assert result["summary"] != ""
        assert result["message_count"] == 8
