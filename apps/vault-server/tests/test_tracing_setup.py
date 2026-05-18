"""Tests for tracing_setup."""
from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)


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
