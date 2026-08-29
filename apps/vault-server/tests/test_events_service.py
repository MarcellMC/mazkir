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


class TestCreateEventDefaults:
    def test_type_defaults_to_calendar_without_photo(self, events_service):
        events_service.create_event(date="2026-03-04", name="Lunch", start_time="2026-03-04T12:00:00")
        events = events_service.get_events("2026-03-04")
        assert events[0]["type"] == "calendar"

    def test_type_defaults_to_unplanned_stop_with_photo(self, events_service):
        events_service.create_event(
            date="2026-03-04", name="Snap", start_time="2026-03-04T14:00:00",
            photo_path="photo.jpg",
        )
        events = events_service.get_events("2026-03-04")
        assert events[0]["type"] == "unplanned_stop"

    def test_type_explicit_override(self, events_service):
        events_service.create_event(
            date="2026-03-04", name="Walk", start_time="2026-03-04T10:00:00",
            event_type="activity",
        )
        events = events_service.get_events("2026-03-04")
        assert events[0]["type"] == "activity"

    def test_duration_calculated_from_times(self, events_service):
        events_service.create_event(
            date="2026-03-04", name="Meeting",
            start_time="2026-03-04T10:00:00", end_time="2026-03-04T11:30:00",
        )
        events = events_service.get_events("2026-03-04")
        assert events[0]["duration_minutes"] == 90

    def test_duration_zero_when_no_end_time(self, events_service):
        events_service.create_event(
            date="2026-03-04", name="Quick stop", start_time="2026-03-04T15:00:00",
        )
        events = events_service.get_events("2026-03-04")
        assert events[0]["duration_minutes"] == 0

    def test_source_ids_passed_through(self, events_service):
        events_service.create_event(
            date="2026-03-04", name="Synced",
            start_time="2026-03-04T10:00:00",
            source_ids={"calendar_id": "gcal_abc123"},
        )
        events = events_service.get_events("2026-03-04")
        assert events[0]["source_ids"] == {"calendar_id": "gcal_abc123"}


class TestUpdateEvent:
    def test_update_event_name(self, events_service):
        events_service.create_event(date="2026-03-04", name="Walk", start_time="2026-03-04T10:00:00")
        event_id = events_service.get_events("2026-03-04")[0]["id"]

        result = events_service.update_event("2026-03-04", event_id, {"name": "Dog walk"})
        assert result["updated"] is True
        events = events_service.get_events("2026-03-04")
        assert events[0]["name"] == "Dog walk"

    def test_update_event_end_time_recalculates_duration(self, events_service):
        events_service.create_event(
            date="2026-03-04", name="Walk",
            start_time="2026-03-04T10:00:00", end_time="2026-03-04T10:30:00",
        )
        event_id = events_service.get_events("2026-03-04")[0]["id"]

        result = events_service.update_event("2026-03-04", event_id, {
            "end_time": "2026-03-04T11:30:00",
        })
        assert result["updated"] is True
        events = events_service.get_events("2026-03-04")
        assert events[0]["end_time"] == "2026-03-04T11:30:00"
        assert events[0]["duration_minutes"] == 90

    def test_update_event_not_found(self, events_service):
        result = events_service.update_event("2026-03-04", "nonexistent", {"name": "X"})
        assert "error" in result

    def test_update_preserves_other_fields(self, events_service):
        events_service.create_event(
            date="2026-03-04", name="Walk",
            start_time="2026-03-04T10:00:00",
            photo_path="photo.jpg", caption="Nice walk",
        )
        event_id = events_service.get_events("2026-03-04")[0]["id"]

        events_service.update_event("2026-03-04", event_id, {"name": "Dog walk"})
        events = events_service.get_events("2026-03-04")
        assert events[0]["name"] == "Dog walk"
        assert len(events[0]["photos"]) == 1  # Photo preserved


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

    def test_attach_photo_finds_event_in_other_date_file(self, events_service):
        # Event lives on 2026-06-17 but caller passes the wrong (today's) date.
        events_service.create_event(date="2026-06-17", name="Band Practice", start_time="14:00")
        event_id = events_service.get_events("2026-06-17")[0]["id"]

        result = events_service.attach_photo(
            date="2026-06-15",
            event_id=event_id,
            photo_path="form.jpg",
            caption="Entry code",
        )
        assert result["attached"] is True
        assert result["date"] == "2026-06-17"

        # Photo landed on the correct date's file...
        events = events_service.get_events("2026-06-17")
        assert len(events[0]["photos"]) == 1
        assert events[0]["photos"][0]["caption"] == "Entry code"
        # ...and the wrong-date file was never created.
        assert events_service.get_events("2026-06-15") == []

    def test_attach_photo_scans_when_date_omitted(self, events_service):
        events_service.create_event(date="2026-06-17", name="X", start_time="14:00")
        event_id = events_service.get_events("2026-06-17")[0]["id"]

        result = events_service.attach_photo(
            date=None,
            event_id=event_id,
            photo_path="p.jpg",
        )
        assert result["attached"] is True
        assert result["date"] == "2026-06-17"

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


