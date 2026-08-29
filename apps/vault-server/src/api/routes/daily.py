"""Daily note API routes — blocks, gaps, coverage, todos and notes for one day."""
import logging
import re
from datetime import date as dt_date, datetime
from fastapi import APIRouter, Depends
import pytz
from pydantic import BaseModel
from src.auth import verify_api_key
from src.config import settings
from src.services.daily_tasks import parse_all_todos, is_todo_line
from src.services.habit_completion import is_complete_today
from src.services.day_coverage import MINUTES_PER_DAY, day_coverage, minutes_into_day

router = APIRouter(prefix="/daily", tags=["daily"], dependencies=[Depends(verify_api_key)])
logger = logging.getLogger(__name__)

tz = pytz.timezone(settings.vault_timezone)


class DailyBlock(BaseModel):
    """One interval of the day, from the events ledger."""
    id: str
    start: str            # "HH:MM"
    end: str              # "HH:MM"
    title: str
    source: str           # "calendar" | "timeline" | "merged" | "daily-note" | "habit"
    type: str
    completed: bool = False
    activity: str | None = None   # populated by Ship 6
    category: str | None = None   # populated by Ship 6
    state: str = "suggested"      # "approved" arrives in Ship 5
    habit_progress: str | None = None  # "1/2" when a daily_target is set


class DailyGap(BaseModel):
    start: str
    end: str
    minutes: int


class DayCoverage(BaseModel):
    covered_minutes: int
    unaccounted_minutes: int


class DailyNote(BaseModel):
    text: str | None = None
    photo_path: str | None = None
    caption: str | None = None


class DailyTodo(BaseModel):
    text: str
    done: bool = False
    section: str = ""
    scheduled_at: str | None = None
    duration_minutes: int | None = None


class DailyResponse(BaseModel):
    date: str
    tokens_today: int
    tokens_total: int
    blocks: list[DailyBlock]
    gaps: list[DailyGap]
    coverage: DayCoverage
    todos: list[DailyTodo]
    notes: list[DailyNote]


def _extract_section(body: str, name: str) -> str:
    pat = re.compile(
        rf"##\s+{re.escape(name)}\s*\n(.*?)(?=^#{{2,}}\s|\Z)",
        re.DOTALL | re.MULTILINE | re.IGNORECASE,
    )
    m = pat.search(body)
    return m.group(1) if m else ""


def _build_todos(content: str, habits: list[dict], for_date: dt_date) -> list[DailyTodo]:
    """Every checkbox in the note that has not been moved away, wherever it
    lives. Checked ones are included too, carrying `done=True`.

    `schedule[]` only carries checkboxes that have a time, so without this
    an untimed todo is parsed and then silently dropped.

    A checkbox naming an active habit is reconciled against that habit's
    real state on `for_date` rather than trusted: `complete_habit` writes
    the habit file and never ticks the note, so the daily template's
    `## Daily Habits` boxes would otherwise sit unticked forever. Completed
    on `for_date` shows as done; not yet completed is omitted, since /habits
    is where outstanding habits belong and /day should not reopen them every
    morning. `for_date` must be the day being viewed, not always today —
    passing today unconditionally showed yesterday's habit todos as today's
    state and made every future date's habit todos vanish.

    Matched on habit name, not on section name, so it holds wherever the
    checkbox was written.
    """
    habit_state = {
        (h.get("metadata", {}).get("name") or "").strip().casefold():
            is_complete_today(h, for_date)
        for h in habits
    }

    todos: list[DailyTodo] = []
    for t in parse_all_todos(content):
        done = t.state == "checked"
        habit_done = habit_state.get(t.text.strip().casefold())
        if habit_done is not None:
            if not habit_done:
                continue
            done = True
        todos.append(DailyTodo(
            text=t.text,
            done=done,
            section=t.section,
            scheduled_at=t.scheduled_at,
            duration_minutes=t.duration_minutes,
        ))
    return todos


def _build_notes(content: str) -> list[DailyNote]:
    """Prose and photos from `## Notes` — checkboxes there are todos, not notes."""
    notes: list[DailyNote] = []
    for line in _extract_section(content, "Notes").splitlines():
        if is_todo_line(line):
            continue
        stripped = line.strip().lstrip("- ").strip()
        if not stripped:
            continue
        img_match = re.match(r"!\[([^\]]*)\]\(([^)]*)\)", stripped)
        if img_match:
            notes.append(DailyNote(
                caption=img_match.group(1) or None,
                photo_path=img_match.group(2) or None,
            ))
        else:
            notes.append(DailyNote(text=stripped))
    return notes


def _end_minutes(timestamp: str, date: str) -> int | None:
    """`minutes_into_day` for a block's *end*, clipped to end-of-day when the
    end falls on a later date.

    Spec §4: "Block spanning midnight → rendered clipped to the day."
    `MergerService` clamps the blocks it builds itself, but a real calendar
    entry (or a manually created event) carries its own end timestamp, and
    `minutes_into_day` returns None for one on the next date — which dropped
    the block entirely. A 22:00→01:00 shift rendered as no blocks at all and
    a single 00:00–24:00 gap: the whole day read as unaccounted. Ship 1
    displayed that event, so dropping it was a regression.

    Only a *later* date clips. An end before `date` is not a span, it is
    corrupt, and None still drops it. Ship 5 owns the second fragment.
    """
    direct = minutes_into_day(timestamp, date)
    if direct is not None:
        return direct
    day_part, sep, _ = timestamp.partition("T")
    if not sep:
        return None
    try:
        if dt_date.fromisoformat(day_part) > dt_date.fromisoformat(date):
            return MINUTES_PER_DAY
    except ValueError:
        return None
    return None


