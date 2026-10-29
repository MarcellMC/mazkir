# tests/test_fast_lane_receipt_routes.py
"""Spec §8.2, §10: what a tap on a receipt does."""

import datetime as dt
import threading
import time
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes import fast_lane as receipts_route
from src.services.events_service import EventsService
from src.services.fast_lane.act import load_turn, run_lines, save_turn
from src.services.fast_lane.actions import PlannedLine, Step

WORKOUT = "20-habits/workout.md"   # conftest: streak 5


def setup(monkeypatch, tmp_path, vault, calendar=None, run_tool=None):
    from src.services.agent_service import AgentService
    events = EventsService(tmp_path / "events")
    agent = AgentService(claude=MagicMock(), vault=vault, memory=MagicMock(), media_path=tmp_path / "media",
                         events=events)
    monkeypatch.setattr(receipts_route, "get_receipt_deps", lambda: {
        "run_tool": run_tool or agent.run_tool, "events": events, "vault": vault, "calendar": calendar,
        "data_dir": tmp_path})
    app = FastAPI()
    app.include_router(receipts_route.router)
    return TestClient(app), agent, events


def create(name, start, end, **extra):
    return {"tool": "create_event", "params": {"name": name, "date": start[:10], "start_time": start, "end_time": end,
                                               **extra,
                                               "_fast": {"defer_calendar_sync": True, "fields": {"intent": "record"}}}}


def save(tmp_path, records, turn_id="t0000beef"):
    turn = {"turn_id": turn_id, "chat_id": 1, "message_id": 7, "created_at": dt.datetime.now().isoformat(),
            "text": "x", "route": "fast", "lines": records}
    save_turn(tmp_path / "actions", turn)
    return turn


def saved(tmp_path, turn_id="t0000beef"):
    return load_turn(tmp_path / "actions", turn_id)


def question(tmp_path):
    save(tmp_path, run_lines([PlannedLine("question", "question", "Gym", reason="no time given")],
                             run_tool=MagicMock(), events=MagicMock()))


def test_ok_on_a_pending_proposal_runs_it_and_no_writes_nothing(monkeypatch, tmp_path, vault_service):
    client, agent, events = setup(monkeypatch, tmp_path, vault_service)
    lines = [PlannedLine("propose", "proposal", "End Work at 13:00?",
                         pending=(Step("create_event", create("Lunch", "2026-01-10T13:00:00", "2026-01-10T13:30:00")["params"]),)),
             PlannedLine("propose", "proposal", "Also this?",
                         pending=(Step("create_event", create("Other", "2026-01-10T15:00:00", "2026-01-10T15:30:00")["params"]),))]
    save(tmp_path, run_lines(lines, run_tool=agent.run_tool, events=events))
    assert client.post("/fast/receipts/t0000beef/0/ok").json()["receipt"]["lines"][0]["glyph"] == "✓"
    assert client.post("/fast/receipts/t0000beef/1/no").json()["receipt"]["lines"][1]["glyph"] == "✕"
    assert [e["name"] for e in events.get_events("2026-01-10")] == ["Lunch"]
    assert client.post("/fast/receipts/t0000beef/0/ok").json()["toast"] == "Already settled"
    assert client.post("/fast/receipts/t0000beef/1/ok").json()["toast"] == "Already settled"
    assert [e["name"] for e in events.get_events("2026-01-10")] == ["Lunch"]
    # The proposal's call ran, so undo now reaches it.
    assert saved(tmp_path)["lines"][0]["undo"][0]["kind"] == "created"


def test_ok_on_a_fuzzy_habit_proposal_ticks_it_and_clears_the_candidate(monkeypatch, tmp_path, vault_service):
    client, agent, events = setup(monkeypatch, tmp_path, vault_service)
    line = PlannedLine("propose", "proposal", "Workout", pending=(Step("complete_habit", {"habit_name": "Workout"}),),
                       reason="did you mean Workout?", habit_candidate={"path": WORKOUT, "name": "Workout"})
    save(tmp_path, run_lines([line], run_tool=agent.run_tool, events=events))
    body = client.post("/fast/receipts/t0000beef/0/ok").json()
    rec = saved(tmp_path)["lines"][0]
    assert body["toast"] == "Done" and rec["status"] == "approved"
    assert rec["habit"]["name"] == "Workout" and rec["habit_candidate"] is None
    assert vault_service.read_file(WORKOUT)["metadata"]["streak"] == 6


