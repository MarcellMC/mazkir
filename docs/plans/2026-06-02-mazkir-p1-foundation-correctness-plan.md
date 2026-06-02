# Mazkir P1 — Foundation Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Mazkir's vault operations deterministic and reliable: fix the May 21 bugs, replace `update_item` with typed mutators, add a unified fuzzy-path resolver, normalize tool responses with an error-code enum, install a minimal hook framework with schema validation, and add idempotency to state-changing tools.

**Architecture:** Adds three new modules under `apps/vault-server/src/services/`: `tool_response.py` (response shape + codes), `resolver.py` (single fuzzy-match helper), `hooks/` (pre/post execution framework). Modifies `agent_service.py` to wire hooks, swap `update_item` for typed mutators, fix the `complete_task` bug, and emit normalized responses. Modifies `vault_service.py` to support new schema fields (`scheduled_at`, `duration_minutes`, `due_soft`, lifecycle fields) and to append a `## History` section in item bodies.

**Tech Stack:** Python 3.14, FastAPI, Pydantic, `jsonschema` (new dependency for schema validation), `rapidfuzz` (new dependency for resolver). Tests via `pytest`. The vault is markdown with YAML frontmatter (`python-frontmatter`).

**Spec source:** `docs/plans/2026-06-01-mazkir-usability-design.md` — Blocks A and D-schema/D2.

**Out of scope for this plan (deferred to later P-plans):**
- Skill registry, router, sub-agents (P2)
- Confidence-gate UX changes, preview, post-hooks beyond schema validation (P2)
- Calendar sync as post-hook (P5, depends on P2 hook expansion)
- Context optimization, observability gaps (P3)
- Daily-tier task tools, `/day` redesign, media migration (P4)
- Schema migration script for existing vault files

---

## File Structure

**Create:**
- `apps/vault-server/src/services/tool_response.py` — `ToolResponse`, `ok()`, `err()`, `ErrorCode` enum
- `apps/vault-server/src/services/resolver.py` — `resolve_item(item_type, query, vault) -> ToolResponse`
- `apps/vault-server/src/services/hooks/__init__.py` — `Hook` Protocol, `HOOK_REGISTRY`, `run_pre_hooks()`, `run_post_hooks()`
- `apps/vault-server/src/services/hooks/validate_schema.py` — `validate_schema` pre-hook
- `apps/vault-server/tests/test_tool_response.py`
- `apps/vault-server/tests/test_resolver.py`
- `apps/vault-server/tests/test_hooks.py`
- `apps/vault-server/tests/test_typed_mutators.py`

**Modify:**
- `apps/vault-server/src/services/vault_service.py` — add `append_history_line()`, accept new fields in `create_task/create_habit/create_goal`, expose `list_items(item_type)`
- `apps/vault-server/src/services/agent_service.py` — register `update_task/_habit/_goal`, drop `update_item`, fix `complete_task` dict-unpack bug, wire hooks in `_execute_tool_inner`, switch destructive handlers to resolver, emit `ToolResponse`-shaped output, add idempotency checks
- `apps/vault-server/tests/test_agent_service.py` — update assertions for new response shape, remove `update_item` tests, add typed-mutator tests
- `apps/vault-server/tests/test_vault_service.py` — add tests for `append_history_line` and new schema fields
- `apps/vault-server/pyproject.toml` — add `jsonschema`, `rapidfuzz` dependencies

---

## Task 1: Add `jsonschema` and `rapidfuzz` dependencies

**Files:**
- Modify: `apps/vault-server/pyproject.toml`

- [ ] **Step 1: Open pyproject.toml and locate the `[project]` `dependencies` array**

Read `apps/vault-server/pyproject.toml`. Find the existing `dependencies = [...]` list under `[project]`.

- [ ] **Step 2: Add `jsonschema` and `rapidfuzz` to the list**

Append two entries (alphabetical order preferred):

```toml
"jsonschema>=4.20.0",
"rapidfuzz>=3.6.0",
```

- [ ] **Step 3: Install into the venv**

```bash
cd ~/dev/mazkir/apps/vault-server
source venv/bin/activate
pip install jsonschema rapidfuzz
```

Expected: both packages install without error.

- [ ] **Step 4: Verify imports work**

```bash
python -c "import jsonschema; import rapidfuzz; print('ok')"
```

Expected output: `ok`

- [ ] **Step 5: Commit**

```bash
cd ~/dev/mazkir
git add apps/vault-server/pyproject.toml
git commit -m "deps(vault-server): add jsonschema and rapidfuzz for P1 foundation"
```

---

## Task 2: Tool response shape (`ToolResponse`, `ok`, `err`, `ErrorCode`)

**Files:**
- Create: `apps/vault-server/src/services/tool_response.py`
- Test: `apps/vault-server/tests/test_tool_response.py`

- [ ] **Step 1: Write the failing test**

Create `apps/vault-server/tests/test_tool_response.py`:

```python
"""Tests for normalized tool response shape."""

from src.services.tool_response import ok, err, ErrorCode


def test_ok_basic():
    r = ok({"saved": "path.md"}, items=["path.md"])
    assert r == {
        "ok": True,
        "data": {"saved": "path.md"},
        "_items": ["path.md"],
    }


def test_ok_default_items():
    r = ok({"x": 1})
    assert r["_items"] == []


def test_err_basic():
    r = err(ErrorCode.PATH_NOT_FOUND, "no such file", details={"query": "foo"})
    assert r == {
        "ok": False,
        "error": {
            "code": "PATH_NOT_FOUND",
            "message": "no such file",
            "details": {"query": "foo"},
        },
        "_items": [],
    }


def test_err_default_details():
    r = err(ErrorCode.SCHEMA_INVALID, "bad input")
    assert r["error"]["details"] == {}


def test_error_codes_complete():
    expected = {
        "PATH_NOT_FOUND",
        "AMBIGUOUS_MATCH",
        "SCHEMA_INVALID",
        "STATE_CONFLICT",
        "ALREADY_DONE",
        "EXTERNAL_FAILURE",
        "AUTH_REQUIRED",
        "CANCELLED_BY_USER",
    }
    assert {c.value for c in ErrorCode} == expected
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd ~/dev/mazkir/apps/vault-server
source venv/bin/activate
python -m pytest tests/test_tool_response.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.tool_response'`

- [ ] **Step 3: Implement `tool_response.py`**

Create `apps/vault-server/src/services/tool_response.py`:

```python
"""Normalized tool response shape and error code enum.

All agent tools return either:
    {"ok": True, "data": {...}, "_items": [...]}
or:
    {"ok": False, "error": {"code": "...", "message": "...", "details": {...}}, "_items": []}

The `_items` list is used by MemoryService to track which vault paths were
touched by a tool call. It is always present (empty on error).
"""

from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    """Stable machine-parseable codes for tool errors.

    The agent's system prompt explains how to respond to each code.
    """

    PATH_NOT_FOUND = "PATH_NOT_FOUND"
    AMBIGUOUS_MATCH = "AMBIGUOUS_MATCH"
    SCHEMA_INVALID = "SCHEMA_INVALID"
    STATE_CONFLICT = "STATE_CONFLICT"
    ALREADY_DONE = "ALREADY_DONE"
    EXTERNAL_FAILURE = "EXTERNAL_FAILURE"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    CANCELLED_BY_USER = "CANCELLED_BY_USER"


def ok(data: dict[str, Any], items: list[str] | None = None) -> dict[str, Any]:
    """Build a successful tool response."""
    return {
        "ok": True,
        "data": data,
        "_items": items or [],
    }


def err(
    code: ErrorCode,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an error tool response."""
    return {
        "ok": False,
        "error": {
            "code": code.value,
            "message": message,
            "details": details or {},
        },
        "_items": [],
    }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_tool_response.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/dev/mazkir
git add apps/vault-server/src/services/tool_response.py apps/vault-server/tests/test_tool_response.py
git commit -m "feat(vault-server): add normalized tool response shape with error code enum"
```

---

## Task 3: Hook framework skeleton

**Files:**
- Create: `apps/vault-server/src/services/hooks/__init__.py`
- Test: `apps/vault-server/tests/test_hooks.py`

- [ ] **Step 1: Write the failing test**

Create `apps/vault-server/tests/test_hooks.py`:

