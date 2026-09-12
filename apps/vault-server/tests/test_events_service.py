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

    def test_start_only_persists_as_genuinely_incomplete(self, events_service):
        """`end_time or start_time` used to complete a bare start into a
        zero-duration event, so `is_complete()` returned True forever and
        the block never surfaced for the follow-up partial capture exists
        to prompt."""
        from src.services.events_service import is_complete

        events_service.create_event(
            date="2026-03-04", name="Gym", start_time="2026-03-04T18:00:00",
        )
        stored = events_service.get_events("2026-03-04")[0]
        assert stored["end_time"] is None
        assert is_complete(stored) is False


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


class TestUpdateEventAcrossDates:
    """The date argument is a hint, and an update may move the event's file.

    `list_events` hands out IDs for any date, so an update arriving with the
    wrong date hint — or none — is normal, not an error.
    """

    def test_update_finds_event_in_other_date_file(self, events_service):
        events_service.create_event(date="2026-09-08", name="Walk", start_time="2026-09-08T10:00:00")
        event_id = events_service.get_events("2026-09-08")[0]["id"]

        result = events_service.update_event("2026-09-07", event_id, {"name": "Dog walk"})

        assert result["updated"] is True
        assert result["date"] == "2026-09-08"
        assert events_service.get_events("2026-09-08")[0]["name"] == "Dog walk"
        assert events_service.get_events("2026-09-07") == []

    def test_update_scans_when_date_omitted(self, events_service):
        events_service.create_event(date="2026-09-08", name="Walk", start_time="2026-09-08T10:00:00")
        event_id = events_service.get_events("2026-09-08")[0]["id"]

        result = events_service.update_event(None, event_id, {"name": "Dog walk"})

        assert result["updated"] is True
        assert result["date"] == "2026-09-08"

    def test_new_date_moves_the_event_and_keeps_its_time(self, events_service):
        events_service.create_event(
            date="2026-09-08", name="Walk",
            start_time="2026-09-08T16:30:00", end_time="2026-09-08T17:10:00",
        )
        event_id = events_service.get_events("2026-09-08")[0]["id"]

        result = events_service.update_event(
            "2026-09-08", event_id, {}, new_date="2026-09-07"
        )

        assert result["date"] == "2026-09-07"
        assert result["moved_from"] == "2026-09-08"
        assert events_service.get_events("2026-09-08") == []
        moved = events_service.get_events("2026-09-07")
        assert len(moved) == 1
        assert moved[0]["id"] == event_id
        assert moved[0]["start_time"] == "2026-09-07T16:30:00"
        assert moved[0]["end_time"] == "2026-09-07T17:10:00"

    def test_start_time_on_another_day_moves_the_file_too(self, events_service):
        """The file an event lives in is the day it belongs to.

        Rewriting start_time to another date without moving the row would
        leave the old day showing an event it no longer has.
        """
        events_service.create_event(date="2026-09-08", name="Walk", start_time="2026-09-08T10:00:00")
        event_id = events_service.get_events("2026-09-08")[0]["id"]

        result = events_service.update_event(
            "2026-09-08", event_id, {"start_time": "2026-09-07T21:00:00"}
        )

        assert result["date"] == "2026-09-07"
        assert events_service.get_events("2026-09-08") == []
        assert events_service.get_events("2026-09-07")[0]["start_time"] == "2026-09-07T21:00:00"

    def test_move_lands_beside_the_target_days_existing_events(self, events_service):
        events_service.create_event(date="2026-09-07", name="Breakfast", start_time="2026-09-07T08:00:00")
        events_service.create_event(date="2026-09-08", name="Walk", start_time="2026-09-08T10:00:00")
        event_id = events_service.get_events("2026-09-08")[0]["id"]

        events_service.update_event("2026-09-08", event_id, {}, new_date="2026-09-07")

        names = {e["name"] for e in events_service.get_events("2026-09-07")}
        assert names == {"Breakfast", "Walk"}

    def test_moved_event_survives_reconcile_at_its_new_date(self, events_service):
        """A moved calendar event must not be deleted by the next merge.

        `reconcile` drops an unmatched calendar event when the calendar
        answered — and the calendar will never emit this one for the day the
        user moved it to. Detaching the upstream ids on the move is what
        keeps the move from silently undoing itself.
        """
        events_service.save_events("2026-09-08", [{
            "id": "evt_moved",
            "name": "Dog walk",
            "start_time": "2026-09-08T16:30:00",
            "end_time": "2026-09-08T17:10:00",
            "source": "calendar",
            "source_ids": {"calendar_id": "gcal_123"},
        }])

        events_service.update_event("2026-09-08", "evt_moved", {}, new_date="2026-09-07")

        moved = events_service.get_events("2026-09-07")[0]
        assert moved["source_ids"] == {}
        assert moved["moved_from_source_ids"] == {"calendar_id": "gcal_123"}
        assert moved["source"] == "manual"

        # The calendar answers for 2026-09-07 and has nothing matching it.
        survivors = events_service.reconcile("2026-09-07", [], available_sources={"calendar"})
        assert [e["id"] for e in survivors] == ["evt_moved"]

    def test_same_day_update_leaves_source_ids_alone(self, events_service):
        events_service.save_events("2026-09-08", [{
            "id": "evt_1",
            "name": "Dog walk",
            "start_time": "2026-09-08T16:30:00",
            "source": "calendar",
            "source_ids": {"calendar_id": "gcal_123"},
        }])

        events_service.update_event("2026-09-08", "evt_1", {"start_time": "2026-09-08T17:00:00"})

        event = events_service.get_events("2026-09-08")[0]
        assert event["source_ids"] == {"calendar_id": "gcal_123"}
        assert event["source"] == "calendar"
        assert "moved_from_source_ids" not in event

    def test_update_unknown_id_reports_not_found_after_scanning(self, events_service):
        events_service.create_event(date="2026-09-08", name="Walk", start_time="2026-09-08T10:00:00")

        result = events_service.update_event(None, "evt_nope", {"name": "X"})

        assert "error" in result


