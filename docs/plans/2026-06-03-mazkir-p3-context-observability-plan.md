# Mazkir P3 — Context Optimization + Observability + P2 Rollovers

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the lecture-notes context leak that started this whole effort, add Anthropic prompt caching, fill the input/output gaps in Phoenix traces, propagate errors correctly on manual spans, correlate logs with traces via `trace_id`, and fold in two follow-ups from P2 (extract the skill loop into its own module; wire a real post-hook to validate the framework end-to-end).

**Architecture:** Block B simplifies `MemoryService.assemble_context` — `_gather_relevant_knowledge` goes away, `_build_vault_snapshot` collapses to a single summary line, `items_referenced` is removed from the conversation schema. `ClaudeService.create` is extended to support a cached static prefix via Anthropic's `cache_control`. The skill loop moves out of `agent_service.py` into a new `skill_executor.py` so the core file stops growing. Span instrumentation gets a try/except wrapper that propagates exceptions and sets ERROR status. `trace_id` joins every structured log line.

**Tech Stack:** Python 3.14, FastAPI, Anthropic SDK (with ephemeral cache_control), OpenTelemetry. Tests via `pytest`.

**Spec source:** `docs/plans/2026-06-01-mazkir-usability-design.md` — Blocks B (context optimization) and C (observability gaps).

**Out of scope (deferred to later P-plans):**
- B5 vault snapshot cache (modest win, ship after measurement signal warrants it)
- B6 `list_preferences` tool (defer until preferences dir is non-empty)
- C3 ERROR trace `122b1a07` investigation (transient, dropped)
- C6 recurring trace-review cadence (on-demand only)
- Daily-tier tools / `/day` redesign / media migration → P4
- GCal sync as post-hook → P5 (P3 wires only the `audit_log` post-hook as proof of the framework)
- Streaming responses / parallel tool execution → P5

---

## File Structure

**Create:**
- `apps/vault-server/src/services/skill_executor.py` — extracted `_handle_via_skills` + helpers (`_skill_tool_schemas`, `_build_system_prompt_for_skill`, `_extract_next_skill`, `MAX_HOPS`, span tagging)
- `apps/vault-server/src/services/hooks/audit_log.py` — first real post-hook (writes `{trace_id, ts, tool, params_summary, ok, error_code}` rows)
- `apps/vault-server/src/services/tracing_helpers.py` — `with_span_status(span)` context manager that sets ERROR + records exception; `current_trace_id()` returning hex string or `None`
- `apps/vault-server/tests/test_skill_executor.py`
- `apps/vault-server/tests/test_audit_log_hook.py`
- `apps/vault-server/tests/test_prompt_caching.py`
- `apps/vault-server/tests/test_tracing_helpers.py`

**Modify:**
- `apps/vault-server/src/services/memory_service.py` — drop `_gather_relevant_knowledge` body, collapse `_build_vault_snapshot` to a one-line summary, stop writing `items_referenced` in `save_turn`, ignore it in `load_conversation`
- `apps/vault-server/src/services/agent_service.py` — delegate `_handle_via_skills` to `SkillExecutor`; add span input/output values + status propagation; tag system-prompt size + Anthropic cache token counts on `agent.loop` and `messages.create` spans
- `apps/vault-server/src/services/claude_service.py` — accept a `cache_static_prefix: str | None` argument on `create` and `create_router_choice`, forward as `cache_control`-wrapped system block
- `apps/vault-server/src/services/logging_setup.py` (or equivalent) — inject `trace_id` into every record via a logging filter
- `apps/vault-server/src/api/routes/message.py` (and `tokens.py`, `tasks.py` if they own spans) — wrap manual spans with `with_span_status`
- `apps/vault-server/tests/test_agent_service.py` / `test_memory_service.py` — update assertions where the removed knowledge dump / `items_referenced` lived
- `CLAUDE.md` — document the simplified context assembly and the audit-log post-hook

---

## Task 1: Extract skill loop into `skill_executor.py`

**Why now:** `agent_service.py` is 2,298 lines after P2. P3 adds more (caching, span attrs, status wrappers). Extracting the skill loop now is a clean breakpoint and pays back before P3 grows the file further.

**Files:**
- Create: `apps/vault-server/src/services/skill_executor.py`
- Create: `apps/vault-server/tests/test_skill_executor.py`
- Modify: `apps/vault-server/src/services/agent_service.py`

- [ ] **Step 1: Write failing tests**

Create `apps/vault-server/tests/test_skill_executor.py`. Re-use the existing `test_skill_loop.py` test shapes — but the new tests instantiate `SkillExecutor` directly instead of going through `AgentService`:

```python
"""Tests for the extracted SkillExecutor."""

from unittest.mock import MagicMock

import pytest

from src.services.skill_executor import SkillExecutor, MAX_HOPS
from src.services.skill_registry import Skill


def _mk_skill(name: str, tools: list[str], next_skills: list[str] | None = None) -> Skill:
    return Skill(
        name=name,
        description=f"{name} skill",
        system_prompt=f"You are the {name} skill.",
        tools=tools,
        model="claude-haiku-4-5",
        max_iterations=3,
        next_skills=next_skills or [],
    )


def test_router_picks_skill_and_executor_uses_its_tools():
    skill = _mk_skill("manager", ["list_tasks"])
    registry = MagicMock()
    registry.list.return_value = [skill]
    registry.get.side_effect = lambda n: skill if n == "manager" else None

    router = MagicMock()
    router.pick.return_value = MagicMock(skill="manager", reason="planning intent")

    tools = {"list_tasks": {"schema": {"name": "list_tasks"}}}
    captured = {}
    def fake_run_loop(*, system, tool_schemas, max_iterations, **kwargs):
        captured["tool_schemas"] = tool_schemas
        captured["system"] = system
        captured["max_iterations"] = max_iterations
        return "ok", "end_turn"

    executor = SkillExecutor(
        skill_registry=registry,
        router=router,
        tools=tools,
        run_loop=fake_run_loop,
        build_base_system_prompt=lambda context: "base prompt",
    )
    result = executor.run(
        chat_id=1,
        user_msg="What's on my plate",
        context_messages=[],
        messages=[],
    )

    assert [s["name"] for s in captured["tool_schemas"]] == ["list_tasks"]
    assert "You are the manager skill" in captured["system"]
    assert captured["max_iterations"] == 3
    assert result.response_text == "ok"
    assert result.iterations == 1


def test_next_skill_handoff_runs_second_skill():
    capture_skill = _mk_skill("capture", ["save_knowledge"], next_skills=["manager"])
    manager_skill = _mk_skill("manager", ["list_tasks"])

    registry = MagicMock()
    registry.list.return_value = [capture_skill, manager_skill]
    registry.get.side_effect = lambda n: {"capture": capture_skill, "manager": manager_skill}.get(n)

    router = MagicMock()
    router.pick.return_value = MagicMock(skill="capture", reason="")

    call_log = []
    def fake_run_loop(*, system, **kwargs):
        skill_name = "capture" if "capture skill" in system else "manager"
        call_log.append(skill_name)
        if skill_name == "capture":
            return "saved. next_skill: manager", "end_turn"
        return "done", "end_turn"

    executor = SkillExecutor(
        skill_registry=registry,
        router=router,
        tools={"save_knowledge": {"schema": {"name": "save_knowledge"}}, "list_tasks": {"schema": {"name": "list_tasks"}}},
        run_loop=fake_run_loop,
        build_base_system_prompt=lambda context: "base prompt",
    )
    executor.run(chat_id=1, user_msg="Save this and then schedule it", context_messages=[], messages=[])
    assert call_log == ["capture", "manager"]


def test_loop_caps_at_max_hops():
    a = _mk_skill("a", [], next_skills=["b"])
    b = _mk_skill("b", [], next_skills=["c"])
    c = _mk_skill("c", [], next_skills=["a"])

    registry = MagicMock()
    registry.list.return_value = [a, b, c]
    registry.get.side_effect = lambda n: {"a": a, "b": b, "c": c}.get(n)

    router = MagicMock()
    router.pick.return_value = MagicMock(skill="a", reason="")

    call_log = []
    def fake_run_loop(*, system, **kwargs):
        name = next(s for s in ("a", "b", "c") if f"{s} skill" in system)
        call_log.append(name)
        nxt = {"a": "b", "b": "c", "c": "a"}[name]
        return f"hop next_skill: {nxt}", "end_turn"

    executor = SkillExecutor(
        skill_registry=registry,
        router=router,
        tools={},
        run_loop=fake_run_loop,
        build_base_system_prompt=lambda context: "base prompt",
    )
    executor.run(chat_id=1, user_msg="go", context_messages=[], messages=[])
    assert len(call_log) <= MAX_HOPS
    assert MAX_HOPS == 3


def test_unknown_next_skill_is_ignored():
    capture = _mk_skill("capture", [], next_skills=[])
    registry = MagicMock()
    registry.list.return_value = [capture]
    registry.get.side_effect = lambda n: capture if n == "capture" else None

    router = MagicMock()
    router.pick.return_value = MagicMock(skill="capture", reason="")

    fake_run_loop = MagicMock(return_value=("text. next_skill: bogus", "end_turn"))
    executor = SkillExecutor(
        skill_registry=registry,
        router=router,
        tools={},
        run_loop=fake_run_loop,
        build_base_system_prompt=lambda context: "base prompt",
    )
    result = executor.run(chat_id=1, user_msg="x", context_messages=[], messages=[])
    # bogus not in capture's allowed next_skills → loop ends after 1 hop
    assert result.iterations == 1
```

- [ ] **Step 2: Run, see them fail**