```python
"""Tests for the pre/post hook framework."""

import pytest

from src.services.hooks import (
    HOOK_REGISTRY,
    register_hook,
    run_pre_hooks,
    run_post_hooks,
)
from src.services.tool_response import ok, err, ErrorCode


@pytest.fixture(autouse=True)
def clean_registry():
    """Reset registry between tests."""
    saved = HOOK_REGISTRY.copy()
    HOOK_REGISTRY.clear()
    yield
    HOOK_REGISTRY.clear()
    HOOK_REGISTRY.update(saved)


def test_register_hook():
    def my_hook(params, ctx):
        return None
    register_hook("my", my_hook)
    assert HOOK_REGISTRY["my"] is my_hook


def test_pre_hooks_pass_through_when_none_blocks():
    register_hook("a", lambda p, c: None)
    register_hook("b", lambda p, c: None)
    result = run_pre_hooks(["a", "b"], {"x": 1}, ctx=None)
    assert result is None  # not blocked


def test_pre_hook_blocks_returns_error_response():
    register_hook(
        "blocker",
        lambda p, c: err(ErrorCode.SCHEMA_INVALID, "nope"),
    )
    result = run_pre_hooks(["blocker"], {"x": 1}, ctx=None)
    assert result is not None
    assert result["ok"] is False
    assert result["error"]["code"] == "SCHEMA_INVALID"


def test_pre_hook_chain_stops_at_first_blocker():
    calls = []
    register_hook("a", lambda p, c: calls.append("a") or None)
    register_hook(
        "b",
        lambda p, c: calls.append("b") or err(ErrorCode.PATH_NOT_FOUND, "halt"),
    )
    register_hook("c", lambda p, c: calls.append("c") or None)
    run_pre_hooks(["a", "b", "c"], {}, ctx=None)
    assert calls == ["a", "b"]  # c not invoked


def test_post_hooks_run_after_handler():
    calls = []
    register_hook("post1", lambda p, o, c: calls.append(("post1", o)))
    register_hook("post2", lambda p, o, c: calls.append(("post2", o)))
    run_post_hooks(["post1", "post2"], params={}, output={"x": 1}, ctx=None)
    assert calls == [("post1", {"x": 1}), ("post2", {"x": 1})]


def test_run_pre_hooks_unknown_name_raises():
    with pytest.raises(KeyError):
        run_pre_hooks(["missing"], {}, ctx=None)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_hooks.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.hooks'`.

- [ ] **Step 3: Implement the framework**

Create `apps/vault-server/src/services/hooks/__init__.py`:

```python
"""Tool execution hook framework.

A hook is a function called before (pre) or after (post) a tool handler runs.

Pre-hook signature: (params: dict, ctx: Any) -> Optional[dict]
    Returning None means "pass". Returning a tool-response dict (built via
    tool_response.err()) blocks execution; the response is returned to the
    agent as if the handler had emitted it.

Post-hook signature: (params: dict, output: dict, ctx: Any) -> None
    Side-effects only. Exceptions are caught and logged by the caller (TBD
    when post-hooks are wired in P2/P5); for P1 the registry is in place
    but only pre-hooks are exercised.

Hooks are registered globally via `register_hook(name, fn)`. Tool registry
entries reference hooks by name.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

PreHook = Callable[[dict, Any], Optional[dict]]
PostHook = Callable[[dict, dict, Any], None]

HOOK_REGISTRY: dict[str, Callable] = {}


def register_hook(name: str, fn: Callable) -> None:
    """Add a hook function to the global registry under `name`."""
    HOOK_REGISTRY[name] = fn


def run_pre_hooks(
    hook_names: list[str],
    params: dict,
    ctx: Any,
) -> Optional[dict]:
    """Run pre-hooks in order. Return the first blocking response, else None.

    Raises KeyError if a referenced hook name is not registered.
    """
    for name in hook_names:
        hook = HOOK_REGISTRY[name]  # KeyError if missing
        result = hook(params, ctx)
        if result is not None:
            return result
    return None


def run_post_hooks(
    hook_names: list[str],
    params: dict,
    output: dict,
    ctx: Any,
) -> None:
    """Run post-hooks in order. Side-effects only.

    Raises KeyError if a referenced hook name is not registered.
    """
    for name in hook_names:
        hook = HOOK_REGISTRY[name]  # KeyError if missing
        hook(params, output, ctx)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_hooks.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/dev/mazkir
git add apps/vault-server/src/services/hooks/__init__.py apps/vault-server/tests/test_hooks.py
git commit -m "feat(vault-server): add pre/post hook framework for tool execution"
```

---

## Task 4: `validate_schema` pre-hook

**Files:**
- Create: `apps/vault-server/src/services/hooks/validate_schema.py`
- Modify: `apps/vault-server/tests/test_hooks.py` (add validate_schema tests)

- [ ] **Step 1: Add failing tests**

Append to `apps/vault-server/tests/test_hooks.py`:

```python
from src.services.hooks.validate_schema import validate_schema


def test_validate_schema_passes_valid_input():
    ctx = {
        "tool": {
            "schema": {
                "input_schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                    "additionalProperties": False,
                }
            }
        }
    }
    assert validate_schema({"name": "x"}, ctx) is None


def test_validate_schema_rejects_missing_required():
    ctx = {
        "tool": {
            "schema": {
                "input_schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                }
            }
        }
    }
    result = validate_schema({}, ctx)
    assert result is not None
    assert result["ok"] is False
    assert result["error"]["code"] == "SCHEMA_INVALID"
    assert "name" in result["error"]["message"]


def test_validate_schema_rejects_additional_props():
    """The Migdal failure mode: passing extra fields not in schema."""
    ctx = {
        "tool": {
            "schema": {
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "additionalProperties": False,
                }
            }
        }
    }
    result = validate_schema({"path": "x", "extra": "y"}, ctx)
    assert result is not None
    assert result["error"]["code"] == "SCHEMA_INVALID"


def test_validate_schema_rejects_wrong_type():
    """The 'JSON-string for updates' failure mode."""
    ctx = {
        "tool": {
            "schema": {
                "input_schema": {
                    "type": "object",
                    "properties": {"updates": {"type": "object"}},
                    "required": ["updates"],
                }
            }
        }
    }
    result = validate_schema({"updates": '{"key": "value"}'}, ctx)
    assert result is not None
    assert result["error"]["code"] == "SCHEMA_INVALID"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_hooks.py -v
```

Expected: 4 new failures (`ModuleNotFoundError: No module named 'src.services.hooks.validate_schema'`).

- [ ] **Step 3: Implement the hook**

Create `apps/vault-server/src/services/hooks/validate_schema.py`:

```python
"""Schema-validation pre-hook.

Validates tool input against the JSON Schema declared in the tool registry
entry. Catches failure modes that Claude SDK's loose schema enforcement lets
through, in particular:

- Missing required fields
- additionalProperties violations
- Wrong types (e.g. JSON-encoded string passed where object is expected)
"""

from typing import Any, Optional

import jsonschema

from src.services.tool_response import ErrorCode, err


def validate_schema(params: dict, ctx: Any) -> Optional[dict]:
    """Validate `params` against `ctx['tool']['schema']['input_schema']`.

    Returns None on success, an error response on failure.

    `ctx` must contain `tool` mapping with the tool registry entry. Hooks
    that want to ignore validation simply aren't registered.
    """
    tool = ctx["tool"]
    schema = tool["schema"]["input_schema"]
    try:
        jsonschema.validate(params, schema)
    except jsonschema.ValidationError as e:
        return err(
            ErrorCode.SCHEMA_INVALID,
            f"Input schema violation: {e.message}",
            details={
                "path": list(e.absolute_path),
                "schema_path": list(e.schema_path),
            },
        )
    return None
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_hooks.py -v
```

Expected: all 10 tests pass.

- [ ] **Step 5: Commit**

```bash
cd ~/dev/mazkir
git add apps/vault-server/src/services/hooks/validate_schema.py apps/vault-server/tests/test_hooks.py
git commit -m "feat(vault-server): add validate_schema pre-hook covering Migdal failure modes"
```

---

## Task 5: Unified fuzzy-path resolver

**Files:**
- Create: `apps/vault-server/src/services/resolver.py`
- Test: `apps/vault-server/tests/test_resolver.py`

- [ ] **Step 1: Write failing tests**

Create `apps/vault-server/tests/test_resolver.py`:

