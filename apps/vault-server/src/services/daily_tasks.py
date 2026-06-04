"""Parser/writer for the `## Tasks` section in daily notes.

Format:
    ## Tasks
    - [ ] 14:00 — Visit dentist (60m)
      - [ ] bring insurance card
      - check tooth still hurts
    - [x] Walk dog
    - [ ] ~~Order phone~~ — moved to [[2026-06-05#Tasks]]

State markers:
    - [ ]   unchecked
    - [x]   checked (done)
    - [ ] ~~text~~   moved (strikethrough)
    plain bullet at child indent   note

Inline time + duration annotation on the parent line:
    `HH:MM — text (NNm)`
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

TaskState = Literal["unchecked", "checked", "moved", "note"]


@dataclass
class DailyTask:
    text: str
    state: TaskState = "unchecked"
    scheduled_at: str | None = None
    duration_minutes: int | None = None
    annotation: str | None = None
    children: list["DailyTask"] = field(default_factory=list)


_SECTION_RE = re.compile(
    r"##\s+Tasks\s*\n(.*?)(?=^##|\Z)", re.DOTALL | re.IGNORECASE | re.MULTILINE
)
_LINE_RE = re.compile(
    r"^(?P<indent>\s*)"
    r"(?:-\s+\[(?P<box>[ x])\]\s+)?"
    r"(?P<rest>.*)$"
)
_TIME_RE = re.compile(r"^(?P<time>\d{1,2}:\d{2})\s+—\s+(?P<text>.*)$")
_DURATION_RE = re.compile(r"\s*\((?P<n>\d+)m\)\s*$")
_STRIKE_RE = re.compile(r"^~~(?P<text>.*?)~~(?:\s+—\s+(?P<ann>.*))?$")


def parse_tasks_section(body: str) -> list[DailyTask]:
    m = _SECTION_RE.search(body)
    if not m:
        return []

    raw_lines = m.group(1).splitlines()
    parsed: list[tuple[int, dict]] = []
    for line in raw_lines:
        if not line.strip():
            continue
        lm = _LINE_RE.match(line)
        if not lm:
            continue
        indent = len(lm.group("indent")) // 2
        rest = lm.group("rest")
        box = lm.group("box")

        if box is not None:
            text = rest
            scheduled_at = None
            duration = None
            annotation = None
            state: TaskState = "checked" if box == "x" else "unchecked"

            sm = _STRIKE_RE.match(text)
            if sm:
                state = "moved"
                text = sm.group("text")
                annotation = sm.group("ann")

            tm = _TIME_RE.match(text)
            if tm:
                scheduled_at = tm.group("time")
                text = tm.group("text")

            dm = _DURATION_RE.search(text)
            if dm:
                duration = int(dm.group("n"))
                text = _DURATION_RE.sub("", text).rstrip()

            parsed.append((indent, {
                "text": text.strip(),
                "state": state,
                "scheduled_at": scheduled_at,
                "duration_minutes": duration,
                "annotation": annotation,
                "children": [],
            }))
        else:
            # plain bullet / numbered note line (no checkbox)
            note_text = rest.lstrip("- ").lstrip()
            note_text = re.sub(r"^\d+\.\s+", "", note_text)
            if not note_text:
                continue
            parsed.append((indent, {
                "text": note_text.strip(),
                "state": "note",
                "scheduled_at": None,
                "duration_minutes": None,
                "annotation": None,
                "children": [],
            }))

    roots: list[DailyTask] = []
    stack: list[tuple[int, DailyTask]] = []
    for indent, fields in parsed:
        task = DailyTask(**fields)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if stack:
            stack[-1][1].children.append(task)
        else:
            roots.append(task)
        stack.append((indent, task))
    return roots


def render_tasks_section(tasks: list[DailyTask]) -> str:
    lines = ["## Tasks"]

    def emit(task: DailyTask, depth: int) -> None:
        prefix = "  " * depth
        if task.state == "note":
            lines.append(f"{prefix}- {task.text}")
        else:
            box = "x" if task.state == "checked" else " "
            content = task.text
            if task.state == "moved":
                content = f"~~{content}~~"
            if task.scheduled_at:
                content = f"{task.scheduled_at} — {content}"
            if task.duration_minutes:
                content = f"{content} ({task.duration_minutes}m)"
            if task.annotation:
                content = f"{content} — {task.annotation}"
            lines.append(f"{prefix}- [{box}] {content}")
        for child in task.children:
            emit(child, depth + 1)

    for t in tasks:
        emit(t, 0)
    return "\n".join(lines) + "\n"


def replace_or_append_section(body: str, section_name: str, new_section: str) -> str:
    """Replace the named ## section (through next ## or EOF) with new_section.

    If the section doesn't exist, append new_section at the end.
    `new_section` must already start with `## <name>`.
    """
    pattern = re.compile(
        rf"##\s+{re.escape(section_name)}\s*\n.*?(?=\n##\s|\Z)",
        re.DOTALL | re.IGNORECASE,
    )
    if pattern.search(body):
        return pattern.sub(new_section.rstrip() + "\n", body)
    return body.rstrip() + "\n\n" + new_section
