import datetime as dt
import json
from zoneinfo import ZoneInfo

from src.logging_setup import configure_fast_lane_log
from src.services.fast_lane.context import BlockView, FastContext
from src.services.fast_lane.contract import Clause, ParseResult, TimeWords
from src.services.fast_lane.parse import ParseFailure
from src.services.fast_lane.shadow import ShadowSettings, run_shadow

TZ = ZoneInfo("Asia/Jerusalem")
SETTINGS = ShadowSettings(model="m", timeout_s=5)


def read_log(tmp_path):
    return [json.loads(line) for line in (tmp_path / "fast-lane-shadow.jsonl").read_text().splitlines()]


def fixed(result):
    return lambda ctx, claude, model, timeout_s: result


def test_a_logged_block_is_placed_and_logged(tmp_path):
    configure_fast_lane_log(tmp_path)
    result = ParseResult((Clause("log_block", "record", True, "Dog walk 23:15-23:35", name="Dog walk",
                                 time=TimeWords(start="23:15", end="23:35")),), None)
    ctx = FastContext(now=dt.datetime(2026, 9, 8, 0, 48, tzinfo=TZ), chat_id=7, text="Dog walk 23:15-23:35")
    record = run_shadow(ctx, None, SETTINGS, parse=fixed(result))
    assert record["route"] == "fast"
    [clause] = record["clauses"]
    assert clause["outcome"] == "fact"
    assert clause["start"] == "2026-09-07T23:15:00+03:00"
    assert read_log(tmp_path)[0]["chat_id"] == 7


def test_an_ending_finds_its_block_in_the_day(tmp_path):
    configure_fast_lane_log(tmp_path)
    walk = BlockView("e1", "2026-09-07", "Dog walk", dt.datetime(2026, 9, 7, 23, 15, tzinfo=TZ), None)
    result = ParseResult((Clause("end_block", "record", True, "Ended at 00:30", target="Dog walk",
                                 time=TimeWords(end="00:30")),), None)
    ctx = FastContext(now=dt.datetime(2026, 9, 8, 0, 50, tzinfo=TZ), chat_id=7, text="Ended at 00:30",
                      blocks=(walk,))
    [clause] = run_shadow(ctx, None, SETTINGS, parse=fixed(result))["clauses"]
    assert clause["end"] == "2026-09-08T00:30:00+03:00"


def test_a_failed_parse_is_logged_as_a_router_fallback(tmp_path):
    configure_fast_lane_log(tmp_path)

    def failing(ctx, claude, model, timeout_s):
        raise ParseFailure("timeout")

    ctx = FastContext(now=dt.datetime(2026, 9, 8, 0, 50, tzinfo=TZ), chat_id=7, text="x")
    record = run_shadow(ctx, None, SETTINGS, parse=failing)
    assert record["route"] == "router_fallback" and record["error"] == "timeout"


def test_anything_unexpected_is_logged_and_swallowed(tmp_path):
    configure_fast_lane_log(tmp_path)

    def broken(ctx, claude, model, timeout_s):
        raise KeyError("boom")

    ctx = FastContext(now=dt.datetime(2026, 9, 8, 0, 50, tzinfo=TZ), chat_id=7, text="x")
    record = run_shadow(ctx, None, SETTINGS, parse=broken)
    assert record["route"] == "error"
    assert read_log(tmp_path)[0]["route"] == "error"


def test_other_clauses_carry_no_outcome(tmp_path):
    configure_fast_lane_log(tmp_path)
    result = ParseResult((Clause("other", "record", True, "hello"),), "mazkir")
    ctx = FastContext(now=dt.datetime(2026, 9, 8, 0, 50, tzinfo=TZ), chat_id=7, text="hello")
    record = run_shadow(ctx, None, SETTINGS, parse=fixed(result))
    assert record["route"] == "fallthrough" and record["fallthrough_skill"] == "mazkir"
    assert "outcome" not in record["clauses"][0]


def test_a_failing_log_write_never_reaches_the_caller(tmp_path, monkeypatch):
    configure_fast_lane_log(tmp_path)

    def exploding_emit(record):
        raise RuntimeError("emit exploded")

    monkeypatch.setattr("src.services.fast_lane.shadow.emit_fast_lane", exploding_emit)
    result = ParseResult((Clause("other", "record", True, "hello"),), "mazkir")
    ctx = FastContext(now=dt.datetime(2026, 9, 8, 0, 50, tzinfo=TZ), chat_id=7, text="hello")
    record = run_shadow(ctx, None, SETTINGS, parse=fixed(result))
    assert record["route"] == "fallthrough" and record["fallthrough_skill"] == "mazkir"
