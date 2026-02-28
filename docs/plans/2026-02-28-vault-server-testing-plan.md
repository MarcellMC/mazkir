# VaultService Testing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add fixture-based unit tests for VaultService covering all CRUD operations, task/habit/goal lifecycle, and token management.

**Architecture:** Tests use `tmp_path` to create temporary vault directories with real templates and sample files. No mocking — real file I/O and frontmatter parsing. Each test file covers one domain area.

**Tech Stack:** pytest, python-frontmatter (already installed), tmp_path fixture

---

### Task 1: Test Fixtures (`conftest.py`)

**Files:**
- Create: `apps/vault-server/tests/conftest.py`

**Step 1: Write the conftest with shared fixtures**

```python
import pytest
from pathlib import Path
from src.services.vault_service import VaultService


# --- Template contents (copied from memory/00-system/templates/) ---

TASK_TEMPLATE = """\
---
type: task
name: "{{title}}"
status: active
priority: 3
due_date: null
category: personal
tags: [task]
tokens_on_completion: 5
google_event_id: null
created: "{{date}}"
updated: "{{date}}"
---

# {{title}}

## Description


## Checklist
- [ ]

## Notes
"""

HABIT_TEMPLATE = """\
---
type: habit
name: "{{title}}"
frequency: daily
streak: 0
longest_streak: 0
last_completed: null
status: active
category: personal
difficulty: medium
tokens_per_completion: 5
google_event_id: null
scheduled_time: null
scheduled_days: []
tags: [habit]
created: "{{date}}"
updated: "{{date}}"
---

# {{title}}

## Goal


## Schedule


## Completion Log


## Notes
"""

GOAL_TEMPLATE = """\
---
type: goal
name: "{{title}}"
status: not-started
priority: medium
start_date: "{{date}}"
target_date: null
progress: 0
category: personal
tags: [goal]
milestones: []
related_tasks: []
created: "{{date}}"
updated: "{{date}}"
---

# {{title}}

## Why This Matters


## Success Criteria
- [ ]

## Milestones

### 1. First Milestone
**Due:**
**Status:** Not Started

- [ ]

## Related Tasks


## Resources


## Notes
"""

DAILY_TEMPLATE = """\
---
type: daily
date: "{{date}}"
day_of_week: "{{day}}"
tokens_earned: 0
tokens_total: 0
mood: null
energy: null
completed_habits: []
tags: [daily]
created: "{{date}}"
updated: "{{date}}"
---

# {{day_full}}, {{date_formatted}}

## Tokens Today: 0
**Total Bank:** 0 tokens

## Daily Habits
- [ ] Review Email
- [ ] Review Browser Tabs

## Tasks
- [ ]

## Notes
"""


def _write(path: Path, content: str):
    """Helper to create a file with parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def vault_path(tmp_path):
    """Create a temporary vault directory with templates and sample files."""
    vault = tmp_path / "vault"
    vault.mkdir()

    # Required: AGENTS.md
    _write(vault / "AGENTS.md", "# Agents\n")

    # Templates
    templates = vault / "00-system" / "templates"
    _write(templates / "_task_.md", TASK_TEMPLATE)
    _write(templates / "_habit_.md", HABIT_TEMPLATE)
    _write(templates / "_goal_.md", GOAL_TEMPLATE)
    _write(templates / "_daily_.md", DAILY_TEMPLATE)

    # Token ledger
    _write(vault / "00-system" / "motivation-tokens.md", """\
---
type: system
total_tokens: 50
tokens_today: 10
all_time_tokens: 50
created: '2026-01-01'
updated: '2026-01-01'
---

# Motivation Tokens Ledger
""")

    # Sample active tasks (varying priorities and due dates)
    _write(vault / "40-tasks" / "active" / "buy-groceries.md", """\
---
type: task
name: Buy groceries
status: active
priority: 3
due_date: '2026-03-01'
category: personal
tokens_on_completion: 5
google_event_id: null
created: '2026-02-20'
updated: '2026-02-20'
---

# Buy groceries
""")

    _write(vault / "40-tasks" / "active" / "finish-report.md", """\
---
type: task
name: Finish report
status: active
priority: 5
due_date: '2026-02-28'
category: work
tokens_on_completion: 25
google_event_id: null
created: '2026-02-15'
updated: '2026-02-15'
---

# Finish report
""")

    _write(vault / "40-tasks" / "active" / "learn-rust.md", """\
---
type: task
name: Learn Rust basics
status: active
priority: 2
due_date: null
category: learning
tokens_on_completion: 10
google_event_id: null
created: '2026-02-10'
updated: '2026-02-10'
---

# Learn Rust basics
""")

    # Archive dir (empty)
    (vault / "40-tasks" / "archive").mkdir(parents=True)

    # Sample habits
    _write(vault / "20-habits" / "workout.md", """\
---
type: habit
name: Workout
frequency: 3x/week
streak: 5
longest_streak: 8
last_completed: '2026-02-27'
status: active
category: health
difficulty: medium
tokens_per_completion: 15
google_event_id: evt-123
tags: [habit, health]
created: '2026-02-01'
updated: '2026-02-27'
---

# Workout
""")

    _write(vault / "20-habits" / "read-book.md", """\
---
type: habit
name: Read book
frequency: daily
streak: 0
longest_streak: 3
last_completed: '2026-02-20'
status: active
category: learning
difficulty: easy
tokens_per_completion: 5
google_event_id: null
tags: [habit, learning]
created: '2026-02-01'
updated: '2026-02-20'
---

# Read book
""")

    _write(vault / "20-habits" / "old-habit.md", """\
---
type: habit
name: Old habit
frequency: daily
streak: 0
longest_streak: 0
last_completed: null
status: inactive
category: personal
difficulty: easy
tokens_per_completion: 5
google_event_id: null
tags: [habit]
created: '2026-01-01'
updated: '2026-01-01'
---

# Old habit
""")

    # Sample goals
    (vault / "30-goals" / "2026").mkdir(parents=True)
    _write(vault / "30-goals" / "2026" / "get-fit.md", """\
---
type: goal
name: Get fit
status: in-progress
priority: high
start_date: '2026-01-01'
target_date: '2026-06-01'
progress: 30
category: health
tags: [goal, health]
milestones: []
related_tasks: []
created: '2026-01-01'
updated: '2026-02-20'
---

# Get fit
""")

    _write(vault / "30-goals" / "2026" / "learn-python.md", """\
---
type: goal
name: Learn Python
status: not-started
priority: medium
start_date: '2026-02-01'
target_date: '2026-12-31'
progress: 0
category: learning
tags: [goal, learning]
milestones: []
related_tasks: []
created: '2026-02-01'
updated: '2026-02-01'
---

# Learn Python
""")

    _write(vault / "30-goals" / "2026" / "done-goal.md", """\
---
type: goal
name: Done goal
status: completed
priority: low
progress: 100
category: personal
tags: [goal]
milestones: []
related_tasks: []
created: '2026-01-01'
updated: '2026-02-15'
---

# Done goal
""")

    # Daily notes dir
    (vault / "10-daily").mkdir(parents=True)

    return vault


@pytest.fixture
def vault_service(vault_path):
    """Create a VaultService instance pointing at the temp vault."""
    return VaultService(vault_path)
```

