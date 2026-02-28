"""Tests for VaultService token operations."""
import pytest


def test_read_token_ledger(vault_service):
    ledger = vault_service.read_token_ledger()

    assert ledger["metadata"]["total_tokens"] == 50
    assert ledger["metadata"]["all_time_tokens"] == 50
    assert ledger["metadata"]["type"] == "system"


def test_update_tokens_increments_totals(vault_service):
    result = vault_service.update_tokens(10, "Completed: test task")

    assert result["tokens_earned"] == 10
    assert result["old_total"] == 50
    assert result["new_total"] == 60
    assert result["activity"] == "Completed: test task"

    # Verify ledger was updated on disk
    ledger = vault_service.read_token_ledger()
    assert ledger["metadata"]["total_tokens"] == 60
    assert ledger["metadata"]["all_time_tokens"] == 60


def test_update_tokens_accumulates_daily(vault_service):
    vault_service.update_tokens(10, "First")
    vault_service.update_tokens(5, "Second")

    ledger = vault_service.read_token_ledger()
    assert ledger["metadata"]["total_tokens"] == 65  # 50 + 10 + 5
    assert ledger["metadata"]["tokens_today"] == 15  # 10 + 5 (reset from old date)


def test_update_tokens_resets_daily_on_new_day(vault_service):
    # The fixture ledger has updated: '2026-01-01', so today is a new day.
    # First call should reset tokens_today from the fixture's 10 to just what we add.
    result = vault_service.update_tokens(7, "New day task")

    ledger = vault_service.read_token_ledger()
    assert ledger["metadata"]["tokens_today"] == 7  # reset + 7, not 10 + 7
