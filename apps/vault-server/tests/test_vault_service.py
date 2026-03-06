"""Tests for VaultService core CRUD operations."""
import pytest
from pathlib import Path
from src.services.vault_service import VaultService


# --- Initialization (existing tests) ---


def test_initializes_with_valid_vault(vault_service, vault_path):
    assert vault_service.vault_path == vault_path


def test_rejects_missing_path():
    with pytest.raises(FileNotFoundError):
        VaultService(Path("/nonexistent/path"))


def test_rejects_vault_without_agents_md(tmp_path):
    with pytest.raises(FileNotFoundError, match="AGENTS.md"):
        VaultService(tmp_path)


# --- read_file ---


def test_read_file_parses_frontmatter_and_content(vault_service):
    data = vault_service.read_file("40-tasks/active/buy-groceries.md")

    assert data["metadata"]["name"] == "Buy groceries"
    assert data["metadata"]["priority"] == 3
    assert data["metadata"]["type"] == "task"
    assert "# Buy groceries" in data["content"]
    assert data["path"] == "40-tasks/active/buy-groceries.md"


def test_read_file_raises_on_missing(vault_service):
    with pytest.raises(FileNotFoundError):
        vault_service.read_file("nonexistent.md")


# --- write_file ---


def test_write_file_creates_file_with_frontmatter(vault_service, vault_path):
    vault_service.write_file(
        "test-dir/new-file.md",
        {"type": "test", "name": "Test"},
        "# Test content",
    )

    written = vault_path / "test-dir" / "new-file.md"
    assert written.exists()

    data = vault_service.read_file("test-dir/new-file.md")
    assert data["metadata"]["type"] == "test"
    assert data["metadata"]["name"] == "Test"
    assert "updated" in data["metadata"]  # auto-set by write_file
    assert "# Test content" in data["content"]


def test_write_file_creates_parent_dirs(vault_service, vault_path):
    vault_service.write_file(
        "a/b/c/deep.md",
        {"name": "deep"},
        "content",
    )
    assert (vault_path / "a" / "b" / "c" / "deep.md").exists()


# --- update_file ---


def test_update_file_merges_metadata(vault_service):
    vault_service.update_file("20-habits/workout.md", {"streak": 99})

    data = vault_service.read_file("20-habits/workout.md")
    assert data["metadata"]["streak"] == 99
    assert data["metadata"]["name"] == "Workout"  # preserved


def test_update_file_preserves_content(vault_service):
    vault_service.update_file("20-habits/workout.md", {"streak": 99})

    data = vault_service.read_file("20-habits/workout.md")
    assert "# Workout" in data["content"]


# --- list_files ---


def test_list_files_returns_md_files(vault_service):
    files = vault_service.list_files("40-tasks/active")
    filenames = {f.name for f in files}

    assert "buy-groceries.md" in filenames
    assert "finish-report.md" in filenames
    assert "learn-rust.md" in filenames


def test_list_files_returns_empty_for_missing_dir(vault_service):
    files = vault_service.list_files("nonexistent-dir")
    assert files == []


# --- _sanitize_filename ---


def test_sanitize_filename_basic(vault_service):
    assert vault_service._sanitize_filename("Buy Groceries") == "buy-groceries"


def test_sanitize_filename_special_chars(vault_service):
    assert vault_service._sanitize_filename("Hello! World? #1") == "hello-world-1"


def test_sanitize_filename_length_limit(vault_service):
    long_name = "a" * 100
    result = vault_service._sanitize_filename(long_name, max_length=10)
    assert len(result) == 10


# --- _process_template ---


def test_process_template_substitutes_placeholders(vault_service):
    template = {
        "metadata": {"name": "{{title}}", "created": "{{date}}"},
        "content": "# {{title}}\nCreated on {{date}}",
    }
    result = vault_service._process_template(template, {
        "title": "My Task",
        "date": "2026-02-28",
    })

    assert result["metadata"]["name"] == "My Task"
    assert result["metadata"]["created"] == "2026-02-28"
    assert "# My Task" in result["content"]
    assert "2026-02-28" in result["content"]


# --- append_to_daily_section ---


