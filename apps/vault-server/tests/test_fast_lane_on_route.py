"""Spec §5.5, §8.1, §10: the message route when the fast lane is on."""

import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.services.calendar_push as calendar_push
import src.services.fast_lane.context as context_module
import src.services.fast_lane.turn as turn_module
from src.api.routes import message as route
from src.config import settings
from src.services.agent_service import AgentResponse
from src.services.fast_lane import act
from src.services.fast_lane.turn import NO_RECEIPT, FastDeps, FastTurn

LINE = {"id": 0, "kind": "block", "outcome": "fact", "text": "Gym", "status": "done", "reason": "",
        "start": "2026-01-10T18:00:00", "end": "2026-01-10T19:00:00", "end_precision": "exact", "day": None,
        "date": "2026-01-10", "event_id": "evt_1", "calendar_sync": {"ok": False, "attempted": False, "reason": "deferred"},
        "habit": None, "habit_candidate": None, "place_text": None, "pending": [],
        "undo": [{"kind": "created"}]}


def a_turn():
    return {"turn_id": "t0000beef", "chat_id": 1, "message_id": 9, "created_at": "2026-01-10T20:00:00+02:00",
            "text": "Gym 18:00-19:00", "route": "fast", "fallthrough_skill": None, "response": "",
            "lines": [dict(LINE)]}


def make(monkeypatch, tmp_path, fast, *, saved=True):
    monkeypatch.setattr(settings, "fast_lane_mode", "on")
    agent = MagicMock()
    agent.handle_message.return_value = AgentResponse(response="skill reply", iterations=1)
    monkeypatch.setattr(route, "get_agent", lambda: agent)
    deps = FastDeps(claude=None, run_tool=agent.run_tool, events=MagicMock(), vault=MagicMock(), memory=MagicMock(),
                    actions_dir=tmp_path / "actions", places_path=tmp_path / "p.json",
                    suggestions_path=tmp_path / "s.json", skills_dir=None)
    monkeypatch.setattr(route, "get_fast_turn_deps", lambda a: (deps, MagicMock()))
    monkeypatch.setattr(context_module, "assemble_fast_context", lambda **kw: SimpleNamespace(**kw))
    monkeypatch.setattr(calendar_push, "sync_block", lambda *a: {"ok": True, "attempted": True, "event_id": "g1"})
    if saved and fast.turn is not None:      # run_fast_turn saves its turn before returning
        act.save_turn(deps.actions_dir, fast.turn)

    def fake_run(ctx, deps, s, **kw):
        kw["on_stage"]("Reading…")
        return fast

    monkeypatch.setattr(turn_module, "run_fast_turn", fake_run)
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app), agent


def post(client, **extra):
    return client.post("/message", json={"text": "Gym 18:00-19:00", "chat_id": 1, "message_id": 9, **extra})


def fast_turn():
    from src.services.fast_lane.receipt import render_receipt
    import datetime as dt
    turn = a_turn()
    return FastTurn(route="fast", turn=turn, receipt=render_receipt(turn, dt.datetime(2026, 1, 10, 20, 0)))


def test_a_fast_turn_answers_with_its_receipt_and_no_agent(monkeypatch, tmp_path):
    fast = fast_turn()
    client, agent = make(monkeypatch, tmp_path, fast)
    body = post(client).json()
    agent.handle_message.assert_not_called()
    assert body["route"] == "fast" and body["response"] == fast.receipt["text"]
    assert body["receipt"]["lines"][0]["sync"] == "✓ calendar"      # synced after the receipt


def test_a_fast_turn_whose_receipt_failed_still_never_reaches_the_agent(monkeypatch, tmp_path):
    client, agent = make(monkeypatch, tmp_path, FastTurn(route="fast", turn=a_turn(), receipt=None))
    body = post(client).json()
    agent.handle_message.assert_not_called()
    assert body["route"] == "fast" and body["response"] == NO_RECEIPT