**Step 2: Verify fixtures work by running existing tests**

Run: `cd apps/vault-server && source venv/bin/activate && pytest tests/ -v`
Expected: 2 existing tests pass (test_vault_service_initializes, test_vault_service_rejects_missing_path)

**Step 3: Commit**

```bash
git add apps/vault-server/tests/conftest.py
git commit -m "test: add shared fixtures for VaultService tests"
```

---

### Task 2: Core CRUD Tests (`test_vault_service.py`)

**Files:**
- Modify: `apps/vault-server/tests/test_vault_service.py`

**Step 1: Write the tests**

Replace the existing file with:

```python
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
```

**Step 2: Run tests**

Run: `cd apps/vault-server && pytest tests/test_vault_service.py -v`
Expected: All 14 tests pass

**Step 3: Commit**

```bash
git add apps/vault-server/tests/test_vault_service.py
git commit -m "test: add core CRUD tests for VaultService"
```

---

### Task 3: Task Operation Tests (`test_task_operations.py`)

**Files:**
- Create: `apps/vault-server/tests/test_task_operations.py`

**Step 1: Write the tests**

```python
"""Tests for VaultService task operations."""
import pytest


def test_create_task_with_defaults(vault_service, vault_path):
    result = vault_service.create_task("Buy milk")

    assert result["path"] == "40-tasks/active/buy-milk.md"
    assert result["metadata"]["name"] == "Buy milk"
    assert result["metadata"]["priority"] == 3
    assert result["metadata"]["category"] == "personal"
    assert result["metadata"]["status"] == "active"
    assert result["metadata"]["tokens_on_completion"] == 5
    assert (vault_path / "40-tasks" / "active" / "buy-milk.md").exists()


def test_create_task_with_custom_params(vault_service):
    result = vault_service.create_task(
        "Ship feature",
        priority=5,
        due_date="2026-03-15",
        category="work",
        tokens_on_completion=50,
    )

    assert result["metadata"]["priority"] == 5
    assert result["metadata"]["due_date"] == "2026-03-15"
    assert result["metadata"]["category"] == "work"
    assert result["metadata"]["tokens_on_completion"] == 50


def test_list_active_tasks_sorted_by_priority_then_due_date(vault_service):
    tasks = vault_service.list_active_tasks()

    names = [t["metadata"]["name"] for t in tasks]
    # Priority 5 first, then 3, then 2
    assert names[0] == "Finish report"    # priority 5
    assert names[1] == "Buy groceries"    # priority 3
    assert names[2] == "Learn Rust basics"  # priority 2


def test_find_task_by_name_exact(vault_service):
    task = vault_service.find_task_by_name("Buy groceries")
    assert task is not None
    assert task["metadata"]["name"] == "Buy groceries"


def test_find_task_by_name_partial(vault_service):
    task = vault_service.find_task_by_name("groceries")
    assert task is not None
    assert task["metadata"]["name"] == "Buy groceries"


def test_find_task_by_name_case_insensitive(vault_service):
    task = vault_service.find_task_by_name("BUY GROCERIES")
    assert task is not None


def test_find_task_by_name_no_match(vault_service):
    task = vault_service.find_task_by_name("nonexistent task xyz")
    assert task is None


def test_complete_task_moves_to_archive(vault_service, vault_path):
    result = vault_service.complete_task("40-tasks/active/buy-groceries.md")

    assert result["task_name"] == "Buy groceries"
    assert result["tokens_earned"] == 5
    assert result["archive_path"] == "40-tasks/archive/buy-groceries.md"

    # Verify file moved
    assert not (vault_path / "40-tasks" / "active" / "buy-groceries.md").exists()
    assert (vault_path / "40-tasks" / "archive" / "buy-groceries.md").exists()

    # Verify archived metadata
    archived = vault_service.read_file("40-tasks/archive/buy-groceries.md")
    assert archived["metadata"]["status"] == "done"
    assert "completed_date" in archived["metadata"]


def test_get_tasks_needing_sync(vault_service):
    # All sample tasks have google_event_id: null and only some have due dates
    tasks = vault_service.get_tasks_needing_sync()
    names = {t["metadata"]["name"] for t in tasks}

    # Only tasks with due_date AND no google_event_id
    assert "Buy groceries" in names     # has due_date, no event_id
    assert "Finish report" in names     # has due_date, no event_id
    assert "Learn Rust basics" not in names  # no due_date
```

