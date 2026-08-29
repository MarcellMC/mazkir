"""Merge calendar events, timeline data, and PKM vault data into MergedEvent[]."""

import hashlib
import re
import uuid
from datetime import datetime
from math import radians, sin, cos, sqrt, atan2
from typing import Any

import pytz
from pydantic import BaseModel, Field

from src.services.daily_tasks import parse_all_todos


class MergedEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])

    # What
    name: str
    type: str  # 'habit' | 'task' | 'calendar' | 'unplanned_stop' | 'transit' | 'home'
    activity: str | None = None

    # When
    start_time: str  # ISO format
    end_time: str
    duration_minutes: int = 0

    # Where
    location: dict[str, Any] | None = None  # {name, lat, lng, place_id}

    # How you got there
    route_from: dict[str, Any] | None = None  # {mode, distance_meters, duration_minutes, polyline, confidence}

    # PKM integration
    habit: dict[str, Any] | None = None  # {name, completed, streak, tokens_earned}
    tokens_earned: int = 0

    # Whether the thing this block stands for is done. Every source has an
    # answer: a checked `- [x]` checkbox, a calendar event the sync marked
    # with the completion prefix, a habit whose target was met today. Before
    # this it only existed inside `habit`, so a checked timed todo rendered
    # identically to an outstanding one and appeared nowhere else (`/day`
    # filters timed todos out of the Todos list, since they are blocks).
    completed: bool = False

    # Generated assets (populated later)
    assets: dict[str, str] | None = None

    # Data quality
    source: str  # 'calendar' | 'timeline' | 'merged'
    confidence: str = "medium"  # 'high' | 'medium' | 'low'

    # Reconciliation key. EventsService.refresh_events matches a freshly
    # merged event to its persisted counterpart through this, which is what
    # lets an id — and anything the user set on the event — survive a
    # re-merge. Exactly one entry; the key names the originating source.
    source_ids: dict[str, str] = Field(default_factory=dict)


# Fuzzy matching config
TIME_MATCH_MINUTES = 30
DISTANCE_MATCH_METERS = 500


def _stable_id(*parts: object) -> str:
    """A deterministic short id for a source that has no id of its own.

    Timeline visits and transit segments carry no stable identifier, so we
    derive one from the fields that identify them. Same input, same id, on
    every re-merge — which is the whole point.
    """
    raw = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def _slugify(name: str) -> str:
    """Lowercase, hyphenated form of a habit name, for a readable source id.

    Computed once per habit at the call site (rather than inside the
    MergedEvent constructor) so `merge` can also use it as the key for the
    occurrence counter that disambiguates habits that slugify identically.
    """
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _normalize_for_match(name: str) -> str:
    """Casefolded name with separators flattened to single spaces.

    Lets "Dog-Walk", "Dog  Walk" and "Dog — Walk" all read as the same
    phrase, so `_find_matching_habit`'s containment test is not defeated by
    punctuation the user happened to type. Anything that is not a letter or
    a digit becomes a space, which also strips the `🎯` prefix
    `CalendarService.sync_habit` puts on a habit's calendar event. `\\w` is
    unicode-aware here, so a Hebrew habit name survives normalization
    rather than collapsing to the empty string.
    """
    return " ".join(re.sub(r"\W+", " ", name.casefold(), flags=re.UNICODE).split())


