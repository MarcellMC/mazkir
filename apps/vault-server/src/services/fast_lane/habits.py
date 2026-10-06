"""Which habit a block is, and ticking it at the block's own time (fast-lane spec §7.2).

The ledger showed why this exists: 12 of 16 dog walks and every gym block
were logged and never ticked, 165 tokens unpaid. A block that *is* a habit
now ticks it, once, stamped when the block ended, so a walk logged after
midnight counts for the evening it happened.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from rapidfuzz import fuzz

from src.config import settings
from src.services.habit_completion import complete_habit

FUZZY_FLOOR = 85.0
SUGGEST_MIN_DAYS = 3
SUGGEST_WINDOW_DAYS = 14
SHOWN_QUIET = dt.timedelta(days=30)      # spec: at most once a month per activity
DECLINED_QUIET = dt.timedelta(days=90)   # "not now" is remembered for a season, not forever
_COMPLETION_KEYS = ("path", "name", "completed_at", "prior", "completions_today",
                    "daily_target", "tokens_earned", "new_streak", "longest_streak")


@dataclass(frozen=True)
class HabitMatch:
    path: str
    name: str
    kind: str          # "exact" | "alias" | "fuzzy"


def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().casefold())


def match_habit(activity: str | None, tags, habits: list[dict]) -> HabitMatch | None:
    """The habit an activity is: by name, then by alias, then fuzzily (for a tap, never a tick)."""
    wanted = {_norm(activity), *(_norm(t) for t in tags or ())} - {""}
    if not wanted:
        return None
    for h in habits:
        meta = h.get("metadata", {})
        if _norm(meta.get("name")) in wanted:
            return HabitMatch(h["path"], str(meta.get("name", "")), "exact")
    for h in habits:
        meta = h.get("metadata", {})
        if {_norm(a) for a in meta.get("aliases") or ()} & wanted:
            return HabitMatch(h["path"], str(meta.get("name", "")), "alias")
    best, score = None, 0.0
    for h in habits:
        meta = h.get("metadata", {})
        for label in (meta.get("name"), *(meta.get("aliases") or ())):
            if activity and label:
                s = fuzz.token_set_ratio(_norm(activity), _norm(label))
                if s > score:
                    best, score = h, s
    if best is not None and score >= FUZZY_FLOOR:
        return HabitMatch(best["path"], str(best["metadata"].get("name", "")), "fuzzy")
    return None


def _event(events, date_str: str, event_id: str) -> dict | None:
    return next((e for e in events.get_events(date_str) if e.get("id") == event_id), None)


def tick_block_habit(vault, events, date_str: str, event_id: str, match: HabitMatch) -> dict | None:
    """Tick `match` for one block, stamped at the block's end, and record it on the block.

    A block ticks at most once: one already carrying `habit_completion` is
    left alone. Returns the completion recorded, or None when nothing was
    ticked (already ticked, or the day's target already met).
    """
    event = _event(events, date_str, event_id)
    if event is None or event.get("habit_completion"):
        return None
    stamp = event.get("end_time") or event.get("start_time")
    if not stamp:
        return None
    at = dt.datetime.fromisoformat(stamp).replace(tzinfo=ZoneInfo(settings.vault_timezone))
    outcome = complete_habit(vault, match.path, now=at)
    if outcome.get("already_completed"):
        return None
    completion = {k: outcome[k] for k in _COMPLETION_KEYS}
    events.update_event(date=date_str, event_id=event_id, updates={"habit_completion": completion})
    return completion


def tick_if_habit(vault, events, date_str: str, event_id: str, now: dt.datetime | None = None) -> dict | None:
    """The hook's rule: a confirmed block that has happened ticks its habit on an exact or alias match."""
    from src.services.approval import has_begun, resolve_state, source_systems

    now = now or dt.datetime.now(ZoneInfo(settings.vault_timezone)).replace(tzinfo=None)
    event = _event(events, date_str, event_id)
    if event is None or event.get("habit_completion") or "habit" in source_systems(event):
        return None
    confirmed = event.get("state") == "approved"
    if (event.get("proposed") or event.get("intent") == "plan") and not confirmed:
        return None
    if resolve_state(event, now) != "approved" or not has_begun(event, now):
        return None
    tags = [event["activity"]] if event.get("activity") else []
    match = match_habit(event.get("name"), tags, vault.list_active_habits())
    if match is None or match.kind == "fuzzy":
        return None
    return tick_block_habit(vault, events, date_str, event_id, match)


def _load(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(path: Path, data: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _quiet(store: dict, key: str, today: dt.date) -> bool:
    for bucket, span in (("shown", SHOWN_QUIET), ("declined", DECLINED_QUIET)):
        when = store.get(bucket, {}).get(key)
        if when and today - dt.date.fromisoformat(when) < span:
            return True
    return False


def suggest_habit(name: str | None, events, habits: list[dict], today: dt.date, store_path: Path) -> str | None:
    """An activity on 3+ distinct days in 14 that is no habit yet: offer to track it, at most monthly."""
    if not name or match_habit(name, (), habits) is not None:
        return None
    key = _norm(name)
    days = {k for k in range(SUGGEST_WINDOW_DAYS)
            if any(_norm(e.get("name")) == key
                   for e in events.get_events((today - dt.timedelta(days=k)).isoformat()))}
    if len(days) < SUGGEST_MIN_DAYS:
        return None
    store = _load(store_path)
    if _quiet(store, key, today):
        return None
    store.setdefault("shown", {})[key] = today.isoformat()
    _save(store_path, store)
    return name


def decline_suggestion(name: str, today: dt.date, store_path: Path) -> None:
    store = _load(store_path)
    store.setdefault("declined", {})[_norm(name)] = today.isoformat()
    _save(store_path, store)
