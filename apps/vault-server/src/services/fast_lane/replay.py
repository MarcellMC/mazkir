"""Replay your real messages through the fast lane and score it (spec §11.2).

Pure functions over the agent-turns log and the golden set; the CLI in
scripts/fast_lane_replay.py does the I/O. Real messages never leave data/,
because the monorepo is public.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from rapidfuzz import fuzz

from src.services.fast_lane.context import BlockView, FastContext, HabitView, clean_turn_text
from src.services.fast_lane.contract import FAST_OPS, Clause, ParseResult, TimeWords, extract_hashtags
from src.services.fast_lane.time_resolver import ClauseResolution
from src.services.interval import normalize_time

_REPLY = re.compile(r'^\(replying to (\w+): "(.*?)"\)\s*', re.DOTALL)
_PHOTO = re.compile(r"^\(photo: [^)]*\)\s*")
HOP_WINDOW = dt.timedelta(minutes=2)
MINUTE = dt.timedelta(minutes=1)
NAME_MATCH = 75   # token_set_ratio: "Washed the dishes" ~ "Wash dishes" (79), not "Dog walk" ~ "Dog food" (55)


@dataclass
class Message:
    id: str
    ts: dt.datetime
    text: str
    reply_to: str | None = None
    reply_from: str | None = None
    has_photo: bool = False
    old_skill: str | None = None
    old_tools: list[dict[str, Any]] = field(default_factory=list)
    old_reply: str = ""


def _strip(raw: str) -> tuple[str, str | None, str | None, bool]:
    text, reply_to, reply_from, has_photo = raw, None, None, False
    for _ in range(2):   # the two prefixes can come in either order
        if _PHOTO.match(text):
            has_photo, text = True, _PHOTO.sub("", text, count=1)
        reply = _REPLY.match(text)
        if reply:
            reply_from, reply_to, text = reply.group(1), reply.group(2), text[reply.end():]
    return text.strip(), reply_to, reply_from, has_photo


def load_messages(turns_path: Path, chat_id: int, tz: ZoneInfo) -> list[Message]:
    """Your messages in order: one per message, even when two skills handled it."""
    out: list[Message] = []
    last_raw: str | None = None
    for line in Path(turns_path).read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict) or rec.get("chat_id") != chat_id:
            continue
        raw = rec.get("user_text") or ""
        try:   # a line with no usable time is skipped like one that isn't JSON
            ts = dt.datetime.strptime(rec["ts"], "%Y-%m-%dT%H:%M:%S%z").astimezone(tz)
        except (KeyError, TypeError, ValueError):
            continue
        tools = [{"name": t.get("name"), "params": t.get("params") or {}, "result": t.get("result_summary")}
                 for t in rec.get("tools") or []]
        if out and raw == last_raw and ts - out[-1].ts <= HOP_WINDOW:
            previous = out[-1]   # the same message, handed to a second skill
            previous.old_tools += tools
            previous.old_skill = rec.get("skill") or previous.old_skill
            previous.old_reply = rec.get("assistant_text") or previous.old_reply
            continue
        text, reply_to, reply_from, has_photo = _strip(raw)
        out.append(Message(id=f"t{len(out) + 1:04d}", ts=ts, text=text, reply_to=reply_to,
                           reply_from=reply_from, has_photo=has_photo, old_skill=rec.get("skill"),
                           old_tools=tools, old_reply=rec.get("assistant_text") or ""))
        last_raw = raw
    return out


_TURN_HEADER = re.compile(r"^### (\d\d):(\d\d) \[(user|assistant)\]\s*$", re.MULTILINE)


def load_conversation_messages(conversations_dir: Path, chat_id: int, tz: ZoneInfo,
                               before: dt.date) -> list[Message]:
    """Your messages kept only in the vault's conversation files: the days before the turn log began.

    Each file is one day, `{date}/{chat_id}.md`, in "### HH:MM [user]" and
    "### HH:MM [assistant]" sections. Ids are c0001… in time order, so they
    never collide with the turn log's t-ids. No tools were logged then.
    """
    out: list[Message] = []
    for path in sorted(Path(conversations_dir).glob(f"*/{chat_id}.md")):
        try:
            day = dt.date.fromisoformat(path.parent.name)
        except ValueError:
            continue
        if day >= before:
            continue
        parts = _TURN_HEADER.split(path.read_text(encoding="utf-8"))
        for k in range(1, len(parts) - 3, 4):
            hour, minute, role, content = parts[k], parts[k + 1], parts[k + 2], parts[k + 3].strip()
            ts = dt.datetime(day.year, day.month, day.day, int(hour), int(minute), tzinfo=tz)
            if role == "user":
                text, reply_to, reply_from, has_photo = _strip(content)
                out.append(Message(id="", ts=ts, text=text, reply_to=reply_to, reply_from=reply_from,
                                   has_photo=has_photo))
            elif out and out[-1].ts.date() == day and not out[-1].old_reply:
                out[-1].old_reply = content
    for n, msg in enumerate(out, 1):
        msg.id = f"c{n:04d}"
    return out


def _ts(value: Any, date: str, tz) -> dt.datetime | None:
    iso = normalize_time(str(value), date) if value else None
    if not iso:
        return None
    try:
        moment = dt.datetime.fromisoformat(iso)
    except ValueError:
        return None
    return moment.replace(tzinfo=tz) if moment.tzinfo is None else moment.astimezone(tz)


def _blocks_before(msg: Message, earlier: list[Message]) -> tuple[BlockView, ...]:
    """Blocks the old path created in the 30 h before this message: the day as it stood then."""
    out = []
    for prev in earlier:
        if msg.ts - prev.ts > dt.timedelta(hours=30):
            continue
        for tool in prev.old_tools:
            if tool["name"] != "create_event":
                continue
            params = tool["params"]
            date = str(params.get("date") or prev.ts.date().isoformat())
            result = tool.get("result") if isinstance(tool.get("result"), dict) else {}
            # Newer turns log the normalized {"ok", "data": {...}} shape; older ones the bare dict.
            data = result.get("data") if isinstance(result.get("data"), dict) else result
            out.append(BlockView(id=str(data.get("event_id", "")), date=date, name=str(params.get("name") or ""),
                                 start=_ts(params.get("start_time"), date, msg.ts.tzinfo),
                                 end=_ts(params.get("end_time"), date, msg.ts.tzinfo)))
    return tuple(out)


def context_for(msg: Message, earlier: list[Message], habits: tuple[HabitView, ...],
                typical: dict[str, int], skills: tuple[str, ...] = ()) -> FastContext:
    turns: list[tuple[str, str]] = []
    for prev in earlier[-2:]:
        turns += [("user", prev.text), ("assistant", clean_turn_text(prev.old_reply))]
    return FastContext(now=msg.ts, chat_id=0, text=msg.text, reply_to=msg.reply_to, reply_from=msg.reply_from,
                       recent_turns=tuple(turns[-4:]), blocks=_blocks_before(msg, earlier), habits=habits,
                       hashtags=extract_hashtags(msg.text), has_photo=msg.has_photo, typical_minutes=typical,
                       skills=skills)


def skeleton_row(msg: Message) -> dict[str, Any]:
    return {"id": msg.id, "ts": msg.ts.isoformat(), "text": msg.text, "reply_to": msg.reply_to,
            "has_photo": msg.has_photo,
            "old": {"skill": msg.old_skill,
                    "tools": [{"name": t["name"], "params": t["params"]} for t in msg.old_tools]},
            "expected": None, "unclear": False, "notes": ""}


def select_rows(messages: list[Message], golden: dict[str, dict[str, Any]], ids: set[str] | None = None,
                limit: int | None = None) -> list[tuple[int, Message]]:
    """The labelled messages to replay, keeping each one's index into the full history."""
    rows = [(i, m) for i, m in enumerate(messages)
            if (golden.get(m.id) or {}).get("expected") and (ids is None or m.id in ids)]
    return rows[:limit] if limit else rows


