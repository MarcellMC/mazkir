"""Structured JSON logging for vault-server.

Configures the root logger with a JSON formatter, writes to stdout and to
a rotating file under settings.logs_dir. Also exposes a helper for emitting
per-turn agent audit records to a separate jsonl file.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import time
from pathlib import Path
from typing import Any

from opentelemetry import trace
from pythonjsonlogger.json import JsonFormatter


SERVICE_NAME = "vault-server"


class _ServiceFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        record.service = SERVICE_NAME
        return True


class _TraceContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        span = trace.get_current_span()
        ctx = span.get_span_context() if span else None
        if ctx is not None and ctx.is_valid:
            record.trace_id = format(ctx.trace_id, "032x")
            record.span_id = format(ctx.span_id, "016x")
        else:
            record.trace_id = None
            record.span_id = None
        return True


def configure_logging(log_level: str, logs_dir: Path) -> None:
    """Configure root logger with stdout + rotating-file JSON handlers."""
    logs_dir.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, log_level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    # Drop any pre-existing handlers (basicConfig from earlier imports, pytest, etc.)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = JsonFormatter(
        "{asctime}{levelname}{name}{message}",
        style="{",
        rename_fields={"asctime": "ts", "levelname": "level", "name": "logger"},
    )
    service_filter = _ServiceFilter()
    trace_filter = _TraceContextFilter()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(service_filter)
    stream_handler.addFilter(trace_filter)
    root.addHandler(stream_handler)

    file_handler = logging.handlers.RotatingFileHandler(
        logs_dir / "vault-server.jsonl",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(service_filter)
    file_handler.addFilter(trace_filter)
    root.addHandler(file_handler)

    # Quiet down a couple of chatty libraries unless explicitly DEBUG.
    if level > logging.DEBUG:
        for noisy in ("httpx", "httpcore", "urllib3", "googleapiclient.discovery_cache"):
            logging.getLogger(noisy).setLevel(logging.WARNING)


_audit_logger: logging.Logger | None = None


def _audit() -> logging.Logger:
    global _audit_logger
    if _audit_logger is not None:
        return _audit_logger
    logger = logging.getLogger("mazkir.audit")
    logger.setLevel(logging.INFO)
    logger.propagate = False  # keep audit lines out of the main log
    _audit_logger = logger
    return logger


def configure_audit_log(logs_dir: Path) -> None:
    """Attach a rotating-file handler that writes raw JSON lines."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger = _audit()
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    handler = logging.handlers.RotatingFileHandler(
        logs_dir / "agent-turns.jsonl",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    # Audit records are already complete JSON dicts; emit the message verbatim.
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)


def emit_agent_turn(record: dict[str, Any]) -> None:
    """Write one audit record (one JSON object per line)."""
    payload = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **record}
    try:
        line = json.dumps(payload, default=str, ensure_ascii=False)
    except Exception:  # pragma: no cover — last-resort fallback
        line = json.dumps({"ts": payload["ts"], "error": "audit_serialize_failed"})
    _audit().info(line)