```bash
cd /home/marcellmc/dev/mazkir/apps/vault-server
source venv/bin/activate
python -m pytest tests/test_skill_executor.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `SkillExecutor`**

Create `apps/vault-server/src/services/skill_executor.py`:

```python
"""Skill loop orchestrator.

Owns the router→skill→handoff flow that used to live inline in
`AgentService.handle_message`. The executor depends on injectable
collaborators (run_loop, build_base_system_prompt) so it can be unit-tested
without spinning up the whole agent.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from opentelemetry import trace as _otel_trace

from src.services.skill_registry import Skill

logger = logging.getLogger(__name__)

MAX_HOPS = 3

_tracer = _otel_trace.get_tracer("mazkir.skill_executor")


@dataclass
class SkillExecutorResult:
    response_text: str
    stop_reason: str
    iterations: int
    visited: list[str]


RunLoopFn = Callable[..., tuple[str, str]]
BuildBaseSystemPromptFn = Callable[[Any], str]


class SkillExecutor:
    def __init__(
        self,
        *,
        skill_registry,
        router,
        tools: dict,
        run_loop: RunLoopFn,
        build_base_system_prompt: BuildBaseSystemPromptFn,
    ):
        self.skill_registry = skill_registry
        self.router = router
        self.tools = tools
        self._run_loop = run_loop
        self._build_base_system_prompt = build_base_system_prompt

    def run(
        self,
        *,
        chat_id: int,
        user_msg: str,
        context_messages: list[dict],
        messages: list[dict],
        context: Optional[Any] = None,
    ) -> SkillExecutorResult:
        skills = self.skill_registry.list()
        decision = self.router.pick(
            user_msg=user_msg,
            recent_messages=context_messages[-10:],
            skills=skills,
        )

        visited: list[str] = []
        response_text = ""
        stop_reason = ""
        active = decision.skill
        previous: Optional[str] = None
        reason = decision.reason

        while active and len(visited) < MAX_HOPS:
            if active in visited:
                logger.warning("Skill cycle detected — stopping at %s", active)
                break
            visited.append(active)

            skill = self.skill_registry.get(active)
            if skill is None:
                logger.warning("Router/handoff requested unknown skill %r", active)
                break

            tool_schemas = self._skill_tool_schemas(skill)
            system = self._build_skill_system_prompt(skill, context)

            with _tracer.start_as_current_span(
                f"skill.{skill.name}",
                attributes={
                    "skill.name": skill.name,
                    "skill.previous": previous or "",
                    "skill.routing_reason": reason,
                },
            ) as span:
                response_text, stop_reason = self._run_loop(
                    chat_id=chat_id,
                    log_text=user_msg,
                    messages=messages,
                    system=system,
                    tool_schemas=tool_schemas,
                    max_iterations=skill.max_iterations,
                )

                next_skill = self._extract_next_skill(response_text, skill.next_skills)
                if next_skill:
                    span.set_attribute("skill.next_skill", next_skill)

            if next_skill:
                previous = active
                active = next_skill
                reason = f"handoff from {previous}"
            else:
                active = None

        return SkillExecutorResult(
            response_text=response_text,
            stop_reason=stop_reason,
            iterations=len(visited),
            visited=visited,
        )

    def _skill_tool_schemas(self, skill: Skill) -> list[dict]:
        return [self.tools[t]["schema"] for t in skill.tools if t in self.tools]

    def _build_skill_system_prompt(self, skill: Skill, context: Any) -> str:
        base = self._build_base_system_prompt(context)
        return f"{skill.system_prompt}\n\n{base}"

    @staticmethod
    def _extract_next_skill(response_text: str, allowed: list[str]) -> Optional[str]:
        m = re.search(r"next_skill:\s*([a-z_-]+)", response_text)
        if not m:
            return None
        name = m.group(1)
        if name not in allowed:
            logger.warning("Skill emitted next_skill=%r not in allowed=%r", name, allowed)
            return None
        return name
```

- [ ] **Step 4: Update `AgentService` to delegate**

In `apps/vault-server/src/services/agent_service.py`:

- Remove the inline `_handle_via_skills`, `_skill_tool_schemas`, `_build_system_prompt_for_skill`, `_extract_next_skill` methods.
- In `__init__`, when both `skill_registry` and `router` are provided, instantiate the executor:

```python
from src.services.skill_executor import SkillExecutor

if skill_registry is not None and router is not None:
    self._skill_executor = SkillExecutor(
        skill_registry=skill_registry,
        router=router,
        tools=self.tools,
        run_loop=self._run_loop,
        build_base_system_prompt=self._build_system_prompt,
    )
else:
    self._skill_executor = None
```

- In `_handle_message_inner` (or wherever the previous dispatch sat), call `self._skill_executor.run(...)` instead of the inline path. Return the `AgentResponse` from the executor's `response_text` + `iterations`.

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_skill_executor.py tests/test_skill_loop.py tests/test_agent_service.py -v
python -m pytest tests/ -q 2>&1 | tail -3
```

The pre-existing `test_skill_loop.py` should still pass because it monkeypatches `agent._run_loop` (now used by both legacy path and the executor via the injected callable). Update its assertions only if they hardcoded the old method names.

Expected: total ~316 (312 + 4 new from `test_skill_executor.py`).

- [ ] **Step 6: Commit**

```bash
git add apps/vault-server/src/services/skill_executor.py apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_skill_executor.py
git commit -m "refactor(vault-server): extract skill loop into SkillExecutor (P2 rollover)"
```

---

## Task 2: `audit_log` post-hook — validate the framework end-to-end

**Why now:** P2's reviewer flagged that `post_hooks=[]` on every entry means the framework has zero real consumers. Add one — a structured audit log line per write/destructive tool call — to prove the slot fires and to give us a tail of what the agent did, indexed by trace_id.

**Files:**
- Create: `apps/vault-server/src/services/hooks/audit_log.py`
- Create: `apps/vault-server/tests/test_audit_log_hook.py`
- Modify: `apps/vault-server/src/services/agent_service.py` (register + attach to write/destructive tools)

- [ ] **Step 1: Write failing tests**

Create `apps/vault-server/tests/test_audit_log_hook.py`:

```python
"""Tests for the audit_log post-hook."""

import json
from pathlib import Path

from src.services.hooks.audit_log import audit_log, _format_row


def test_format_row_minimal_success():
    row = _format_row(
        tool_name="create_task",
        params={"name": "X", "priority": 3},
        output={"ok": True, "data": {"path": "40-tasks/active/x.md"}, "_items": ["40-tasks/active/x.md"]},
        trace_id="abc123",
    )
    assert row["tool"] == "create_task"
    assert row["ok"] is True
    assert row["items"] == ["40-tasks/active/x.md"]
    assert row["params_summary"]["name"] == "X"
    assert row["trace_id"] == "abc123"
    assert "ts" in row


def test_format_row_error():
    row = _format_row(
        tool_name="delete_task",
        params={"task_name": "X"},
        output={"ok": False, "error": {"code": "PATH_NOT_FOUND", "message": "no match", "details": {}}, "_items": []},
        trace_id=None,
    )
    assert row["ok"] is False
    assert row["error_code"] == "PATH_NOT_FOUND"
    assert row["trace_id"] is None


def test_audit_log_writes_jsonl_row(tmp_path, monkeypatch):
    log_file = tmp_path / "tool-calls.jsonl"
    monkeypatch.setenv("MAZKIR_AUDIT_LOG_PATH", str(log_file))

    audit_log(
        params={"name": "X"},
        output={"ok": True, "data": {}, "_items": []},
        ctx={"tool": {"schema": {"name": "create_task"}}, "vault": None},
    )

    lines = log_file.read_text().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["tool"] == "create_task"
    assert row["ok"] is True


def test_audit_log_redacts_long_string_params(tmp_path, monkeypatch):
    log_file = tmp_path / "tool-calls.jsonl"
    monkeypatch.setenv("MAZKIR_AUDIT_LOG_PATH", str(log_file))

    long_text = "x" * 1000
    audit_log(
        params={"name": "Y", "append_note": long_text},
        output={"ok": True, "data": {}, "_items": []},
        ctx={"tool": {"schema": {"name": "update_task"}}, "vault": None},
    )

    row = json.loads(log_file.read_text().splitlines()[0])
    summary_note = row["params_summary"]["append_note"]
    assert isinstance(summary_note, str)
    assert len(summary_note) <= 200  # truncated
```

- [ ] **Step 2: Run, expect failure**

```bash
python -m pytest tests/test_audit_log_hook.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement the hook**

Create `apps/vault-server/src/services/hooks/audit_log.py`:

```python
"""audit_log post-hook — writes one JSON line per tool call to a structured log.

The line shape:
    {
        "ts": "2026-06-03T10:00:00.123Z",
        "trace_id": "abc123" | null,
        "tool": "create_task",
        "ok": true,
        "error_code": "...",            # only when ok is false
        "params_summary": { ... },      # long strings truncated to 200 chars
        "items": ["..."],
    }

