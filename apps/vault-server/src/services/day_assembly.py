"""Fan out to every source and merge one day's events.

Lived in `routes/events.py`, which made it reachable only from HTTP. The
agent's `list_events` needs the same day the `/day` view renders — reading
the raw persisted file instead is how `list_events` and `/day` came to
disagree about what exists.
"""

from datetime import date as date_type

from src.services.habit_completion import completions_today, daily_target_of, is_complete_today
from src.services.merger_service import MergerService


async def merge_from_sources(date: date_type) -> tuple[list[dict], set[str]]:
    """Run MergerService against all sources and return fresh event dicts.

    Also returns which source systems actually answered this call —
    `refresh_events` needs that to tell "the calendar has nothing today"
    apart from "the calendar failed to answer", since only the former means
    an unmatched persisted event was genuinely deleted upstream. An
    uninitialized calendar (no OAuth token yet) is not an available source
    either — that's the exact condition that caused the original data loss.
    """
    from src.main import get_vault, get_calendar, get_timeline

    vault = get_vault()
    calendar = get_calendar()
    timeline = get_timeline()

    available_sources: set[str] = set()

    calendar_events = []
    if calendar and calendar.is_initialized:
        try:
            # `.get_todays_events` swallows HttpErrors and returns [] either
            # way, so it cannot tell "the calendar is empty" from "the token
            # expired" — that was the bug this fix exists for. The
            # `_with_status` variant reports a real ok/failed signal.
            calendar_events, calendar_ok = await calendar.get_todays_events_with_status(
                all_calendars=True, target_date=date,
            )
            if calendar_ok:
                available_sources.add("calendar")
        except Exception:
            pass

    timeline_data = {"visits": [], "activities": []}
    if timeline:
        try:
            timeline_data = timeline.get_day(date)
            # get_day/_load_timeline_objects returns [] when data/timeline/
            # doesn't exist rather than raising, so a missing Takeout export
            # looks identical to "nothing happened today" unless gated here.
            if timeline.data_path.exists():
                available_sources.add("timeline")
        except Exception:
            pass

    habits = []
    try:
        raw_habits = vault.list_active_habits()
        for h in raw_habits:
            meta = h["metadata"]
            habits.append({
                "name": meta.get("name", ""),
                # Target met on `date`, not merely touched: `last_completed`
                # is stamped on partial completions too.
                "completed_today": is_complete_today(h, date),
                "streak": meta.get("streak", 0),
                "tokens_per_completion": meta.get("tokens_per_completion", 5),
                "scheduled_at": meta.get("scheduled_at") or meta.get("scheduled_time") or None,
                "duration_minutes": meta.get("duration_minutes", 0),
                "completions_today": completions_today(h, date),
                "daily_target": daily_target_of(meta),
            })
        # `list_active_habits` returns [] for a missing `20-habits/`
        # directory rather than raising, so "it didn't raise" would mark a
        # renamed or missing habits directory as available — the same
        # availability-by-exception mistake the calendar and timeline
        # branches above already correct for. Gate on the directory
        # resolving, which is the actual "did this source answer" question.
        if (vault.vault_path / "20-habits").exists():
            available_sources.add("habit")
    except Exception:
        pass

    daily_body = ""
    try:
        raw_daily = vault.read_daily_note(date)
        daily_body = raw_daily.get("content", "")
        # read_daily_note catches FileNotFoundError internally and returns
        # an empty note, so the call succeeding says nothing about whether
        # a note exists — a missing note for `date` is real information (no
        # checkboxes to merge), not a failure. Gate on the vault directory
        # itself resolving instead; that is the actual "did this source
        # answer" question.
        if vault.vault_path.exists():
            available_sources.add("daily-note")
    except Exception:
        pass

    merger = MergerService(timezone="Asia/Jerusalem")
    events = merger.merge(
        calendar_events=calendar_events,
        timeline_data=timeline_data,
        habits=habits,
        daily_body=daily_body,
        date=date.isoformat(),
    )
    return [e.model_dump() for e in events], available_sources
