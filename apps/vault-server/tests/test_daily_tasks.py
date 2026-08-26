"""Tests for DailyTasksService — parse/write ## Tasks section."""

import pytest

from src.services.daily_tasks import (
    DailyTask,
    parse_tasks_section,
    render_tasks_section,
    parse_all_todos,
    is_todo_line,
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


WHOLE_NOTE = """\
- [ ] Stray above any heading

## Tasks
- [ ] 14:00 — Visit dentist (60m)
- [x] Walk dog
- [ ] ~~Order phone~~ — moved to [[2026-06-05#Tasks]]

## Notes
- Bought dog food
- [ ] Order dog food (30m)

## Schedule
09:00–10:00 Standup
"""


def test_collects_checkboxes_from_every_section():
    todos = parse_all_todos(WHOLE_NOTE)
    assert [t.text for t in todos] == [
        "Stray above any heading",
        "Visit dentist",
        "Walk dog",
        "Order dog food",
    ]


def test_records_the_enclosing_section():
    todos = {t.text: t.section for t in parse_all_todos(WHOLE_NOTE)}
    assert todos["Stray above any heading"] == ""
    assert todos["Visit dentist"] == "Tasks"
    assert todos["Order dog food"] == "Notes"


def test_moved_todos_are_excluded():
    assert "Order phone" not in [t.text for t in parse_all_todos(WHOLE_NOTE)]


def test_preserves_time_duration_and_state():
    by_text = {t.text: t for t in parse_all_todos(WHOLE_NOTE)}
    assert by_text["Visit dentist"].scheduled_at == "14:00"
    assert by_text["Visit dentist"].duration_minutes == 60
    assert by_text["Visit dentist"].state == "unchecked"
    assert by_text["Walk dog"].state == "checked"
    assert by_text["Order dog food"].duration_minutes == 30


def test_plain_bullets_are_not_todos():
    assert "Bought dog food" not in [t.text for t in parse_all_todos(WHOLE_NOTE)]


def test_note_with_no_checkboxes_returns_empty():
    assert parse_all_todos("## Notes\n- just a thought\n") == []


def test_is_todo_line_identifies_checkboxes():
    assert is_todo_line("- [ ] Order dog food") is True
    assert is_todo_line("- [x] Walk dog") is True
    assert is_todo_line("- Bought dog food") is False
    assert is_todo_line("## Notes") is False
    assert is_todo_line("") is False


def test_parse_tasks_section_still_scoped_to_tasks():
    """The existing write-path parser must not start seeing Notes checkboxes."""
    texts = [t.text for t in parse_tasks_section(WHOLE_NOTE)]
    assert "Order dog food" not in texts
    assert "Visit dentist" in texts


# --- _STRIKE_RE round-trip: duration between the strike and the annotation ---


def test_parse_moved_task_with_duration():
    """render_tasks_section emits `~~text~~ (30m) — moved to [[...]]`, so the
    parser must read that form back as moved."""
    body = "## Tasks\n- [ ] ~~Order dog food~~ (30m) — moved to [[2026-08-23#Tasks]]\n"
    task = parse_tasks_section(body)[0]
    assert task.state == "moved"
    assert task.text == "Order dog food"
    assert task.duration_minutes == 30
    assert task.annotation == "moved to [[2026-08-23#Tasks]]"


def test_parse_moved_task_with_time_and_duration():
    body = "## Tasks\n- [ ] 14:00 — ~~Visit dentist~~ (60m) — moved to [[2026-08-23#Tasks]]\n"
    task = parse_tasks_section(body)[0]
    assert task.state == "moved"
    assert task.text == "Visit dentist"
    assert task.scheduled_at == "14:00"
    assert task.duration_minutes == 60
    assert task.annotation == "moved to [[2026-08-23#Tasks]]"


def test_parse_moved_task_with_hand_written_time_inside_strike():
    """Obsidian-authored `~~14:00 — text~~` still yields the time."""
    body = "## Tasks\n- [ ] ~~14:00 — Visit dentist~~ — moved to [[2026-08-23#Tasks]]\n"
    task = parse_tasks_section(body)[0]
    assert task.state == "moved"
    assert task.text == "Visit dentist"
    assert task.scheduled_at == "14:00"


@pytest.mark.parametrize("line", [
    "- [ ] ~~Order dog food~~ (30m) — moved to [[2026-08-23#Tasks]]",
    "- [ ] ~~Order phone~~ — moved to [[2026-08-23#Tasks]]",
    "- [ ] 14:00 — ~~Visit dentist~~ (60m) — moved to [[2026-08-23#Tasks]]",
    "- [ ] ~~Bare strike no annotation~~",
])
def test_render_round_trips_every_moved_form(line):
    body = f"## Tasks\n{line}\n"
    assert render_tasks_section(parse_tasks_section(body)) == body


def test_moved_todo_with_duration_excluded_from_parse_all_todos():
    body = "## Tasks\n- [ ] ~~Order dog food~~ (30m) — moved to [[2026-08-23#Tasks]]\n"
    assert parse_all_todos(body) == []


def test_parse_annotation_on_an_unchecked_task():
    """The move chain lives on unchecked lines — that is where daily_rollover
    reads it from. It must parse there, not only inside a strike wrapper."""
    body = "## Tasks\n- [ ] Order dog food (30m) — moved from [[2026-08-20#Tasks]]\n"
    task = parse_tasks_section(body)[0]
    assert task.state == "unchecked"
    assert task.text == "Order dog food"
    assert task.duration_minutes == 30
    assert task.annotation == "moved from [[2026-08-20#Tasks]]"


def test_em_dash_in_task_prose_is_not_an_annotation():
    """Only the move-chain shape counts, so ordinary prose keeps its dash."""
    body = "## Tasks\n- [ ] Buy milk — the good kind\n"
    task = parse_tasks_section(body)[0]
    assert task.text == "Buy milk — the good kind"
    assert task.annotation is None


@pytest.mark.parametrize("line", [
    "- [ ] Order dog food (30m) — moved from [[2026-08-20#Tasks]]",
    "- [ ] Buy milk — the good kind",
    "- [x] 09:00 — Standup (15m)",
])
def test_render_round_trips_unmoved_forms(line):
    body = f"## Tasks\n{line}\n"
    assert render_tasks_section(parse_tasks_section(body)) == body
