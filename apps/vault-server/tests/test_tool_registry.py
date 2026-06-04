"""Tests for the extracted tool registry stamping."""

import pytest

from src.services.tool_registry import build_tool_registry, _RISK_DEFAULT_THRESHOLDS


def _h():
    return lambda p: {"ok": True}


def _schema(name):
    return {"name": name, "input_schema": {"type": "object", "properties": {}}}


def test_registry_returns_dict_of_tools():
    handlers = {
        "list_tasks": (_h(), "safe"),
        "create_task": (_h(), "write"),
        "delete_task": (_h(), "destructive"),
    }
    schemas = {n: _schema(n) for n in handlers}
    tools = build_tool_registry(handlers, schemas)
    assert "list_tasks" in tools
    assert tools["list_tasks"]["risk"] == "safe"
    assert tools["create_task"]["risk"] == "write"


def test_threshold_stamp_uses_risk_defaults():
    handlers = {
        "list_tasks": (_h(), "safe"),
        "create_task": (_h(), "write"),
        "delete_task": (_h(), "destructive"),
    }
    schemas = {n: _schema(n) for n in handlers}
    tools = build_tool_registry(handlers, schemas)
    assert tools["list_tasks"]["confidence_threshold"] is None
    assert tools["create_task"]["confidence_threshold"] == 0.85
    assert tools["delete_task"]["confidence_threshold"] == 0.95


def test_audit_log_attached_to_write_and_destructive_only():
    handlers = {
        "list_tasks": (_h(), "safe"),
        "create_task": (_h(), "write"),
        "delete_task": (_h(), "destructive"),
    }
    schemas = {n: _schema(n) for n in handlers}
    tools = build_tool_registry(handlers, schemas)
    assert "audit_log" not in tools["list_tasks"]["post_hooks"]
    assert "audit_log" in tools["create_task"]["post_hooks"]
    assert "audit_log" in tools["delete_task"]["post_hooks"]


def test_pre_hooks_default_to_validate_schema_for_write_destructive():
    handlers = {
        "list_tasks": (_h(), "safe"),
        "create_task": (_h(), "write"),
    }
    schemas = {n: _schema(n) for n in handlers}
    tools = build_tool_registry(handlers, schemas)
    assert tools["list_tasks"]["pre_hooks"] == []
    assert "validate_schema" in tools["create_task"]["pre_hooks"]


def test_destructive_tools_get_preview_flag():
    handlers = {
        "delete_task": (_h(), "destructive"),
        "create_task": (_h(), "write"),
    }
    schemas = {n: _schema(n) for n in handlers}
    tools = build_tool_registry(handlers, schemas)
    assert tools["delete_task"]["preview"] is True
    assert tools["create_task"].get("preview", False) is False