**Step 2: Run tests**

Run: `cd apps/vault-server && pytest tests/test_task_operations.py -v`
Expected: All 9 tests pass

**Step 3: Commit**

```bash
git add apps/vault-server/tests/test_task_operations.py
git commit -m "test: add task operation tests for VaultService"
```

---

### Task 4: Habit Operation Tests (`test_habit_operations.py`)

**Files:**
- Create: `apps/vault-server/tests/test_habit_operations.py`

**Step 1: Write the tests**

```python
"""Tests for VaultService habit operations."""
import pytest


def test_create_habit_with_defaults(vault_service, vault_path):
    result = vault_service.create_habit("Meditate")

    assert result["path"] == "20-habits/meditate.md"
    assert result["metadata"]["name"] == "Meditate"
    assert result["metadata"]["frequency"] == "daily"
    assert result["metadata"]["streak"] == 0
    assert result["metadata"]["status"] == "active"
    assert (vault_path / "20-habits" / "meditate.md").exists()


def test_create_habit_with_custom_params(vault_service):
    result = vault_service.create_habit(
        "Run",
        frequency="3x/week",
        category="health",
        difficulty="hard",
        tokens_per_completion=20,
    )

    assert result["metadata"]["frequency"] == "3x/week"
    assert result["metadata"]["category"] == "health"
    assert result["metadata"]["difficulty"] == "hard"
    assert result["metadata"]["tokens_per_completion"] == 20


def test_list_active_habits_filters_inactive(vault_service):
    habits = vault_service.list_active_habits()
    names = {h["metadata"]["name"] for h in habits}

    assert "Workout" in names
    assert "Read book" in names
    assert "Old habit" not in names  # status: inactive


def test_read_habit(vault_service):
    data = vault_service.read_habit("workout")

    assert data["metadata"]["name"] == "Workout"
    assert data["metadata"]["streak"] == 5


def test_update_habit_returns_updated_data(vault_service):
    result = vault_service.update_habit("workout", {"streak": 6})

    assert result["metadata"]["streak"] == 6
    assert result["metadata"]["name"] == "Workout"  # preserved


def test_get_habits_needing_sync(vault_service):
    habits = vault_service.get_habits_needing_sync()
    names = {h["metadata"]["name"] for h in habits}

    # workout has google_event_id=evt-123, read-book has null
    assert "Read book" in names
    assert "Workout" not in names
```

