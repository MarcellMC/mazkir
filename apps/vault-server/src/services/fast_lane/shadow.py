"""Piece A1: run the fast lane beside the normal path, write nothing, log what it would do.

Spec §11.3, step 1. Each message in shadow mode is parsed and resolved, and
one line goes to data/logs/fast-lane-shadow.jsonl describing the receipt the
fast lane would have sent. The normal path is untouched and never waits.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from opentelemetry import trace

from src.logging_setup import emit_fast_lane
from src.services.block_resolver import resolve_block
from src.services.fast_lane.context import FastContext
from src.services.fast_lane.contract import FAST_OPS, Clause, ParseResult
from src.services.fast_lane.parse import ParseFailure, parse_message
from src.services.fast_lane.time_resolver import (
    ClauseResolution, ClauseTime, Placement, ResolverContext, resolve,
)

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer("mazkir.fast_lane")
_OUTCOMES = ("fact", "plan", "proposal", "question")


@dataclass(frozen=True)
class ShadowSettings:
    model: str
    timeout_s: float
    day_boundary_hour: int = 5
    default_minutes: int = 30


def _clause_time(c: Clause, candidates: list[dict], by_id: dict) -> ClauseTime:
    t = c.time
    target_start = target_end = None
    if c.op in ("end_block", "edit_block") and c.target and candidates:
        found = resolve_block(c.target, candidates)
        if found.get("ok"):
            block = by_id.get(found["data"]["id"])
            if block is not None:
                target_start, target_end = block.start, block.end
    return ClauseTime(
        op=c.op if c.op in FAST_OPS else "other", intent=c.intent, stated=c.stated, name=c.name,
        start=t.start if t else None, end=t.end if t else None, duration=t.duration if t else None,
        shift=t.shift if t else None, day=t.day if t else None,
        after=t.after if t else None, with_=t.with_ if t else None,
        target_start=target_start, target_end=target_end,
    )


def resolve_clauses(result: ParseResult, ctx: FastContext, settings: ShadowSettings) -> list[ClauseResolution | None]:
    """The resolver's answer for each fast clause; None for clauses that fall through."""
    candidates = [b.as_candidate() for b in ctx.blocks]
    by_id = {b.id: b for b in ctx.blocks}
    times = [_clause_time(c, candidates, by_id) for c in result.clauses]
    rctx = ResolverContext(now=ctx.now, day_boundary_hour=settings.day_boundary_hour,
                           typical_minutes=dict(ctx.typical_minutes), default_minutes=settings.default_minutes)
    resolved = resolve(times, rctx)
    return [r if c.op in FAST_OPS else None for c, r in zip(result.clauses, resolved)]


def _placement(p: Placement | None) -> dict[str, Any]:
    if p is None:
        return {}
    return {
        "start": p.start.isoformat() if p.start else None,
        "end": p.end.isoformat() if p.end else None,
        "start_precision": p.start_precision,
        "end_precision": p.end_precision,
        "logical_date": p.logical_date.isoformat() if p.logical_date else None,
    }


def _describe(c: Clause, r: ClauseResolution | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "op": c.op, "intent": c.intent, "stated": c.stated, "name": c.name, "evidence": c.evidence,
        "target": c.target, "place": c.place, "people": list(c.people), "project": c.project,
        "tags": list(c.tags),
    }
    if r is not None:
        out["outcome"] = r.outcome
        out["reason"] = r.reason
        out.update(_placement(r.placement))
        if r.alternatives:
            out["alternatives"] = [_placement(p) for p in r.alternatives]
    return out


def _ms(since: float) -> int:
    return round((time.monotonic() - since) * 1000)


def _run(ctx: FastContext, claude, settings: ShadowSettings, parse) -> dict[str, Any]:
    started = time.monotonic()
    try:
        with _tracer.start_as_current_span("fast.parse"):
            result = parse(ctx, claude, model=settings.model, timeout_s=settings.timeout_s)
    except ParseFailure as e:
        return {"route": "router_fallback", "error": str(e), "parse_ms": _ms(started)}
    parse_ms = _ms(started)
    resolving = time.monotonic()
    with _tracer.start_as_current_span("fast.resolve"):
        resolutions = resolve_clauses(result, ctx, settings)
    return {
        "route": result.route,
        "fallthrough_skill": result.fallthrough_skill,
        "dropped": list(result.dropped),
        "parse_ms": parse_ms,
        "resolve_ms": _ms(resolving),
        "clauses": [_describe(c, r) for c, r in zip(result.clauses, resolutions)],
    }


def run_shadow(ctx: FastContext, claude, settings: ShadowSettings, parse=parse_message) -> dict[str, Any]:
    """Parse and resolve one message; return and log the would-be receipt. Never raises."""
    record: dict[str, Any] = {"event": "fast_shadow", "chat_id": ctx.chat_id, "text": ctx.text,
                              "now": ctx.now.isoformat()}
    try:
        with _tracer.start_as_current_span("fast.shadow") as span:
            record.update(_run(ctx, claude, settings, parse))
            clauses = record.get("clauses", [])
            span.set_attribute("mazkir.fast.route", record["route"])
            span.set_attribute("mazkir.fast.clauses", len(clauses))
            for outcome in _OUTCOMES:
                span.set_attribute(f"mazkir.fast.{outcome}s",
                                   sum(1 for c in clauses if c.get("outcome") == outcome))
            if record.get("fallthrough_skill"):
                span.set_attribute("mazkir.fast.fallthrough_skill", record["fallthrough_skill"])
    except Exception as e:  # the shadow must never cost the real turn anything
        logger.warning("fast lane shadow failed", exc_info=True)
        record.update({"route": "error", "error": repr(e)})
    try:
        emit_fast_lane(record)
    except Exception:  # the shadow must never cost the real turn anything
        logger.warning("fast lane log write failed", exc_info=True)
    return record
