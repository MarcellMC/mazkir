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


class TestPayloadProvenance:
    """The fields whose absence was invisible in Phoenix on 2026-09-12.

    Thirty spans covering the failing minute mentioned neither `reply_to` nor
    `selected_date`, so a lost gap question could only be found by grepping
    structured logs by timestamp. These attributes make it one query.
    """

    def _recorded(self, **kwargs) -> dict:
        from unittest.mock import patch
        from src.services.tracing_helpers import set_payload_provenance
        span = MagicMock()
        span.is_recording.return_value = True
        with patch("src.services.tracing_helpers.get_current_span", return_value=span):
            set_payload_provenance(**kwargs)
        return {c.args[0]: c.args[1] for c in span.set_attribute.call_args_list}

    def test_records_the_context_that_arrived(self):
        attrs = self._recorded(
            text_length=11, has_reply_to=True, reply_to_from="assistant",
            selected_date="2026-09-12", has_forwarded_from=False,
            attachment_types=["photo"],
        )
        assert attrs["mazkir.payload.has_reply_to"] is True
        assert attrs["mazkir.payload.reply_to_from"] == "assistant"
        assert attrs["mazkir.payload.selected_date"] == "2026-09-12"
        assert attrs["mazkir.payload.text_length"] == 11
        assert attrs["mazkir.payload.attachment_types"] == ["photo"]

    def test_absence_is_recorded_as_empty_not_omitted(self):
        """The 20:03 turn, as it would now appear.

        An absent key cannot be told apart from a span predating the
        attribute, so "nothing was sent" has to be written down explicitly —
        that is the whole point of the change.
        """
        attrs = self._recorded(text_length=11, has_reply_to=False)

        assert attrs["mazkir.payload.has_reply_to"] is False
        assert "mazkir.payload.selected_date" in attrs
        assert attrs["mazkir.payload.selected_date"] == ""
        assert attrs["mazkir.payload.reply_to_from"] == ""

    def test_no_op_without_a_recording_span(self):
        from unittest.mock import patch
        from src.services.tracing_helpers import set_payload_provenance
        span = MagicMock()
        span.is_recording.return_value = False
        with patch("src.services.tracing_helpers.get_current_span", return_value=span):
            set_payload_provenance(text_length=1, has_reply_to=False)
        span.set_attribute.assert_not_called()
