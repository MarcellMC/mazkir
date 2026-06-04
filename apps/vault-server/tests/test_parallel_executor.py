"""Tests for parallel tool batch execution."""

import time

import pytest

from src.services.parallel_executor import execute_calls_maybe_parallel


def _slow_call(name: str, duration_ms: int):
    """A fake tool registry entry that sleeps then returns ok."""
    def handler(params):
        time.sleep(duration_ms / 1000)
        return {"ok": True, "data": {"name": name}, "_items": []}
    return handler


def _tools_dict(call_specs):
    """Build a minimal registry from [(name, risk, duration_ms, safe_for_parallel)] tuples."""
    return {
        name: {
            "schema": {"name": name, "input_schema": {"type": "object", "properties": {}}},
            "handler": _slow_call(name, duration_ms),
            "risk": risk,
            "safe_for_parallel": sfp,
            "post_hooks": [],
            "pre_hooks": [],
            "confidence_threshold": None,
            "preview": False,
        }
        for name, risk, duration_ms, sfp in call_specs
    }


def test_parallel_dispatch_runs_calls_concurrently_when_all_safe():
    """3 calls × 100ms — serial ≈ 300ms, parallel ≈ 100ms."""
    tools = _tools_dict([
        ("c0", "safe", 100, True),
        ("c1", "safe", 100, True),
        ("c2", "safe", 100, True),
    ])
    calls = [{"name": f"c{i}", "params": {}, "risk": "safe"} for i in range(3)]
    t0 = time.perf_counter()
    results = execute_calls_maybe_parallel(calls, tools=tools, ctx={})
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert len(results) == 3
    assert all(r["ok"] for r in results)
    assert elapsed_ms < 250, f"Expected parallel (≤250ms), got {elapsed_ms:.0f}ms"


def test_serial_fallback_when_any_call_is_unsafe():
    tools = _tools_dict([
        ("c0", "safe", 100, True),
        ("c1", "write", 100, False),  # unsafe — forces serial
        ("c2", "safe", 100, True),
    ])
    calls = [
        {"name": "c0", "params": {}, "risk": "safe"},
        {"name": "c1", "params": {}, "risk": "write"},
        {"name": "c2", "params": {}, "risk": "safe"},
    ]
    t0 = time.perf_counter()
    results = execute_calls_maybe_parallel(calls, tools=tools, ctx={})
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert len(results) == 3
    # Serial ≈ 300ms
    assert elapsed_ms >= 250, f"Expected serial (≥250ms), got {elapsed_ms:.0f}ms"


def test_single_call_runs_directly():
    tools = _tools_dict([("only", "safe", 50, True)])
    calls = [{"name": "only", "params": {}, "risk": "safe"}]
    results = execute_calls_maybe_parallel(calls, tools=tools, ctx={})
    assert len(results) == 1
    assert results[0]["ok"]


def test_results_preserve_order():
    tools = _tools_dict([
        ("a", "safe", 50, True),
        ("b", "safe", 10, True),
        ("c", "safe", 30, True),
    ])
    calls = [
        {"name": "a", "params": {}, "risk": "safe"},
        {"name": "b", "params": {}, "risk": "safe"},
        {"name": "c", "params": {}, "risk": "safe"},
    ]
    results = execute_calls_maybe_parallel(calls, tools=tools, ctx={})
    names = [r["data"]["name"] for r in results]
    assert names == ["a", "b", "c"]
