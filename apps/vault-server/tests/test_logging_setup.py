"""Tests for trace_id/span_id injection in structured log records."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


def _reset_otel():
    """Reset the global tracer provider between tests."""
    trace._TRACER_PROVIDER_SET_ONCE._done = False  # type: ignore[attr-defined]
    trace._TRACER_PROVIDER = None  # type: ignore[attr-defined]


def _reset_root_logger():
    """Remove all handlers from the root logger."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)


@pytest.fixture(autouse=True)
def isolate_logging_and_otel():
    """Reset root logger handlers and OTel provider before/after each test."""
    _reset_root_logger()
    _reset_otel()
    yield
    _reset_root_logger()
    _reset_otel()


def _read_last_log_line(logs_dir: Path) -> dict:
    """Read and parse the last JSON line from the vault-server log file."""
    log_file = logs_dir / "vault-server.jsonl"
    lines = [line.strip() for line in log_file.read_text().splitlines() if line.strip()]
    return json.loads(lines[-1])


def test_log_record_has_null_trace_id_outside_span(tmp_path: Path):
    """trace_id and span_id are null when no OTel span is active."""
    from src.logging_setup import configure_logging

    configure_logging("INFO", tmp_path)
    logging.getLogger("test").info("outside span")

    record = _read_last_log_line(tmp_path)
    assert record.get("trace_id") is None
    assert record.get("span_id") is None


def test_log_record_has_trace_id_inside_span(tmp_path: Path):
    """trace_id and span_id are hex strings when an OTel span is active."""
    from src.logging_setup import configure_logging

    # Set up an in-memory tracer provider so we can open a real span.
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    configure_logging("INFO", tmp_path)

    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("test_span"):
        logging.getLogger("test").info("inside span")

    record = _read_last_log_line(tmp_path)
    trace_id = record.get("trace_id")
    span_id = record.get("span_id")

    assert trace_id is not None, "trace_id should not be null inside a span"
    assert span_id is not None, "span_id should not be null inside a span"
    assert len(trace_id) == 32, f"trace_id should be 32 hex chars, got {len(trace_id)}: {trace_id!r}"
    assert len(span_id) == 16, f"span_id should be 16 hex chars, got {len(span_id)}: {span_id!r}"
    assert all(c in "0123456789abcdef" for c in trace_id), f"trace_id not hex: {trace_id!r}"
    assert all(c in "0123456789abcdef" for c in span_id), f"span_id not hex: {span_id!r}"


def test_log_record_service_field_preserved(tmp_path: Path):
    """Regression: _ServiceFilter still sets service='vault-server' alongside the new trace filter."""
    from src.logging_setup import configure_logging

    configure_logging("INFO", tmp_path)
    logging.getLogger("test").info("service check")

    record = _read_last_log_line(tmp_path)
    assert record.get("service") == "vault-server"
