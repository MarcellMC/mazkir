"""Tests for tracing_setup."""
from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)


@pytest.fixture(autouse=True)
def _restore_otel_provider():
    """Snapshot and restore the global tracer provider around each test.

    These tests deliberately swap the global provider; without restoration
    a leaked real provider pollutes later tests that rely on the default
    no-op ProxyTracerProvider.
    """
    saved_provider = trace._TRACER_PROVIDER  # type: ignore[attr-defined]
    saved_done = trace._TRACER_PROVIDER_SET_ONCE._done  # type: ignore[attr-defined]
    yield
    trace._TRACER_PROVIDER = saved_provider  # type: ignore[attr-defined]
    trace._TRACER_PROVIDER_SET_ONCE._done = saved_done  # type: ignore[attr-defined]


def _reset_otel():
    """Reset the global tracer provider between tests."""
    trace._TRACER_PROVIDER_SET_ONCE._done = False  # type: ignore[attr-defined]
    trace._TRACER_PROVIDER = None  # type: ignore[attr-defined]


def test_configure_tracing_noop_when_endpoint_empty():
    from src.tracing_setup import configure_tracing

    _reset_otel()
    provider = configure_tracing(endpoint="", service_name="vault-server")
    assert provider is None


def test_configure_tracing_returns_provider_when_endpoint_set():
    from src.tracing_setup import configure_tracing

    _reset_otel()
    provider = configure_tracing(
        endpoint="http://localhost:6006/v1/traces",
        service_name="vault-server",
    )
    assert isinstance(provider, TracerProvider)


def test_emitted_spans_are_captured_by_inmemory_exporter():
    from src import tracing_setup

    _reset_otel()
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("unit"):
        pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "unit"


def test_fs_span_emits_span_with_attributes():
    from src import tracing_setup

    _reset_otel()
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    with tracing_setup.fs_span("write", "10-daily/2026-05-20.md", "vault") as span:
        span.set_attribute("fs.bytes", 1843)

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "fs.write"
    assert spans[0].attributes["fs.operation"] == "write"
    assert spans[0].attributes["fs.path"] == "10-daily/2026-05-20.md"
    assert spans[0].attributes["fs.store"] == "vault"
    assert spans[0].attributes["fs.bytes"] == 1843