```python
"""Tests for the unified item resolver."""

import pytest
from unittest.mock import MagicMock

from src.services.resolver import resolve_item, SCORE_AMBIGUOUS_DELTA


def _mk_item(path: str, name: str):
    return {"path": path, "metadata": {"name": name}}


@pytest.fixture
def vault():
    v = MagicMock()
    v.list_active_tasks.return_value = [
        _mk_item("40-tasks/active/migdal-insurance.md", "Submit missing documents to Migdal Insurance"),
        _mk_item("40-tasks/active/order-phone.md", "Order phone from AliExpress"),
        _mk_item("40-tasks/active/walk-dog.md", "Walk the dog"),
    ]
    v.list_active_habits.return_value = []
    v.list_active_goals.return_value = []
    return v


def test_exact_path_match(vault):
    r = resolve_item("task", "40-tasks/active/walk-dog.md", vault)
    assert r["ok"] is True
    assert r["data"]["path"] == "40-tasks/active/walk-dog.md"


def test_exact_name_match(vault):
    r = resolve_item("task", "Walk the dog", vault)
    assert r["ok"] is True
    assert r["data"]["path"] == "40-tasks/active/walk-dog.md"


def test_substring_match(vault):
    r = resolve_item("task", "migdal", vault)
    assert r["ok"] is True
    assert "migdal-insurance" in r["data"]["path"]


def test_fuzzy_match_typo(vault):
    r = resolve_item("task", "walke the dog", vault)
    assert r["ok"] is True
    assert "walk-dog" in r["data"]["path"]


def test_no_match_returns_path_not_found(vault):
    r = resolve_item("task", "completely unrelated", vault)
    assert r["ok"] is False
    assert r["error"]["code"] == "PATH_NOT_FOUND"


def test_ambiguous_returns_candidates():
    v = MagicMock()
    v.list_active_tasks.return_value = [
        _mk_item("40-tasks/active/migdal-insurance.md", "Migdal Insurance docs"),
        _mk_item("40-tasks/active/migdal-bank.md", "Migdal Bank statement"),
    ]
    r = resolve_item("task", "migdal", v)
    assert r["ok"] is False
    assert r["error"]["code"] == "AMBIGUOUS_MATCH"
    assert len(r["error"]["details"]["candidates"]) >= 2


def test_habit_resolution_uses_habit_list():
    v = MagicMock()
    v.list_active_habits.return_value = [
        _mk_item("20-habits/morning-workout.md", "Morning workout"),
    ]
    v.list_active_tasks.return_value = []
    r = resolve_item("habit", "workout", v)
    assert r["ok"] is True
    assert r["data"]["name"] == "Morning workout"


def test_goal_resolution_uses_goal_list():
    v = MagicMock()
    v.list_active_goals.return_value = [
        _mk_item("30-goals/2026/learn-ai.md", "Learn AI engineering"),
    ]
    v.list_active_tasks.return_value = []
    v.list_active_habits.return_value = []
    r = resolve_item("goal", "ai engineering", v)
    assert r["ok"] is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_resolver.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.resolver'`.

- [ ] **Step 3: Implement the resolver**

Create `apps/vault-server/src/services/resolver.py`:

```python
"""Unified fuzzy-path resolver for tasks, habits, and goals.

Single function `resolve_item(item_type, query, vault)` used by every name-
accepting tool. Returns a normalized ToolResponse — `ok` with the matched
path/name/score, or `err` with PATH_NOT_FOUND or AMBIGUOUS_MATCH.
"""

from __future__ import annotations

from typing import Any, Literal

from rapidfuzz import fuzz

from src.services.tool_response import ErrorCode, err, ok

SCORE_AMBIGUOUS_DELTA = 10.0  # rapidfuzz scores are 0–100; <10 gap → ambiguous

ItemType = Literal["task", "habit", "goal"]


def _candidates(vault: Any, item_type: ItemType) -> list[dict]:
    if item_type == "task":
        return vault.list_active_tasks()
    if item_type == "habit":
        return vault.list_active_habits()
    if item_type == "goal":
        return vault.list_active_goals()
    raise ValueError(f"Unknown item_type: {item_type}")


def resolve_item(item_type: ItemType, query: str, vault: Any) -> dict:
    """Resolve a query string to a unique item of the given type.

    Tries, in order: exact path match, exact name match (case-sensitive),
    case-insensitive substring of name, fuzzy match via rapidfuzz.

    Returns:
        ok({path, name, score}) on a unique hit.
        err(PATH_NOT_FOUND, ...) when no candidate scores above the floor.
        err(AMBIGUOUS_MATCH, ..., candidates: [...]) when top-1 and top-2
        are within `SCORE_AMBIGUOUS_DELTA` of each other.
    """
    items = _candidates(vault, item_type)
    if not items:
        return err(ErrorCode.PATH_NOT_FOUND, f"No {item_type}s available")

    # 1. exact path
    for item in items:
        if item["path"] == query:
            return ok({"path": item["path"], "name": item["metadata"].get("name", ""), "score": 100.0})

    # 2. exact name (case-sensitive)
    for item in items:
        if item["metadata"].get("name") == query:
            return ok({"path": item["path"], "name": item["metadata"]["name"], "score": 100.0})

    # 3. substring of name (case-insensitive)
    q_lower = query.lower()
    substring_hits = [
        item for item in items
        if q_lower in item["metadata"].get("name", "").lower()
    ]
    if len(substring_hits) == 1:
        item = substring_hits[0]
        return ok({"path": item["path"], "name": item["metadata"]["name"], "score": 95.0})

    # 4. fuzzy via rapidfuzz token_set_ratio (handles word reorder + partial)
    ranked = sorted(
        (
            {
                "path": item["path"],
                "name": item["metadata"].get("name", ""),
                "score": fuzz.token_set_ratio(query, item["metadata"].get("name", "")),
            }
            for item in items
        ),
        key=lambda r: r["score"],
        reverse=True,
    )

    if not ranked or ranked[0]["score"] < 60.0:
        return err(
            ErrorCode.PATH_NOT_FOUND,
            f"No {item_type} matched '{query}'",
            details={"query": query, "best_score": ranked[0]["score"] if ranked else 0},
        )

    top = ranked[0]
    if len(ranked) > 1 and (top["score"] - ranked[1]["score"]) < SCORE_AMBIGUOUS_DELTA:
        return err(
            ErrorCode.AMBIGUOUS_MATCH,
            f"Multiple {item_type}s match '{query}' similarly",
            details={
                "query": query,
                "candidates": [
                    {"path": r["path"], "name": r["name"], "score": r["score"]}
                    for r in ranked[:5]
                ],
            },
        )

    return ok(top)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_resolver.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/dev/mazkir
git add apps/vault-server/src/services/resolver.py apps/vault-server/tests/test_resolver.py
git commit -m "feat(vault-server): add unified fuzzy-path resolver for tasks/habits/goals"
```

---

## Task 6: `vault_service.append_history_line` helper

**Files:**
- Modify: `apps/vault-server/src/services/vault_service.py`
- Modify: `apps/vault-server/tests/test_vault_service.py`

- [ ] **Step 1: Write the failing test**

Append to `apps/vault-server/tests/test_vault_service.py` (after existing fixtures):

```python
def test_append_history_line_creates_section(vault, tmp_path):
    """First history entry creates the ## History section."""
    body = "Task body text.\n"
    new_body = vault.append_history_line(body, "Created (priority: 3)")
    assert "## History" in new_body
    assert "— Created (priority: 3)" in new_body


def test_append_history_line_appends_to_existing(vault, tmp_path):
    body = "Task body text.\n\n## History\n- 2026-05-21 14:00 — Created\n"
    new_body = vault.append_history_line(body, "Priority changed: 3 → 4")
    # original line preserved
    assert "- 2026-05-21 14:00 — Created" in new_body
    # new line appended after
    assert "Priority changed: 3 → 4" in new_body
    # only one ## History header
    assert new_body.count("## History") == 1


def test_append_history_line_timestamp_format(vault, freezer):
    freezer.move_to("2026-06-02 09:30:00")
    new_body = vault.append_history_line("body\n", "Test event")
    assert "- 2026-06-02 09:30 — Test event" in new_body
```

If `freezer` fixture isn't available, replace the third test with this simpler version (no freezer):

```python
def test_append_history_line_timestamp_format_loose(vault):
    import re
    new_body = vault.append_history_line("body\n", "Test event")
    assert re.search(r"- \d{4}-\d{2}-\d{2} \d{2}:\d{2} — Test event", new_body)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_vault_service.py::test_append_history_line_creates_section -v
```

Expected: FAIL with `AttributeError: ... no attribute 'append_history_line'`.

- [ ] **Step 3: Implement in `vault_service.py`**

Add to `apps/vault-server/src/services/vault_service.py` (find a good spot near other helpers, e.g. after `update_file`):

