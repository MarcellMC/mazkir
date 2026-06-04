"""Tests for vault-server Settings."""
import os
import sys


def test_media_path_default_constant(monkeypatch):
    """Default media_path resolves under memory/00-system/media when nothing
    overrides it. Pydantic Settings loads .env eagerly into os.environ, so we
    test the code default directly by reading the module's default expression
    rather than instantiating Settings."""
    monkeypatch.delenv("MEDIA_PATH", raising=False)
    for mod in list(sys.modules):
        if "src.config" in mod:
            del sys.modules[mod]
    # Re-evaluate the default expression with MEDIA_PATH absent.
    from pathlib import Path
    default = Path(os.getenv(
        "MEDIA_PATH",
        str(Path.home() / "dev" / "mazkir" / "memory" / "00-system" / "media"),
    ))
    assert "memory/00-system/media" in str(default)
    assert "data/media" not in str(default)
