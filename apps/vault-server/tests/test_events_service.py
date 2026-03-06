"""Tests for EventsService — merged event persistence."""

import json
import pytest

from src.services.events_service import EventsService, PhotoRef


@pytest.fixture
def events_service(tmp_path):
    return EventsService(events_path=tmp_path)


class TestReadWrite:
    def test_get_events_empty_day(self, events_service):
        events = events_service.get_events("2026-03-04")
        assert events == []

    def test_save_and_read_events(self, events_service):
        events = [
            {
                "name": "Team standup",
                "type": "calendar",
                "start_time": "2026-03-04T10:00:00",
                "end_time": "2026-03-04T10:30:00",
                "source": "calendar",
            }
        ]
        events_service.save_events("2026-03-04", events)
        result = events_service.get_events("2026-03-04")
        assert len(result) == 1
        assert result[0]["name"] == "Team standup"
        assert "id" in result[0]  # ID was assigned

    def test_stable_ids_on_rewrite(self, events_service):
        events = [{"name": "Lunch", "type": "calendar", "start_time": "12:00", "end_time": "13:00", "source": "calendar"}]
        events_service.save_events("2026-03-04", events)
        first_id = events_service.get_events("2026-03-04")[0]["id"]

        # Save again — same event keeps its ID
        events_service.save_events("2026-03-04", events_service.get_events("2026-03-04"))
        second_id = events_service.get_events("2026-03-04")[0]["id"]
        assert first_id == second_id


class TestCreateEvent:
    def test_create_event_minimal(self, events_service):
        result = events_service.create_event(
            date="2026-03-04",
            name="Coffee at cafe",
            start_time="2026-03-04T15:00:00",
        )
        assert "id" in result
        events = events_service.get_events("2026-03-04")
        assert len(events) == 1
        assert events[0]["name"] == "Coffee at cafe"
        assert events[0]["source"] == "manual"

    def test_create_event_with_photo(self, events_service):
        result = events_service.create_event(
            date="2026-03-04",
            name="Dog walk",
            start_time="2026-03-04T14:30:00",
            photo_path="data/media/2026-03-04/photo.jpg",
            caption="Walking the dog",
        )
        events = events_service.get_events("2026-03-04")
        assert len(events[0]["photos"]) == 1
        assert events[0]["photos"][0]["path"] == "data/media/2026-03-04/photo.jpg"
        assert events[0]["source"] == "photo"

    def test_create_event_with_location(self, events_service):
        result = events_service.create_event(
            date="2026-03-04",
            name="Lunch spot",
            start_time="2026-03-04T12:00:00",
            location={"lat": 32.08, "lng": 34.78, "name": "Tel Aviv"},
        )
        events = events_service.get_events("2026-03-04")
        assert events[0]["location"]["name"] == "Tel Aviv"


class TestAttachPhoto:
    def test_attach_photo_to_event(self, events_service):
        events_service.create_event(date="2026-03-04", name="Walk", start_time="14:00")
        events = events_service.get_events("2026-03-04")
        event_id = events[0]["id"]

        result = events_service.attach_photo(
            date="2026-03-04",
            event_id=event_id,
            photo_path="data/media/2026-03-04/photo.jpg",
            caption="Sunset",
        )
        assert result["attached"] is True

        events = events_service.get_events("2026-03-04")
        assert len(events[0]["photos"]) == 1
        assert events[0]["photos"][0]["caption"] == "Sunset"

    def test_attach_photo_nonexistent_event(self, events_service):
        result = events_service.attach_photo(
            date="2026-03-04",
            event_id="nonexistent",
            photo_path="data/media/photo.jpg",
        )
        assert "error" in result

    def test_attach_multiple_photos(self, events_service):
        events_service.create_event(date="2026-03-04", name="Hike", start_time="09:00")
        event_id = events_service.get_events("2026-03-04")[0]["id"]

        events_service.attach_photo(date="2026-03-04", event_id=event_id, photo_path="photo1.jpg")
        events_service.attach_photo(date="2026-03-04", event_id=event_id, photo_path="photo2.jpg")

        events = events_service.get_events("2026-03-04")
        assert len(events[0]["photos"]) == 2


