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


from src.services.events_service import EventsService


def _cal(id_="cal1", summary="Standup", start="2026-08-29T09:05", end="2026-08-29T10:00"):
    return {"id": id_, "summary": summary, "start": start, "end": end,
            "completed": False, "calendar": "Mazkir"}


def test_calendar_event_carries_its_calendar_id():
    m = MergerService()
    events = m.merge(calendar_events=[_cal()], timeline_data={"visits": [], "activities": []})
    assert events[0].source_ids == {"calendar_id": "cal1"}


def test_unplanned_stop_source_id_is_stable_for_the_same_visit():
    visit = {"name": "Xoho", "start_time": "2026-08-29T11:00", "end_time": "2026-08-29T12:00",
             "duration_minutes": 60, "lat": 32.07, "lng": 34.78, "place_id": "p123"}
    m = MergerService()
    a = m.merge(calendar_events=[], timeline_data={"visits": [visit], "activities": []})
    b = m.merge(calendar_events=[], timeline_data={"visits": [dict(visit)], "activities": []})
    assert a[0].source_ids == b[0].source_ids
    assert a[0].source_ids != {}


def test_merger_no_longer_guesses_an_activity():
    """CATEGORY_KEYWORDS targeted the single-facet model Phase 1 replaced.
    Blocks must arrive unclassified; Ship 6 fills `activity`."""
    m = MergerService()
    events = m.merge(
        calendar_events=[_cal(summary="Gym session")],
        timeline_data={"visits": [], "activities": []},
    )
    assert events[0].activity is None


def test_merged_event_survives_a_reopen_with_its_id_and_state(tmp_path):
    """Regression: without source_ids, refresh_events appends every fresh
    event as new and drops the persisted copy, so approval could never
    survive an open. Ship 5 depends on this holding."""
    m = MergerService()
    svc = EventsService(tmp_path)

    def fresh():
        return [e.model_dump() for e in m.merge(
            calendar_events=[_cal()], timeline_data={"visits": [], "activities": []},
        )]

    first = svc.refresh_events("2026-08-29", fresh())
    original_id = first[0]["id"]
    first[0]["state"] = "approved"
    first[0]["activity"] = "meetings"
    svc.save_events("2026-08-29", first)

    second = svc.refresh_events("2026-08-29", fresh())
    assert len(second) == 1
    assert second[0]["id"] == original_id
    assert second[0]["state"] == "approved"
    assert second[0]["activity"] == "meetings"
