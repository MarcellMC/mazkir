"""Parallel tool dispatch must propagate the OTel context into worker threads.

Regression tests for the span-drop bug: tool calls executed via the parallel
path ran in fresh threads with an empty OTel context, so their
`agent.tool_call` spans became roots of separate traces (invisible in
Phoenix next to the agent loop) and audit-log rows lost their trace_id.
"""

from __future__ import annotations

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from src.services.agent_service import AgentService
from src.services.parallel_executor import execute_calls_maybe_parallel
from src.services.tracing_helpers import current_trace_id


@pytest.fixture
def otel(monkeypatch):
    """An isolated (provider, exporter) pair, not the global provider.

    The module-level ProxyTracer in agent_service binds to whichever real
    provider was set first in the process, so tests pin `_tracer` to this
    provider explicitly instead of mutating global state.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(
        "src.services.agent_service._tracer", provider.get_tracer("mazkir.agent")
    )
    return provider, exporter


def _fake_tool(name: str, handler):
    return {
        "schema": {"name": name, "input_schema": {"type": "object", "properties": {}}},
        "handler": handler,
        "risk": "write",
        "safe_for_parallel": True,
        "pre_hooks": [],
        "post_hooks": [],
        "confidence_threshold": 0.85,
        "preview": False,
    }


def test_parallel_executor_handlers_see_callers_trace(otel):
    provider, _ = otel
    captured: list[str | None] = []

    def handler(params):
        captured.append(current_trace_id())
        return {"ok": True, "data": {}, "_items": []}

    tools = {
        "a": _fake_tool("a", handler),
        "b": _fake_tool("b", handler),
    }
    calls = [
        {"name": "a", "params": {}, "risk": "write"},
        {"name": "b", "params": {}, "risk": "write"},
    ]

    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("parent") as parent:
        parent_trace_id = format(parent.get_span_context().trace_id, "032x")
        results = execute_calls_maybe_parallel(calls, tools=tools, ctx={})

    assert all(r["ok"] for r in results)
    assert captured == [parent_trace_id, parent_trace_id]


def test_execute_tool_batch_parallel_spans_parent_to_caller(otel, mock_services):
    provider, exporter = otel
    agent = AgentService(**mock_services)

    def handler(params):
        return {"ok": True, "data": {}, "_items": []}

    agent.tools["fake_a"] = _fake_tool("fake_a", handler)
    agent.tools["fake_b"] = _fake_tool("fake_b", handler)

    calls = [
        {"name": "fake_a", "id": "t1", "input": {}},
        {"name": "fake_b", "id": "t2", "input": {}},
    ]
    gate_info = {"t1": (0.9, "test"), "t2": (0.9, "test")}

    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("parent") as parent:
        parent_ctx = parent.get_span_context()
        results = agent._execute_tool_batch(calls, gate_info)

    assert len(results) == 2
    assert all(r[3]["ok"] for r in results)

    tool_spans = [s for s in exporter.get_finished_spans() if s.name == "agent.tool_call"]
    assert len(tool_spans) == 2
    for span in tool_spans:
        assert span.context.trace_id == parent_ctx.trace_id, (
            "agent.tool_call span landed in a different trace than the caller"
        )
        assert span.parent is not None
        assert span.parent.span_id == parent_ctx.span_id
