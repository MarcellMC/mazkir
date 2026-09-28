import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.services.fast_lane.context as context_module
import src.services.fast_lane.shadow as shadow_module
from src.api.routes import message as route
from src.config import settings
from src.services.agent_service import AgentResponse


def make_client(monkeypatch, mode, assemble=None, run_shadow=None):
    monkeypatch.setattr(settings, "fast_lane_mode", mode)
    ran, seen = threading.Event(), {}

    def fake_run_shadow(ctx, claude, s, complete=None):
        seen["text"] = ctx.text
        seen["complete"] = complete
        ran.set()
        return {}

    monkeypatch.setattr(shadow_module, "run_shadow", run_shadow or fake_run_shadow)
    monkeypatch.setattr(context_module, "assemble_fast_context",
                        assemble or (lambda **kw: SimpleNamespace(text=kw["text"])))
    monkeypatch.setattr(route, "get_fast_lane_deps", lambda: (MagicMock(), MagicMock(), MagicMock(), MagicMock()))
    # What the route got back from starting the shadow: a task, or None when it started nothing.
    started = []
    real_start = route._start_fast_lane_shadow

    def recording_start(body):
        started.append(real_start(body))
        return started[-1]

    monkeypatch.setattr(route, "_start_fast_lane_shadow", recording_start)
    agent = MagicMock()
    agent.handle_message.return_value = AgentResponse(response="ok", iterations=1)
    monkeypatch.setattr(route, "get_agent", lambda: agent)
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app), ran, seen, started


def test_shadow_mode_runs_the_fast_lane_beside_the_agent(monkeypatch):
    client, ran, seen, started = make_client(monkeypatch, "shadow")
    with client:
        r = client.post("/message", json={"text": "Dog walk 23:15-23:35", "chat_id": 1})
        assert r.status_code == 200 and r.json()["response"] == "ok"
        assert ran.wait(2)
    assert len(started) == 1 and started[0] is not None
    assert seen["text"] == "Dog walk 23:15-23:35"
    # history and habits are read in the shadow's thread, not on the event loop
    assert seen["complete"].func is context_module.complete_fast_context


def test_off_mode_runs_nothing(monkeypatch):
    client, ran, _, started = make_client(monkeypatch, "off")
    with client:
        assert client.post("/message", json={"text": "hi", "chat_id": 1}).status_code == 200
    assert started == [None]   # no task was ever created
    assert not ran.is_set()


def test_a_broken_snapshot_never_breaks_the_reply(monkeypatch):
    def boom(**kw):
        raise RuntimeError("disk")

    client, ran, _, started = make_client(monkeypatch, "shadow", assemble=boom)
    with client:
        r = client.post("/message", json={"text": "hi", "chat_id": 1})
        assert r.status_code == 200 and r.json()["response"] == "ok"
    assert started == [None]   # the snapshot failed, so no task was created
    assert not ran.is_set()


def test_the_reply_never_waits_for_the_shadow(monkeypatch):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def blocking_run_shadow(ctx, claude, s, complete=None):
        entered.set()
        release.wait(5)   # bounded, so a regression fails the test instead of hanging it
        finished.set()
        return {}

    client, _, _, started = make_client(monkeypatch, "shadow", run_shadow=blocking_run_shadow)
    try:
        with client:
            r = client.post("/message", json={"text": "Dog walk 23:15-23:35", "chat_id": 1})
            assert r.status_code == 200 and r.json()["response"] == "ok"
            assert entered.wait(2)            # the shadow is running ...
            assert not finished.is_set()      # ... and still blocked when the reply arrived
            assert not release.is_set()
            assert started[0] is not None
            release.set()
            assert finished.wait(2)
    finally:
        release.set()   # never leave the shadow's thread blocked