def test_fallthrough_goes_to_the_parse_skill_without_the_router(monkeypatch, tmp_path):
    client, agent = make(monkeypatch, tmp_path, FastTurn(route="fallthrough", fallthrough_skill="knowledge-management"))
    assert post(client).json()["response"] == "skill reply"
    kwargs = agent.handle_message.call_args.kwargs
    assert kwargs["skill"] == "knowledge-management" and kwargs["prior_actions"] is None


def test_a_lone_answer_goes_back_to_the_skill_that_asked(monkeypatch, tmp_path):
    client, agent = make(monkeypatch, tmp_path, FastTurn(route="fallthrough", fallthrough_skill="mazkir", lone_other=True))
    monkeypatch.setattr(route, "_previous_skill", lambda chat_id, date: "engineering")
    post(client, text="3")
    assert agent.handle_message.call_args.kwargs["skill"] == "engineering"


def test_a_lone_answer_with_no_skill_before_it_keeps_the_parse_skill(monkeypatch, tmp_path):
    client, agent = make(monkeypatch, tmp_path, FastTurn(route="fallthrough", fallthrough_skill="mazkir", lone_other=True))
    monkeypatch.setattr(route, "_previous_skill", lambda chat_id, date: None)
    post(client, text="3")
    assert agent.handle_message.call_args.kwargs["skill"] == "mazkir"


def _write_turns(logs_dir, *skills):
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    with (logs_dir / "agent-turns.jsonl").open("w", encoding="utf-8") as fh:
        for skill in skills:
            fh.write(json.dumps({"ts": ts, "chat_id": 1, "skill": skill}) + "\n")
    return ts[:10]


def test_previous_skill_is_the_last_turn_unless_the_fast_lane_answered_it(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "logs_dir", tmp_path / "logs")
    # a mixed turn logs the fast-lane record first, then the skill's
    day = _write_turns(tmp_path / "logs", "fast-lane", "engineering")
    assert route._previous_skill(1, day) == "engineering"
    # a pure fast turn in between: the lone answer is not right after a skill turn
    _write_turns(tmp_path / "logs", "engineering", "fast-lane")
    assert route._previous_skill(1, day) is None
    assert route._previous_skill(2, day) is None


def test_a_mixed_turn_tells_the_skill_what_ran(monkeypatch, tmp_path):
    fast = FastTurn(route="mixed", fallthrough_skill="knowledge-management", turn=a_turn(),
                    receipt={"turn_id": "t0000beef", "lines": [], "undo": None, "open_question": None, "text": "✓ Gym"},
                    ran=["✓ 18:00–19:00 Gym (block)"])
    client, agent = make(monkeypatch, tmp_path, fast)
    body = post(client).json()
    assert agent.handle_message.call_args.kwargs["prior_actions"] == ["✓ 18:00–19:00 Gym (block)"]
    assert body["response"] == "skill reply" and body["receipt"]["turn_id"] == "t0000beef"
    assert act.load_turn(tmp_path / "actions", "t0000beef")["response"] == "skill reply"


def test_a_repeated_mixed_turn_runs_no_skill(monkeypatch, tmp_path):
    turn = {**a_turn(), "route": "mixed", "response": "skill reply"}
    fast = FastTurn(route="mixed", fallthrough_skill="knowledge-management", turn=turn, repeat=True)
    client, agent = make(monkeypatch, tmp_path, fast)
    body = post(client).json()
    agent.handle_message.assert_not_called()
    assert body["response"] == "skill reply" and body["route"] == "mixed"


def test_a_repeat_while_the_first_is_still_running_says_so(monkeypatch, tmp_path):
    turn = {**a_turn(), "route": "fallthrough", "lines": [], "response": ""}
    client, agent = make(monkeypatch, tmp_path, FastTurn(route="fallthrough", turn=turn, repeat=True))
    body = post(client).json()
    agent.handle_message.assert_not_called()
    assert body["response"] == route.STILL_WORKING


