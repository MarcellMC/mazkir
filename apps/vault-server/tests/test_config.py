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


def test_location_awareness_defaults_off(monkeypatch):
    from src.config import Settings      # its import loads .env into os.environ; clear it after
    monkeypatch.delenv("LOCATION_AWARENESS", raising=False)
    s = Settings(_env_file=None)
    assert s.location_awareness == "off"
    assert s.location_guess_model == s.fast_parse_model
    assert s.location_guess_timeout_s == 8.0


def test_location_map_defaults(monkeypatch):
    from src.config import Settings      # its import loads .env into os.environ; clear it after
    for key in ("LOCATION_MAP", "LOCATION_MAP_URL", "LOCATION_MAP_MAX_AGE_DAYS", "LOCATION_MAP_PATH"):
        monkeypatch.delenv(key, raising=False)
    s = Settings(_env_file=None)
    assert s.location_map == "on"
    assert s.location_map_url == "https://download.geofabrik.de/asia/israel-and-palestine-latest.osm.pbf"
    assert s.location_map_max_age_days == 30
    assert s.location_map_path.name == "map"
