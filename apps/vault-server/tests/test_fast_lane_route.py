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


def make_client(monkeypatch, mode, assemble=None):
    monkeypatch.setattr(settings, "fast_lane_mode", mode)
    ran, seen = threading.Event(), {}

    def fake_run_shadow(ctx, claude, s, complete=None):
        seen["text"] = ctx.text
        seen["complete"] = complete
        ran.set()
        return {}

    monkeypatch.setattr(shadow_module, "run_shadow", fake_run_shadow)
    monkeypatch.setattr(context_module, "assemble_fast_context",
                        assemble or (lambda **kw: SimpleNamespace(text=kw["text"])))
    monkeypatch.setattr(route, "get_fast_lane_deps", lambda: (MagicMock(), MagicMock(), MagicMock(), MagicMock()))
    agent = MagicMock()
    agent.handle_message.return_value = AgentResponse(response="ok", iterations=1)
    monkeypatch.setattr(route, "get_agent", lambda: agent)
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app), ran, seen


def test_shadow_mode_runs_the_fast_lane_beside_the_agent(monkeypatch):
    client, ran, seen = make_client(monkeypatch, "shadow")
    with client:
        r = client.post("/message", json={"text": "Dog walk 23:15-23:35", "chat_id": 1})
        assert r.status_code == 200 and r.json()["response"] == "ok"
        assert ran.wait(2)
    assert seen["text"] == "Dog walk 23:15-23:35"
    # history and habits are read in the shadow's thread, not on the event loop
    assert seen["complete"].func is context_module.complete_fast_context


def test_off_mode_runs_nothing(monkeypatch):
    client, ran, _ = make_client(monkeypatch, "off")
    with client:
        assert client.post("/message", json={"text": "hi", "chat_id": 1}).status_code == 200
        assert not ran.wait(0.3)


def test_a_broken_snapshot_never_breaks_the_reply(monkeypatch):
    def boom(**kw):
        raise RuntimeError("disk")

    client, ran, _ = make_client(monkeypatch, "shadow", assemble=boom)
    with client:
        r = client.post("/message", json={"text": "hi", "chat_id": 1})
        assert r.status_code == 200 and r.json()["response"] == "ok"
        assert not ran.wait(0.3)
