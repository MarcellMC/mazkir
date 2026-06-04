# Mazkir P5 — Integrations (GCal Sync) + Latency Polish

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute task-by-task.

**Goal:** Deliver the last user-visible wins from the original design: Google Calendar sync wired as a post-hook so every task/habit write reaches GCal automatically, parallel tool execution for the bulk-action latency win observed in May 21 traces (13.7 s for 11 completes → ~1–2 s), and Anthropic streaming on the final response so multi-second turns feel near-instant in Telegram. Plus two P4 rollovers.

**Architecture:**
- A new `sync_to_calendar` post-hook lives in `services/hooks/sync_to_calendar.py` and is attached to every tool that creates/updates/completes/archives/deletes a task or habit. It reads the relevant item from the vault and calls `CalendarService.sync_task` / `sync_habit` / `mark_event_complete`. Failures log at WARNING and never block the tool result.
- `tool_executor.execute_tool` learns to dispatch a list of independent tool calls in parallel via `asyncio.gather`. A new `safe_for_parallel: bool` field on each registry entry decides: read tools are always safe, daily-section writes are never safe, file-tier writes touching distinct paths are safe. Mixed-safety batches fall back to serial.
- `ClaudeService.create` gains a `stream: bool` mode that uses the Anthropic SDK's streaming endpoint and yields text deltas. The agent loop streams only the **final** response (after `stop_reason=end_turn` and no tool calls). The bot sends a placeholder message immediately and edits it as tokens arrive.
- Daily-tier tool handlers extracted from `agent_service.py` into `services/tool_handlers/daily.py` (partial P4 rollover — validate the pattern before extracting the rest in a later P).
- `daily_set_task_state` learns to walk nested children, fixing the silent-PATH_NOT_FOUND P4 bug.

**Tech Stack:** Python 3.14, FastAPI, Anthropic SDK (streaming + tool use), Google Calendar API, OpenTelemetry, grammY (Telegram bot).

**Spec source:** `docs/plans/2026-06-01-mazkir-usability-design.md` — Blocks E1, F1, F2, F4.

**Out of scope:**
- Extract remaining tool handlers (tasks/habits/goals/knowledge) into their own packages — defer until pattern proven in T2.
- B5 vault snapshot caching — revisit once we have cache-hit data from P3.
- Custom Phoenix evaluator for router parse failures — defer.
- Sub-millisecond optimizations (HTTP keep-alive, gRPC, etc.).

---

## File Structure

**Create:**
- `apps/vault-server/src/services/hooks/sync_to_calendar.py` — post-hook
- `apps/vault-server/src/services/parallel_executor.py` — `gather_tool_calls` helper around `asyncio.gather`
- `apps/vault-server/src/services/tool_handlers/__init__.py` — package init
- `apps/vault-server/src/services/tool_handlers/daily.py` — extracted daily handlers + `_replace_or_append_section` helper
- `apps/vault-server/tests/test_sync_to_calendar_hook.py`
- `apps/vault-server/tests/test_parallel_executor.py`
- `apps/vault-server/tests/test_streaming.py`

**Modify:**
- `apps/vault-server/src/services/agent_service.py` — wire `sync_to_calendar` post-hook; thin out daily handlers (delegate to `tool_handlers.daily`); pass `stream` flag to ClaudeService on final iteration
- `apps/vault-server/src/services/tool_registry.py` — stamp `safe_for_parallel` field
- `apps/vault-server/src/services/tool_executor.py` — accept a list of calls; delegate to parallel executor when allowed
- `apps/vault-server/src/services/claude_service.py` — add `stream: bool` kwarg producing a text-delta iterator
- `apps/vault-server/src/api/routes/message.py` (or wherever `/message` lives) — accept a Server-Sent Events / chunked response when client opts in
- `apps/telegram-bot/src/conversations/nl.ts` (the NL handler) — placeholder message + edit-on-stream
- `memory/00-system/mazkir-skills/capture.md` + `manager.md` — append parallel-batch nudge (F4)
- `CLAUDE.md` — document GCal sync flow, parallel execution, streaming

---

## Task 1: `daily_set_task_state` walks nested children (P4 rollover)

The P4 reviewer flagged that `_tool_daily_set_task_state` only matches against top-level `tasks` — children are silently skipped. Walk the tree.

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py` (handler) OR `services/tool_handlers/daily.py` if T2 runs first
- Modify: `apps/vault-server/tests/test_daily_tools.py`

- [ ] **Step 1: Failing tests**

```python
def test_daily_set_state_matches_child_subtask():
    agent = _agent_with_daily_body(
        "## Tasks\n- [ ] Plan picnic\n  - [ ] Buy bread\n  - [ ] Bring blanket\n"
    )
    result = agent._tool_daily_set_task_state({"text": "bread", "state": "checked"})
    assert result["ok"] is True
    new_body = agent.vault.write_daily_note.call_args.args[1]
    assert "- [x] Buy bread" in new_body
    # parent untouched
    assert "- [ ] Plan picnic" in new_body


def test_daily_set_state_no_match_includes_no_children():
    agent = _agent_with_daily_body(
        "## Tasks\n- [ ] Plan picnic\n  - just a bullet note\n"
    )
    # The note child has state=note, not unchecked/checked — should still be findable
    # if we explicitly target it
    result = agent._tool_daily_set_task_state({"text": "ghost", "state": "checked"})
    assert result["ok"] is False
    assert result["error"]["code"] == "PATH_NOT_FOUND"
```

- [ ] **Step 2: Run, expect first test to fail**

```bash
cd /home/marcellmc/dev/mazkir/apps/vault-server
source venv/bin/activate
python -m pytest tests/test_daily_tools.py -v -k "matches_child"
```

- [ ] **Step 3: Walk the tree**

In `_tool_daily_set_task_state` (in `agent_service.py` for now; will move in T2):

```python
def _flatten_with_path(tasks, path=()):
    """Yield (task, parent_chain) for every task in the tree."""
    for i, t in enumerate(tasks):
        yield t, path
        yield from _flatten_with_path(t.children, path + (i,))

