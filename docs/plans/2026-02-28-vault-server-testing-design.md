# Vault-Server Testing Design

## Goal

Add fixture-based unit tests for VaultService — the core business logic layer that handles all Obsidian vault CRUD operations.

## Approach

Fixture-based unit tests using `tmp_path`. Each test gets a temporary vault directory with real templates and sample files. No mocking — tests exercise real file I/O and frontmatter parsing.

## Test Structure

```
apps/vault-server/tests/
├── conftest.py              # Shared fixtures
├── test_vault_service.py    # Core CRUD tests
├── test_task_operations.py  # Task lifecycle
├── test_habit_operations.py # Habit CRUD
├── test_goal_operations.py  # Goal CRUD
└── test_token_operations.py # Token ledger
```

## Core Fixture (`conftest.py`)

A `vault_service` fixture that creates:
- `AGENTS.md`
- `00-system/templates/` with `_task_.md`, `_habit_.md`, `_goal_.md`, `_daily_.md`
- `00-system/motivation-tokens.md` (ledger with initial values)
- `40-tasks/active/` with 2-3 sample tasks (varying priorities/due dates)
- `20-habits/` with 2 sample habits (one active, one inactive)
- `30-goals/{year}/` with 2 sample goals (varying statuses)
- `10-daily/` directory (empty, for daily note creation tests)

Returns a `VaultService` instance pointing at this temp vault.

## Test Coverage

### `test_vault_service.py` — Core CRUD (~8 tests)
- `read_file`: parses frontmatter + content, raises FileNotFoundError for missing
- `write_file`: creates file with frontmatter, creates parent dirs, sets `updated`
- `update_file`: merges metadata, preserves existing content
- `list_files`: returns .md files, empty list for missing dir
- `_sanitize_filename`: special chars, spaces, length truncation
- `_process_template`: placeholder substitution in metadata and content

### `test_task_operations.py` (~7 tests)
- `create_task`: correct path, all metadata fields, default values
- `create_task` with custom params: priority, due_date, category, tokens
- `list_active_tasks`: sorted by priority desc then due_date asc
- `find_task_by_name`: fuzzy match, case insensitive
- `find_task_by_name`: returns None when no match
- `complete_task`: moves to archive, deletes from active, awards tokens
- `get_tasks_needing_sync`: filters tasks without google_event_id

### `test_habit_operations.py` (~5 tests)
- `create_habit`: correct path, metadata, defaults
- `list_active_habits`: filters by status=active
- `update_habit`: updates fields, returns updated data
- `read_habit`: reads by name
- `get_habits_needing_sync`: filters habits without google_event_id

### `test_goal_operations.py` (~4 tests)
- `create_goal`: year-based path, metadata, defaults
- `list_active_goals`: filters by active statuses (in-progress, not-started, active, planning)
- `list_active_goals`: sorted by priority desc then progress asc
- `create_goal` with custom params: priority, target_date, category

### `test_token_operations.py` (~4 tests)
- `read_token_ledger`: reads ledger file
- `update_tokens`: increments totals correctly
- `update_tokens`: tracks daily tokens
- `update_tokens`: resets tokens_today on new day

**Total: ~28 test cases**

## Dependencies

Already available in vault-server `pyproject.toml`:
- `pytest>=8.0.0`
- `pytest-asyncio>=0.23.0`
- `httpx>=0.27.0`

No additional dependencies needed.

## Run Command

```bash
cd apps/vault-server && pytest tests/ -v
```

Or via Turborepo: `npx turbo test`
