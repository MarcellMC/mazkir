"""Tests for normalized tool response shape."""

from src.services.tool_response import ok, err, ErrorCode


def test_ok_basic():
    r = ok({"saved": "path.md"}, items=["path.md"])
    assert r == {
        "ok": True,
        "data": {"saved": "path.md"},
        "_items": ["path.md"],
    }


def test_ok_default_items():
    r = ok({"x": 1})
    assert r["_items"] == []


def test_err_basic():
    r = err(ErrorCode.PATH_NOT_FOUND, "no such file", details={"query": "foo"})
    assert r == {
        "ok": False,
        "error": {
            "code": "PATH_NOT_FOUND",
            "message": "no such file",
            "details": {"query": "foo"},
        },
        "_items": [],
    }


def test_err_default_details():
    r = err(ErrorCode.SCHEMA_INVALID, "bad input")
    assert r["error"]["details"] == {}


def test_error_codes_complete():
    expected = {
        "PATH_NOT_FOUND",
        "AMBIGUOUS_MATCH",
        "SCHEMA_INVALID",
        "STATE_CONFLICT",
        "ALREADY_DONE",
        "EXTERNAL_FAILURE",
        "AUTH_REQUIRED",
        "CANCELLED_BY_USER",
    }
    assert {c.value for c in ErrorCode} == expected
