"""Tests for /goals routes — slug detail endpoint."""
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
    return {"path": path, "metadata": metadata, "content": f"# {name}\n\n## Milestones\n"}


LAUNCH = _goal(
    "30-goals/2026/launch-mazkir-personal-assistant-to-production.md",
    "Launch Mazkir personal assistant to production",
    progress=40,
    category="engineering",
)
SPANISH = _goal("30-goals/2026/learn-spanish.md", "Learn Spanish")
SPANISH_LIT = _goal("30-goals/2026/learn-spanish-literature.md", "Learn Spanish literature")


class TestFindGoalBySlug:
    def test_exact_stem_match(self):
        vault = MagicMock()
        vault.list_active_goals.return_value = [LAUNCH, SPANISH]
        goal = find_goal_by_slug(vault, "learn-spanish")
        assert goal is SPANISH

    def test_truncated_prefix_match(self):
        vault = MagicMock()
        vault.list_active_goals.return_value = [LAUNCH, SPANISH]
        # 54-byte truncation as produced by the Telegram inline keyboard
        goal = find_goal_by_slug(vault, "launch-mazkir-personal-assistant-to-produc")
        assert goal is LAUNCH

    def test_exact_match_wins_over_prefix(self):
        vault = MagicMock()
        vault.list_active_goals.return_value = [SPANISH_LIT, SPANISH]
        goal = find_goal_by_slug(vault, "learn-spanish")
        assert goal is SPANISH

    def test_ambiguous_prefix_returns_none(self):
        vault = MagicMock()
        vault.list_active_goals.return_value = [SPANISH, SPANISH_LIT]
        assert find_goal_by_slug(vault, "learn-spanis") is None

    def test_no_match_returns_none(self):
        vault = MagicMock()
        vault.list_active_goals.return_value = [SPANISH]
        assert find_goal_by_slug(vault, "nonexistent") is None


@pytest.fixture
def client():
    from src.main import app  # lazy: see find_goal_by_slug note above
    return TestClient(app)


class TestGetGoalDetail:
    def test_returns_full_detail(self, client):
        vault = MagicMock()
        vault.list_active_goals.return_value = [LAUNCH]
        with patch("src.api.routes.goals.get_vault", return_value=vault):
            resp = client.get("/goals/launch-mazkir-personal-assistant-to-production")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"].startswith("Launch Mazkir")
        assert body["slug"] == "launch-mazkir-personal-assistant-to-production"
        assert body["progress"] == 40
        assert body["category"] == "engineering"
        assert body["path"] == LAUNCH["path"]
        assert "## Milestones" in body["content"]

    def test_unknown_slug_404(self, client):
        vault = MagicMock()
        vault.list_active_goals.return_value = []
        with patch("src.api.routes.goals.get_vault", return_value=vault):
            resp = client.get("/goals/nonexistent")
        assert resp.status_code == 404
