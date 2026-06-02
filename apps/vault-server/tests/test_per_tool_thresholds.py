"""Tests for per-tool confidence thresholds with risk-class defaults."""

import pytest
import pytz
from unittest.mock import MagicMock

from src.services.agent_service import AgentService, _confidence_threshold_for
from src.services.memory_service import ConversationContext


@pytest.fixture
def mock_services(tmp_path):
    """Return a tuple of mock services matching test_agent_service.py convention."""
    claude = MagicMock()
    vault = MagicMock()
    memory = MagicMock()
    calendar = MagicMock()
    events = MagicMock()

    vault.vault_path = tmp_path / "vault"
    vault.vault_path.mkdir()
    vault.tz = pytz.timezone("Asia/Jerusalem")

    memory.assemble_context.return_value = ConversationContext(
        messages=[],
        summary="",
        vault_snapshot="No data.",
        knowledge="",
    )
    memory.save_turn = MagicMock()
    memory.summarize_and_decay = MagicMock()

    return claude, vault, memory, calendar, events


def test_default_thresholds_by_risk():
    assert _confidence_threshold_for(risk="safe") is None
    assert _confidence_threshold_for(risk="write") == 0.85
    assert _confidence_threshold_for(risk="destructive") == 0.95


def test_tool_carries_threshold_from_risk_default(mock_services):
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)
    # update_task is "write" with default threshold 0.85
    assert agent.tools["update_task"]["confidence_threshold"] == 0.85
    # delete_task is "destructive" with default threshold 0.95
    assert agent.tools["delete_task"]["confidence_threshold"] == 0.95
    # list_tasks is "safe" — threshold is None
    assert agent.tools["list_tasks"]["confidence_threshold"] is None


def test_gate_uses_per_tool_threshold_destructive(mock_services):
    """A 0.90 confidence destructive call fails the 0.95 gate."""
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)

    score, action = agent._check_confidence(
        name="delete_task",
        params={"task_name": "x", "_confidence": 0.90, "_reasoning": "test"},
    )
    assert action == "needs_confirmation"


def test_gate_passes_write_at_threshold(mock_services):
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)

    score, action = agent._check_confidence(
        name="update_task",
        params={"name": "x", "_confidence": 0.86, "_reasoning": "test"},
    )
    assert action == "auto_execute"


def test_gate_passes_safe_with_no_confidence(mock_services):
    """Safe tools don't need a confidence; auto-execute always."""
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)

    score, action = agent._check_confidence(name="list_tasks", params={})
    assert action == "auto_execute"
