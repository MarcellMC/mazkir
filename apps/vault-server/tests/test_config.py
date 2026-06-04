"""Tests for vault-server Settings."""
import importlib
import sys


def test_media_path_defaults_to_vault(monkeypatch):
    monkeypatch.delenv("MEDIA_PATH", raising=False)
    # Force reimport so the default is recalculated with no env var present.
    for mod in list(sys.modules):
        if "src.config" in mod:
            del sys.modules[mod]
    from src.config import Settings
    s = Settings()
    assert "memory/00-system/media" in str(s.media_path)
    assert "data/media" not in str(s.media_path)