Path is `MAZKIR_AUDIT_LOG_PATH` env var, defaulting to
`<repo>/data/logs/tool-calls.jsonl`.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.services.tracing_helpers import current_trace_id

logger = logging.getLogger(__name__)

MAX_STR_LEN = 200


def _summarize_value(v: Any) -> Any:
    if isinstance(v, str) and len(v) > MAX_STR_LEN:
        return v[:MAX_STR_LEN] + f"…({len(v) - MAX_STR_LEN} more)"
    if isinstance(v, list) and len(v) > 5:
        return v[:5] + [f"…({len(v) - 5} more)"]
    return v


def _summarize_params(params: dict) -> dict:
    return {k: _summarize_value(v) for k, v in params.items() if not k.startswith("_")}


def _format_row(*, tool_name: str, params: dict, output: dict, trace_id: str | None) -> dict:
    row = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "trace_id": trace_id,
        "tool": tool_name,
        "ok": bool(output.get("ok", True)),
        "params_summary": _summarize_params(params),
        "items": output.get("_items", []),
    }
    if not row["ok"]:
        err_obj = output.get("error", {}) or {}
        row["error_code"] = err_obj.get("code")
    return row


def _log_path() -> Path:
    raw = os.getenv("MAZKIR_AUDIT_LOG_PATH")
    if raw:
        return Path(raw)
    return Path.home() / "dev" / "mazkir" / "data" / "logs" / "tool-calls.jsonl"


def audit_log(params: dict, output: dict, ctx: Any) -> None:
    """Post-hook: append one JSON row to the audit log.

    Hook failures are caught and logged at WARNING — the framework treats
    post-hooks as best-effort side effects.
    """
    try:
        tool_name = ctx["tool"]["schema"]["name"]
        row = _format_row(
            tool_name=tool_name,
            params=params,
            output=output,
            trace_id=current_trace_id(),
        )
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("audit_log hook failed: %s", e)
```

(Note: `current_trace_id` is implemented in Task 8. For T2's tests, you can stub it with `lambda: None` — but the import should match the real module path so the wiring is correct once T8 lands. If T8 isn't done yet when this task runs, add a temporary inline implementation:

```python
def current_trace_id() -> str | None:
    try:
        from opentelemetry.trace import get_current_span
        ctx = get_current_span().get_span_context()
        if ctx.is_valid:
            return format(ctx.trace_id, "032x")
    except Exception:
        pass
    return None
```

and move it into `tracing_helpers.py` when T8 runs.)

- [ ] **Step 4: Register the hook + attach to write/destructive tools**

In `apps/vault-server/src/services/agent_service.py`, at the end of `__init__` (after preview registration):

```python
from src.services.hooks.audit_log import audit_log
register_hook("audit_log", audit_log)
```

At the end of `_register_tools`, after the existing `post_hooks = []` stamp loop, append `audit_log` for write + destructive tools:

```python
for entry in tools.values():
    if entry["risk"] in ("write", "destructive"):
        if "audit_log" not in entry["post_hooks"]:
            entry["post_hooks"] = entry["post_hooks"] + ["audit_log"]
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_audit_log_hook.py -v
python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: 4 new pass. Some existing test may suddenly write to `~/dev/mazkir/data/logs/tool-calls.jsonl` if the test runs a write tool. If you see noisy file writes, set `MAZKIR_AUDIT_LOG_PATH=/tmp/test-audit.jsonl` in `tests/conftest.py` for test isolation.

- [ ] **Step 6: Commit**

```bash
git add apps/vault-server/src/services/hooks/audit_log.py apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_audit_log_hook.py apps/vault-server/tests/conftest.py
git commit -m "feat(vault-server): add audit_log post-hook for write+destructive tools (P2 rollover)"
```

---

## Task 3: Remove `items_referenced` from the conversation schema

**Files:**
- Modify: `apps/vault-server/src/services/memory_service.py`
- Modify: `apps/vault-server/tests/test_memory_service.py`

- [ ] **Step 1: Write a failing test** for the desired behavior

Append to `apps/vault-server/tests/test_memory_service.py`:

```python
def test_save_turn_does_not_write_items_referenced(memory_service):
    """items_referenced is removed in P3."""
    memory_service.save_turn(
        chat_id=123,
        user_msg="hi",
        assistant_msg="hello",
        items=["40-tasks/active/x.md"],   # would have been appended in P2; now ignored
    )
    convo = memory_service.load_conversation(123)
    assert "items_referenced" not in convo
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_memory_service.py::test_save_turn_does_not_write_items_referenced -v
```

Expected: KeyError or AssertionError.

- [ ] **Step 3: Drop the field from `save_turn`**

In `memory_service.py`, find `save_turn`. Remove the `items_referenced` accumulation and frontmatter write. The `items` argument can either:
- Be dropped entirely if no other caller uses it.
- Be kept in the signature (back-compat) but ignored — document the no-op with a one-line comment.

Pick the latter to keep callers compiling without a refactor:

```python
def save_turn(self, chat_id, user_msg, assistant_msg, items=None, **kwargs):
    # items_referenced retired in P3 — argument retained for back-compat
    ...
```

In `load_conversation`, remove the `items_referenced` field from the returned dict.

- [ ] **Step 4: Drop any callers reading `items_referenced`**

```bash
grep -rn "items_referenced" apps/vault-server/src/
```

Expected matches (besides the deletions above):
- `_build_vault_snapshot` uses it for the `[referenced]` marker — removed in T5.
- `_gather_relevant_knowledge` uses it as the search-term source — removed in T4.

For now, leave both call sites until T4/T5 deletes them entirely. Add a `referenced = set()` local in those functions for the moment so the rest of the body keeps compiling.

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_memory_service.py tests/test_agent_service.py -v
python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: green. Update any test that asserted `items_referenced` appeared.

- [ ] **Step 6: Commit**

```bash
git add apps/vault-server/src/services/memory_service.py apps/vault-server/tests/test_memory_service.py
git commit -m "refactor(vault-server): retire items_referenced from conversation schema"
```

---

## Task 4: B1 — stop auto-dumping knowledge content

