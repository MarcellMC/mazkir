"""Tests for /media route — direct lookup and wikilink fallback search."""
import pytest
from fastapi.testclient import TestClient


def test_media_route_serves_file_directly(tmp_path, monkeypatch):
    """Direct path lookup: /media/{date}/{filename} serves the file."""
    media_dir = tmp_path / "media"
    actual_dir = media_dir / "2026-06-03"
    actual_dir.mkdir(parents=True)
    (actual_dir / "photo.jpg").write_bytes(b"fake-image")

    monkeypatch.setenv("MEDIA_PATH", str(media_dir))

    # Re-import after env change so settings picks up the new value
    import importlib
    import sys
    for mod in list(sys.modules):
        if "src.config" in mod:
            del sys.modules[mod]
    import src.config
    importlib.reload(src.config)
    import src.api.routes.media as media_mod
    importlib.reload(media_mod)

    from src.main import app
    client = TestClient(app)

    resp = client.get("/media/2026-06-03/photo.jpg")
    assert resp.status_code == 200
    assert resp.content == b"fake-image"


def test_media_route_finds_file_via_filename_search(tmp_path, monkeypatch):
    """Fallback: a request with the wrong date still finds the file by name."""
    media_dir = tmp_path / "media"
    actual_dir = media_dir / "2026-06-03"
    actual_dir.mkdir(parents=True)
    (actual_dir / "photo.jpg").write_bytes(b"fake-image")

    monkeypatch.setenv("MEDIA_PATH", str(media_dir))

    import importlib
    import sys
    for mod in list(sys.modules):
        if "src.config" in mod:
            del sys.modules[mod]
    import src.config
    importlib.reload(src.config)
    import src.api.routes.media as media_mod
    importlib.reload(media_mod)

    from src.main import app
    client = TestClient(app)

    # Request with WRONG date should still find via search
    resp = client.get("/media/2099-01-01/photo.jpg")
    assert resp.status_code == 200
    assert resp.content == b"fake-image"


def test_media_route_404_when_file_missing(tmp_path, monkeypatch):
    """Return 404 if file doesn't exist anywhere under media_path."""
    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True)

    monkeypatch.setenv("MEDIA_PATH", str(media_dir))

    import importlib
    import sys
    for mod in list(sys.modules):
        if "src.config" in mod:
            del sys.modules[mod]
    import src.config
    importlib.reload(src.config)
    import src.api.routes.media as media_mod
    importlib.reload(media_mod)

    from src.main import app
    client = TestClient(app)

    resp = client.get("/media/2026-06-03/missing.jpg")
    assert resp.status_code == 404
