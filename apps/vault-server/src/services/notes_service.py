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
        try:
            # ISO weekday 7 = Sunday, the last day of the ISO week.
            sunday = datetime.date.fromisocalendar(year, week, 7)
        except ValueError:
            return stem
        return sunday.isoformat()
    if _DAILY_RE.match(stem):
        return stem
    return stem


_PHOTO_RE = re.compile(r"!\[\[[^\]]+\]\]")
_HEADER_RE = re.compile(r"^#{1,6}\s*", re.MULTILINE)
_MD_TOKENS_RE = re.compile(r"[*_`>#\[\]!]|\!\[\[|\]\]")


def has_photo_embed(body: str) -> bool:
    """True if the body contains an Obsidian image embed."""
    return bool(_PHOTO_RE.search(body))


def extract_snippet(body: str, limit: int = 140) -> str:
    """First ~limit chars of human prose: drop frontmatter-free body's
    headers/list markers/markdown tokens, collapse whitespace."""
    text = _PHOTO_RE.sub("", body)
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _HEADER_RE.match(line):              # skip header lines entirely
            continue
        line = line.lstrip("-* ").strip()       # list markers
        line = _MD_TOKENS_RE.sub("", line)       # leftover markdown tokens
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    snippet = " ".join(lines)
    return snippet[:limit].strip()