class TestUpdateEventReturnsPersistedEvent:
    def test_update_event_returns_the_persisted_event(self, events_service):
        svc = events_service
        svc.save_events("2026-08-16", [{
            "id": "evt_1",
            "name": "Dog walk",
            "start_time": "2026-08-16T16:29:00",
            "end_time": "2026-08-16T17:09:00",
        }])

        result = svc.update_event(
            "2026-08-16", "evt_1", {"start_time": "2026-08-16T15:59:00"}
        )

        assert result["updated"] is True
        assert result["event"]["start_time"] == "2026-08-16T15:59:00"
        assert result["event"] == svc.get_events("2026-08-16")[0]

    def test_update_event_missing_id_still_returns_error(self, events_service):
        svc = events_service
        svc.save_events("2026-08-16", [{"id": "evt_1", "name": "Dog walk"}])

        result = svc.update_event("2026-08-16", "evt_nope", {"name": "x"})

        assert "error" in result
        assert "event" not in result


class TestFilesystemSpans:
    """save_events should emit an fs.write span."""

    def test_save_events_emits_fs_write_span(self, events_service, monkeypatch):
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        monkeypatch.setattr(trace, "_TRACER_PROVIDER", provider, raising=False)
        monkeypatch.setattr(
            trace._TRACER_PROVIDER_SET_ONCE, "_done", False, raising=False
        )
        trace.set_tracer_provider(provider)

        events_service.save_events("2026-05-21", [{"name": "Span Test"}])

        spans = [s for s in exporter.get_finished_spans() if s.name.startswith("fs.")]
        assert len(spans) == 1
        assert spans[0].name == "fs.write"
        assert spans[0].attributes["fs.store"] == "events"
        assert spans[0].attributes["fs.bytes"] > 0


def test_legacy_activity_category_is_read_as_activity(tmp_path):
    import json
    from src.services.events_service import EventsService

    events_dir = tmp_path / "events"
    events_dir.mkdir()
    (events_dir / "2026-05-01.json").write_text(json.dumps([{
        "id": "evt_old",
        "name": "Coffee",
        "activity_category": "cafe",
    }]), encoding="utf-8")

    svc = EventsService(events_dir)
    event = svc.get_events("2026-05-01")[0]

    assert event["activity"] == "cafe"
    assert "activity_category" not in event


def test_new_events_are_saved_with_activity(tmp_path):
    from src.services.events_service import EventsService

    svc = EventsService(tmp_path / "events")
    svc.save_events("2026-08-17", [{"id": "evt_1", "activity": "dev"}])

    assert svc.get_events("2026-08-17")[0]["activity"] == "dev"


def test_new_fields_are_defaulted_on_save(tmp_path):
    from src.services.events_service import EventsService

    svc = EventsService(tmp_path / "events")
    svc.save_events("2026-08-17", [{"id": "evt_1", "name": "Dog walk"}])

    event = svc.get_events("2026-08-17")[0]

    assert event["activity"] is None
    assert event["category"] is None
    assert event["tags"] == []
    assert event["state"] == "suggested"


def test_explicit_values_are_preserved(tmp_path):
    from src.services.events_service import EventsService

    svc = EventsService(tmp_path / "events")
    svc.save_events("2026-08-17", [{
        "id": "evt_1",
        "activity": "dev",
        "category": "personal",
        "tags": ["mazkir"],
        "state": "approved",
    }])

    event = svc.get_events("2026-08-17")[0]

    assert event["activity"] == "dev"
    assert event["category"] == "personal"
    assert event["tags"] == ["mazkir"]
    assert event["state"] == "approved"