def test_undo_route_reverses_the_turn(monkeypatch, tmp_path, vault_service):
    client, agent, events = setup(monkeypatch, tmp_path, vault_service)
    step = Step("create_event", create("Gym", "2026-01-10T08:00:00", "2026-01-10T09:00:00")["params"])
    save(tmp_path, run_lines([PlannedLine("block", "fact", "Gym", steps=(step,))], run_tool=agent.run_tool, events=events))
    body = client.post("/fast/receipts/t0000beef/u/un").json()
    assert body["toast"] == "Undone 1" and body["receipt"]["lines"][0]["glyph"] == "↶"
    assert body["receipt"]["undo"] is None and events.get_events("2026-01-10") == []
    assert saved(tmp_path)["lines"][0]["status"] == "undone"


def test_undo_after_a_day_is_refused_with_a_toast(monkeypatch, tmp_path, vault_service):
    client, agent, events = setup(monkeypatch, tmp_path, vault_service)
    step = Step("create_event", create("Gym", "2026-01-10T08:00:00", "2026-01-10T09:00:00")["params"])
    turn = save(tmp_path, run_lines([PlannedLine("block", "fact", "Gym", steps=(step,))],
                                    run_tool=agent.run_tool, events=events))
    turn["created_at"] = (dt.datetime.now() - dt.timedelta(hours=25)).isoformat()
    save_turn(tmp_path / "actions", turn)
    body = client.post("/fast/receipts/t0000beef/u/un").json()
    assert body["toast"].startswith("Too late to undo")
    assert len(events.get_events("2026-01-10")) == 1 and saved(tmp_path)["lines"][0]["status"] == "done"


def test_undo_that_google_refuses_answers_with_the_line_kept(monkeypatch, tmp_path, vault_service):
    calendar = MagicMock(is_initialized=True)
    calendar.delete_event = AsyncMock(side_effect=RuntimeError("503 from Google"))
    client, agent, events = setup(monkeypatch, tmp_path, vault_service, calendar=calendar)
    step = Step("create_event", create("Gym", "2026-01-10T08:00:00", "2026-01-10T09:00:00")["params"])
    turn = save(tmp_path, run_lines([PlannedLine("block", "fact", "Gym", steps=(step,))],
                                    run_tool=agent.run_tool, events=events))
    events.update_event("2026-01-10", turn["lines"][0]["event_id"], {"source_ids": {"calendar_id": "g1"}})
    response = client.post("/fast/receipts/t0000beef/u/un")
    assert response.status_code == 200
    assert response.json()["toast"] == "Nothing undone, 1 kept"
    assert "Google refused" in response.json()["receipt"]["lines"][0]["reason"]


def test_add_a_place_from_the_receipt(monkeypatch, tmp_path, vault_service):
    client, agent, events = setup(monkeypatch, tmp_path, vault_service)
    step = Step("create_event", create("Coffee", "2026-01-10T08:00:00", "2026-01-10T08:30:00")["params"])
    [rec] = run_lines([PlannedLine("block", "fact", "Coffee", steps=(step,), place_text="the corner cafe")],
                      run_tool=agent.run_tool, events=events)
    save(tmp_path, [rec])
    body = client.post("/fast/receipts/t0000beef/0/pl").json()
    assert body["toast"] == "Added the corner cafe"
    assert events.get_events("2026-01-10")[0]["place_id"] == "the-corner-cafe"
    assert all(b["data"] != "rcpt:t0000beef:0:pl" for b in body["receipt"]["lines"][0]["buttons"])
    assert client.post("/fast/receipts/t0000beef/0/pl").json()["toast"] == "Already settled"


def test_a_habit_tap_ticks_it_at_the_blocks_own_time_and_undo_takes_it_back(monkeypatch, tmp_path, vault_service):
    client, agent, events = setup(monkeypatch, tmp_path, vault_service)
    step = Step("create_event", create("Workouts", "2026-01-10T08:00:00", "2026-01-10T09:00:00")["params"])
    save(tmp_path, run_lines([PlannedLine("block", "fact", "Workouts", steps=(step,),
                                          habit_candidate={"path": WORKOUT, "name": "Workout"})],
                             run_tool=agent.run_tool, events=events))
    body = client.post("/fast/receipts/t0000beef/0/hb").json()
    assert body["toast"] == "Ticked Workout"
    [event] = events.get_events("2026-01-10")
    assert event["habit_completion"]["completed_at"].startswith("2026-01-10T09:00")   # the block's end
    assert vault_service.read_file(WORKOUT)["metadata"]["streak"] == 6
    assert saved(tmp_path)["lines"][0]["habit_candidate"] is None
    assert body["receipt"]["lines"][0]["detail"].startswith("🎯 Workout")
    assert client.post("/fast/receipts/t0000beef/0/hb").json()["toast"] == "Already settled"
    assert client.post("/fast/receipts/t0000beef/u/un").json()["toast"] == "Undone 1"
    assert vault_service.read_file(WORKOUT)["metadata"]["streak"] == 5