class TestAppendToDailySection:
    def test_appends_to_notes_section(self, vault_service, vault_path):
        # Create a daily note first
        vault_service.create_daily_note()
        result = vault_service.append_to_daily_section(
            section="Notes",
            content="![Dog walk](../../data/media/2026-03-04/photo.jpg)\n*14:30 — Dog walk*",
        )
        assert "path" in result

        # Read back and verify content was added
        daily = vault_service.read_daily_note()
        assert "Dog walk" in daily["content"]
        assert "photo.jpg" in daily["content"]

    def test_creates_daily_if_missing(self, vault_service, vault_path):
        result = vault_service.append_to_daily_section(
            section="Notes",
            content="Test content",
        )
        assert "path" in result
        daily = vault_service.read_daily_note()
        assert "Test content" in daily["content"]

    def test_appends_to_nonexistent_section(self, vault_service, vault_path):
        vault_service.create_daily_note()
        result = vault_service.append_to_daily_section(
            section="Photos",
            content="A photo here",
        )
        daily = vault_service.read_daily_note()
        assert "## Photos" in daily["content"]
        assert "A photo here" in daily["content"]


# --- read_daily_section / replace_daily_section ---


class TestDailySections:
    def test_read_daily_section_returns_content(self, vault_service, vault_path):
        vault_service.create_daily_note()
        vault_service.append_to_daily_section("Notes", "Hello world")
        result = vault_service.read_daily_section("Notes")
        assert "Hello world" in result

    def test_read_daily_section_empty(self, vault_service, vault_path):
        vault_service.create_daily_note()
        result = vault_service.read_daily_section("Notes")
        assert result.strip() == ""

    def test_read_daily_section_missing(self, vault_service, vault_path):
        vault_service.create_daily_note()
        result = vault_service.read_daily_section("Nonexistent")
        assert result == ""

    def test_read_daily_section_no_daily_note(self, vault_service):
        result = vault_service.read_daily_section("Notes")
        assert result == ""

    def test_replace_daily_section(self, vault_service, vault_path):
        vault_service.create_daily_note()
        vault_service.append_to_daily_section("Notes", "Old content")
        vault_service.replace_daily_section("Notes", "New content")
        result = vault_service.read_daily_section("Notes")
        assert "New content" in result
        assert "Old content" not in result

    def test_replace_daily_section_preserves_other_sections(self, vault_service, vault_path):
        vault_service.create_daily_note()
        vault_service.replace_daily_section("Notes", "New notes content")
        daily = vault_service.read_daily_note()
        assert "## Daily Habits" in daily["content"]
        assert "## Tasks" in daily["content"]
        assert "New notes content" in daily["content"]


# --- delete_file, archive_task, find_habit/goal_by_name ---


class TestDeleteAndArchive:
    def test_delete_file(self, vault_service, vault_path):
        assert (vault_path / "40-tasks/active/buy-groceries.md").exists()
        vault_service.delete_file("40-tasks/active/buy-groceries.md")
        assert not (vault_path / "40-tasks/active/buy-groceries.md").exists()

    def test_delete_file_not_found(self, vault_service):
        with pytest.raises(FileNotFoundError):
            vault_service.delete_file("40-tasks/active/nonexistent.md")

    def test_archive_task_no_tokens(self, vault_service, vault_path):
        old_ledger = vault_service.read_token_ledger()
        old_total = old_ledger["metadata"]["total_tokens"]

        result = vault_service.archive_task("40-tasks/active/buy-groceries.md")

        assert result["archive_path"] == "40-tasks/archive/buy-groceries.md"
        assert not (vault_path / "40-tasks/active/buy-groceries.md").exists()
        assert (vault_path / "40-tasks/archive/buy-groceries.md").exists()

        new_ledger = vault_service.read_token_ledger()
        assert new_ledger["metadata"]["total_tokens"] == old_total

        archived = vault_service.read_file("40-tasks/archive/buy-groceries.md")
        assert archived["metadata"]["status"] == "archived"

    def test_find_habit_by_name(self, vault_service):
        habit = vault_service.find_habit_by_name("workout")
        assert habit is not None
        assert habit["metadata"]["name"] == "Workout"

    def test_find_habit_by_name_not_found(self, vault_service):
        assert vault_service.find_habit_by_name("nonexistent") is None

    def test_find_goal_by_name(self, vault_service):
        goal = vault_service.find_goal_by_name("get fit")
        assert goal is not None
        assert goal["metadata"]["name"] == "Get fit"

    def test_find_goal_by_name_not_found(self, vault_service):
        assert vault_service.find_goal_by_name("nonexistent") is None
