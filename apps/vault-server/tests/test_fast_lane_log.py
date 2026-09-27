import json

from src.config import Settings
from src.logging_setup import configure_fast_lane_log, emit_fast_lane


def test_fast_lane_is_off_unless_asked(monkeypatch):
    for name in ("FAST_LANE_MODE", "FAST_LANE_DAY_BOUNDARY_HOUR",
                 "FAST_PARSE_MODEL", "FAST_PARSE_TIMEOUT_S"):
        monkeypatch.delenv(name, raising=False)
    s = Settings(_env_file=None)
    assert s.fast_lane_mode == "off"
    assert s.fast_lane_day_boundary_hour == 5
    assert s.fast_parse_model == "claude-haiku-4-5-20251001"
    assert s.fast_parse_timeout_s == 5.0


def test_fast_lane_mode_reads_the_environment(monkeypatch):
    monkeypatch.setenv("FAST_LANE_MODE", "shadow")
    assert Settings(_env_file=None).fast_lane_mode == "shadow"


def test_emit_fast_lane_writes_one_json_line(tmp_path):
    configure_fast_lane_log(tmp_path)
    emit_fast_lane({"event": "fast_shadow", "clauses": [{"op": "log_block"}]})
    lines = (tmp_path / "fast-lane-shadow.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["event"] == "fast_shadow"
    assert record["clauses"] == [{"op": "log_block"}]
    assert "ts" in record
