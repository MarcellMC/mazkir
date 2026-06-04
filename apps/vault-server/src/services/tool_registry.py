"""Builds the tool registry dict from handlers + schemas, applying risk-class
defaults, pre/post hook stamps, and the destructive-preview flag.

The 27-entry tool registration itself stays in AgentService (it references
self._tool_* handlers). This module owns only the stamping logic.
"""

from __future__ import annotations

from typing import Callable

_RISK_DEFAULT_THRESHOLDS: dict[str, float | None] = {
    "safe": None,
    "write": 0.85,
    "destructive": 0.95,
}


def build_tool_registry(
    handlers: dict[str, tuple[Callable, str]],
    schemas: dict[str, dict],
) -> dict[str, dict]:
    """Build a tool registry dict from handlers + schemas.

    handlers: {name: (handler_callable, risk)}
    schemas:  {name: schema_dict}

    Each output entry has: schema, handler, risk, confidence_threshold,
    pre_hooks, post_hooks, preview.
    """
    tools: dict[str, dict] = {}
    for name, (handler, risk) in handlers.items():
        entry = {
            "schema": schemas[name],
            "handler": handler,
            "risk": risk,
            "confidence_threshold": _RISK_DEFAULT_THRESHOLDS.get(risk),
            "pre_hooks": [],
            "post_hooks": [],
            "preview": risk == "destructive",
            "safe_for_parallel": risk == "safe",
        }
        if risk in ("write", "destructive"):
            entry["pre_hooks"].append("validate_schema")
            entry["post_hooks"].append("audit_log")
        tools[name] = entry
    return tools


def stamp_tool_registry(tools: dict[str, dict]) -> dict[str, dict]:
    """Apply risk-class defaults, pre/post hook stamps, and preview flag
    to an existing registry dict (in-place AND returns it).

    Intended for callers that build the registry inline and want to apply
    the standard stamping without restructuring.
    """
    for entry in tools.values():
        risk = entry["risk"]
        entry.setdefault("confidence_threshold", _RISK_DEFAULT_THRESHOLDS.get(risk))
        entry.setdefault("pre_hooks", [])
        entry.setdefault("post_hooks", [])
        entry.setdefault("preview", risk == "destructive")
        entry.setdefault("safe_for_parallel", risk == "safe")
        if risk in ("write", "destructive"):
            if "validate_schema" not in entry["pre_hooks"]:
                entry["pre_hooks"].append("validate_schema")
            if "audit_log" not in entry["post_hooks"]:
                entry["post_hooks"].append("audit_log")
    return tools
