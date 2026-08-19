"""Shared habit-completion semantics.

`daily_target` turned "did I do this today?" into "how many times today?".
Two callers ask that question — the agent's `complete_habit` tool and
`PATCH /habits/{name}` behind the Telegram inline keyboard — and they must
answer it identically, or the same habit reads as done in one place and
pending in the other.

This module owns the answer:

- `daily_target_of` — the target, guarded against hand-edited YAML.
- `completions_today` — today's count, including the transition-day backfill.
"""

from __future__ import annotations

import datetime as dt

from src.services.completion_log import count_on, parse_completion_log


def daily_target_of(meta: dict) -> int:
    """How many completions make a full day for this habit. Never below 1.

    `daily_target` is hand-edited YAML in a live vault, so it can be absent,
    empty, a typo (`two`), or nonsense (`-1`). A target below 1 would make the
    habit permanently uncompletable — `0 >= -1` — and a non-numeric one would
    raise on every completion. Both degrade to the default of 1.
    """
    try:
        return max(1, int(meta.get("daily_target") or 1))
    except (TypeError, ValueError):
        return 1


def completions_today(habit: dict, today: dt.date | None = None) -> int:
    """How many times `habit` was completed on `today`.

    Counts timestamped entries in the note's `## Completion Log`.

    Habits completed before the log existed carry only `last_completed`.
    Treat that as a full day's progress so the transition day cannot
    double-count. Self-retiring: once a habit has log entries, it never fires
    again.
    """
    today = today or dt.date.today()
    meta = habit.get("metadata", {})
    done = count_on(parse_completion_log(habit.get("content", "")), today)
    if not done and meta.get("last_completed") == today.isoformat():
        return daily_target_of(meta)
    return done