def test_legacy_events_default_to_suggested(tmp_path):
    """Events written before this change must not silently count as logged."""
    import json
    from src.services.events_service import EventsService

    events_dir = tmp_path / "events"
    events_dir.mkdir()
    (events_dir / "2026-05-01.json").write_text(
        json.dumps([{"id": "evt_old", "name": "Coffee"}]), encoding="utf-8"
    )

    svc = EventsService(events_dir)

    assert svc.get_events("2026-05-01")[0]["state"] == "suggested"


def test_create_event_writes_the_activity_kwarg_to_the_activity_field(tmp_path):
    from src.services.events_service import EventsService

    svc = EventsService(tmp_path / "events")
    svc.create_event(
        date="2026-08-17", name="Dog walk", start_time="07:00", activity="walk"
    )

    event = svc.get_events("2026-08-17")[0]
    assert event["activity"] == "walk"
    # The category facet is a separate axis and is not populated from here.
    assert event["category"] is None


def test_create_event_still_accepts_the_deprecated_category_alias(tmp_path):
    from src.services.events_service import EventsService

    svc = EventsService(tmp_path / "events")
    svc.create_event(
        date="2026-08-17", name="Dog walk", start_time="07:00", category="walk"
    )

    assert svc.get_events("2026-08-17")[0]["activity"] == "walk"


def test_activity_wins_when_both_names_are_given(tmp_path):
    from src.services.events_service import EventsService

    svc = EventsService(tmp_path / "events")
    svc.create_event(
        date="2026-08-17",
        name="Dog walk",
        start_time="07:00",
        activity="walk",
        category="legacy",
    )

    assert svc.get_events("2026-08-17")[0]["activity"] == "walk"


def _persisted(**kw):
    e = {"id": "evt_1", "name": "Visit Alex", "type": "calendar",
         "start_time": "2026-08-30T00:00", "end_time": "2026-08-30T01:00",
         "source": "calendar", "source_ids": {"calendar_id": "cal1"},
         "state": "approved", "photos": []}
    e.update(kw)
    return e


def test_an_unavailable_source_does_not_delete_its_events(tmp_path):
    """The bug this fixes: a failed calendar fetch looked identical to an
    empty calendar, so every persisted calendar event was deleted. With
    /daily calling this on every navigation tap, browsing a week with an
    expired token would have wiped seven days."""
    svc = EventsService(tmp_path)
    svc.save_events("2026-08-30", [_persisted()])
    result = svc.refresh_events("2026-08-30", [], available_sources=set())
    assert [e["name"] for e in result] == ["Visit Alex"]
    assert result[0]["state"] == "approved"


def test_an_available_source_still_deletes_events_it_no_longer_returns(tmp_path):
    """The feature must survive the fix: deleting a calendar event really
    should remove it once the calendar has answered without it."""
    svc = EventsService(tmp_path)
    svc.save_events("2026-08-30", [_persisted()])
    result = svc.refresh_events("2026-08-30", [], available_sources={"calendar"})
    assert result == []


def test_one_failed_source_does_not_delete_another_source_events(tmp_path):
    """Partial failure is the common case — the calendar answers, the
    timeline does not."""
    svc = EventsService(tmp_path)
    svc.save_events("2026-08-30", [
        _persisted(id="evt_cal", source_ids={"calendar_id": "cal1"}),
        _persisted(id="evt_visit", name="Xoho", source="timeline",
                   source_ids={"visit_id": "v1"}),
    ])
    result = svc.refresh_events("2026-08-30", [], available_sources={"calendar"})
    assert [e["name"] for e in result] == ["Xoho"]


def test_omitting_available_sources_preserves_everything(tmp_path):
    """The default must be safe: a caller that has not been updated cannot
    delete data by accident."""
    svc = EventsService(tmp_path)
    svc.save_events("2026-08-30", [_persisted()])
    assert len(svc.refresh_events("2026-08-30", [])) == 1


def test_manual_events_are_still_preserved(tmp_path):
    svc = EventsService(tmp_path)
    svc.save_events("2026-08-30", [_persisted(source="manual", source_ids={})])
    result = svc.refresh_events("2026-08-30", [], available_sources={"calendar"})
    assert len(result) == 1
