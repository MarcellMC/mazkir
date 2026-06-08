"""Tests for the daily-note `## Schedule` section parser/renderer."""

from src.services.daily_schedule import (
    ScheduleEntry,
    parse_schedule_section,
    render_schedule_section,
)


def test_parse_empty_when_no_section():
    assert parse_schedule_section("## Tasks\n- [ ]\n") == []


def test_parse_single_entry_with_end_and_text():
    body = "## Schedule\n- 20:00–22:30 Pub meeting @ Shnitt brewery [[Momentick]]\n\n## Food\n"
    entries = parse_schedule_section(body)
    assert entries == [
        ScheduleEntry(
            start="20:00",
            end="22:30",
            text="Pub meeting @ Shnitt brewery [[Momentick]]",
        )
    ]


def test_parse_entry_without_end():
    entries = parse_schedule_section("## Schedule\n- 09:00 Standup\n")
    assert entries == [ScheduleEntry(start="09:00", end=None, text="Standup")]


def test_render_includes_header_and_dash_range():
    section = render_schedule_section(
        [ScheduleEntry(start="20:00", end="22:30", text="Pub meeting @ Shnitt brewery")]
    )
    assert section == "## Schedule\n- 20:00–22:30 Pub meeting @ Shnitt brewery\n"


def test_render_omits_end_when_absent():
    section = render_schedule_section([ScheduleEntry(start="09:00", end=None, text="Standup")])
    assert section == "## Schedule\n- 09:00 Standup\n"


def test_round_trip_preserves_entries():
    body = "## Schedule\n- 09:00 Standup\n- 20:00–22:30 Pub meeting [[Momentick]]\n"
    entries = parse_schedule_section(body)
    assert render_schedule_section(entries) == body