class TestDeleteEvent:
    def test_delete_removes_the_event(self, events_service):
        events_service.create_event(date="2026-09-07", name="Dog walk", start_time="2026-09-07T16:30:00")
        events_service.create_event(date="2026-09-07", name="Dinner", start_time="2026-09-07T19:00:00")
        event_id = events_service.get_events("2026-09-07")[0]["id"]

        result = events_service.delete_event("2026-09-07", event_id)

        assert result["deleted"] is True
        assert result["event"]["name"] == "Dog walk"
        assert result["date"] == "2026-09-07"
        assert [e["name"] for e in events_service.get_events("2026-09-07")] == ["Dinner"]

    def test_delete_finds_event_on_another_date(self, events_service):
        events_service.create_event(date="2026-09-08", name="Dog walk", start_time="2026-09-08T16:30:00")
        event_id = events_service.get_events("2026-09-08")[0]["id"]

        result = events_service.delete_event("2026-09-07", event_id)

        assert result["date"] == "2026-09-08"
        assert events_service.get_events("2026-09-08") == []

    def test_delete_unknown_id_errors(self, events_service):
        result = events_service.delete_event("2026-09-07", "evt_nope")
        assert "error" in result


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


class TestReconcileDerivedVsUserSetState:
    """`completed` and `habit` are recomputed from the vault on every merge,
    so a matched event must take them from the fresh side — the persisted
    value is stale the instant the underlying checkbox/habit log changes.
    `photos`/`assets`/`state` are the opposite: user-set enrichment nothing
    upstream can regenerate, so those must keep coming from the persisted
    side. This guards against a fix to one direction accidentally undoing
    the other."""

    def test_completed_refreshes_from_the_fresh_merge(self, events_service):
        events_service.save_events("2026-03-04", [{
            "name": "Morning workout",
            "type": "daily-task",
            "start_time": "07:00",
            "end_time": "07:30",
            "source": "daily-note",
            "source_ids": {"note_line": "line1"},
            "completed": False,
        }])

        fresh = [{
            "name": "Morning workout",
            "type": "daily-task",
            "start_time": "07:00",
            "end_time": "07:30",
            "source": "daily-note",
            "source_ids": {"note_line": "line1"},
            "completed": True,
        }]

        result = events_service.reconcile("2026-03-04", fresh)
        assert len(result) == 1
        assert result[0]["completed"] is True  # Ticking the box wins, not the stale persisted value

    def test_habit_dict_refreshes_from_the_fresh_merge(self, events_service):
        events_service.save_events("2026-03-04", [{
            "name": "🎯 Meditate",
            "type": "habit",
            "start_time": "07:00",
            "source": "habit",
            "source_ids": {"habit_slug": "meditate"},
            "completed": False,
            "habit": {"name": "Meditate", "completed": False, "streak": 3, "tokens_earned": 0},
        }])

        fresh = [{
            "name": "🎯 Meditate",
            "type": "habit",
            "start_time": "07:00",
            "source": "habit",
            "source_ids": {"habit_slug": "meditate"},
            "completed": True,
            "habit": {"name": "Meditate", "completed": True, "streak": 4, "tokens_earned": 5},
        }]

        result = events_service.reconcile("2026-03-04", fresh)
        assert len(result) == 1
        assert result[0]["completed"] is True
        assert result[0]["habit"]["completed"] is True
        assert result[0]["habit"]["streak"] == 4
        assert result[0]["habit"]["tokens_earned"] == 5

    def test_photos_and_state_survive_reconcile_even_as_completed_flips(self, events_service):
        """A fix that refreshed everything on a match — not just derived
        fields — would silently drop user-set enrichment. Assert both
        travel through the same reconcile call that flips `completed`."""
        events_service.save_events("2026-03-04", [{
            "name": "Morning workout",
            "type": "daily-task",
            "start_time": "07:00",
            "end_time": "07:30",
            "source": "daily-note",
            "source_ids": {"note_line": "line1"},
            "completed": False,
            "photos": [{"path": "photo.jpg", "caption": "before"}],
            "state": "approved",
        }])
        old_id = events_service.get_events("2026-03-04")[0]["id"]

        fresh = [{
            "name": "Morning workout",
            "type": "daily-task",
            "start_time": "07:00",
            "end_time": "07:30",
            "source": "daily-note",
            "source_ids": {"note_line": "line1"},
            "completed": True,
        }]

        result = events_service.reconcile("2026-03-04", fresh)
        assert len(result) == 1
        assert result[0]["id"] == old_id
        assert result[0]["completed"] is True
        assert len(result[0]["photos"]) == 1  # user-set enrichment preserved
        assert result[0]["photos"][0]["caption"] == "before"
        assert result[0]["state"] == "approved"  # user-set enrichment preserved


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
    # `state` is absent, not "suggested" (spec §2.2): absent means "derive
    # it from the source", and a stored value means the user decided. A
    # default would make those two indistinguishable.
    assert "state" not in event


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


