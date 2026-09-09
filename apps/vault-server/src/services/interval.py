"""Interval arithmetic for events: derive, validate, split at midnight.

Pure. No I/O, no timezone conversion — every timestamp here is local wall
clock, the same convention `day_coverage` uses.

This module exists because the arithmetic it does is the arithmetic the
model demonstrably gets wrong. On 2026-08-16 a retrospective utterance was
turned into a block shifted by its own length, because computing the second
endpoint was left to the model. Given any two of start/end/duration, the
third is a subtraction — so the tool takes any two and does it here.
"""

from __future__ import annotations

import datetime as dt

_FMT = "%Y-%m-%dT%H:%M:%S"


def normalize_time(value: str | None, date: str) -> str | None:
    """Anchor a bare `HH:MM` to `date`. Anything else is returned as-is."""
    if not value:
        return None
    if "T" in value:
        return value
    if len(value) <= 5:
        return f"{date}T{value}:00"
    return value


def _parse(value: str) -> dt.datetime:
    # `fromisoformat` accepts both "…T18:00" and "…T18:00:00"; normalizing
    # to a datetime here means every comparison below is on real instants
    # rather than on string prefixes.
    return dt.datetime.fromisoformat(value)


def _fmt(value: dt.datetime) -> str:
    return value.strftime(_FMT)


def derive_interval(
    start: str | None,
    end: str | None,
    duration_minutes: int | None,
    date: str,
) -> dict:
    """Fill in whichever of start/end/duration was not given.

    Fewer than two known values is not an error: it produces an incomplete
    block, which is the correct record of an incomplete statement. Three
    mutually inconsistent values IS an error — two of them are wrong and
    nothing here can tell which, so guessing would silently corrupt the day.
    """
    start_iso = normalize_time(start, date)
    end_iso = normalize_time(end, date)

    # Two bare times in reverse order mean the interval crossed midnight:
    # "slept 23:30 to 07:15" is one night, not a contradiction. Only bare
    # times get this reading — two explicit dates in reverse order are a
    # contradiction, because the dates already said what was meant.
    if (
        start_iso
        and end_iso
        and start and end
        and "T" not in start and "T" not in end
        and _parse(end_iso) < _parse(start_iso)
    ):
        end_iso = _fmt(_parse(end_iso) + dt.timedelta(days=1))

    known = sum(x is not None for x in (start_iso, end_iso, duration_minutes))
    if known < 2:
        return {
            "ok": True,
            "start_time": start_iso,
            "end_time": end_iso,
            "duration_minutes": duration_minutes,
        }

    if start_iso and end_iso:
        delta = int((_parse(end_iso) - _parse(start_iso)).total_seconds() // 60)
        if delta < 0:
            return {
                "ok": False,
                "error": f"End {end_iso} is before start {start_iso}",
            }
        if duration_minutes is not None and duration_minutes != delta:
            return {
                "ok": False,
                "error": (
                    f"start {start_iso} and end {end_iso} are {delta} minutes apart, "
                    f"but duration_minutes says {duration_minutes}. "
                    "Supply two of the three, not three that disagree."
                ),
            }
        return {
            "ok": True,
            "start_time": start_iso,
            "end_time": end_iso,
            "duration_minutes": delta,
        }

    if start_iso and duration_minutes is not None:
        end_iso = _fmt(_parse(start_iso) + dt.timedelta(minutes=duration_minutes))
    else:
        start_iso = _fmt(_parse(end_iso) - dt.timedelta(minutes=duration_minutes))

    # Validate ordering after derivation — the same rule as the direct-endpoints branch.
    if _parse(end_iso) < _parse(start_iso):
        return {
            "ok": False,
            "error": f"End {end_iso} is before start {start_iso}",
        }

    return {
        "ok": True,
        "start_time": start_iso,
        "end_time": end_iso,
        "duration_minutes": duration_minutes,
    }


def crosses_midnight(start_time: str, end_time: str) -> bool:
    """True when the two timestamps fall on different calendar days.

    A predicate answers a question; it does not raise. Unparseable input is
    not a midnight crossing, so it is `False`. This matters because the
    calendar-sync ladder in `_tool_update_event` calls this *after* the
    ledger write has already succeeded — a malformed stored timestamp would
    otherwise turn a completed write into a raised tool error, reporting a
    success as a failure, which is exactly the inversion the
    `{ok, attempted, reason}` contract exists to prevent.

    `derive_interval` keeps its strictness deliberately: it is validating
    input the user just supplied, where rejecting bad values is the right
    answer. Only the predicate softens.
    """
    if not start_time or not end_time:
        return False
    try:
        return _parse(start_time).date() != _parse(end_time).date()
    except (ValueError, TypeError):
        return False


def split_at_midnight(start_time: str, end_time: str) -> list[tuple[str, str]]:
    """One `(start, end)` fragment per calendar day the interval touches.

    Storage splits at 00:00 (Phase 1 §4.2): `data/events/{date}.json` is
    keyed by day and `day_coverage` measures minute offsets within one, so
    an interval spanning a boundary has no single correct home. The first
    fragment ends at 23:59:59 rather than the next midnight, so the two do
    not both claim the boundary minute.
    """
    if not crosses_midnight(start_time, end_time):
        return [(start_time, end_time)]

    fragments: list[tuple[str, str]] = []
    cursor = _parse(start_time)
    finish = _parse(end_time)

    while cursor.date() < finish.date():
        day_end = dt.datetime.combine(cursor.date(), dt.time(23, 59, 59))
        fragments.append((_fmt(cursor), _fmt(day_end)))
        cursor = dt.datetime.combine(
            cursor.date() + dt.timedelta(days=1), dt.time(0, 0, 0)
        )

    # Drop a trailing fragment whose start equals its end (zero-length phantom).
    # A genuinely stated zero-length interval (18:00 → 18:00) does not cross
    # midnight, so it never reaches this function — the drop is safe.
    if cursor < finish:
        fragments.append((_fmt(cursor), _fmt(finish)))
    return fragments
