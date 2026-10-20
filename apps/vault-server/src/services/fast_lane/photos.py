"""When a photo was taken, and the block it belongs to (fast-lane spec §5.6).

EXIF survives only when the image is sent as a file; a compressed Telegram
photo loses it (35 of 44 did). Then Telegram's send time is the best clue,
and it is UTC: read as local time it put photos three hours early, twice.
"""

from __future__ import annotations

import datetime as dt


def photo_moment(exif_timestamp: str | None, telegram_date: str | None, tz) -> tuple[dt.datetime | None, str | None]:
    """The moment, and "exact" (EXIF, local camera time) or "approx" (Telegram's send time, UTC)."""
    if exif_timestamp:
        try:
            return dt.datetime.fromisoformat(exif_timestamp).replace(tzinfo=tz), "exact"
        except ValueError:
            pass
    if telegram_date:
        try:
            sent = dt.datetime.fromisoformat(telegram_date.replace("Z", "+00:00"))
            if sent.tzinfo is None:
                sent = sent.replace(tzinfo=dt.timezone.utc)
            return sent.astimezone(tz).replace(microsecond=0), "approx"
        except ValueError:
            pass
    return None, None


def covering_block(events, moment: dt.datetime) -> dict | None:
    """The live block whose interval holds `moment`; an open block holds everything after its start.

    The latest-starting one wins when two overlap: it is the more specific.
    """
    day = moment.date().isoformat()
    wall = moment.replace(tzinfo=None)
    best = None
    for e in events.get_events(day):
        if e.get("state") == "dismissed" or not e.get("start_time"):
            continue
        start = dt.datetime.fromisoformat(e["start_time"]).replace(tzinfo=None)
        end = dt.datetime.fromisoformat(e["end_time"]).replace(tzinfo=None) if e.get("end_time") else None
        if start <= wall and (end is None or wall <= end) and (best is None or start > best[0]):
            best = (start, e)
    return {**best[1], "date": day} if best else None
