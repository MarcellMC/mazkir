"""Preview-text registry for destructive tool calls.

Each destructive tool may register a `preview_fn(params, ctx) -> str` that
produces a human-readable description of what would change. The confirmation
flow renders this text alongside yes/no buttons before executing.

Tools without a registered preview_fn get a generic fallback ("Would call
<tool> with <params>").
"""

from __future__ import annotations

import json
from typing import Any, Callable

PreviewFn = Callable[[dict, Any], str]

PREVIEW_FUNCTIONS: dict[str, PreviewFn] = {}


def register_preview_fn(tool_name: str, fn: PreviewFn) -> None:
    PREVIEW_FUNCTIONS[tool_name] = fn


def render_preview(tool_name: str, params: dict, ctx: Any) -> str:
    fn = PREVIEW_FUNCTIONS.get(tool_name)
    if fn is None:
        return f"Would call `{tool_name}` with params: {json.dumps(params, indent=2)}"
    return fn(params, ctx)
