"""Tests for VaultService goal operations."""
import pytest
from unittest.mock import patch
from datetime import datetime


def test_create_goal_with_defaults(vault_service, vault_path):
    with patch("src.services.vault_service.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 2, 28, 12, 0, 0)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = vault_service.create_goal("Run a marathon")

    assert result["path"] == "30-goals/2026/run-a-marathon.md"
    assert result["metadata"]["name"] == "Run a marathon"
    assert result["metadata"]["status"] == "not-started"
    assert result["metadata"]["priority"] == "medium"
    assert result["metadata"]["progress"] == 0
    assert (vault_path / "30-goals" / "2026" / "run-a-marathon.md").exists()


def test_create_goal_with_custom_params(vault_service):
    result = vault_service.create_goal(
        "Save money",
        priority="high",
        target_date="2026-12-31",
        category="finance",
    )

    assert result["metadata"]["priority"] == "high"
    assert result["metadata"]["target_date"] == "2026-12-31"
    assert result["metadata"]["category"] == "finance"


def test_list_active_goals_filters_completed(vault_service):
    goals = vault_service.list_active_goals()
    names = {g["metadata"]["name"] for g in goals}

    assert "Get fit" in names          # in-progress
    assert "Learn Python" in names     # not-started
    assert "Done goal" not in names    # completed


def test_list_active_goals_sorted_by_priority_then_progress(vault_service):
    goals = vault_service.list_active_goals()
    names = [g["metadata"]["name"] for g in goals]

    # high priority first, then medium
    assert names[0] == "Get fit"       # high priority, 30% progress
    assert names[1] == "Learn Python"  # medium priority, 0% progress
