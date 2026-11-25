"""Photos whose block is gone go to the day's note as embeds, so none is lost."""

from __future__ import annotations

import datetime as dt
from typing import Any


def embed_photos_in_note(vault: Any, date: dt.date, photos: list[dict]) -> bool:
    """Append one `![[file]]` line per photo to `## Notes` of `date`'s note; return whether any was written."""
    lines = [f"![[{str(p.get('path') or '').rsplit('/', 1)[-1]}]]" for p in photos if p.get("path")]
    if not lines or vault is None:
        return False
    vault.append_to_daily_section(section="Notes", content="\n".join(lines),
                                  date=dt.datetime.combine(date, dt.time(12, 0)))
    return True
