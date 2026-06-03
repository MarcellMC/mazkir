"""audit_log post-hook — writes one JSON line per tool call to a structured log.

Row shape:
    {
        "ts": "2026-06-03T10:00:00.123Z",
        "trace_id": "abc..." | null,
        "tool": "create_task",
        "ok": true,
        "error_code": "...",            # only when ok is false
        "params_summary": { ... },      # long strings truncated to 200 chars
        "items": ["..."],
    }

Path is `MAZKIR_AUDIT_LOG_PATH`, default `<repo>/data/logs/tool-calls.jsonl`.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.services.tracing_helpers import current_trace_id

logger = logging.getLogger(__name__)

MAX_STR_LEN = 200


def _summarize_value(v: Any) -> Any:
    if isinstance(v, str) and len(v) > MAX_STR_LEN:
        return v[:MAX_STR_LEN] + f"…({len(v) - MAX_STR_LEN} more)"
    if isinstance(v, list) and len(v) > 5:
        return v[:5] + [f"…({len(v) - 5} more)"]
    return v


def _summarize_params(params: dict) -> dict:
    return {k: _summarize_value(v) for k, v in params.items() if not k.startswith("_")}


def _format_row(*, tool_name: str, params: dict, output: dict, trace_id: str | None) -> dict:
    row = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "trace_id": trace_id,
        "tool": tool_name,
        "ok": bool(output.get("ok", True)),
        "params_summary": _summarize_params(params),
        "items": output.get("_items", []),
    }
    if not row["ok"]:
        err_obj = output.get("error", {}) or {}
        row["error_code"] = err_obj.get("code")
    return row


def _log_path() -> Path:
    raw = os.getenv("MAZKIR_AUDIT_LOG_PATH")
    if raw:
        return Path(raw)
    return Path.home() / "dev" / "mazkir" / "data" / "logs" / "tool-calls.jsonl"


def audit_log(params: dict, output: dict, ctx: Any) -> None:
    """Post-hook: append one JSON row to the audit log.

    Hook failures are caught and logged at WARNING — the framework treats
    post-hooks as best-effort side effects.
    """
    try:
        tool_name = ctx["tool"]["schema"]["name"]
        row = _format_row(
            tool_name=tool_name,
            params=params,
            output=output,
            trace_id=current_trace_id(),
        )
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("audit_log hook failed: %s", e)
