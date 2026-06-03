"""Shared OpenTelemetry helpers.

`with_span_status` wraps a span body so a successful exit sets OK and any
raised exception sets ERROR + records the exception event before re-raising.

`current_trace_id` returns the active trace id as a 32-char hex string, or
None if no valid span is in scope. Used by structured-log filters and by
the audit_log post-hook to cross-reference Phoenix traces.
"""

from contextlib import contextmanager
from typing import Optional

from opentelemetry.trace import Status, StatusCode, get_current_span


@contextmanager
def with_span_status(span):
    """Wrap a span body to set OK on success or ERROR on exception.

    On exception: span.record_exception is called, span status is set to
    ERROR with the exception message, and the exception is re-raised.
    """
    try:
        yield
        span.set_status(Status(StatusCode.OK))
    except Exception as e:
        span.record_exception(e)
        span.set_status(Status(StatusCode.ERROR, str(e)))
        raise


def current_trace_id() -> Optional[str]:
    """Return the active OpenTelemetry trace id as 32-char hex, or None."""
    ctx = get_current_span().get_span_context()
    if ctx.is_valid:
        return format(ctx.trace_id, "032x")
    return None
