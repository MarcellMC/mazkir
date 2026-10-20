"""Carry out a planned turn, one call at a time, keeping what undo needs (fast-lane spec §7.5–7.6).

Every call goes through `AgentService.run_tool`, so the audit log, pinning,
hooks and cross-date moves behave exactly as they do for the agent. Calls
run in message order. A failing call marks its line ✗ with the reason, and
the other lines still run: nothing is claimed that did not happen.

The turn record lands in `data/actions/{turn_id}.json`. The receipt is
rendered from it, undo reverses it for 24 hours, and a repeat of the same
Telegram message within 10 minutes finds it instead of writing twice.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import re
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from opentelemetry import trace

from src.services.fast_lane.actions import PlannedLine, Step
from src.services.fast_lane.receipt import UNDO_WINDOW
from src.services.fast_lane.time_resolver import to_wire

REPEAT_WINDOW = dt.timedelta(minutes=10)
_TURN_ID = re.compile(r"t[0-9a-f]{8}")
_HABIT_KEYS = ("path", "completed_at", "prior", "completions_today", "daily_target",
               "tokens_earned", "new_streak", "longest_streak")
_tracer = trace.get_tracer("mazkir.fast_lane")

RunTool = Callable[[str, dict], dict]


def new_turn_id() -> str:
    return "t" + uuid4().hex[:8]


def _find(events, event_id: str, date: str | None = None) -> dict | None:
    """A copy of the stored event, with the date of its file, or None."""
    found_date = events.resolve_event_date(event_id, date)
    if found_date is None:
        return None
    event = next((e for e in events.get_events(found_date) if e.get("id") == event_id), None)
    return {**copy.deepcopy(event), "date": found_date} if event else None


def _error(result: Any) -> str:
    error = result.get("error") if isinstance(result, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or "failed")
    return str(error or "failed")


def run_step(step: Step, *, run_tool: RunTool, events) -> dict:
    """One tool call, and what the receipt and undo need to know about it."""
    before = None
    if step.tool == "update_event":
        before = _find(events, step.params["event_id"], step.params.get("date"))
    with _tracer.start_as_current_span(f"fast.act.{step.tool}"):
        result = run_tool(step.tool, step.params)
    if not isinstance(result, dict) or not result.get("ok"):
        return {"ok": False, "reason": _error(result), "undo": []}
    data = result.get("data") or {}
    out: dict[str, Any] = {"ok": True, "reason": "", "undo": []}
    if step.tool == "create_event":
        ids = list(dict.fromkeys([data["event_id"], *(data.get("fragments") or [])]))
        file_date = Path(data["path"]).stem
        after = {eid: _find(events, eid, file_date) for eid in ids}
        first = after[ids[0]] or {}
        out.update(event_id=ids[0], date=first.get("date", file_date), calendar_sync=data.get("calendar_sync"),
                   habit=next((e["habit_completion"] for e in after.values() if e and e.get("habit_completion")), None),
                   undo=[{"kind": "created", "ids": ids, "after": after}])
    elif step.tool == "update_event":
        event_id = step.params["event_id"]
        after = _find(events, event_id, data.get("date"))
        newly_ticked = (after or {}).get("habit_completion") if not (before or {}).get("habit_completion") else None
        out.update(event_id=event_id, date=(after or {}).get("date") or data.get("date"),
                   calendar_sync=data.get("calendar_sync"), habit=newly_ticked,
                   undo=[{"kind": "edited", "event_id": event_id, "before": before, "after": after}])
    elif step.tool == "complete_habit":
        out.update(habit={"name": data.get("habit"), **{k: data.get(k) for k in _HABIT_KEYS}},
                   undo=[{"kind": "habit", "path": data.get("path"), "completed_at": data.get("completed_at"),
                          "prior": data.get("prior")}])
    elif step.tool in ("daily_add_task", "daily_check_todo"):
        kind = "todo_added" if step.tool == "daily_add_task" else "todo_checked"
        out.update(day=data.get("date"), undo=[{"kind": kind, "date": data.get("date"), "text": data.get("text")}])
    elif step.tool == "daily_rollover":
        out.update(undo=[{"kind": "none", "why": "a rollover can't be undone from here"}])
    return out


def _record(k: int, line: PlannedLine) -> dict[str, Any]:
    p = line.placement
    return {
        "id": k, "kind": line.kind, "outcome": line.outcome, "text": line.text, "status": "", "reason": line.reason,
        "start": to_wire(p.start) if p and p.start else None,
        "end": to_wire(p.end) if p and p.end else None,
        "end_precision": p.end_precision if p else None,
        "day": p.logical_date.isoformat() if p and p.logical_date and not (p.start or p.end) else None,
        "date": None, "event_id": None, "calendar_sync": None, "habit": None,
        "habit_candidate": line.habit_candidate, "place_text": line.place_text,
        "pending": [asdict(s) for s in line.pending], "undo": [],
    }


def apply_result(rec: dict, res: dict, *, done_status: str) -> None:
    """Fold one call's outcome into its line. Shared with the receipt routes (Task 16)."""
    if not res["ok"]:
        rec["status"], rec["reason"] = "failed", res["reason"]
        return
    for key in ("event_id", "date", "calendar_sync", "habit", "day"):
        if res.get(key) is not None:
            rec[key] = res[key]
    if res.get("habit") is not None:
        # The question a fuzzy candidate stood for is answered: a habit was ticked.
        rec["habit_candidate"] = None
    rec["undo"] = [*rec.get("undo", []), *res["undo"]]
    rec["status"] = done_status