def test_a_fallthrough_with_a_message_id_leaves_a_turn_record_before_the_agent_runs(monkeypatch, tmp_path):
    client, agent = make(monkeypatch, tmp_path, FastTurn(route="fallthrough", fallthrough_skill="mazkir"))
    seen = {}

    def handle(**kw):
        seen["during"] = act.find_repeat(tmp_path / "actions", 1, 9)
        return AgentResponse(response="skill reply", iterations=1)

    agent.handle_message.side_effect = handle
    post(client)
    assert seen["during"] is not None and seen["during"]["response"] == ""
    after = act.find_repeat(tmp_path / "actions", 1, 9)
    assert after["route"] == "fallthrough" and after["response"] == "skill reply" and after["lines"] == []


def test_a_fallthrough_without_a_message_id_saves_nothing(monkeypatch, tmp_path):
    client, agent = make(monkeypatch, tmp_path, FastTurn(route="fallthrough", fallthrough_skill="mazkir"))
    client.post("/message", json={"text": "hi", "chat_id": 1})
    assert not (tmp_path / "actions").exists() or not list((tmp_path / "actions").glob("t*.json"))


def test_a_parse_failure_goes_to_the_router(monkeypatch, tmp_path):
    client, agent = make(monkeypatch, tmp_path, FastTurn(route="router_fallback"))
    post(client)
    assert agent.handle_message.call_args.kwargs["skill"] is None


def test_a_fast_lane_that_cannot_start_hands_the_message_to_the_router(monkeypatch, tmp_path):
    client, agent = make(monkeypatch, tmp_path, FastTurn(route="fast"))

    def broken(**kw):
        raise RuntimeError("context broke")

    monkeypatch.setattr(context_module, "assemble_fast_context", broken)
    body = post(client).json()
    assert body["response"] == "skill reply" and body["route"] == "router_fallback"
    assert agent.handle_message.call_args.kwargs["skill"] is None


def test_a_failing_sync_never_fails_the_turn(monkeypatch, tmp_path):
    client, agent = make(monkeypatch, tmp_path, fast_turn())

    def boom(*a):
        raise RuntimeError("google down")

    monkeypatch.setattr(calendar_push, "sync_block", boom)
    body = post(client).json()
    assert body["route"] == "fast" and body["receipt"]["lines"][0]["sync"].startswith("⚠ calendar")
    assert act.load_turn(tmp_path / "actions", "t0000beef")["lines"][0]["undo"] == [{"kind": "created"}]


def test_a_sync_never_clobbers_an_undo_that_landed_meanwhile(monkeypatch, tmp_path):
    client, agent = make(monkeypatch, tmp_path, fast_turn())

    def sync_while_undone(*a):
        stored = act.load_turn(tmp_path / "actions", "t0000beef")
        stored["lines"][0].update(status="undone", undo_note="undone")
        act.save_turn(tmp_path / "actions", stored)
        return {"ok": True, "attempted": True, "event_id": "g1"}

    monkeypatch.setattr(calendar_push, "sync_block", sync_while_undone)
    post(client)
    stored = act.load_turn(tmp_path / "actions", "t0000beef")
    assert stored["lines"][0]["status"] == "undone" and stored["lines"][0]["calendar_sync"]["ok"] is True
    assert stored["response"]


def test_the_stream_carries_stages_the_receipt_and_its_updates(monkeypatch, tmp_path):
    client, _ = make(monkeypatch, tmp_path, fast_turn())
    raw = client.post("/message?stream=true", json={"text": "Gym 18:00-19:00", "chat_id": 1, "message_id": 9}).text
    payloads = [json.loads(chunk[len("data: "):]) for chunk in raw.split("\n\n") if chunk.startswith("data: ")]
    kinds = [next(iter(p)) for p in payloads]
    assert kinds[:2] == ["stage", "receipt"] and "receipt_update" in kinds and kinds[-1] == "done"
    update = next(p["receipt_update"] for p in payloads if "receipt_update" in p)
    assert update["line_id"] == 0 and update["receipt"]["lines"][0]["sync"] == "✓ calendar"


