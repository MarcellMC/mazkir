"""Tests for tracing helpers."""

import pytest
from unittest.mock import MagicMock

from src.services.tracing_helpers import with_span_status, current_trace_id


def test_with_span_status_ok_path():
    span = MagicMock()
    with with_span_status(span):
        pass
    span.set_status.assert_called_once()
    args, _ = span.set_status.call_args
    status = args[0]
    from opentelemetry.trace import StatusCode
    assert status.status_code == StatusCode.OK


def test_with_span_status_error_path_propagates_exception():
    span = MagicMock()
    with pytest.raises(ValueError):
        with with_span_status(span):
            raise ValueError("boom")
    span.record_exception.assert_called_once()
    args, _ = span.set_status.call_args
    status = args[0]
    from opentelemetry.trace import StatusCode
    assert status.status_code == StatusCode.ERROR
    assert "boom" in status.description


def test_current_trace_id_returns_string_or_none():
    result = current_trace_id()
    assert result is None or (isinstance(result, str) and len(result) == 32)
