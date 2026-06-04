"""Tests for the migrate_media_to_vault script."""

import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "migrate_media_to_vault.py"


def _load_script(monkeypatch, repo_root: Path):
    """Import the script with REPO/OLD/NEW/DAILY pointing at tmp_path."""
    spec = importlib.util.spec_from_file_location("migrate_media_to_vault", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "REPO", repo_root)
    monkeypatch.setattr(module, "OLD", repo_root / "data" / "media")
    monkeypatch.setattr(module, "NEW", repo_root / "memory" / "00-system" / "media")
    monkeypatch.setattr(module, "DAILY", repo_root / "memory" / "10-daily")
    return module


def test_dry_run_does_not_modify(tmp_path, monkeypatch, capsys):
    (tmp_path / "data" / "media" / "2026-06-01").mkdir(parents=True)
    (tmp_path / "data" / "media" / "2026-06-01" / "photo.jpg").write_bytes(b"x")
    (tmp_path / "memory" / "10-daily").mkdir(parents=True)
    daily = tmp_path / "memory" / "10-daily" / "2026-06-01.md"
    daily.write_text("![cap](../../data/media/2026-06-01/photo.jpg)\n", encoding="utf-8")

    module = _load_script(monkeypatch, tmp_path)
    module.main(dry_run=True)

    # Photo still in old location
    assert (tmp_path / "data" / "media" / "2026-06-01" / "photo.jpg").exists()
    # Daily note unchanged
    assert "![cap](../../data/media/2026-06-01/photo.jpg)" in daily.read_text()


def test_apply_moves_files_and_rewrites_embeds(tmp_path, monkeypatch):
    (tmp_path / "data" / "media" / "2026-06-01").mkdir(parents=True)
    (tmp_path / "data" / "media" / "2026-06-01" / "photo.jpg").write_bytes(b"x")
    (tmp_path / "memory" / "10-daily").mkdir(parents=True)
    daily = tmp_path / "memory" / "10-daily" / "2026-06-01.md"
    daily.write_text("Before\n![cap](../../data/media/2026-06-01/photo.jpg)\nAfter\n", encoding="utf-8")

    module = _load_script(monkeypatch, tmp_path)
    module.main(dry_run=False)

    # Photo moved to new location
    assert (tmp_path / "memory" / "00-system" / "media" / "2026-06-01" / "photo.jpg").exists()
    assert not (tmp_path / "data" / "media" / "2026-06-01").exists()
    # Daily note rewritten to wikilink
    text = daily.read_text()
    assert "![[photo.jpg]]" in text
    assert "../../data/media" not in text


def test_no_op_when_no_source_dir(tmp_path, monkeypatch, capsys):
    module = _load_script(monkeypatch, tmp_path)
    rc = module.main(dry_run=False)
    assert rc == 0
