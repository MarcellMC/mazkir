"""NotesService — read the daily/weekly note feed for the time-management app."""
import datetime
import re

_DAILY_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_WEEKLY_RE = re.compile(r"^(\d{4})-W(\d{2})$")


def derive_kind(stem: str) -> str:
    """Classify a note filename stem as 'weekly' or 'daily'."""
    return "weekly" if _WEEKLY_RE.match(stem) else "daily"


def derive_sort_key(stem: str) -> str:
    """Return an ISO date string used to order notes newest-first.

    Dailies sort by their own date. Weeklies are anchored to the LAST day
    (Sunday) of their ISO week, so they land where the week concluded.
    Unrecognized stems sort by themselves.
    """
    m = _WEEKLY_RE.match(stem)
    if m:
        year, week = int(m.group(1)), int(m.group(2))
        # ISO weekday 7 = Sunday, the last day of the ISO week.
        sunday = datetime.date.fromisocalendar(year, week, 7)
        return sunday.isoformat()
    if _DAILY_RE.match(stem):
        return stem
    return stem
