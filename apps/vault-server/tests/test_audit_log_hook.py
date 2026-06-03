"""Tests for the audit_log post-hook."""

import json
from pathlib import Path

from src.services.hooks.audit_log import audit_log, _format_row


def test_format_row_minimal_success():
    row = _format_row(
        tool_name="create_task",
        params={"name": "X", "priority": 3},
        output={"ok": True, "data": {"path": "40-tasks/active/x.md"}, "_items": ["40-tasks/active/x.md"]},
        trace_id="abc123",
    )
    assert row["tool"] == "create_task"
    assert row["ok"] is True
    assert row["items"] == ["40-tasks/active/x.md"]
    assert row["params_summary"]["name"] == "X"
    assert row["trace_id"] == "abc123"
    assert "ts" in row


def test_format_row_error():
    row = _format_row(
        tool_name="delete_task",
        params={"task_name": "X"},
        output={"ok": False, "error": {"code": "PATH_NOT_FOUND", "message": "no match", "details": {}}, "_items": []},
        trace_id=None,
    )
    assert row["ok"] is False
    assert row["error_code"] == "PATH_NOT_FOUND"
    assert row["trace_id"] is None


def test_audit_log_writes_jsonl_row(tmp_path, monkeypatch):
    log_file = tmp_path / "tool-calls.jsonl"
    monkeypatch.setenv("MAZKIR_AUDIT_LOG_PATH", str(log_file))

    audit_log(
        params={"name": "X"},
        output={"ok": True, "data": {}, "_items": []},
        ctx={"tool": {"schema": {"name": "create_task"}}, "vault": None},
    )

    lines = log_file.read_text().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["tool"] == "create_task"
    assert row["ok"] is True


def test_audit_log_redacts_long_string_params(tmp_path, monkeypatch):
    log_file = tmp_path / "tool-calls.jsonl"
    monkeypatch.setenv("MAZKIR_AUDIT_LOG_PATH", str(log_file))

    long_text = "x" * 1000
    audit_log(
        params={"name": "Y", "append_note": long_text},
        output={"ok": True, "data": {}, "_items": []},
        ctx={"tool": {"schema": {"name": "update_task"}}, "vault": None},
    )

    row = json.loads(log_file.read_text().splitlines()[0])
    summary_note = row["params_summary"]["append_note"]
    assert isinstance(summary_note, str)
    assert len(summary_note) <= 250  # truncated to 200 + ellipsis suffix
