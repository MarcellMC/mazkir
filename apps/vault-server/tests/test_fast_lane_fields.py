# tests/test_fast_lane_fields.py
"""Spec §9.1–9.2: the fields a fast-lane block carries, and what a plan means for approval."""

import datetime as dt
from unittest.mock import MagicMock

from src.services.approval import has_begun, resolve_state
from src.services.events_service import EventsService

NOW = dt.datetime(2026, 9, 28, 12, 0)


def plan(start, **kw):
    return {"source": "manual", "intent": "plan", "start_time": start, "end_time": None, **kw}


def test_a_plan_whose_time_has_come_waits_for_confirmation():
    assert resolve_state(plan("2026-09-28T11:00:00"), now=NOW) == "pending"


def test_a_plan_still_ahead_is_not_yet_a_question():
    assert resolve_state(plan("2026-09-28T15:00:00"), now=NOW) == "approved"


def test_a_confirmed_plan_is_approved():
    assert resolve_state(plan("2026-09-28T11:00:00", state="approved"), now=NOW) == "approved"


def test_rows_without_intent_keep_their_meaning():
    assert resolve_state({"source": "manual", "start_time": "2026-09-28T11:00:00"}, now=NOW) == "approved"
    assert resolve_state({"source": "manual", "intent": "record",
                          "start_time": "2026-09-28T11:00:00"}, now=NOW) == "approved"


def test_has_begun_reads_the_end_when_there_is_no_start():
    assert has_begun({"start_time": None, "end_time": "2026-09-28T11:30:00"}, NOW)
    assert not has_begun({"start_time": "2026-09-28T12:30:00"}, NOW)
    assert not has_begun({}, NOW)


def test_create_event_keeps_only_the_known_fields(tmp_path):
    events = EventsService(tmp_path / "events")
    events.create_event("2026-09-27", "Dog walk", "2026-09-27T23:15:00", "2026-09-27T23:35:00",
                        fields={"intent": "record", "end_precision": "exact", "bogus": 1, "project": None})
    [stored] = events.get_events("2026-09-27")
    assert stored["intent"] == "record" and stored["end_precision"] == "exact"
    assert "bogus" not in stored and "project" not in stored


def make_agent(tmp_path, calendar=None):
    from src.services.agent_service import AgentService
    events = EventsService(tmp_path / "events")
    agent = AgentService(claude=MagicMock(), vault=MagicMock(), memory=MagicMock(),
                         calendar=calendar, media_path=tmp_path / "media", events=events)
    return agent, events


def test_create_event_records_fast_fields_and_can_defer_the_calendar(tmp_path):
    calendar = MagicMock(is_initialized=True)
    agent, events = make_agent(tmp_path, calendar)
    result = agent.run_tool("create_event", {
        "name": "Dog walk", "date": "2026-09-27",
        "start_time": "2026-09-27T23:15:00", "end_time": "2026-09-27T23:35:00",
        "_fast": {"defer_calendar_sync": True,
                  "fields": {"intent": "record", "start_precision": "exact", "end_precision": "exact",
                             "logical_date": "2026-09-27",
                             "evidence": {"text": "Dog walk 23:15-23:35", "message_id": 7}}},
    })
    assert result["ok"] and result["data"]["calendar_sync"]["reason"] == "deferred"
    calendar.create_event.assert_not_called()
    [stored] = events.get_events("2026-09-27")
    assert stored["intent"] == "record" and stored["evidence"]["message_id"] == 7


def test_update_event_applies_fast_fields_and_state_without_pinning_them(tmp_path):
    calendar = MagicMock(is_initialized=True)
    agent, events = make_agent(tmp_path, calendar)
    created = events.create_event("2026-09-28", "Gym", "2026-09-28T18:00:00", "2026-09-28T19:00:00",
                                  fields={"intent": "plan"})
    result = agent.run_tool("update_event", {
        "event_id": created["id"], "date": "2026-09-28", "end_time": "2026-09-28T19:15:00",
        "_fast": {"defer_calendar_sync": True, "state": "approved",
                  "fields": {"intent": "record", "end_precision": "exact"}},
    })
    assert result["ok"] and result["data"]["calendar_sync"]["reason"] == "deferred"
    calendar.update_event.assert_not_called()
    [stored] = events.get_events("2026-09-28")
    assert stored["intent"] == "record" and stored["state"] == "approved"
    assert stored["end_time"] == "2026-09-28T19:15:00"
    assert "end_time" in stored["user_set"]                       # what the user said is pinned
    assert not {"intent", "end_precision", "state"} & set(stored["user_set"])   # the fast lane's own fields are not
