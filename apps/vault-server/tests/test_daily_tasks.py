"""Tests for DailyTasksService — parse/write ## Tasks section."""

import pytest

from src.services.daily_tasks import (
    DailyTask,
    parse_tasks_section,
    render_tasks_section,
)


def test_parse_empty_section():
    body = "Some body text.\n\n## Tasks\n\n## Notes\nstuff"
    tasks = parse_tasks_section(body)
    assert tasks == []


def test_parse_no_section_returns_empty():
    body = "Some body without any tasks section\n"
    tasks = parse_tasks_section(body)
    assert tasks == []


def test_parse_single_unchecked_task():
    body = "## Tasks\n- [ ] Walk dog\n"
    tasks = parse_tasks_section(body)
    assert len(tasks) == 1
    assert tasks[0].text == "Walk dog"
    assert tasks[0].state == "unchecked"
    assert tasks[0].scheduled_at is None
    assert tasks[0].duration_minutes is None
    assert tasks[0].children == []


def test_parse_checked_task():
    body = "## Tasks\n- [x] Done thing\n"
    tasks = parse_tasks_section(body)
    assert tasks[0].state == "checked"
    assert tasks[0].text == "Done thing"


def test_parse_multiple_top_level_tasks():
    body = "## Tasks\n- [ ] First\n- [x] Second\n- [ ] Third\n"
    tasks = parse_tasks_section(body)
    assert len(tasks) == 3
    assert tasks[0].state == "unchecked"
    assert tasks[1].state == "checked"
    assert tasks[2].state == "unchecked"


def test_parse_task_with_time_and_duration():
    body = "## Tasks\n- [ ] 14:00 — Visit dentist (60m)\n"
    tasks = parse_tasks_section(body)
    assert tasks[0].text == "Visit dentist"
    assert tasks[0].scheduled_at == "14:00"
    assert tasks[0].duration_minutes == 60


def test_parse_task_with_only_time_no_duration():
    body = "## Tasks\n- [ ] 09:00 — Standup\n"
    tasks = parse_tasks_section(body)
    assert tasks[0].text == "Standup"
    assert tasks[0].scheduled_at == "09:00"
    assert tasks[0].duration_minutes is None


def test_parse_task_with_only_duration_no_time():
    body = "## Tasks\n- [ ] Deep work (45m)\n"
    tasks = parse_tasks_section(body)
    assert tasks[0].text == "Deep work"
    assert tasks[0].scheduled_at is None
    assert tasks[0].duration_minutes == 45


def test_parse_task_with_children():
    body = (
        "## Tasks\n"
        "- [ ] Plan picnic\n"
        "  - [ ] Buy bread\n"
        "  - check weather forecast\n"
        "  - bring blanket\n"
    )
    tasks = parse_tasks_section(body)
    assert len(tasks) == 1
    assert len(tasks[0].children) == 3
    assert tasks[0].children[0].text == "Buy bread"
    assert tasks[0].children[0].state == "unchecked"
    assert tasks[0].children[1].text == "check weather forecast"
    assert tasks[0].children[1].state == "note"


def test_parse_strikethrough_moved_task():
    body = "## Tasks\n- [ ] ~~Order phone~~ — moved to [[2026-06-05#Tasks]]\n"
    tasks = parse_tasks_section(body)
    assert tasks[0].state == "moved"
    assert tasks[0].text == "Order phone"


def test_render_round_trip_preserves_top_level_tasks():
    body_in = "## Tasks\n- [ ] Walk dog\n- [x] Pay rent\n"
    tasks = parse_tasks_section(body_in)
    rendered = render_tasks_section(tasks)
    assert "- [ ] Walk dog" in rendered
    assert "- [x] Pay rent" in rendered
    assert rendered.startswith("## Tasks")


def test_render_includes_time_and_duration():
    tasks = [
        DailyTask(text="Visit dentist", scheduled_at="14:00", duration_minutes=60),
    ]
    rendered = render_tasks_section(tasks)
    assert "14:00 — Visit dentist (60m)" in rendered


def test_render_strikethrough_for_moved_task():
    tasks = [
        DailyTask(text="Order phone", state="moved", annotation="moved to [[2026-06-05#Tasks]]"),
    ]
    rendered = render_tasks_section(tasks)
    assert "~~Order phone~~" in rendered
    assert "moved to [[2026-06-05#Tasks]]" in rendered


def test_render_nested_children():
    tasks = [
        DailyTask(text="Parent", children=[
            DailyTask(text="Sub-task", state="unchecked"),
            DailyTask(text="just a note", state="note"),
        ]),
    ]
    rendered = render_tasks_section(tasks)
    assert "- [ ] Parent" in rendered
    assert "  - [ ] Sub-task" in rendered
    assert "  - just a note" in rendered