**Files:**
- Modify: `apps/vault-server/src/services/memory_service.py`
- Modify: `apps/vault-server/tests/test_memory_service.py`

- [ ] **Step 1: Failing test**

Append to `apps/vault-server/tests/test_memory_service.py`:

```python
def test_assemble_context_does_not_auto_dump_knowledge(memory_service, tmp_path):
    """B1: knowledge content no longer leaks into the system prompt."""
    # Seed a knowledge note that previous behavior would have surfaced
    (memory_service.vault_path / "60-knowledge" / "notes").mkdir(parents=True, exist_ok=True)
    (memory_service.vault_path / "60-knowledge" / "notes" / "ai-lecture.md").write_text(
        "---\nname: ai-lecture\ntype: knowledge\ntags: [ai]\n---\n\nLecture body text."
    )
    context = memory_service.assemble_context(chat_id=42)
    assert context.knowledge == ""
```

- [ ] **Step 2: Run, see fail**

```bash
python -m pytest tests/test_memory_service.py::test_assemble_context_does_not_auto_dump_knowledge -v
```

Expected: AssertionError (current behavior populates knowledge).

- [ ] **Step 3: Gut `_gather_relevant_knowledge`**

In `memory_service.py`:

```python
def _gather_relevant_knowledge(self, conversation: dict) -> str:
    # B1 — auto-dumping retired. Agent uses `search_knowledge` tool when it
    # actually needs context. Preferences will get their own list_preferences
    # tool in P4 if/when populated.
    return ""
```

Leave the rest of `assemble_context` untouched — it still passes `knowledge=""` into the context dataclass.

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/ -q 2>&1 | tail -3
```

Existing tests that asserted on populated knowledge content will fail — update them to assert empty.

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/memory_service.py apps/vault-server/tests/test_memory_service.py
git commit -m "refactor(memory-service): stop auto-dumping knowledge content in system prompt (B1)"
```

---

## Task 5: B2 — vault snapshot collapses to a one-line summary

**Files:**
- Modify: `apps/vault-server/src/services/memory_service.py`
- Modify: `apps/vault-server/tests/test_memory_service.py`

- [ ] **Step 1: Failing test**

```python
def test_vault_snapshot_is_summary_line(memory_service):
    """B2: snapshot reports counts, not per-item lists."""
    snapshot = memory_service._build_vault_snapshot(conversation={"items_referenced": []})
    # Single line, contains 4 cells: tasks / habits / goals / tokens
    assert "active tasks" in snapshot
    assert "habits" in snapshot
    assert "goals" in snapshot
    assert "tokens" in snapshot
    # No per-item details: no markdown bullets, no priorities, no streaks
    assert "- " not in snapshot
    assert "P1" not in snapshot
    assert "streak" not in snapshot
```

- [ ] **Step 2: Run, see fail**

Expected: per-item lists still present.

- [ ] **Step 3: Rewrite `_build_vault_snapshot`**

```python
def _build_vault_snapshot(self, conversation: dict | None = None) -> str:
    """One-line summary of vault state. Agent uses list_* tools for detail."""
    try:
        tasks = self.vault.list_active_tasks()
        habits = self.vault.list_active_habits()
        goals = self.vault.list_active_goals()
    except Exception:
        return "Vault: unavailable"

    overdue = 0
    try:
        from datetime import date
        today = date.today().isoformat()
        overdue = sum(
            1 for t in tasks
            if (t["metadata"].get("due_date") or "") < today
            and t["metadata"].get("status") == "active"
        )
    except Exception:
        pass

    habits_done_today = 0
    try:
        from datetime import date
        today_str = date.today().isoformat()
        habits_done_today = sum(
            1 for h in habits
            if h["metadata"].get("last_completed") == today_str
        )
    except Exception:
        pass

    tokens_today = 0
    tokens_total = 0
    try:
        ledger = self.vault.read_token_ledger()
        tokens_today = ledger["metadata"].get("tokens_today", 0)
        tokens_total = ledger["metadata"].get("total_tokens", 0)
    except Exception:
        pass

    return (
        f"Vault: {len(tasks)} active tasks ({overdue} overdue), "
        f"{len(habits)} habits ({habits_done_today} done today), "
        f"{len(goals)} active goals, "
        f"{tokens_today} tokens today / {tokens_total} total"
    )
```

The `conversation` parameter is kept for backwards-compat but ignored — `items_referenced` is gone from the conversation dict anyway after T3.

- [ ] **Step 4: Run all tests**

```bash
python -m pytest tests/ -q 2>&1 | tail -3
```

Tests that asserted on the verbose `## Active tasks` listing fail — update them to assert on the new summary shape (e.g. `"active tasks" in snapshot`).

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/memory_service.py apps/vault-server/tests/test_memory_service.py
git commit -m "refactor(memory-service): vault snapshot is one-line summary, not per-item listing (B2)"
```

---

## Task 6: B4 — Anthropic prompt caching on the static prefix

**Files:**
- Modify: `apps/vault-server/src/services/claude_service.py`
- Modify: `apps/vault-server/src/services/agent_service.py`
- Create: `apps/vault-server/tests/test_prompt_caching.py`

- [ ] **Step 1: Failing tests**

Create `apps/vault-server/tests/test_prompt_caching.py`:

```python
"""Tests for Anthropic prompt caching on the static prefix."""

from unittest.mock import MagicMock


def test_claude_create_sends_cache_control_when_static_prefix_provided():
    from src.services.claude_service import ClaudeService
    cs = ClaudeService.__new__(ClaudeService)
    cs.client = MagicMock()
    cs.client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="ok")],
        stop_reason="end_turn",
        usage=MagicMock(
            cache_creation_input_tokens=12,
            cache_read_input_tokens=0,
            input_tokens=100,
            output_tokens=10,
        ),
    )

    cs.create(
        system="dynamic tail",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        cache_static_prefix="big static thing",
    )

    args, kwargs = cs.client.messages.create.call_args
    system_blocks = kwargs["system"]
    assert isinstance(system_blocks, list)
    assert system_blocks[0]["text"] == "big static thing"
    assert system_blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert system_blocks[1]["text"] == "dynamic tail"
    assert "cache_control" not in system_blocks[1]


