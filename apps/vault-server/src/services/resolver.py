"""Unified fuzzy-path resolver for tasks, habits, and goals.

Single function `resolve_item(item_type, query, vault)` used by every name-
accepting tool. Returns a normalized ToolResponse — `ok` with the matched
path/name/score, or `err` with PATH_NOT_FOUND or AMBIGUOUS_MATCH.
"""

from __future__ import annotations

from typing import Any, Literal

from rapidfuzz import fuzz

from src.services.tool_response import ErrorCode, err, ok

SCORE_AMBIGUOUS_DELTA = 10.0

ItemType = Literal["task", "habit", "goal"]


def _candidates(vault: Any, item_type: ItemType) -> list[dict]:
    if item_type == "task":
        return vault.list_active_tasks()
    if item_type == "habit":
        return vault.list_active_habits()
    if item_type == "goal":
        return vault.list_active_goals()
    raise ValueError(f"Unknown item_type: {item_type}")


def resolve_item(item_type: ItemType, query: str, vault: Any) -> dict:
    """Resolve a query string to a unique item of the given type.

    Tries, in order: exact path match, exact name match (case-sensitive),
    case-insensitive substring of name, fuzzy match via rapidfuzz.

    Returns:
        ok({path, name, score}) on a unique hit.
        err(PATH_NOT_FOUND, ...) when no candidate scores above the floor.
        err(AMBIGUOUS_MATCH, ..., candidates: [...]) when top-1 and top-2
        are within `SCORE_AMBIGUOUS_DELTA` of each other.
    """
    items = _candidates(vault, item_type)
    if not items:
        return err(ErrorCode.PATH_NOT_FOUND, f"No {item_type}s available")

    for item in items:
        if item["path"] == query:
            return ok({"path": item["path"], "name": item["metadata"].get("name", ""), "score": 100.0})

    for item in items:
        if item["metadata"].get("name") == query:
            return ok({"path": item["path"], "name": item["metadata"]["name"], "score": 100.0})

    q_lower = query.lower()
    substring_hits = [
        item for item in items
        if q_lower in item["metadata"].get("name", "").lower()
    ]
    if len(substring_hits) == 1:
        item = substring_hits[0]
        return ok({"path": item["path"], "name": item["metadata"]["name"], "score": 95.0})

    if len(substring_hits) > 1:
        return err(
            ErrorCode.AMBIGUOUS_MATCH,
            f"Multiple {item_type}s match '{query}' similarly",
            details={
                "query": query,
                "candidates": [
                    {"path": item["path"], "name": item["metadata"].get("name", ""), "score": 95.0}
                    for item in substring_hits[:5]
                ],
            },
        )

    ranked = sorted(
        (
            {
                "path": item["path"],
                "name": item["metadata"].get("name", ""),
                "score": fuzz.token_set_ratio(query, item["metadata"].get("name", "")),
            }
            for item in items
        ),
        key=lambda r: r["score"],
        reverse=True,
    )

    if not ranked or ranked[0]["score"] < 60.0:
        return err(
            ErrorCode.PATH_NOT_FOUND,
            f"No {item_type} matched '{query}'",
            details={"query": query, "best_score": ranked[0]["score"] if ranked else 0},
        )

    top = ranked[0]
    if len(ranked) > 1 and (top["score"] - ranked[1]["score"]) < SCORE_AMBIGUOUS_DELTA:
        return err(
            ErrorCode.AMBIGUOUS_MATCH,
            f"Multiple {item_type}s match '{query}' similarly",
            details={
                "query": query,
                "candidates": [
                    {"path": r["path"], "name": r["name"], "score": r["score"]}
                    for r in ranked[:5]
                ],
            },
        )

    return ok(top)
