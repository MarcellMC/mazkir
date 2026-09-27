"""Place a message's clauses on the timeline.

Pure: the parse's clauses and the message's send time go in; placed
intervals and one outcome per clause come out. No model, no I/O, no clock
of its own. This is the arithmetic the agent kept getting wrong: "3:00-3:20"
sent at 04:17 was stored at 15:00 the same day, in the future, and "ended at
00:30" became a 25-hour walk. Here a test can pin it down.

Spec: docs/superpowers/specs/2026-09-27-fast-lane-design.md §6.

`ResolverContext.now` must carry a `zoneinfo.ZoneInfo`: instants are built
with `datetime(..., tzinfo=now.tzinfo)`, which is only correct for zoneinfo.
A pytz zone would silently use its LMT offset.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from src.services.fast_lane.time_words import (
    Clock, DayRef, is_now, parse_clock, parse_day, parse_duration, parse_shift, weekday_date,
)

TOLERANCE = dt.timedelta(minutes=2)
MAX_RECORD = dt.timedelta(hours=16)
AGREE = dt.timedelta(minutes=5)
ASK_APART = dt.timedelta(hours=2)
RECENT = dt.timedelta(hours=3)
SOON = dt.timedelta(hours=12)
DOMINANT_GAP = dt.timedelta(hours=8)

BLOCK_OPS = frozenset({"log_block", "start_block"})
EDIT_OPS = frozenset({"end_block", "edit_block"})


@dataclass(frozen=True)
class ClauseTime:
    """What the resolver needs from one parse clause."""
    op: str
    intent: str = "record"
    stated: bool = True
    name: str | None = None
    start: str | None = None
    end: str | None = None
    duration: str | None = None
    shift: str | None = None
    day: str | None = None
    after: int | None = None
    with_: int | None = None
    # end_block / edit_block: the target's current interval, found by the caller
    target_start: dt.datetime | None = None
    target_end: dt.datetime | None = None


@dataclass(frozen=True)
class Placement:
    start: dt.datetime | None
    end: dt.datetime | None
    start_precision: str | None
    end_precision: str | None
    logical_date: dt.date | None


@dataclass(frozen=True)
class ClauseResolution:
    outcome: str                       # fact | plan | proposal | question
    placement: Placement | None = None
    reason: str = ""
    alternatives: tuple[Placement, ...] = ()


@dataclass(frozen=True)
class ResolverContext:
    now: dt.datetime
    day_boundary_hour: int = 5
    typical_minutes: dict[str, int] = field(default_factory=dict)
    default_minutes: int = 30


def logical_date(instant: dt.datetime, boundary_hour: int) -> dt.date:
    """The day a moment belongs to: before the boundary it is still last night."""
    day = instant.date()
    return day - dt.timedelta(days=1) if instant.hour < boundary_hour else day


@dataclass(frozen=True)
class _Raw:
    start: Clock | None
    end: Clock | None
    start_now: bool
    end_now: bool
    minutes: int | None
    day: DayRef | None

    @property
    def anchor(self) -> Clock | None:
        # "now" is not a clock reading: a start_now clause is placed by
        # `_fill_relative`, never seeded from a clock (spec §6.2 rule 5).
        if self.start_now:
            return None
        return self.start or self.end


@dataclass
class _Reading:
    placed: dict[int, Placement] = field(default_factory=dict)
    flags: dict[int, str] = field(default_factory=dict)
    valid: bool = True
    group: int | None = None  # the seed's hour: which 12-hour reading this is (§6.4 refinement)


def _raw(c: ClauseTime, ctx: ResolverContext) -> _Raw:
    return _Raw(
        start=parse_clock(c.start), end=parse_clock(c.end),
        start_now=is_now(c.start), end_now=is_now(c.end),
        minutes=parse_duration(c.duration),
        day=parse_day(c.day, ctx.now.date(), c.intent),
    )


def _precision(clock: Clock) -> str:
    return "approx" if clock.hedged else "exact"


def _at(day: dt.date, hour: int, minute: int, tz) -> dt.datetime:
    return dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)


def _hours(clock: Clock) -> list[int]:
    return [clock.hour, (clock.hour + 12) % 24] if clock.ambiguous else [clock.hour]


def _dates(ref: DayRef | None, intent: str, ctx: ResolverContext) -> tuple[list[dt.date], bool]:
    """Candidate calendar dates for a clause's anchor, and whether they name a night."""
    today = ctx.now.date()
    if ref is None:
        step = -1 if intent == "record" else 1
        return [today, today + dt.timedelta(days=step)], False
    if ref.kind == "date":
        return [ref.date], False
    if ref.kind == "weekday":
        return [weekday_date(ref.weekday, today, intent)], False
    night = logical_date(ctx.now, ctx.day_boundary_hour) + dt.timedelta(days=ref.night_offset)
    return [night], True