def test_legacy_events_carry_no_state_and_resolve_to_pending(tmp_path):
    """Events written before approval existed must not silently count as
    logged. They now carry no `state` at all, and `resolve_state` derives
    "pending" for them — same protection, without a stored default that
    would be indistinguishable from a real decision."""
    import json
    from src.services.approval import resolve_state
    from src.services.events_service import EventsService

    events_dir = tmp_path / "events"
    events_dir.mkdir()
    (events_dir / "2026-05-01.json").write_text(
        json.dumps([{"id": "evt_old", "name": "Coffee"}]), encoding="utf-8"
    )

    svc = EventsService(events_dir)
    event = svc.get_events("2026-05-01")[0]

    assert "state" not in event
    assert resolve_state(event) == "pending"


def test_a_stored_suggested_is_dropped_on_read(tmp_path):
    """Rows written by Ship 4 carry state="suggested". It never expressed a
    decision, so it is stripped rather than preserved — otherwise it would
    read as stored state forever."""
    import json
    from src.services.events_service import EventsService

    events_dir = tmp_path / "events"
    events_dir.mkdir()
    (events_dir / "2026-05-01.json").write_text(
        json.dumps([{"id": "e1", "name": "Coffee", "state": "suggested"}]),
        encoding="utf-8",
    )

    assert "state" not in EventsService(events_dir).get_events("2026-05-01")[0]


def test_approved_and_dismissed_survive_a_save_and_read(tmp_path):
    from src.services.events_service import EventsService

    svc = EventsService(tmp_path / "events")
    svc.save_events("2026-05-01", [
        {"id": "a", "state": "approved"},
        {"id": "b", "state": "dismissed"},
    ])

    by_id = {e["id"]: e for e in svc.get_events("2026-05-01")}
    assert by_id["a"]["state"] == "approved"
    assert by_id["b"]["state"] == "dismissed"