def test_the_stream_carries_the_agents_stages_and_text(monkeypatch, tmp_path):
    client, agent = make(monkeypatch, tmp_path, FastTurn(route="fallthrough", fallthrough_skill="mazkir"))

    def handle(**kw):
        kw["stage_callback"]("Checking your calendar…")
        kw["stream_callback"]("skill ")
        kw["stream_callback"]("reply")
        return AgentResponse(response="skill reply", iterations=1)

    agent.handle_message.side_effect = handle
    raw = client.post("/message?stream=true", json={"text": "hi", "chat_id": 1, "message_id": 9}).text
    payloads = [json.loads(chunk[len("data: "):]) for chunk in raw.split("\n\n") if chunk.startswith("data: ")]
    assert [next(iter(p)) for p in payloads] == ["stage", "stage", "text", "text", "done"]
    assert payloads[-1]["response"]["response"] == "skill reply" and payloads[-1]["response"]["route"] == "fallthrough"


def test_a_repeated_message_id_returns_the_first_receipt(monkeypatch, tmp_path, vault_service):
    from src.services.agent_service import AgentService
    from src.services.events_service import EventsService
    from src.services.fast_lane.contract import Clause, ParseResult, TimeWords
    monkeypatch.setattr(settings, "fast_lane_mode", "on")
    events = EventsService(tmp_path / "events")
    agent = AgentService(claude=MagicMock(), vault=vault_service, memory=MagicMock(),
                         media_path=tmp_path / "media", events=events)
    deps = FastDeps(claude=None, run_tool=agent.run_tool, events=events, vault=vault_service, memory=MagicMock(),
                    actions_dir=tmp_path / "actions", places_path=tmp_path / "p.json",
                    suggestions_path=tmp_path / "s.json", skills_dir=None)
    monkeypatch.setattr(route, "get_agent", lambda: agent)
    monkeypatch.setattr(route, "get_fast_turn_deps", lambda a: (deps, None))
    parsed = []

    def fake_parse(ctx, claude, **kw):
        parsed.append(ctx.text)
        return ParseResult((Clause("log_block", "record", True, "Gym 08:00-09:00", "Gym",
                                   time=TimeWords(start="08:00", end="09:00")),), None)

    monkeypatch.setattr(turn_module, "parse_message", fake_parse)
    app = FastAPI()
    app.include_router(route.router)
    client = TestClient(app)
    body = {"text": "Gym 08:00-09:00", "chat_id": 1, "message_id": 42}
    first, second = client.post("/message", json=body).json(), client.post("/message", json=body).json()
    assert first["receipt"]["turn_id"] == second["receipt"]["turn_id"] and parsed == ["Gym 08:00-09:00"]
    assert second["response"] == first["response"]
    written = [e for f in (tmp_path / "events").glob("*.json") for e in json.loads(f.read_text())
               if e["name"] == "Gym"]
    assert len(written) == 1


def test_shadow_mode_is_unchanged(monkeypatch, tmp_path):
    client, agent = make(monkeypatch, tmp_path, FastTurn(route="fast"))
    monkeypatch.setattr(settings, "fast_lane_mode", "shadow")
    monkeypatch.setattr(route, "_start_fast_lane_shadow", lambda body: None)
    assert post(client).json()["response"] == "skill reply"
    assert "skill" not in agent.handle_message.call_args.kwargs


