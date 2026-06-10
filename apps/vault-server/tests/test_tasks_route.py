"""Tests for /tasks routes — slug detail endpoint + slug-based completion."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def find_task_by_slug(vault, slug):
    # Lazy import: importing src.main at module level would initialize tracing
    # during pytest collection and leak a global TracerProvider into other tests.
    import src.main  # noqa: F401 — break circular import (main imports route modules)
    from src.api.routes.tasks import find_task_by_slug as fn
    return fn(vault, slug)


def _task(path: str, name: str, **meta) -> dict:
    metadata = {
        "name": name,
        "status": "active",
        "priority": 3,
        "category": "personal",
        **meta,
    }
    return {"path": path, "metadata": metadata, "content": f"# {name}\n\n## Notes\n"}


SMARTOMICA = _task(
    "40-tasks/active/smartomica-do-overview-of-arbox-and-crm-for-clinic.md",
    "Smartomica: Do overview of Arbox and CRM for clinic patients management",
    priority=3,
    category="work",
)
GROCERIES = _task("40-tasks/active/buy-groceries.md", "Buy groceries")
GROCERIES_LIST = _task("40-tasks/active/buy-groceries-list.md", "Buy groceries list")


class TestFindTaskBySlug:
    def test_exact_stem_match(self):
        vault = MagicMock()
        vault.list_active_tasks.return_value = [SMARTOMICA, GROCERIES]
        task = find_task_by_slug(vault, "buy-groceries")
        assert task is GROCERIES

    def test_truncated_prefix_match(self):
        vault = MagicMock()
        vault.list_active_tasks.return_value = [SMARTOMICA, GROCERIES]
        # 54-byte truncation as produced by the Telegram inline keyboard
        task = find_task_by_slug(vault, "smartomica-do-overview-of-arbox-and-crm-for-clin")
        assert task is SMARTOMICA

    def test_exact_match_wins_over_prefix(self):
        vault = MagicMock()
        vault.list_active_tasks.return_value = [GROCERIES_LIST, GROCERIES]
        task = find_task_by_slug(vault, "buy-groceries")
        assert task is GROCERIES

    def test_ambiguous_prefix_returns_none(self):
        vault = MagicMock()
        vault.list_active_tasks.return_value = [GROCERIES, GROCERIES_LIST]
        assert find_task_by_slug(vault, "buy-grocerie") is None

    def test_no_match_returns_none(self):
        vault = MagicMock()
        vault.list_active_tasks.return_value = [GROCERIES]
        assert find_task_by_slug(vault, "nonexistent") is None


@pytest.fixture
def client():
    from src.main import app  # lazy: see find_task_by_slug note above
    return TestClient(app)


class TestGetTaskDetail:
    def test_returns_full_detail(self, client):
        vault = MagicMock()
        vault.list_active_tasks.return_value = [SMARTOMICA]
        with patch("src.api.routes.tasks.get_vault", return_value=vault):
            resp = client.get("/tasks/smartomica-do-overview-of-arbox-and-crm-for-clinic")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"].startswith("Smartomica")
        assert body["slug"] == "smartomica-do-overview-of-arbox-and-crm-for-clinic"
        assert body["category"] == "work"
        assert body["path"] == SMARTOMICA["path"]
        assert "## Notes" in body["content"]

    def test_unknown_slug_404(self, client):
        vault = MagicMock()
        vault.list_active_tasks.return_value = []
        with patch("src.api.routes.tasks.get_vault", return_value=vault):
            resp = client.get("/tasks/nonexistent")
        assert resp.status_code == 404


class TestCompleteTaskBySlug:
    def test_patch_resolves_slug(self, client):
        vault = MagicMock()
        vault.list_active_tasks.return_value = [GROCERIES]
        vault.complete_task.return_value = {
            "task_name": "Buy groceries",
            "tokens_earned": 5,
            "archive_path": "40-tasks/archive/buy-groceries.md",
        }
        with patch("src.api.routes.tasks.get_vault", return_value=vault), \
             patch("src.api.routes.tasks.get_calendar", return_value=None):
            resp = client.patch("/tasks/buy-groceries", json={"completed": True})
        assert resp.status_code == 200
        vault.complete_task.assert_called_once_with("40-tasks/active/buy-groceries.md")
        # Fuzzy name lookup should not have been needed
        vault.find_task_by_name.assert_not_called()

    def test_patch_falls_back_to_name(self, client):
        vault = MagicMock()
        vault.list_active_tasks.return_value = [GROCERIES]
        vault.find_task_by_name.return_value = GROCERIES
        vault.complete_task.return_value = {
            "task_name": "Buy groceries",
            "tokens_earned": 5,
            "archive_path": "40-tasks/archive/buy-groceries.md",
        }
        with patch("src.api.routes.tasks.get_vault", return_value=vault), \
             patch("src.api.routes.tasks.get_calendar", return_value=None):
            resp = client.patch("/tasks/Buy groceries", json={"completed": True})
        assert resp.status_code == 200
        vault.find_task_by_name.assert_called_once_with("Buy groceries")
