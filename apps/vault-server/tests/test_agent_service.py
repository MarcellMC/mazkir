"""Tests for AgentService — tool registry, confidence gate, loop control."""

from unittest.mock import MagicMock

import pytest

from src.services.agent_service import AgentService, AgentResponse, CONFIDENCE_THRESHOLD


@pytest.fixture
def mock_services():
    """Create mock service dependencies."""
    claude = MagicMock()
    vault = MagicMock()
    memory = MagicMock()
    calendar = MagicMock()

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
