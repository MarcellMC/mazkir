"""What the parse is shown: this message, this moment, and the day around it.

Spec §5.1. Reads files only: the persisted events, the daily note, the
habits, the conversation. It never uses the reconcile path, because
`GET /events` writes to disk and the fast lane must not change anything by
reading. Every source is optional; a failing one costs context, not the turn.

It is read in two steps. `assemble_fast_context` runs on the event loop
before the agent is dispatched, and snapshots what the agent could change
this turn: the day's blocks, the todos, the conversation, the reply. The
costlier parts the agent cannot meaningfully change, a month of past
durations and the habit list, are added by `complete_fast_context` in the
shadow's own thread, so the reply never waits for them.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import statistics
from dataclasses import dataclass, field, replace
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
    bedtime: dt.time | None = None  # your usual Sleep start, for "woke up at …" with no Sleep open
    skills: tuple[str, ...] = ()    # the router's catalog, one line per skill, for fallthrough_skill


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


def _skill_line(skill) -> str:
    line = f"{skill.name}: {skill.description.strip()}"
    when = " ".join(skill.when_to_use.split())
    return f"{line} Use for: {when}" if when else line


def skills_of(skills_dir: Path) -> tuple[str, ...]:
    """The skill catalog the router reads, one line per skill.

    The parse chooses `fallthrough_skill` from it. With only one-line hints in
    its prompt it chose right 55 % of the time, against the router's 82 %
    with this catalog (2026-09-29 replay).
    """
    from src.services.skill_registry import SkillRegistry
    registry = SkillRegistry(skills_dir=Path(skills_dir))
    registry.load()
    return tuple(_skill_line(s) for s in registry.list())


def typical_minutes(events, before: dt.date, days: int = 30) -> dict[str, int]:
    """Median length per activity name over the `days` days before `before`, for an unknown end.

    Never `before` itself. For a replayed message that day holds blocks
    written after it was sent; live, it is the file the agent may be writing
    while the shadow's thread reads.
    """
    lengths: dict[str, list[float]] = {}
    for k in range(1, days + 1):
        for e in events.get_events((before - dt.timedelta(days=k)).isoformat()):
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


def typical_bedtime(events, before: dt.date, days: int = 30) -> dt.time | None:
    """Your usual Sleep start: the median over the `days` days before `before`.

    Counted in minutes from noon, so 23:30 and 00:30 have midnight between
    them, not noon. None with fewer than three nights.
    """
    from src.services.fast_lane.time_resolver import SLEEP_NAMES
    from_noon: list[int] = []
    for k in range(1, days + 1):
        for e in events.get_events((before - dt.timedelta(days=k)).isoformat()):
            if (e.get("name") or "").strip().lower() not in SLEEP_NAMES or not e.get("start_time"):
                continue
            try:
                start = dt.datetime.fromisoformat(e["start_time"])
            except (ValueError, TypeError):
                continue
            from_noon.append((start.hour * 60 + start.minute - 720) % 1440)
    if len(from_noon) < 3:
        return None
    minutes = (round(statistics.median(from_noon)) + 720) % 1440
    return dt.time(minutes // 60, minutes % 60)


def assemble_fast_context(
    *, text: str, chat_id: int, now: dt.datetime, memory, events, vault,
    reply_to: dict | None = None, selected_date: str | None = None,
    attachments: list[dict] | None = None, places_path: Path | None = None,
    day_boundary_hour: int = 5,
) -> FastContext:
    """Snapshot, before the agent runs, what it could change this turn. Never raises.

    Cheap reads only, because this runs on the event loop: habits and
    typical durations are left empty for `complete_fast_context`.
    """
    reply = reply_to or {}
    return FastContext(
        now=now, chat_id=chat_id, text=text,
        reply_to=reply.get("text"), reply_from=reply.get("from"),
        recent_turns=_safe(lambda: _recent_turns(memory, chat_id), ()),
        blocks=_safe(lambda: _blocks(events, now, day_boundary_hour), ()),
        todos=_safe(lambda: _todos(vault, now), ()),
        places=_safe(lambda: _places(places_path), ()),
        hashtags=extract_hashtags(text),
        selected_date=selected_date,
        has_photo=any(a.get("type") == "photo" for a in attachments or ()),
    )


def complete_fast_context(snapshot: FastContext, *, events, vault, history_days: int = 30,
                          skills_dir: Path | None = None) -> FastContext:
    """The snapshot plus the habit list and the typical durations. Never raises.

    Runs in the shadow's thread, before the parse. Durations come only from
    the days before today, which the agent's writes this turn cannot reach
    in any way that matters. Returns a new context; the snapshot is frozen.
    """
    return replace(
        snapshot,
        habits=_safe(lambda: habits_of(vault), ()),
        typical_minutes=_safe(lambda: typical_minutes(events, snapshot.now.date(), history_days), {}),
        bedtime=_safe(lambda: typical_bedtime(events, snapshot.now.date(), history_days), None),
        skills=_safe(lambda: skills_of(skills_dir), ()) if skills_dir else snapshot.skills,
    )
