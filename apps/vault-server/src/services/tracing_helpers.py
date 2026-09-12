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


# Attribute prefix for "what context arrived with this turn". Kept as one
# namespace so a Phoenix query can select the whole group.
PAYLOAD_PREFIX = "mazkir.payload"


def set_payload_provenance(
    *,
    text_length: int,
    has_reply_to: bool,
    reply_to_from: str | None = None,
    selected_date: str | None = None,
    has_forwarded_from: bool = False,
    attachment_types: list[str] | None = None,
) -> None:
    """Stamp the current span with the context that came with this message.

    These are the fields whose *absence* is a bug and which no other span
    records. On 2026-09-12 a gap question the bot had asked never reached the
    agent, and the traces for that minute could show only that the model
    received a bare "Bar hopping" — `reply_to` and `selected_date` appeared
    nowhere in 30 spans, so localising it meant grepping structured logs
    instead. The server-side half of that answer lives here.

    Read alongside the bot's `mazkir.payload.reply_to_source` on the
    `telegram.update` span: the bot records what it *sent*, this records what
    *arrived*. Agreement narrows the fault to one side of the wire.

    No-ops without a recording span, so callers need no guard and tests need
    no tracing setup.
    """
    span = get_current_span()
    if not span.is_recording():
        return
    span.set_attribute(f"{PAYLOAD_PREFIX}.text_length", text_length)
    span.set_attribute(f"{PAYLOAD_PREFIX}.has_reply_to", has_reply_to)
    span.set_attribute(f"{PAYLOAD_PREFIX}.has_forwarded_from", has_forwarded_from)
    # Empty string rather than omitting the key: a Phoenix filter on
    # "selected_date == ''" can then distinguish "no date was sent" from "this
    # span predates the attribute", which an absent key cannot.
    span.set_attribute(f"{PAYLOAD_PREFIX}.selected_date", selected_date or "")
    span.set_attribute(f"{PAYLOAD_PREFIX}.reply_to_from", reply_to_from or "")
    span.set_attribute(
        f"{PAYLOAD_PREFIX}.attachment_types", attachment_types or []
    )