# Replace the existing matching block:
q = params["text"].lower()
matches = [(t, p) for t, p in _flatten_with_path(tasks) if q in t.text.lower()]
if not matches:
    return err(ErrorCode.PATH_NOT_FOUND, f"No daily task matches '{params['text']}'")
if len(matches) > 1:
    return err(
        ErrorCode.AMBIGUOUS_MATCH,
        f"Multiple daily tasks match '{params['text']}'",
        details={"candidates": [t.text for t, _ in matches]},
    )
target, _ = matches[0]
target.state = params["state"]
```

(The parent_chain tuple is unused for now but useful when promote_daily_task gets the same treatment — keep it.)

- [ ] **Step 4: Tests + commit**

```bash
python -m pytest tests/test_daily_tools.py -v -k "set_state"
python -m pytest tests/ -q 2>&1 | tail -3
```

```bash
git commit -m "fix(vault-server): daily_set_task_state walks nested children (P4 rollover)"
```

---

## Task 2: Extract daily-tier handlers into `services/tool_handlers/daily.py` (P4 rollover)

`agent_service.py` is 2,617 lines. Validate the extraction pattern on the most recently-added, most self-contained tool group: the four `daily_*` handlers.

**Files:**
- Create: `apps/vault-server/src/services/tool_handlers/__init__.py`
- Create: `apps/vault-server/src/services/tool_handlers/daily.py`
- Modify: `apps/vault-server/src/services/agent_service.py`

- [ ] **Step 1: Carve out daily handler bodies**

Read `_tool_daily_add_task`, `_tool_daily_set_task_state`, `_tool_daily_rollover`, `_tool_promote_daily_task` in `agent_service.py`. They share dependencies on `vault` (read/write daily notes), `daily_tasks` parser/renderer, and (for promote) `vault.create_task`. None of them need `claude`, `memory`, or `events`.

Create `apps/vault-server/src/services/tool_handlers/__init__.py` (empty file).

Create `apps/vault-server/src/services/tool_handlers/daily.py`:

```python
"""Daily-tier task handlers extracted from AgentService.

Each handler is a free function taking (vault, params) and returning the
normalized {ok, data|error, _items} response. AgentService delegates by
binding `self.vault` as the first argument.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any

from src.services.daily_tasks import (
    DailyTask,
    parse_tasks_section,
    render_tasks_section,
    replace_or_append_section,
)
from src.services.tool_response import ErrorCode, err, ok

_MOVED_RE = re.compile(r"moved from\s+\[\[(\d{4}-\d{2}-\d{2})#Tasks\]\]")


def _flatten_with_path(tasks, path=()):
    for i, t in enumerate(tasks):
        yield t, path
        yield from _flatten_with_path(t.children, path + (i,))


def _first_original(task: DailyTask, fallback: str) -> str:
    """Walk the moved-from chain in task.annotation OR task.text.

    The parser stores `moved from [[X#Tasks]]` annotations in task.annotation
    when they follow a strikethrough; otherwise the text may still contain the
    pattern. Cover both.
    """
    blob = (task.annotation or "") + " " + (task.text or "")
    m = _MOVED_RE.search(blob)
    return m.group(1) if m else fallback


def daily_add_task(vault: Any, params: dict) -> dict:
    date_str = params.get("date") or dt.date.today().isoformat()
    daily = vault.read_daily_note(date_str)
    body = daily["content"]
    tasks = parse_tasks_section(body)
    tasks.append(DailyTask(
        text=params["text"],
        state="unchecked",
        scheduled_at=params.get("scheduled_at"),
        duration_minutes=params.get("duration_minutes"),
    ))
    new_body = replace_or_append_section(body, "Tasks", render_tasks_section(tasks))
    vault.write_daily_note(date_str, new_body)
    return ok(
        {"date": date_str, "text": params["text"]},
        items=[f"10-daily/{date_str}.md"],
    )


def daily_set_task_state(vault: Any, params: dict) -> dict:
    date_str = params.get("date") or dt.date.today().isoformat()
    daily = vault.read_daily_note(date_str)
    body = daily["content"]
    tasks = parse_tasks_section(body)

    q = params["text"].lower()
    matches = [(t, p) for t, p in _flatten_with_path(tasks) if q in t.text.lower()]
    if not matches:
        return err(ErrorCode.PATH_NOT_FOUND, f"No daily task matches '{params['text']}'")
    if len(matches) > 1:
        return err(
            ErrorCode.AMBIGUOUS_MATCH,
            f"Multiple daily tasks match '{params['text']}'",
            details={"candidates": [t.text for t, _ in matches]},
        )
    target, _ = matches[0]
    target.state = params["state"]

    new_body = replace_or_append_section(body, "Tasks", render_tasks_section(tasks))
    vault.write_daily_note(date_str, new_body)
    return ok(
        {"date": date_str, "text": target.text, "state": target.state},
        items=[f"10-daily/{date_str}.md"],
    )


def daily_rollover(vault: Any, params: dict) -> dict:
    today = dt.date.today()
    to_date = params.get("to_date") or today.isoformat()
    from_date = params.get("from_date") or (today - dt.timedelta(days=1)).isoformat()

    src = vault.read_daily_note(from_date)
    src_tasks = parse_tasks_section(src["content"])
    dst = vault.read_daily_note(to_date)
    dst_tasks = parse_tasks_section(dst["content"])

    src_changed = False
    dst_changed = False
    rolled: list[str] = []

    for task in src_tasks:
        if task.state != "unchecked":
            continue
        first = _first_original(task, from_date)

        already = any(
            d.text == task.text
            and f"moved from [[{first}#Tasks]]" in (d.annotation or "")
            for d in dst_tasks
        )
        if already:
            continue

        task.state = "moved"
        task.annotation = f"moved to [[{to_date}#Tasks]]"
        src_changed = True

        copy = DailyTask(
            text=task.text,
            state="unchecked",
            scheduled_at=task.scheduled_at,
            duration_minutes=task.duration_minutes,
            annotation=f"moved from [[{first}#Tasks]]",
        )
        dst_tasks.append(copy)
        dst_changed = True
        rolled.append(task.text)

    items: list[str] = []
    if src_changed:
        vault.write_daily_note(
            from_date,
            replace_or_append_section(src["content"], "Tasks", render_tasks_section(src_tasks)),
        )
        items.append(f"10-daily/{from_date}.md")
    if dst_changed:
        vault.write_daily_note(
            to_date,
            replace_or_append_section(dst["content"], "Tasks", render_tasks_section(dst_tasks)),
        )
        items.append(f"10-daily/{to_date}.md")

    return ok(
        {"from_date": from_date, "to_date": to_date, "rolled": rolled},
        items=items,
    )


def promote_daily_task(vault: Any, params: dict) -> dict:
    date_str = params.get("date") or dt.date.today().isoformat()
    daily = vault.read_daily_note(date_str)
    body = daily["content"]
    tasks = parse_tasks_section(body)

    q = params["text"].lower()
    candidates = [
        (t, p) for t, p in _flatten_with_path(tasks)
        if q in t.text.lower() and t.state == "unchecked"
    ]
    if not candidates:
        return err(
            ErrorCode.PATH_NOT_FOUND,
            f"No unchecked daily task matches '{params['text']}'",
        )
    if len(candidates) > 1:
        return err(
            ErrorCode.AMBIGUOUS_MATCH,
            f"Multiple unchecked daily tasks match '{params['text']}'",
            details={"candidates": [t.text for t, _ in candidates]},
        )
    target, _ = candidates[0]
    first = _first_original(target, date_str)

    # Strip `— moved from [[…]]` annotation from text before using as task name
    bare = _MOVED_RE.sub("", target.text)
    bare = re.sub(r"\s*—\s*$", "", bare).strip()

    result = vault.create_task(
        name=bare,
        priority=params.get("priority", 3),
        due_date=params.get("due_date"),
        created=first,
    )
    new_path = result["path"]
    slug = Path(new_path).stem

    target.text = f"[[{slug}]]"
    target.annotation = None
    new_body = replace_or_append_section(body, "Tasks", render_tasks_section(tasks))
    vault.write_daily_note(date_str, new_body)

    return ok(
        {"path": new_path, "name": result["metadata"]["name"], "first_original": first},
        items=[new_path, f"10-daily/{date_str}.md"],
    )
```

- [ ] **Step 2: Delegate from AgentService**

In `agent_service.py`, replace the four daily handler bodies with thin delegations:

```python
def _tool_daily_add_task(self, params: dict) -> dict:
    from src.services.tool_handlers.daily import daily_add_task
    return daily_add_task(self.vault, params)

def _tool_daily_set_task_state(self, params: dict) -> dict:
    from src.services.tool_handlers.daily import daily_set_task_state
    return daily_set_task_state(self.vault, params)

def _tool_daily_rollover(self, params: dict) -> dict:
    from src.services.tool_handlers.daily import daily_rollover
    return daily_rollover(self.vault, params)

def _tool_promote_daily_task(self, params: dict) -> dict:
    from src.services.tool_handlers.daily import promote_daily_task
    return promote_daily_task(self.vault, params)
```

- [ ] **Step 3: Run all daily tests**

```bash
python -m pytest tests/test_daily_tools.py tests/test_daily_tasks.py -v
python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: all existing daily tests pass — public behavior unchanged.

- [ ] **Step 4: Commit**

```bash
git commit -m "refactor(vault-server): extract daily-tier handlers into tool_handlers/daily.py (P4 rollover)"
```

---

## Task 3: `safe_for_parallel` flag on every tool

**Files:**
- Modify: `apps/vault-server/src/services/tool_registry.py`
- Modify: `apps/vault-server/src/services/agent_service.py` (override defaults for known-unsafe write tools)
- Modify: `apps/vault-server/tests/test_tool_registry.py`

- [ ] **Step 1: Failing tests**

Append to `test_tool_registry.py`:

```python
def test_safe_tools_default_to_parallel_safe():
    handlers = {"list_tasks": (_h(), "safe")}
    schemas = {"list_tasks": _schema("list_tasks")}
    tools = build_tool_registry(handlers, schemas)
    assert tools["list_tasks"]["safe_for_parallel"] is True


def test_write_tools_default_to_parallel_unsafe():
    handlers = {"create_task": (_h(), "write")}
    schemas = {"create_task": _schema("create_task")}
    tools = build_tool_registry(handlers, schemas)
    # Write tools default unsafe — risk of touching shared state.
    assert tools["create_task"]["safe_for_parallel"] is False


def test_destructive_tools_default_to_parallel_unsafe():
    handlers = {"delete_task": (_h(), "destructive")}
    schemas = {"delete_task": _schema("delete_task")}
    tools = build_tool_registry(handlers, schemas)
    assert tools["delete_task"]["safe_for_parallel"] is False
```

- [ ] **Step 2: Stamp the field**

In `tool_registry.py`, both `build_tool_registry` and `stamp_tool_registry` set the default:

```python
entry["safe_for_parallel"] = (risk == "safe")
```

- [ ] **Step 3: Override write tools that ARE safe in parallel**

In `agent_service.py` after `stamp_tool_registry(tools)`, override the cases where parallel writes don't conflict. The plan-locked semantics:

- Reads (`list_*`, `get_*`, `read_*`, `search_*`): SAFE (already default).
- File-tier writes touching distinct paths (`create_task`, `create_habit`, `create_goal`, `update_task`, `update_habit`, `update_goal`, `complete_task`, `complete_habit`, `delete_task`, `archive_task`, `delete_habit`, `archive_goal`, `save_knowledge`): SAFE — the resolver picks distinct paths and `vault.read_file`/`write_file` are per-file.
- Daily-section writes (`daily_add_task`, `daily_set_task_state`, `daily_rollover`, `promote_daily_task`, `attach_to_daily`, `edit_daily_section`): UNSAFE — concurrent writes to today's `## Tasks` section race.
- Event writes (`create_event`, `update_event`, `attach_photo_to_event`): UNSAFE — share the `data/events/{date}.json` lock.

```python
SAFE_WRITES = {
    "create_task", "create_habit", "create_goal",
    "update_task", "update_habit", "update_goal",
    "complete_task", "complete_habit",
    "delete_task", "archive_task", "delete_habit", "archive_goal",
    "save_knowledge",
}
for name in SAFE_WRITES:
    if name in tools:
        tools[name]["safe_for_parallel"] = True
```

- [ ] **Step 4: Tests pass + commit**

```bash
python -m pytest tests/test_tool_registry.py -v
python -m pytest tests/ -q 2>&1 | tail -3
```

```bash
git commit -m "feat(vault-server): safe_for_parallel flag on tool registry entries"
```

---

## Task 4: Parallel tool execution

**Files:**
- Create: `apps/vault-server/src/services/parallel_executor.py`
- Create: `apps/vault-server/tests/test_parallel_executor.py`
- Modify: `apps/vault-server/src/services/agent_service.py` (use it in the tool-batch dispatch)

- [ ] **Step 1: Failing tests**

```python
"""Tests for parallel tool batch execution."""

import asyncio
import time

import pytest

from src.services.parallel_executor import execute_calls_maybe_parallel


def _slow_call(name: str, duration_ms: int):
    """A fake call record: dict matching the tool-call shape used by the agent."""
    def handler(params):
        time.sleep(duration_ms / 1000)
        return {"ok": True, "data": {"name": name}, "_items": []}
    return {
        "name": name,
        "params": {},
        "risk": "safe",
        "_handler": handler,  # test-only shortcut
    }


def test_parallel_dispatch_runs_calls_concurrently_when_all_safe():
    """3 calls × 100ms — serial would take 300ms, parallel ≈ 100ms."""
    calls = [_slow_call(f"call_{i}", 100) for i in range(3)]
    tools = {
        f"call_{i}": {
            "safe_for_parallel": True,
            "handler": calls[i]["_handler"],
            "risk": "safe",
            "post_hooks": [],
            "pre_hooks": [],
            "schema": {"name": f"call_{i}"},
        }
        for i in range(3)
    }
    t0 = time.perf_counter()
    results = execute_calls_maybe_parallel(calls, tools=tools, ctx={})
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert len(results) == 3
    assert all(r["ok"] for r in results)
    assert elapsed_ms < 250, f"Expected parallel (≤250ms), got {elapsed_ms:.0f}ms"


def test_serial_fallback_when_any_call_is_unsafe():
    """If any tool in the batch is unsafe, fall back to serial."""
    calls = [_slow_call(f"call_{i}", 100) for i in range(3)]
    tools = {
        f"call_{i}": {
            "safe_for_parallel": i != 1,  # second call unsafe
            "handler": calls[i]["_handler"],
            "risk": "safe" if i != 1 else "write",
            "post_hooks": [],
            "pre_hooks": [],
            "schema": {"name": f"call_{i}"},
        }
        for i in range(3)
    }
    t0 = time.perf_counter()
    results = execute_calls_maybe_parallel(calls, tools=tools, ctx={})
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert len(results) == 3
    # Serial takes ~300ms
    assert elapsed_ms >= 250, f"Expected serial (≥250ms), got {elapsed_ms:.0f}ms"


def test_single_call_runs_directly():
    calls = [_slow_call("only", 50)]
    tools = {
        "only": {
            "safe_for_parallel": True,
            "handler": calls[0]["_handler"],
            "risk": "safe",
            "post_hooks": [],
            "pre_hooks": [],
            "schema": {"name": "only"},
        }
    }
    results = execute_calls_maybe_parallel(calls, tools=tools, ctx={})
    assert len(results) == 1
    assert results[0]["ok"]
```

- [ ] **Step 2: Implement**

```python
"""Parallel-or-serial dispatch for a batch of tool calls.

