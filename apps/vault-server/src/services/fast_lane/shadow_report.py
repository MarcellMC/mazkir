"""Compare a day of shadow runs with what the normal path actually did (spec §11.3, step 1).

The shadow log says what the fast lane would have written; agent-turns.jsonl
says what really ran. This lists where they disagree, so a daily read shows
whether the fast lane is ready to be switched on.
"""

from __future__ import annotations

import datetime as dt
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from src.services.interval import normalize_time

_WRITES = frozenset({"create_event", "update_event", "complete_habit", "daily_add_task",
                     "daily_set_task_state", "daily_rollover"})
_BEFORE, _AFTER = dt.timedelta(minutes=1), dt.timedelta(minutes=5)
_SLACK = dt.timedelta(minutes=5)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    if not Path(path).exists():
        return rows
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _when(value: str) -> dt.datetime:
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", None):
        try:
            return dt.datetime.strptime(value, fmt) if fmt else dt.datetime.fromisoformat(value)
        except ValueError:
            continue
    raise ValueError(value)


def pair_runs(shadow: list[dict], turns: list[dict]) -> list[tuple[dict, list[dict]]]:
    """Each shadow run with the agent turns that handled the same message."""
    pairs = []
    for run in shadow:
        if run.get("event") != "fast_shadow":
            continue
        now = _when(run["now"])
        text = (run.get("text") or "").strip()
        matched = [t for t in turns
                   if t.get("chat_id") == run.get("chat_id") and text and text in (t.get("user_text") or "")
                   and now - _BEFORE <= _when(t["ts"]) <= now + _AFTER]
        pairs.append((run, matched))
    return pairs


def _old_times(tool: dict, date: str) -> tuple[dt.datetime | None, dt.datetime | None]:
    params = tool.get("params") or {}

    def one(value):
        iso = normalize_time(str(value), date) if value else None
        return dt.datetime.fromisoformat(iso).replace(tzinfo=None) if iso else None

    return one(params.get("start_time")), one(params.get("end_time"))


def findings(run: dict, turns: list[dict], habit_names: set[str]) -> list[str]:
    if run.get("route") in ("router_fallback", "error"):
        return [f"parse failed: {run.get('error')}"]
    tools = [t for turn in turns for t in turn.get("tools") or []]
    wrote = {t.get("name") for t in tools} & _WRITES
    date = run["now"][:10]
    notes = []
    for c in run.get("clauses", []):
        outcome, name = c.get("outcome"), c.get("name") or ""
        if outcome == "question":
            notes.append(f"the fast lane would ask about \"{c.get('evidence')}\" ({c.get('reason')})")
            continue
        if c.get("op") in ("log_block", "start_block") and outcome in ("fact", "plan"):
            if not wrote & {"create_event", "update_event"}:
                notes.append(f"the old path wrote no block for \"{c.get('evidence')}\"")
            elif c.get("start"):
                fast_start = _when(c["start"]).replace(tzinfo=None)
                fast_end = _when(c["end"]).replace(tzinfo=None) if c.get("end") else None
                for tool in tools:
                    old_name = str((tool.get("params") or {}).get("name") or "").casefold()
                    if tool.get("name") != "create_event" or name.casefold() not in old_name:
                        continue
                    old_start, old_end = _old_times(tool, date)
                    off = old_start is None or abs(old_start - fast_start) > _SLACK or (
                        fast_end and old_end and abs(old_end - fast_end) > _SLACK)
                    if off:
                        notes.append(f"times differ for {name}: fast {c['start'][11:16]}–"
                                     f"{(c.get('end') or '')[11:16]}, old {old_start}–{old_end}")
            if name.casefold() in habit_names and "complete_habit" not in wrote:
                notes.append(f"habit not ticked by the old path: {name}")
    if run.get("route") == "fallthrough" and turns:
        old_skill = turns[-1].get("skill")
        if old_skill and run.get("fallthrough_skill") and old_skill != run["fallthrough_skill"]:
            notes.append(f"fallthrough skill {run['fallthrough_skill']}, old path used {old_skill}")
    return notes


def render_report(pairs: list[tuple[dict, list[dict]]], habit_names: set[str]) -> str:
    routes = Counter(run.get("route") for run, _ in pairs)
    outcomes = Counter(c.get("outcome") for run, _ in pairs for c in run.get("clauses", []) if c.get("outcome"))
    parse_ms = [run["parse_ms"] for run, _ in pairs if isinstance(run.get("parse_ms"), int)]
    head = [
        f"{len(pairs)} message{'s' if len(pairs) != 1 else ''} · routes {dict(routes)} · outcomes {dict(outcomes)}",
        f"parse ms median {statistics.median(parse_ms) if parse_ms else '–'}"
        f" · max {max(parse_ms) if parse_ms else '–'}",
        "",
    ]
    body = []
    for run, turns in pairs:
        notes = findings(run, turns, habit_names)
        if notes:
            body.append(f"{run['now'][11:16]}  {run.get('text', '')[:80]}")
            body += [f"    - {n}" for n in notes]
    return "\n".join(head + (body or ["no disagreements"]))
