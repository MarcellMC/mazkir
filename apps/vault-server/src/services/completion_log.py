"""Parser/renderer for the `## Completion Log` section of a habit note.

Source of truth for how many times a habit was completed on a given day.
Counting entries beats a mutable counter: the log cannot drift out of sync
with itself, and it doubles as an audit trail.

Format — one ISO timestamp per line, file order preserved:

    ## Completion Log
    - 2026-08-16T07:12:00
    - 2026-08-16T19:40:00
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from src.services.daily_tasks import replace_or_append_section

_SECTION_RE = re.compile(
    r"##\s+Completion Log\s*\n(.*?)(?=^##\s|\Z)",
    re.DOTALL | re.IGNORECASE | re.MULTILINE,
)
_ENTRY_RE = re.compile(r"^\s*-\s+(?P<ts>\S+)\s*$")


@dataclass(frozen=True)
class CompletionEntry:
    at: dt.datetime


def parse_completion_log(body: str) -> list[CompletionEntry]:
    """Return every well-formed entry, in file order. Malformed lines are skipped."""
    match = _SECTION_RE.search(body)
    if not match:
        return []

    entries: list[CompletionEntry] = []
    for line in match.group(1).splitlines():
        m = _ENTRY_RE.match(line)
        if not m:
            continue
        try:
            entries.append(CompletionEntry(at=dt.datetime.fromisoformat(m.group("ts"))))
        except ValueError:
            continue
    return entries


def count_on(entries: list[CompletionEntry], day: dt.date) -> int:
    """How many of `entries` fall on `day`."""
    return sum(1 for e in entries if e.at.date() == day)


def render_completion_log(entries: list[CompletionEntry]) -> str:
    """Render the section body (without its heading)."""
    lines = [f"- {e.at.isoformat()}" for e in entries]
    return "\n".join(lines) + "\n"


def append_completion(body: str, at: dt.datetime) -> str:
    """Return `body` with one more completion recorded at `at`."""
    entries = parse_completion_log(body)
    entries.append(CompletionEntry(at=at.replace(microsecond=0)))
    new_section = "## Completion Log\n" + render_completion_log(entries)
    return replace_or_append_section(
        body, "Completion Log", new_section
    )
