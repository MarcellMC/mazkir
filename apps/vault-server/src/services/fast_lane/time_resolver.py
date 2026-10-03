"""Place a message's clauses on the timeline.

Pure: the parse's clauses and the message's send time go in; placed
intervals and one outcome per clause come out. No model, no I/O, no clock
of its own. This is the arithmetic the agent kept getting wrong: "3:00-3:20"
sent at 04:17 was stored at 15:00 the same day, in the future, and "ended at
00:30" became a 25-hour walk. Here a test can pin it down.

Spec: docs/specs/2026-09-27-fast-lane-design.md §6.

`ResolverContext.now` must carry a `zoneinfo.ZoneInfo`: instants are built
with `datetime(..., tzinfo=now.tzinfo)`, which is only correct for zoneinfo.
A pytz zone would silently use its LMT offset.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field, replace

from src.services.fast_lane.time_words import (
    Clock, DayRef, ends_next_day, is_now, parse_clock, parse_day, parse_day_range, parse_duration,
    parse_relative, parse_shift, split_run_together, weekday_date,
)

TOLERANCE = dt.timedelta(minutes=2)
MAX_RECORD = dt.timedelta(hours=16)
AGREE = dt.timedelta(minutes=5)

BLOCK_OPS = frozenset({"log_block", "start_block"})
EDIT_OPS = frozenset({"end_block", "edit_block"})
TODO_OPS = frozenset({"add_todo", "check_todo", "rollover_todos"})
SLEEP_NAMES = frozenset({"sleep", "sleeping", "night sleep", "сон", "שינה"})
NIGHT_SLEEP = dt.timedelta(hours=8)


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
    bedtime: dt.time | None = None   # your usual Sleep start, from the ledger


def logical_date(instant: dt.datetime, boundary_hour: int) -> dt.date:
    """The day a moment belongs to: before the boundary it is still last night."""
    day = instant.date()
    return day - dt.timedelta(days=1) if instant.hour < boundary_hour else day


def to_wire(instant: dt.datetime) -> str:
    """The ledger's form of an instant: local wall clock, no offset, whole seconds.

    Round-trips through UTC first. A wall time the clocks skipped (02:30 on
    the night Israel springs forward) comes back as the real moment it names
    (03:30), never as a time no clock showed. Every fast-lane write goes
    through here (A2 gate from A1's final review).
    """
    real = instant.astimezone(dt.timezone.utc).astimezone(instant.tzinfo)
    return real.replace(tzinfo=None).isoformat(timespec="seconds")


@dataclass(frozen=True)
class _Raw:
    start: Clock | None
    end: Clock | None
    start_now: bool
    end_now: bool
    minutes: int | None
    day: DayRef | None
    start_rel: dt.timedelta | None = None   # "15 mins ago", "in 20 minutes": from the message time
    end_rel: dt.timedelta | None = None
    end_day: dt.date | None = None          # a range's last day ("30.08 - 06.09")
    end_next_day: bool = False              # "14:00 next day"

    @property
    def anchor(self) -> Clock | None:
        # "now" is not a clock reading, and neither is "15 mins ago": such a
        # start is placed by `_fill_relative`, never seeded from a clock
        # (spec §6.2 rule 5).
        if self.start_now or self.start_rel is not None:
            return None
        return self.start or self.end

    @property
    def relative(self) -> bool:
        return self.start_rel is not None or self.end_rel is not None


def _fixed(now_word: bool, rel: dt.timedelta | None, ctx: ResolverContext) -> dt.datetime | None:
    """An instant pinned to the message time: "now", or "N min ago" / "in N min"."""
    if now_word:
        return ctx.now
    if rel is not None:
        return ctx.now + rel
    return None


@dataclass
class _Reading:
    placed: dict[int, Placement] = field(default_factory=dict)
    flags: dict[int, str] = field(default_factory=dict)
    valid: bool = True


def _raw(c: ClauseTime, ctx: ResolverContext) -> _Raw:
    return _Raw(
        start=parse_clock(c.start), end=parse_clock(c.end),
        start_now=is_now(c.start), end_now=is_now(c.end),
        minutes=parse_duration(c.duration),
        day=parse_day(c.day, ctx.now.date(), c.intent),
        start_rel=parse_relative(c.start), end_rel=parse_relative(c.end),
        end_day=(span[1] if (span := parse_day_range(c.day, ctx.now.date(), c.intent)) else None),
        end_next_day=ends_next_day(c.end),
    )


def _precision(clock: Clock) -> str:
    return "approx" if clock.hedged else "exact"


def _at(day: dt.date, hour: int, minute: int, tz) -> dt.datetime:
    return dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)


def _hours(clock: Clock, night: bool) -> list[int]:
    """The hours a clock can mean. You write the 24-hour clock or say am/pm (spec §6.2 rule 3).

    One exception: after a night word, a bare hour 1-12 may be the evening
    one ("tonight at 11" is 23:00), and the night itself picks between them.
    """
    return [clock.hour, (clock.hour + 12) % 24] if night and clock.ambiguous else [clock.hour]


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
    return [_night_of(ref, ctx)], True


def _night_of(ref: DayRef, ctx: ResolverContext) -> dt.date:
    """The calendar day whose evening a night word names ("tonight", "last night")."""
    return logical_date(ctx.now, ctx.day_boundary_hour) + dt.timedelta(days=ref.night_offset)


def _in_night(instant: dt.datetime, ref: DayRef, ctx: ResolverContext) -> bool:
    """Whether `instant` lies inside the night a night word names (spec §6.2 rule 4).

    The night opens 12 hours after the day boundary on its evening (17:00
    with the default 05:00) and closes at the boundary the next morning.
    Those 12 hours make the word decisive: of an ambiguous hour's two
    readings exactly one lies inside, so "last night at 2" is 02:00, never
    14:00 the afternoon before, and "tonight at 11" is 23:00.
    """
    night = _night_of(ref, ctx)
    opens = _at(night, 12 + ctx.day_boundary_hour, 0, instant.tzinfo)
    closes = _at(night + dt.timedelta(days=1), ctx.day_boundary_hour, 0, instant.tzinfo)
    return opens <= instant < closes


def _instants(clock: Clock, dates: list[dt.date], night: bool, tz) -> list[dt.datetime]:
    out = set()
    for day in dates:
        for hour in _hours(clock, night):
            # a night runs from the evening of `day` into the small hours of the next
            on = day + dt.timedelta(days=1) if night and hour < 12 else day
            out.add(_at(on, hour, clock.minute, tz))
    return sorted(out)


def _first_after(clock: Clock, after: dt.datetime, tz, strictly: bool) -> dt.datetime:
    """The earliest reading of `clock` after `after` (at or after, within tolerance, if not strict)."""
    days = [after.date(), after.date() + dt.timedelta(days=1)]
    options = [i for i in _instants(clock, days, False, tz)
               if (i > after if strictly else i >= after - TOLERANCE)]
    return min(options)


def _end_after(raw: _Raw, start: dt.datetime, tz) -> dt.datetime:
    """The end clock's reading after `start`: on a range's last day or "next day" when written."""
    if raw.end_day is not None or raw.end_next_day:
        day = raw.end_day if raw.end_day is not None else start.date() + dt.timedelta(days=1)
        return _at(day, raw.end.hour, raw.end.minute, tz)
    return _first_after(raw.end, start, tz, strictly=True)


def _open_end(start: dt.datetime, raw: _Raw, c: ClauseTime, ctx: ResolverContext) -> dt.datetime | None:
    """A record with only a start: your usual length once that has passed, else still open."""
    if c.intent != "record":
        return None
    span, _ = _duration(raw, c, ctx)
    return start + span if start + span <= ctx.now else None


def _back_from_end(end: dt.datetime, raw: _Raw, c: ClauseTime,
                   ctx: ResolverContext) -> tuple[dt.datetime, str, str | None]:
    """The start of a block known only by its end, that start's precision, and a reason to ask.

    A Sleep known only by when you woke starts at your usual bedtime (eight
    hours before, with none known) and is proposed, not written: the start
    is a guess hours wide (owner, 2026-09-29).
    """
    if raw.minutes is None and (c.name or "").strip().lower() in SLEEP_NAMES:
        if ctx.bedtime is not None:
            start = _at(end.date(), ctx.bedtime.hour, ctx.bedtime.minute, end.tzinfo)
            if start >= end:
                start -= dt.timedelta(days=1)
        else:
            typical = ctx.typical_minutes.get("sleep")
            start = end - (dt.timedelta(minutes=typical) if typical else NIGHT_SLEEP)
        return start, "assumed", "start assumed from your usual bedtime"
    span, assumed = _duration(raw, c, ctx)
    return end - span, ("assumed" if assumed else "inferred"), None


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
            end, end_precision = _end_after(raw, start, tz), _precision(raw.end)
            if raw.minutes is not None and abs((end - start) - dt.timedelta(minutes=raw.minutes)) > AGREE:
                r.flags[i] = "start, end and duration disagree"
        elif (fixed_end := _fixed(raw.end_now, raw.end_rel, ctx)) is not None:
            end, end_precision = fixed_end, "inferred"
        elif raw.minutes is not None:
            end, end_precision = start + dt.timedelta(minutes=raw.minutes), "inferred"
        elif (assumed := _open_end(start, raw, c, ctx)) is not None:
            end, end_precision = assumed, "assumed"
    else:  # anchored on the end
        end, end_precision = anchor, _precision(raw.end)
        linked = r.placed.get(c.after)
        after = (linked.end or linked.start) if linked is not None else None
        if after is not None and after < end:
            # "…then a bar until 3:00": the bar starts where the clause before it ended.
            start, start_precision = after, "inferred"
        else:
            start, start_precision, why = _back_from_end(end, raw, c, ctx)
            if why:
                r.flags[i] = why
    r.placed[i] = _place(start, end, start_precision, end_precision, c, ctx)


CHAIN_REACH = dt.timedelta(hours=12)


def _next_anchor(options: list[dt.datetime], previous: dt.datetime) -> tuple[dt.datetime, bool]:
    """Where a later clause's clock lands, and whether that is out of order.

    The reading just after the clause before it, when that is within 12
    hours; otherwise the nearest one before it within 12 hours, so "…before
    that, 00:33-02:35" lands earlier the same night (spec §6.2 rule 3).
    """
    later = sorted(o for o in options if o >= previous - TOLERANCE)
    if later and later[0] - previous <= CHAIN_REACH:
        return later[0], False
    earlier = sorted(o for o in options if o < previous - TOLERANCE)
    if earlier and previous - earlier[-1] <= CHAIN_REACH:
        return earlier[-1], False
    return (later[0], False) if later else (min(options), True)


def _chain(seed: dt.datetime, anchored: list[int], clauses, raws, ctx: ResolverContext,
           known: dict[int, Placement] | None = None) -> _Reading:
    """One reading: the first anchor at `seed`, every later one nearest the one before."""
    r = _Reading()
    r.placed.update(known or {})   # edits placed already, which an `after` may name
    tz = ctx.now.tzinfo
    previous: dt.datetime | None = None
    for position, i in enumerate(anchored):
        raw = raws[i]
        if position == 0:
            anchor = seed
        else:
            if raw.day is not None:
                dates, night = _dates(raw.day, clauses[i].intent, ctx)
            else:
                dates, night = [previous.date() + dt.timedelta(days=k) for k in (-1, 0, 1)], False
            options = _instants(raw.anchor, dates, night, tz)
            if night:
                options = [o for o in options if _in_night(o, raw.day, ctx)] or options
            anchor, out_of_order = _next_anchor(options, previous)
            if out_of_order:
                r.flags[i] = "out of order with the clause before it"
        _complete(i, clauses[i], raw, anchor, r, ctx)
        previous = r.placed[i].start or r.placed[i].end
    return r


def _from_start(start: dt.datetime, start_precision: str, raw: _Raw, c: ClauseTime, ctx) -> Placement:
    if raw.end is not None:
        return _place(start, _end_after(raw, start, ctx.now.tzinfo), start_precision, _precision(raw.end), c, ctx)
    if raw.minutes is not None:
        return _place(start, start + dt.timedelta(minutes=raw.minutes), start_precision, "inferred", c, ctx)
    fixed_end = _fixed(raw.end_now, raw.end_rel, ctx)
    if fixed_end is not None:
        return _place(start, fixed_end, start_precision, "inferred", c, ctx)
    assumed = _open_end(start, raw, c, ctx)
    return _place(start, assumed, start_precision, "assumed" if assumed else None, c, ctx)


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
        # "now" and "N min ago" pin a member, and the chain works outward from it
        now_anchored = any(raws[i].start_now or raws[i].relative for i in chain)
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
        elif (fixed_start := _fixed(raw.start_now, raw.start_rel, ctx)) is not None:
            # Its own "10 min ago" beats the link: "then shower started 10
            # min ago" is 13:50, not wherever the walk before it ended.
            r.placed[i] = _from_start(fixed_start, "inferred", raw, c, ctx)
        elif (fixed_end := _fixed(raw.end_now, raw.end_rel, ctx)) is not None:
            start, start_precision, why = _back_from_end(fixed_end, raw, c, ctx)
            if why:
                r.flags.setdefault(i, why)
            r.placed[i] = _place(start, fixed_end, start_precision, "inferred", c, ctx)
        elif c.after in r.placed:
            other = r.placed[c.after]
            r.placed[i] = _from_start(other.end or other.start, "inferred", raw, c, ctx)
        elif raw.end_day is not None and raw.day is not None and raw.day.kind == "date":
            # A range of days with no clock: the whole days, first to last.
            tz = ctx.now.tzinfo
            r.placed[i] = _place(_at(raw.day.date, 0, 0, tz), _at(raw.end_day + dt.timedelta(days=1), 0, 0, tz),
                                 "exact", "exact", c, ctx)
    # A placed clause whose predecessor has no time of its own: walk back from it.
    for i in sorted(idx, reverse=True):
        j = clauses[i].after
        if j in members and j not in r.placed and i in r.placed and r.placed[i].start is not None:
            span, assumed = _duration(raws[j], clauses[j], ctx)
            end = r.placed[i].start
            r.placed[j] = _place(end - span, end, "assumed" if assumed else "inferred",
                                 "inferred", clauses[j], ctx)


def _check(r: _Reading, idx: list[int], clauses, raws, ctx: ResolverContext) -> None:
    """Rules 1, 2, 4 and 10: records can't start after the message, plans can't start before it.

    A clause placed from the message time ("in 20 minutes") has no other
    reading to fall back on, so breaking rule 1 or 2 flags that clause, as
    an edit does (Ruling 7), rather than voiding the reading for them all.
    """
    today = ctx.now.date()
    for i in idx:
        p = r.placed.get(i)
        if p is None:
            continue
        c, raw = clauses[i], raws[i]
        first = p.start or p.end
        if raw.day is not None and raw.day.kind == "night" and not _in_night(first, raw.day, ctx):
            r.valid = False
        pinned = raw.anchor is None and raw.relative
        if c.intent == "record" and first > ctx.now + TOLERANCE:
            if pinned:
                r.flags.setdefault(i, "starts after the message")
            else:
                r.valid = False
        explicit_past = raw.day is not None and raw.day.kind == "date" and raw.day.date < today
        if c.intent == "plan" and first < ctx.now - TOLERANCE and not explicit_past:
            if pinned:
                r.flags.setdefault(i, "starts before the message")
            else:
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


def _resolve_blocks(clauses: list[ClauseTime], idx: list[int], ctx: ResolverContext,
                    known: dict[int, Placement] | None = None) -> dict[int, ClauseResolution]:
    raws = {i: _raw(clauses[i], ctx) for i in idx}
    anchored = [i for i in idx if raws[i].anchor is not None]
    if anchored:
        first = raws[anchored[0]]
        dates, night = _dates(first.day, clauses[anchored[0]].intent, ctx)
        # Seeded on the first clause's start: a date names the day a range
        # begins, so "23:00-00:30 on the 31st" ends on the 1st.
        readings = [_chain(seed, anchored, clauses, raws, ctx, known)
                    for seed in _instants(first.anchor, dates, night, ctx.now.tzinfo)]
    else:
        readings = [_Reading()]
    for r in readings:
        # Clauses placed elsewhere — edits — that an `after` / `with` may name.
        for j, p in (known or {}).items():
            r.placed.setdefault(j, p)
        _fill_relative(r, idx, clauses, raws, ctx)
        _check(r, idx, clauses, raws, ctx)
    valid = _unique([r for r in readings if r.valid])
    if not valid:
        return {i: ClauseResolution("question", reason="no reading of these times fits") for i in idx}
    # The readings differ only in their day (today or the one before, for a
    # record). A clean one beats a flagged one, then the most recent record or
    # the soonest plan wins: nothing is left to ask (spec §6.4).
    best = min(valid, key=lambda r: (bool(r.flags), _key(r, anchored, clauses, ctx)))
    return {i: _outcome(clauses[i], best.placed.get(i), best.flags.get(i)) for i in idx}


def _nearest(clock: Clock, reference: dt.datetime, tz) -> dt.datetime:
    days = [reference.date() + dt.timedelta(days=k) for k in (-1, 0, 1)]
    return min(_instants(clock, days, False, tz), key=lambda instant: abs(instant - reference))


def _edit_day(ref: DayRef, anchor: dt.datetime, intent: str, ctx: ResolverContext) -> dt.date:
    """The calendar day an edit moves a block to. A night keeps small hours on its morning."""
    if ref.kind == "date":
        return ref.date
    if ref.kind == "weekday":
        return weekday_date(ref.weekday, ctx.now.date(), intent)
    night = _night_of(ref, ctx)
    return night + dt.timedelta(days=1) if anchor.hour < 12 else night


def _resolve_edit(c: ClauseTime, ctx: ResolverContext) -> ClauseResolution:
    """end_block / edit_block: new times relative to the block they change (spec §6.2 rule 9).

    A day word moves the block to that day at the same clock times, and a
    length on its own keeps the start and sets the end (Ruling 14). Both are
    real placements, checked like any other edit; nothing that changes the
    time is reported as done without one.
    """
    if c.target_start is None and c.target_end is None:
        return ClauseResolution("question", reason="which block?")
    tz = ctx.now.tzinfo
    shift = parse_shift(c.shift)
    start_clock, end_clock = parse_clock(c.start), parse_clock(c.end)
    fixed_start = _fixed(is_now(c.start), parse_relative(c.start), ctx)
    fixed_end = _fixed(is_now(c.end), parse_relative(c.end), ctx)
    day = parse_day(c.day, ctx.now.date(), c.intent)
    minutes = parse_duration(c.duration)
    touches_time = (shift is not None or start_clock or end_clock or fixed_start or fixed_end
                    or day is not None or minutes is not None)
    if not touches_time:  # a rename or another edit with nothing to place
        return ClauseResolution("fact" if c.stated else "proposal")
    start, end = c.target_start, c.target_end
    start_precision = end_precision = None   # None: that end keeps the label it had
    if day is not None:
        anchor = start or end
        moved = dt.timedelta(days=(_edit_day(day, anchor, c.intent, ctx) - anchor.date()).days)
        start = start + moved if start is not None else None
        end = end + moved if end is not None else None
    reference = start or end
    if shift is not None:
        delta = dt.timedelta(minutes=shift)
        if start is not None:
            start, start_precision = start + delta, "inferred"
        if end is not None:
            end, end_precision = end + delta, "inferred"
    else:
        old_start, old_end = start, end
        if start_clock is not None:
            start, start_precision = _nearest(start_clock, reference, tz), _precision(start_clock)
        elif fixed_start is not None:
            start, start_precision = fixed_start, "inferred"
        moved_whole = (start is not None and old_start is not None and old_end is not None
                       and start != old_start and start >= old_end
                       and end_clock is None and fixed_end is None and minutes is None)
        if moved_whole:
            # A new start at or past the old end moves the block and keeps its
            # length; one inside it moves only the start (spec §6.2 rule 9).
            end, end_precision = old_end + (start - old_start), "inferred"
        elif end_clock is not None:
            end, end_precision = _first_after(end_clock, start or end, tz, strictly=True), _precision(end_clock)
        elif fixed_end is not None:
            end, end_precision = fixed_end, "inferred"
        elif minutes is not None:
            if start is None:
                return ClauseResolution("question", reason="the block has no start to measure the length from")
            end, end_precision = start + dt.timedelta(minutes=minutes), "inferred"
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


def _ended_with_nothing_open(c: ClauseTime) -> ClauseTime:
    """An end whose block is not on the timeline is that block, ending then (spec §7.1).

    "Completed gym at 16:50" with no gym open is a gym block that ended at
    16:50; asking "which block?" would ask about one that does not exist.
    """
    if c.op == "end_block" and c.target_start is None and c.target_end is None and c.end:
        return replace(c, op="log_block")
    return c


def _as_written(c: ClauseTime) -> ClauseTime:
    """The clause with the run-together typo "06:35:07:35" split into a start and an end (spec §6.6)."""
    start, end = split_run_together(c.start, c.end)
    return c if (start, end) == (c.start, c.end) else replace(c, start=start, end=end)


def _todo_day(ref: DayRef, c: ClauseTime, ctx: ResolverContext) -> dt.date:
    if ref.kind == "date":
        return ref.date
    if ref.kind == "weekday":
        return weekday_date(ref.weekday, ctx.now.date(), c.intent)
    return _night_of(ref, ctx)


def resolve(clauses: list[ClauseTime], ctx: ResolverContext) -> list[ClauseResolution]:
    """One resolution per clause, in order (spec §6.4)."""
    clauses = [_ended_with_nothing_open(_as_written(c)) for c in clauses]   # every later reading sees these once
    results = [ClauseResolution("fact" if c.stated else "proposal") for c in clauses]
    for i, c in enumerate(clauses):
        if c.op in EDIT_OPS:
            results[i] = _resolve_edit(c, ctx)
        elif c.op in TODO_OPS and (ref := parse_day(c.day, ctx.now.date(), c.intent)) is not None:
            # A todo has a day, not a time: "add X for tomorrow" lands on tomorrow's note.
            results[i] = replace(results[i], placement=Placement(None, None, None, None,
                                                                 _todo_day(ref, c, ctx)))
    known = {i: r.placement for i, r in enumerate(results)
             if clauses[i].op in EDIT_OPS and r.placement is not None}
    blocks = [i for i, c in enumerate(clauses) if c.op in BLOCK_OPS]
    if blocks:
        for i, resolution in _resolve_blocks(clauses, blocks, ctx, known).items():
            results[i] = resolution
    return results