def _instants(clock: Clock, dates: list[dt.date], night: bool, tz) -> list[dt.datetime]:
    out = set()
    for day in dates:
        for hour in _hours(clock):
            # a night runs from the evening of `day` into the small hours of the next
            on = day + dt.timedelta(days=1) if night and hour < 12 else day
            out.add(_at(on, hour, clock.minute, tz))
    return sorted(out)


def _seeded_instants(clock: Clock, dates: list[dt.date], night: bool, tz) -> list[tuple[dt.datetime, int]]:
    """`(instant, hour)` pairs: `hour` is the 12-hour reading chosen, for grouping (spec §6.4)."""
    out: dict[dt.datetime, int] = {}
    for day in dates:
        for hour in _hours(clock):
            on = day + dt.timedelta(days=1) if night and hour < 12 else day
            out[_at(on, hour, clock.minute, tz)] = hour
    return sorted(out.items())


def _first_after(clock: Clock, after: dt.datetime, tz, strictly: bool) -> dt.datetime:
    """The earliest reading of `clock` after `after` (at or after, within tolerance, if not strict)."""
    days = [after.date(), after.date() + dt.timedelta(days=1)]
    options = [i for i in _instants(clock, days, False, tz)
               if (i > after if strictly else i >= after - TOLERANCE)]
    return min(options)


def _last_before(clock: Clock, before: dt.datetime, tz) -> dt.datetime:
    """The latest reading of `clock` strictly before `before` (its date and the day before)."""
    days = [before.date() - dt.timedelta(days=1), before.date()]
    options = [i for i in _instants(clock, days, False, tz) if i < before]
    return max(options)


def _duration(raw: _Raw, c: ClauseTime, ctx: ResolverContext) -> tuple[dt.timedelta, bool]:
    """The clause's length, and whether it was assumed from your history."""
    if raw.minutes is not None:
        return dt.timedelta(minutes=raw.minutes), False
    typical = ctx.typical_minutes.get((c.name or "").strip().lower())
    return dt.timedelta(minutes=typical or ctx.default_minutes), True


def _place(start, end, start_precision, end_precision, c: ClauseTime, ctx: ResolverContext) -> Placement:
    if end is not None and c.intent == "record" and end > ctx.now + TOLERANCE:
        end_precision = "expected"
    moment = start or end
    return Placement(start, end, start_precision, end_precision,
                     logical_date(moment, ctx.day_boundary_hour) if moment else None)


def _complete(i: int, c: ClauseTime, raw: _Raw, anchor: dt.datetime, r: _Reading, ctx: ResolverContext) -> None:
    """Place a clause that has a clock of its own, given where its anchor landed."""
    tz = ctx.now.tzinfo
    if raw.start is not None:
        start, start_precision = anchor, _precision(raw.start)
        end = end_precision = None
        if raw.end is not None:
            end, end_precision = _first_after(raw.end, start, tz, strictly=True), _precision(raw.end)
            if raw.minutes is not None and abs((end - start) - dt.timedelta(minutes=raw.minutes)) > AGREE:
                r.flags[i] = "start, end and duration disagree"
        elif raw.end_now:
            end, end_precision = ctx.now, "inferred"
        elif raw.minutes is not None:
            end, end_precision = start + dt.timedelta(minutes=raw.minutes), "inferred"
    else:  # anchored on the end
        end, end_precision = anchor, _precision(raw.end)
        span, assumed = _duration(raw, c, ctx)
        start, start_precision = end - span, ("assumed" if assumed else "inferred")
    r.placed[i] = _place(start, end, start_precision, end_precision, c, ctx)