class MergerService:
    def __init__(self, timezone: str = "Asia/Jerusalem"):
        self.tz = pytz.timezone(timezone)

    def merge(
        self,
        calendar_events: list[dict],
        timeline_data: dict,
        habits: list[dict] | None = None,
        daily: dict | None = None,
        daily_body: str = "",
        date: str = "",
    ) -> list[MergedEvent]:
        visits = timeline_data.get("visits", [])
        activities = timeline_data.get("activities", [])
        habits = habits or []

        merged: list[MergedEvent] = []
        matched_visit_indices: set[int] = set()
        # Keyed by object identity (id()), not by name: two distinct habit
        # files can share a display name, and a name-keyed set would treat
        # them as one — attaching one to a calendar event would then
        # silently suppress the other's standalone block too.
        attached_habits: set[int] = set()

        # Step 1: Match calendar events to timeline visits
        for cal in calendar_events:
            best_visit_idx = self._find_matching_visit(cal, visits, matched_visit_indices)

            if best_visit_idx is not None:
                # Merged event
                visit = visits[best_visit_idx]
                matched_visit_indices.add(best_visit_idx)
                event = self._create_merged_event(cal, visit)
            else:
                # Calendar-only event
                event = self._create_calendar_event(cal)

            # Attach habit data
            habit_match = self._find_matching_habit(event.name, habits)
            if habit_match:
                attached_habits.add(id(habit_match))
                event.habit = {
                    "name": habit_match["name"],
                    "completed": habit_match.get("completed_today", False),
                    "streak": habit_match.get("streak", 0),
                    "tokens_earned": habit_match.get("tokens_per_completion", 0),
                }
                if event.habit["completed"]:
                    event.tokens_earned = event.habit["tokens_earned"]
                    # An attached habit suppresses its own standalone block,
                    # so this event is the only row the habit gets. Its
                    # completion has to travel with it.
                    event.completed = True

            merged.append(event)

        # Step 2: Unmatched timeline visits → unplanned stops
        for i, visit in enumerate(visits):
            if i not in matched_visit_indices:
                merged.append(self._create_unplanned_stop(visit))

        # Step 3: Activity segments → transit events
        for activity in activities:
            merged.append(self._create_transit_event(activity))

        # Scheduled habits that no calendar event claimed. Without this,
        # dropping schedule[] would lose a habit that has a time but no
        # calendar entry — which is most of them.
        if date:
            # Occurrence counter, scoped to the slug that collides — same
            # rationale as the note-block counter above. Two differently
            # named habits ("Dog Walk", "Dog-Walk") can slugify identically;
            # a global counter would also shift an unrelated habit's id
            # whenever an unrelated one was inserted earlier in the list.
            habit_slug_occurrences: dict[str, int] = {}
            for h in habits:
                if h.get("scheduled_at") and id(h) not in attached_habits:
                    slug = _slugify(h.get("name", ""))
                    occurrence = habit_slug_occurrences.get(slug, 0)
                    habit_slug_occurrences[slug] = occurrence + 1
                    merged.append(self._create_habit_block(h, date, slug, occurrence))

        # Timed checkboxes from the note body. The note is a worksurface; the
        # ledger is the source of truth for temporal data, so a checkbox that
        # has acquired a time is a block. It is regenerated from the note on
        # every merge and matched by source_ids, so nothing needs persisting
        # and no write path is involved.
        if daily_body and date:
            # Occurrence counter, scoped to (section, text, scheduled_at)
            # rather than a single running index over all todos. A global
            # counter would make every id downstream of an inserted
            # checkbox shift, so adding one unrelated line above a block
            # would orphan it on the next merge. Scoping to the identical
            # triple means a normal insertion changes nothing, and only
            # genuine duplicates receive distinct occurrence numbers.
            occurrence_counts: dict[tuple[str | None, str, str], int] = {}
            for todo in parse_all_todos(daily_body):
                if todo.scheduled_at:
                    key = (todo.section, todo.text, todo.scheduled_at)
                    occurrence = occurrence_counts.get(key, 0)
                    occurrence_counts[key] = occurrence + 1
                    merged.append(self._create_note_block(todo, date, occurrence))

        # Step 4: Sort chronologically
        merged.sort(key=lambda e: e.start_time)

        # Step 5: Attach route_from to events that follow transit
        self._attach_routes(merged)

        return merged

    def _find_matching_visit(
        self, cal: dict, visits: list[dict], excluded: set[int]
    ) -> int | None:
        """Find the best matching timeline visit for a calendar event."""
        cal_start = self._parse_time(cal.get("start", ""))
        if not cal_start:
            return None

        best_idx = None
        best_time_diff = float("inf")

        for i, visit in enumerate(visits):
            if i in excluded:
                continue
            visit_start = self._parse_time(visit.get("start_time", ""))
            if not visit_start:
                continue

            time_diff = abs((cal_start - visit_start).total_seconds() / 60)
            if time_diff > TIME_MATCH_MINUTES:
                continue

            if time_diff < best_time_diff:
                best_time_diff = time_diff
                best_idx = i

        return best_idx

    def _create_merged_event(self, cal: dict, visit: dict) -> MergedEvent:
        name = cal.get("summary", "Unknown")
        return MergedEvent(
            name=name,
            type=self._infer_type(cal),
            start_time=cal.get("start", visit["start_time"]),
            end_time=cal.get("end", visit["end_time"]),
            duration_minutes=visit.get("duration_minutes", 0),
            location={
                "name": visit["name"],
                "lat": visit["lat"],
                "lng": visit["lng"],
                "place_id": visit.get("place_id"),
            },
            completed=bool(cal.get("completed", False)),
            source="merged",
            confidence=visit.get("confidence", "medium"),
            source_ids={"calendar_id": str(cal.get("id", "")) or _stable_id(
                cal.get("summary"), cal.get("start"))},
        )

    def _create_calendar_event(self, cal: dict) -> MergedEvent:
        name = cal.get("summary", "Unknown")
        return MergedEvent(
            name=name,
            type=self._infer_type(cal),
            start_time=cal.get("start", ""),
            end_time=cal.get("end", ""),
            duration_minutes=self._calc_duration(cal.get("start", ""), cal.get("end", "")),
            # CalendarService derives this from the summary's completion
            # prefix or the event colour; it was read from the API and then
            # discarded here.
            completed=bool(cal.get("completed", False)),
            source="calendar",
            confidence="medium",
            source_ids={"calendar_id": str(cal.get("id", "")) or _stable_id(
                name, cal.get("start"))},
        )

    def _create_note_block(self, todo, date: str, occurrence: int = 0) -> MergedEvent:
        """A timed checkbox is a block: known start, known length.

        Untimed checkboxes are filtered out by the caller — without a start
        there is no interval, and coverage arithmetic needs one.

        `occurrence` disambiguates duplicate checkboxes (identical section,
        text, and time) so they hash to distinct ids instead of colliding —
        see the caller for why the counter is scoped rather than global.
        """
        start = f"{date}T{todo.scheduled_at}"
        minutes = todo.duration_minutes or 0
        hh, mm = (int(x) for x in todo.scheduled_at.split(":"))
        end_total = hh * 60 + mm + minutes
        # Clamp rather than wrap: `% 24` would carry a past-midnight block
        # into the next day's 00:xx, putting its end before its own start.
        # The coverage builder drops any interval whose end isn't after its
        # start, so that would silently delete the block instead of
        # rendering it. Storage splits at midnight (Ship 5); here we just
        # clip the visible block to the end of this date.
        end_total = min(end_total, 23 * 60 + 59)
        end = f"{date}T{end_total // 60:02d}:{end_total % 60:02d}"
        return MergedEvent(
            name=todo.text,
            type="task",
            start_time=start,
            end_time=end,
            duration_minutes=minutes,
            completed=todo.state == "checked",
            source="daily-note",
            confidence="high",
            source_ids={"note_line": _stable_id(
                date, todo.section, todo.text, todo.scheduled_at, occurrence)},
        )

    def _create_habit_block(
        self, habit: dict, date: str, slug: str, occurrence: int = 0
    ) -> MergedEvent:
        """A scheduled habit with no calendar event of its own.

        Habits that DO have a calendar event are attached to it by the
        existing name match in step 1; emitting a block for those as well
        would render the same commitment twice.

        `slug` is precomputed by the caller (it also drives the occurrence
        counter there). `occurrence` disambiguates habits that slugify to
        the same string — "Dog Walk" and "Dog-Walk" both become
        `dog-walk` — so they hash to distinct ids instead of one silently
        overwriting the other's persisted data in EventsService's
        source-id-keyed reconciliation.
        """
        name = habit.get("name", "")
        scheduled_at = habit["scheduled_at"]
        minutes = habit.get("duration_minutes") or 0
        hh, mm = (int(x) for x in scheduled_at.split(":"))
        end_total = hh * 60 + mm + minutes
        # Clamp rather than wrap: `% 24` would carry a past-midnight block
        # into the next day's 00:xx, putting its end before its own start.
        # The coverage builder drops any interval whose end isn't after its
        # start, so that would silently delete the block instead of
        # rendering it. Storage splits at midnight (Ship 5); here we just
        # clip the visible block to the end of this date.
        end_total = min(end_total, 23 * 60 + 59)
        end = f"{date}T{end_total // 60:02d}:{end_total % 60:02d}"
        slug_id = f"{date}:{slug}" if occurrence == 0 else f"{date}:{slug}-{occurrence + 1}"
        completed = habit.get("completed_today", False)
        return MergedEvent(
            name=name,
            type="habit",
            start_time=f"{date}T{scheduled_at}",
            end_time=end,
            duration_minutes=minutes,
            habit={
                "name": name,
                "completed": completed,
                "streak": habit.get("streak", 0),
                "tokens_earned": habit.get("tokens_per_completion", 0),
                # /daily renders these as "1/2". Without them the bot can only
                # show a binary box, which is the Phase 1 §11 carry-forward.
                "completions_today": habit.get("completions_today", 0),
                "daily_target": habit.get("daily_target", 1),
            },
            tokens_earned=habit.get("tokens_per_completion", 0) if completed else 0,
            completed=completed,
            source="habit",
            confidence="high",
            source_ids={"habit_slug": slug_id},
        )

    def _create_unplanned_stop(self, visit: dict) -> MergedEvent:
        return MergedEvent(
            name=visit["name"],
            type="unplanned_stop",
            start_time=visit["start_time"],
            end_time=visit["end_time"],
            duration_minutes=visit.get("duration_minutes", 0),
            location={
                "name": visit["name"],
                "lat": visit["lat"],
                "lng": visit["lng"],
                "place_id": visit.get("place_id"),
            },
            source="timeline",
            confidence=visit.get("confidence", "low"),
            source_ids={"visit_id": _stable_id(
                visit["start_time"], visit.get("place_id"), visit["name"])},
        )

    def _create_transit_event(self, activity: dict) -> MergedEvent:
        return MergedEvent(
            name=f"Transit ({activity['mode']})",
            type="transit",
            start_time=activity["start_time"],
            end_time=activity["end_time"],
            duration_minutes=activity.get("duration_minutes", 0),
            route_from={
                "mode": activity["mode"],
                "distance_meters": activity.get("distance_meters", 0),
                "duration_minutes": activity.get("duration_minutes", 0),
                "polyline": activity.get("polyline", []),
                "confidence": activity.get("confidence", "low"),
            },
            source="timeline",
            confidence=activity.get("confidence", "low"),
            source_ids={"transit_id": _stable_id(
                activity["start_time"], activity["mode"])},
        )

    def _attach_routes(self, events: list[MergedEvent]) -> None:
        """Move route_from from transit events to the next non-transit event."""
        for i, event in enumerate(events):
            if event.type == "transit" and event.route_from:
                # Find next non-transit event
                for j in range(i + 1, len(events)):
                    if events[j].type != "transit":
                        events[j].route_from = event.route_from
                        break

    def _find_matching_habit(self, event_name: str, habits: list[dict]) -> dict | None:
        """Find the habit a calendar event stands for, by whole-phrase match.

        A match here does more than decorate the event: it makes the habit
        `attached`, and an attached habit emits no standalone block. So a
        false positive does not merely mislabel a row — it removes one,
        and reconciliation then reads the missing row as "deleted
        upstream" and destroys the persisted event with any photo on it.

        This used to fall back to bare single-word overlap, which made
        every common word a match: a "Design review" meeting claimed the
        "Review Email" habit, and "Walk to office" claimed "Dog Walk".
        Now one name must contain the other as a whole phrase.

        The alternative considered — keeping word overlap but gating it on
        time proximity — was rejected because `scheduled_at` is optional
        (it is `null` on habits in this vault today). Gating on it would
        silently stop matching exactly the habits that have no standalone
        block to fall back on, so they would vanish from `/day` entirely.
        Phrase containment needs no extra inputs and covers the path that
        actually generates these events: `CalendarService.sync_habit`
        writes the summary as `🎯 {name}`, the habit name verbatim.
        """
        name_norm = _normalize_for_match(event_name)
        for habit in habits:
            habit_norm = _normalize_for_match(habit.get("name", ""))
            if not habit_norm or not name_norm:
                continue
            if habit_norm in name_norm or name_norm in habit_norm:
                return habit
        return None

    @staticmethod
    def _infer_type(cal: dict) -> str:
        calendar_name = cal.get("calendar", "").lower()
        if "mazkir" in calendar_name:
            return "habit"
        return "calendar"

    def _parse_time(self, ts: str) -> datetime | None:
        if not ts:
            return None
        try:
            return datetime.fromisoformat(ts)
        except ValueError:
            return None

    def _calc_duration(self, start: str, end: str) -> int:
        s = self._parse_time(start)
        e = self._parse_time(end)
        if s and e:
            return int((e - s).total_seconds() / 60)
        return 0

    @staticmethod
    def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """Distance in meters between two lat/lng points."""
        R = 6371000
        dlat = radians(lat2 - lat1)
        dlng = radians(lng2 - lng1)
        a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
        return R * 2 * atan2(sqrt(a), sqrt(1 - a))