```python
def append_history_line(self, body: str, summary: str) -> str:
    """Append a timestamped event line to the ## History section of `body`.

    Creates the section if absent. Used by typed mutators to record schema
    changes inline so the audit log lives next to the data in Obsidian.

    Args:
        body: Current markdown body (without frontmatter).
        summary: Free-text description of what changed.

    Returns:
        Updated body with the new history line appended.
    """
    from datetime import datetime
    ts = datetime.now(self.tz).strftime("%Y-%m-%d %H:%M")
    line = f"- {ts} — {summary}"

    if "## History" in body:
        # Append after the last line of an existing history section.
        # We append at the very end of the body, which is sufficient as long
        # as ## History is the last section. Mutators always emit it last.
        return body.rstrip() + "\n" + line + "\n"

    # Create section
    return body.rstrip() + "\n\n## History\n" + line + "\n"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_vault_service.py -k append_history_line -v
```

Expected: 2 (or 3) passed.

- [ ] **Step 5: Commit**

```bash
cd ~/dev/mazkir
git add apps/vault-server/src/services/vault_service.py apps/vault-server/tests/test_vault_service.py
git commit -m "feat(vault-server): add append_history_line helper for inline audit log"
```

---

## Task 7: Extend `vault_service.create_*` for new schema fields

**Files:**
- Modify: `apps/vault-server/src/services/vault_service.py`
- Modify: `apps/vault-server/tests/test_task_operations.py`

- [ ] **Step 1: Add failing test for `create_task` new fields**

Append to `apps/vault-server/tests/test_task_operations.py`:

```python
def test_create_task_with_scheduled_at_and_due_soft(vault):
    result = vault.create_task(
        name="Test task",
        priority=3,
        due_date="2026-06-10",
        category="general",
        scheduled_at="2026-06-05T14:00",
        duration_minutes=60,
        due_soft="2026-06-08",
    )
    meta = result["metadata"]
    assert meta["scheduled_at"] == "2026-06-05T14:00"
    assert meta["duration_minutes"] == 60
    assert meta["due_soft"] == "2026-06-08"
    assert meta["due_date"] == "2026-06-10"  # existing field preserved
    assert "created" in meta
    assert "updated" in meta
    assert meta["completed"] is None


def test_create_task_omits_optional_fields_when_not_provided(vault):
    result = vault.create_task(name="Minimal", priority=2, due_date=None)
    meta = result["metadata"]
    assert meta.get("scheduled_at") is None
    assert meta.get("duration_minutes") is None
    assert meta.get("due_soft") is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_task_operations.py::test_create_task_with_scheduled_at_and_due_soft -v
```

Expected: FAIL — either `TypeError: unexpected keyword argument 'scheduled_at'` or missing-key assertion.

- [ ] **Step 3: Update `create_task` signature**

In `apps/vault-server/src/services/vault_service.py`, find `def create_task(...)` and update the signature + body to accept and persist new fields:

```python
def create_task(
    self,
    name: str,
    priority: int = 3,
    due_date: Optional[str] = None,
    category: str = "general",
    tokens_on_completion: int = 5,
    scheduled_at: Optional[str] = None,
    duration_minutes: Optional[int] = None,
    due_soft: Optional[str] = None,
) -> Dict:
    """Create a new task file in 40-tasks/active/.

    New schema fields (scheduled_at, duration_minutes, due_soft) are
    optional and omitted from frontmatter when None. Lifecycle fields
    (created, updated, completed) are always written.
    """
    today = datetime.now(self.tz).strftime("%Y-%m-%d")
    slug = self._slugify(name)
    path = f"40-tasks/active/{slug}.md"

    metadata = {
        "type": "task",
        "name": name,
        "status": "active",
        "priority": priority,
        "due_date": due_date,
        "category": category,
        "tokens_on_completion": tokens_on_completion,
        "created": today,
        "updated": today,
        "completed": None,
    }
    if scheduled_at is not None:
        metadata["scheduled_at"] = scheduled_at
    if duration_minutes is not None:
        metadata["duration_minutes"] = duration_minutes
    if due_soft is not None:
        metadata["due_soft"] = due_soft

    self.write_file(path, metadata, content="")
    return {"path": path, "metadata": metadata, "content": ""}
```

Note: preserve any existing logic in `create_task` not shown here (e.g., template content). Read the current implementation first and integrate the new fields rather than wholesale-replacing.

- [ ] **Step 4: Apply the same pattern to `create_habit` and `create_goal`**

For `create_habit`: add optional `scheduled_at: Optional[str] = None` (an `"HH:MM"` string) and `duration_minutes: Optional[int] = None`, plus lifecycle fields.

For `create_goal`: add optional `start_date: Optional[str] = None`, plus lifecycle fields (`created`, `updated`, `completed`).

Add corresponding `test_create_habit_with_scheduled_at` and `test_create_goal_with_start_date` tests in `test_habit_operations.py` and `test_goal_operations.py` following the pattern from Step 1.

- [ ] **Step 5: Run all create_* tests**

```bash
python -m pytest tests/test_task_operations.py tests/test_habit_operations.py tests/test_goal_operations.py -v
```

Expected: all green (new tests pass, existing tests still pass because new params are optional).

- [ ] **Step 6: Commit**

```bash
cd ~/dev/mazkir
git add apps/vault-server/src/services/vault_service.py apps/vault-server/tests/test_task_operations.py apps/vault-server/tests/test_habit_operations.py apps/vault-server/tests/test_goal_operations.py
git commit -m "feat(vault-server): extend create_task/habit/goal with schedule + lifecycle fields"
```

---

## Task 8: Wire pre-hooks into `agent_service._execute_tool_inner`

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py`
- Modify: `apps/vault-server/tests/test_agent_service.py`

- [ ] **Step 1: Write failing test**

Append to `apps/vault-server/tests/test_agent_service.py`:

```python
def test_execute_tool_runs_pre_hooks_and_blocks_on_error(mock_services, tmp_path):
    """When a pre-hook returns an error, the handler is not called."""
    from src.services.hooks import register_hook, HOOK_REGISTRY
    from src.services.tool_response import err, ErrorCode

    # Register a blocking hook
    HOOK_REGISTRY.clear()
    register_hook(
        "always_block",
        lambda p, c: err(ErrorCode.SCHEMA_INVALID, "blocked by test"),
    )

    agent = AgentService(**mock_services)
    # Override one tool's pre_hooks to use our blocker, replacing its handler
    # to track invocations.
    handler_called = []
    agent.tools["list_tasks"]["pre_hooks"] = ["always_block"]
    agent.tools["list_tasks"]["handler"] = lambda p: handler_called.append(True) or {"data": []}

    result = agent._execute_tool_inner("list_tasks", {}, risk="safe")

    assert handler_called == []  # handler skipped
    assert result["ok"] is False
    assert result["error"]["code"] == "SCHEMA_INVALID"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_agent_service.py::test_execute_tool_runs_pre_hooks_and_blocks_on_error -v
```

Expected: FAIL because either `pre_hooks` is not respected or `_execute_tool_inner` doesn't return the response shape.

- [ ] **Step 3: Modify `agent_service.py` — register validate_schema and wire pre-hooks**

In `agent_service.py`:

a) Near top-of-file imports, add:
```python
from src.services.hooks import register_hook, run_pre_hooks
from src.services.hooks.validate_schema import validate_schema as _validate_schema_hook
from src.services.tool_response import ErrorCode, err, ok
```

b) Register the validate_schema hook once (in `__init__` after `self.tools = self._register_tools()`):
```python
# Register built-in hooks (idempotent — safe to call multiple times)
register_hook("validate_schema", _validate_schema_hook)
```

c) Update `_register_tools` so every entry has a `pre_hooks` list. Add `"pre_hooks": ["validate_schema"]` to every write or destructive tool entry, and `"pre_hooks": []` to safe (read) tools. This is a mechanical edit — touch each tool dict.

d) Modify `_execute_tool_inner` to run hooks. Locate the existing implementation (around line 1206) and refactor:

```python
def _execute_tool_inner(self, name: str, params: dict, risk: str) -> dict:
    tool = self.tools[name]
    ctx = {"tool": tool, "vault": self.vault, "memory": self.memory}

    # Pre-hooks
    pre_hooks = tool.get("pre_hooks", [])
    blocked = run_pre_hooks(pre_hooks, params, ctx)
    if blocked is not None:
        return blocked

    # Handler
    handler = tool["handler"]
    raw = handler(params)
    # Backwards-compat: legacy handlers may return plain dicts. Wrap them.
    if isinstance(raw, dict) and "ok" in raw and ("data" in raw or "error" in raw):
        return raw  # already normalized
    # Legacy success shape: extract _items if present, treat rest as data
    items = raw.pop("_items", []) if isinstance(raw, dict) else []
    return ok(raw if isinstance(raw, dict) else {"value": raw}, items=items)
