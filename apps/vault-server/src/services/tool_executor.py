"""Per-tool-call execution: pre-hooks → handler → post-hooks → status
propagation → application-level error override.

Decoupled from AgentService's loop and the registry's construction. Takes
the registry, the ctx dict, and the tool name; returns the normalized
response.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from src.services.hooks import run_pre_hooks, run_post_hooks
from src.services.tool_response import ok

logger = logging.getLogger(__name__)


def _sanitize_params(params: dict) -> dict:
    """Strip internal fields and truncate long strings for safe logging."""
    out: dict[str, Any] = {}
    for k, v in params.items():
        if k.startswith("_"):
            continue
        if isinstance(v, str) and len(v) > 200:
            out[k] = v[:200] + "…"
        else:
            out[k] = v
    return out


def _summarize_result(result: dict) -> dict:
    """Compact form of a tool result for the audit record."""
    summary: dict[str, Any] = {}
    for k, v in result.items():
        if k == "_items":
            continue
        if isinstance(v, str) and len(v) > 200:
            summary[k] = v[:200] + "…"
        elif isinstance(v, list):
            summary[k] = f"<list len={len(v)}>"
        else:
            summary[k] = v
    return summary


def execute_tool(
    *,
    name: str,
    params: dict,
    risk: str,
    tools: dict,
    ctx: dict | None = None,
) -> dict:
    """Run a tool by name. Returns the normalized response.

    `ctx` may include {"vault": ..., "memory": ...}; the executor sets
    ctx["tool"] = <registry entry> before passing into hooks.

    Runs pre-hooks before the handler. If any pre-hook returns a blocking
    response, the handler is skipped and the error is returned immediately.
    Always emits one structured log line per call with timing + status.
    """
    sanitized = _sanitize_params(params)
    start = time.monotonic()

    if name not in tools:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.warning(
            "tool_call",
            extra={
                "event_type": "tool_call",
                "tool": name,
                "risk": risk,
                "params": sanitized,
                "status": "error",
                "error": "unknown_tool",
                "duration_ms": duration_ms,
            },
        )
        return {"error": f"Unknown tool: {name}"}

    tool = tools[name]
    full_ctx = {**(ctx or {}), "tool": tool}

    # Pre-hooks: run before handler; first blocking response short-circuits
    pre_hooks = tool.get("pre_hooks", [])
    blocked = run_pre_hooks(pre_hooks, params, full_ctx)
    if blocked is not None:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "tool_call",
            extra={
                "event_type": "tool_call",
                "tool": name,
                "risk": risk,
                "params": sanitized,
                "status": "blocked",
                "duration_ms": duration_ms,
                "result_summary": _summarize_result(blocked),
            },
        )
        return blocked

    try:
        handler = tool["handler"]
        raw = handler(params)
    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.error(
            "tool_call",
            exc_info=True,
            extra={
                "event_type": "tool_call",
                "tool": name,
                "risk": risk,
                "params": sanitized,
                "status": "error",
                "error": str(e),
                "duration_ms": duration_ms,
            },
        )
        return {"error": str(e)}

    # Backwards-compat: legacy handlers may return plain dicts. Wrap them.
    if isinstance(raw, dict) and "ok" in raw and ("data" in raw or "error" in raw):
        result = raw  # already normalized
    else:
        # Legacy success shape: extract _items if present, treat rest as data
        items = raw.pop("_items", []) if isinstance(raw, dict) else []
        result = ok(raw if isinstance(raw, dict) else {"value": raw}, items=items)

    # Post-hooks: run after a successful handler, receiving (params, output, ctx)
    post_hooks = tool.get("post_hooks", [])
    if post_hooks:
        run_post_hooks(post_hooks, params, result, full_ctx)

    duration_ms = int((time.monotonic() - start) * 1000)
    status = "error" if isinstance(result, dict) and result.get("ok") is False else "ok"
    logger.info(
        "tool_call",
        extra={
            "event_type": "tool_call",
            "tool": name,
            "risk": risk,
            "params": sanitized,
            "status": status,
            "duration_ms": duration_ms,
            "result_summary": _summarize_result(result) if isinstance(result, dict) else {"value": str(result)[:200]},
        },
    )
    return result
