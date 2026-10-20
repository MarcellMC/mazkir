"""Spec §7.5: what Google is told about a block, decided in one place."""

from unittest.mock import AsyncMock, MagicMock

from src.services.calendar_push import sync_block
from src.services.events_service import EventsService


def cal():
    c = MagicMock(is_initialized=True)
    c.create_event = AsyncMock(return_value="g123")
    c.update_event = AsyncMock(return_value=True)
    return c


def test_a_new_block_is_created_in_google_and_remembers_the_id(tmp_path):
    events = EventsService(tmp_path)
    e = events.create_event("2026-09-28", "Gym", "2026-09-28T18:00:00", "2026-09-28T19:00:00")
    c = cal()
    assert sync_block(c, events, "2026-09-28", e["id"]) == {"ok": True, "attempted": True, "event_id": "g123"}
    assert c.create_event.await_args.kwargs["start_time"] == "18:00"
    assert events.get_events("2026-09-28")[0]["source_ids"] == {"calendar_id": "g123"}


def test_a_synced_block_is_updated_not_duplicated(tmp_path):
    events = EventsService(tmp_path)
    e = events.create_event("2026-09-28", "Gym", "2026-09-28T18:00:00", "2026-09-28T19:00:00",
                            source_ids={"calendar_id": "g1"})
    c = cal()
    assert sync_block(c, events, "2026-09-28", e["id"]) == {"ok": True, "attempted": True, "event_id": "g1"}
    c.create_event.assert_not_awaited()


def test_blocks_google_must_not_hear_about(tmp_path):
    events = EventsService(tmp_path)
    blocks = [
        events.create_event("2026-09-28", "Nap", "2026-09-28T14:00:00", "2026-09-28T14:30:00", proposed=True),
        events.create_event("2026-09-28", "Walk", None, "2026-09-28T15:00:00"),
        events.create_event("2026-09-28", "Party", "2026-09-28T23:00:00", "2026-09-29T01:00:00"),
        events.create_event("2026-09-28", "Checkbox", "2026-09-28T09:00:00", "2026-09-28T09:30:00",
                            source_ids={"note_line": "abc"}),
    ]
    c = cal()
    reasons = [sync_block(c, events, "2026-09-28", b["id"])["reason"] for b in blocks]
    assert reasons == ["proposed", "no_start_time", "crosses_midnight", "derived_from_source"]
    assert sync_block(c, events, "2026-09-28", "evt_missing")["reason"] == "not_found"
    assert sync_block(None, events, "2026-09-28", blocks[1]["id"])["reason"] == "no_start_time"
    c.create_event.assert_not_awaited()


def test_a_failing_calendar_is_reported_not_raised(tmp_path):
    events = EventsService(tmp_path)
    e = events.create_event("2026-09-28", "Gym", "2026-09-28T18:00:00", "2026-09-28T19:00:00")
    c = cal()
    # Not RuntimeError: async_bridge.maybe_await reads that as "already inside a loop".
    c.create_event = AsyncMock(side_effect=ConnectionError("quota"))
    assert sync_block(c, events, "2026-09-28", e["id"]) == {"ok": False, "attempted": True, "reason": "quota"}


def test_a_block_undone_while_google_creates_it_takes_its_google_entry_with_it(tmp_path):
    events = EventsService(tmp_path)
    e = events.create_event("2026-09-28", "Gym", "2026-09-28T18:00:00", "2026-09-28T19:00:00")
    c = cal()

    async def create_while_undone(**kw):
        events.delete_event("2026-09-28", e["id"])     # undo lands mid-create: no calendar_id yet
        return "g123"

    c.create_event = AsyncMock(side_effect=create_while_undone)
    c.delete_event = AsyncMock(return_value=True)
    sync = sync_block(c, events, "2026-09-28", e["id"])
    assert sync == {"ok": False, "attempted": False, "reason": "undone_meanwhile"}
    c.delete_event.assert_awaited_once_with("g123")
    assert events.get_events("2026-09-28") == []


def test_undone_meanwhile_draws_no_warning_on_the_receipt():
    from src.services.fast_lane.receipt import _sync_label
    assert _sync_label({"ok": False, "attempted": False, "reason": "undone_meanwhile"}) is None
