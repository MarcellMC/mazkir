"""Parser/writer for the `## Schedule` section in daily notes.

Format:
    ## Schedule
    - 20:00–22:30 Pub meeting @ Shnitt brewery [[Momentick]]
    - 09:00 Standup

Each line is `- HH:MM[–HH:MM] <text>`. The text (title, optional `@ location`,
trailing wikilinks) is stored and re-emitted verbatim so the section round-trips.
The dash between start and end times is an en-dash (U+2013).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SECTION_RE = re.compile(
    r"##\s+Schedule\s*\n(.*?)(?=^##|\Z)", re.DOTALL | re.IGNORECASE | re.MULTILINE
)
_LINE_RE = re.compile(
    r"^-\s+(?P<start>\d{1,2}:\d{2})(?:–(?P<end>\d{1,2}:\d{2}))?\s+(?P<text>.*\S)\s*$"
)


@dataclass
class ScheduleEntry:
    start: str
    end: str | None
    text: str


def parse_schedule_section(body: str) -> list[ScheduleEntry]:
    m = _SECTION_RE.search(body)
    if not m:
        return []
    entries: list[ScheduleEntry] = []
    for line in m.group(1).splitlines():
        lm = _LINE_RE.match(line)
        if not lm:
            continue
        entries.append(
            ScheduleEntry(
                start=lm.group("start"),
                end=lm.group("end"),
                text=lm.group("text"),
            )
        )
    return entries


def render_schedule_section(entries: list[ScheduleEntry]) -> str:
    lines = ["## Schedule"]
    for e in entries:
        rng = f"{e.start}–{e.end}" if e.end else e.start
        lines.append(f"- {rng} {e.text}")
    return "\n".join(lines) + "\n"