def _build_blocks_and_coverage(
    events: list[dict], date: str, elapsed_minutes: int
) -> tuple[list[DailyBlock], list[DailyGap], DayCoverage]:
    """Turn merged events into the day's timeline, plus its coverage.

    Events that *start* outside `date` are dropped: storage splits at
    midnight, so a neighbouring day's fragment here would distort this
    day's arithmetic. An event that starts on `date` and ends after it is
    clipped to `24:00` rather than dropped — see `_end_minutes`.
    """
    blocks: list[DailyBlock] = []
    intervals: list[tuple[int, int]] = []

    for e in events:
        start = minutes_into_day(e.get("start_time", ""), date)
        end = _end_minutes(e.get("end_time", ""), date)
        if start is None or end is None:
            continue
        habit = e.get("habit") or {}
        target = habit.get("daily_target")
        blocks.append(DailyBlock(
            id=e.get("id", ""),
            start=f"{start // 60:02d}:{start % 60:02d}",
            end=f"{end // 60:02d}:{end % 60:02d}",
            title=e.get("name", ""),
            # `or default`, not `.get(k, default)`: a persisted event can
            # carry an explicit `null` for these keys, and `.get` only
            # supplies its default when the key is absent — an explicit
            # None sails through and 500s the endpoint at the pydantic
            # boundary (`type`/`source`/`state` are non-optional `str`).
            source=e.get("source") or "",
            type=e.get("type") or "",
            # `habit.completed` is the fallback, not the source: it is
            # where completion used to live, so persisted events written
            # before `MergedEvent.completed` existed still carry it there.
            completed=bool(e.get("completed") or habit.get("completed", False)),
            activity=e.get("activity"),
            category=e.get("category"),
            state=e.get("state") or "suggested",
            habit_progress=(
                f"{habit.get('completions_today', 0)}/{target}" if target else None
            ),
        ))
        intervals.append((start, end))

    blocks.sort(key=lambda b: b.start)
    raw_gaps, coverage = day_coverage(intervals, elapsed_minutes)
    return (
        blocks,
        [DailyGap(start=g.start, end=g.end, minutes=g.minutes) for g in raw_gaps],
        DayCoverage(
            covered_minutes=coverage.covered_minutes,
            unaccounted_minutes=coverage.unaccounted_minutes,
        ),
    )


@router.get("", response_model=DailyResponse)
async def get_daily(date: dt_date | None = None):
    """`date` is typed, not a raw string: FastAPI rejects anything that
    isn't a real calendar date with 422 before it ever reaches a filesystem
    path. It used to be `str | None`, and `date`'s only use was interpolated
    straight into `10-daily/{date}.md` and into the events-preview call —
    `?date=../../../../etc/hosts` read an arbitrary file off disk and
    returned its body through notes[]/todos[]. This parameter took no input
    at all before this route grew ?date=, so there was nothing to validate
    before now.
    """
    from src.main import get_vault
    from src.api.routes.events import get_events_preview

    vault = get_vault()
    now = datetime.now(tz)
    today_date = now.date()
    target_date = date or today_date
    target = target_date.isoformat()

    # read_daily_note catches FileNotFoundError internally and returns an
    # empty note rather than raising, so there is no exception here to
    # handle — a missing note for `target` is a legitimate empty day.
    daily = vault.read_daily_note(target)
    content = daily.get("content", "")

    # Blocks come from the events ledger, which owns temporal data. We call
    # a read-only preview rather than the persisting GET /events/{date}:
    # /daily is called on every navigation tap, and persisting on every tap
    # would let browsing a date rewrite data/events/{date}.json for it from
    # whatever the vault looks like *now* — a persisted block for a past
    # date could be silently dropped because a habit was since renamed. We
    # also call the shared merge rather than re-merging here: two
    # implementations of the same merge is how the ordinal bug in the Phase
    # 2 design §7 happened.
    events: list[dict] = []
    try:
        payload = await get_events_preview(target_date)
        events = payload.get("events", [])
    except Exception:
        # A silent [] here would render identically to a genuinely empty
        # day — log it so a failing events service doesn't look like the
        # user did nothing.
        logger.warning(
            "GET /daily?date=%s: fetching events failed, showing no blocks",
            target, exc_info=True,
        )

    if target_date < today_date:
        elapsed = 24 * 60
    elif target_date > today_date:
        elapsed = 0
    else:
        elapsed = now.hour * 60 + now.minute

    blocks, gaps, coverage = _build_blocks_and_coverage(events, target, elapsed)

    habits = vault.list_active_habits()
    # `target_date`, not today: habit checkboxes are reconciled against the
    # day being viewed, or yesterday shows this morning's completions and
    # every future date's habit todos vanish.
    todos = _build_todos(content, habits, target_date)
    notes = _build_notes(content)

    try:
        ledger = vault.read_token_ledger()
        tokens_today = ledger["metadata"].get("tokens_today", 0)
        tokens_total = ledger["metadata"].get("total_tokens", 0)
    except Exception:
        tokens_today = 0
        tokens_total = 0

    return DailyResponse(
        date=target,
        tokens_today=tokens_today,
        tokens_total=tokens_total,
        blocks=blocks,
        gaps=gaps,
        coverage=coverage,
        todos=todos,
        notes=notes,
    )
