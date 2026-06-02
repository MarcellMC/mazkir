"""Tests for the pre/post hook framework."""

import pytest

from src.services.hooks import (
    HOOK_REGISTRY,
    register_hook,
    run_pre_hooks,
    run_post_hooks,
)
from src.services.tool_response import ok, err, ErrorCode


@pytest.fixture(autouse=True)
def clean_registry():
    """Reset registry between tests."""
    saved = HOOK_REGISTRY.copy()
    HOOK_REGISTRY.clear()
    yield
    HOOK_REGISTRY.clear()
    HOOK_REGISTRY.update(saved)


def test_register_hook():
    def my_hook(params, ctx):
        return None
    register_hook("my", my_hook)
    assert HOOK_REGISTRY["my"] is my_hook


def test_pre_hooks_pass_through_when_none_blocks():
    register_hook("a", lambda p, c: None)
    register_hook("b", lambda p, c: None)
    result = run_pre_hooks(["a", "b"], {"x": 1}, ctx=None)
    assert result is None


def test_pre_hook_blocks_returns_error_response():
    register_hook(
        "blocker",
        lambda p, c: err(ErrorCode.SCHEMA_INVALID, "nope"),
    )
    result = run_pre_hooks(["blocker"], {"x": 1}, ctx=None)
    assert result is not None
    assert result["ok"] is False
    assert result["error"]["code"] == "SCHEMA_INVALID"


def test_pre_hook_chain_stops_at_first_blocker():
    calls = []
    register_hook("a", lambda p, c: calls.append("a") or None)
    register_hook(
        "b",
        lambda p, c: calls.append("b") or err(ErrorCode.PATH_NOT_FOUND, "halt"),
    )
    register_hook("c", lambda p, c: calls.append("c") or None)
    run_pre_hooks(["a", "b", "c"], {}, ctx=None)
    assert calls == ["a", "b"]


def test_post_hooks_run_after_handler():
    calls = []
    register_hook("post1", lambda p, o, c: calls.append(("post1", o)))
    register_hook("post2", lambda p, o, c: calls.append(("post2", o)))
    run_post_hooks(["post1", "post2"], params={}, output={"x": 1}, ctx=None)
    assert calls == [("post1", {"x": 1}), ("post2", {"x": 1})]


def test_run_pre_hooks_unknown_name_raises():
    with pytest.raises(KeyError):
        run_pre_hooks(["missing"], {}, ctx=None)
