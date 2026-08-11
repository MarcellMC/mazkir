"""Tests for /goals routes — slug detail endpoint backing the inline keyboard."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def find_goal_by_slug(vault, slug):
    # Lazy import: importing src.main at module level would initialize tracing
    # during pytest collection and leak a global TracerProvider into other tests.
    import src.main  # noqa: F401 — break circular import (main imports route modules)
    from src.api.routes.goals import find_goal_by_slug as fn
    return fn(vault, slug)


def _goal(path: str, name: str, **meta) -> dict:
    metadata = {
        "name": name,
        "status": "in-progress",
        "priority": "medium",
        "progress": 0,
        **meta,
    }
    return {"path": path, "metadata": metadata, "content": f"# {name}\n\n## Why\nBecause.\n"}


LONG_GOAL = _goal(
    "30-goals/2026/ship-the-personal-assistant-with-habits-goals-and-knowl.md",
    "Ship the personal assistant with habits, goals and knowledge recall",
    priority="high",
    progress=30,
    category="product",
    milestones=["Ship habits", "Ship goals"],
)
FIT = _goal("30-goals/2026/get-fit.md", "Get fit", progress=40)
FIT_FASTER = _goal("30-goals/2026/get-fit-faster.md", "Get fit faster")


class TestFindGoalBySlug:
    def test_exact_stem_match(self):
        vault = MagicMock()
        vault.list_active_goals.return_value = [LONG_GOAL, FIT]
        assert find_goal_by_slug(vault, "get-fit") is FIT

    def test_truncated_prefix_match(self):
        vault = MagicMock()
        vault.list_active_goals.return_value = [LONG_GOAL, FIT]
        # 54-byte truncation as produced by the Telegram inline keyboard
        goal = find_goal_by_slug(vault, "ship-the-personal-assistant-with-habits-goals-and-knowl"[:54])
        assert goal is LONG_GOAL

    def test_exact_match_wins_over_prefix(self):
        vault = MagicMock()
        vault.list_active_goals.return_value = [FIT_FASTER, FIT]
        assert find_goal_by_slug(vault, "get-fit") is FIT

    def test_ambiguous_prefix_returns_none(self):
        vault = MagicMock()
        vault.list_active_goals.return_value = [FIT, FIT_FASTER]
        assert find_goal_by_slug(vault, "get-fi") is None

    def test_no_match_returns_none(self):
        vault = MagicMock()
        vault.list_active_goals.return_value = [FIT]
        assert find_goal_by_slug(vault, "nonexistent") is None


@pytest.fixture
def client():
    from src.main import app  # lazy: see find_goal_by_slug note above
    return TestClient(app)


class TestGetGoalDetail:
    def test_returns_full_detail(self, client):
        vault = MagicMock()
        vault.list_active_goals.return_value = [LONG_GOAL]
        with patch("src.api.routes.goals.get_vault", return_value=vault):
            resp = client.get("/goals/ship-the-personal-assistant-with-habits-goals-and-knowl")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"].startswith("Ship the personal assistant")
        assert body["slug"] == "ship-the-personal-assistant-with-habits-goals-and-knowl"
        assert body["priority"] == "high"
        assert body["progress"] == 30
        assert body["category"] == "product"
        assert body["milestones"] == ["Ship habits", "Ship goals"]
        assert body["path"] == LONG_GOAL["path"]
        assert "Because." in body["content"]

    def test_unknown_slug_404(self, client):
        vault = MagicMock()
        vault.list_active_goals.return_value = []
        with patch("src.api.routes.goals.get_vault", return_value=vault):
            resp = client.get("/goals/nonexistent")
        assert resp.status_code == 404


class TestListGoalsStillWorks:
    def test_list_returns_path_for_keyboard_slugs(self, client):
        vault = MagicMock()
        vault.list_active_goals.return_value = [FIT]
        with patch("src.api.routes.goals.get_vault", return_value=vault):
            resp = client.get("/goals")
        assert resp.status_code == 200
        assert resp.json()[0]["path"] == "30-goals/2026/get-fit.md"
