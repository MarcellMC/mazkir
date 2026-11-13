"""Location spike (L0), spec §4.3: POST /locations/points."""

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes import locations as locations_route
from src.auth import verify_api_key
from src.services import location_store
from src.services.location_store import load_points

BODY = {"source": "telegram", "kind": "live", "message_id": 7, "ts": "2026-11-06T06:14:03Z",
        "lat": 32.0853, "lng": 34.7818, "accuracy_m": 12.0, "heading": 270, "live_period": 28800}


def make_client(monkeypatch, tmp_path, mode):
    # Patch the route module's own `settings`: test_config.py drops src.config
    # from sys.modules, so a fresh import elsewhere would bind another object.
    monkeypatch.setattr(locations_route.settings, "location_ingest", mode)
    monkeypatch.setattr(locations_route.settings, "location_data_path", tmp_path)
    monkeypatch.setattr(locations_route.settings, "vault_timezone", "Asia/Jerusalem")
    location_store._reset_for_tests()
    app = FastAPI()
    app.include_router(locations_route.router)
    app.dependency_overrides[verify_api_key] = lambda: None
    return TestClient(app)


@pytest.fixture
def client(monkeypatch, tmp_path):
    return make_client(monkeypatch, tmp_path, "log")


@pytest.fixture
def client_off(monkeypatch, tmp_path):
    return make_client(monkeypatch, tmp_path, "off")


def test_a_valid_point_is_stored_with_received_at(client, tmp_path):
    r = client.post("/locations/points", json=BODY)
    assert r.status_code == 200 and r.json() == {"ok": True}
    [line], skipped = load_points(tmp_path, date(2026, 11, 6))
    assert skipped == 0
    assert line["kind"] == "live" and line["lat"] == 32.0853 and line["live_period"] == 28800
    assert "received_at" in line


def test_unknown_fields_are_rejected(client, tmp_path):
    assert client.post("/locations/points", json={**BODY, "speed": 3}).status_code == 422
    assert not (tmp_path / "raw").exists()


def test_a_ts_without_offset_is_rejected(client, tmp_path):
    assert client.post("/locations/points", json={**BODY, "ts": "2026-11-06T08:14:03"}).status_code == 422
    assert not (tmp_path / "raw").exists()


def test_latitude_out_of_range_is_rejected(client):
    assert client.post("/locations/points", json={**BODY, "lat": 91}).status_code == 422


def test_an_unknown_kind_is_rejected(client):
    assert client.post("/locations/points", json={**BODY, "kind": "teleport"}).status_code == 422


def test_off_answers_404_and_writes_nothing(client_off, tmp_path):
    assert client_off.post("/locations/points", json=BODY).status_code == 404
    assert not (tmp_path / "raw").exists()


def test_a_check_in_keeps_its_venue_title(client, tmp_path):
    body = {**BODY, "kind": "check_in", "venue_title": "Superpharm"}
    del body["live_period"], body["heading"]
    assert client.post("/locations/points", json=body).status_code == 200
    [line], _ = load_points(tmp_path, date(2026, 11, 6))
    assert line["kind"] == "check_in" and line["venue_title"] == "Superpharm"


def test_a_field_telegram_did_not_send_is_not_stored(client, tmp_path):
    # The report reads which fields the last update of a share carried
    # (spec §2.2 item 3); a stored null would look like a field that was sent.
    body = {k: v for k, v in BODY.items() if k not in ("live_period", "heading")}
    assert client.post("/locations/points", json=body).status_code == 200
    [line], _ = load_points(tmp_path, date(2026, 11, 6))
    assert "live_period" not in line and "heading" not in line and "venue_title" not in line


# --- location awareness (trips), plan Task 12 --------------------------------

from unittest.mock import MagicMock

from src.services.location import runtime as runtime_mod


