import dataclasses
import datetime as dt
import json
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import src.services.fast_lane.shadow as shadow_module
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


def reply(payload, stop_reason="end_turn"):
    """The shape of an Anthropic Messages response, as far as the parse reads it."""
    return SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(text=json.dumps(payload))])


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


# --- Final fixes F13, F5, F6 ---


def test_more_than_twelve_clauses_is_a_router_fallback(tmp_path):
    configure_fast_lane_log(tmp_path)
    claude = MagicMock()
    item = {"op": "log_block", "intent": "record", "stated": True, "evidence": "Dog walk", "name": "Dog walk"}
    claude.create_fast_parse.return_value = reply({"clauses": [item] * 13, "fallthrough_skill": "mazkir"})
    ctx = FastContext(now=dt.datetime(2026, 9, 8, 0, 50, tzinfo=TZ), chat_id=7, text="Dog walk")
    record = run_shadow(ctx, claude, SETTINGS)
    assert record["route"] == "router_fallback"
    assert "fallthrough_skill" not in record


def test_the_record_carries_the_trace_id(tmp_path, monkeypatch):
    configure_fast_lane_log(tmp_path)
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(shadow_module, "_tracer", provider.get_tracer("test"))
    result = ParseResult((Clause("other", "record", True, "hello"),), "mazkir")
    ctx = FastContext(now=dt.datetime(2026, 9, 8, 0, 50, tzinfo=TZ), chat_id=7, text="hello")
    record = run_shadow(ctx, None, SETTINGS, parse=fixed(result))
    [span] = [s for s in exporter.get_finished_spans() if s.name == "fast.shadow"]
    assert record["trace_id"] == format(span.context.trace_id, "032x")
    assert read_log(tmp_path)[0]["trace_id"] == record["trace_id"]


def test_the_trace_id_is_empty_without_a_span(tmp_path, monkeypatch):
    configure_fast_lane_log(tmp_path)
    monkeypatch.setattr(shadow_module, "_tracer", trace.NoOpTracer())
    ctx = FastContext(now=dt.datetime(2026, 9, 8, 0, 50, tzinfo=TZ), chat_id=7, text="hello")
    record = run_shadow(ctx, None, SETTINGS, parse=fixed(ParseResult((), None)))
    assert record["trace_id"] == ""


def test_the_context_is_completed_in_the_thread_before_the_parse(tmp_path):
    configure_fast_lane_log(tmp_path)
    snapshot = FastContext(now=dt.datetime(2026, 9, 8, 12, 0, tzinfo=TZ), chat_id=7, text="Dog walk ended now")
    seen = {}

    def complete(ctx):
        return dataclasses.replace(ctx, typical_minutes={"dog walk": 40})

    def parse(ctx, claude, model, timeout_s):
        seen["typical"] = ctx.typical_minutes
        return ParseResult((Clause("log_block", "record", True, "Dog walk ended now", name="Dog walk",
                                   time=TimeWords(end="now")),), None)

    [clause] = run_shadow(snapshot, None, SETTINGS, parse=parse, complete=complete)["clauses"]
    assert seen["typical"] == {"dog walk": 40}
    assert clause["start"] == "2026-09-08T11:20:00+03:00"


def test_a_failing_completion_is_swallowed(tmp_path):
    configure_fast_lane_log(tmp_path)

    def complete(ctx):
        raise RuntimeError("disk")

    ctx = FastContext(now=dt.datetime(2026, 9, 8, 12, 0, tzinfo=TZ), chat_id=7, text="x")
    record = run_shadow(ctx, None, SETTINGS, parse=fixed(ParseResult((), None)), complete=complete)
    assert record["route"] == "error"
    assert read_log(tmp_path)[0]["route"] == "error"
