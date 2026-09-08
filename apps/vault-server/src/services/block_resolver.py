"""Resolve a spoken reference — "the gym block" — to one event.

Mirrors `services/resolver.py`'s ladder and its `SCORE_AMBIGUOUS_DELTA`
deliberately. Two resolvers that disagree about what counts as ambiguous
are two behaviours the user has to learn, and the difference would show up
only in the rare case where being consistent matters most.

Candidates are event dicts that additionally carry a `date` key naming the
day file they came from. The caller supplies it, because an event dict on
its own does not know which day's reconciliation produced it — and a
candidate list spanning two days is the normal case here (§5 of the spec).
"""

from __future__ import annotations

from typing import Any

from rapidfuzz import fuzz

from src.services.tool_response import ErrorCode, err, ok

SCORE_AMBIGUOUS_DELTA = 10.0
SCORE_FLOOR = 60.0


def _summary(candidate: dict[str, Any], score: float) -> dict[str, Any]:
    return {
        "id": candidate.get("id", ""),
        "name": candidate.get("name", ""),
        "date": candidate.get("date", ""),
        "start_time": candidate.get("start_time"),
        "score": score,
    }


def resolve_block(reference: str, candidates: list[dict[str, Any]]) -> dict:
    """Resolve `reference` to a unique block among `candidates`."""
    if not candidates:
        return err(ErrorCode.PATH_NOT_FOUND, "No blocks available to match against")

    for candidate in candidates:
        if candidate.get("id") == reference:
            return ok(_summary(candidate, 100.0))

    for candidate in candidates:
        if candidate.get("name") == reference:
            return ok(_summary(candidate, 100.0))

    lowered = reference.lower()
    substring_hits = [
        c for c in candidates if lowered in (c.get("name") or "").lower()
    ]
    if len(substring_hits) == 1:
        return ok(_summary(substring_hits[0], 95.0))
    if len(substring_hits) > 1:
        return err(
            ErrorCode.AMBIGUOUS_MATCH,
            f"Several blocks match '{reference}'",
            details={
                "query": reference,
                "candidates": [_summary(c, 95.0) for c in substring_hits[:5]],
            },
        )

    ranked = sorted(
        (_summary(c, float(fuzz.token_set_ratio(reference, c.get("name") or "")))
         for c in candidates),
        key=lambda r: r["score"],
        reverse=True,
    )

    if ranked[0]["score"] < SCORE_FLOOR:
        return err(
            ErrorCode.PATH_NOT_FOUND,
            f"No block matched '{reference}'",
            details={"query": reference, "best_score": ranked[0]["score"]},
        )

    if len(ranked) > 1 and (ranked[0]["score"] - ranked[1]["score"]) < SCORE_AMBIGUOUS_DELTA:
        return err(
            ErrorCode.AMBIGUOUS_MATCH,
            f"Several blocks match '{reference}' similarly",
            details={"query": reference, "candidates": ranked[:5]},
        )

    return ok(ranked[0])
