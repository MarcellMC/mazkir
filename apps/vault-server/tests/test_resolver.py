"""Tests for the unified item resolver."""

import pytest
from unittest.mock import MagicMock

from src.services.resolver import resolve_item, SCORE_AMBIGUOUS_DELTA


def _mk_item(path: str, name: str):
    return {"path": path, "metadata": {"name": name}}


@pytest.fixture
def vault():
    v = MagicMock()
    v.list_active_tasks.return_value = [
        _mk_item("40-tasks/active/migdal-insurance.md", "Submit missing documents to Migdal Insurance"),
        _mk_item("40-tasks/active/order-phone.md", "Order phone from AliExpress"),
        _mk_item("40-tasks/active/walk-dog.md", "Walk the dog"),
    ]
    v.list_active_habits.return_value = []
    v.list_active_goals.return_value = []
    return v


def test_exact_path_match(vault):
    r = resolve_item("task", "40-tasks/active/walk-dog.md", vault)
    assert r["ok"] is True
    assert r["data"]["path"] == "40-tasks/active/walk-dog.md"


def test_exact_name_match(vault):
    r = resolve_item("task", "Walk the dog", vault)
    assert r["ok"] is True
    assert r["data"]["path"] == "40-tasks/active/walk-dog.md"


def test_substring_match(vault):
    r = resolve_item("task", "migdal", vault)
    assert r["ok"] is True
    assert "migdal-insurance" in r["data"]["path"]


def test_fuzzy_match_typo(vault):
    r = resolve_item("task", "walke the dog", vault)
    assert r["ok"] is True
    assert "walk-dog" in r["data"]["path"]


def test_no_match_returns_path_not_found(vault):
    r = resolve_item("task", "completely unrelated", vault)
    assert r["ok"] is False
    assert r["error"]["code"] == "PATH_NOT_FOUND"


def test_ambiguous_returns_candidates():
    v = MagicMock()
    v.list_active_tasks.return_value = [
        _mk_item("40-tasks/active/migdal-insurance.md", "Migdal Insurance docs"),
        _mk_item("40-tasks/active/migdal-bank.md", "Migdal Bank statement"),
    ]
    r = resolve_item("task", "migdal", v)
    assert r["ok"] is False
    assert r["error"]["code"] == "AMBIGUOUS_MATCH"
    assert len(r["error"]["details"]["candidates"]) >= 2


def test_habit_resolution_uses_habit_list():
    v = MagicMock()
    v.list_active_habits.return_value = [
        _mk_item("20-habits/morning-workout.md", "Morning workout"),
    ]
    v.list_active_tasks.return_value = []
    r = resolve_item("habit", "workout", v)
    assert r["ok"] is True
    assert r["data"]["name"] == "Morning workout"


def test_goal_resolution_uses_goal_list():
    v = MagicMock()
    v.list_active_goals.return_value = [
        _mk_item("30-goals/2026/learn-ai.md", "Learn AI engineering"),
    ]
    v.list_active_tasks.return_value = []
    v.list_active_habits.return_value = []
    r = resolve_item("goal", "ai engineering", v)
    assert r["ok"] is True
