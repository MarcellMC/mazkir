"""Tests for turn_trace — reading, rendering and joining per-turn tool traces."""

import json

import pytest

from src.services.turn_trace import read_turn_records


def _write_log(logs_dir, rows):
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / "agent-turns.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


class TestReadTurnRecords:
    def test_returns_empty_when_file_missing(self, tmp_path):
        assert read_turn_records(tmp_path / "nope", chat_id=1, date="2026-09-05") == []

    def test_filters_by_chat_and_date(self, tmp_path):
        _write_log(tmp_path, [
            {"ts": "2026-09-05T10:00:00+0300", "chat_id": 1, "user_text": "a"},
            {"ts": "2026-09-05T11:00:00+0300", "chat_id": 2, "user_text": "b"},
            {"ts": "2026-09-04T10:00:00+0300", "chat_id": 1, "user_text": "c"},
            {"ts": "2026-09-05T12:00:00+0300", "chat_id": 1, "user_text": "d"},
        ])

        got = read_turn_records(tmp_path, chat_id=1, date="2026-09-05")

        assert [r["user_text"] for r in got] == ["a", "d"]

    def test_preserves_file_order(self, tmp_path):
        _write_log(tmp_path, [
            {"ts": "2026-09-05T10:00:00+0300", "chat_id": 1, "user_text": str(i)}
            for i in range(5)
        ])

        got = read_turn_records(tmp_path, chat_id=1, date="2026-09-05")

        assert [r["user_text"] for r in got] == ["0", "1", "2", "3", "4"]

    def test_skips_torn_final_line(self, tmp_path):
        path = _write_log(tmp_path, [
            {"ts": "2026-09-05T10:00:00+0300", "chat_id": 1, "user_text": "good"},
        ])
        with path.open("a", encoding="utf-8") as fh:
            fh.write('{"ts": "2026-09-05T11:00:00+0300", "chat_id": 1, "user_te')

        got = read_turn_records(tmp_path, chat_id=1, date="2026-09-05")

        assert [r["user_text"] for r in got] == ["good"]

    def test_skips_blank_and_non_dict_rows(self, tmp_path):
        path = _write_log(tmp_path, [
            {"ts": "2026-09-05T10:00:00+0300", "chat_id": 1, "user_text": "good"},
        ])
        with path.open("a", encoding="utf-8") as fh:
            fh.write("\n[1, 2, 3]\n\n")

        got = read_turn_records(tmp_path, chat_id=1, date="2026-09-05")

        assert [r["user_text"] for r in got] == ["good"]

    def test_tolerates_record_without_ts_or_chat_id(self, tmp_path):
        _write_log(tmp_path, [
            {"user_text": "no ts"},
            {"ts": "2026-09-05T10:00:00+0300", "user_text": "no chat"},
            {"ts": "2026-09-05T11:00:00+0300", "chat_id": 1, "user_text": "good"},
        ])

        got = read_turn_records(tmp_path, chat_id=1, date="2026-09-05")

        assert [r["user_text"] for r in got] == ["good"]

    def test_returns_empty_when_path_is_directory(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "agent-turns.jsonl").mkdir()

        got = read_turn_records(tmp_path, chat_id=1, date="2026-09-05")

        assert got == []


def _call(name, params=None, ok=True, error_code=None, pending=False, no_result=False):
    if pending:
        summary = None
    elif no_result:
        summary = None
    elif ok:
        summary = {"ok": True, "data": {}}
    else:
        summary = {"ok": False, "error": {"code": error_code, "message": "boom"}}
    call = {"name": name, "params": params or {}, "result_summary": summary}
    if pending:
        call["pending"] = True
    return call


class TestRenderTrace:
    def test_no_calls_renders_none(self):
        from src.services.turn_trace import render_trace
        assert render_trace({"tools": []}) == "[Tools I called this turn: none]"

    def test_missing_tools_key_renders_none(self):
        from src.services.turn_trace import render_trace
        assert render_trace({}) == "[Tools I called this turn: none]"

    def test_skill_appears_in_header(self):
        from src.services.turn_trace import render_trace
        out = render_trace({"skill": "time-management", "tools": []})
        assert out == "[Tools I called this turn, as time-management: none]"

    def test_successful_call(self):
        from src.services.turn_trace import render_trace
        out = render_trace({"tools": [_call("daily_add_task", {"text": "Order dog food"})]})
        assert 'daily_add_task(text="Order dog food") → ok' in out

    def test_failed_call_shows_error_code(self):
        from src.services.turn_trace import render_trace
        out = render_trace({"tools": [
            _call("delete_task", {"name": "old"}, ok=False, error_code="SCHEMA_INVALID"),
        ]})
        assert "delete_task(name=\"old\") → SCHEMA_INVALID" in out

    def test_pending_call_is_marked_not_executed(self):
        from src.services.turn_trace import render_trace
        out = render_trace({"tools": [_call("delete_task", {"name": "old"}, pending=True)]})
        assert "→ proposed, awaiting confirmation — NOT executed" in out
        assert "→ ok" not in out

    def test_missing_result_summary(self):
        from src.services.turn_trace import render_trace
        out = render_trace({"tools": [_call("get_daily", no_result=True)]})
        assert "→ no result recorded" in out

    def test_multiple_calls_each_get_a_line(self):
        from src.services.turn_trace import render_trace
        out = render_trace({"tools": [
            _call("daily_add_task", {"text": "Order dog food"}),
            _call("daily_add_task", {"text": "Bring the bicycle to repair shop"}),
        ]})
        assert out.count("daily_add_task") == 2
        assert out.startswith("[Tools I called this turn:\n")
        assert out.endswith("]")

    def test_long_params_are_truncated(self):
        from src.services.turn_trace import render_trace
        body = "x" * 500
        out = render_trace({"tools": [_call("save_knowledge", {"content": body})]})
        assert "…" in out
        assert len(out) < 200
        assert body not in out

    def test_non_string_params_render_without_quotes(self):
        from src.services.turn_trace import render_trace
        out = render_trace({"tools": [_call("update_goal", {"progress": 40, "done": True})]})
        assert "progress=40" in out
        assert "done=True" in out

    def test_call_without_params(self):
        from src.services.turn_trace import render_trace
        out = render_trace({"tools": [_call("list_tasks")]})
        assert "list_tasks() → ok" in out