def new_skeleton_rows(messages: list[Message], golden: dict[str, Any]) -> list[dict[str, Any]]:
    """Skeleton rows for messages the golden set does not have yet, without the old router's pick.

    The old skill is left out so a labeller judges the fallthrough skill from
    the catalog, not by agreeing with the router it is meant to be compared to.
    """
    rows = []
    for msg in messages:
        if msg.id not in golden:
            row = skeleton_row(msg)
            row["old"].pop("skill", None)
            rows.append(row)
    return rows


def load_golden(path: Path) -> dict[str, dict[str, Any]]:
    rows = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            rows[row["id"]] = row
    return rows


def expected_parse(expected: dict[str, Any], message: str) -> ParseResult:
    """The labelled clauses as if the parse had been perfect, for scoring the resolver alone."""
    clauses = []
    for c in expected.get("clauses", []):
        t = c.get("time") or {}
        clauses.append(Clause(op=c["op"], intent=c.get("intent", "record"), stated=c.get("stated", True),
                              evidence=message, name=c.get("name"), target=c.get("target"),
                              time=TimeWords(start=t.get("start"), end=t.get("end"), duration=t.get("duration"),
                                             shift=t.get("shift"), day=t.get("day"),
                                             after=t.get("after"), with_=t.get("with"))))
    return ParseResult(tuple(clauses), expected.get("fallthrough_skill"))


