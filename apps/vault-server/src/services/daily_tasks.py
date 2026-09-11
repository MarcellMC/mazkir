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
    r"(?:[-*]\s+\[(?P<box>[ xX])\]\s+)?"
    r"(?P<rest>.*)$"
)
_TIME_RE = re.compile(r"^(?P<time>\d{1,2}:\d{2})\s+—\s+(?P<text>.*)$")
_DURATION_RE = re.compile(r"\s*\((?P<n>\d+)m\)\s*$")
_STRIKE_RE = re.compile(r"^~~(?P<text>.*)~~$")
# The only annotation the writers ever emit is a move-chain link. Matching
# that shape specifically keeps an em dash in ordinary task prose
# ("Buy milk — the good kind") from being torn off as an annotation.
_ANNOTATION_RE = re.compile(r"\s+—\s+(?P<ann>moved (?:to|from) \[\[[^\]]+\]\])\s*$")
# Struck lines only: a hand-written trailing comment ("~~Order phone~~ —
# cancelled, bought in store") is an annotation too. The boundary is the
# first em dash *after the closing* `~~` — `.*~~` runs greedy to find that
# closing wrapper, `.*?` then stops at the first dash beyond it. Anchoring
# on the wrapper rather than on a dash is what keeps dashes inside the
# struck text ("~~a — b~~ — c") and dashes inside the comment
# ("~~Order phone~~ — cancelled — refunded already") on their own sides.
_STRUCK_COMMENT_RE = re.compile(r"^(?P<head>~~.*~~.*?)\s+—\s+(?P<ann>.*)$")
_HEADING_RE = re.compile(r"^##\s+(?P<name>.+?)\s*$")


def _parse_task_content(rest: str, box: str) -> dict:
    """Parse the content of one checkbox line into its fields.

    The exact inverse of how `render_tasks_section` assembles content.
    That function wraps the text in `~~`, prefixes the time, then appends
    the duration and the annotation — so all four decorations must be
    peeled off in the opposite order. Peeling in any other order strands
    markup inside `text`: it survives a round-trip unchanged, which is
    why such bugs stay invisible until something reads a field.
    """
    text = rest
    state: TaskState = "checked" if box.lower() == "x" else "unchecked"
    scheduled_at = None
    duration = None
    annotation = None

    # The time prefix comes off first even though the renderer applies it
    # second-to-innermost: it is the only decoration anchored at the front,
    # and leaving it in place keeps the strike wrapper away from position 0,
    # where every pattern below expects to find it.
    tm = _TIME_RE.match(text)
    if tm:
        scheduled_at = tm.group("time")
        text = tm.group("text")

    am = _ANNOTATION_RE.search(text)
    if am:
        annotation = am.group("ann")
        text = text[: am.start()]
    else:
        cm = _STRUCK_COMMENT_RE.match(text)
        if cm:
            annotation = cm.group("ann")
            text = cm.group("head")

    dm = _DURATION_RE.search(text)
    if dm:
        duration = int(dm.group("n"))
        text = _DURATION_RE.sub("", text).rstrip()

    sm = _STRIKE_RE.match(text)
    if sm:
        state = "moved"
        text = sm.group("text")
        # Hand-authored `~~14:00 — text (30m)~~`, where the decorations sit
        # inside the wrapper rather than around it. Extracting them here
        # normalises the line to the canonical outer form on the next
        # render; that is a deliberate rewrite, not a round-trip.
        if scheduled_at is None:
            tm = _TIME_RE.match(text)
            if tm:
                scheduled_at = tm.group("time")
                text = tm.group("text")
        if duration is None:
            dm = _DURATION_RE.search(text)
            if dm:
                duration = int(dm.group("n"))
                text = _DURATION_RE.sub("", text).rstrip()

    return {
        "text": text.strip(),
        "state": state,
        "scheduled_at": scheduled_at,
        "duration_minutes": duration,
        "annotation": annotation,
    }


