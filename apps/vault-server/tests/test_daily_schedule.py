"""Tests for the daily-note `## Schedule` section parser/renderer."""

from src.services.daily_schedule import (
    ScheduleEntry,
    append_schedule_entry,
    parse_schedule_section,
    render_schedule_section,
)


def test_append_adds_a_line_and_keeps_other_sections():
    body = "## Schedule\n- 09:00–09:30 Standup\n\n## Notes\n- hi\n"

    out = append_schedule_entry(body, "17:00", "17:10", "Water the plants")

    assert parse_schedule_section(out) == [
        ScheduleEntry(start="09:00", end="09:30", text="Standup"),
        ScheduleEntry(start="17:00", end="17:10", text="Water the plants"),
    ]
    assert "## Notes\n- hi" in out


def test_append_creates_the_section_when_missing():
    out = append_schedule_entry("## Notes\n- hi\n", "17:00", None, "Water the plants")

    assert parse_schedule_section(out) == [
        ScheduleEntry(start="17:00", end=None, text="Water the plants"),
    ]


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


def test_parse_empty_section_returns_empty():
    body = "## Schedule\n\n## Food\n"
    assert parse_schedule_section(body) == []


def test_parse_schedule_at_end_of_file():
    body = "## Tasks\n- [ ] Walk dog\n\n## Schedule\n- 09:00 Standup\n"
    entries = parse_schedule_section(body)
    assert entries == [ScheduleEntry(start="09:00", end=None, text="Standup")]


class TestRenderSkipsUnrepresentableEntries:
    """`- HH:MM ...` is the only shape `parse_schedule_section` can read.

    An entry with no start has no representation in this format at all, and
    the naive f-string wrote `- None-16:40 Dog walk` — unparseable, so
    silently discarded by the next rewrite of the section. Dropping it here
    is the renderer's own guard; the caller in `_tool_create_event` also
    declines to write incomplete blocks in the first place.
    """

    def test_entry_with_no_start_is_dropped(self):
        from src.services.daily_schedule import (
            ScheduleEntry, parse_schedule_section, render_schedule_section,
        )

        out = render_schedule_section([
            ScheduleEntry(start="09:00", text="Standup"),
            ScheduleEntry(start=None, end="16:40", text="Dog walk"),
        ])

        assert "None" not in out
        assert "Dog walk" not in out
        assert "- 09:00 Standup" in out
        assert [e.text for e in parse_schedule_section(out)] == ["Standup"]
