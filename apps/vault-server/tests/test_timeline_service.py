import json
from datetime import date
from pathlib import Path

import pytest

from src.services.timeline_service import TimelineService


SAMPLE_LEGACY_DATA = {
    "timelineObjects": [
        {
            "placeVisit": {
                "location": {
                    "latitudeE7": 321078900,
                    "longitudeE7": 346818400,
                    "name": "Holmes Place Dizengoff",
                    "address": "Dizengoff St 123, Tel Aviv",
                    "placeId": "ChIJtest123",
                    "locationConfidence": 85.0,
                },
                "duration": {
                    "startTimestamp": "2026-02-27T16:00:00.000Z",
                    "endTimestamp": "2026-02-27T17:30:00.000Z",
                },
                "placeConfidence": "HIGH_CONFIDENCE",
                "visitConfidence": 95,
            }
        },
        {
            "activitySegment": {
                "startLocation": {"latitudeE7": 321078900, "longitudeE7": 346818400},
                "endLocation": {"latitudeE7": 321085000, "longitudeE7": 346825000},
                "duration": {
                    "startTimestamp": "2026-02-27T15:30:00.000Z",
                    "endTimestamp": "2026-02-27T16:00:00.000Z",
                },
                "distance": 2400,
                "activityType": "IN_BUS",
                "confidence": "HIGH",
                "waypointPath": {
                    "waypoints": [
                        {"latE7": 321078900, "lngE7": 346818400},
                        {"latE7": 321085000, "lngE7": 346825000},
                    ]
                },
            }
        },
    ]
}


SAMPLE_NEW_FORMAT_DATA = {
    "semanticSegments": [
        {
            "startTime": "2026-02-27T16:00:00.000Z",
            "endTime": "2026-02-27T17:30:00.000Z",
            "visit": {
                "topCandidate": {
                    "placeId": "ChIJtest456",
                    "semanticType": "TYPE_SEARCHED_ADDRESS",
                    "probability": 0.85,
                    "placeLocation": {
                        "latLng": "32.1079°N, 34.6818°E"
                    }
                }
            }
        },
        {
            "startTime": "2026-02-27T15:30:00.000Z",
            "endTime": "2026-02-27T16:00:00.000Z",
            "activity": {
                "topCandidate": {
                    "type": "IN_BUS",
                    "probability": 0.9
                },
                "distanceMeters": 2400.0
            },
            "timelinePath": [
                {"point": "32.1079°N, 34.6818°E", "time": "2026-02-27T15:30:00.000Z"},
                {"point": "32.1085°N, 34.6825°E", "time": "2026-02-27T15:45:00.000Z"}
            ]
        }
    ]
}


@pytest.fixture
def timeline_path(tmp_path):
    """Create a temporary timeline data directory with sample files."""
    timeline_dir = tmp_path / "timeline"
    timeline_dir.mkdir()

    # Legacy format: monthly file
    month_dir = timeline_dir / "Semantic Location History" / "2026"
    month_dir.mkdir(parents=True)
    (month_dir / "2026_FEBRUARY.json").write_text(json.dumps(SAMPLE_LEGACY_DATA))

    return timeline_dir


@pytest.fixture
def timeline_path_new_format(tmp_path):
    """Create timeline directory with new on-device format."""
    timeline_dir = tmp_path / "timeline"
    timeline_dir.mkdir()

    # New format: single file per export
    (timeline_dir / "Timeline.json").write_text(json.dumps(SAMPLE_NEW_FORMAT_DATA))

    return timeline_dir


@pytest.fixture
def timeline_service(timeline_path):
    return TimelineService(timeline_path, timezone="Asia/Jerusalem")


@pytest.fixture
def timeline_service_new(timeline_path_new_format):
    return TimelineService(timeline_path_new_format, timezone="Asia/Jerusalem")


class TestTimelineServiceLegacy:
    def test_get_visits_for_date(self, timeline_service):
        visits = timeline_service.get_visits(date(2026, 2, 27))
        assert len(visits) == 1
        assert visits[0]["name"] == "Holmes Place Dizengoff"
        assert visits[0]["lat"] == pytest.approx(32.10789, abs=0.001)
        assert visits[0]["lng"] == pytest.approx(34.68184, abs=0.001)

    def test_get_activities_for_date(self, timeline_service):
        activities = timeline_service.get_activities(date(2026, 2, 27))
        assert len(activities) == 1
        assert activities[0]["mode"] == "transit"
        assert activities[0]["distance_meters"] == 2400

    def test_get_visits_empty_for_other_date(self, timeline_service):
        visits = timeline_service.get_visits(date(2026, 2, 20))
        assert visits == []

    def test_get_day_data_returns_both(self, timeline_service):
        data = timeline_service.get_day(date(2026, 2, 27))
        assert "visits" in data
        assert "activities" in data
        assert len(data["visits"]) == 1
        assert len(data["activities"]) == 1

    def test_waypoints_parsed_to_polyline(self, timeline_service):
        activities = timeline_service.get_activities(date(2026, 2, 27))
        polyline = activities[0]["polyline"]
        assert len(polyline) == 2
        assert polyline[0] == pytest.approx([32.10789, 34.68184], abs=0.001)


class TestTimelineServiceNewFormat:
    def test_get_visits_new_format(self, timeline_service_new):
        visits = timeline_service_new.get_visits(date(2026, 2, 27))
        assert len(visits) == 1
        assert visits[0]["place_id"] == "ChIJtest456"

    def test_get_activities_new_format(self, timeline_service_new):
        activities = timeline_service_new.get_activities(date(2026, 2, 27))
        assert len(activities) == 1
        assert activities[0]["mode"] == "transit"


class TestTimelineServiceMissing:
    def test_no_data_dir_returns_empty(self, tmp_path):
        service = TimelineService(tmp_path / "nonexistent", timezone="Asia/Jerusalem")
        data = service.get_day(date(2026, 2, 27))
        assert data["visits"] == []
        assert data["activities"] == []