def saved_parse(row: dict[str, Any]) -> ParseResult | None:
    """A parse from a saved replay row, to score again without calling the model.

    A saved row keeps the clauses that passed the checks but not the ones
    that were dropped, so a route of "mixed" over all-fast clauses is kept
    by marking one dropped clause.
    """
    if "clauses" not in row:
        return None
    clauses = []
    for c in row["clauses"]:
        t = c.get("time")
        time_words = TimeWords(**{k: t.get(k) for k in ("start", "end", "duration", "shift", "day", "after", "with_")}) \
            if isinstance(t, dict) else None
        clauses.append(Clause(op=c["op"], intent=c["intent"], stated=c["stated"], evidence=c["evidence"],
                              name=c.get("name"), target=c.get("target"), tags=tuple(c.get("tags") or ()),
                              place=c.get("place"), people=tuple(c.get("people") or ()),
                              project=c.get("project"), time=time_words))
    result = ParseResult(tuple(clauses), row.get("fallthrough_skill"))
    if row.get("route") == "mixed" and result.route == "fast":
        result = ParseResult(result.clauses, result.fallthrough_skill, dropped=("(dropped)",))
    return result


@dataclass
class RowScore:
    route_ok: bool
    skill_ok: bool | None
    expected_clauses: int
    got_clauses: int
    matched: int
    fields_ok: int
    placed: int
    placed_ok: int
    wrong_date: int
    future_records: int
    outcome_ok: int


def _same_name(a: str | None, b: str | None) -> bool:
    if not a and not b:
        return True
    if not a or not b:
        return False
    a, b = a.casefold(), b.casefold()
    return a == b or a in b or b in a or fuzz.token_set_ratio(a, b) >= NAME_MATCH


CREATE_OPS = frozenset({"log_block", "start_block"})


def _time_word(side: dict[str, Any] | Clause, key: str) -> str | None:
    """A time word from a label (a dict) or a parsed clause (TimeWords)."""
    if isinstance(side, dict):
        return (side.get("time") or {}).get(key)
    return getattr(side.time, key, None) if side.time is not None else None


def _same_write(label: dict[str, Any], clause: Clause) -> bool:
    """Whether the clause's op makes the write the label's op makes (2026-09-29, the Sonnet sample).

    Both models, and the labels, split the same message between ops whose
    writes do not differ. The resolver places log_block and start_block
    alike, and end_block and an edit_block that only sets the end alike. An
    end with no start matches a block logged by its end, because the matcher
    closes an open block of that activity either way and an end_block with
    nothing open becomes that new block (spec §7.1). Ops that write
    something else, such as a todo tick or an edit that moves the start,
    still count as misses.
    """
    ops = {label["op"], *label.get("also_ops", ())}
    if clause.op in ops:
        return True
    pair = {label["op"], clause.op}
    by_op = {label["op"]: label, clause.op: clause}
    if pair <= CREATE_OPS:
        return True
    if pair == {"end_block", "edit_block"}:
        edit = by_op["edit_block"]
        return _time_word(edit, "start") is None and _time_word(edit, "shift") is None
    if "end_block" in pair and pair - {"end_block"} <= CREATE_OPS:
        create = by_op[next(iter(pair - {"end_block"}))]
        return _time_word(create, "start") is None
    return False