**Step 2: Run tests**

Run: `cd apps/vault-server && pytest tests/test_habit_operations.py -v`
Expected: All 6 tests pass

**Step 3: Commit**

```bash
git add apps/vault-server/tests/test_habit_operations.py
git commit -m "test: add habit operation tests for VaultService"
```

---

### Task 5: Goal Operation Tests (`test_goal_operations.py`)

**Files:**
- Create: `apps/vault-server/tests/test_goal_operations.py`

**Step 1: Write the tests**

```python
"""Tests for VaultService goal operations."""
import pytest
from unittest.mock import patch
from datetime import datetime


def test_create_goal_with_defaults(vault_service, vault_path):
    with patch("src.services.vault_service.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 2, 28, 12, 0, 0)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = vault_service.create_goal("Run a marathon")

    assert result["path"] == "30-goals/2026/run-a-marathon.md"
    assert result["metadata"]["name"] == "Run a marathon"
    assert result["metadata"]["status"] == "not-started"
    assert result["metadata"]["priority"] == "medium"
    assert result["metadata"]["progress"] == 0
    assert (vault_path / "30-goals" / "2026" / "run-a-marathon.md").exists()


def test_create_goal_with_custom_params(vault_service):
    result = vault_service.create_goal(
        "Save money",
        priority="high",
        target_date="2026-12-31",
        category="finance",
    )

    assert result["metadata"]["priority"] == "high"
    assert result["metadata"]["target_date"] == "2026-12-31"
    assert result["metadata"]["category"] == "finance"


def test_list_active_goals_filters_completed(vault_service):
    goals = vault_service.list_active_goals()
    names = {g["metadata"]["name"] for g in goals}

    assert "Get fit" in names          # in-progress
    assert "Learn Python" in names     # not-started
    assert "Done goal" not in names    # completed


def test_list_active_goals_sorted_by_priority_then_progress(vault_service):
    goals = vault_service.list_active_goals()
    names = [g["metadata"]["name"] for g in goals]

    # high priority first, then medium
    assert names[0] == "Get fit"       # high priority, 30% progress
    assert names[1] == "Learn Python"  # medium priority, 0% progress
```

**Step 2: Run tests**

Run: `cd apps/vault-server && pytest tests/test_goal_operations.py -v`
Expected: All 4 tests pass

**Step 3: Commit**

```bash
git add apps/vault-server/tests/test_goal_operations.py
git commit -m "test: add goal operation tests for VaultService"
```

---

### Task 6: Token Operation Tests (`test_token_operations.py`)

**Files:**
- Create: `apps/vault-server/tests/test_token_operations.py`

**Step 1: Write the tests**

```python
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
```

**Step 2: Run tests**

Run: `cd apps/vault-server && pytest tests/test_token_operations.py -v`
Expected: All 4 tests pass

**Step 3: Commit**

```bash
git add apps/vault-server/tests/test_token_operations.py
git commit -m "test: add token operation tests for VaultService"
```

---

### Task 7: Full Test Suite Run

**Step 1: Run all tests**

Run: `cd apps/vault-server && pytest tests/ -v`
Expected: All ~37 tests pass (14 core + 9 task + 6 habit + 4 goal + 4 token)

**Step 2: Run via Turborepo**

Run: `cd /home/marcellmc/dev/mazkir && npx turbo test`
Expected: Both apps' test scripts run successfully

**Step 3: Final commit with all tests passing**

If any individual task commits were skipped, do a single combined commit:
```bash
git add apps/vault-server/tests/
git commit -m "test: add comprehensive VaultService test suite"
```