def _complete_end_seeded(i: int, c: ClauseTime, raw: _Raw, end: dt.datetime, r: _Reading, ctx: ResolverContext) -> None:
    """Place a first clause with both a start and an end clock, seeded on its end.

    Rule 9: an edit moves both ends. The seed is the end clock's reading (it is
    usually unambiguous where the start alone would not be), and the start is
    the latest reading of the start clock strictly before it.
    """
    tz = ctx.now.tzinfo
    end_precision = _precision(raw.end)
    start = _last_before(raw.start, end, tz)
    start_precision = _precision(raw.start)
    if raw.minutes is not None and abs((end - start) - dt.timedelta(minutes=raw.minutes)) > AGREE:
        r.flags[i] = "start, end and duration disagree"
    r.placed[i] = _place(start, end, start_precision, end_precision, c, ctx)


def _chain(seed: dt.datetime, anchored: list[int], clauses, raws, ctx: ResolverContext) -> _Reading:
    """One reading: the first anchor at `seed`, every later one at its earliest time after the one before."""
    r = _Reading()
    tz = ctx.now.tzinfo
    previous: dt.datetime | None = None
    for position, i in enumerate(anchored):
        raw = raws[i]
        if position == 0:
            if raw.start is not None and raw.end is not None:
                _complete_end_seeded(i, clauses[i], raw, seed, r, ctx)
                previous = r.placed[i].start or r.placed[i].end
                continue
            anchor = seed
        else:
            if raw.day is not None:
                dates, night = _dates(raw.day, clauses[i].intent, ctx)
            else:
                dates, night = [previous.date(), previous.date() + dt.timedelta(days=1)], False
            options = _instants(raw.anchor, dates, night, tz)
            later = [o for o in options if o >= previous - TOLERANCE]
            if later:
                anchor = min(later)
            else:
                anchor = min(options)
                r.flags[i] = "out of order with the clause before it"
        _complete(i, clauses[i], raw, anchor, r, ctx)
        previous = r.placed[i].start or r.placed[i].end
    return r


def _from_start(start: dt.datetime, start_precision: str, raw: _Raw, c: ClauseTime, ctx) -> Placement:
    if raw.end is not None:
        end = _first_after(raw.end, start, ctx.now.tzinfo, strictly=True)
        return _place(start, end, start_precision, _precision(raw.end), c, ctx)
    if raw.minutes is not None:
        return _place(start, start + dt.timedelta(minutes=raw.minutes), start_precision, "inferred", c, ctx)
    if raw.end_now:
        return _place(start, ctx.now, start_precision, "inferred", c, ctx)
    return _place(start, None, start_precision, None, c, ctx)


def _fill_relative(r: _Reading, idx: list[int], clauses, raws, ctx: ResolverContext) -> None:
    """Place clauses with no clock of their own: chains, "with", and "now" (spec §6.2 rules 5-7)."""
    members = set(idx)
    follower = {clauses[i].after: i for i in idx if clauses[i].after in members}
    # A clock-less chain reported as past ends at the message time and runs backwards.
    for head in [i for i in idx if clauses[i].after not in members]:
        chain = [head]
        while chain[-1] in follower and follower[chain[-1]] not in chain:
            chain.append(follower[chain[-1]])
        clockless = all(raws[i].anchor is None and i not in r.placed for i in chain)
        now_anchored = any(raws[i].start_now for i in chain)
        if len(chain) > 1 and clockless and not now_anchored and clauses[chain[-1]].intent == "record":
            end, end_precision = ctx.now, "inferred"
            for i in reversed(chain):
                span, assumed = _duration(raws[i], clauses[i], ctx)
                start = end - span
                r.placed[i] = _place(start, end, "assumed" if assumed else "inferred",
                                     end_precision, clauses[i], ctx)
                end, end_precision = start, "inferred"
    for i in idx:
        if i in r.placed:
            continue
        c, raw = clauses[i], raws[i]
        if c.with_ in r.placed:
            other = r.placed[c.with_]
            r.placed[i] = _place(other.start, other.end, "inferred",
                                 "inferred" if other.end else None, c, ctx)
        elif c.after in r.placed:
            other = r.placed[c.after]
            r.placed[i] = _from_start(other.end or other.start, "inferred", raw, c, ctx)
        elif raw.start_now:
            r.placed[i] = _from_start(ctx.now, "inferred", raw, c, ctx)
        elif raw.end_now:
            span, assumed = _duration(raw, c, ctx)
            r.placed[i] = _place(ctx.now - span, ctx.now, "assumed" if assumed else "inferred",
                                 "inferred", c, ctx)
    # A placed clause whose predecessor has no time of its own: walk back from it.
    for i in sorted(idx, reverse=True):
        j = clauses[i].after
        if j in members and j not in r.placed and i in r.placed and r.placed[i].start is not None:
            span, assumed = _duration(raws[j], clauses[j], ctx)
            end = r.placed[i].start
            r.placed[j] = _place(end - span, end, "assumed" if assumed else "inferred",
                                 "inferred", clauses[j], ctx)


