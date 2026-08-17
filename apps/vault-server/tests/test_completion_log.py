"""Tests for the habit ## Completion Log section."""
import datetime as dt

from src.services.completion_log import (
    CompletionEntry,
    append_completion,
    count_on,
    parse_completion_log,
)

BODY = """\
# Dog Walk

## Goal


## Completion Log
- 2026-08-16T07:12:00
- 2026-08-16T19:40:00
- 2026-08-15T08:00:00

## Notes
"""


def test_parses_entries_in_file_order():
    entries = parse_completion_log(BODY)
    assert [e.at for e in entries] == [
        dt.datetime(2026, 8, 16, 7, 12),
        dt.datetime(2026, 8, 16, 19, 40),
        dt.datetime(2026, 8, 15, 8, 0),
    ]


def test_missing_section_parses_as_empty():
    assert parse_completion_log("# Dog Walk\n\n## Notes\n") == []


def test_malformed_lines_are_skipped():
    body = "## Completion Log\n- not a date\n- 2026-08-16T07:12:00\n"
    assert [e.at for e in parse_completion_log(body)] == [
        dt.datetime(2026, 8, 16, 7, 12)
    ]


def test_count_on_counts_only_that_day():
    entries = parse_completion_log(BODY)
    assert count_on(entries, dt.date(2026, 8, 16)) == 2
    assert count_on(entries, dt.date(2026, 8, 15)) == 1
    assert count_on(entries, dt.date(2026, 8, 14)) == 0


def test_append_adds_a_line_and_preserves_other_sections():
    new_body = append_completion(BODY, dt.datetime(2026, 8, 17, 6, 5))

    assert "- 2026-08-17T06:05:00" in new_body
    assert count_on(parse_completion_log(new_body), dt.date(2026, 8, 17)) == 1
    assert "## Notes" in new_body
    assert "## Goal" in new_body


def test_append_creates_the_section_when_absent():
    new_body = append_completion("# Dog Walk\n", dt.datetime(2026, 8, 17, 6, 5))

    assert "## Completion Log" in new_body
    assert count_on(parse_completion_log(new_body), dt.date(2026, 8, 17)) == 1
