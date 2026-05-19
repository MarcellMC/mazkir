"""OpenTelemetry tracing setup for vault-server.

Initializes a TracerProvider that exports OTLP/HTTP spans to the configured
endpoint. When the endpoint is empty, installs no tracer at all (no-op).
Also wires up OpenInference's Anthropic instrumentor and FastAPI's
auto-instrumentation so we capture LLM generations and HTTP spans without
manual annotation at the call sites.
"""
from __future__ import annotations

import logging

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger(__name__)


def configure_tracing(endpoint: str, service_name: str) -> TracerProvider | None:
    """Set up the global tracer provider. Returns None if endpoint is empty."""
    if not endpoint:
        logger.info("tracing_disabled", extra={"reason": "empty_endpoint"})
        return None

    resource = Resource.create(
        {
            "service.name": service_name,
            "openinference.project.name": "mazkir",
        }
    )
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    _install_anthropic_instrumentor()

    logger.info(
        "tracing_enabled",
        extra={"endpoint": endpoint, "service_name": service_name},
    )
    return provider


def instrument_fastapi(app) -> None:
    """Attach FastAPI auto-instrumentation. Safe to call when tracing is off."""
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("fastapi_instrumentation_failed", extra={"error": str(exc)})


def _install_anthropic_instrumentor() -> None:
    try:
        from openinference.instrumentation.anthropic import AnthropicInstrumentor

        AnthropicInstrumentor().instrument()
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "anthropic_instrumentation_failed", extra={"error": str(exc)}
        )


def get_tracer():
    """Return the project's tracer. Always safe to call."""
    return trace.get_tracer("mazkir.agent")
