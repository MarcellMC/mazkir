"""Smoke tests for VaultService."""
import pytest
from pathlib import Path
from src.services.vault_service import VaultService


def test_vault_service_initializes(tmp_path):
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text("# Agents")
    service = VaultService(tmp_path)
    assert service.vault_path == tmp_path


def test_vault_service_rejects_missing_path():
    with pytest.raises(FileNotFoundError):
        VaultService(Path("/nonexistent/path"))
