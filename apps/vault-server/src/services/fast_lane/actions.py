"""Turn a message's clauses into the tool calls that carry them out (fast-lane spec §7).

Pure: the parse's clauses, the resolver's placements, the day's blocks,
habits and places go in; `PlannedLine`s come out. A line names the calls to
run now, the ones to run if you tap ✓, or the question it asks.
Nothing here writes, and nothing the model said becomes a timestamp or an
id: times are the resolver's and ids are the ledger's (spec §1.3).
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field, replace
from typing import Any

from rapidfuzz import fuzz

from src.services.fast_lane.contract import ACTIVITY_TAGS, FAST_OPS, Clause, ParseResult
from src.services.fast_lane.habits import match_habit
from src.services.fast_lane.matching import instant, match_record
from src.services.fast_lane.places import Place, match_place
from src.services.fast_lane.time_resolver import (
    BLOCK_OPS, EDIT_OPS, ClauseResolution, Placement, to_wire,
)

STATED = frozenset({"exact", "approx"})   # ends the message wrote, not ones the resolver filled in
TODO_MATCH = 85                            # token_sort_ratio for the todo hook (spec §7.3)


@dataclass(frozen=True)
class Step:
    tool: str
    params: dict[str, Any]


@dataclass(frozen=True)
class PlannedLine:
    kind: str                     # block | edit | todo | habit | rollover | propose | question
    outcome: str                  # fact | plan | proposal | question
    text: str
    steps: tuple[Step, ...] = ()                    # run now
    pending: tuple[Step, ...] = ()                  # run on ✓
    placement: Placement | None = None
    reason: str = ""
    habit_candidate: dict | None = None             # a fuzzy habit match, confirmed by a tap
    place_text: str | None = None                   # a place not in places.json yet


@dataclass(frozen=True)
class PlanInputs:
    """What a turn is planned against.

    `candidates` must already be bounded to the days the turn's placements
    touch (`matching.day_blocks` over their logical dates): `match_record`
    has no age bound on `close` or `also_close_other`, so a block left open
    days ago would otherwise be closed, or offered for closing, by a record
    made today. A start-only record beside an open block of the same
    activity is created, not merged: `close` needs an end.
    """

    now: dt.datetime
    message_id: int | None
    candidates: list[dict] = field(default_factory=list)   # blocks on the days in play, each with "date"
    targets: dict[int, dict] = field(default_factory=dict)  # clause index → the block an edit is about
    habits: list[dict] = field(default_factory=list)
    places: list[Place] = field(default_factory=list)
    todos: list[str] = field(default_factory=list)   # today's open todos; a scheduled one starts with its time


def _wire(moment: dt.datetime | None) -> str | None:
    return to_wire(moment) if moment is not None else None


def _fields(c: Clause, p: Placement, inputs: PlanInputs, place: Place | None) -> dict[str, Any]:
    return {
        "intent": c.intent,
        "start_precision": p.start_precision, "end_precision": p.end_precision,
        "logical_date": p.logical_date.isoformat() if p.logical_date else None,
        "place_id": place.id if place else None,
        "place_text": c.place if c.place and place is None else None,
        "project": c.project,
        "evidence": {"text": c.evidence, "message_id": inputs.message_id},
        "tags": list(c.tags) or None,   # #green is the owner's reserved tag, kept for his analysis
    }


def _create(c: Clause, p: Placement, inputs: PlanInputs, *, proposed: bool = False) -> Step:
    place = match_place(c.place, inputs.places)
    start, end = _wire(p.start), _wire(p.end)
    params: dict[str, Any] = {
        "name": c.name or c.evidence, "date": (start or end)[:10],
        "_fast": {"defer_calendar_sync": True, "fields": _fields(c, p, inputs, place)},
    }
    if start:
        params["start_time"] = start
    if end:
        params["end_time"] = end
    if proposed:
        params["proposed"] = True
    activity = next((t for t in c.tags if t in ACTIVITY_TAGS), None)
    if activity:
        params["activity"] = activity
    links = [*c.people, *([c.project] if c.project else [])]
    if links:
        params["wikilinks"] = links
    if place:
        params["location"] = {"name": place.name}
    return Step("create_event", params)


def _update(block: dict, *, start: str | None = None, end: str | None = None, name: str | None = None,
            fields: dict | None = None, state: str | None = None) -> Step:
    """An `update_event` carrying only what differs from the block as it is now."""
    params: dict[str, Any] = {"event_id": block["id"], "date": block["date"],
                              "_fast": {"defer_calendar_sync": True, "fields": fields or {}}}
    if start and start != block.get("start_time"):
        params["start_time"] = start
    if end and end != block.get("end_time"):
        params["end_time"] = end
    if name and name != block.get("name"):
        params["name"] = name
    if state:
        params["_fast"]["state"] = state
    return Step("update_event", params)


def _open_todo(name: str, todos: list[str]) -> str | None:
    """The open todo a record of `name` finishes, when one clearly does (spec §7.3, the todo hook).

    token_sort_ratio, not token_set_ratio: "Gym" is a subset of "Renew the
    gym membership", which token_set_ratio scores 100.
    """
    best, best_score = None, 0.0
    for todo in todos:
        text = re.sub(r"^\d{1,2}:\d{2}\s+", "", todo)
        score = fuzz.token_sort_ratio(name.casefold(), text.casefold())
        if score > best_score:
            best, best_score = text, score
    return best if best_score >= TODO_MATCH else None


def _crossing_out(line: PlannedLine, name: str, inputs: PlanInputs) -> PlannedLine:
    """A record that finishes an open todo crosses it out in the same line, so undo reverses both."""
    todo = _open_todo(name, inputs.todos)
    if todo is None:
        return line
    step = Step("daily_check_todo", {"text": todo, "date": inputs.now.date().isoformat()})
    return replace(line, steps=line.steps + (step,))


def _block(c: Clause, r: ClauseResolution, inputs: PlanInputs) -> list[PlannedLine]:
    name = c.name or c.evidence
    if r.outcome == "question":
        return [PlannedLine("question", "question", name, reason=r.reason or "no time given")]
    p = r.placement
    known_place = match_place(c.place, inputs.places)
    common: dict[str, Any] = {"placement": p, "place_text": c.place if c.place and known_place is None else None}
    habit = match_habit(name, c.tags, inputs.habits)
    candidate = {"path": habit.path, "name": habit.name} if habit and habit.kind == "fuzzy" else None
    if r.outcome == "proposal":
        return [PlannedLine("block", "proposal", name, steps=(_create(c, p, inputs, proposed=True),),
                            reason=r.reason, **common)]
    tz = inputs.now.tzinfo
    precision = {"start_precision": p.start_precision, "end_precision": p.end_precision}
    if r.outcome == "plan":
        # A plan moves a plan or proposal of its activity within ±2 h rather than
        # adding a second (§7.1, revised 2026-10-03); a proposal it moves is approved.
        m = match_record(name, c.tags, p.start, p.end, inputs.candidates, tz, intent="plan")
        if m.kind == "move":
            step = _update(m.block, start=_wire(p.start), end=_wire(p.end),
                           fields={"intent": "plan", **precision},
                           state="approved" if m.block.get("proposed") else None)
            return [PlannedLine("edit", "plan", m.block.get("name") or name, steps=(step,), **common)]
        return [PlannedLine("block", "plan", name, steps=(_create(c, p, inputs),), **common)]
    m = match_record(name, c.tags, p.start, p.end, inputs.candidates, tz)
    if m.kind == "close":
        opened = instant(m.block.get("start_time"), tz)
        earlier = p.start is not None and opened is not None and p.start < opened
        step = _update(m.block, start=_wire(p.start) if earlier else None, end=_wire(p.end),
                       fields=precision if earlier else {"end_precision": p.end_precision})
        return [_crossing_out(PlannedLine("edit", "fact", m.block.get("name") or name, steps=(step,),
                                          habit_candidate=candidate, **common), name, inputs)]
    if m.kind == "confirm":
        step = _update(m.block, start=_wire(p.start), end=_wire(p.end),
                       fields={"intent": "record", **precision}, state="approved")
        return [_crossing_out(PlannedLine("edit", "fact", m.block.get("name") or name, steps=(step,),
                                          habit_candidate=candidate, **common), name, inputs)]
    if m.kind == "update":
        # Only the ends this record states: an assumed or inferred end never
        # overwrites one the block already has (§7.1, revised 2026-10-03).
        start = _wire(p.start) if p.start_precision in STATED or not m.block.get("start_time") else None
        end = _wire(p.end) if p.end_precision in STATED or not m.block.get("end_time") else None
        fields = {k: v for k, v, kept in (("start_precision", p.start_precision, start),
                                          ("end_precision", p.end_precision, end)) if kept}
        step = _update(m.block, start=start, end=end, fields=fields)
        return [_crossing_out(PlannedLine("edit", "fact", m.block.get("name") or name, steps=(step,),
                                          habit_candidate=candidate, **common), name, inputs)]
    if m.kind == "sleep":
        return [PlannedLine("block", "proposal", name, steps=(_create(c, p, inputs, proposed=True),),
                            reason=f"overlaps {m.block.get('name') or 'Sleep'}", **common)]
    lines = [_crossing_out(PlannedLine("block", "fact", name, steps=(_create(c, p, inputs),),
                                       habit_candidate=candidate, **common), name, inputs)]
    if m.kind == "also_close_other" and p.start is not None:
        at = _wire(p.start)
        lines.append(PlannedLine(
            "propose", "proposal", f"End {m.block.get('name')} at {at[11:16]}?",
            pending=(_update(m.block, end=at, fields={"end_precision": "inferred"}),), reason="still open",
        ))
    return lines


def _edit(i: int, c: Clause, r: ClauseResolution, inputs: PlanInputs) -> list[PlannedLine]:
    label = c.target or c.name or c.evidence
    target = inputs.targets.get(i)
    if target is None and c.op == "end_block" and r.placement is not None:
        # Nothing open to end: the resolver placed it as a new block ending then (§6.2 rule 9).
        return _block(replace(c, op="log_block", name=c.name or c.target), r, inputs)
    if target is None:
        reason = r.reason if r.outcome == "question" and r.reason else "which block?"
        return [PlannedLine("question", "question", label, reason=reason)]
    if r.outcome == "question":
        return [PlannedLine("question", "question", target.get("name") or label, reason=r.reason)]
    p = r.placement
    fields = {}
    if p is not None:
        fields = {k: v for k, v in (("start_precision", p.start_precision), ("end_precision", p.end_precision)) if v}
    new_name = c.name if c.op == "edit_block" and c.name else None
    step = _update(target, start=_wire(p.start) if p else None, end=_wire(p.end) if p else None,
                   name=new_name, fields=fields)
    text = new_name or target.get("name") or label
    if r.outcome == "proposal":
        return [PlannedLine("propose", "proposal", text, pending=(step,), placement=p, reason=r.reason)]
    outcome = "plan" if r.outcome == "plan" else "fact"
    return [PlannedLine("edit", outcome, text, steps=(step,), placement=p)]


def _habit(c: Clause, r: ClauseResolution, inputs: PlanInputs) -> list[PlannedLine]:
    """A habit done with no clock time (spec §7.2).

    Exact or alias: ticked. Fuzzy: one tap, never a tick (`match_habit`). No
    match: a question, writing nothing; handing the raw words to
    `complete_habit` would let its own looser lookup tick a habit the matcher
    rejected.
    """
    name = c.name or c.evidence
    match = match_habit(name, c.tags, inputs.habits)
    if match is None:
        return [PlannedLine("question", "question", name, reason="no habit by that name")]
    step = Step("complete_habit", {"habit_name": match.name})
    if match.kind == "fuzzy":
        return [PlannedLine("propose", "proposal", match.name, pending=(step,), reason=f"did you mean {match.name}?",
                            habit_candidate={"path": match.path, "name": match.name})]
    if r.outcome == "proposal":
        return [PlannedLine("propose", "proposal", match.name, pending=(step,),
                            reason=r.reason or "mentioned in passing")]
    return [PlannedLine("habit", "fact", match.name, steps=(step,))]


def _todo_text(c: Clause, inputs: PlanInputs) -> str:
    text = c.name or c.evidence
    # extract_hashtags yields "#dev-session" as both "dev-session" and "dev": keep the full tag once.
    tags = [t for t in dict.fromkeys(c.tags)
            if not any(o != t and (o.startswith(t + "-") or o.startswith(t + "/")) for o in c.tags)]
    if tags:
        text += " " + " ".join(f"#{t}" for t in tags)
    if c.place:
        place = match_place(c.place, inputs.places)
        text += f" @ {place.name if place else c.place}"
    return text


def _todo(c: Clause, r: ClauseResolution, inputs: PlanInputs) -> list[PlannedLine]:
    p = r.placement
    if c.op == "rollover_todos":
        # To the clause's day (today by default), from today when that lies ahead,
        # else from yesterday; a target moves only that todo (§7.3, revised).
        today = inputs.now.date()
        to = p.logical_date if p is not None and p.logical_date else today
        source = today if to > today else today - dt.timedelta(days=1)
        params = {"from_date": source.isoformat(), "to_date": to.isoformat()}
        if c.target:
            params["text"] = c.target
        text = f"Moved “{c.target}” to {to.isoformat()}" if c.target else f"Rolled over {source.isoformat()}'s todos"
        return [PlannedLine("rollover", "fact", text, steps=(Step("daily_rollover", params),))]
    day = (p.logical_date if p is not None and p.logical_date else inputs.now.date()).isoformat()
    if c.op == "check_todo":
        text = c.target or c.name or c.evidence
        step = Step("daily_check_todo", {"text": text, "date": day})
    else:
        text = _todo_text(c, inputs)
        step = Step("daily_add_task", {"text": text, "date": day})
    if r.outcome == "proposal":
        return [PlannedLine("propose", "proposal", text, pending=(step,), placement=p,
                            reason=r.reason or "mentioned in passing")]
    return [PlannedLine("todo", "fact", text, steps=(step,), placement=p)]


def plan_turn(result: ParseResult, resolutions: list[ClauseResolution | None],
              inputs: PlanInputs) -> list[PlannedLine]:
    """One or more lines per fast clause, in message order; `other` clauses are left to the skill."""
    lines: list[PlannedLine] = []
    for i, (c, r) in enumerate(zip(result.clauses, resolutions)):
        if c.op not in FAST_OPS or r is None:
            continue
        if c.op in BLOCK_OPS:
            lines += _block(c, r, inputs)
        elif c.op in EDIT_OPS:
            lines += _edit(i, c, r, inputs)
        elif c.op == "tick_habit":
            lines += _habit(c, r, inputs)
        else:
            lines += _todo(c, r, inputs)
    return lines