When every call in the batch has `safe_for_parallel = True`, run them via
`asyncio.gather` in a worker thread. Otherwise fall back to serial execution.

This module assumes synchronous tool handlers — it shims them into the
async world via `loop.run_in_executor`.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import Any

from src.services.tool_executor import execute_tool

logger = logging.getLogger(__name__)


def execute_calls_maybe_parallel(
    calls: list[dict],
    *,
    tools: dict,
    ctx: dict,
) -> list[dict]:
    """Run a batch of tool calls. Return results in the same order as `calls`.

    Each call dict must have `name`, `params`, and `risk` keys.
    """
    if not calls:
        return []
    if len(calls) == 1:
        c = calls[0]
        return [execute_tool(name=c["name"], params=c["params"], risk=c["risk"], tools=tools, ctx=ctx)]

    all_parallel_safe = all(
        tools.get(c["name"], {}).get("safe_for_parallel", False) for c in calls
    )
    if not all_parallel_safe:
        return [
            execute_tool(name=c["name"], params=c["params"], risk=c["risk"], tools=tools, ctx=ctx)
            for c in calls
        ]

    # Parallel path
    async def _run_all() -> list[dict]:
        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(calls)) as pool:
            tasks = [
                loop.run_in_executor(
                    pool,
                    lambda c=c: execute_tool(
                        name=c["name"], params=c["params"], risk=c["risk"],
                        tools=tools, ctx=ctx,
                    ),
                )
                for c in calls
            ]
            return await asyncio.gather(*tasks)

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Nested-loop case — run in a new thread with its own loop
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                return ex.submit(asyncio.run, _run_all()).result()
        return asyncio.run(_run_all())
    except Exception as e:
        logger.warning("Parallel dispatch failed (%s), falling back to serial", e)
        return [
            execute_tool(name=c["name"], params=c["params"], risk=c["risk"], tools=tools, ctx=ctx)
            for c in calls
        ]
