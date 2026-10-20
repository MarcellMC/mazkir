"""What a record does to the blocks already in the ledger (fast-lane spec §7.1).

Pure. The blocks come in as event dicts, each carrying the `date` of the file
it came from; the decision comes out as a `Match`. Nothing here writes: the
planner (`actions.py`) turns a `Match` into tool calls.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any, Iterable

from src.services.block_resolver import resolve_block

SAME_PLAN_WINDOW = dt.timedelta(hours=2)
OVERLAP_SHARE = 0.5
SLEEP_WORDS = frozenset({"sleep", "sleeping", "nap", "сон", "שינה"})


@dataclass(frozen=True)
class Match:
    kind: str                     # create | close | confirm | update | also_close_other | sleep | move
    block: dict | None = None     # the ledger block it acts on


def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().casefold())


_ARTICLE = re.compile(r"^(?:the|my|that|this|a|an)\s+", re.IGNORECASE)


def _bare(reference: str) -> str:
    """"the gym" → "gym": block_resolver scores the article too, 40 for "the gym" against "Gym"."""
    return _ARTICLE.sub("", str(reference or "").strip())


def day_blocks(events, dates: Iterable[str]) -> list[dict[str, Any]]:
    """Every live block on `dates`, each tagged with the date of its file."""
    out = []
    for date in dict.fromkeys(d for d in dates if d):
        for e in events.get_events(date):
            if e.get("state") != "dismissed":
                out.append({**e, "date": date})
    return out


def instant(value: str | None, tz) -> dt.datetime | None:
    """A ledger timestamp (local wall clock) as an aware instant, or None."""
    if not value:
        return None
    try:
        moment = dt.datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return moment.replace(tzinfo=tz) if moment.tzinfo is None else moment.astimezone(tz)


NAMED = 95   # block_resolver's score for an exact or contained name


def find_target(reference: str, *, reply_text: str | None, selected: list[dict],
                today: list[dict], later: list[dict] = (), prefer_open: bool = False) -> dict | None:
    """The block an edit is about: the replied-to message, the day open in /day, today, then the coming days.

    `prefer_open` (an end) tries each tier's open blocks first: "got back"
    closes the walk still running, not one that ended this morning. The
    coming days (`later`, e.g. a trip planned for the weekend) are reached
    only by an exact or contained name. None when no tier names exactly one
    block; the caller asks "which block?".
    """
    def pick(tier: list[dict], least: float = 0) -> dict | None:
        pools = [[b for b in tier if not b.get("end_time")], tier] if prefer_open else [tier]
        for pool in pools:
            if pool:
                found = resolve_block(_bare(reference), pool)
                if found.get("ok") and found["data"].get("score", 100) >= least:
                    return next(b for b in pool if b["id"] == found["data"]["id"])
        return None

    if reply_text:
        pool = list({b["id"]: b for b in [*selected, *today]}.values())
        named = [b for b in pool if b.get("name") and _norm(b["name"]) in _norm(reply_text)]
        if len(named) == 1:
            return named[0]
        if named and (block := pick(named)) is not None:
            return block
    for tier in (selected, today):
        if tier and (block := pick(tier)) is not None:
            return block
    return pick(list(later), NAMED) if later else None


def same_activity(name: str | None, tags, block: dict) -> bool:
    if name and resolve_block(_bare(name), [block]).get("ok"):
        return True
    activity = _norm(block.get("activity"))
    return bool(activity) and activity in {_norm(t) for t in tags or ()}


def _is_plan(block: dict) -> bool:
    """Intent rather than evidence: a plan, Mazkir's proposal, or a calendar entry nobody has confirmed."""
    if block.get("state") == "approved":
        return False
    return block.get("intent") == "plan" or block.get("proposed") is True or block.get("source") == "calendar"


def _is_sleep(block: dict) -> bool:
    return _norm(block.get("name")) in SLEEP_WORDS or _norm(block.get("activity")) in SLEEP_WORDS


def _share(block: dict, start, end, tz) -> float:
    """How much of the shorter interval the two share, 0..1; 0 when either is open."""
    bs, be = instant(block.get("start_time"), tz), instant(block.get("end_time"), tz)
    if None in (bs, be, start, end):
        return 0.0
    overlap = (min(be, end) - max(bs, start)).total_seconds()
    shortest = min((be - bs).total_seconds(), (end - start).total_seconds())
    return overlap / shortest if overlap > 0 and shortest > 0 else 0.0


def match_record(name: str | None, tags, start: dt.datetime | None, end: dt.datetime | None,
                 candidates: list[dict], tz, intent: str = "record") -> Match:
    """Spec §7.1, in order: close, confirm, update, Sleep, close-the-other, create.

    A plan only moves a plan or proposal of its activity within ±2 h, so it
    never adds a second one (revised 2026-10-03); it touches no record.
    """
    blocks = [b for b in candidates if b.get("state") != "dismissed"]
    same = [b for b in blocks if same_activity(name, tags, b)]
    if intent == "plan":
        if start is not None:
            for b in same:
                bs = instant(b.get("start_time"), tz)
                if _is_plan(b) and bs is not None and abs(bs - start) <= SAME_PLAN_WINDOW:
                    return Match("move", b)
        return Match("create")
    moment = start or end
    if end is not None:
        for b in same:
            bs = instant(b.get("start_time"), tz)
            if b.get("end_time") is None and bs is not None and bs <= moment:
                return Match("close", b)
    if start is not None:
        for b in same:
            bs = instant(b.get("start_time"), tz)
            if _is_plan(b) and bs is not None and abs(bs - start) <= SAME_PLAN_WINDOW:
                return Match("confirm", b)
    for b in same:
        if not _is_plan(b) and _share(b, start, end, tz) >= OVERLAP_SHARE:
            return Match("update", b)
    for b in blocks:
        if b not in same and _is_sleep(b) and _share(b, start, end, tz) > 0:
            return Match("sleep", b)
    if start is not None:
        for b in blocks:
            bs = instant(b.get("start_time"), tz)
            if b not in same and b.get("end_time") is None and bs is not None and bs < start:
                return Match("also_close_other", b)
    return Match("create")
