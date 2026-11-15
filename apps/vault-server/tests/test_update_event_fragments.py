"""A block split at midnight is one block to the user (2026-11-15).

Renaming the 14th's half of the Chaser bar stay left the 15th's half under
its old name, so the night read as two different things.
"""

from __future__ import annotations

from src.services.events_service import EventsService
from tests.test_agent_service import agent, mock_services  # noqa: F401  (fixtures)


def _split(tmp_path, agent):  # noqa: F811
    ev = EventsService(tmp_path / "events")
    agent.events, agent.calendar = ev, None
    a = ev.create_event("2026-11-14", "Went to Chaser bar", "2026-11-14T23:57:40", "2026-11-14T23:59:59",
                        logical_id="6b742297", proposed=True)["id"]
    b = ev.create_event("2026-11-15", "Went to Chaser bar", "2026-11-15T00:00:00", "2026-11-15T02:47:02",
                        logical_id="6b742297", proposed=True)["id"]
    ride = ev.create_event("2026-11-15", "Ride back home", "2026-11-15T02:47:02", "2026-11-15T02:57:46")["id"]
    return ev, a, b, ride


def _get(ev, date, eid):
    return next(e for e in ev.get_events(date) if e["id"] == eid)


def test_renaming_one_half_renames_the_other(agent, tmp_path):  # noqa: F811
    ev, a, b, ride = _split(tmp_path, agent)
    out = agent._tool_update_event({"event_id": a, "date": "2026-11-14", "name": "Chaser bar"})
    assert out["ok"] and out["data"]["fragments_updated"] == [b]
    assert _get(ev, "2026-11-15", b)["name"] == "Chaser bar"
    assert _get(ev, "2026-11-15", b)["user_set"].get("name") == "Chaser bar"
    assert _get(ev, "2026-11-15", ride)["name"] == "Ride back home"


def test_the_later_half_reaches_back_too(agent, tmp_path):  # noqa: F811
    ev, a, b, _ = _split(tmp_path, agent)
    agent._tool_update_event({"event_id": b, "date": "2026-11-15", "name": "Chaser bar", "activity": "bar"})
    first = _get(ev, "2026-11-14", a)
    assert (first["name"], first["activity"]) == ("Chaser bar", "bar")


def test_times_stay_with_their_own_half(agent, tmp_path):  # noqa: F811
    ev, a, b, _ = _split(tmp_path, agent)
    out = agent._tool_update_event({"event_id": b, "date": "2026-11-15", "end_time": "2026-11-15T02:50:00"})
    assert out["data"].get("fragments_updated", []) == []
    assert _get(ev, "2026-11-14", a)["end_time"] == "2026-11-14T23:59:59"