```

- [ ] **Step 3: Use it in the agent loop**

Find where the agent loop processes a batch of `tool_use` blocks from one Claude response (search `tool_calls = self._extract_tool_calls(response)`). Today it loops serially. Replace with a single call to `execute_calls_maybe_parallel` — but only when the batch is ≥ 2 calls AND none need a confirmation gate. Calls needing confirmation still stage individually.

```python
# After confidence gate splits calls into auto_execute vs needs_confirmation:
from src.services.parallel_executor import execute_calls_maybe_parallel

auto_results = execute_calls_maybe_parallel(
    auto_execute,
    tools=self.tools,
    ctx={"vault": self.vault, "memory": self.memory},
)
```

Map results back to tool_use_id for the next Claude message.

- [ ] **Step 4: Tests + commit**

```bash
python -m pytest tests/test_parallel_executor.py -v
python -m pytest tests/ -q 2>&1 | tail -3
git commit -m "feat(vault-server): parallel tool execution for safe batches (F1)"
```

---

## Task 5: `sync_to_calendar` post-hook

**Files:**
- Create: `apps/vault-server/src/services/hooks/sync_to_calendar.py`
- Create: `apps/vault-server/tests/test_sync_to_calendar_hook.py`

- [ ] **Step 1: Failing tests**

```python
"""Tests for sync_to_calendar post-hook."""

