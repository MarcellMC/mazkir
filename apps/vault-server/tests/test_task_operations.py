"""Tests for VaultService task operations."""
import pytest


def test_create_task_with_defaults(vault_service, vault_path):
    result = vault_service.create_task("Buy milk")

    assert result["path"] == "40-tasks/active/buy-milk.md"
    assert result["metadata"]["name"] == "Buy milk"
    assert result["metadata"]["priority"] == 3
    assert result["metadata"]["category"] == "personal"
    assert result["metadata"]["status"] == "active"
    assert result["metadata"]["tokens_on_completion"] == 5
    assert (vault_path / "40-tasks" / "active" / "buy-milk.md").exists()


def test_create_task_with_custom_params(vault_service):
    result = vault_service.create_task(
        "Ship feature",
        priority=5,
        due_date="2026-03-15",
        category="work",
        tokens_on_completion=50,
    )

    assert result["metadata"]["priority"] == 5
    assert result["metadata"]["due_date"] == "2026-03-15"
    assert result["metadata"]["category"] == "work"
    assert result["metadata"]["tokens_on_completion"] == 50


def test_list_active_tasks_sorted_by_priority_then_due_date(vault_service):
    tasks = vault_service.list_active_tasks()

    names = [t["metadata"]["name"] for t in tasks]
    # Priority 5 first, then 3, then 2
    assert names[0] == "Finish report"    # priority 5
    assert names[1] == "Buy groceries"    # priority 3
    assert names[2] == "Learn Rust basics"  # priority 2


def test_find_task_by_name_exact(vault_service):
    task = vault_service.find_task_by_name("Buy groceries")
    assert task is not None
    assert task["metadata"]["name"] == "Buy groceries"


def test_find_task_by_name_partial(vault_service):
    task = vault_service.find_task_by_name("groceries")
    assert task is not None
    assert task["metadata"]["name"] == "Buy groceries"


def test_find_task_by_name_case_insensitive(vault_service):
    task = vault_service.find_task_by_name("BUY GROCERIES")
    assert task is not None


def test_find_task_by_name_no_match(vault_service):
    task = vault_service.find_task_by_name("nonexistent task xyz")
    assert task is None


def test_complete_task_moves_to_archive(vault_service, vault_path):
    result = vault_service.complete_task("40-tasks/active/buy-groceries.md")

    assert result["task_name"] == "Buy groceries"
    assert result["tokens_earned"] == 5
    assert result["archive_path"] == "40-tasks/archive/buy-groceries.md"

    # Verify file moved
    assert not (vault_path / "40-tasks" / "active" / "buy-groceries.md").exists()
    assert (vault_path / "40-tasks" / "archive" / "buy-groceries.md").exists()

    # Verify archived metadata
    archived = vault_service.read_file("40-tasks/archive/buy-groceries.md")
    assert archived["metadata"]["status"] == "done"
    assert "completed_date" in archived["metadata"]


def test_get_tasks_needing_sync(vault_service):
    # All sample tasks have google_event_id: null and only some have due dates
    tasks = vault_service.get_tasks_needing_sync()
    names = {t["metadata"]["name"] for t in tasks}

    # Only tasks with due_date AND no google_event_id
    assert "Buy groceries" in names     # has due_date, no event_id
    assert "Finish report" in names     # has due_date, no event_id
    assert "Learn Rust basics" not in names  # no due_date
