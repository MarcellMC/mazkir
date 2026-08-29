"""Merge calendar events, timeline data, and PKM vault data into MergedEvent[]."""

import hashlib
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
                event.habit = {
                    "name": habit_match["name"],
                    "completed": habit_match.get("completed_today", False),
                    "streak": habit_match.get("streak", 0),
                    "tokens_earned": habit_match.get("tokens_per_completion", 0),
                }
                if event.habit["completed"]:
                    event.tokens_earned = event.habit["tokens_earned"]

            merged.append(event)

        # Step 2: Unmatched timeline visits → unplanned stops
        for i, visit in enumerate(visits):
            if i not in matched_visit_indices:
                merged.append(self._create_unplanned_stop(visit))

        # Step 3: Activity segments → transit events
        for activity in activities:
            merged.append(self._create_transit_event(activity))

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
            source="daily-note",
            confidence="high",
            source_ids={"note_line": _stable_id(
                date, todo.section, todo.text, todo.scheduled_at, occurrence)},
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
        """Find a habit that matches an event name by keyword overlap."""
        name_lower = event_name.lower()
        for habit in habits:
            habit_name = habit.get("name", "").lower()
            if habit_name in name_lower or name_lower in habit_name:
                return habit
            # Check if any word overlaps
            habit_words = set(habit_name.split())
            name_words = set(name_lower.replace("\u2014", " ").replace("-", " ").split())
            if habit_words & name_words:
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
