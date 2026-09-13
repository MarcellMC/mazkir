"""Shared habit-completion semantics.

`daily_target` turned "did I do this today?" into "how many times today?".
Two callers ask that question — the agent's `complete_habit` tool and
`PATCH /habits/{name}` behind the Telegram inline keyboard — and they must
answer it identically, or the same habit reads as done in one place and
pending in the other.

This module owns the answer:

- `daily_target_of` — the target, guarded against hand-edited YAML.
- `completions_today` — today's count, including the transition-day backfill.
- `is_complete_today` — whether the day's target has been met.
- `complete_habit` — record one completion and report what changed.

Calendar sync is deliberately not here: the agent path gets it from the
`sync_to_calendar` post-hook, the REST route does it inline.
"""

from __future__ import annotations

import datetime as dt
import pytz
from typing import Any

from src.config import settings
from src.services.completion_log import (
    append_completion,
    count_on,
    parse_completion_log,
)


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


def is_complete_today(habit: dict, today: dt.date | None = None) -> bool:
    """Has this habit met its target for `today`?

    Not the same question as "was it touched today". `last_completed` is set
    on every completion, including partial ones, so a habit with
    `daily_target: 2` carries today's date after the first of two walks.
    """
    return completions_today(habit, today) >= daily_target_of(
        habit.get("metadata", {})
    )


def complete_habit(vault: Any, path: str, now: dt.datetime | None = None) -> dict:
    """Record one completion of the habit at `path`.

    Returns a dict describing the outcome — never raises for the
    already-complete case, which callers report in their own vocabulary:

        {
          "already_completed": bool,
          "path", "name", "date", "old_streak", "new_streak",
          "longest_streak", "tokens_earned", "completions_today",
          "daily_target", "target_met", "google_event_id", "new_token_total",
        }

    On `already_completed` the streak fields describe the untouched habit and
    `tokens_earned` is 0 — nothing is written.

    Tokens are awarded on every completion; the streak advances only on the
    completion that meets the day's target.
    """
    # `VAULT_TIMEZONE`, not the server clock. `habits.py` has always read
    # "today" in the vault's timezone while this wrote in the server's —
    # inert while the two agree, and off by a day for the first hours of
    # every local day when they don't (phase-2 doc §11). Ship 5 is the code
    # that cares: approving a block on a past date must stamp that date, and
    # a caller passing `now` explicitly is how it does so.
    now = now or dt.datetime.now(pytz.timezone(settings.vault_timezone))
    today = now.date()

    habit = vault.read_file(path)
    meta = habit["metadata"]
    body = habit.get("content", "")

    target = daily_target_of(meta)
    done_today = completions_today(habit, today)

    common = {
        "path": path,
        "name": meta.get("name", ""),
        "date": today.isoformat(),
        "daily_target": target,
        "google_event_id": meta.get("google_event_id"),
    }

    if done_today >= target:
        return {
            **common,
            "already_completed": True,
            "old_streak": meta.get("streak", 0),
            "new_streak": meta.get("streak", 0),
            "longest_streak": meta.get("longest_streak", 0),
            "tokens_earned": 0,
            "completions_today": done_today,
            "target_met": True,
            "new_token_total": None,
        }

    new_body = append_completion(body, now)
    count = done_today + 1
    target_met = count >= target

    old_streak = meta.get("streak", 0)
    new_streak = old_streak + 1 if target_met else old_streak
    longest = max(meta.get("longest_streak", 0), new_streak)

    vault.write_file(path, {
        **meta,
        "streak": new_streak,
        "longest_streak": longest,
        "last_completed": today.isoformat(),
        "updated": today.isoformat(),
    }, new_body)

    tokens = meta.get("tokens_per_completion", 5)
    token_result = vault.update_tokens(tokens, meta.get("name", "habit"))

    return {
        **common,
        "already_completed": False,
        "old_streak": old_streak,
        "new_streak": new_streak,
        "longest_streak": longest,
        "tokens_earned": tokens,
        "completions_today": count,
        "target_met": target_met,
        "new_token_total": (token_result or {}).get("new_total")
        if isinstance(token_result, dict)
        else None,
    }
