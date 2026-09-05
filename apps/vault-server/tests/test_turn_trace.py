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