def test_save_events_does_not_invent_a_state(tmp_path):
    from src.services.events_service import EventsService

    svc = EventsService(tmp_path / "events")
    svc.save_events("2026-05-01", [{"id": "a", "name": "Coffee"}])

    raw = (tmp_path / "events" / "2026-05-01.json").read_text()
    assert '"state"' not in raw


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


def test_reconcile_does_not_persist(tmp_path):
    """The whole point of the read/write split: /daily calls this to
    preview a merge without ever writing data/events/{date}.json for
    whatever date is being browsed — browsing history must not rewrite it."""
    svc = EventsService(tmp_path)
    svc.save_events("2026-08-30", [_persisted()])
    result = svc.reconcile("2026-08-30", [], available_sources={"calendar"})
    assert result == []
    # The file on disk must be untouched — reconcile only computed a view.
    on_disk = svc.get_events("2026-08-30")
    assert len(on_disk) == 1
    assert on_disk[0]["name"] == "Visit Alex"


def test_refresh_events_still_persists(tmp_path):
    """reconcile stays pure; refresh_events keeps its old persisting
    behaviour unchanged, so POST /events/{date}/refresh is unaffected."""
    svc = EventsService(tmp_path)
    svc.save_events("2026-08-30", [_persisted()])
    result = svc.refresh_events("2026-08-30", [], available_sources={"calendar"})
    assert result == []
    assert svc.get_events("2026-08-30") == []


def test_an_event_with_an_unmapped_source_key_is_never_deleted(tmp_path):
    """An unrecognised source_ids key means we cannot tell which system owns
    this event, so we keep it. A future source type added without a
    _SOURCE_SYSTEM_BY_ID_KEY entry must not silently become deletable —
    especially not when available_sources is empty because nothing answered."""
    svc = EventsService(tmp_path)
    svc.save_events("2026-08-30", [_persisted(
        id="evt_future", source="something-new", source_ids={"unmapped_id": "x1"},
    )])
    assert len(svc.reconcile("2026-08-30", [], available_sources=set())) == 1
    assert len(svc.reconcile("2026-08-30", [], available_sources={"calendar"})) == 1


def test_a_note_derived_event_is_never_deleted_even_when_its_source_answered(tmp_path):
    """`note_line` hashes the checkbox's date, section, text and time, so
    fixing a typo re-hashes it and the fresh merge carries a different id.
    The daily-note source answered, so availability cannot see the
    difference between "edited" and "deleted" — and the persisted block,
    with any photo attached to it, used to be destroyed."""
    svc = EventsService(tmp_path)
    svc.save_events("2026-08-30", [_persisted(
        id="evt_note", name="Standup", source="daily-note",
        source_ids={"note_line": "abc123"},
        photos=[{"path": "whiteboard.jpg", "caption": None, "wikilinks": []}],
    )])
    result = svc.reconcile(
        "2026-08-30", [], available_sources={"calendar", "timeline", "daily-note", "habit"},
    )
    assert [e["name"] for e in result] == ["Standup"]
    assert len(result[0]["photos"]) == 1


def test_a_habit_derived_event_is_never_deleted_even_when_its_source_answered(tmp_path):
    """A habit block is *suppressed* whenever a calendar event claims the
    habit, so its absence from a merge is shadowing, not deletion — and the
    habit source answered either way."""
    svc = EventsService(tmp_path)
    svc.save_events("2026-08-30", [_persisted(
        id="evt_habit", name="Review Email", source="habit",
        source_ids={"habit_slug": "2026-08-30:review-email"},
        photos=[{"path": "inbox.jpg", "caption": None, "wikilinks": []}],
    )])
    result = svc.reconcile(
        "2026-08-30", [], available_sources={"calendar", "timeline", "daily-note", "habit"},
    )
    assert [e["name"] for e in result] == ["Review Email"]
    assert len(result[0]["photos"]) == 1


def test_timeline_events_stay_deletable(tmp_path):
    """The restriction is to the two sources with upstream-stable ids —
    timeline is one of them, so a visit that Google no longer reports is
    still removed."""
    svc = EventsService(tmp_path)
    svc.save_events("2026-08-30", [_persisted(
        id="evt_visit", name="Xoho", source="timeline", source_ids={"visit_id": "v1"},
    )])
    assert svc.reconcile("2026-08-30", [], available_sources={"timeline"}) == []