```

- [ ] **Step 4: Run the new test**

```bash
python -m pytest tests/test_agent_service.py::test_execute_tool_runs_pre_hooks_and_blocks_on_error -v
```

Expected: PASS.

- [ ] **Step 5: Run the full agent_service test file**

```bash
python -m pytest tests/test_agent_service.py -v
```

Expected: all pass. Some existing tests may fail because they assert the old response shape. Fix any that break by either (a) updating them to assert the new shape, or (b) ensuring the legacy-wrap branch hits.

- [ ] **Step 6: Commit**

```bash
cd ~/dev/mazkir
git add apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_agent_service.py
git commit -m "feat(vault-server): wire pre-hooks into tool execution with validate_schema default"
```

---

## Task 9: Fix `complete_task` A1 dict-iteration bug

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py`
- Modify: `apps/vault-server/tests/test_agent_service.py`

- [ ] **Step 1: Write failing test**

Append to `apps/vault-server/tests/test_agent_service.py`:

```python
def test_complete_task_returns_real_values_not_placeholders(mock_services):
    """Regression: agent_service.py dict-unpacking iterated keys not values."""
    agent = AgentService(**mock_services)
    agent.vault.find_task_by_name.return_value = {
        "path": "40-tasks/active/x.md",
        "metadata": {"name": "X", "google_event_id": None},
    }
    agent.vault.complete_task.return_value = {
        "task_name": "X",
        "tokens_earned": 5,
        "archive_path": "40-tasks/archive/x.md",
    }

    result = agent._tool_complete_task({"task_name": "X"})

    # Old buggy result had string keys "task_name", "tokens_earned", etc.
    # Real values must come through.
    payload = result["data"] if "data" in result else result
    assert payload["task"] == "X"
    assert payload["tokens_earned"] == 5
    assert payload["archived_to"] == "40-tasks/archive/x.md"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_agent_service.py::test_complete_task_returns_real_values_not_placeholders -v
```

Expected: FAIL — assertions show literal strings `"task_name"`, etc.

- [ ] **Step 3: Fix the bug**

In `apps/vault-server/src/services/agent_service.py`, locate `_tool_complete_task` (around line 1637). Replace the buggy unpack:

```python
def _tool_complete_task(self, params: dict) -> dict:
    task = self.vault.find_task_by_name(params["task_name"])
    if not task:
        return err(
            ErrorCode.PATH_NOT_FOUND,
            f"No task found matching '{params['task_name']}'",
        )

    # FIXED: previously `name, tokens, archive_path = ...` which iterated dict keys.
    result = self.vault.complete_task(task["path"])
    name = result["task_name"]
    tokens = result["tokens_earned"]
    archive_path = result["archive_path"]

    if self.calendar and task["metadata"].get("google_event_id"):
        try:
            self.calendar.mark_event_complete(task["metadata"]["google_event_id"])
        except Exception as e:
            logger.warning(f"Calendar update failed: {e}")

    return ok(
        {
            "task": name,
            "tokens_earned": tokens,
            "archived_to": archive_path,
        },
        items=[archive_path],
    )
```

- [ ] **Step 4: Run the regression test**

```bash
python -m pytest tests/test_agent_service.py::test_complete_task_returns_real_values_not_placeholders -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/dev/mazkir
git add apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_agent_service.py
git commit -m "fix(vault-server): complete_task returns real task name and tokens, not placeholder strings"
```

---

## Task 10: Typed mutator — `update_task`

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py`
- Create: `apps/vault-server/tests/test_typed_mutators.py`

- [ ] **Step 1: Write failing tests**

Create `apps/vault-server/tests/test_typed_mutators.py`:

```python
"""Tests for the typed mutators update_task / update_habit / update_goal."""

import pytest
from unittest.mock import MagicMock

from src.services.agent_service import AgentService


@pytest.fixture
def agent(mock_services):
    return AgentService(**mock_services)


def test_update_task_appends_note_to_body(agent):
    agent.vault.list_active_tasks.return_value = [
        {"path": "40-tasks/active/migdal.md", "metadata": {"name": "Migdal docs"}}
    ]
    agent.vault.read_file.return_value = {
        "metadata": {"name": "Migdal docs", "priority": 2},
        "content": "Existing body text.\n",
    }

    result = agent._tool_update_task({
        "name": "Migdal docs",
        "append_note": "Got the missing-docs message from Migdal.",
    })

    assert result["ok"] is True
    # write_file should have been called with the appended body
    args, _ = agent.vault.write_file.call_args
    written_body = args[2]  # write_file(path, metadata, content)
    assert "Got the missing-docs message from Migdal." in written_body


def test_update_task_changes_priority_and_logs_history(agent):
    agent.vault.list_active_tasks.return_value = [
        {"path": "40-tasks/active/x.md", "metadata": {"name": "X", "priority": 2}}
    ]
    agent.vault.read_file.return_value = {
        "metadata": {"name": "X", "priority": 2},
        "content": "body\n",
    }
    agent.vault.append_history_line = lambda body, line: body + f"HIST:{line}\n"

    result = agent._tool_update_task({
        "name": "X",
        "priority": 4,
    })

    assert result["ok"] is True
    args, _ = agent.vault.write_file.call_args
    written_meta = args[1]
    written_body = args[2]
    assert written_meta["priority"] == 4
    assert "HIST:Priority changed: 2 → 4" in written_body


def test_update_task_returns_ambiguous_match_error(agent):
    agent.vault.list_active_tasks.return_value = [
        {"path": "40-tasks/active/migdal-insurance.md", "metadata": {"name": "Migdal insurance"}},
        {"path": "40-tasks/active/migdal-bank.md", "metadata": {"name": "Migdal bank"}},
    ]

    result = agent._tool_update_task({"name": "migdal", "priority": 4})

    assert result["ok"] is False
    assert result["error"]["code"] == "AMBIGUOUS_MATCH"


def test_update_task_returns_path_not_found_error(agent):
    agent.vault.list_active_tasks.return_value = []
    result = agent._tool_update_task({"name": "nonexistent", "priority": 4})
    assert result["ok"] is False
    assert result["error"]["code"] == "PATH_NOT_FOUND"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_typed_mutators.py -v
