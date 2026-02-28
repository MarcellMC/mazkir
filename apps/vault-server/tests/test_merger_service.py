from datetime import date

import pytest

from src.services.merger_service import MergerService, MergedEvent


@pytest.fixture
def calendar_events():
    """Sample calendar events as returned by /calendar/events."""
    return [
        {
            "id": "cal-1",
            "summary": "Gym — Holmes Place",
            "start": "2026-02-27T16:00:00+02:00",
            "end": "2026-02-27T17:30:00+02:00",
            "completed": False,
            "calendar": "Mazkir",
        },
        {
            "id": "cal-2",
            "summary": "Team standup",
            "start": "2026-02-27T10:00:00+02:00",
            "end": "2026-02-27T10:30:00+02:00",
            "completed": False,
            "calendar": "Work",
        },
    ]


@pytest.fixture
def timeline_data():
    """Sample timeline data as returned by TimelineService.get_day()."""
    return {
        "visits": [
            {
                "name": "Holmes Place Dizengoff",
                "address": "Dizengoff St 123, Tel Aviv",
                "lat": 32.1079,
                "lng": 34.6818,
                "place_id": "ChIJtest123",
                "start_time": "2026-02-27T16:05:00+02:00",
                "end_time": "2026-02-27T17:25:00+02:00",
                "duration_minutes": 80,
                "confidence": "high",
            },
            {
                "name": "Carmel Market",
                "lat": 32.0660,
                "lng": 34.7678,
                "place_id": "ChIJmarket",
                "start_time": "2026-02-27T18:30:00+02:00",
                "end_time": "2026-02-27T19:00:00+02:00",
                "duration_minutes": 30,
                "confidence": "medium",
            },
        ],
        "activities": [
            {
                "mode": "transit",
                "distance_meters": 2400,
                "duration_minutes": 12,
                "start_time": "2026-02-27T15:48:00+02:00",
                "end_time": "2026-02-27T16:00:00+02:00",
                "start_lat": 32.0800,
                "start_lng": 34.7800,
                "end_lat": 32.1079,
                "end_lng": 34.6818,
                "polyline": [[32.0800, 34.7800], [32.1079, 34.6818]],
                "confidence": "high",
            },
        ],
    }


@pytest.fixture
def habits_data():
    """Sample habits data as returned by /habits."""
    return [
        {
            "name": "gym",
            "completed_today": True,
            "streak": 15,
            "tokens_per_completion": 10,
        },
    ]


@pytest.fixture
def daily_data():
    """Sample daily data as returned by /daily."""
    return {
        "date": "2026-02-27",
        "tokens_earned": 10,
        "tokens_total": 250,
    }


class TestMergerService:
    def test_merge_calendar_with_timeline_match(
        self, calendar_events, timeline_data, habits_data, daily_data
    ):
        """Calendar gym event + timeline gym visit → single merged event."""
        merger = MergerService(timezone="Asia/Jerusalem")
        events = merger.merge(
            calendar_events=calendar_events,
            timeline_data=timeline_data,
            habits=habits_data,
            daily=daily_data,
        )

        # Find the gym event
        gym = next(e for e in events if "gym" in e.name.lower() or "holmes" in e.name.lower())
        assert gym.source == "merged"
        assert gym.location is not None
        assert gym.location["name"] == "Holmes Place Dizengoff"
        assert gym.location["lat"] == pytest.approx(32.1079, abs=0.001)

    def test_unmatched_calendar_event_preserved(
        self, calendar_events, timeline_data, habits_data, daily_data
    ):
        """Calendar event with no timeline match → kept as calendar-only."""
        merger = MergerService(timezone="Asia/Jerusalem")
        events = merger.merge(
            calendar_events=calendar_events,
            timeline_data=timeline_data,
            habits=habits_data,
            daily=daily_data,
        )

        standup = next(e for e in events if "standup" in e.name.lower())
        assert standup.source == "calendar"
        assert standup.location is None

    def test_unmatched_timeline_visit_becomes_unplanned_stop(
        self, calendar_events, timeline_data, habits_data, daily_data
    ):
        """Timeline visit with no calendar match → unplanned_stop."""
        merger = MergerService(timezone="Asia/Jerusalem")
        events = merger.merge(
            calendar_events=calendar_events,
            timeline_data=timeline_data,
            habits=habits_data,
            daily=daily_data,
        )

        market = next(e for e in events if "carmel" in e.name.lower())
        assert market.type == "unplanned_stop"
        assert market.source == "timeline"

    def test_transit_activity_becomes_route(
        self, calendar_events, timeline_data, habits_data, daily_data
    ):
        """Activity segments → transit events with route data."""
        merger = MergerService(timezone="Asia/Jerusalem")
        events = merger.merge(
            calendar_events=calendar_events,
            timeline_data=timeline_data,
            habits=habits_data,
            daily=daily_data,
        )

        transit = [e for e in events if e.type == "transit"]
        assert len(transit) >= 1
        assert transit[0].route_from is not None
        assert transit[0].route_from["mode"] == "transit"

    def test_habit_attached_to_matching_event(
        self, calendar_events, timeline_data, habits_data, daily_data
    ):
        """Gym habit → attached to gym calendar event."""
        merger = MergerService(timezone="Asia/Jerusalem")
        events = merger.merge(
            calendar_events=calendar_events,
            timeline_data=timeline_data,
            habits=habits_data,
            daily=daily_data,
        )

        gym = next(e for e in events if "gym" in e.name.lower() or "holmes" in e.name.lower())
        assert gym.habit is not None
        assert gym.habit["completed"] is True
        assert gym.habit["streak"] == 15

    def test_events_sorted_chronologically(
        self, calendar_events, timeline_data, habits_data, daily_data
    ):
        """All events sorted by start_time."""
        merger = MergerService(timezone="Asia/Jerusalem")
        events = merger.merge(
            calendar_events=calendar_events,
            timeline_data=timeline_data,
            habits=habits_data,
            daily=daily_data,
        )

        times = [e.start_time for e in events]
        assert times == sorted(times)

    def test_merged_event_serializes_to_dict(
        self, calendar_events, timeline_data, habits_data, daily_data
    ):
        """MergedEvent can be serialized to dict for JSON response."""
        merger = MergerService(timezone="Asia/Jerusalem")
        events = merger.merge(
            calendar_events=calendar_events,
            timeline_data=timeline_data,
            habits=habits_data,
            daily=daily_data,
        )

        for event in events:
            d = event.model_dump()
            assert "id" in d
            assert "name" in d
            assert "type" in d
            assert "start_time" in d