def test_an_event_spanning_a_deletable_and_a_protected_source_is_kept(tmp_path):
    """Subset, not intersection: an event carrying two keys is only
    deletable when *every* system behind it is."""
    svc = EventsService(tmp_path)
    svc.save_events("2026-08-30", [_persisted(
        id="evt_both", source="merged",
        source_ids={"calendar_id": "cal1", "note_line": "abc123"},
    )])
    result = svc.reconcile(
        "2026-08-30", [], available_sources={"calendar", "daily-note"},
    )
    assert len(result) == 1


def test_a_habit_shadowed_by_a_calendar_event_keeps_its_persisted_block(tmp_path):
    """End-to-end reproduction of the whole-branch review's Critical 1.

    Even with the matcher narrowed, attachment still legitimately
    suppresses a habit's standalone block — that is the point of it. The
    suppression must stay a rendering decision: the persisted event, and
    the photo on it, must survive a merge that does not emit the block.
    """
    from src.services.merger_service import MergerService

    m = MergerService()
    habit = {"name": "Dog Walk", "scheduled_at": "07:00", "duration_minutes": 40,
             "completed_today": False, "streak": 3, "tokens_per_completion": 5,
             "completions_today": 0, "daily_target": 1}
    empty_timeline = {"visits": [], "activities": []}
    sources = {"calendar", "timeline", "habit", "daily-note"}
    svc = EventsService(tmp_path)

    standalone = m.merge([], empty_timeline, habits=[habit], date="2026-08-29")
    persisted = svc.refresh_events(
        "2026-08-29", [e.model_dump() for e in standalone], sources)
    persisted[0]["photos"] = [{"path": "dog.jpg", "caption": None, "wikilinks": []}]
    svc.save_events("2026-08-29", persisted)

    # The habit now has a calendar event of its own, so it emits no block.
    shadowed = m.merge(
        [{"id": "cal1", "summary": "🎯 Dog Walk", "start": "2026-08-29T07:00",
          "end": "2026-08-29T07:40", "completed": False, "calendar": "Mazkir"}],
        empty_timeline, habits=[habit], date="2026-08-29",
    )
    assert not [e for e in shadowed if e.source == "habit"]

    result = svc.refresh_events(
        "2026-08-29", [e.model_dump() for e in shadowed], sources)
    survivor = [e for e in result if e["source"] == "habit"]
    assert len(survivor) == 1
    assert survivor[0]["photos"] == [{"path": "dog.jpg", "caption": None, "wikilinks": []}]