def suggestion(tmp_path):
    save(tmp_path, [{"id": 0, "kind": "suggest", "outcome": "proposal", "status": "pending",
                     "text": "Track “Swim” as a habit?", "reason": "", "suggest": "Swim", "start": None, "end": None,
                     "end_precision": None, "day": None, "date": None, "event_id": None, "calendar_sync": None,
                     "habit": None, "habit_candidate": None, "place_text": None, "pending": [], "undo": []}])


def test_track_it_creates_the_habit(monkeypatch, tmp_path, vault_service):
    client, _, _ = setup(monkeypatch, tmp_path, vault_service)
    suggestion(tmp_path)
    body = client.post("/fast/receipts/t0000beef/0/sy").json()
    assert body["toast"] == "Tracking Swim" and body["receipt"]["lines"][0]["buttons"] == []
    assert "Swim" in [h["metadata"]["name"] for h in vault_service.list_active_habits()]
    assert client.post("/fast/receipts/t0000beef/0/sy").json()["toast"] == "Already settled"


def test_not_now_declines_the_suggestion(monkeypatch, tmp_path, vault_service):
    import json
    client, _, _ = setup(monkeypatch, tmp_path, vault_service)
    suggestion(tmp_path)
    body = client.post("/fast/receipts/t0000beef/0/sn").json()
    assert body["toast"] == "Not now" and saved(tmp_path)["lines"][0]["status"] == "dismissed"
    assert "swim" in json.loads((tmp_path / "fast-lane-suggestions.json").read_text())["declined"]


def proposal_block(monkeypatch, tmp_path, vault_service, **kw):
    """A proposed block written by the turn, and /day's approval wired to the same services."""
    import src.main as main
    from src.api.routes import events as events_route
    client, agent, events = setup(monkeypatch, tmp_path, vault_service, **kw)

    async def no_sources(date):
        return [], set()
    monkeypatch.setattr(events_route, "_merge_from_sources", no_sources)
    monkeypatch.setattr(main, "get_events", lambda: events)
    monkeypatch.setattr(main, "get_vault", lambda: vault_service)
    monkeypatch.setattr(main, "get_calendar", lambda: kw.get("calendar"))
    step = Step("create_event", create("Lunch", "2026-01-10T13:00:00", "2026-01-10T13:30:00", proposed=True)["params"])
    save(tmp_path, run_lines([PlannedLine("block", "proposal", "Lunch", steps=(step,))],
                             run_tool=agent.run_tool, events=events))
    return client, events


def test_ok_on_a_proposed_block_approves_it_through_day_and_undo_still_reaches_it(monkeypatch, tmp_path, vault_service):
    client, events = proposal_block(monkeypatch, tmp_path, vault_service)
    body = client.post("/fast/receipts/t0000beef/0/ok").json()
    assert body["toast"] == "Approved" and body["receipt"]["lines"][0]["glyph"] == "✓"
    assert events.get_events("2026-01-10")[0]["state"] == "approved"
    assert "13:00" in vault_service.read_daily_note("2026-01-10")["content"]   # /day's settle wrote ## Schedule
    assert client.post("/fast/receipts/t0000beef/0/ok").json()["toast"] == "Already settled"
    # The approval is Mazkir's own doing from this receipt, not a change made since.
    assert client.post("/fast/receipts/t0000beef/u/un").json()["toast"] == "Undone 1"
    assert events.get_events("2026-01-10") == []


def test_no_on_a_proposed_block_dismisses_it(monkeypatch, tmp_path, vault_service):
    client, events = proposal_block(monkeypatch, tmp_path, vault_service)
    body = client.post("/fast/receipts/t0000beef/0/no").json()
    assert body["toast"] == "Dismissed" and body["receipt"]["lines"][0]["glyph"] == "✕"
    assert events.get_events("2026-01-10")[0]["state"] == "dismissed"


def test_an_approval_google_refuses_still_approves_and_says_so(monkeypatch, tmp_path, vault_service):
    calendar = MagicMock(is_initialized=True)
    calendar.create_event = AsyncMock(side_effect=RuntimeError("Google is down"))
    client, events = proposal_block(monkeypatch, tmp_path, vault_service, calendar=calendar)
    response = client.post("/fast/receipts/t0000beef/0/ok")
    assert response.status_code == 200 and response.json()["toast"] == "Approved"
    assert response.json()["receipt"]["lines"][0]["sync"].startswith("⚠ calendar")