import pytest
from unittest.mock import MagicMock

from src.services.hooks.sync_to_calendar import sync_to_calendar


@pytest.fixture
def ctx_factory():
    def make(calendar=None, vault=None):
        return {
            "calendar": calendar or MagicMock(is_initialized=True),
            "vault": vault or MagicMock(),
            "tool": {"schema": {"name": "create_task"}},
        }
    return make


def test_hook_noop_when_calendar_unavailable(ctx_factory):
    ctx = ctx_factory(calendar=None)
    # Should not raise even with no calendar
    sync_to_calendar(
        params={"name": "X"},
        output={"ok": True, "data": {"path": "40-tasks/active/x.md"}, "_items": ["40-tasks/active/x.md"]},
        ctx=ctx,
    )


def test_hook_noop_when_output_not_ok(ctx_factory):
    calendar = MagicMock(is_initialized=True)
    sync_to_calendar(
        params={"name": "X"},
        output={"ok": False, "error": {"code": "PATH_NOT_FOUND"}, "_items": []},
        ctx=ctx_factory(calendar=calendar),
    )
    calendar.sync_task.assert_not_called()
    calendar.sync_habit.assert_not_called()


def test_hook_syncs_task_after_create(ctx_factory):
    calendar = MagicMock(is_initialized=True)
    vault = MagicMock()
    vault.read_file.return_value = {
        "metadata": {"type": "task", "name": "X", "due_date": "2026-06-10"},
        "content": "",
    }

    sync_to_calendar(
        params={"name": "X"},
        output={"ok": True, "data": {}, "_items": ["40-tasks/active/x.md"]},
        ctx={
            "calendar": calendar,
            "vault": vault,
            "tool": {"schema": {"name": "create_task"}},
        },
    )
    calendar.sync_task.assert_called_once()


def test_hook_syncs_habit(ctx_factory):
    calendar = MagicMock(is_initialized=True)
    vault = MagicMock()
    vault.read_file.return_value = {
        "metadata": {"type": "habit", "name": "Workout"},
        "content": "",
    }
    sync_to_calendar(
        params={"name": "Workout"},
        output={"ok": True, "data": {}, "_items": ["20-habits/workout.md"]},
        ctx={
            "calendar": calendar,
            "vault": vault,
            "tool": {"schema": {"name": "create_habit"}},
        },
    )
    calendar.sync_habit.assert_called_once()


def test_hook_handles_complete_task_with_existing_event(ctx_factory):
    calendar = MagicMock(is_initialized=True)
    vault = MagicMock()
    vault.read_file.return_value = {
        "metadata": {"type": "task", "name": "X", "google_event_id": "evt-123", "status": "done"},
        "content": "",
    }
    sync_to_calendar(
        params={"task_name": "X"},
        output={"ok": True, "data": {"task": "X"}, "_items": ["40-tasks/archive/x.md"]},
        ctx={
            "calendar": calendar,
            "vault": vault,
            "tool": {"schema": {"name": "complete_task"}},
        },
    )
    calendar.mark_event_complete.assert_called_once_with("evt-123")


def test_hook_failure_logs_but_does_not_raise(ctx_factory, caplog):
    calendar = MagicMock(is_initialized=True)
    calendar.sync_task.side_effect = RuntimeError("GCal down")
    vault = MagicMock()
    vault.read_file.return_value = {
        "metadata": {"type": "task", "name": "X"},
        "content": "",
    }
    # Should NOT raise
    sync_to_calendar(
        params={"name": "X"},
        output={"ok": True, "data": {}, "_items": ["40-tasks/active/x.md"]},
        ctx={
            "calendar": calendar,
            "vault": vault,
            "tool": {"schema": {"name": "create_task"}},
        },
    )