```

Expected: FAIL with `AttributeError: ... no attribute '_tool_update_task'`.

- [ ] **Step 3: Register the tool + handler**

In `_register_tools` in `agent_service.py`, add the entry (place between `create_goal` and `update_item`):

```python
"update_task": {
    "schema": {
        "name": "update_task",
        "description": (
            "Update fields on an existing task. Specify the task by fuzzy "
            "`name` match. Provide only the fields you want to change. "
            "`append_note` adds free-text to the task body with a timestamp."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Task name (fuzzy match)"},
                "priority": {"type": "integer", "minimum": 1, "maximum": 5},
                "status": {"type": "string", "enum": ["active", "blocked", "done"]},
                "category": {"type": "string"},
                "scheduled_at": {"type": ["string", "null"], "description": "ISO datetime"},
                "duration_minutes": {"type": ["integer", "null"]},
                "due_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                "due_soft": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                "append_note": {"type": "string"},
                "_confidence": {"type": "number"},
                "_reasoning": {"type": "string"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    "handler": self._tool_update_task,
    "risk": "write",
    "pre_hooks": ["validate_schema"],
},
```

- [ ] **Step 4: Implement the handler**

Add to `agent_service.py` (near other mutators, e.g. after `_tool_update_item`):

```python
def _tool_update_task(self, params: dict) -> dict:
    from src.services.resolver import resolve_item

    resolved = resolve_item("task", params["name"], self.vault)
    if not resolved["ok"]:
        return resolved

    path = resolved["data"]["path"]
    current = self.vault.read_file(path)
    meta = dict(current["metadata"])
    body = current["content"]

    history_lines: list[str] = []

    # Field changes
    field_map = [
        ("priority", "Priority"),
        ("status", "Status"),
        ("category", "Category"),
        ("scheduled_at", "Scheduled"),
        ("duration_minutes", "Duration (min)"),
        ("due_date", "Due"),
        ("due_soft", "Soft due"),
    ]
    for key, label in field_map:
        if key in params and params[key] != meta.get(key):
            history_lines.append(f"{label} changed: {meta.get(key)} → {params[key]}")
            meta[key] = params[key]

    # Append note to body (independent of frontmatter changes)
    if "append_note" in params and params["append_note"]:
        body = body.rstrip() + "\n\n" + params["append_note"].strip() + "\n"
        history_lines.append(f"Note appended: {params['append_note'][:60]}")

    # Bump updated
    from datetime import datetime
    today = datetime.now(self.vault.tz).strftime("%Y-%m-%d")
    if history_lines:
        meta["updated"] = today
        for line in history_lines:
            body = self.vault.append_history_line(body, line)

    self.vault.write_file(path, meta, body)

    return ok(
        {"path": path, "name": meta.get("name", ""), "changes": history_lines},
        items=[path],
    )
```

- [ ] **Step 5: Run the tests**

```bash
python -m pytest tests/test_typed_mutators.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
cd ~/dev/mazkir
git add apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_typed_mutators.py
git commit -m "feat(vault-server): add typed update_task mutator with resolver, history, append_note"
```

---

## Task 11: Typed mutator — `update_habit`

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py`
- Modify: `apps/vault-server/tests/test_typed_mutators.py`

- [ ] **Step 1: Write failing tests**

Append to `apps/vault-server/tests/test_typed_mutators.py`:

```python
def test_update_habit_changes_scheduled_at(agent):
    agent.vault.list_active_habits.return_value = [
        {"path": "20-habits/workout.md", "metadata": {"name": "Workout"}}
    ]
    agent.vault.read_file.return_value = {
        "metadata": {"name": "Workout", "scheduled_at": "07:00"},
        "content": "body\n",
    }
    agent.vault.append_history_line = lambda body, line: body + f"HIST:{line}\n"

    result = agent._tool_update_habit({
        "name": "Workout",
        "scheduled_at": "08:30",
    })

    assert result["ok"] is True
    args, _ = agent.vault.write_file.call_args
    assert args[1]["scheduled_at"] == "08:30"


def test_update_habit_returns_path_not_found(agent):
    agent.vault.list_active_habits.return_value = []
    result = agent._tool_update_habit({"name": "ghost", "scheduled_at": "09:00"})
    assert result["ok"] is False
    assert result["error"]["code"] == "PATH_NOT_FOUND"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_typed_mutators.py -k update_habit -v
```

Expected: FAIL (`AttributeError`).

- [ ] **Step 3: Register tool + handler**

In `_register_tools`, add:

```python
"update_habit": {
    "schema": {
        "name": "update_habit",
        "description": "Update fields on an existing habit. Specify by fuzzy `name`.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "frequency": {"type": "string", "enum": ["daily", "weekly", "monthly"]},
                "scheduled_at": {"type": ["string", "null"], "description": "HH:MM"},
                "duration_minutes": {"type": ["integer", "null"]},
                "tokens_per_completion": {"type": "integer"},
                "append_note": {"type": "string"},
                "_confidence": {"type": "number"},
                "_reasoning": {"type": "string"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    "handler": self._tool_update_habit,
    "risk": "write",
    "pre_hooks": ["validate_schema"],
},
```

Add handler (near `_tool_update_task`):

```python
def _tool_update_habit(self, params: dict) -> dict:
    from src.services.resolver import resolve_item

    resolved = resolve_item("habit", params["name"], self.vault)
    if not resolved["ok"]:
        return resolved

    path = resolved["data"]["path"]
    current = self.vault.read_file(path)
    meta = dict(current["metadata"])
    body = current["content"]

    history_lines: list[str] = []
    field_map = [
        ("frequency", "Frequency"),
        ("scheduled_at", "Scheduled at"),
        ("duration_minutes", "Duration (min)"),
        ("tokens_per_completion", "Tokens per completion"),
    ]
    for key, label in field_map:
        if key in params and params[key] != meta.get(key):
            history_lines.append(f"{label} changed: {meta.get(key)} → {params[key]}")
            meta[key] = params[key]

    if "append_note" in params and params["append_note"]:
        body = body.rstrip() + "\n\n" + params["append_note"].strip() + "\n"
        history_lines.append(f"Note appended: {params['append_note'][:60]}")

    from datetime import datetime
    today = datetime.now(self.vault.tz).strftime("%Y-%m-%d")
    if history_lines:
        meta["updated"] = today
        for line in history_lines:
            body = self.vault.append_history_line(body, line)

    self.vault.write_file(path, meta, body)
    return ok(
        {"path": path, "name": meta.get("name", ""), "changes": history_lines},
        items=[path],
    )
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_typed_mutators.py -k update_habit -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/dev/mazkir
git add apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_typed_mutators.py
git commit -m "feat(vault-server): add typed update_habit mutator"
```

---

## Task 12: Typed mutator — `update_goal`

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py`
- Modify: `apps/vault-server/tests/test_typed_mutators.py`

- [ ] **Step 1: Write failing tests**

Append to `apps/vault-server/tests/test_typed_mutators.py`:

```python
def test_update_goal_changes_progress(agent):
    agent.vault.list_active_goals.return_value = [
        {"path": "30-goals/2026/learn-ai.md", "metadata": {"name": "Learn AI"}}
    ]
    agent.vault.read_file.return_value = {
        "metadata": {"name": "Learn AI", "progress": 20},
        "content": "body\n",
    }
    agent.vault.append_history_line = lambda body, line: body + f"HIST:{line}\n"

    result = agent._tool_update_goal({"name": "Learn AI", "progress": 40})
    assert result["ok"] is True
    args, _ = agent.vault.write_file.call_args
    assert args[1]["progress"] == 40
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_typed_mutators.py::test_update_goal_changes_progress -v
```

Expected: FAIL.

- [ ] **Step 3: Register tool + handler**

In `_register_tools`, add:

```python
"update_goal": {
    "schema": {
        "name": "update_goal",
        "description": "Update fields on an existing goal. Specify by fuzzy `name`.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "status": {"type": "string", "enum": ["active", "paused", "completed", "archived"]},
                "progress": {"type": "integer", "minimum": 0, "maximum": 100},
                "priority": {"type": "integer", "minimum": 1, "maximum": 5},
                "start_date": {"type": ["string", "null"]},
                "target_date": {"type": ["string", "null"]},
                "append_note": {"type": "string"},
                "_confidence": {"type": "number"},
                "_reasoning": {"type": "string"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    "handler": self._tool_update_goal,
    "risk": "write",
    "pre_hooks": ["validate_schema"],
},
```

Add handler (mirroring `_tool_update_task`):

```python
def _tool_update_goal(self, params: dict) -> dict:
    from src.services.resolver import resolve_item

    resolved = resolve_item("goal", params["name"], self.vault)
    if not resolved["ok"]:
        return resolved

    path = resolved["data"]["path"]
    current = self.vault.read_file(path)
    meta = dict(current["metadata"])
    body = current["content"]

    history_lines: list[str] = []
    field_map = [
        ("status", "Status"),
        ("progress", "Progress"),
        ("priority", "Priority"),
        ("start_date", "Start date"),
        ("target_date", "Target date"),
    ]
    for key, label in field_map:
        if key in params and params[key] != meta.get(key):
            history_lines.append(f"{label} changed: {meta.get(key)} → {params[key]}")
            meta[key] = params[key]

    if "append_note" in params and params["append_note"]:
        body = body.rstrip() + "\n\n" + params["append_note"].strip() + "\n"
        history_lines.append(f"Note appended: {params['append_note'][:60]}")

    from datetime import datetime
    today = datetime.now(self.vault.tz).strftime("%Y-%m-%d")
    if history_lines:
        meta["updated"] = today
        for line in history_lines:
            body = self.vault.append_history_line(body, line)

    self.vault.write_file(path, meta, body)
    return ok(
        {"path": path, "name": meta.get("name", ""), "changes": history_lines},
        items=[path],
    )
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_typed_mutators.py -k update_goal -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/dev/mazkir
git add apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_typed_mutators.py
git commit -m "feat(vault-server): add typed update_goal mutator"
```

---

## Task 13: Retire `update_item`

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py`
- Modify: `apps/vault-server/tests/test_agent_service.py`

- [ ] **Step 1: Remove the tool registration**

In `agent_service.py` `_register_tools`, delete the entire `"update_item": { ... }` dict entry.

- [ ] **Step 2: Remove the handler**

Delete `_tool_update_item` method.

- [ ] **Step 3: Remove tests that reference `update_item`**

In `apps/vault-server/tests/test_agent_service.py`, search for `update_item` and delete any test functions that exercise it. Replace with a single assertion that the tool is gone:

```python
def test_update_item_tool_removed():
    """update_item retired in favor of typed update_task/_habit/_goal."""
    from src.services.agent_service import AgentService
    # Construct with minimal MagicMocks just to inspect the tool registry.
    from unittest.mock import MagicMock
    agent = AgentService(
        claude=MagicMock(), vault=MagicMock(), memory=MagicMock(),
        calendar=None, events=None,
    )
    assert "update_item" not in agent.tools
    assert "update_task" in agent.tools
    assert "update_habit" in agent.tools
    assert "update_goal" in agent.tools
```

If existing tests touch `update_item` from other angles (e.g. confidence-gate tests), update them to use `update_task` with a valid set of fields.

- [ ] **Step 4: Run the full agent_service test file**

```bash
python -m pytest tests/test_agent_service.py -v
```

Expected: all pass. Any failures point to remaining `update_item` references — fix by replacing with `update_task`/`update_habit`/`update_goal` calls in the test.

- [ ] **Step 5: Commit**

```bash
cd ~/dev/mazkir
git add apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_agent_service.py
git commit -m "refactor(vault-server): retire update_item, typed mutators are the only path"
```

---

## Task 14: Idempotency on `complete_task` and `complete_habit`

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py`
- Modify: `apps/vault-server/tests/test_agent_service.py`

- [ ] **Step 1: Write failing tests**

Append to `apps/vault-server/tests/test_agent_service.py`:

```python
def test_complete_task_idempotent_when_already_done(mock_services):
    """Re-completing a done task returns ALREADY_DONE, no double-credit."""
    agent = AgentService(**mock_services)
    agent.vault.find_task_by_name.return_value = {
        "path": "40-tasks/active/x.md",
        "metadata": {"name": "X", "status": "done"},
    }

    result = agent._tool_complete_task({"task_name": "X"})

    assert result["ok"] is False
    assert result["error"]["code"] == "ALREADY_DONE"
    # complete_task should NOT have been called
    agent.vault.complete_task.assert_not_called()


def test_complete_habit_idempotent_when_done_today(mock_services):
    from datetime import datetime
    agent = AgentService(**mock_services)
    today = datetime.now().strftime("%Y-%m-%d")
    agent.vault.list_active_habits.return_value = [
        {
            "path": "20-habits/workout.md",
            "metadata": {"name": "Workout", "last_completed": today, "streak": 5},
        }
    ]

    result = agent._tool_complete_habit({"habit_name": "Workout"})

    assert result["ok"] is False
    assert result["error"]["code"] == "ALREADY_DONE"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_agent_service.py -k "idempotent" -v
```

Expected: FAIL (current handlers don't check terminal state).

- [ ] **Step 3: Add idempotency check to `_tool_complete_task`**

Just after the `if not task:` block in `_tool_complete_task`:

```python
if task["metadata"].get("status") == "done":
    return err(
        ErrorCode.ALREADY_DONE,
        f"Task '{task['metadata'].get('name', '')}' is already done",
        details={"path": task["path"]},
    )
```

- [ ] **Step 4: Add idempotency check to `_tool_complete_habit`**

Locate `_tool_complete_habit`. After resolving the habit (the existing `if not habit:` block), add:

```python
from datetime import datetime
today = datetime.now(self.vault.tz).strftime("%Y-%m-%d")
if habit["metadata"].get("last_completed") == today:
    return err(
        ErrorCode.ALREADY_DONE,
        f"Habit '{habit['metadata'].get('name', '')}' already completed today",
        details={"path": habit["path"], "streak": habit["metadata"].get("streak", 0)},
    )
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_agent_service.py -k "idempotent" -v
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
cd ~/dev/mazkir
git add apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_agent_service.py
git commit -m "feat(vault-server): idempotent complete_task and complete_habit return ALREADY_DONE"
```

---

## Task 15: Idempotency on `archive_task`, `archive_goal`, `delete_task`

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py`
- Modify: `apps/vault-server/tests/test_agent_service.py`

- [ ] **Step 1: Write failing tests**

Append to `apps/vault-server/tests/test_agent_service.py`:

```python
def test_archive_goal_idempotent_when_already_archived(mock_services):
    agent = AgentService(**mock_services)
    agent.vault.find_goal_by_name.return_value = {
        "path": "30-goals/2026/x.md",
        "metadata": {"name": "X", "status": "archived"},
    }
    result = agent._tool_archive_goal({"goal_name": "X"})
    assert result["ok"] is False
    assert result["error"]["code"] == "ALREADY_DONE"


def test_delete_task_idempotent_when_target_absent(mock_services):
    agent = AgentService(**mock_services)
    agent.vault.find_task_by_name.return_value = None
    result = agent._tool_delete_task({"task_name": "ghost"})
    # find returns None → PATH_NOT_FOUND, not ALREADY_DONE (different semantic)
    assert result["ok"] is False
    assert result["error"]["code"] == "PATH_NOT_FOUND"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_agent_service.py -k "archive_goal_idempotent" -v
```

Expected: FAIL.

- [ ] **Step 3: Add idempotency check to `_tool_archive_goal`**

After the existing `if not goal:` block:

```python
if goal["metadata"].get("status") == "archived":
    return err(
        ErrorCode.ALREADY_DONE,
        f"Goal '{goal['metadata'].get('name', '')}' is already archived",
        details={"path": goal["path"]},
    )
```

- [ ] **Step 4: Ensure `_tool_delete_task` returns normalized error on missing target**

Modify the existing `if not task:` branch to use `err(...)`:

```python
if not task:
    return err(
        ErrorCode.PATH_NOT_FOUND,
        f"No task found matching '{params['task_name']}'",
    )
```

Apply the same to `_tool_archive_task`, `_tool_delete_habit`, `_tool_complete_task`, etc. for any branches still returning raw `{"error": "..."}` dicts.

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_agent_service.py -k "idempotent or PATH_NOT_FOUND" -v
python -m pytest tests/test_agent_service.py -v   # full pass to catch regressions
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
cd ~/dev/mazkir
git add apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_agent_service.py
git commit -m "feat(vault-server): idempotency and normalized errors on archive/delete handlers"
```

---

## Task 16: Migrate destructive handlers to use the resolver

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py`
- Modify: `apps/vault-server/tests/test_agent_service.py`

- [ ] **Step 1: Write failing test for `_tool_delete_task` resolver use**

Append to `apps/vault-server/tests/test_agent_service.py`:

```python
def test_delete_task_uses_resolver_for_fuzzy_match(mock_services):
    """delete_task should match 'walke' to 'Walk the dog' via fuzzy resolver."""
    agent = AgentService(**mock_services)
    agent.vault.list_active_tasks.return_value = [
        {"path": "40-tasks/active/walk-dog.md", "metadata": {"name": "Walk the dog"}}
    ]
    # Old find_task_by_name path should no longer be used; mock it to error
    agent.vault.find_task_by_name.side_effect = AssertionError("resolver should be used")

    result = agent._tool_delete_task({"task_name": "walke the dog"})
    assert result["ok"] is True
    agent.vault.delete_file.assert_called_once_with("40-tasks/active/walk-dog.md")


def test_delete_task_ambiguous_returns_candidates(mock_services):
    agent = AgentService(**mock_services)
    agent.vault.list_active_tasks.return_value = [
        {"path": "40-tasks/active/a.md", "metadata": {"name": "Project Alpha review"}},
        {"path": "40-tasks/active/b.md", "metadata": {"name": "Project Alpha summary"}},
    ]
    result = agent._tool_delete_task({"task_name": "alpha"})
    assert result["ok"] is False
    assert result["error"]["code"] == "AMBIGUOUS_MATCH"
    assert "candidates" in result["error"]["details"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_agent_service.py -k "delete_task_uses_resolver or ambiguous_returns_candidates" -v
```

Expected: FAIL (handler still calls `find_task_by_name`).

- [ ] **Step 3: Swap destructive handlers to the resolver**

For each of `_tool_delete_task`, `_tool_archive_task`, `_tool_delete_habit`, `_tool_archive_goal`, `_tool_complete_task`:

Replace the existing fuzzy lookup line:
```python
task = self.vault.find_task_by_name(params["task_name"])  # OLD
```
with:
```python
from src.services.resolver import resolve_item
resolved = resolve_item("task", params["task_name"], self.vault)
if not resolved["ok"]:
    return resolved
path = resolved["data"]["path"]
task = self.vault.read_file(path)
```

(Use `"habit"` / `"goal"` for the habit/goal handlers.)

Update the rest of the handler to use `path` directly and reference `task["metadata"]` for the name. The idempotency checks already added in Task 14/15 continue to apply.

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_agent_service.py -v
```

Expected: all pass, including the two new resolver-based tests.

- [ ] **Step 5: Commit**

```bash
cd ~/dev/mazkir
git add apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_agent_service.py
git commit -m "refactor(vault-server): destructive handlers use unified resolver with normalized errors"
```

---

## Task 17: Migrate safe (read) tools to normalized response shape

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py`
- Modify: `apps/vault-server/tests/test_agent_service.py`

- [ ] **Step 1: Write failing test**

Append to `apps/vault-server/tests/test_agent_service.py`:

```python
def test_list_tasks_returns_normalized_ok_shape(mock_services):
    agent = AgentService(**mock_services)
    agent.vault.list_active_tasks.return_value = [
        {"path": "40-tasks/active/x.md", "metadata": {"name": "X", "priority": 3}}
    ]
    result = agent._tool_list_tasks({})
    assert result["ok"] is True
    assert "data" in result
    assert "tasks" in result["data"]
    assert "_items" in result


def test_search_knowledge_returns_normalized_ok_shape(mock_services):
    agent = AgentService(**mock_services)
    agent.memory.search_knowledge.return_value = [{"path": "k.md", "name": "k", "tags": [], "score": 1}]
    result = agent._tool_search_knowledge({"query": "test"})
    assert result["ok"] is True
    assert "results" in result["data"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_agent_service.py -k "normalized_ok_shape" -v
```

Expected: FAIL — old handlers return plain dicts, the legacy-wrap in Task 8 normalizes them but assertions for the exact shape may still fail depending on wrapping.

- [ ] **Step 3: Update all safe-tool handlers**

For each of the read-only handlers (`_tool_list_tasks`, `_tool_list_habits`, `_tool_list_goals`, `_tool_get_daily`, `_tool_read_daily_section`, `_tool_get_tokens`, `_tool_search_knowledge`, `_tool_get_related`, `_tool_list_events`), wrap the existing return value with `ok(...)`:

```python
# before
def _tool_list_tasks(self, params: dict) -> dict:
    tasks = self.vault.list_active_tasks()
    return {"tasks": [...]}

# after
def _tool_list_tasks(self, params: dict) -> dict:
    tasks = self.vault.list_active_tasks()
    return ok({"tasks": [...]})
```

`_items` for read tools is `[]` (they don't mutate). No change to per-tool body except wrapping the dict.

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_agent_service.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd ~/dev/mazkir
git add apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_agent_service.py
git commit -m "refactor(vault-server): safe (read) tools return normalized ok() responses"
```

---

## Task 18: Normalize remaining write/destructive handlers

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py`

- [ ] **Step 1: Audit handlers still returning legacy shape**

```bash
cd ~/dev/mazkir/apps/vault-server
grep -n "def _tool_" src/services/agent_service.py | awk -F'def ' '{print $2}' | awk -F'(' '{print $1}'
```

For each handler not yet returning `ok(...)` or `err(...)`, update it:

- `_tool_create_task`, `_tool_create_habit`, `_tool_create_goal`: wrap success in `ok({...}, items=[result["path"]])`.
- `_tool_save_knowledge`: wrap.
- `_tool_attach_to_daily`, `_tool_edit_daily_section`: wrap.
- `_tool_attach_photo_to_event`, `_tool_create_event`, `_tool_update_event`: wrap. Note these already have `"error"` early returns — convert those to `err(ErrorCode.EXTERNAL_FAILURE, ...)` or appropriate code.
- `_tool_delete_*`, `_tool_archive_*`: already done in Tasks 14–16; double-check.

- [ ] **Step 2: Run the full test suite**

```bash
python -m pytest tests/ -v
```

Expected: all pass. Fix any test that asserted the legacy raw-dict shape.

- [ ] **Step 3: Commit**

```bash
cd ~/dev/mazkir
git add apps/vault-server/src/services/agent_service.py apps/vault-server/tests/
git commit -m "refactor(vault-server): all tool handlers return normalized ok()/err() responses"
```

---

## Task 19: Update the agent's system prompt to teach the response shape + error codes

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py`

- [ ] **Step 1: Extend `_build_system_prompt`**

Locate `_build_system_prompt` (around line 1120). Insert a new section between `## Tools` and `## Current vault state`:

```python
parts.extend([
    "",
    "## Tool responses",
    "Every tool returns either:",
    '  - success: {"ok": true, "data": {...}, "_items": [...]}',
    '  - error:   {"ok": false, "error": {"code": "...", "message": "...", "details": {...}}, "_items": []}',
    "",
    "Error codes (what to do):",
    "  - PATH_NOT_FOUND: target name/path doesn't match anything. Ask the user to clarify or rephrase.",
    "  - AMBIGUOUS_MATCH: multiple candidates close in score. Inspect details.candidates and either ask the user or pick one explicitly by path.",
    "  - SCHEMA_INVALID: your tool call had wrong fields or types. Re-emit with the correct schema.",
    "  - STATE_CONFLICT: target changed since you read it. Re-read and try again.",
    "  - ALREADY_DONE: the action is a no-op (item already in the desired state). Tell the user; do not retry.",
    "  - EXTERNAL_FAILURE: integration error (e.g. GCal). Mention the failure to the user; do not retry blindly.",
    "  - AUTH_REQUIRED: a permission step the user hasn't completed. Surface to the user.",
    "  - CANCELLED_BY_USER: confirmation flow returned no. Move on; do not retry the same action.",
])
```

- [ ] **Step 2: Run the agent_service tests to verify no regression**

```bash
python -m pytest tests/test_agent_service.py -v
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
cd ~/dev/mazkir
git add apps/vault-server/src/services/agent_service.py
git commit -m "feat(vault-server): teach agent the normalized response shape and error code semantics"
```

---

## Task 20: Final integration sweep and CLAUDE.md tool count update

**Files:**
- Modify: `CLAUDE.md`
- Test: full suite

- [ ] **Step 1: Run the entire vault-server test suite**

```bash
cd ~/dev/mazkir/apps/vault-server
source venv/bin/activate
python -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 2: Run the full repo test suite**

```bash
cd ~/dev/mazkir
npx turbo test
```

Expected: all packages pass. The telegram-bot and webapp tests should be unaffected by these backend changes.

- [ ] **Step 3: Update CLAUDE.md tool count and risk groupings**

In `CLAUDE.md`, locate "**Agent loop** (`AgentService`) replaces intent-parse-then-route: Claude tool-use with 26 registered tools…" and update:
- Tool count: 26 → number after this work (count entries in `_register_tools`)
- List drop `update_item`; add `update_task`, `update_habit`, `update_goal`
- Add a sentence on the new response shape: "All tool calls return `{ok, data|error, _items}`; agent reacts to `error.code` (PATH_NOT_FOUND, AMBIGUOUS_MATCH, SCHEMA_INVALID, STATE_CONFLICT, ALREADY_DONE, EXTERNAL_FAILURE, AUTH_REQUIRED, CANCELLED_BY_USER)."

In the "Agent tool risk levels" section:
- Remove `update_item` from the write list
- Add `update_task`, `update_habit`, `update_goal` to write list

- [ ] **Step 4: Sanity-start the server and smoke-test one tool**

```bash
cd ~/dev/mazkir/apps/vault-server
source venv/bin/activate
python -m uvicorn src.main:app --port 8000 &
sleep 2
curl -s http://localhost:8000/health
curl -s http://localhost:8000/tasks | head -50
kill %1
```

Expected: `/health` returns `{"status": "ok"}` and `/tasks` returns a JSON task list.

- [ ] **Step 5: Commit**

```bash
cd ~/dev/mazkir
git add CLAUDE.md
git commit -m "docs(claude-md): refresh tool count and risk groupings after P1 mutator refactor"
```

---

## Self-review notes (post-write checks)

This plan covers the following P1 spec elements:

| Spec item | Task(s) |
| --- | --- |
| ToolResponse shape `{ok, data|error, _items}` | 2, 17, 18 |
| Error code enum (8 codes) | 2, 19 |
| Hook framework (pre/post) | 3 |
| `validate_schema` pre-hook | 4 |
| Unified fuzzy resolver | 5 |
| Schema field additions (scheduled_at, duration_minutes, due_soft, lifecycle) | 7 |
| `append_history_line` helper | 6 |
| Typed mutators (update_task / _habit / _goal) | 10, 11, 12 |
| Retire `update_item` | 13 |
| Fix A1 `complete_task` dict-iter bug | 9 |
| Idempotency (ALREADY_DONE) | 14, 15 |
| Resolver usage in destructive handlers | 16 |
| Agent prompt teaching of new shape + codes | 19 |
| CLAUDE.md update | 20 |

**Out of scope** (verified): skill architecture (P2), confidence-gate UX (P2), post-hooks for calendar sync (P5), context optimization (P3), daily-tier tools (P4), media migration (P4), schema migration for existing vault files (separate effort).

**Open question to resolve during implementation:** if any existing vault file has a `status` value not in the new `update_task` enum (`"active", "blocked", "done"`), `validate_schema` will reject reads from the agent. Run `grep -r "^status:" memory/40-tasks/ memory/20-habits/ memory/30-goals/` first to verify the enums match real data. Widen the enum or fix the file before merging.