def test_an_approval_that_raises_leaves_the_line_pending_with_a_toast(monkeypatch, tmp_path, vault_service):
    from src.api.routes import events as events_route
    client, events = proposal_block(monkeypatch, tmp_path, vault_service)

    async def broken(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(events_route, "set_event_state", broken)
    response = client.post("/fast/receipts/t0000beef/0/ok")
    assert response.status_code == 200 and response.json()["toast"] == "That didn't work"
    assert saved(tmp_path)["lines"][0]["status"] == "pending"


def test_unknown_turns_lines_and_actions_are_404(monkeypatch, tmp_path, vault_service):
    client, _, _ = setup(monkeypatch, tmp_path, vault_service)
    assert client.get("/fast/receipts/t00000000").status_code == 404
    # Decoded, this is three segments and lands on the tap route, which has no GET.
    assert client.get("/fast/receipts/..%2F..%2Fetc").status_code in (404, 405)
    assert client.get("/fast/receipts/..%2Fetc").status_code == 404
    assert client.get("/fast/receipts/t0000beef%0A").status_code == 404
    assert client.get("/fast/receipts/T0000BEEF").status_code == 404
    question(tmp_path)
    assert client.get("/fast/receipts/t0000beef").status_code == 200
    assert client.post("/fast/receipts/t0000beef/7/ok").status_code == 404
    assert client.post("/fast/receipts/t0000beef/-1/ok").status_code == 404
    assert client.post("/fast/receipts/t0000beef/x/ok").status_code == 404
    assert client.post("/fast/receipts/t0000beef/0/zz").status_code == 404
    assert client.post("/fast/receipts/t00000000/0/ok").status_code == 404
    assert client.post("/fast/receipts/t00000000/u/un").status_code == 404
    assert client.post("/fast/receipts/..%2Fx/u/un").status_code == 404


def test_two_simultaneous_taps_on_one_line_run_it_once(monkeypatch, tmp_path, vault_service):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def slow_run_tool(name, params):
        calls.append(name)
        entered.set()
        release.wait(5)
        return agent.run_tool(name, params)

    client, agent, events = setup(monkeypatch, tmp_path, vault_service, run_tool=slow_run_tool)
    line = PlannedLine("propose", "proposal", "Lunch?",
                       pending=(Step("create_event", create("Lunch", "2026-01-10T13:00:00", "2026-01-10T13:30:00")["params"]),))
    save(tmp_path, run_lines([line], run_tool=agent.run_tool, events=events))
    toasts = []
    taps = [threading.Thread(target=lambda: toasts.append(client.post("/fast/receipts/t0000beef/0/ok").json()["toast"]))
            for _ in range(2)]
    taps[0].start()
    assert entered.wait(5)
    taps[1].start()
    time.sleep(0.2)   # the second tap is now waiting on the turn's lock
    release.set()
    for t in taps:
        t.join(5)
    assert sorted(toasts) == ["Already settled", "Done"]
    assert calls == ["create_event"] and len(events.get_events("2026-01-10")) == 1


def test_an_undo_racing_a_sync_patch_keeps_both(monkeypatch, tmp_path, vault_service):
    """The on-route patches each line's Google sync onto the saved turn while undo may be mid-flight."""
    from src.api.routes.message import _patch_turn
    entered, release = threading.Event(), threading.Event()

    async def slow_delete(google_id):
        entered.set()
        release.wait(5)
        return True

    calendar = MagicMock(is_initialized=True)
    calendar.delete_event = slow_delete
    client, agent, events = setup(monkeypatch, tmp_path, vault_service, calendar=calendar)
    steps = [Step("create_event", create(n, f"2026-01-10T0{h}:00:00", f"2026-01-10T0{h}:30:00")["params"])
             for n, h in (("Gym", 8), ("Walk", 9))]
    turn = save(tmp_path, run_lines([PlannedLine("block", "fact", "Gym", steps=(steps[0],)),
                                     PlannedLine("block", "fact", "Walk", steps=(steps[1],))],
                                    run_tool=agent.run_tool, events=events))
    events.update_event("2026-01-10", turn["lines"][1]["event_id"], {"source_ids": {"calendar_id": "g1"}})
    out = {}
    undo = threading.Thread(target=lambda: out.update(undo=client.post("/fast/receipts/t0000beef/u/un").json()))
    undo.start()
    assert entered.wait(5)   # undo holds the turn while Google answers

    def patch(saved_turn):
        saved_turn["lines"][0]["calendar_sync"] = {"ok": True, "attempted": True}

    sync = threading.Thread(target=_patch_turn, args=(tmp_path / "actions", turn, patch))
    sync.start()
    time.sleep(0.2)
    assert sync.is_alive()   # the sync patch waits for the undo rather than overwrite it
    release.set()
    undo.join(5)
    sync.join(5)
    assert out["undo"]["toast"] == "Undone 2"
    final = saved(tmp_path)
    assert [line["status"] for line in final["lines"]] == ["undone", "undone"]
    assert final["lines"][0]["calendar_sync"] == {"ok": True, "attempted": True}