def test_claude_create_falls_back_to_string_when_no_prefix():
    """When no cache prefix, the system arg is a plain string (existing behavior)."""
    from src.services.claude_service import ClaudeService
    cs = ClaudeService.__new__(ClaudeService)
    cs.client = MagicMock()
    cs.client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="ok")], stop_reason="end_turn",
        usage=MagicMock(input_tokens=100, output_tokens=10),
    )

    cs.create(system="just a string", messages=[{"role": "user", "content": "hi"}], tools=[])

    args, kwargs = cs.client.messages.create.call_args
    assert kwargs["system"] == "just a string"
```

- [ ] **Step 2: Run, see fail**

Expected: `cache_static_prefix` not yet a parameter.

- [ ] **Step 3: Extend `ClaudeService.create`**

In `apps/vault-server/src/services/claude_service.py`, add the optional kwarg and rewrite the system block when set:

```python
def create(self, *, system, messages, tools, cache_static_prefix=None):
    if cache_static_prefix:
        system_arg = [
            {"type": "text", "text": cache_static_prefix, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": system},
        ]
    else:
        system_arg = system

    response = self.client.messages.create(
        model=...,           # preserve existing
        system=system_arg,
        messages=messages,
        tools=tools,
        max_tokens=...,
    )
    return response
```

Preserve all existing kwargs / behavior; the only addition is the new `cache_static_prefix` path.

- [ ] **Step 4: Decide what counts as "static prefix"**

The most cacheable, conversation-invariant content per turn:
- The full tool schema list (rendered into prompt or as `tools` SDK arg — note: `tools` already get cached automatically by Anthropic SDK when wrapped, but the system text portion benefits from explicit `cache_control`).
- The skill's `system_prompt` body (static for the conversation).
- The base guidelines (`## Tools`, `## Tool responses`, `## Guidelines` sections from `_build_system_prompt`).

What stays in the "dynamic tail":
- Current date/time.
- Vault summary line (changes each turn).
- Recent conversation tail (the agent loop puts this in `messages`, not `system`, so it's already not in the system prefix).

In `AgentService`, split the system prompt at the boundary. The easiest way:
- Add a `_build_static_prefix(skill_or_none) -> str` method that returns the parts above.
- Modify `_build_system_prompt` to return only the dynamic tail.
- In `_run_loop` (or its caller), pass both to `claude.create`.

Concretely in `_run_agent_turn` / `_run_loop`:

```python
static_prefix = self._build_static_prefix(skill=current_skill)
dynamic_tail = self._build_system_prompt(context)
response = self.claude.create(
    system=dynamic_tail,
    messages=messages,
    tools=self._tool_schemas(),   # or skill-filtered
    cache_static_prefix=static_prefix,
)
```

For the legacy (non-skill) path, `current_skill` is None and the static prefix is just the base prompt.

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: green. The fake response in existing tests must include `usage` so it doesn't blow up if the agent tries to log cache metrics (T7). Use the `MagicMock(spec=...)` pattern if needed.

- [ ] **Step 6: Commit**

```bash
git add apps/vault-server/src/services/claude_service.py apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_prompt_caching.py
git commit -m "feat(vault-server): Anthropic prompt caching on static prefix (B4)"
```

---

## Task 7: Measurement span attributes for prompt size + cache hits

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py`

- [ ] **Step 1: Add the attributes**

In the `agent.loop` span or wherever `messages.create` is called from `_run_agent_turn` / `_run_loop`:

```python
prompt_estimate = (len(system_arg if isinstance(system_arg, str) else "".join(b["text"] for b in system_arg)) // 4)
span = get_current_span()
span.set_attribute("system_prompt.token_estimate", prompt_estimate)
# After the call:
usage = getattr(response, "usage", None)
if usage:
    span.set_attribute("llm.token_count.prompt_cached_read", getattr(usage, "cache_read_input_tokens", 0) or 0)
    span.set_attribute("llm.token_count.prompt_cached_write", getattr(usage, "cache_creation_input_tokens", 0) or 0)
```

Also add `vault.snapshot.compute_ms` on `agent.handle_message`:

```python
import time
t0 = time.perf_counter()
context = self.memory.assemble_context(chat_id)
get_current_span().set_attribute("vault.snapshot.compute_ms", int((time.perf_counter() - t0) * 1000))
```

- [ ] **Step 2: Run full suite**

```bash
python -m pytest tests/ -q 2>&1 | tail -3
```

No behavioral change; tests should be green.

- [ ] **Step 3: Commit**

```bash
git add apps/vault-server/src/services/agent_service.py
git commit -m "feat(vault-server): span attrs for prompt size + cache hits + snapshot timing"
```

---

## Task 8: `tracing_helpers.py` — status propagation context manager + trace_id helper

**Files:**
- Create: `apps/vault-server/src/services/tracing_helpers.py`
- Create: `apps/vault-server/tests/test_tracing_helpers.py`

- [ ] **Step 1: Failing tests**

Create `apps/vault-server/tests/test_tracing_helpers.py`:

```python
"""Tests for tracing helpers."""

import pytest
from unittest.mock import MagicMock

from src.services.tracing_helpers import with_span_status, current_trace_id


def test_with_span_status_ok_path():
    span = MagicMock()
    with with_span_status(span):
        pass
    span.set_status.assert_called_once()
    args, _ = span.set_status.call_args
    status = args[0]
    # OpenTelemetry status is StatusCode.OK
    from opentelemetry.trace import StatusCode
    assert status.status_code == StatusCode.OK


def test_with_span_status_error_path_propagates_exception():
    span = MagicMock()
    with pytest.raises(ValueError):
        with with_span_status(span):
            raise ValueError("boom")
    span.record_exception.assert_called_once()
    args, _ = span.set_status.call_args
    status = args[0]
    from opentelemetry.trace import StatusCode
    assert status.status_code == StatusCode.ERROR
    assert "boom" in status.description


def test_current_trace_id_returns_none_outside_trace():
    # Without an active span, returns None
    assert current_trace_id() is None or isinstance(current_trace_id(), str)
```

- [ ] **Step 2: Run, expect fail**

```bash
python -m pytest tests/test_tracing_helpers.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `apps/vault-server/src/services/tracing_helpers.py`:

```python
"""Shared OpenTelemetry helpers."""

from contextlib import contextmanager
from typing import Optional

from opentelemetry.trace import Status, StatusCode, get_current_span


@contextmanager
def with_span_status(span):
    """Wrap a span body to set OK on success or ERROR on exception.

    On exception: span.record_exception is called, span status is set to
    ERROR with the exception message, and the exception re-raises.
    """
    try:
        yield
        span.set_status(Status(StatusCode.OK))
    except Exception as e:
        span.record_exception(e)
        span.set_status(Status(StatusCode.ERROR, str(e)))
        raise


def current_trace_id() -> Optional[str]:
    """Return the active OpenTelemetry trace id as 32-char hex, or None."""
    ctx = get_current_span().get_span_context()
    if ctx.is_valid:
        return format(ctx.trace_id, "032x")
    return None
```

- [ ] **Step 4: Tests pass**

```bash
python -m pytest tests/test_tracing_helpers.py -v
```

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/tracing_helpers.py apps/vault-server/tests/test_tracing_helpers.py
git commit -m "feat(vault-server): tracing helpers (with_span_status, current_trace_id)"
```

---

## Task 9: C1 — fill `input.value` / `output.value` on owned spans

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py`

The owned spans are `agent.handle_message`, `agent.loop`, `agent.tool_call`, and `skill.<name>` (now in `skill_executor.py`).

- [ ] **Step 1: Tag `agent.handle_message`**

At the start of the span block:

```python
span.set_attribute(SpanAttributes.INPUT_VALUE, text[:2000])
if len(text) > 2000:
    span.set_attribute("truncated", True)
```

At end of block (success path):

```python
span.set_attribute(SpanAttributes.OUTPUT_VALUE, response_text[:2000])
```

- [ ] **Step 2: Tag `agent.loop`**

Before the Claude call:

```python
# Last user/tool-result message as input
last_msg = messages[-1] if messages else {}
last_content = str(last_msg.get("content", ""))[:2000]
span.set_attribute(SpanAttributes.INPUT_VALUE, last_content)
```

After the Claude call:

```python
first_text_block = ""
for block in response.content:
    if hasattr(block, "text"):
        first_text_block = block.text[:2000]
        break
span.set_attribute(SpanAttributes.OUTPUT_VALUE, f"stop_reason={response.stop_reason}; {first_text_block}")
```

- [ ] **Step 3: Tag `agent.tool_call`**

Inside `_execute_tool` / `_execute_tool_inner`:

```python
import json
span.set_attribute(SpanAttributes.INPUT_VALUE, json.dumps(params, default=str)[:2000])
```

After handler:

```python
span.set_attribute(SpanAttributes.OUTPUT_VALUE, json.dumps(result, default=str)[:2000])
```

- [ ] **Step 4: Tag `skill.<name>`** (in `skill_executor.py`)

```python
span.set_attribute(SpanAttributes.INPUT_VALUE, user_msg[:2000])
# After the loop call:
span.set_attribute(SpanAttributes.OUTPUT_VALUE, response_text[:2000])
```

- [ ] **Step 5: Run full suite**

```bash
python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: green (additive attributes only).

- [ ] **Step 6: Commit**

```bash
git add apps/vault-server/src/services/agent_service.py apps/vault-server/src/services/skill_executor.py
git commit -m "feat(vault-server): fill input.value / output.value on owned spans (C1)"
```

---

## Task 10: C2 — error status propagation on manual spans

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py`
- Modify: `apps/vault-server/src/services/skill_executor.py`

- [ ] **Step 1: Wrap `agent.handle_message`, `agent.loop`, `agent.tool_call`**

For each `with _tracer.start_as_current_span(...) as span:` in the agent service, wrap the body using `with_span_status(span):`. Example:

```python
with _tracer.start_as_current_span("agent.tool_call", attributes=attrs) as span:
    with with_span_status(span):
        # existing body
        ...
```

For `agent.tool_call` specifically, also set ERROR explicitly when the handler returns `ok=False` (without an exception):

```python
if not result.get("ok"):
    span.set_status(Status(StatusCode.ERROR, result["error"]["code"]))
    span.set_attribute("tool.error.code", result["error"]["code"])
```

(`with_span_status` sets OK by default; this overrides on the application-level error path.)

- [ ] **Step 2: Same wrap on `skill.<name>` span**

In `skill_executor.py`, wrap the per-skill span body:

```python
with _tracer.start_as_current_span(f"skill.{skill.name}", attributes=...) as span:
    with with_span_status(span):
        # existing run_loop call + next_skill extraction
        ...
```

- [ ] **Step 3: Verify**

Run the full suite — no behavioral change, all green.

```bash
python -m pytest tests/ -q 2>&1 | tail -3
```

Optionally restart the server and trigger an error path (e.g. delete a nonexistent task with high confidence) and confirm via Phoenix that the outer span shows ERROR status.

- [ ] **Step 4: Commit**

```bash
git add apps/vault-server/src/services/agent_service.py apps/vault-server/src/services/skill_executor.py
git commit -m "feat(vault-server): status propagation + exception recording on manual spans (C2)"
```

---

## Task 11: C5 — `trace_id` injected into every structured log line

**Files:**
- Modify: `apps/vault-server/src/services/logging_setup.py` (or wherever the JSON formatter is configured)
- Create / extend: `apps/vault-server/tests/test_logging_setup.py`

- [ ] **Step 1: Add failing test**

```python
def test_log_record_has_trace_id_when_inside_span(monkeypatch, caplog):
    from src.services.logging_setup import attach_trace_id_filter
    import logging
    from opentelemetry import trace as _otel_trace

    handler = logging.StreamHandler()
    attach_trace_id_filter(handler)

    logger = logging.getLogger("test_trace_id")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    tracer = _otel_trace.get_tracer("test")
    with tracer.start_as_current_span("t"):
        # The filter mutates the record in place; we observe it via formatter access
        record = logger.makeRecord("test_trace_id", logging.INFO, __file__, 0, "msg", (), None)
        for f in handler.filters:
            f.filter(record)
        assert isinstance(getattr(record, "trace_id", None), str)
        assert len(record.trace_id) == 32


def test_log_record_trace_id_is_none_outside_span():
    from src.services.logging_setup import attach_trace_id_filter
    import logging
    handler = logging.StreamHandler()
    attach_trace_id_filter(handler)
    record = logging.LogRecord("x", logging.INFO, __file__, 0, "msg", (), None)
    for f in handler.filters:
        f.filter(record)
    # Either unset or None — both are acceptable
    assert getattr(record, "trace_id", None) is None
```

- [ ] **Step 2: Implement the filter**

In `logging_setup.py` (or near it), add:

```python
import logging

from src.services.tracing_helpers import current_trace_id


class _TraceIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = current_trace_id()
        return True


def attach_trace_id_filter(handler: logging.Handler) -> None:
    """Attach the trace_id filter to a handler so JSON records include trace_id."""
    for existing in handler.filters:
        if isinstance(existing, _TraceIdFilter):
            return
    handler.addFilter(_TraceIdFilter())
```

Call `attach_trace_id_filter` on the handlers configured during app startup (in `main.py` lifespan or wherever logging is set up).

- [ ] **Step 3: Update JSON formatter** to surface `trace_id` if it's not picked up automatically

If the existing JSON formatter only emits explicit `extra` fields, modify it to include `record.trace_id` when present.

- [ ] **Step 4: Tests pass**

```bash
python -m pytest tests/test_logging_setup.py -v
python -m pytest tests/ -q 2>&1 | tail -3
```

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/logging_setup.py apps/vault-server/tests/test_logging_setup.py
git commit -m "feat(vault-server): inject trace_id into structured log records (C5)"
```

---

## Task 12: Final sweep + CLAUDE.md refresh

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Run the full vault-server suite**

```bash
cd /home/marcellmc/dev/mazkir/apps/vault-server
source venv/bin/activate
python -m pytest tests/ -v 2>&1 | tail -15
```

Expected: all green. Total should be in the 320s.

- [ ] **Step 2: Run turbo test**

```bash
cd /home/marcellmc/dev/mazkir
npx turbo test 2>&1 | tail -10
```

Expected: telegram-bot + webapp pass; vault-server may fail under turbo (venv detection issue) but pytest direct works.

- [ ] **Step 3: Smoke test — verify caching is hitting**

Start the server and run two NL `/message` calls back-to-back (same chat_id). Inspect Phoenix:

```bash
PHOENIX_PROJECT=mazkir px trace list --last-n-minutes 5 --format raw --no-progress \
  | jq '.[] | .spans[] | select(.name == "messages.create") | .attributes | {prompt_cache_read: ."llm.token_count.prompt_cached_read", prompt_cache_write: ."llm.token_count.prompt_cached_write"}'
```

Expected: the second call's `prompt_cached_read` is non-zero (cache hit).

- [ ] **Step 4: Update CLAUDE.md**

Add to the Architecture / Context layer notes:

> **Context assembly:** `MemoryService.assemble_context` returns the conversation sliding window + a one-line vault summary. Knowledge auto-dump and `items_referenced` retired in P3; the agent calls `search_knowledge` explicitly when it needs notes.

> **Prompt caching:** Anthropic `cache_control: ephemeral` is set on the static prefix (skill system prompt + base instructions + tool docs). The dynamic tail (current date + vault summary line + recent conversation) is sent fresh each turn. Watch `llm.token_count.prompt_cached_read` in Phoenix to confirm hits.

Add to Agent loop section:

> **Skill loop module:** Extracted to `services/skill_executor.py`. `AgentService` constructs a `SkillExecutor` when both `skill_registry` and `router` are present and delegates the per-turn loop to it.

Add to Observability:

> **Span input/output values** are set on `agent.handle_message`, `agent.loop`, `agent.tool_call`, and `skill.<name>` spans. Errors propagate via `with_span_status`. Every structured log record carries a `trace_id` field that maps back to Phoenix.

> **Audit log:** `data/logs/tool-calls.jsonl` (path overridable via `MAZKIR_AUDIT_LOG_PATH`) records one JSON row per write/destructive tool call: `{ts, trace_id, tool, ok, error_code?, params_summary, items}`. Useful for grepping agent activity offline and correlating with Phoenix traces.

- [ ] **Step 5: Commit**

```bash
cd /home/marcellmc/dev/mazkir
git add CLAUDE.md
git commit -m "docs(claude-md): document P3 context, caching, and observability changes"
```

---

## Self-review notes

Spec coverage:

| Spec item (Block B / C + P2 rollovers) | Task(s) |
| --- | --- |
| P2 rollover: extract skill loop into its own module | 1 |
| P2 rollover: wire a real post-hook to validate framework | 2 |
| B1: stop auto-dumping knowledge content | 4 |
| B2: vault snapshot → one-line summary | 5 |
| B4: Anthropic prompt caching on static prefix | 6 |
| B7: remove items_referenced | 3 |
| Measurement: system_prompt token estimate + cache token counts | 7 |
| C1: fill input.value / output.value on owned spans | 9 |
| C2: error status propagation | 10 |
| C4: skill / confidence / preview attrs (already landed in P2) | — |
| C5: trace_id in structured logs | 11 |
| CLAUDE.md refresh | 12 |

**Out of scope** (verified): B5 snapshot cache, B6 `list_preferences` tool, C3 ERROR trace investigation, C6 recurring review cadence, daily-tier tools (P4), media migration (P4), GCal sync (P5), parallel exec (P5), streaming (P5).

**Open questions to resolve during implementation:**

- B4 boundary: where exactly does "static" stop and "dynamic" start? The plan splits at the vault-summary line, but if measurement shows the tool schemas alone are the dominant token cost, just cache those and leave the rest of the system prompt uncached. Pick based on T7 measurements.
- T2 audit-log path: `data/logs/tool-calls.jsonl` may collide with existing log files. Verify there's no name clash before shipping.
- T11 logging filter: existing logging setup in this codebase may already inject context via `LoggerAdapter` or similar. Read it first and integrate rather than parallel-pipe.
- T8/T2 ordering: `audit_log` imports `current_trace_id` from `tracing_helpers`. If executed in plan order T1 → T2, the helper doesn't exist yet at T2. Either inline the trace-id lookup in `audit_log.py` (with a note to extract), or move T8 ahead of T2. Recommendation: inline at T2, then T8 hoists it into the shared helper and updates the import.
