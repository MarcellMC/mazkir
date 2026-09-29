"""Read the time words a parse clause carries: clocks, durations, shifts, days.

Pure: strings in, numbers and dates out. The parse copies your words as
written ("around 3:00", "7hr", "yesterday"); turning them into instants is
the resolver's job, and this module is the vocabulary it reads them with.
English, plus the Russian and Hebrew words that appear in the history.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

NOW_WORDS = frozenset({
    "now", "just now", "right now", "just", "just returned", "just back",
    "сейчас", "только что", "עכשיו",
})

_HEDGE = re.compile(r"around|about|approx|roughly|~|\d\s*-?ish\b|около|примерно|בערך", re.IGNORECASE)
_CLOCK = re.compile(r"(?<!\d)(\d{1,2})(?:[:.](\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?(?!\d)", re.IGNORECASE)
# Units of a length, in the three languages: after a number they make it a duration.
_HOUR_UNITS = r"hours?|hrs?|h|час(?:а|ов)?|ч|שעות|שעה"
_MINUTE_UNITS = r"minutes?|mins?|m|минут[аыу]?|мин|דקות|דקה"
_UNIT_AFTER = re.compile(rf"\s*(?:{_HOUR_UNITS}|{_MINUTE_UNITS})(?!\w)", re.IGNORECASE)
# "в 3 часа", "к 5 часам", "at 3 o'clock": the number names an hour on the
# clock, although "часа" after a bare number would make it a length (A1
# Ruling 18b).
_OCLOCK = re.compile(r"(?<!\w)(?:в|к|at)\s+(\d{1,2})\s*(?:час(?:а|ов|ам)?|o'?clock)(?!\w)", re.IGNORECASE)


@dataclass(frozen=True)
class Clock:
    hour: int          # 0-23, as written or after am/pm
    minute: int
    ambiguous: bool    # an hour 1-12 with no am/pm and no leading zero: two readings
    hedged: bool       # "around 3:00" → approx precision


@dataclass(frozen=True)
class DayRef:
    kind: str                    # "date" | "night" | "weekday"
    date: dt.date | None = None
    night_offset: int = 0        # "tonight" 0, "last night" -1
    weekday: int | None = None   # Monday = 0


def is_now(text: str | None) -> bool:
    return bool(text) and text.strip().lower() in NOW_WORDS


def parse_clock(text: str | None) -> Clock | None:
    """A clock time in `text`, or None. "now" is not a clock; see `is_now`.

    A number with a unit after it is a length, not a clock: "15 mins ago"
    sent at 16:00 is 15:45 (see `parse_relative`), never 15:00, and "in 20
    minutes" is never 20:00.
    """
    if not text or is_now(text):
        return None
    oclock = _OCLOCK.search(text)
    if oclock:
        hour = int(oclock.group(1))
        if hour > 23:
            return None
        leading_zero = len(oclock.group(1)) == 2 and oclock.group(1)[0] == "0"
        return Clock(hour, 0, ambiguous=1 <= hour <= 12 and not leading_zero,
                     hedged=bool(_HEDGE.search(text)))
    match = next((m for m in _CLOCK.finditer(text) if not _UNIT_AFTER.match(text, m.end())), None)
    if not match:
        return None
    raw_hour, raw_minute, meridiem = match.groups()
    hour, minute = int(raw_hour), int(raw_minute or 0)
    if hour > 23 or minute > 59:
        return None
    hedged = bool(_HEDGE.search(text))
    if meridiem:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if meridiem.lower().startswith("p") else 0)
        return Clock(hour, minute, ambiguous=False, hedged=hedged)
    leading_zero = len(raw_hour) == 2 and raw_hour[0] == "0"
    return Clock(hour, minute, ambiguous=1 <= hour <= 12 and not leading_zero, hedged=hedged)


_HALF_HOUR = ("half an hour", "half hour", "полчаса", "חצי שעה")
_H_M = re.compile(r"(\d+)\s*h\s*(\d{1,2})(?!\d)")
_DURATION_PART = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*"
    r"(hours?|hrs?|h|ч|час(?:а|ов)?|minutes?|mins?|m|мин(?:ут[аы]?)?)(?![a-zа-я])",
    re.IGNORECASE,
)


def parse_duration(text: str | None) -> int | None:
    """Minutes in `text` ("30 mins", "7hr", "1h30", "1.5h", "half an hour"), or None."""
    if not text:
        return None
    lowered = text.lower().strip()
    if any(phrase in lowered for phrase in _HALF_HOUR):
        return 30
    hours_minutes = _H_M.search(lowered)
    if hours_minutes:
        return int(hours_minutes.group(1)) * 60 + int(hours_minutes.group(2))
    total, found = 0.0, False
    for number, unit in _DURATION_PART.findall(lowered):
        value = float(number.replace(",", "."))
        total += value * 60 if unit[0] in "hч" else value
        found = True
    if found:
        return round(total)
    if re.fullmatch(r"(an?|one)?\s*(hour|час|שעה)", lowered):
        return 60
    return None


_AMOUNT = rf"(\d+(?:[.,]\d+)?)\s*({_HOUR_UNITS}|{_MINUTE_UNITS})(?!\w)"
# Relative times: the direction word, and whether it comes before the amount.
_RELATIVE_TIME = {
    "ago": (-1, False), "назад": (-1, False), "לפני": (-1, True),
    "in": (1, True), "через": (1, True), "בעוד": (1, True),
}
_RELATIVE_PATTERNS = [
    (re.compile(rf"(?<!\w){word}\s+{_AMOUNT}" if before else rf"(?<![\w.,]){_AMOUNT}\s+{word}(?!\w)",
                re.IGNORECASE), sign)
    for word, (sign, before) in _RELATIVE_TIME.items()
]
# Amounts written as words (A1 Ruling 18b): "an hour ago", "через полчаса",
# "לפני שעה". Longest phrase first, so "half an hour ago" is never read as
# "an hour ago".
_WORD_AMOUNTS = sorted({
    "half an hour": 30, "an hour": 60, "one hour": 60, "a minute": 1,
    "полчаса": 30, "час": 60, "минуту": 1,
    "חצי שעה": 30, "שעה": 60, "דקה": 1,
}.items(), key=lambda kv: -len(kv[0]))
_WORD_RELATIVE = [
    (re.compile(rf"(?<!\w){word}\s+{re.escape(phrase)}(?!\w)" if before
                else rf"(?<!\w){re.escape(phrase)}\s+{word}(?!\w)", re.IGNORECASE), sign * minutes)
    for phrase, minutes in _WORD_AMOUNTS
    for word, (sign, before) in _RELATIVE_TIME.items()
]


def parse_relative(text: str | None) -> dt.timedelta | None:
    """A time relative to the message: "15 mins ago" → -15 min, "in 20 minutes" → +20 min, else None.

    Russian and Hebrew too: "15 минут назад", "через 20 минут", "לפני 10 דקות",
    "בעוד 20 דקות". The resolver places it at the message time plus this.
    """
    if not text:
        return None
    for pattern, sign in _RELATIVE_PATTERNS:
        match = pattern.search(text)
        if match:
            value = float(match.group(1).replace(",", "."))
            hours = re.fullmatch(_HOUR_UNITS, match.group(2), re.IGNORECASE) is not None
            return dt.timedelta(minutes=sign * round(value * 60 if hours else value))
    for pattern, minutes in _WORD_RELATIVE:
        if pattern.search(text):
            return dt.timedelta(minutes=minutes)
    return None


_RUN_TOGETHER = re.compile(r"^\s*(\d{1,2}:\d{2}):(\d{1,2}:\d{2})\s*$")


def split_run_together(start: str | None, end: str | None) -> tuple[str | None, str | None]:
    """The typo "06:35:07:35" is a start and an end run together; otherwise both unchanged."""
    match = _RUN_TOGETHER.match(start or "")
    if match and not (end or "").strip():
        return match.group(1), match.group(2)
    return start, end


_EARLIER = ("back", "earlier", "before", "назад", "раньше")
_LATER = ("forward", "later", "ahead", "позже", "вперед", "вперёд")
_SIGN = re.compile(r"(?:^|\s)([+-])\s*\d")


def parse_shift(text: str | None) -> int | None:
    """Signed minutes for an edit: "back 30 mins" → -30, "+15m" → 15. None without a direction."""
    if not text:
        return None
    lowered = text.lower()
    minutes = parse_duration(lowered)
    if minutes is None:
        bare = re.search(r"(\d+)", lowered)
        if not bare:
            return None
        minutes = int(bare.group(1))
    sign = _SIGN.search(lowered)
    if sign:
        return minutes if sign.group(1) == "+" else -minutes
    if any(word in lowered for word in _EARLIER):
        return -minutes
    if any(word in lowered for word in _LATER):
        return minutes
    return None


_NIGHT = {
    "tonight": 0, "this night": 0, "сегодня ночью": 0, "הלילה": 0,
    "last night": -1, "yesterday night": -1, "вчера ночью": -1, "прошлой ночью": -1, "אמש": -1,
}
_RELATIVE = {
    "day before yesterday": -2, "позавчера": -2,
    "yesterday": -1, "вчера": -1, "אתמול": -1,
    "today": 0, "сегодня": 0, "היום": 0,
    "tomorrow": 1, "завтра": 1, "מחר": 1,
}
_WEEKDAYS = {
    "monday": 0, "понедельник": 0, "tuesday": 1, "вторник": 1, "wednesday": 2, "среда": 2, "среду": 2,
    "thursday": 3, "четверг": 3, "friday": 4, "пятница": 4, "пятницу": 4,
    "saturday": 5, "суббота": 5, "субботу": 5, "sunday": 6, "воскресенье": 6,
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}
_MONTHS = {
    "january": 1, "jan": 1, "января": 1, "february": 2, "feb": 2, "февраля": 2,
    "march": 3, "mar": 3, "марта": 3, "april": 4, "apr": 4, "апреля": 4,
    "may": 5, "мая": 5, "june": 6, "jun": 6, "июня": 6, "july": 7, "jul": 7, "июля": 7,
    "august": 8, "aug": 8, "августа": 8, "september": 9, "sept": 9, "sep": 9, "сентября": 9,
    "october": 10, "oct": 10, "октября": 10, "november": 11, "nov": 11, "ноября": 11,
    "december": 12, "dec": 12, "декабря": 12,
}
_WORD = r"(?<![a-zа-яё]){}(?![a-zа-яё])"


def _dated(day: int, month: int, year: int | None, today: dt.date, intent: str) -> DayRef | None:
    """A date as written. Without a year, the nearest one in the direction the clause points."""
    try:
        if year is not None:
            return DayRef("date", date=dt.date(year + 2000 if year < 100 else year, month, day))
        candidate = dt.date(today.year, month, day)
        if intent == "plan" and candidate < today - dt.timedelta(days=1):
            candidate = candidate.replace(year=today.year + 1)
        if intent == "record" and candidate > today + dt.timedelta(days=1):
            candidate = candidate.replace(year=today.year - 1)
        return DayRef("date", date=candidate)
    except ValueError:
        return None


def parse_day(text: str | None, today: dt.date, intent: str) -> DayRef | None:
    """The day a clause names, or None when it names none this module knows."""
    if not text:
        return None
    lowered = text.lower().strip()
    for phrase in sorted(_NIGHT, key=len, reverse=True):
        if phrase in lowered:
            return DayRef("night", night_offset=_NIGHT[phrase])
    for phrase in sorted(_RELATIVE, key=len, reverse=True):
        if phrase in lowered:
            return DayRef("date", date=today + dt.timedelta(days=_RELATIVE[phrase]))
    iso = re.search(r"(\d{4})-(\d{2})-(\d{2})", lowered)
    if iso:
        return _dated(int(iso[3]), int(iso[2]), int(iso[1]), today, intent)
    numeric = re.search(r"(?<!\d)(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?(?!\d)", lowered)
    if numeric:
        year = int(numeric[3]) if numeric[3] else None
        return _dated(int(numeric[1]), int(numeric[2]), year, today, intent)
    month = next((number for name, number in sorted(_MONTHS.items(), key=lambda kv: -len(kv[0]))
                  if re.search(_WORD.format(name), lowered)), None)
    day_number = re.search(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?(?!\d)", lowered)
    if month and day_number:
        return _dated(int(day_number.group(1)), month, None, today, intent)
    for name, index in sorted(_WEEKDAYS.items(), key=lambda kv: -len(kv[0])):
        if re.search(_WORD.format(name), lowered):
            return DayRef("weekday", weekday=index)
    return None


def weekday_date(weekday: int, today: dt.date, intent: str) -> dt.date:
    """The nearest date with that weekday: forward for a plan, back for a record."""
    if intent == "plan":
        return today + dt.timedelta(days=(weekday - today.weekday()) % 7)
    return today - dt.timedelta(days=(today.weekday() - weekday) % 7)
