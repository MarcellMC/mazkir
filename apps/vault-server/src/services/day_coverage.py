"""Coverage and gap arithmetic for one day's blocks.

Two numbers, per the Ship 2 design §3.3:

    covered      union of block intervals, intersected with elapsed time
    unaccounted  elapsed − covered

Every maximal unaccounted span becomes a `⚠` row in the timeline. Overnight
is deliberately included: sleep is the largest unlogged span in a typical
day and the one most in need of surfacing, so a standing gap for it is a
prompt rather than noise.

Blocks are unioned before measuring, so two things at once — eating while
watching a video — is one hour of the day, not two. Coverage can never
exceed elapsed time, which is what keeps `unaccounted` non-negative.

Pure arithmetic on minute offsets from midnight. No I/O, no timezone
handling: the caller resolves both before calling in.
"""

from __future__ import annotations

from dataclasses import dataclass

MINUTES_PER_DAY = 24 * 60


@dataclass(frozen=True)
class Gap:
    """An unaccounted span. `end` is "24:00" at the end of a day rather than
    "00:00", which would read as a zero-length interval."""
    start: str
    end: str
    minutes: int


@dataclass(frozen=True)
class Coverage:
    covered_minutes: int
    unaccounted_minutes: int


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def minutes_into_day(timestamp: str, date: str) -> int | None:
    """Minutes from midnight, or None if `timestamp` is unusable or belongs
    to another day.

    Accepts `YYYY-MM-DDTHH:MM[...]` and a bare `HH:MM`. A timestamp on a
    different date returns None rather than folding into this one — a
    block spanning midnight is clipped by the caller, not silently moved.

    UTC timestamps (ending with `Z`) are rejected: they express UTC time,
    not local wall clock, and converting them requires timezone knowledge
    this module deliberately does not have (see module docstring). Timestamps
    with an offset like `+03:00` are accepted as local wall-clock time,
    since their hour/minute already express what the clock showed.
    """
    if not timestamp:
        return None
    time_part = timestamp
    if "T" in timestamp:
        day_part, _, time_part = timestamp.partition("T")
        if day_part != date:
            return None

    # Reject UTC timestamps explicitly.
    if time_part.endswith("Z"):
        return None

    parts = time_part.split(":")
    if len(parts) < 2:
        return None
    try:
        hours, minutes = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (0 <= hours < 24 and 0 <= minutes < 60):
        return None
    return hours * 60 + minutes


def day_coverage(
    intervals: list[tuple[int, int]], elapsed_minutes: int
) -> tuple[list[Gap], Coverage]:
    """Gaps and coverage for a day.

    `intervals` are (start, end) minute offsets from midnight, in any order,
    possibly overlapping. `elapsed_minutes` is midnight→now for today, 1440
    for a past day, and 0 for a future one.
    """
    elapsed = max(0, min(elapsed_minutes, MINUTES_PER_DAY))
    if elapsed == 0:
        return [], Coverage(covered_minutes=0, unaccounted_minutes=0)

    # Clip to the elapsed window: a block still ahead has not happened, and
    # counting it would drive `unaccounted` negative.
    clipped = sorted(
        (max(0, start), min(end, elapsed))
        for start, end in intervals
        if min(end, elapsed) > max(0, start)
    )

    merged: list[list[int]] = []
    for start, end in clipped:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    covered = sum(end - start for start, end in merged)

    gaps: list[Gap] = []
    cursor = 0
    for start, end in merged:
        if start > cursor:
            gaps.append(Gap(_hhmm(cursor), _hhmm(start), start - cursor))
        cursor = end
    if cursor < elapsed:
        end_label = "24:00" if elapsed == MINUTES_PER_DAY else _hhmm(elapsed)
        gaps.append(Gap(_hhmm(cursor), end_label, elapsed - cursor))

    return gaps, Coverage(
        covered_minutes=covered, unaccounted_minutes=elapsed - covered
    )
