"""Tests for destructive-action preview rendering."""

import pytest
from unittest.mock import MagicMock

from src.services.preview import (
    PREVIEW_FUNCTIONS,
    register_preview_fn,
    render_preview,
)


@pytest.fixture(autouse=True)
def clean_registry():
    saved = PREVIEW_FUNCTIONS.copy()
    PREVIEW_FUNCTIONS.clear()
    yield
    PREVIEW_FUNCTIONS.clear()
    PREVIEW_FUNCTIONS.update(saved)


def test_register_and_render():
    register_preview_fn("delete_task", lambda params, ctx: f"Would delete: {params['task_name']}")
    out = render_preview("delete_task", {"task_name": "Walk dog"}, ctx={})
    assert out == "Would delete: Walk dog"


def test_render_returns_default_when_no_preview_fn_registered():
    out = render_preview("delete_task", {"task_name": "X"}, ctx={})
    assert "delete_task" in out
    assert "X" in out
