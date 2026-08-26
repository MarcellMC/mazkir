"""Daily note API routes."""
import re
from datetime import datetime
from fastapi import APIRouter, Depends
import pytz
from pydantic import BaseModel
from src.auth import verify_api_key
from src.config import settings
from src.services.daily_tasks import parse_tasks_section, parse_all_todos, is_todo_line
from src.services.habit_completion import is_complete_today

router = APIRouter(prefix="/daily", tags=["daily"], dependencies=[Depends(verify_api_key)])

tz = pytz.timezone(settings.vault_timezone)


class DailyScheduleItem(BaseModel):
    start: str
    end: str | None = None
    title: str
    source: str  # "calendar" | "daily-task" | "habit"
    completed: bool = False
    calendar_name: str | None = None


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
    schedule: list[DailyScheduleItem]
    todos: list[DailyTodo]
    notes: list[DailyNote]


def _extract_section(body: str, name: str) -> str:
    pat = re.compile(
        rf"##\s+{re.escape(name)}\s*\n(.*?)(?=^##\s|\Z)",
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


def _build_todos(content: str) -> list[DailyTodo]:
    """Every checkbox in the note that has not been moved away, wherever it
    lives. Checked ones are included too, carrying `done=True`.

    `schedule[]` only carries checkboxes that have a time, so without this
    an untimed todo is parsed and then silently dropped.
    """
    return [
        DailyTodo(
            text=t.text,
            done=t.state == "checked",
            section=t.section,
            scheduled_at=t.scheduled_at,
            duration_minutes=t.duration_minutes,
        )
        for t in parse_all_todos(content)
    ]


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


@router.get("", response_model=DailyResponse)
async def get_daily():
    from src.main import get_vault, get_calendar
    vault = get_vault()
    calendar = get_calendar()

    today = datetime.now(tz).strftime("%Y-%m-%d")

    # Read or create daily note
    try:
        daily = vault.read_daily_note()
    except FileNotFoundError:
        daily = vault.create_daily_note()

    schedule: list[DailyScheduleItem] = []

    # Calendar events (already filtered by allowlist from T9)
    if calendar and calendar.is_initialized:
        try:
            cal_events = await calendar.get_todays_events(all_calendars=True)
            for e in cal_events:
                schedule.append(DailyScheduleItem(
                    start=e.get("start", ""),
                    end=e.get("end"),
                    title=e.get("summary", ""),
                    source="calendar",
                    completed=e.get("completed", False),
                    calendar_name=e.get("calendar"),
                ))
        except Exception:
            pass

    # Timed daily checkboxes from ## Tasks section
    content = daily.get("content", "")
    daily_tasks = parse_tasks_section(content)
    for t in daily_tasks:
        if t.scheduled_at and t.state in ("unchecked", "checked"):
            schedule.append(DailyScheduleItem(
                start=t.scheduled_at,
                title=t.text,
                source="daily-task",
                completed=t.state == "checked",
            ))

    # Scheduled habits (those with scheduled_at HH:MM)
    habits = vault.list_active_habits()
    for h in habits:
        meta = h.get("metadata", {})
        scheduled_at = _habit_scheduled_at(meta)
        if not scheduled_at:
            continue
        schedule.append(DailyScheduleItem(
            start=scheduled_at,
            title=meta.get("name", ""),
            source="habit",
            # Target met, not merely touched today — `last_completed` is set
            # on partial completions as well.
            completed=is_complete_today(h, datetime.now(tz).date()),
        ))

    # Sort schedule by start time
    schedule.sort(key=lambda s: s.start)

    # Todos parsed from all sections
    todos = _build_todos(content)

    # Notes parsed from ## Notes section
    notes = _build_notes(content)

    # Token ledger
    try:
        ledger = vault.read_token_ledger()
        tokens_today = ledger["metadata"].get("tokens_today", 0)
        tokens_total = ledger["metadata"].get("total_tokens", 0)
    except Exception:
        tokens_today = 0
        tokens_total = 0

    return DailyResponse(
        date=today,
        tokens_today=tokens_today,
        tokens_total=tokens_total,
        schedule=schedule,
        todos=todos,
        notes=notes,
    )
