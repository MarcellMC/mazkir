"""End-to-end integration test for the agent loop."""

from unittest.mock import MagicMock

import pytest

from src.services.memory_service import MemoryService
from src.services.agent_service import AgentService


@pytest.fixture
def agent_with_vault(vault_service, vault_path):
    """Create a fully wired AgentService with real vault, mocked Claude."""
    memory = MemoryService(
        vault=vault_service,
        vault_path=vault_path,
        timezone="Asia/Jerusalem",
    )
    (vault_path / "00-system" / "conversations").mkdir(parents=True, exist_ok=True)
    (vault_path / "00-system" / "preferences").mkdir(parents=True, exist_ok=True)
    (vault_path / "60-knowledge" / "notes").mkdir(parents=True, exist_ok=True)
    (vault_path / "60-knowledge" / "insights").mkdir(parents=True, exist_ok=True)
    memory.initialize()

    claude = MagicMock()

    agent = AgentService(
        claude=claude,
        vault=vault_service,
        memory=memory,
        calendar=None,
    )

    return agent, claude, memory


class TestEndToEnd:
    def test_simple_question_no_tools(self, agent_with_vault):
        agent, claude, _ = agent_with_vault

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "You have 1 active task: Buy groceries (P3)."
        mock_response.content = [text_block]
        claude.create.return_value = mock_response

        result = agent.handle_message("what are my tasks?", chat_id=111)

        assert "Buy groceries" in result.response
        assert not result.awaiting_confirmation

    def test_tool_call_creates_task(self, agent_with_vault):
        agent, claude, _ = agent_with_vault

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "create_task"
        tool_block.id = "call_1"
        tool_block.input = {
            "name": "Buy milk",
            "priority": 1,
            "_confidence": 0.95,
            "_reasoning": "User clearly asked to create a task",
        }
        mock_tool_response = MagicMock()
        mock_tool_response.stop_reason = "tool_use"
        mock_tool_response.content = [tool_block]

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Created task: Buy milk (P1)"
        mock_text_response = MagicMock()
        mock_text_response.stop_reason = "end_turn"
        mock_text_response.content = [text_block]

        claude.create.side_effect = [mock_tool_response, mock_text_response]

        result = agent.handle_message("create task buy milk, priority 1", chat_id=111)

        assert "Buy milk" in result.response

    def test_conversation_context_persists(self, agent_with_vault):
        agent, claude, memory = agent_with_vault

        mock_r1 = MagicMock()
        mock_r1.stop_reason = "end_turn"
        tb1 = MagicMock(); tb1.type = "text"; tb1.text = "Created task!"
        mock_r1.content = [tb1]

        mock_r2 = MagicMock()
        mock_r2.stop_reason = "end_turn"
        tb2 = MagicMock(); tb2.type = "text"; tb2.text = "Updated!"
        mock_r2.content = [tb2]

        claude.create.side_effect = [mock_r1, mock_r2]

        agent.handle_message("create task buy milk", chat_id=222)
        agent.handle_message("set it to due tomorrow", chat_id=222)

        second_call = claude.create.call_args_list[1]
        messages = second_call[1]["messages"]
        assert any("create task buy milk" in str(m.get("content", "")) for m in messages)

    def test_low_confidence_triggers_confirmation(self, agent_with_vault):
        agent, claude, _ = agent_with_vault

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "complete_task"
        tool_block.id = "call_2"
        tool_block.input = {
            "task_name": "groceries",
            "_confidence": 0.4,
            "_reasoning": "not sure which task",
        }
        mock_response = MagicMock()
        mock_response.stop_reason = "tool_use"
        mock_response.content = [tool_block]
        claude.create.return_value = mock_response

        result = agent.handle_message("maybe finish that thing", chat_id=333)

        assert result.awaiting_confirmation is True
        assert result.pending_action_id is not None