def test_the_cap_stops_the_wait_not_the_sync(monkeypatch, tmp_path):
    """§8.1: past 15 s the reply goes out; the late line still reaches Google and its record."""
    import threading
    from src.services.fast_lane.receipt import render_receipt
    import datetime as dt
    turn = {**a_turn(), "lines": [dict(LINE), {**LINE, "id": 1, "event_id": "evt_2"}]}
    fast = FastTurn(route="fast", turn=turn, receipt=render_receipt(turn, dt.datetime(2026, 1, 10, 20, 0)))
    client, agent = make(monkeypatch, tmp_path, fast)
    monkeypatch.setattr(route, "SYNC_CAP_S", 0.2)
    release, finished = threading.Event(), threading.Event()

    def slow_second(calendar, events, date, event_id):
        if event_id == "evt_2":
            release.wait(5)
            finished.set()
        return {"ok": True, "attempted": True, "event_id": "g-" + event_id}

    monkeypatch.setattr(calendar_push, "sync_block", slow_second)
    with client:                                    # one loop for the request and what outlives it
        started = time.monotonic()
        body = post(client).json()
        assert time.monotonic() - started < 2
        assert [line["sync"] for line in body["receipt"]["lines"]] == ["✓ calendar", "⏳ calendar"]
        release.set()
        assert finished.wait(2)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            stored = act.load_turn(tmp_path / "actions", "t0000beef")
            if stored["lines"][1]["calendar_sync"].get("ok"):
                break
            time.sleep(0.02)
    assert stored["lines"][1]["calendar_sync"] == {"ok": True, "attempted": True, "event_id": "g-evt_2"}
    assert stored["response"] == fast.receipt["text"]           # the late patch kept the reply


def test_the_stream_closes_at_the_cap_and_a_late_update_goes_nowhere(monkeypatch, tmp_path):
    import threading
    client, _ = make(monkeypatch, tmp_path, fast_turn())
    monkeypatch.setattr(route, "SYNC_CAP_S", 0.2)
    release, finished = threading.Event(), threading.Event()

    def slow(*a):
        release.wait(5)
        finished.set()
        return {"ok": True, "attempted": True, "event_id": "g1"}

    monkeypatch.setattr(calendar_push, "sync_block", slow)
    with client:
        raw = client.post("/message?stream=true", json={"text": "Gym", "chat_id": 1, "message_id": 9}).text
        kinds = [next(iter(json.loads(c[len("data: "):]))) for c in raw.split("\n\n") if c.startswith("data: ")]
        assert kinds == ["stage", "receipt", "done"]
        release.set()
        assert finished.wait(2)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not act.load_turn(
                tmp_path / "actions", "t0000beef")["lines"][0]["calendar_sync"].get("ok"):
            time.sleep(0.02)
    assert act.load_turn(tmp_path / "actions", "t0000beef")["lines"][0]["calendar_sync"]["ok"] is True


def test_an_agent_that_raises_leaves_a_failure_on_the_record(monkeypatch, tmp_path):
    client, agent = make(monkeypatch, tmp_path, FastTurn(route="fallthrough", fallthrough_skill="mazkir"))
    agent.handle_message.side_effect = RuntimeError("boom")
    raw = client.post("/message?stream=true", json={"text": "hi", "chat_id": 1, "message_id": 9}).text
    assert '"route": "error"' in raw
    assert act.find_repeat(tmp_path / "actions", 1, 9)["response"] == route.AGENT_FAILED


def test_a_mixed_turn_whose_skill_raises_does_not_invite_a_resend(monkeypatch, tmp_path):
    fast = FastTurn(route="mixed", fallthrough_skill="knowledge-management", turn={**a_turn(), "route": "mixed"},
                    receipt={"turn_id": "t0000beef", "lines": [], "undo": None, "open_question": None, "text": "✓ Gym"},
                    ran=["✓ 18:00–19:00 Gym (block)"])
    client, agent = make(monkeypatch, tmp_path, fast)
    agent.handle_message.side_effect = RuntimeError("boom")
    client.post("/message?stream=true", json={"text": "Gym and a note", "chat_id": 1, "message_id": 9})
    assert act.load_turn(tmp_path / "actions", "t0000beef")["response"] == route.MIXED_FAILED


def test_a_held_task_that_fails_is_logged_at_error(caplog):
    import asyncio
    import logging

    async def boom():
        raise RuntimeError("late sync broke")

    async def main():
        task = route._hold(asyncio.create_task(boom()))
        await asyncio.wait({task})
        await asyncio.sleep(0)            # done-callbacks run on the next loop pass
        return task

    with caplog.at_level(logging.ERROR, logger=route.logger.name):
        task = asyncio.run(main())
    assert task not in route._fast_tasks
    assert any("background task failed" in r.getMessage() and r.levelno == logging.ERROR for r in caplog.records)
