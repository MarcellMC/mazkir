"""What you see after the fast lane acts: one line per thing it did (fast-lane spec §8.2).

Rendered from the turn record `act.py` keeps (`data/actions/{turn_id}.json`),
so a tap that changes one line re-renders the same receipt from the same
data. Every word, glyph and button is decided here; the bot's formatter only
draws the structure.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

GLYPHS = {"fact": "✓", "plan": "◌", "proposal": "●", "question": "?"}
STATUS_GLYPHS = {"failed": "✗", "undone": "↶", "dismissed": "✕", "approved": "✓"}
UNDO_WINDOW = dt.timedelta(hours=24)
_LIVE = ("done", "approved", "pending")


def _naive(moment: dt.datetime) -> dt.datetime:
    return moment.replace(tzinfo=None)


def day_label(day: dt.date, today: dt.date) -> str:
    """"" today, then "yest", "tmrw", a weekday within the week, else "7 Sep"."""
    if day == today:
        return ""
    if day == today - dt.timedelta(days=1):
        return "yest"
    if day == today + dt.timedelta(days=1):
        return "tmrw"
    if abs((day - today).days) < 7:
        return day.strftime("%a")
    return f"{day.day} {day.strftime('%b')}"


def when_label(start: str | None, end: str | None, now: dt.datetime, end_precision: str | None = None) -> str:
    """"yest 23:15–23:35"; "09:00–~09:30" for a soft end; "00:10→" for a block still running."""
    s = dt.datetime.fromisoformat(start) if start else None
    e = dt.datetime.fromisoformat(end) if end else None
    first = s or e
    if first is None:
        return ""
    soft = "~" if end_precision in ("approx", "assumed") else ""
    if s and e:
        span = f"{s:%H:%M}–{soft}{e:%H:%M}"
    elif s:
        span = f"{s:%H:%M}→"
    else:
        span = f"…–{soft}{e:%H:%M}"
    return f"{day_label(first.date(), now.date())} {span}".strip()


def _sync_label(sync: dict | None) -> str | None:
    if not sync:
        return None
    if sync.get("reason") == "deferred":
        return "⏳ calendar"
    if sync.get("ok"):
        return "✓ calendar"
    if sync.get("attempted"):
        return f"⚠ calendar: {sync.get('reason') or 'failed'}"
    return None


def _habit_detail(habit: dict | None) -> str | None:
    if not habit:
        return None
    text = (f"🎯 {habit['name']} {habit['completions_today']}/{habit['daily_target']} · "
            f"+{habit['tokens_earned']} 🪙 · streak {habit['new_streak']}")
    before = (habit.get("prior") or {}).get("longest_streak")
    if before is not None and habit["new_streak"] > before:
        text += " · longest ever"
    return text


def _buttons(tid: str, line: dict) -> list[dict[str, str]]:
    def tap(label: str, action: str) -> dict[str, str]:
        return {"label": label, "data": f"rcpt:{tid}:{line['id']}:{action}"}

    status, out = line["status"], []
    if line["kind"] == "suggest":
        return [tap("Track it", "sy"), tap("Not now", "sn")] if status == "pending" else []
    if status == "pending":
        out += [tap("✓", "ok"), tap("✕", "no")]
    # A `google_orphan` means undo already removed the block and kept only the
    # Google id it could not delete: ✎ would open a block that is gone.
    orphaned = any(r.get("google_orphan") for r in line.get("undo") or ())
    if line.get("event_id") and status in _LIVE and line["kind"] in ("block", "edit") and not orphaned:
        out.append({"label": "✎", "data": f"block:edit:{line['date']}:{line['event_id']}"})
    if line.get("habit_candidate") and not line.get("habit") and status in ("done", "approved"):
        out.append(tap(f"{line['habit_candidate']['name']}?", "hb"))
    if line.get("place_text") and status in _LIVE:
        out.append(tap("+ place", "pl"))
    return out


def _line(tid: str, line: dict, now: dt.datetime) -> dict[str, Any]:
    glyph = STATUS_GLYPHS.get(line["status"]) or GLYPHS.get(line["outcome"], "·")
    when = when_label(line.get("start"), line.get("end"), now, line.get("end_precision"))
    if not when and line.get("day"):
        when = day_label(dt.date.fromisoformat(line["day"]), now.date())
    return {
        "id": line["id"], "glyph": glyph, "when": when, "text": line["text"],
        "detail": _habit_detail(line.get("habit")), "sync": _sync_label(line.get("calendar_sync")),
        "reason": line.get("undo_note") or line.get("reason") or "", "status": line["status"],
        "buttons": _buttons(tid, line),
    }


def receipt_text(receipt: dict) -> str:
    """The receipt as plain lines: the non-rich fallback, and what the conversation log keeps."""
    rows = []
    for line in receipt["lines"]:
        head = " ".join(p for p in (line["glyph"], line["when"], line["text"]) if p)
        if line.get("reason"):
            head += f" — {line['reason']}"
        rows.append(head)
        rows += [f"  {sub}" for sub in (line.get("detail"), line.get("sync")) if sub]
    return "\n".join(rows)


def _ask(line: dict) -> str:
    """What a question line asks, armed as the bot's open question so a plain reply answers it."""
    reason = line.get("reason") or "no time given"
    return f"{line['text']} · {reason}" + (". Reply with one." if reason == "no time given" else "")


def render_receipt(turn: dict, now: dt.datetime) -> dict:
    tid = turn["turn_id"]
    lines = [_line(tid, line, now) for line in turn["lines"]]
    fresh = _naive(now) - _naive(dt.datetime.fromisoformat(turn["created_at"])) < UNDO_WINDOW
    undoable = fresh and any(line.get("undo") and line["status"] in _LIVE for line in turn["lines"])
    asking = next((line for line in turn["lines"] if line["status"] == "question"), None)
    receipt = {
        "turn_id": tid, "lines": lines,
        "undo": f"rcpt:{tid}:u:un" if undoable else None,
        "open_question": _ask(asking) if asking else None,
    }
    receipt["text"] = receipt_text(receipt)
    return receipt


def ran_summary(turn: dict, now: dt.datetime) -> list[str]:
    """What the fast lane already did, told to the skill that takes the rest (spec §5.5)."""
    out = []
    for line, drawn in zip(turn["lines"], render_receipt(turn, now)["lines"]):
        if line["status"] in _LIVE:
            out.append(" ".join(p for p in (drawn["glyph"], drawn["when"], drawn["text"]) if p)
                       + f" ({line['kind']})")
    return out