def _check(r: _Reading, idx: list[int], clauses, raws, ctx: ResolverContext) -> None:
    """Rules 1, 2 and 10: records can't start after the message, plans can't start before it."""
    today = ctx.now.date()
    for i in idx:
        p = r.placed.get(i)
        if p is None:
            continue
        c, raw = clauses[i], raws[i]
        first = p.start or p.end
        if c.intent == "record" and first > ctx.now + TOLERANCE:
            r.valid = False
        explicit_past = raw.day is not None and raw.day.kind == "date" and raw.day.date < today
        if c.intent == "plan" and first < ctx.now - TOLERANCE and not explicit_past:
            r.valid = False
        if p.start is not None and p.end is not None:
            if p.end <= p.start:
                r.flags.setdefault(i, "ends before it starts")
            elif c.intent == "record" and p.end - p.start > MAX_RECORD:
                r.flags.setdefault(i, "longer than 16 hours")


def _age(r: _Reading, anchored: list[int], clauses, ctx) -> dt.timedelta | None:
    moments = [min(p.end or p.start, ctx.now) for i in anchored
               if clauses[i].intent == "record" and (p := r.placed.get(i)) is not None]
    return ctx.now - max(moments) if moments else None


def _lead(r: _Reading, anchored: list[int], clauses, ctx) -> dt.timedelta | None:
    starts = [p.start or p.end for i in anchored
              if clauses[i].intent == "plan" and (p := r.placed.get(i)) is not None]
    return min(starts) - ctx.now if starts else None


def _key(r: _Reading, anchored, clauses, ctx) -> dt.timedelta:
    age = _age(r, anchored, clauses, ctx)
    if age is not None:
        return age
    lead = _lead(r, anchored, clauses, ctx)
    return lead if lead is not None else dt.timedelta(0)


def _dominates(best: _Reading, other: _Reading, anchored, clauses, ctx) -> bool:
    """Spec §6.4: the best reading is taken without asking when it clearly wins on recency."""
    a, b = _age(best, anchored, clauses, ctx), _age(other, anchored, clauses, ctx)
    if a is not None and b is not None:
        return a <= RECENT and b - a >= DOMINANT_GAP
    la, lb = _lead(best, anchored, clauses, ctx), _lead(other, anchored, clauses, ctx)
    if la is not None and lb is not None:
        return la <= SOON and lb - la >= DOMINANT_GAP
    return False


def _first(r: _Reading, anchored: list[int]) -> dt.datetime:
    p = r.placed[anchored[0]]
    return p.start or p.end


def _unique(readings: list[_Reading]) -> list[_Reading]:
    seen, out = set(), []
    for r in readings:
        key = tuple(sorted((i, p.start, p.end) for i, p in r.placed.items()))
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _outcome(c: ClauseTime, placement: Placement | None, flag: str | None) -> ClauseResolution:
    if placement is None:
        return ClauseResolution("question", reason="no time given")
    if not c.stated:
        return ClauseResolution("proposal", placement, reason="mentioned in passing")
    if flag:
        return ClauseResolution("proposal", placement, reason=flag)
    if c.intent == "plan":
        return ClauseResolution("plan", placement)
    return ClauseResolution("fact", placement)


