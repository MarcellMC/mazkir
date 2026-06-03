"""Tests for the pre/post hook framework."""

import pytest

from src.services.hooks import (
    HOOK_REGISTRY,
    register_hook,
    run_pre_hooks,
    run_post_hooks,
)
from src.services.tool_response import ok, err, ErrorCode
from src.services.hooks.validate_schema import validate_schema


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


def test_validate_schema_passes_valid_input():
    ctx = {
        "tool": {
            "schema": {
                "input_schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                    "additionalProperties": False,
                }
            }
        }
    }
    assert validate_schema({"name": "x"}, ctx) is None


def test_validate_schema_rejects_missing_required():
    ctx = {
        "tool": {
            "schema": {
                "input_schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                }
            }
        }
    }
    result = validate_schema({}, ctx)
    assert result is not None
    assert result["ok"] is False
    assert result["error"]["code"] == "SCHEMA_INVALID"
    assert "name" in result["error"]["message"]


def test_validate_schema_rejects_additional_props():
    """The Migdal failure mode: passing extra fields not in schema."""
    ctx = {
        "tool": {
            "schema": {
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "additionalProperties": False,
                }
            }
        }
    }
    result = validate_schema({"path": "x", "extra": "y"}, ctx)
    assert result is not None
    assert result["error"]["code"] == "SCHEMA_INVALID"


def test_validate_schema_rejects_wrong_type():
    """The 'JSON-string for updates' failure mode."""
    ctx = {
        "tool": {
            "schema": {
                "input_schema": {
                    "type": "object",
                    "properties": {"updates": {"type": "object"}},
                    "required": ["updates"],
                }
            }
        }
    }
    result = validate_schema({"updates": '{"key": "value"}'}, ctx)
    assert result is not None
    assert result["error"]["code"] == "SCHEMA_INVALID"


def test_execute_tool_runs_post_hooks_after_handler():
    """Post-hooks run after a successful handler, receiving (params, output, ctx)."""
    from src.services.agent_service import AgentService
    from src.services.hooks import register_hook, HOOK_REGISTRY
    from unittest.mock import MagicMock

    HOOK_REGISTRY.clear()
    calls = []
    register_hook("audit", lambda p, o, c: calls.append(("audit", p, o)))

    claude, vault, memory = MagicMock(), MagicMock(), MagicMock()
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=None, events=None)
    agent.tools["list_tasks"]["post_hooks"] = ["audit"]
    agent.tools["list_tasks"]["handler"] = lambda p: {"ok": True, "data": {"tasks": []}, "_items": []}
    agent.tools["list_tasks"]["pre_hooks"] = []

    result = agent._execute_tool_inner("list_tasks", {}, risk="safe")
    assert result["ok"] is True
    assert len(calls) == 1
    assert calls[0][0] == "audit"
    assert calls[0][2]["data"]["tasks"] == []
