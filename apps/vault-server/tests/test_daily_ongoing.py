"""A block still going on is drawn up to now (2026-11-15, the Chaser bar night).

A trip's stop and an open fast-lane block have a start and no end until they
end. /day listed them under "Needs a time", and the next day — when the stay
crossed midnight — showed nothing at all, because the block lives in the
previous day's file.
"""

from __future__ import annotations

import datetime as dt

import pytz

from src.api.routes.daily import (
    _build_blocks_and_coverage,
    _build_incomplete,
    _with_ongoing,
)

TZ = pytz.timezone("Asia/Jerusalem")
NOW = TZ.localize(dt.datetime(2026, 11, 15, 2, 26))


def bar(start="2026-11-14T23:57:40", **extra):
    return {"id": "evt_bar", "name": "Chaser bar", "start_time": start, "end_time": None,
            "source": "manual", "proposed": True, **extra}


def test_open_block_runs_to_midnight_on_its_own_day():
    events = _with_ongoing([bar()], [], "2026-11-14", NOW)
    blocks, _, _ = _build_blocks_and_coverage(events, "2026-11-14", 1440)
    [b] = blocks
    assert (b.start, b.end, b.ongoing) == ("23:57", "24:00", True)
    assert _build_incomplete(events, "2026-11-14") == []


def test_open_block_from_yesterday_carries_into_today():
    events = _with_ongoing([], [bar()], "2026-11-15", NOW)
    blocks, gaps, coverage = _build_blocks_and_coverage(events, "2026-11-15", 2 * 60 + 26)
    [b] = blocks
    assert (b.start, b.end, b.ongoing, b.title) == ("00:00", "02:26", True, "Chaser bar")
    assert gaps == [] and coverage.unaccounted_minutes == 0


def test_offset_timestamps_work_too():
    events = _with_ongoing([], [bar(start="2026-11-14T21:57:40+00:00")], "2026-11-15", NOW)
    blocks, _, _ = _build_blocks_and_coverage(events, "2026-11-15", 146)
    assert [(b.start, b.end) for b in blocks] == [("00:00", "02:26")]


def test_an_open_block_older_than_twelve_hours_still_needs_a_time():
    old = bar(start="2026-11-14T14:00:00")
    events = _with_ongoing([old], [], "2026-11-14", NOW)
    assert _build_blocks_and_coverage(events, "2026-11-14", 1440)[0] == []
    assert [i.id for i in _build_incomplete(events, "2026-11-14")] == ["evt_bar"]
    assert _with_ongoing([], [old], "2026-11-15", NOW) == []


def test_a_block_that_has_not_started_is_left_alone():
    later = bar(start="2026-11-15T09:00:00")
    events = _with_ongoing([later], [], "2026-11-15", NOW)
    assert _build_blocks_and_coverage(events, "2026-11-15", 146)[0] == []


def test_dismissed_and_finished_blocks_are_not_carried():
    done = {**bar(), "end_time": "2026-11-15T00:30:00"}
    dismissed = {**bar(), "id": "evt_x", "state": "dismissed"}
    assert _with_ongoing([], [done, dismissed], "2026-11-15", NOW) == []


def test_the_stored_event_is_not_changed():
    stored = bar()
    _with_ongoing([stored], [stored], "2026-11-15", NOW)
    assert stored["end_time"] is None and "start_time" in stored and stored["start_time"].startswith("2026-11-14")


def test_approve_all_skips_an_ongoing_block(monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.routes import daily as daily_route
    from src.api.routes.daily import DailyBlock, DailyResponse, DayCoverage
    from src.main import app

    day = DailyResponse(
        date="2026-11-15", tokens_today=0, tokens_total=0, gaps=[], todos=[], notes=[],
        blocks=[DailyBlock(id="evt_bar", start="00:00", end="02:26", title="Chaser bar", source="manual",
                           type="event", state="pending", ongoing=True)],
        coverage=DayCoverage(covered_minutes=146, unaccounted_minutes=0, elapsed_minutes=146),
    )

    async def fake_get_daily(date):
        return day
    calls = []

    async def fake_set_state(date, event_id, body):
        calls.append(event_id)
    monkeypatch.setattr(daily_route, "get_daily", fake_get_daily)
    monkeypatch.setattr(daily_route, "_set_state_for_approve_all", fake_set_state)
    body = TestClient(app).post("/daily/2026-11-15/approve-all").json()
    assert calls == [] and body["approved"] == []


def test_route_carries_yesterdays_open_block(monkeypatch):
    from unittest.mock import MagicMock, patch

    from fastapi.testclient import TestClient

    from src.api.routes import daily as daily_route
    from src.main import app

    vault = MagicMock()
    vault.read_daily_note.return_value = {"content": "", "path": "10-daily/x.md"}
    vault.list_active_habits.return_value = []
    vault.read_token_ledger.return_value = {"metadata": {}}

    async def no_events(target_date):
        return {"date": target_date.isoformat(), "events": [], "summary": {}}
    svc = MagicMock()
    svc.get_events.side_effect = lambda d: [bar()] if d == "2026-11-14" else []

    class FrozenNow(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW
    monkeypatch.setattr(daily_route, "datetime", FrozenNow)
    monkeypatch.setattr(daily_route, "tz", TZ)
    with patch("src.main.get_vault", return_value=vault), \
            patch("src.main.get_events", return_value=svc), \
            patch("src.api.routes.events.get_events_preview", side_effect=no_events):
        body = TestClient(app).get("/daily", params={"date": "2026-11-15"}).json()
    assert [(b["title"], b["start"], b["end"], b["ongoing"]) for b in body["blocks"]] == \
        [("Chaser bar", "00:00", "02:26", True)]
