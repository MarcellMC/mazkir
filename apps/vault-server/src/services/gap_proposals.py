"""What probably filled a gap — spec §4.1.

Guess when there is a basis, ask otherwise. The basis is the events store
itself: the last two weeks of approved blocks. No new store, no network, no
accumulation mechanism to build.

Pure arithmetic over minute offsets and a caller-supplied history, so nothing
here touches the filesystem. The caller loads the date files; this decides
what they mean.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from src.services.approval import is_approved
from src.services.day_coverage import minutes_into_day

# How many previous days of approved blocks count as history.
HISTORY_DAYS = 14

# How many *distinct days* a name must appear on before it is proposed. Three
# of fourteen is deliberately low: a proposal is a question with a ✕ next to
# it, not an assertion, and the row shows the count so it can be judged.
MIN_DAYS_SEEN = 3

# How much of the gap a historical block must cover to be evidence for what
# filled it. A twenty-minute coffee inside a two-hour hole says nothing about
# the hole. Inclusive: exactly half counts.
OVERLAP_FRACTION = 0.5

# The core of the night, in minutes from midnight (02:00-05:00). A gap must
# contain all of it to read as sleep — an evening hole is not sleep however
# long it is.
SLEEP_CORE = (120, 300)

SLEEP_NAME = "Sleep"


def _overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start))


def _block_window(event: dict[str, Any]) -> tuple[int, int] | None:
    """The event's clock window in minutes from midnight, or None.

    The date the block sits on is irrelevant here — we are asking "what
    usually happens at this time of day", so only the clock matters. An end
    at or before the start is malformed or zero-duration input, not a span:
    a genuine cross-midnight event is already rejected upstream by
    `minutes_into_day`, which returns None when the timestamp's date differs
    from the date it is given. Either way such a window is no evidence about
    what filled a gap, so it is skipped rather than guessed at.
    """
    start_raw, end_raw = event.get("start_time"), event.get("end_time")
    if not start_raw or not end_raw:
        return None
    start_day = str(start_raw).partition("T")[0]
    start = minutes_into_day(str(start_raw), start_day)
    end = minutes_into_day(str(end_raw), start_day)
    if start is None or end is None or end <= start:
        return None
    return start, end


def propose_for_gap(
    start: int, end: int, history: list[list[dict[str, Any]]]
) -> dict[str, Any] | None:
    """`{"name", "days_seen"}` for a gap `[start, end)`, or None to ask.

    `history` is one event list per previous day, most recent first, already
    loaded by the caller. Only the first `HISTORY_DAYS` are read, so a caller
    passing more cannot smuggle in older evidence.

    Ladder, first hit wins: history, then the overnight seed, then nothing.
    """
    gap_minutes = end - start
    if gap_minutes <= 0:
        return None

    needed = gap_minutes * OVERLAP_FRACTION
    days_by_name: dict[str, set[int]] = defaultdict(set)

    for day_index, events in enumerate(history[:HISTORY_DAYS]):
        for event in events:
            if not is_approved(event):
                continue
            window = _block_window(event)
            if window is None:
                continue
            if _overlap(start, end, *window) >= needed:
                name = (event.get("name") or "").strip()
                if name:
                    days_by_name[name].add(day_index)

    if days_by_name:
        # Ties break on the name, so the same history always yields the same
        # proposal. §4.2 depends on that: the server recomputes the proposal
        # when the user approves it rather than trusting a client-sent name,
        # and a nondeterministic tiebreak would make the two disagree.
        name, days = max(days_by_name.items(), key=lambda kv: (len(kv[1]), kv[0]))
        if len(days) >= MIN_DAYS_SEEN:
            return {"name": name, "days_seen": len(days)}

    core_start, core_end = SLEEP_CORE
    if start <= core_start and end >= core_end:
        return {"name": SLEEP_NAME, "days_seen": 0}

    return None