class TestUserSet:
    """Per-field provenance: a merge must not undo what the user said.

    `reconcile` re-derives name/start/end/location from the source on every
    read. Before `user_set`, renaming a calendar block worked and then
    silently reverted the next time the day was opened.
    """

    def _calendar_event(self):
        return {
            "id": "evt_1",
            "name": "Daily sync",
            "start_time": "2026-09-08T10:00:00",
            "end_time": "2026-09-08T10:30:00",
            "source": "calendar",
            "source_ids": {"calendar_id": "gcal_1"},
        }

    def _fresh(self):
        return [{
            "name": "Daily sync",
            "start_time": "2026-09-08T10:00:00",
            "end_time": "2026-09-08T10:30:00",
            "source": "calendar",
            "source_ids": {"calendar_id": "gcal_1"},
        }]

    def test_save_events_defaults_user_set_to_empty(self, events_service):
        events_service.save_events("2026-09-08", [self._calendar_event()])
        assert events_service.get_events("2026-09-08")[0]["user_set"] == {}

    def test_pinned_name_survives_reconcile(self, events_service):
        """The exact 2026-09-08 regression, asserted directly."""
        events_service.save_events("2026-09-08", [self._calendar_event()])
        events_service.update_event(
            "2026-09-08", "evt_1", {"name": "Standup"}, user_set_fields=["name"],
        )
        result = events_service.reconcile(
            "2026-09-08", self._fresh(), available_sources={"calendar"},
        )
        assert result[0]["name"] == "Standup"

    def test_unpinned_fields_still_track_the_source(self, events_service):
        events_service.save_events("2026-09-08", [self._calendar_event()])
        events_service.update_event(
            "2026-09-08", "evt_1", {"name": "Standup"}, user_set_fields=["name"],
        )
        fresh = self._fresh()
        fresh[0]["start_time"] = "2026-09-08T11:00:00"
        fresh[0]["end_time"] = "2026-09-08T11:30:00"

        result = events_service.reconcile(
            "2026-09-08", fresh, available_sources={"calendar"},
        )

        assert result[0]["name"] == "Standup"          # pinned
        assert result[0]["start_time"] == "2026-09-08T11:00:00"  # not pinned

    def test_pinned_times_recompute_duration_after_reconcile(self, events_service):
        events_service.save_events("2026-09-08", [self._calendar_event()])
        events_service.update_event(
            "2026-09-08", "evt_1",
            {"end_time": "2026-09-08T11:00:00"},
            user_set_fields=["end_time"],
        )
        result = events_service.reconcile(
            "2026-09-08", self._fresh(), available_sources={"calendar"},
        )
        assert result[0]["end_time"] == "2026-09-08T11:00:00"
        assert result[0]["duration_minutes"] == 60

    def test_non_settable_keys_are_ignored(self, events_service):
        """A stray key must not become a way to pin `completed`, which
        reconcile re-derives from vault state every merge."""
        event = self._calendar_event()
        event["user_set"] = {"completed": True, "source_ids": {"calendar_id": "hijacked"}}
        events_service.save_events("2026-09-08", [event])

        result = events_service.reconcile(
            "2026-09-08", self._fresh(), available_sources={"calendar"},
        )

        assert result[0]["completed"] is False
        assert result[0]["source_ids"] == {"calendar_id": "gcal_1"}

    def test_empty_user_set_is_a_no_op(self, events_service):
        events_service.save_events("2026-09-08", [self._calendar_event()])
        result = events_service.reconcile(
            "2026-09-08", self._fresh(), available_sources={"calendar"},
        )
        assert result[0]["name"] == "Daily sync"

    def test_revert_fields_restores_source_tracking(self, events_service):
        events_service.save_events("2026-09-08", [self._calendar_event()])
        events_service.update_event(
            "2026-09-08", "evt_1", {"name": "Standup"}, user_set_fields=["name"],
        )
        events_service.update_event("2026-09-08", "evt_1", {}, revert_fields=["name"])

        result = events_service.reconcile(
            "2026-09-08", self._fresh(), available_sources={"calendar"},
        )
        assert result[0]["name"] == "Daily sync"

    def test_revert_is_applied_before_the_calls_own_updates(self, events_service):
        """Naming a field in both reverts it and then pins the new value —
        the only reading under which one call cannot contradict itself."""
        events_service.save_events("2026-09-08", [self._calendar_event()])
        events_service.update_event(
            "2026-09-08", "evt_1", {"name": "Standup"}, user_set_fields=["name"],
        )
        events_service.update_event(
            "2026-09-08", "evt_1", {"name": "Morning sync"},
            user_set_fields=["name"], revert_fields=["name"],
        )
        result = events_service.reconcile(
            "2026-09-08", self._fresh(), available_sources={"calendar"},
        )
        assert result[0]["name"] == "Morning sync"


class TestIsComplete:
    def test_both_ends_is_complete(self):
        from src.services.events_service import is_complete
        assert is_complete({"start_time": "2026-09-08T10:00:00", "end_time": "2026-09-08T11:00:00"}) is True

    def test_missing_end_is_incomplete(self):
        from src.services.events_service import is_complete
        assert is_complete({"start_time": "2026-09-08T10:00:00", "end_time": None}) is False

    def test_missing_start_is_incomplete(self):
        from src.services.events_service import is_complete
        assert is_complete({"start_time": None, "end_time": "2026-09-08T11:00:00"}) is False

    def test_neither_is_incomplete(self):
        from src.services.events_service import is_complete
        assert is_complete({}) is False