def _parse_todo_line(line: str) -> dict | None:
    """Parse one checkbox line. Returns None for anything that isn't one.

    Shares `_parse_task_content` with `parse_tasks_section`, so the two
    cannot drift apart on what a checkbox looks like. Drops `annotation`,
    which `Todo` does not carry.
    """
    lm = _LINE_RE.match(line)
    if not lm or lm.group("box") is None:
        return None
    fields = _parse_task_content(lm.group("rest"), lm.group("box"))
    fields.pop("annotation")
    return fields


def is_todo_line(line: str) -> bool:
    """True when `line` is a checkbox. Public so other modules can filter
    checkboxes out of prose without importing a private helper."""
    return _parse_todo_line(line) is not None


@dataclass(frozen=True)
class Todo:
    """A checkbox anywhere in a daily note.

    Distinct from `DailyTask`, which models the nested `## Tasks` tree the
    write tools edit. A Todo is flat and carries the section it came from.
    """
    text: str
    state: TaskState
    section: str
    scheduled_at: str | None = None
    duration_minutes: int | None = None


def parse_all_todos(body: str) -> list[Todo]:
    """Every checkbox in the note that has not been moved away, in
    document order — checked ones included, so callers can show what is
    already done.

    Section-agnostic: a checkbox under `## Notes` is as much a todo as one
    under `## Tasks`. `moved` items are excluded — they have been rolled to
    another day and are no longer this day's business.
    """
    todos: list[Todo] = []
    section = ""
    for line in body.splitlines():
        hm = _HEADING_RE.match(line)
        if hm:
            section = hm.group("name")
            continue
        fields = _parse_todo_line(line)
        if fields is None or fields["state"] == "moved":
            continue
        todos.append(Todo(section=section, **fields))
    return todos


def set_todo_checked(body: str, text: str, checked: bool = True) -> tuple[str | None, str]:
    """Tick or untick one checkbox anywhere in the note, matched by its text.

    Returns `(new_body, "ok")`, or `(None, reason)` with reason `"not_found"`
    or `"ambiguous"`.

    Section-agnostic, to match `parse_all_todos` — which is what turns a
    timed checkbox into an event-service block in the first place, so the
    write path has to reach every checkbox the read path can see.
    `daily_set_task_state` cannot: it re-renders `## Tasks` wholesale via
    `render_tasks_section`, so it can only ever write back to that section.

    An in-place edit of the matched line's checkbox marker only, located via
    `_LINE_RE`'s own `box` group span, so no other section's formatting,
    ordering, indentation or annotations can be disturbed by approving a
    block. `moved` lines are skipped: they have been rolled to another day
    and are no longer this day's checkbox to tick.
    """
    needle = text.strip().lower()
    if not needle:
        return None, "not_found"

    lines = body.splitlines(keepends=True)
    hits: list[int] = []
    for index, line in enumerate(lines):
        fields = _parse_todo_line(line)
        if fields is None or fields["state"] == "moved":
            continue
        if needle in fields["text"].strip().lower():
            hits.append(index)

    if not hits:
        return None, "not_found"
    if len(hits) > 1:
        return None, "ambiguous"

    index = hits[0]
    line = lines[index]
    lm = _LINE_RE.match(line)
    box_start, box_end = lm.span("box")
    marker = "x" if checked else " "
    lines[index] = line[:box_start] + marker + line[box_end:]
    return "".join(lines), "ok"


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
            parsed.append((indent, {**_parse_task_content(rest, box), "children": []}))
        else:
            # plain bullet / numbered note line (no checkbox)
            note_text = rest.lstrip("-* ").lstrip()
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
    # `#{2,}` — not `##` — so this stops where `_SECTION_RE` stops. When the
    # two disagreed, `## Tasks` rewrites silently deleted a following
    # `### Sub` heading and every line under it from the user's vault.
    pattern = re.compile(
        rf"##\s+{re.escape(section_name)}\s*\n.*?(?=\n#{{2,}}\s|\Z)",
        re.DOTALL | re.IGNORECASE,
    )
    if pattern.search(body):
        return pattern.sub(new_section.rstrip() + "\n", body)
    return body.rstrip() + "\n\n" + new_section