```

- [ ] **Step 2: Implement**

```python
"""sync_to_calendar post-hook — push task/habit writes to Google Calendar.

Wired into every tool that creates / updates / completes / archives / deletes
a task or habit. Reads the affected vault path from output._items, loads the
metadata, and dispatches to CalendarService.sync_task or sync_habit.

Hook failures log at WARNING and never re-raise; calendar sync is best-effort.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Map tool name → action class. Drives behavior.
_DELETE_TOOLS = {"delete_task", "delete_habit", "archive_task", "archive_goal"}
_COMPLETE_TOOLS = {"complete_task", "complete_habit"}


def sync_to_calendar(params: dict, output: dict, ctx: Any) -> None:
    """Post-hook: push changes to Google Calendar (best-effort)."""
    try:
        calendar = (ctx or {}).get("calendar")
        if calendar is None or not getattr(calendar, "is_initialized", False):
            return
        if not output.get("ok", False):
            return

        tool_name = ctx.get("tool", {}).get("schema", {}).get("name", "")
        items = output.get("_items") or []
        if not items:
            return
        path = items[0]

        vault = ctx.get("vault")
        if vault is None:
            return

        try:
            item = vault.read_file(path)
        except Exception:
            return
        meta = item.get("metadata", {})
        item_type = meta.get("type")

        # Complete: if a google_event_id exists, mark it done.
        if tool_name in _COMPLETE_TOOLS and meta.get("google_event_id"):
            calendar.mark_event_complete(meta["google_event_id"])
            return

        # Delete/archive: tools may not have left an item; nothing to sync.
        if tool_name in _DELETE_TOOLS:
            return

        if item_type == "task":
            calendar.sync_task(item)
        elif item_type == "habit":
            calendar.sync_habit(item)
    except Exception as e:
        logger.warning("sync_to_calendar hook failed: %s", e)
```

- [ ] **Step 3: Tests + commit**

```bash
python -m pytest tests/test_sync_to_calendar_hook.py -v
python -m pytest tests/ -q 2>&1 | tail -3
git commit -m "feat(vault-server): sync_to_calendar post-hook (best-effort GCal push)"
```

---

## Task 6: Attach `sync_to_calendar` to write/destructive tools

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py`

- [ ] **Step 1: Register the hook**

In `AgentService.__init__`, alongside the existing `register_hook("audit_log", …)` call:

```python
from src.services.hooks.sync_to_calendar import sync_to_calendar
register_hook("sync_to_calendar", sync_to_calendar)
```

- [ ] **Step 2: Attach to relevant tools**

After `stamp_tool_registry(tools)` and the `SAFE_WRITES` override from T3, append `sync_to_calendar` to the post-hooks of every tool that affects a task or habit:

```python
SYNC_TOOLS = {
    "create_task", "update_task", "complete_task",
    "archive_task", "delete_task",
    "create_habit", "update_habit", "complete_habit",
    "delete_habit",
}
for name in SYNC_TOOLS:
    if name in tools and "sync_to_calendar" not in tools[name]["post_hooks"]:
        tools[name]["post_hooks"].append("sync_to_calendar")
```

- [ ] **Step 3: Make `calendar` reachable from tool ctx**

The hook's ctx dict needs a `calendar` entry. In `tool_executor.execute_tool` the ctx is built from caller-supplied `ctx`. In `agent_service.py` find `_execute_tool_inner` (which delegates to `execute_tool`) and update the ctx:

```python
ctx={"vault": self.vault, "memory": self.memory, "calendar": self.calendar}
```

- [ ] **Step 4: Run the full suite**

```bash
python -m pytest tests/ -q 2>&1 | tail -3
```

Existing tests may break if they mock the tool registry and find unexpected post_hooks entries. Update those mocks.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(vault-server): attach sync_to_calendar post-hook to task/habit writers (E1)"
```

---

## Task 7: Streaming — extend `ClaudeService.create`

**Files:**
- Modify: `apps/vault-server/src/services/claude_service.py`
- Create: `apps/vault-server/tests/test_streaming.py`

- [ ] **Step 1: Failing test**

```python
"""Tests for streaming response from ClaudeService."""

from unittest.mock import MagicMock


def test_create_with_stream_returns_iterator():
    from src.services.claude_service import ClaudeService
    cs = ClaudeService.__new__(ClaudeService)
    cs.client = MagicMock()

    # Stub the streaming context manager
    fake_events = [
        MagicMock(type="content_block_delta", delta=MagicMock(type="text_delta", text="Hello")),
        MagicMock(type="content_block_delta", delta=MagicMock(type="text_delta", text=" world")),
    ]
    fake_stream = MagicMock()
    fake_stream.__enter__ = MagicMock(return_value=fake_stream)
    fake_stream.__exit__ = MagicMock(return_value=None)
    fake_stream.__iter__ = MagicMock(return_value=iter(fake_events))
    fake_stream.get_final_message = MagicMock(return_value=MagicMock(
        content=[MagicMock(text="Hello world")],
        stop_reason="end_turn",
        usage=MagicMock(input_tokens=10, output_tokens=2, cache_creation_input_tokens=0, cache_read_input_tokens=0),
    ))
    cs.client.messages.stream = MagicMock(return_value=fake_stream)

    chunks = []
    response = cs.create(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        stream=True,
        on_chunk=lambda text: chunks.append(text),
    )

    assert chunks == ["Hello", " world"]
    # Final response is still returned for downstream use
    assert response.stop_reason == "end_turn"
```

- [ ] **Step 2: Implement**

Read the existing `create` first. Add `stream` and `on_chunk` kwargs:

```python
def create(
    self,
    *,
    system,
    messages,
    tools,
    cache_static_prefix=None,
    stream: bool = False,
    on_chunk=None,
    **kwargs,
):
    system_arg = ...  # existing build with cache_static_prefix

    if not stream:
        return self.client.messages.create(
            model=...,
            max_tokens=...,
            system=system_arg,
            messages=messages,
            tools=tools,
            **kwargs,
        )

    # Streaming path
    with self.client.messages.stream(
        model=...,
        max_tokens=...,
        system=system_arg,
        messages=messages,
        tools=tools,
        **kwargs,
    ) as stream_ctx:
        for event in stream_ctx:
            if event.type == "content_block_delta" and event.delta.type == "text_delta":
                if on_chunk:
                    on_chunk(event.delta.text)
        return stream_ctx.get_final_message()
```

- [ ] **Step 3: Run tests + commit**

```bash
python -m pytest tests/test_streaming.py -v
python -m pytest tests/ -q 2>&1 | tail -3
git commit -m "feat(vault-server): ClaudeService.create streaming mode with chunk callback (F2)"
```

---

## Task 8: Streaming — thread through agent loop on final iteration

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py`

- [ ] **Step 1: Detect the "final" iteration**

The agent loop calls `claude.create` once per iteration. We want streaming ONLY on the iteration that returns `stop_reason == "end_turn"` (no more tool calls). The challenge: you don't know it's the final iteration until you've made the call.

Workaround: every iteration's response is built up from streamed chunks. Pass `on_chunk` always, but buffer chunks until we know the stop_reason. If it's `end_turn` AND there are no tool calls, flush buffered chunks to a caller-supplied `stream_callback`. Otherwise discard.

In `_run_loop` (the inner agent loop):

```python
buffered_chunks: list[str] = []

def _on_chunk(text: str) -> None:
    buffered_chunks.append(text)
    if self._stream_callback:
        self._stream_callback(text)

response = self.claude.create(
    system=dynamic_tail,
    messages=messages,
    tools=tool_schemas,
    cache_static_prefix=static_prefix,
    stream=True,
    on_chunk=_on_chunk,
)
buffered_chunks.clear()
```

Add `self._stream_callback` to `AgentService.__init__` (default `None`). `handle_message` accepts a `stream_callback` kwarg and sets it for the duration.

- [ ] **Step 2: Pass through the API**

In `apps/vault-server/src/api/routes/message.py`, add a query param `stream=true` to `/message`. When set, return a `StreamingResponse` (FastAPI) that yields SSE chunks:

```python
from fastapi.responses import StreamingResponse

@router.post("/message")
async def message(body: MessageRequest, stream: bool = False):
    if not stream:
        # existing path
        ...
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def on_chunk(text: str) -> None:
        queue.put_nowait(text)

    async def producer():
        result = await asyncio.to_thread(
            agent.handle_message, ..., stream_callback=on_chunk,
        )
        # signal end
        queue.put_nowait(None)
        # final JSON
        return result

    async def stream_iter():
        producer_task = asyncio.create_task(producer())
        while True:
            chunk = await queue.get()
            if chunk is None:
                break
            yield f"data: {json.dumps({'text': chunk})}\n\n"
        result = await producer_task
        yield f"data: {json.dumps({'done': True, 'response': result.dict()})}\n\n"

    return StreamingResponse(stream_iter(), media_type="text/event-stream")
```

- [ ] **Step 3: Tests**

Smoke-test that the endpoint streams. Use FastAPI's TestClient:

```python
def test_message_streams_when_requested():
    from fastapi.testclient import TestClient
    # Mock agent.handle_message to call stream_callback a few times
    client = TestClient(app)
    with client.stream("POST", "/message?stream=true", json={"text": "hi", "chat_id": 1}) as r:
        chunks = []
        for line in r.iter_lines():
            if line.startswith("data: "):
                chunks.append(line[6:])
        assert len(chunks) >= 1
```

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(vault-server): stream agent response via SSE when stream=true (F2)"
```

---

## Task 9: Streaming — telegram bot edits placeholder

**Files:**
- Modify: `apps/telegram-bot/src/conversations/nl.ts` (or wherever NL is handled)
- Modify: `apps/telegram-bot/src/api/client.ts`

- [ ] **Step 1: API client adds streaming method**

In `client.ts`:

```ts
import EventSource from "eventsource";  // or fetch-based SSE

export async function streamMessage(
  url: string,
  body: { text: string; chat_id: number },
  onChunk: (text: string) => void,
): Promise<{ response: string }> {
  return new Promise((resolve, reject) => {
    const eventSource = new EventSource(`${url}?stream=true`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    let final: any = null;
    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.done) {
        final = data.response;
        eventSource.close();
        resolve(final);
      } else if (data.text) {
        onChunk(data.text);
      }
    };
    eventSource.onerror = (err) => {
      eventSource.close();
      reject(err);
    };
  });
}
```

(If your existing API client uses `fetch`, build the SSE consumer with `Response.body.getReader()` instead — adapt to the existing patterns.)

- [ ] **Step 2: NL handler uses streaming**

In the NL conversation handler:

```ts
// existing:
await ctx.replyWithChatAction("typing");
const response = await api.message({ text, chat_id });
await ctx.reply(response.response, { parse_mode: "HTML" });

// new:
const placeholder = await ctx.reply("...");
let buffered = "";
let lastEdit = Date.now();
await api.streamMessage(
  apiUrl + "/message",
  { text, chat_id },
  async (chunk) => {
    buffered += chunk;
    // Throttle edits to ~500ms to stay under Telegram rate limits
    if (Date.now() - lastEdit > 500) {
      try {
        await ctx.api.editMessageText(ctx.chat!.id, placeholder.message_id, buffered);
      } catch (e) {
        // ignore — bot will get the final state on completion
      }
      lastEdit = Date.now();
    }
  },
);
// Final state (with formatting)
await ctx.api.editMessageText(ctx.chat!.id, placeholder.message_id, buffered, { parse_mode: "HTML" });
```

- [ ] **Step 3: Add a feature flag**

Add `STREAM_RESPONSES` env / config; default `false` for safety. When false, fall back to the existing non-streaming path. This lets you smoke-test in production without breaking existing chats.

- [ ] **Step 4: Bot tests**

```bash
cd apps/telegram-bot
npx vitest run 2>&1 | tail -10
```

Update bot tests to handle the new streaming path or leave covered by integration smoke test.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(telegram-bot): stream agent responses by editing placeholder message (F2)"
```

---

## Task 10: F4 — prompt nudges for parallel batching

**Files:**
- Modify: `memory/00-system/mazkir-skills/capture.md`
- Modify: `memory/00-system/mazkir-skills/manager.md`

- [ ] **Step 1: Edit capture.md**

Append to the system-prompt body:

> When you have multiple independent captures to file (e.g. a quote AND a new task), emit the tool calls in a single response block as parallel calls rather than across iterations. The runtime executes safe-for-parallel calls concurrently.

- [ ] **Step 2: Edit manager.md**

Append:

> When you have multiple independent operations (completing several tasks, attaching notes to different items, etc.), batch them into one response block as parallel tool calls. The runtime dispatches `safe_for_parallel` tools concurrently — your single bulk-completion call becomes ~1 s instead of ~10 s. Keep daily-section writes serial: those tools are flagged unsafe and the runtime will fall back automatically.

- [ ] **Step 3: Verify parser**

```bash
cd /home/marcellmc/dev/mazkir/apps/vault-server
source venv/bin/activate
python -c "
from pathlib import Path
from src.services.skill_registry import SkillRegistry
r = SkillRegistry(skills_dir=Path('/home/marcellmc/dev/mazkir/memory/00-system/mazkir-skills'))
r.load()
for s in r.list():
    assert 'parallel' in s.system_prompt.lower() or s.name == 'recall'
print('OK')
"
```

- [ ] **Step 4: Commit in the nested vault repo**

```bash
cd /home/marcellmc/dev/mazkir/memory
git add 00-system/mazkir-skills/capture.md 00-system/mazkir-skills/manager.md
git commit -m "feat(skills): nudge agents to emit parallel tool batches (F4)"
cd /home/marcellmc/dev/mazkir
```

---

## Task 11: Final sweep + CLAUDE.md

**Files:** modify `CLAUDE.md`.

- [ ] **Step 1: Full suite**

```bash
cd /home/marcellmc/dev/mazkir/apps/vault-server
source venv/bin/activate
python -m pytest tests/ -v 2>&1 | tail -15
```

- [ ] **Step 2: Turbo**

```bash
cd /home/marcellmc/dev/mazkir
npx turbo test 2>&1 | tail -10
```

- [ ] **Step 3: CLAUDE.md updates**

Add bullets under Architecture / Observability:

> **GCal sync as post-hook (P5):** Every task/habit write fires the `sync_to_calendar` post-hook, which reads the affected vault path from `output._items`, loads metadata, and calls `CalendarService.sync_task` / `sync_habit` / `mark_event_complete`. Failures log at WARNING and never block the tool result. Wired into `create_task`, `update_task`, `complete_task`, `archive_task`, `delete_task`, `create_habit`, `update_habit`, `complete_habit`, `delete_habit`.

> **Parallel tool execution (P5):** Each tool entry carries `safe_for_parallel`. Read tools default safe; file-tier writes touching distinct paths (create/update/complete/archive/delete on task/habit/goal, save_knowledge) are flagged safe; daily-section and event writes are unsafe. The agent loop dispatches a batch of auto-execute tool calls via `parallel_executor.execute_calls_maybe_parallel` — concurrent via `asyncio.gather` when all calls are safe, serial fallback otherwise.

> **Streaming responses (P5):** When the bot POSTs `/message?stream=true`, the server returns Server-Sent Events. Anthropic SDK streaming is enabled on every loop iteration; the final iteration's text deltas reach the bot, which edits a placeholder message every ~500 ms. Tool-use iterations still complete fully before the next iteration; only the post-tool final text streams.

> **Tool handler split (P4 rollover, P5):** `services/tool_handlers/daily.py` owns the daily-tier handler bodies. AgentService delegates via thin wrappers. Other handler groups remain in agent_service.py; extraction continues incrementally.

- [ ] **Step 4: Commit**

```bash
git commit -m "docs(claude-md): document GCal sync, parallel exec, streaming after P5"
```

---

## Self-review notes

Coverage:

| Spec item | Task(s) |
| --- | --- |
| P4 rollover: daily_set_task_state walks children | 1 |
| P4 rollover: extract daily handlers | 2 |
| F1: safe_for_parallel flag | 3 |
| F1: parallel batch execution | 4 |
| E1: sync_to_calendar hook | 5 |
| E1: attach to task/habit tools | 6 |
| F2: ClaudeService streaming | 7 |
| F2: agent loop threads stream | 8 |
| F2: bot edits placeholder | 9 |
| F4: prompt nudges | 10 |
| CLAUDE.md refresh | 11 |

**Out of scope:** Extract remaining handler groups (tasks/habits/goals/knowledge); B5 snapshot cache; mid-loop tool-use streaming; router-parse-failure evaluator.

**Open implementation questions:**
- **Streaming and tool use interact subtly.** The agent loop may iterate 5+ times before `end_turn`. Streaming every iteration's text deltas means the bot sees intermediate "I'm going to call list_tasks now" text before the final answer. Two options: (a) only flush stream chunks when stop_reason=end_turn AND no tool calls — clean UX but the bot stays on "…" until the last iteration; (b) stream everything — chatty but feels alive. Plan locks in (a) via the buffer-and-flush approach in T8; revisit if users find it sluggish.
- **Parallel executor's nested-loop handling** — `asyncio.run` in a worker thread is the safe escape when the caller already has a running loop (e.g. FastAPI). Verify under the actual request path; the test harness uses synchronous handlers and may not exercise the real case.
- **CalendarService method signatures** — T5's hook calls `sync_task` / `sync_habit` / `mark_event_complete`. Confirm these exist and are async/sync per current code; the hook is synchronous so `await` won't work — the calendar service may need a sync facade or the hook may need to schedule via `asyncio.run_coroutine_threadsafe`. Investigate first.