class TestUpdateEventGuards:
    def test_inverted_interval_is_rejected_and_nothing_is_written(self, events_service):
        """Verified on c3ffcee: this used to persist start 21:00 / end 19:00
        / duration 0, which renders as `21:00–19:00` and counts for nothing."""
        events_service.create_event(
            date="2026-09-08", name="Gym",
            start_time="2026-09-08T18:00:00", end_time="2026-09-08T19:00:00",
        )
        event_id = events_service.get_events("2026-09-08")[0]["id"]

        result = events_service.update_event(
            "2026-09-08", event_id, {"start_time": "2026-09-08T21:00:00"},
        )

        assert "error" in result
        stored = events_service.get_events("2026-09-08")[0]
        assert stored["start_time"] == "2026-09-08T18:00:00"

    def test_zero_length_update_is_allowed(self, events_service):
        events_service.create_event(
            date="2026-09-08", name="Gym",
            start_time="2026-09-08T18:00:00", end_time="2026-09-08T19:00:00",
        )
        event_id = events_service.get_events("2026-09-08")[0]["id"]

        result = events_service.update_event(
            "2026-09-08", event_id, {"end_time": "2026-09-08T18:00:00"},
        )

        assert result.get("updated") is True

    def test_updates_dict_is_not_mutated(self, events_service):
        """A side effect on an argument. Harmless today because every caller
        builds the dict locally, which is exactly why it would surprise the
        first caller that does not."""
        events_service.create_event(
            date="2026-09-08", name="Gym", start_time="2026-09-08T18:00:00",
        )
        event_id = events_service.get_events("2026-09-08")[0]["id"]
        updates = {"end_time": "2026-09-08T19:00:00"}

        events_service.update_event("2026-09-08", event_id, updates)

        assert updates == {"end_time": "2026-09-08T19:00:00"}


class TestReconcileDualKeySourceIds:
    """A persisted event reachable under two source_ids keys must still
    produce exactly one row.

    Nothing in the repo produced a dual-key `source_ids` until the calendar
    ladder in `_tool_update_event` started writing `calendar_id` onto an
    inferred block, so this path had never been exercised. When it was, the
    matched branch popped only the key it matched on and left the other one
    in the lookup, so a second fresh event handed the *same* persisted dict
    back a second time: `/day` rendered the block twice and it settled into
    a permanent duplicate. The gate in `_tool_update_event` now stops that
    state arising, but this is the property that actually matters.
    """

    def test_two_fresh_events_matching_one_persisted_event_yield_one_row(
        self, events_service
    ):
        events_service.save_events("2026-09-08", [{
            "name": "Dog walk",
            "type": "daily-task",
            "start_time": "2026-09-08T16:00:00",
            "end_time": "2026-09-08T16:40:00",
            "source": "daily-note",
            "source_ids": {"note_line": "h", "calendar_id": "gcal_new"},
        }])

        fresh = [
            {"name": "Dog walk", "type": "daily-task",
             "start_time": "2026-09-08T16:00:00", "end_time": "2026-09-08T16:40:00",
             "source": "daily-note", "source_ids": {"note_line": "h"}},
            {"name": "Dog walk", "type": "calendar",
             "start_time": "2026-09-08T16:00:00", "end_time": "2026-09-08T16:40:00",
             "source": "calendar", "source_ids": {"calendar_id": "gcal_new"}},
        ]

        persisted_id = events_service.get_events("2026-09-08")[0]["id"]

        result = events_service.reconcile("2026-09-08", fresh, {"calendar", "daily-note"})

        # The persisted row is claimed exactly once. (The other fresh event
        # is then simply unmatched and becomes a new row, which is the
        # correct outcome once this state exists at all — what must never
        # happen is the same stored dict, with the same id, coming back
        # twice.)
        assert [e.get("id") for e in result].count(persisted_id) == 1
        assert len({id(e) for e in result}) == len(result)


