"""Daily note API routes."""
import re
from datetime import datetime
from fastapi import APIRouter, Depends
import pytz
from pydantic import BaseModel
from src.main import get_vault, get_calendar
from src.auth import verify_api_key
from src.config import settings
from src.services.daily_tasks import parse_tasks_section

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


class DailyResponse(BaseModel):
    date: str
    tokens_today: int
    tokens_total: int
    schedule: list[DailyScheduleItem]
    notes: list[DailyNote]


def _extract_section(body: str, name: str) -> str:
    pat = re.compile(
        rf"##\s+{re.escape(name)}\s*\n(.*?)(?=^##\s|\Z)",
        re.DOTALL | re.MULTILINE | re.IGNORECASE,
    )
    m = pat.search(body)
    return m.group(1) if m else ""


@router.get("", response_model=DailyResponse)
async def get_daily():
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
        scheduled_at = meta.get("scheduled_at")
        if not scheduled_at:
            continue
        schedule.append(DailyScheduleItem(
            start=scheduled_at,
            title=meta.get("name", ""),
            source="habit",
            completed=meta.get("last_completed") == today,
        ))

    # Sort schedule by start time
    schedule.sort(key=lambda s: s.start)

    # Notes parsed from ## Notes section
    notes: list[DailyNote] = []
    notes_text = _extract_section(content, "Notes")
    for line in notes_text.splitlines():
        stripped = line.strip().lstrip("- ").strip()
        if not stripped:
            continue
        # Detect markdown image links: ![caption](path)
        img_match = re.match(r"!\[([^\]]*)\]\(([^)]*)\)", stripped)
        if img_match:
            caption = img_match.group(1) or None
            photo_path = img_match.group(2) or None
            notes.append(DailyNote(caption=caption, photo_path=photo_path))
        else:
            notes.append(DailyNote(text=stripped))

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
        notes=notes,
    )