class TestAutoRefresh:
    def test_auto_refresh_returns_merged_events(self, events_service):
        fresh = [
            {"name": "Standup", "type": "calendar", "start_time": "10:00",
             "end_time": "10:30", "source": "calendar",
             "source_ids": {"calendar_id": "cal_1"}},
        ]
        result = events_service.auto_refresh("2026-03-06", fresh)
        assert len(result) == 1
        assert result[0]["name"] == "Standup"
        assert "id" in result[0]

        # Should be persisted
        persisted = events_service.get_events("2026-03-06")
        assert len(persisted) == 1

    def test_auto_refresh_preserves_photos(self, events_service):
        events_service.create_event(
            date="2026-03-06", name="Cafe", start_time="15:00",
            photo_path="photo.jpg", caption="Latte",
        )
        fresh = [
            {"name": "Standup", "type": "calendar", "start_time": "10:00",
             "end_time": "10:30", "source": "calendar",
             "source_ids": {"calendar_id": "cal_1"}},
        ]
        result = events_service.auto_refresh("2026-03-06", fresh)
        names = [e["name"] for e in result]
        assert "Standup" in names
        assert "Cafe" in names
        cafe = next(e for e in result if e["name"] == "Cafe")
        assert len(cafe["photos"]) == 1

    def test_auto_refresh_empty_fresh_keeps_manual(self, events_service):
        events_service.create_event(
            date="2026-03-06", name="Manual event", start_time="14:00",
        )
        result = events_service.auto_refresh("2026-03-06", [])
        assert len(result) == 1
        assert result[0]["name"] == "Manual event"


class TestRefreshMerge:
    def test_refresh_preserves_photos(self, events_service):
        """Re-merging from sources keeps manually-attached photos."""
        events_service.create_event(
            date="2026-03-04",
            name="Cafe",
            start_time="15:00",
            photo_path="photo.jpg",
            caption="Latte",
        )
        event_id = events_service.get_events("2026-03-04")[0]["id"]

        # Simulate fresh merge from sources
        fresh_events = [
            {"name": "Team standup", "type": "calendar", "start_time": "10:00", "end_time": "10:30", "source": "calendar",
             "source_ids": {"calendar_id": "cal_123"}},
        ]

        events_service.refresh_events("2026-03-04", fresh_events)
        result = events_service.get_events("2026-03-04")

        # Should have both: fresh calendar event + preserved photo event
        names = [e["name"] for e in result]
        assert "Team standup" in names
        assert "Cafe" in names
        # Photo should still be attached
        cafe = next(e for e in result if e["name"] == "Cafe")
        assert len(cafe["photos"]) == 1

    def test_refresh_matches_by_source_ids(self, events_service):
        """Re-merge matches existing events by source_ids, preserving their IDs and photos."""
        events_service.save_events("2026-03-04", [{
            "name": "Standup",
            "type": "calendar",
            "start_time": "10:00",
            "end_time": "10:30",
            "source": "merged",
            "source_ids": {"calendar_id": "cal_123"},
            "photos": [{"path": "photo.jpg", "caption": "Whiteboard"}],
        }])
        old_id = events_service.get_events("2026-03-04")[0]["id"]

        fresh = [{
            "name": "Standup (updated)",
            "type": "calendar",
            "start_time": "10:00",
            "end_time": "10:45",
            "source": "calendar",
            "source_ids": {"calendar_id": "cal_123"},
        }]
        events_service.refresh_events("2026-03-04", fresh)

        result = events_service.get_events("2026-03-04")
        assert len(result) == 1
        assert result[0]["id"] == old_id  # Same ID preserved
        assert result[0]["name"] == "Standup (updated)"  # Name updated from source
        assert len(result[0]["photos"]) == 1  # Photo preserved
