"""What the parse is shown: this message, this moment, and the day around it.

Spec §5.1. Reads files only: the persisted events, the daily note, the
habits, the conversation. It never uses the reconcile path, because
`GET /events` writes to disk and the fast lane must not change anything by
reading. Every source is optional; a failing one costs context, not the turn.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.services.daily_tasks import parse_all_todos
from src.services.fast_lane.contract import extract_hashtags

logger = logging.getLogger(__name__)

_MARKERS = ("[Record of your previous reply", "[Tools I called this turn")


def clean_turn_text(text: str) -> str:
    """A turn without the tool records that Ship 3 attaches, or that older replies imitated."""
    cuts = [i for m in _MARKERS if (i := text.find(m)) >= 0]
    return (text[:min(cuts)] if cuts else text).strip()


@dataclass(frozen=True)
class BlockView:
    id: str
    date: str
    name: str
    start: dt.datetime | None
    end: dt.datetime | None

    def line(self) -> str:
        start = self.start.strftime("%m-%d %H:%M") if self.start else "?"
        end = self.end.strftime("%H:%M") if self.end else "open"
        return f"{start}–{end} {self.name}"

    def as_candidate(self) -> dict[str, Any]:
        """The shape `block_resolver.resolve_block` matches against."""
        return {"id": self.id, "name": self.name, "date": self.date,
                "start_time": self.start.isoformat() if self.start else None}


@dataclass(frozen=True)
class HabitView:
    name: str
    aliases: tuple[str, ...] = ()

    def line(self) -> str:
        return f"{self.name} ({', '.join(self.aliases)})" if self.aliases else self.name


@dataclass(frozen=True)
class FastContext:
    now: dt.datetime
    chat_id: int
    text: str
    reply_to: str | None = None
    reply_from: str | None = None
    recent_turns: tuple[tuple[str, str], ...] = ()
    blocks: tuple[BlockView, ...] = ()
    todos: tuple[str, ...] = ()
    habits: tuple[HabitView, ...] = ()
    places: tuple[str, ...] = ()
    hashtags: tuple[str, ...] = ()
    selected_date: str | None = None
    has_photo: bool = False
    typical_minutes: dict[str, int] = field(default_factory=dict)


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        logger.warning("fast lane context source failed", exc_info=True)
        return default


def _parse_ts(value: Any, tz) -> dt.datetime | None:
    if not value:
        return None
    try:
        moment = dt.datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return moment.replace(tzinfo=tz) if moment.tzinfo is None else moment.astimezone(tz)


def _recent_turns(memory, chat_id: int, limit: int = 4) -> tuple[tuple[str, str], ...]:
    messages = memory.load_conversation(chat_id).get("messages", [])
    turns = [(m["role"], clean_turn_text(m["content"])) for m in messages if isinstance(m.get("content"), str)]
    return tuple(turns[-limit:])


def _blocks(events, now: dt.datetime, boundary: int) -> tuple[BlockView, ...]:
    days = [now.date()]
    if now.hour < boundary:
        days.insert(0, now.date() - dt.timedelta(days=1))
    out = []
    for day in days:
        for e in events.get_events(day.isoformat()):
            if e.get("state") == "dismissed":
                continue
            out.append(BlockView(id=str(e.get("id", "")), date=day.isoformat(), name=str(e.get("name") or ""),
                                 start=_parse_ts(e.get("start_time"), now.tzinfo),
                                 end=_parse_ts(e.get("end_time"), now.tzinfo)))
    latest = dt.datetime.max.replace(tzinfo=now.tzinfo)
    return tuple(sorted(out, key=lambda b: b.start or latest))


def _todos(vault, now: dt.datetime) -> tuple[str, ...]:
    note = vault.read_daily_note(now.date().isoformat())
    out = []
    for t in parse_all_todos(note.get("content", "")):
        if t.state == "unchecked":
            if t.scheduled_at:
                out.append(f"{t.scheduled_at} {t.text}")
            else:
                out.append(t.text)
    return tuple(out)


def habits_of(vault) -> tuple[HabitView, ...]:
    out = []
    for habit in vault.list_active_habits():
        meta = habit.get("metadata", {})
        out.append(HabitView(str(meta.get("name", "")), tuple(str(a) for a in meta.get("aliases") or ())))
    return tuple(out)


def _places(path: Path | None) -> tuple[str, ...]:
    if path is None or not path.exists():
        return ()
    names: list[str] = []
    for place in json.loads(path.read_text(encoding="utf-8")).get("places", []):
        names.append(str(place["name"]))
        names += [str(a) for a in place.get("aliases", [])]
    return tuple(names)


def typical_minutes(events, today: dt.date, days: int = 30) -> dict[str, int]:
    """Median length per activity name over the last `days`, for filling in an unknown end."""
    lengths: dict[str, list[float]] = {}
    for k in range(days):
        for e in events.get_events((today - dt.timedelta(days=k)).isoformat()):
            start, end, name = e.get("start_time"), e.get("end_time"), e.get("name")
            if not (start and end and name):
                continue
            try:
                minutes = (dt.datetime.fromisoformat(end) - dt.datetime.fromisoformat(start)).total_seconds() / 60
            except (ValueError, TypeError):
                continue
            if 0 < minutes <= 16 * 60:
                lengths.setdefault(name.strip().lower(), []).append(minutes)
    return {name: round(statistics.median(values)) for name, values in lengths.items()}


def assemble_fast_context(
    *, text: str, chat_id: int, now: dt.datetime, memory, events, vault,
    reply_to: dict | None = None, selected_date: str | None = None,
    attachments: list[dict] | None = None, places_path: Path | None = None,
    day_boundary_hour: int = 5, history_days: int = 30,
) -> FastContext:
    """Snapshot everything the parse needs. Never raises."""
    reply = reply_to or {}
    return FastContext(
        now=now, chat_id=chat_id, text=text,
        reply_to=reply.get("text"), reply_from=reply.get("from"),
        recent_turns=_safe(lambda: _recent_turns(memory, chat_id), ()),
        blocks=_safe(lambda: _blocks(events, now, day_boundary_hour), ()),
        todos=_safe(lambda: _todos(vault, now), ()),
        habits=_safe(lambda: habits_of(vault), ()),
        places=_safe(lambda: _places(places_path), ()),
        hashtags=extract_hashtags(text),
        selected_date=selected_date,
        has_photo=any(a.get("type") == "photo" for a in attachments or ()),
        typical_minutes=_safe(lambda: typical_minutes(events, now.date(), history_days), {}),
    )
