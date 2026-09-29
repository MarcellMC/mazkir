"""The parse contract: the schema one Haiku call must fill, and the checks code runs on its answer.

Spec §5. The model says what a message contains, in your own words; nothing
reads a clause until it has passed these checks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any

OPS = ("log_block", "start_block", "end_block", "edit_block", "tick_habit",
       "add_todo", "check_todo", "rollover_todos", "other")
FAST_OPS = frozenset(OPS[:-1])
SKILLS = ("time-management", "knowledge-management", "mazkir", "engineering", "motivation-management")
MAX_CLAUSES = 12
_NEEDS = {"log_block": "name", "start_block": "name", "end_block": "target", "edit_block": "target",
          "tick_habit": "name", "add_todo": "name", "check_todo": "target"}

KNOWLEDGE_TAGS = frozenset({"idea", "green"})
TODO_TAGS = frozenset({"buy"})
ACTIVITY_TAGS = frozenset({"dev", "work", "explore"})
_HASHTAG = re.compile(r"#(\w[\w/-]*)")


class ParseFailure(Exception):
    """The parse failed or answered with something unusable; the router takes the message.

    Spec §5.5 and §10: never the `mazkir` fallback. The shadow logs it as
    route "router_fallback".
    """


@dataclass(frozen=True)
class TimeWords:
    start: str | None = None
    end: str | None = None
    duration: str | None = None
    shift: str | None = None
    day: str | None = None
    after: int | None = None
    with_: int | None = None


@dataclass(frozen=True)
class Clause:
    op: str
    intent: str
    stated: bool
    evidence: str
    name: str | None = None
    target: str | None = None
    tags: tuple[str, ...] = ()
    place: str | None = None
    people: tuple[str, ...] = ()
    project: str | None = None
    time: TimeWords | None = None


@dataclass(frozen=True)
class ParseResult:
    clauses: tuple[Clause, ...]
    fallthrough_skill: str | None
    dropped: tuple[str, ...] = ()   # evidence of clauses the checks removed

    @property
    def route(self) -> str:
        """fast: every clause is a fast-lane op. fallthrough: none is. mixed: some are."""
        if not self.clauses:
            return "fallthrough"
        fast = [c.op in FAST_OPS for c in self.clauses]
        if all(fast):
            return "mixed" if self.dropped else "fast"
        return "fallthrough" if not any(fast) else "mixed"


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


_STR = {"type": "string"}
_INT = {"type": "integer"}
_TIME_KEYS = ("start", "end", "duration", "shift", "day", "after", "with")
_TIME_SCHEMA = {
    "type": "object",
    "properties": {**{k: _nullable(_STR) for k in _TIME_KEYS[:5]},
                   "after": _nullable(_INT), "with": _nullable(_INT)},
    "required": list(_TIME_KEYS),
    "additionalProperties": False,
}
_CLAUSE_SCHEMA = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": list(OPS)},
        "intent": {"type": "string", "enum": ["record", "plan"]},
        "stated": {"type": "boolean"},
        "evidence": _STR,
        "name": _nullable(_STR),
        "target": _nullable(_STR),
        "place": _nullable(_STR),
        "people": {"type": "array", "items": _STR},
        "project": _nullable(_STR),
        "time": _nullable(_TIME_SCHEMA),
    },
    "required": ["op", "intent", "stated", "evidence", "name", "target",
                 "place", "people", "project", "time"],
    "additionalProperties": False,
}
PARSE_SCHEMA = {
    "type": "object",
    "properties": {
        "clauses": {"type": "array", "items": _CLAUSE_SCHEMA},
        "fallthrough_skill": _nullable({"type": "string", "enum": list(SKILLS)}),
    },
    "required": ["clauses", "fallthrough_skill"],
    "additionalProperties": False,
}


def extract_hashtags(text: str | None) -> tuple[str, ...]:
    """Hashtags in order, lowercased; "#explore/watch" also yields "explore"."""
    seen: list[str] = []
    for raw in _HASHTAG.findall(text or ""):
        full = raw.lower().rstrip("/-")
        first = full.split("/")[0].split("-")[0]
        for tag in (full, first):
            if tag and tag not in seen:
                seen.append(tag)
    return tuple(seen)


def _norm(text: str) -> str:
    return " ".join((text or "").casefold().split())


def _link(value: Any, own: int, index: dict[int, int]) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value == own:
        return None
    return index.get(value)


def _clause(item: dict[str, Any], own: int, index: dict[int, int]) -> Clause:
    t = item.get("time")
    time = None
    if isinstance(t, dict):
        time = TimeWords(start=t.get("start"), end=t.get("end"), duration=t.get("duration"),
                         shift=t.get("shift"), day=t.get("day"),
                         after=_link(t.get("after"), own, index), with_=_link(t.get("with"), own, index))
    intent = item.get("intent")
    return Clause(
        op=item["op"], intent=intent if intent in ("record", "plan") else "record",
        stated=bool(item.get("stated")), evidence=str(item["evidence"]),
        name=item.get("name") or None, target=item.get("target") or None,
        place=item.get("place") or None, people=tuple(str(p) for p in item.get("people") or ()),
        project=item.get("project") or None, time=time,
    )


def _apply_hashtags(clauses: list[Clause], skill: str | None) -> tuple[list[Clause], str | None]:
    """Your hashtags are rules, not hints: code wins over the model (spec §5.4).

    A clause's tags are the hashtags in its own words, read here. The model is
    no longer asked for them: asked, it invented tags without end ("query",
    "request", "priorities", …) until it ran out of tokens, on messages as
    short as "3" (22 of 276 parses failed that way in the 2026-09-29 replay).
    """
    out = []
    for c in clauses:
        tags = extract_hashtags(c.evidence)
        c = replace(c, tags=tags)
        if set(tags) & KNOWLEDGE_TAGS:
            if c.op != "other":
                c = replace(c, op="other")
            skill = "knowledge-management"
        elif set(tags) & TODO_TAGS and c.op not in ("add_todo", "check_todo"):
            c = replace(c, op="add_todo", name=c.name or c.evidence)
        out.append(c)
    return out, skill


def validate(raw: dict[str, Any], message: str) -> ParseResult:
    """Turn the model's JSON into clauses that passed every check (spec §5.4).

    Raises ParseFailure when the answer is unusable as a whole: more than
    MAX_CLAUSES clauses sends the message to today's router (spec §5.5, §10).
    """
    items = [i for i in raw.get("clauses") or [] if isinstance(i, dict)]
    skill = raw.get("fallthrough_skill")
    skill = skill if skill in SKILLS else None
    if len(items) > MAX_CLAUSES:
        raise ParseFailure(f"the parse returned {len(items)} clauses, more than {MAX_CLAUSES}")
    body = _norm(message)
    keep: list[int] = []
    dropped: list[str] = []
    for i, item in enumerate(items):
        evidence = str(item.get("evidence") or "")
        op = item.get("op")
        needed = _NEEDS.get(op)
        if op not in OPS or not evidence or _norm(evidence) not in body or (needed and not item.get(needed)):
            dropped.append(evidence)
        else:
            keep.append(i)

    # Cascade: drop clauses with broken links until the kept set stops changing
    while True:
        dropped_this_round = []
        new_keep = []
        dropped_indices = set(range(len(items))) - set(keep)
        for idx in keep:
            item = items[idx]
            t = item.get("time")
            is_broken = False
            if isinstance(t, dict):
                for link_name in ("after", "with"):
                    link_value = t.get(link_name)
                    # Apply same predicate as _link(): bool or non-int is broken, plus checks for valid int
                    if link_value is not None:
                        if isinstance(link_value, bool) or not isinstance(link_value, int):
                            is_broken = True
                            break
                        # Check: self-referential, out-of-range, or links to dropped clause
                        if link_value == idx or link_value < 0 or link_value >= len(items) or link_value in dropped_indices:
                            is_broken = True
                            break
            if is_broken:
                dropped_this_round.append(idx)
                dropped.append(str(item.get("evidence") or ""))
            else:
                new_keep.append(idx)

        if not dropped_this_round:
            break
        keep = new_keep

    index = {old: new for new, old in enumerate(keep)}
    clauses = [_clause(items[old], old, index) for old in keep]
    clauses, skill = _apply_hashtags(clauses, skill)
    return ParseResult(tuple(clauses), skill, tuple(dropped))
