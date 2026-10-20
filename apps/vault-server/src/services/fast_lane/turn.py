"""One message through the fast lane: read, place, match, write, receipt (fast-lane spec §3.1).

What `FAST_LANE_MODE=on` runs for every message, in a worker thread. It
never raises for anything a message can cause: a failed parse is route
"router_fallback" (the router takes the message, never the `mazkir`
fallback), and a failed write is a ✗ line on the receipt.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from opentelemetry import trace

from src.logging_setup import emit_agent_turn
from src.services.fast_lane import act
from src.services.fast_lane.actions import PlanInputs, PlannedLine, plan_turn
from src.services.fast_lane.context import FastContext, complete_fast_context
from src.services.fast_lane.contract import FAST_OPS, ParseResult
from src.services.fast_lane.habits import suggest_habit
from src.services.fast_lane.matching import day_blocks, find_target
from src.services.fast_lane.parse import ParseFailure, parse_message
from src.services.fast_lane.places import load_places
from src.services.fast_lane.receipt import ran_summary, render_receipt
from src.services.fast_lane.shadow import ShadowSettings, resolve_clauses
from src.services.fast_lane.time_resolver import EDIT_OPS

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer("mazkir.fast_lane")


@dataclass
class FastDeps:
    claude: Any
    run_tool: Callable[[str, dict], dict]
    events: Any
    vault: Any
    memory: Any
    actions_dir: Path
    places_path: Path
    suggestions_path: Path
    skills_dir: Path | None          # the skill catalog the parse picks a fallthrough skill from; None: no catalog


@dataclass
class FastTurn:
    route: str                               # fast | mixed | fallthrough | router_fallback
    fallthrough_skill: str | None = None
    turn: dict | None = None                 # the saved record; None when nothing ran
    receipt: dict | None = None
    ran: list[str] = field(default_factory=list)
    lone_other: bool = False                 # one `other` clause: maybe an answer to the last skill
    repeat: bool = False                     # this message_id was already handled


def _safe(fn: Callable[[], Any], default: Any) -> Any:
    try:
        return fn()
    except Exception:
        logger.warning("fast lane step failed; continuing without it", exc_info=True)
        return default


def _near_days(now: dt.datetime) -> list[str]:
    return [(now.date() - dt.timedelta(days=1)).isoformat(), now.date().isoformat()]


def _later_days(now: dt.datetime) -> list[str]:
    return [(now.date() + dt.timedelta(days=k)).isoformat() for k in range(1, 8)]


def _targets(result: ParseResult, ctx: FastContext, events) -> dict[int, dict]:
    """The block each edit clause is about (spec §7.1's order, then the coming week by name)."""
    near = day_blocks(events, _near_days(ctx.now))
    selected = day_blocks(events, [ctx.selected_date]) if ctx.selected_date else []
    later: list[dict] | None = None   # read only when an edit asks for it
    out = {}
    for i, c in enumerate(result.clauses):
        if c.op in EDIT_OPS and c.target:
            if later is None:
                later = day_blocks(events, _later_days(ctx.now))
            block = find_target(c.target, reply_text=ctx.reply_to, selected=selected, today=near,
                                later=later, prefer_open=c.op == "end_block")
            if block is not None:
                out[i] = block
    return out


def _candidate_days(resolutions, now: dt.datetime) -> list[str]:
    """The days whose blocks a record can match: today, yesterday, and each placement's day and the one before."""
    days = {now.date(), now.date() - dt.timedelta(days=1)}
    for r in resolutions:
        p = r.placement if r is not None else None
        for moment in ((p.start, p.end) if p is not None else ()):
            if moment is not None:
                days |= {moment.date(), moment.date() - dt.timedelta(days=1)}
    return sorted(d.isoformat() for d in days)


def _suggestion_lines(records: list[dict], deps: FastDeps, habits: list[dict], now: dt.datetime) -> list[dict]:
    out = []
    for rec in records:
        if rec["kind"] != "block" or rec["status"] != "done" or rec.get("habit"):
            continue
        name = _safe(lambda: suggest_habit(rec["text"], deps.events, habits, now.date(), deps.suggestions_path), None)
        if name:
            out.append({
                "id": len(records) + len(out), "kind": "suggest", "outcome": "proposal", "status": "pending",
                "text": f"Track “{name}” as a habit?", "reason": "", "suggest": name,
                "start": None, "end": None, "end_precision": None, "day": None, "date": None, "event_id": None,
                "calendar_sync": None, "habit": None, "habit_candidate": None, "place_text": None,
                "pending": [], "undo": [],
            })
    return out


NO_RECEIPT = "(the receipt for this message could not be shown)"


def _summary(step: dict) -> dict:
    """The shape `turn_trace` reads: `ok`, else `error.code`."""
    if step["ok"]:
        return {"ok": True}
    return {"ok": False, "error": {"code": step.get("code") or "FAILED", "message": step.get("reason") or ""}}


def _log_turn(ctx: FastContext, deps: FastDeps, lines: list[PlannedLine], records: list[dict],
              assistant_text: str, *, route: str) -> None:
    """Spec §7.6: the turn is part of the agent's memory, as skill `fast-lane`.

    Logged under `ctx.log_text`, the string the agent loop would remember the
    message by, so on a mixed turn this record and the skill's carry the same
    `user_text` and `turn_trace` can fold them into one trace. `route` tells
    the join which kind it is: a `fast` record has its own conversation pair,
    a `mixed` one only ever coalesces with the skill record after it.

    One entry per call that actually ran, with its own outcome; a step after
    a failed one never ran and is not claimed. `records[k].steps[i]` is the
    outcome of `lines[k].steps[i]` (act.run_lines).
    """
    tools = [
        {"name": step.tool, "params": {k: v for k, v in step.params.items() if not k.startswith("_")},
         "confidence": 1.0, "reasoning": "fast lane", "confirmed": True, "result_summary": _summary(ran)}
        for line, rec in zip(lines, records) for step, ran in zip(line.steps, rec.get("steps", []))
    ]
    user_text = ctx.log_text or ctx.text
    if route == "fast":
        # The agent loop's order: the exchange first, then the record. A crash
        # between leaves a pair with no record, which turn_trace absorbs; a
        # `fast` record with no pair is an ordinary record to the join and
        # could attach to an older message with the same words. So a failed
        # save logs no record at all.
        try:
            deps.memory.save_turn(ctx.chat_id, user_text, assistant_text, [])
        except Exception:
            logger.error("fast lane could not save the exchange; its agent-turns record is withheld",
                         exc_info=True, extra={"event_type": "fast_turn", "chat_id": ctx.chat_id})
            return
    emit_agent_turn({
        "chat_id": ctx.chat_id, "skill": "fast-lane", "route": route, "user_text": user_text, "tools": tools,
        "assistant_text": assistant_text, "items_referenced": [], "awaiting_confirmation": False,
        "pending_action_id": None, "prior_action_id": None, "iters": 0, "stop_reason": "fast_lane",
    })


def run_fast_turn(ctx: FastContext, deps: FastDeps, settings: ShadowSettings, *, message_id: int | None = None,
                  on_stage: Callable[[str], None] = lambda _stage: None, parse=None) -> FastTurn:
    parse = parse or parse_message
    repeat = _safe(lambda: act.find_repeat(deps.actions_dir, ctx.chat_id, message_id), None)
    if repeat is not None:
        return FastTurn(route=repeat.get("route") or "fast", fallthrough_skill=repeat.get("fallthrough_skill"),
                        turn=repeat,
                        receipt=_safe(lambda: render_receipt(repeat, ctx.now), None) if repeat.get("lines") else None,
                        repeat=True)
    with _tracer.start_as_current_span("fast.turn") as span:
        started = time.monotonic()
        on_stage("Reading…")
        ctx = complete_fast_context(ctx, events=deps.events, vault=deps.vault, skills_dir=deps.skills_dir)
        try:
            with _tracer.start_as_current_span("fast.parse"):
                result = parse(ctx, deps.claude, model=settings.model, timeout_s=settings.timeout_s)
        except Exception as e:   # ParseFailure, or a bug in the parse: either way nothing has been written
            logger.error("fast lane parse failed; the router takes the message",
                         exc_info=not isinstance(e, ParseFailure),
                         extra={"event_type": "fast_turn", "route": "router_fallback", "error": str(e)})
            span.set_attribute("mazkir.fast.route", "router_fallback")
            return FastTurn(route="router_fallback")
        parse_ms = round((time.monotonic() - started) * 1000)
        route = result.route
        if route == "fast" and ctx.has_attachment:
            # Spec §5.6: the fast lane writes what the caption says, and the
            # message goes on to the agent, the only code that saves a photo
            # or reads a location. As `mixed`, so the record, the agent's
            # memory and a repeat all treat it as the turn it is.
            route = "mixed"
        span.set_attribute("mazkir.fast.route", route)
        if result.fallthrough_skill:
            span.set_attribute("mazkir.fast.fallthrough_skill", result.fallthrough_skill)
        fast_count = sum(1 for c in result.clauses if c.op in FAST_OPS)
        if fast_count == 0:
            lone = len(result.clauses) == 1 and result.clauses[0].op == "other"
            logger.info("fast_turn", extra={"event_type": "fast_turn", "route": "fallthrough",
                                            "clauses": len(result.clauses), "parse_ms": parse_ms})
            return FastTurn(route="fallthrough", fallthrough_skill=result.fallthrough_skill, lone_other=lone)

        on_stage(f"Placing {fast_count} {'thing' if fast_count == 1 else 'things'}…")
        targets = _safe(lambda: _targets(result, ctx, deps.events), {})
        habits = _safe(deps.vault.list_active_habits, [])
        try:
            with _tracer.start_as_current_span("fast.resolve"):
                resolutions = resolve_clauses(result, ctx, settings, targets)
            inputs = PlanInputs(
                now=ctx.now, message_id=message_id, targets=targets, habits=habits,
                candidates=_safe(lambda: day_blocks(deps.events, _candidate_days(resolutions, ctx.now)), []),
                places=_safe(lambda: load_places(deps.places_path), []),
                todos=list(ctx.todos),
            )
            lines = plan_turn(result, resolutions, inputs)
        except Exception as e:   # a bug in placing or planning; nothing has been written yet
            logger.error("fast lane could not place or plan the message; the router takes it", exc_info=True,
                         extra={"event_type": "fast_turn", "route": "router_fallback", "error": str(e)})
            span.set_attribute("mazkir.fast.route", "router_fallback")
            return FastTurn(route="router_fallback")

        on_stage("Writing…")
        records = act.run_lines(lines, run_tool=deps.run_tool, events=deps.events)
        records += _suggestion_lines(records, deps, habits, ctx.now)
        turn_id = act.new_turn_id()
        turn = {"turn_id": turn_id, "chat_id": ctx.chat_id, "message_id": message_id,
                "created_at": ctx.now.isoformat(), "text": ctx.text, "route": route,
                "fallthrough_skill": result.fallthrough_skill, "response": "", "lines": records}
        # Saved before the receipt is rendered: the record is what undo needs, and
        # a receipt bug must not cost the writes above their way back.
        _safe(lambda: (act.save_turn(deps.actions_dir, turn), act.prune(deps.actions_dir)), None)
        receipt = None
        try:
            with _tracer.start_as_current_span("fast.receipt"):
                receipt = render_receipt(turn, ctx.now)
        except Exception:
            logger.error("fast lane receipt failed to render; the turn %s is saved", turn_id, exc_info=True,
                         extra={"event_type": "fast_turn", "turn_id": turn_id})
        assistant_text = receipt["text"] if receipt else NO_RECEIPT
        _safe(lambda: _log_turn(ctx, deps, lines, records, assistant_text, route=route), None)

        outcomes = Counter(rec["outcome"] for rec in records)
        span.set_attribute("mazkir.fast.clauses", len(result.clauses))
        for outcome in ("fact", "plan", "proposal", "question"):
            span.set_attribute(f"mazkir.fast.{outcome}s", outcomes.get(outcome, 0))
        logger.info("fast_turn", extra={"event_type": "fast_turn", "turn_id": turn_id, "route": route,
                                        "clauses": len(result.clauses), "outcomes": dict(outcomes),
                                        "parse_ms": parse_ms})
        return FastTurn(route=route, fallthrough_skill=result.fallthrough_skill, turn=turn,
                        receipt=receipt, ran=_safe(lambda: ran_summary(turn, ctx.now), []))