def _resolve_blocks(clauses: list[ClauseTime], idx: list[int], ctx: ResolverContext) -> dict[int, ClauseResolution]:
    raws = {i: _raw(clauses[i], ctx) for i in idx}
    anchored = [i for i in idx if raws[i].anchor is not None]
    if anchored:
        first = raws[anchored[0]]
        dates, night = _dates(first.day, clauses[anchored[0]].intent, ctx)
        # Both clocks given: seed on the end and derive the start backward (rule 9).
        seed_clock = first.end if (first.start is not None and first.end is not None) else first.anchor
        readings = []
        for seed, hour in _seeded_instants(seed_clock, dates, night, ctx.now.tzinfo):
            r = _chain(seed, anchored, clauses, raws, ctx)
            r.group = hour
            readings.append(r)
    else:
        readings = [_Reading()]
    for r in readings:
        _fill_relative(r, idx, clauses, raws, ctx)
        _check(r, idx, clauses, raws, ctx)
    valid = _unique([r for r in readings if r.valid])
    if not valid:
        return {i: ClauseResolution("question", reason="no reading of these times fits") for i in idx}
    # One best reading per 12-hour reading (spec §6.4 refinement): an unambiguous
    # clock's "today vs. yesterday" pair collapses to whichever is more plausible,
    # rather than surfacing both as if they were genuinely different readings.
    champions = []
    for group_key in dict.fromkeys(r.group for r in valid):
        members = [r for r in valid if r.group == group_key]
        members.sort(key=lambda r: _key(r, anchored, clauses, ctx))
        champions.append(members[0])
    # A flagged reading (disagreement, implausible length, out of order) drops out
    # of ranking and alternatives while a clean one survives; kept only when every
    # surviving reading is flagged, so the best still becomes a proposal.
    unflagged = [r for r in champions if not r.flags]
    survivors = unflagged or champions
    survivors.sort(key=lambda r: _key(r, anchored, clauses, ctx))
    best = survivors[0]
    if anchored and len(survivors) > 1:
        second = survivors[1]
        apart = abs(_first(best, anchored) - _first(second, anchored)) >= ASK_APART
        if apart and not _dominates(best, second, anchored, clauses, ctx):
            return {
                i: ClauseResolution(
                    "question", reason="two readings of these times fit",
                    alternatives=tuple(p for p in (best.placed.get(i), second.placed.get(i)) if p),
                )
                for i in idx
            }
    return {i: _outcome(clauses[i], best.placed.get(i), best.flags.get(i)) for i in idx}


def _nearest(clock: Clock, reference: dt.datetime, tz) -> dt.datetime:
    days = [reference.date() + dt.timedelta(days=k) for k in (-1, 0, 1)]
    return min(_instants(clock, days, False, tz), key=lambda instant: abs(instant - reference))


def _resolve_edit(c: ClauseTime, ctx: ResolverContext) -> ClauseResolution:
    """end_block / edit_block: new times relative to the block they change (spec §6.2 rule 9)."""
    if c.target_start is None and c.target_end is None:
        return ClauseResolution("question", reason="which block?")
    tz = ctx.now.tzinfo
    shift = parse_shift(c.shift)
    start_clock, end_clock = parse_clock(c.start), parse_clock(c.end)
    touches_time = (shift is not None or start_clock or end_clock or is_now(c.start) or is_now(c.end))
    if not touches_time:  # a rename or another edit with nothing to place
        return ClauseResolution("fact" if c.stated else "proposal")
    start, end = c.target_start, c.target_end
    start_precision = end_precision = None   # None: that end is unchanged
    if shift is not None:
        delta = dt.timedelta(minutes=shift)
        if start is not None:
            start, start_precision = start + delta, "inferred"
        if end is not None:
            end, end_precision = end + delta, "inferred"
    else:
        if start_clock is not None:
            start, start_precision = _nearest(start_clock, c.target_start or c.target_end, tz), _precision(start_clock)
        elif is_now(c.start):
            start, start_precision = ctx.now, "inferred"
        if end_clock is not None:
            end, end_precision = _first_after(end_clock, start or c.target_end, tz, strictly=True), _precision(end_clock)
        elif is_now(c.end):
            end, end_precision = ctx.now, "inferred"
    flag = None
    if c.intent == "record" and start is not None and start > ctx.now + TOLERANCE:
        flag = "starts after the message"
    elif c.intent == "plan" and start is not None and start < ctx.now - TOLERANCE:
        flag = "starts before the message"
    elif start is not None and end is not None:
        if end <= start:
            flag = "ends before it starts"
        elif end - start > MAX_RECORD:
            flag = "longer than 16 hours"
    return _outcome(c, _place(start, end, start_precision, end_precision, c, ctx), flag)


def resolve(clauses: list[ClauseTime], ctx: ResolverContext) -> list[ClauseResolution]:
    """One resolution per clause, in order (spec §6.4)."""
    results = [ClauseResolution("fact" if c.stated else "proposal") for c in clauses]
    for i, c in enumerate(clauses):
        if c.op in EDIT_OPS:
            results[i] = _resolve_edit(c, ctx)
    blocks = [i for i, c in enumerate(clauses) if c.op in BLOCK_OPS]
    if blocks:
        for i, resolution in _resolve_blocks(clauses, blocks, ctx).items():
            results[i] = resolution
    return results