class TestReconcileRefreshesTheOwningCalendar:
    """`calendar` decides whether Mazkir may write to a Google entry.

    It is re-derived from the source on every merge, like name/start/end, so
    it belongs with those and not with the preserved enrichment. Without the
    copy, an event persisted before the field existed never acquires one and
    every edit falls through into a doomed patch reported as `update_failed`
    rather than the accurate `not_in_mazkir_calendar`.
    """

    def test_calendar_is_copied_from_the_fresh_event(self, events_service):
        events_service.save_events("2026-09-08", [{
            "name": "Standup", "type": "calendar",
            "start_time": "2026-09-08T10:00:00", "end_time": "2026-09-08T10:30:00",
            "source": "calendar", "source_ids": {"calendar_id": "cal_1"},
        }])

        result = events_service.reconcile("2026-09-08", [{
            "name": "Standup", "type": "calendar",
            "start_time": "2026-09-08T10:00:00", "end_time": "2026-09-08T10:30:00",
            "source": "calendar", "source_ids": {"calendar_id": "cal_1"},
            "calendar": "Work",
        }], {"calendar"})

        assert result[0]["calendar"] == "Work"

    def test_a_fresh_event_without_the_field_leaves_the_persisted_one_alone(
        self, events_service
    ):
        """A source that does not report a calendar must not blank one that
        was previously known."""
        events_service.save_events("2026-09-08", [{
            "name": "Standup", "type": "calendar",
            "start_time": "2026-09-08T10:00:00", "end_time": "2026-09-08T10:30:00",
            "source": "calendar", "source_ids": {"calendar_id": "cal_1"},
            "calendar": "Mazkir",
        }])

        result = events_service.reconcile("2026-09-08", [{
            "name": "Standup", "type": "calendar",
            "start_time": "2026-09-08T10:00:00", "end_time": "2026-09-08T10:30:00",
            "source": "calendar", "source_ids": {"calendar_id": "cal_1"},
        }], {"calendar"})

        assert result[0]["calendar"] == "Mazkir"


class TestManualOriginSurvivesCalendarEcho:
    """A block the user dictated must not become machine-inferred.

    `create_event` writes `source: "manual"` and syncs to Google Calendar,
    which stores a `calendar_id` in `source_ids`. On the next merge the
    calendar hands that same event back, it matches on `calendar_id`, and
    reconcile used to re-derive `source` and `name` from the echo — turning
    the user's own statement into a pending calendar entry (`resolve_state`
    keys on `source`) and importing the `📅` display prefix that
    `calendar_service` had added on the way out.

    The echo is not independent evidence: Mazkir wrote it. Observed on
    2026-09-12, where ten hours of dictated sleep rendered as `pending` with
    `confirmed_minutes: 0`.
    """

    def _echo(self, calendar_id: str) -> dict:
        """What the calendar source returns for an event Mazkir pushed."""
        return {
            "name": "📅 Sleep",
            "type": "calendar",
            "source": "calendar",
            "calendar": "Mazkir",
            "start_time": "2026-09-12T05:00:00+03:00",
            "end_time": "2026-09-12T15:00:00+03:00",
            "source_ids": {"calendar_id": calendar_id},
        }

    def test_dictated_block_stays_approved_after_calendar_echo(self, events_service):
        from src.services.approval import resolve_state

        events_service.create_event(
            date="2026-09-12", name="Sleep",
            start_time="05:00", end_time="15:00",
            source_ids={"calendar_id": "cal_sleep"},
        )
        assert resolve_state(events_service.get_events("2026-09-12")[0]) == "approved"

        result = events_service.reconcile(
            "2026-09-12", [self._echo("cal_sleep")], {"calendar"},
        )

        assert len(result) == 1
        assert result[0]["source"] == "manual"
        assert resolve_state(result[0]) == "approved"

    def test_calendar_echo_does_not_import_the_display_prefix(self, events_service):
        events_service.create_event(
            date="2026-09-12", name="Sleep",
            start_time="05:00", end_time="15:00",
            source_ids={"calendar_id": "cal_sleep"},
        )

        result = events_service.reconcile(
            "2026-09-12", [self._echo("cal_sleep")], {"calendar"},
        )

        assert result[0]["name"] == "Sleep"

    def test_a_real_calendar_event_still_tracks_its_source(self, events_service):
        """The narrow rule must not freeze genuine calendar events.

        Without this, the fix would be indistinguishable from "never update
        name or source from the calendar", and a renamed Google entry would
        stop propagating.
        """
        events_service.save_events("2026-09-12", [{
            "id": "evt_cal", "name": "Standup", "source": "calendar",
            "source_ids": {"calendar_id": "cal_standup"},
            "start_time": "2026-09-12T10:00:00", "end_time": "2026-09-12T10:30:00",
        }])

        result = events_service.reconcile("2026-09-12", [{
            "name": "Standup (moved)", "type": "calendar", "source": "calendar",
            "calendar": "Mazkir",
            "start_time": "2026-09-12T11:00:00", "end_time": "2026-09-12T11:30:00",
            "source_ids": {"calendar_id": "cal_standup"},
        }], {"calendar"})

        assert result[0]["name"] == "Standup (moved)"
        assert result[0]["source"] == "calendar"