def run_lines(lines: list[PlannedLine], *, run_tool: RunTool, events) -> list[dict]:
    records = []
    for k, line in enumerate(lines):
        rec = _record(k, line)
        if line.kind == "question":
            rec["status"] = "question"
        elif line.kind == "propose":
            rec["status"] = "pending"
        else:
            done = "pending" if line.outcome == "proposal" else "done"
            for step in line.steps:
                res = run_step(step, run_tool=run_tool, events=events)
                apply_result(rec, res, done_status=done)
                if not res["ok"]:
                    break
        records.append(rec)
    return records


def _path(actions_dir: Path, turn_id: str) -> Path | None:
    # fullmatch, not match with `$`: `$` also matches before a trailing newline.
    ok = isinstance(turn_id, str) and _TURN_ID.fullmatch(turn_id)
    return Path(actions_dir) / f"{turn_id}.json" if ok else None


def save_turn(actions_dir: Path, turn: dict) -> None:
    path = _path(actions_dir, turn["turn_id"])
    if path is None:
        raise ValueError(f"not a turn id: {turn['turn_id']!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(turn, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(path)


def load_turn(actions_dir: Path, turn_id: str) -> dict | None:
    """The turn record, or None. Only a `t<8 hex>` id is ever turned into a path."""
    path = _path(actions_dir, turn_id)
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def find_repeat(actions_dir: Path, chat_id: int, message_id: int | None) -> dict | None:
    """The turn this Telegram message already produced within 10 minutes (spec §10), or None."""
    if message_id is None or not Path(actions_dir).exists():
        return None
    horizon = time.time() - REPEAT_WINDOW.total_seconds()
    for path in Path(actions_dir).glob("t*.json"):
        if path.stat().st_mtime < horizon:
            continue
        turn = load_turn(actions_dir, path.stem)
        if turn and turn.get("chat_id") == chat_id and turn.get("message_id") == message_id:
            return turn
    return None


def prune(actions_dir: Path) -> None:
    """Undo snapshots are kept for 24 hours (spec §9.4)."""
    horizon = time.time() - UNDO_WINDOW.total_seconds()
    for path in Path(actions_dir).glob("t*.json"):
        try:
            if path.stat().st_mtime < horizon:
                path.unlink()
        except OSError:
            continue
