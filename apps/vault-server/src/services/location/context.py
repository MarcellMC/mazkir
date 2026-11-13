"""Context for the guess, chosen by time only and quoted as found (trips spec §5.2 item 2).

Nothing here interprets a line. Each gets an id so the model can cite it, and
code checks that citation (`guess.py`): the model can find "Dana's for
dinner" in yesterday's messages without being able to make one up.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from src.services.daily_tasks import parse_all_todos
from src.services.habit_completion import completions_today, daily_target_of

logger = logging.getLogger(__name__)

WINDOW = dt.timedelta(hours=24)
MAX_CONVERSATION = 60
MAX_CHARS = 300
_HEADER = re.compile(r"^### (\d{2}):(\d{2}) \[(\w+)\]\s*$")
# A check-in is logged in the conversation as "(location: <lat>, <lng>)", and
# a pasted pair looks the same: neither may reach the model (spec §1.3).
_COORDS = re.compile(r"\(location:[^)]*\)|-?\d{1,3}\.\d{3,}\s*,\s*-?\d{1,3}\.\d{3,}")


@dataclass(frozen=True)
class ContextLine:
    id: str
    kind: str      # "conversation" | "todo" | "task" | "block" | "habit"
    text: str


def _cut(text: str) -> str:
    text = _COORDS.sub("(a location)", text)
    text = " ".join(text.split())
    return text if len(text) <= MAX_CHARS else text[: MAX_CHARS - 1] + "…"


def _conversation(conversations_dir: Path, chat_id: int, now: dt.datetime, zone: ZoneInfo) -> list[tuple[str, str]]:
    today = now.astimezone(zone).date()
    out: list[tuple[dt.datetime, str]] = []
    for day in (today - dt.timedelta(days=1), today):
        path = conversations_dir / day.isoformat() / f"{chat_id}.md"
        if not path.exists():
            continue
        current: tuple[dt.datetime, str, list[str]] | None = None
        messages: list[tuple[dt.datetime, str, list[str]]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            m = _HEADER.match(line)
            if m:
                current = (dt.datetime(day.year, day.month, day.day, int(m[1]), int(m[2]), tzinfo=zone), m[3], [])
                messages.append(current)
            elif current is not None:
                current[2].append(line)
        for when, role, body in messages:
            text = "\n".join(body).strip()
            if text and now - WINDOW <= when <= now:
                label = "today" if when.date() == today else "yesterday"
                out.append((when, f"[{label} {when:%H:%M}] {role}: {text}"))
    out.sort(key=lambda x: x[0])
    return [("conversation", text) for _, text in out[-MAX_CONVERSATION:]]


def _todos(vault, today: dt.date) -> list[tuple[str, str]]:
    body = vault.read_daily_note(today.isoformat()).get("content") or ""
    return [("todo", t.text) for t in parse_all_todos(body) if t.state == "unchecked"]


def _tasks(vault) -> list[tuple[str, str]]:
    out = []
    for task in vault.list_active_tasks():
        meta = task.get("metadata") or {}
        name = meta.get("name")
        if name:
            due = meta.get("due_date")
            out.append(("task", f"{name} (due {due})" if due else str(name)))
    return out


def _blocks(events, today: dt.date) -> list[tuple[str, str]]:
    out = []
    for e in sorted(events.get_events(today.isoformat()), key=lambda e: e.get("start_time") or ""):
        if e.get("trip") or e.get("state") == "dismissed":
            continue   # Mazkir's own guesses about trips are not evidence for one
        start, end = (e.get("start_time") or "")[11:16], (e.get("end_time") or "")[11:16]
        when = f"{start}–{end}" if start and end else start or (f"until {end}" if end else "")
        place = (e.get("location") or {}).get("name")
        text = " ".join(x for x in (e.get("name") or "", when) if x)
        out.append(("block", f"{text} @ {place}" if place else text))
    return out


def _habits(vault, today: dt.date) -> list[tuple[str, str]]:
    out = []
    for habit in vault.list_active_habits():
        meta = habit.get("metadata") or {}
        target = daily_target_of(meta)
        done = completions_today(habit, today)
        if meta.get("name") and done < target:
            out.append(("habit", f"{meta['name']} ({done} of {target} today)"))
    return out


def gather_context(now: dt.datetime, *, vault, events, conversations_dir: Path, chat_id: int | None,
                   tz: str) -> list[ContextLine]:
    zone = ZoneInfo(tz)
    today = now.astimezone(zone).date()
    sources = [
        ("conversation", lambda: _conversation(Path(conversations_dir), chat_id, now, zone) if chat_id else []),
        ("todo", lambda: _todos(vault, today)),
        ("task", lambda: _tasks(vault)),
        ("block", lambda: _blocks(events, today)),
        ("habit", lambda: _habits(vault, today)),
    ]
    raw: list[tuple[str, str]] = []
    for name, read in sources:
        try:
            raw.extend(read())
        except Exception:
            logger.warning("location context: %s unavailable", name, exc_info=True)
    return [ContextLine(f"c{i}", kind, _cut(text)) for i, (kind, text) in enumerate(raw, 1)]
