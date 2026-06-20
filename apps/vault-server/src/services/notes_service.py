"""NotesService — read the daily/weekly note feed for the time-management app."""
import datetime
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.services.vault_service import VaultService as VaultServiceLike
else:
    VaultServiceLike = object

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


def _title_for(stem: str, meta: dict, body: str) -> str:
    """Prefer an H1 in the body, else a frontmatter title, else the stem."""
    m = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    if m:
        return m.group(1).strip()
    for key in ("title", "name"):
        if meta.get(key):
            return str(meta[key])
    return stem


class NotesService:
    """Reads the daily/weekly note feed from the Obsidian vault."""

    def __init__(self, vault: VaultServiceLike):
        self.vault = vault

    def _daily_dir(self):
        return self.vault.vault_path / "10-daily"

    def list_notes(self) -> list[dict]:
        """All notes in 10-daily/, newest-first."""
        out = []
        d = self._daily_dir()
        if not d.exists():
            return out
        for f in d.glob("*.md"):
            stem = f.stem
            rel = f"10-daily/{f.name}"
            parsed = self.vault.read_file(rel)
            body = parsed.get("content", "")
            meta = parsed.get("metadata", {}) or {}
            out.append({
                "id": stem,
                "sort_key": derive_sort_key(stem),
                "kind": derive_kind(stem),
                "title": _title_for(stem, meta, body),
                "has_photos": has_photo_embed(body),
                "snippet": extract_snippet(body),
            })
        out.sort(key=lambda n: n["sort_key"], reverse=True)
        return out
