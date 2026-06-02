"""Normalized tool response shape and error code enum.

All agent tools return either:
    {"ok": True, "data": {...}, "_items": [...]}
or:
    {"ok": False, "error": {"code": "...", "message": "...", "details": {...}}, "_items": []}

The `_items` list is used by MemoryService to track which vault paths were
touched by a tool call. It is always present (empty on error).
"""

from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    """Stable machine-parseable codes for tool errors.

    The agent's system prompt explains how to respond to each code.
    """

    PATH_NOT_FOUND = "PATH_NOT_FOUND"
    AMBIGUOUS_MATCH = "AMBIGUOUS_MATCH"
    SCHEMA_INVALID = "SCHEMA_INVALID"
    STATE_CONFLICT = "STATE_CONFLICT"
    ALREADY_DONE = "ALREADY_DONE"
    EXTERNAL_FAILURE = "EXTERNAL_FAILURE"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    CANCELLED_BY_USER = "CANCELLED_BY_USER"


def ok(data: dict[str, Any], items: list[str] | None = None) -> dict[str, Any]:
    """Build a successful tool response."""
    return {
        "ok": True,
        "data": data,
        "_items": items or [],
    }


def err(
    code: ErrorCode,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an error tool response."""
    return {
        "ok": False,
        "error": {
            "code": code.value,
            "message": message,
            "details": details or {},
        },
        "_items": [],
    }