def _local(moment: dt.datetime, tz) -> dt.datetime:
    """Naive wall time in `tz`. A label with an offset is converted first; one without is local already."""
    if moment.tzinfo is not None and tz is not None:
        moment = moment.astimezone(tz)
    return moment.replace(tzinfo=None)


def _close(got: dt.datetime | None, want: str | None) -> bool:
    if got is None or want is None:
        return got is None and want is None
    return abs(_local(got, got.tzinfo) - _local(dt.datetime.fromisoformat(want), got.tzinfo)) <= MINUTE


def score_row(expected: dict[str, Any], result: ParseResult,
              resolutions: list[ClauseResolution | None], now: dt.datetime) -> RowScore:
    want = [c for c in expected.get("clauses", []) if c.get("op") in FAST_OPS]
    got = [(c, r) for c, r in zip(result.clauses, resolutions) if c.op in FAST_OPS]
    used: set[int] = set()
    matched = fields_ok = placed = placed_ok = wrong_date = outcome_ok = 0
    for e in want:
        names = [e.get("name") or e.get("target"), *e.get("also_names", ())]
        k = next((k for k, (c, _) in enumerate(got)
                  if k not in used and _same_write(e, c)
                  and any(_same_name(c.name or c.target, name) for name in names)), None)
        if k is None:
            continue
        used.add(k)
        matched += 1
        c, r = got[k]
        if c.intent == e.get("intent", "record") and c.stated == e.get("stated", True):
            fields_ok += 1
        expect = e.get("expect") or {}
        if r is not None and expect.get("outcome") == r.outcome:
            outcome_ok += 1
        if expect.get("start"):
            placed += 1
            p = r.placement if r is not None else None
            if p is not None and p.start is not None:
                if _close(p.start, expect["start"]) and _close(p.end, expect.get("end")):
                    placed_ok += 1
                want_start = _local(dt.datetime.fromisoformat(expect["start"]), p.start.tzinfo)
                if _local(p.start, p.start.tzinfo).date() != want_start.date():
                    wrong_date += 1
    future = sum(1 for c, r in got
                 if r is not None and r.outcome == "fact" and c.intent == "record" and r.placement
                 and r.placement.start and r.placement.start > now + dt.timedelta(minutes=2))
    skill_ok = (result.fallthrough_skill == expected.get("fallthrough_skill")
                if expected.get("route") in ("fallthrough", "mixed") else None)
    return RowScore(route_ok=result.route == expected.get("route"), skill_ok=skill_ok,
                    expected_clauses=len(want), got_clauses=len(got), matched=matched, fields_ok=fields_ok,
                    placed=placed, placed_ok=placed_ok, wrong_date=wrong_date, future_records=future,
                    outcome_ok=outcome_ok)


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def _percentile(values: list[int], q: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def summarize(scores: list[RowScore], latencies_ms: list[int]) -> dict[str, Any]:
    skills = [s.skill_ok for s in scores if s.skill_ok is not None]
    return {
        "rows": len(scores),
        "route_accuracy": _ratio(sum(s.route_ok for s in scores), len(scores)),
        "fallthrough_skill_accuracy": _ratio(sum(skills), len(skills)),
        "clause_recall": _ratio(sum(s.matched for s in scores), sum(s.expected_clauses for s in scores)),
        "clause_precision": _ratio(sum(s.matched for s in scores), sum(s.got_clauses for s in scores)),
        "fields_agree": _ratio(sum(s.fields_ok for s in scores), sum(s.matched for s in scores)),
        "placement_accuracy": _ratio(sum(s.placed_ok for s in scores), sum(s.placed for s in scores)),
        "outcome_agreement": _ratio(sum(s.outcome_ok for s in scores), sum(s.matched for s in scores)),
        "wrong_date": sum(s.wrong_date for s in scores),
        "future_records": sum(s.future_records for s in scores),
        "parse_ms_p50": _percentile(latencies_ms, 0.5),
        "parse_ms_p95": _percentile(latencies_ms, 0.95),
        "median_parse_ms": statistics.median(latencies_ms) if latencies_ms else None,
    }
