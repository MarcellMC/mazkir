"""Merge calendar events, timeline data, and PKM vault data into MergedEvent[]."""

import uuid
from datetime import datetime
from math import radians, sin, cos, sqrt, atan2
from typing import Any

import pytz
from pydantic import BaseModel, Field


class MergedEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])

    # What
    name: str
    type: str  # 'habit' | 'task' | 'calendar' | 'unplanned_stop' | 'transit' | 'home'
    activity_category: str | None = None

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


# Fuzzy matching config
TIME_MATCH_MINUTES = 30
DISTANCE_MATCH_METERS = 500

# Keywords for activity category detection
CATEGORY_KEYWORDS = {
    "gym": ["gym", "fitness", "workout", "holmes place", "crossfit"],
    "walk": ["walk", "hike", "park", "dog walk"],
    "cafe": ["cafe", "café", "coffee", "xoho", "starbucks"],
    "shopping": ["market", "mall", "shop", "store", "carmel"],
    "work": ["work", "office", "meeting", "standup", "deep work"],
    "social": ["dinner", "lunch", "drinks", "party", "friend"],
}


class MergerService:
    def __init__(self, timezone: str = "Asia/Jerusalem"):
        self.tz = pytz.timezone(timezone)

    def merge(
        self,
        calendar_events: list[dict],
        timeline_data: dict,
        habits: list[dict] | None = None,
        daily: dict | None = None,
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
            activity_category=self._infer_category(name),
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
        )

    def _create_calendar_event(self, cal: dict) -> MergedEvent:
        name = cal.get("summary", "Unknown")
        return MergedEvent(
            name=name,
            type=self._infer_type(cal),
            activity_category=self._infer_category(name),
            start_time=cal.get("start", ""),
            end_time=cal.get("end", ""),
            duration_minutes=self._calc_duration(cal.get("start", ""), cal.get("end", "")),
            source="calendar",
            confidence="medium",
        )

    def _create_unplanned_stop(self, visit: dict) -> MergedEvent:
        return MergedEvent(
            name=visit["name"],
            type="unplanned_stop",
            activity_category=self._infer_category(visit["name"]),
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

    @staticmethod
    def _infer_category(name: str) -> str | None:
        name_lower = name.lower()
        for category, keywords in CATEGORY_KEYWORDS.items():
            if any(kw in name_lower for kw in keywords):
                return category
        return None

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
