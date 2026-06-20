"""Tests for the /notes router."""
from pathlib import Path
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Point the vault at a temp dir BEFORE importing the app.
    vault = tmp_path / "vault"
    (vault / "10-daily").mkdir(parents=True)
    (vault / "AGENTS.md").write_text("# Agents\n")
    (vault / "10-daily" / "2026-05-21.md").write_text(
        "---\ntype: daily\nupdated: '2026-05-21'\n---\n\n## Tasks\n- [ ] Pack cooler\n"
    )
    monkeypatch.setenv("VAULT_PATH", str(vault))
    monkeypatch.setenv("API_KEY", "")
    import importlib
    import src.config, src.main
    importlib.reload(src.config)
    importlib.reload(src.main)
    with TestClient(src.main.app) as c:
        yield c


def test_list_notes(client):
    r = client.get("/notes")
    assert r.status_code == 200
    notes = r.json()["notes"]
    assert notes[0]["id"] == "2026-05-21"


def test_get_note(client):
    r = client.get("/notes/2026-05-21")
    assert r.status_code == 200
    assert "## Tasks" in r.json()["markdown"]


def test_get_note_404(client):
    assert client.get("/notes/2099-01-01").status_code == 404


def test_patch_checkbox(client):
    r = client.patch("/notes/2026-05-21/checkbox", json={"line": 2, "checked": True})
    assert r.status_code == 200
    assert "- [x] Pack cooler" in r.json()["markdown"]


def test_patch_checkbox_conflict(client):
    r = client.patch("/notes/2026-05-21/checkbox", json={"line": 1, "checked": True})
    assert r.status_code == 409