@pytest.fixture
def aware(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, "log")
    monkeypatch.setattr(locations_route.settings, "location_awareness", "on")
    rt = MagicMock()
    rt.feed.return_value = [{"id": "n1", "kind": "notice", "receipt": {"text": "hi"}}]
    monkeypatch.setattr(runtime_mod, "_runtime", rt)
    return client, rt


def test_awareness_off_keeps_the_l0_response(client, monkeypatch):
    monkeypatch.setattr(locations_route.settings, "location_awareness", "off")
    rt = MagicMock()
    monkeypatch.setattr(runtime_mod, "_runtime", rt)
    assert client.post("/locations/points", json=BODY).json() == {"ok": True}
    rt.feed.assert_not_called()


def test_ingest_returns_notify_when_on(aware):
    client, rt = aware
    r = client.post("/locations/points", json={**BODY, "chat_id": 156175834})
    assert r.json() == {"ok": True, "notify": [{"id": "n1", "kind": "notice", "receipt": {"text": "hi"}}]}
    assert rt.feed.call_args.args[0]["chat_id"] == 156175834


def test_tracker_crash_still_returns_200(aware, tmp_path):
    client, rt = aware
    rt.feed.side_effect = RuntimeError("boom")
    r = client.post("/locations/points", json=BODY)
    assert r.status_code == 200 and r.json() == {"ok": True, "notify": []}
    assert load_points(tmp_path, date(2026, 11, 6))[0]          # the raw point is stored regardless


def test_ack(aware):
    client, rt = aware
    rt.ack.return_value = True
    assert client.post("/locations/outbox/0a1b2c3d/ack").json() == {"ok": True}
    assert client.post("/locations/outbox/../x/ack").status_code in (404, 422)


def test_trip_routes_404_when_off(client, monkeypatch):
    monkeypatch.setattr(locations_route.settings, "location_awareness", "off")
    assert client.post("/locations/outbox/0a1b2c3d/ack").status_code == 404
    assert client.post("/locations/trips/1a2b3c4d/tap", json={"line": "s1", "action": "p"}).status_code == 404


def test_tap_rejects_bad_input(aware):
    client, _ = aware
    assert client.post("/locations/trips/1A2B/tap", json={"line": "s1", "action": "p"}).status_code == 422
    assert client.post("/locations/trips/1a2b3c4d/tap", json={"line": "s1", "action": "zz"}).status_code == 422
    assert client.post("/locations/trips/1a2b3c4d/tap", json={"line": "s1", "action": "p", "x": 1}).status_code == 422


def test_tap_on_an_unknown_trip_is_404(aware):
    client, rt = aware
    rt.tap.side_effect = KeyError("1a2b3c4d")
    assert client.post("/locations/trips/1a2b3c4d/tap", json={"line": "s1", "action": "p"}).status_code == 404


def test_ok_tap_approves_through_set_event_state(aware, monkeypatch):
    client, rt = aware
    rt.tap.return_value = {"receipt": None, "toast": "✓ Confirmed", "open_question": None,
                           "approvals": [("2026-11-13", "evt_1", "approved")], "rerender": True}
    rt.render_arrival.return_value = {"turn_id": "1a2b3c4d", "lines": [], "text": "", "undo": None,
                                      "open_question": None}
    calls = []

    async def fake_state(day, event_id, body):
        calls.append((day.isoformat(), event_id, body.state))
        return {"ok": True, "habit": {"name": "Dog Walk", "tokens_earned": 5, "new_streak": 3}}

    import src.api.routes.events as events_route
    monkeypatch.setattr(events_route, "set_event_state", fake_state)
    r = client.post("/locations/trips/1a2b3c4d/tap", json={"line": "1", "action": "ok"})
    assert r.status_code == 200 and calls == [("2026-11-13", "evt_1", "approved")]
    assert r.json()["toast"] == "✓ Dog Walk · +5 tokens · streak 3"
    assert r.json()["receipt"]["turn_id"] == "1a2b3c4d"
