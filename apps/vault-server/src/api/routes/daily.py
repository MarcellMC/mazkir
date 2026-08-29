"""Daily note API routes."""
import re
from datetime import date as dt_date, datetime
from fastapi import APIRouter, Depends
import pytz
from pydantic import BaseModel
from src.auth import verify_api_key
from src.config import settings
from src.services.daily_tasks import parse_all_todos, is_todo_line
from src.services.habit_completion import is_complete_today
from src.services.day_coverage import day_coverage, minutes_into_day

router = APIRouter(prefix="/daily", tags=["daily"], dependencies=[Depends(verify_api_key)])

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


def _habit_scheduled_at(meta: dict) -> str | None:
    """Time a habit is scheduled for, or None.

    `scheduled_at` is canonical. `scheduled_time` is the legacy key that the
    habit template used to write; habits created before the rename still
    carry it, and dropping them would silently empty the schedule.
    """
    return meta.get("scheduled_at") or meta.get("scheduled_time") or None


def _build_todos(content: str, habits: list[dict], today: dt_date) -> list[DailyTodo]:
    """Every checkbox in the note that has not been moved away, wherever it
    lives. Checked ones are included too, carrying `done=True`.

    `schedule[]` only carries checkboxes that have a time, so without this
    an untimed todo is parsed and then silently dropped.

    A checkbox naming an active habit is reconciled against that habit's
    real state rather than trusted: `complete_habit` writes the habit file
    and never ticks the note, so the daily template's `## Daily Habits`
    boxes would otherwise sit unticked forever. Completed today shows as
    done; not yet completed is omitted, since /habits is where outstanding
    habits belong and /day should not reopen them every morning.

    Matched on habit name, not on section name, so it holds wherever the
    checkbox was written.
    """
    habit_state = {
        (h.get("metadata", {}).get("name") or "").strip().casefold():
            is_complete_today(h, today)
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


def _build_blocks_and_coverage(
    events: list[dict], date: str, elapsed_minutes: int
) -> tuple[list[DailyBlock], list[DailyGap], DayCoverage]:
    """Turn merged events into the day's timeline, plus its coverage.

    Events whose start or end falls outside `date` are dropped: storage
    splits at midnight, so a neighbouring day's fragment here would distort
    this day's arithmetic.
    """
    blocks: list[DailyBlock] = []
    intervals: list[tuple[int, int]] = []

    for e in events:
        start = minutes_into_day(e.get("start_time", ""), date)
        end = minutes_into_day(e.get("end_time", ""), date)
        if start is None or end is None:
            continue
        habit = e.get("habit") or {}
        target = habit.get("daily_target")
        blocks.append(DailyBlock(
            id=e.get("id", ""),
            start=f"{start // 60:02d}:{start % 60:02d}",
            end=f"{end // 60:02d}:{end % 60:02d}",
            title=e.get("name", ""),
            source=e.get("source", ""),
            type=e.get("type", ""),
            completed=bool(habit.get("completed", False)),
            activity=e.get("activity"),
            category=e.get("category"),
            state=e.get("state", "suggested"),
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
async def get_daily(date: str | None = None):
    from src.main import get_vault
    from src.api.routes.events import get_events as get_events_route

    vault = get_vault()
    now = datetime.now(tz)
    today = now.strftime("%Y-%m-%d")
    target = date or today

    try:
        daily = vault.read_daily_note(target)
    except FileNotFoundError:
        daily = vault.create_daily_note() if target == today else {"content": ""}
    content = daily.get("content", "")

    # Blocks come from the events ledger, which owns temporal data. We call
    # the events route rather than re-merging: two implementations of the
    # same merge is how the ordinal bug in the Phase 2 design §7 happened.
    events: list[dict] = []
    try:
        payload = await get_events_route(dt_date.fromisoformat(target))
        events = payload.get("events", [])
    except Exception:
        pass

    if target < today:
        elapsed = 24 * 60
    elif target > today:
        elapsed = 0
    else:
        elapsed = now.hour * 60 + now.minute

    blocks, gaps, coverage = _build_blocks_and_coverage(events, target, elapsed)

    habits = vault.list_active_habits()
    todos = _build_todos(content, habits, now.date())
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
