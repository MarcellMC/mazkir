"""Tests for VaultService habit operations."""
import pytest


def test_create_habit_with_defaults(vault_service, vault_path):
    result = vault_service.create_habit("Meditate")

    assert result["path"] == "20-habits/meditate.md"
    assert result["metadata"]["name"] == "Meditate"
    assert result["metadata"]["frequency"] == "daily"
    assert result["metadata"]["streak"] == 0
    assert result["metadata"]["status"] == "active"
    assert (vault_path / "20-habits" / "meditate.md").exists()


def test_create_habit_with_custom_params(vault_service):
    result = vault_service.create_habit(
        "Run",
        frequency="3x/week",
        category="health",
        difficulty="hard",
        tokens_per_completion=20,
    )

    assert result["metadata"]["frequency"] == "3x/week"
    assert result["metadata"]["category"] == "health"
    assert result["metadata"]["difficulty"] == "hard"
    assert result["metadata"]["tokens_per_completion"] == 20


def test_list_active_habits_filters_inactive(vault_service):
    habits = vault_service.list_active_habits()
    names = {h["metadata"]["name"] for h in habits}

    assert "Workout" in names
    assert "Read book" in names
    assert "Old habit" not in names  # status: inactive


def test_read_habit(vault_service):
    data = vault_service.read_habit("workout")

    assert data["metadata"]["name"] == "Workout"
    assert data["metadata"]["streak"] == 5


def test_update_habit_returns_updated_data(vault_service):
    result = vault_service.update_habit("workout", {"streak": 6})

    assert result["metadata"]["streak"] == 6
    assert result["metadata"]["name"] == "Workout"  # preserved


def test_get_habits_needing_sync(vault_service):
    habits = vault_service.get_habits_needing_sync()
    names = {h["metadata"]["name"] for h in habits}

    # workout has google_event_id=evt-123, read-book has null
    assert "Read book" in names
    assert "Workout" not in names
