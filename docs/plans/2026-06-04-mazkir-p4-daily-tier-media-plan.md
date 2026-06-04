# Mazkir P4 — Daily-Tier Tasks + `/day` Redesign + Media in Vault

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute this plan task-by-task.

**Goal:** Deliver the user-visible workflow change: two-tier tasks (daily checkboxes default, promote to file when multi-day), the redesigned `/day` as a time-based feed, and media files moved inside the Obsidian vault so attachments render in Obsidian. Plus the P3 rollover to split `agent_service.py` further.

**Architecture:**
- A new `DailyTasksService` owns parsing and writing the `## Tasks` section of daily notes (checkboxes, optional inline `HH:MM` and `(NNm)` annotations, nested children).
- Four new tools (`daily_add_task`, `daily_set_task_state`, `daily_rollover`, `promote_daily_task`) wire into the existing tool registry + capture/manager skills.
- `list_tasks` returns a grouped object instead of a flat list.
- `/day` becomes a schedule + notes feed — no standalone Tasks/Habits sections — and respects `GOOGLE_CALENDAR_INCLUDE`.
- Media moves to `memory/00-system/media/{date}/`; embeds switch to Obsidian wikilinks; migration script rewrites existing daily-note image refs.
- `_register_tools` and `_execute_tool` extracted from `agent_service.py` into `tool_registry.py` and `tool_executor.py` (P3 rollover).

**Tech Stack:** Python 3.14, FastAPI, OpenTelemetry. Telegram bot updates for the `/day` formatter.

**Spec source:** `docs/plans/2026-06-01-mazkir-usability-design.md` — Blocks D1, D2 (daily-tier tools), E2 (media), and the P3 rollover.

**Out of scope (P5):** GCal sync as `sync_to_calendar` post-hook, parallel tool execution, streaming responses, B5 snapshot caching, schema migration for existing file-tier tasks.

---

## File Structure

**Create:**
- `apps/vault-server/src/services/daily_tasks.py` — `DailyTasksService` (parse + write `## Tasks` section)
- `apps/vault-server/src/services/tool_registry.py` — extracted `_register_tools` + risk-class threshold stamp + post_hook stamp + audit_log attachment + preview registrations
- `apps/vault-server/src/services/tool_executor.py` — extracted `_execute_tool` / `_execute_tool_inner` (pre/post hooks, with_span_status wrap, error code override)
- `apps/vault-server/scripts/migrate_media_to_vault.py` — one-shot migration of `data/media/` → `memory/00-system/media/`
- `apps/vault-server/tests/test_daily_tasks.py`
- `apps/vault-server/tests/test_daily_tools.py`
- `apps/vault-server/tests/test_tool_registry.py`

**Modify:**
- `apps/vault-server/src/services/agent_service.py` — delegate to `tool_registry` + `tool_executor`; add 4 daily-tier tool handlers
- `apps/vault-server/src/services/vault_service.py` — minor: `find_or_create_daily(date)` returning the path
- `apps/vault-server/src/api/routes/daily.py` — new `/day` shape (schedule + notes only)
- `apps/vault-server/src/services/calendar_service.py` — verify `GOOGLE_CALENDAR_INCLUDE` allowlist applies; tighten default
- `apps/vault-server/src/config.py` — `media_path` default to `memory/00-system/media`
- `apps/vault-server/src/api/routes/media.py` — read from new path
- `apps/vault-server/src/services/agent_service.py` — `_tool_attach_to_daily` emits wikilink embeds
- `apps/vault-server/tests/test_agent_service.py` — update for grouped `list_tasks` shape, daily-tool tests
- `apps/vault-server/tests/test_daily.py` (or test_daily_route) — new `/day` shape
- `apps/telegram-bot/src/formatters/telegram.ts` — `formatDay` consumes new shape
- `memory/00-system/mazkir-skills/capture.md` — add daily_add_task + daily_set_task_state
- `memory/00-system/mazkir-skills/manager.md` — add all 4 daily tools
- `memory/.gitignore` — exclude `00-system/media/`
- `CLAUDE.md` — daily tier, `/day` redesign, media path

---

## Task 1: Extract `_register_tools` into `tool_registry.py` (P3 rollover)

Pull the tool registration + threshold/post-hook stamping out of `AgentService`. Keeps the agent service focused; tool registry becomes independently testable.

**Files:**
- Create: `apps/vault-server/src/services/tool_registry.py`
- Create: `apps/vault-server/tests/test_tool_registry.py`
- Modify: `apps/vault-server/src/services/agent_service.py`

- [ ] **Step 1: Failing test**

Create `apps/vault-server/tests/test_tool_registry.py`:

```python
"""Tests for the extracted tool registry."""

import pytest
from unittest.mock import MagicMock

from src.services.tool_registry import build_tool_registry, _RISK_DEFAULT_THRESHOLDS


def test_registry_returns_dict_of_tools():
    handlers = {
        "list_tasks": (lambda p: {"ok": True}, "safe"),
        "create_task": (lambda p: {"ok": True}, "write"),
        "delete_task": (lambda p: {"ok": True}, "destructive"),
    }
    schemas = {
        "list_tasks": {"name": "list_tasks", "input_schema": {"type": "object", "properties": {}}},
        "create_task": {"name": "create_task", "input_schema": {"type": "object", "properties": {}}},
        "delete_task": {"name": "delete_task", "input_schema": {"type": "object", "properties": {}}},
    }
    tools = build_tool_registry(handlers, schemas)
    assert "list_tasks" in tools
    assert tools["list_tasks"]["risk"] == "safe"
    assert tools["create_task"]["risk"] == "write"


def test_threshold_stamp_uses_risk_defaults():
    handlers = {
        "list_tasks": (lambda p: {"ok": True}, "safe"),
        "create_task": (lambda p: {"ok": True}, "write"),
        "delete_task": (lambda p: {"ok": True}, "destructive"),
    }
    schemas = {
        n: {"name": n, "input_schema": {"type": "object", "properties": {}}}
        for n in handlers
    }
    tools = build_tool_registry(handlers, schemas)
    assert tools["list_tasks"]["confidence_threshold"] is None
    assert tools["create_task"]["confidence_threshold"] == 0.85
    assert tools["delete_task"]["confidence_threshold"] == 0.95


def test_audit_log_attached_to_write_and_destructive_only():
    handlers = {
        "list_tasks": (lambda p: {"ok": True}, "safe"),
        "create_task": (lambda p: {"ok": True}, "write"),
        "delete_task": (lambda p: {"ok": True}, "destructive"),
    }
    schemas = {
        n: {"name": n, "input_schema": {"type": "object", "properties": {}}}
        for n in handlers
    }
    tools = build_tool_registry(handlers, schemas)
    assert "audit_log" not in tools["list_tasks"]["post_hooks"]
    assert "audit_log" in tools["create_task"]["post_hooks"]
    assert "audit_log" in tools["delete_task"]["post_hooks"]


def test_pre_hooks_default_to_validate_schema_for_write_destructive():
    handlers = {
        "list_tasks": (lambda p: {"ok": True}, "safe"),
        "create_task": (lambda p: {"ok": True}, "write"),
    }
    schemas = {
        n: {"name": n, "input_schema": {"type": "object", "properties": {}}}
        for n in handlers
    }
    tools = build_tool_registry(handlers, schemas)
    assert tools["list_tasks"]["pre_hooks"] == []
    assert "validate_schema" in tools["create_task"]["pre_hooks"]


def test_destructive_tools_get_preview_flag():
    handlers = {
        "delete_task": (lambda p: {"ok": True}, "destructive"),
        "create_task": (lambda p: {"ok": True}, "write"),
    }
    schemas = {
        n: {"name": n, "input_schema": {"type": "object", "properties": {}}}
        for n in handlers
    }
    tools = build_tool_registry(handlers, schemas)
    assert tools["delete_task"]["preview"] is True
    assert tools["create_task"].get("preview", False) is False
```

- [ ] **Step 2: Run, expect failures**

```bash
cd /home/marcellmc/dev/mazkir/apps/vault-server
source venv/bin/activate
python -m pytest tests/test_tool_registry.py -v
```

- [ ] **Step 3: Implement `tool_registry.py`**

Read the existing `_register_tools` in `agent_service.py` first. The registry stamping logic — threshold defaults, pre_hooks=[validate_schema], post_hooks=[] then post_hooks+=audit_log, preview=True on destructive — is what gets extracted.

Create `apps/vault-server/src/services/tool_registry.py`:

```python
"""Builds the tool registry dict from handlers + schemas, applying risk-class
defaults, pre/post hook stamps, and the destructive-preview flag.

This module owns *only* the registry shape — it doesn't know about the
agent loop or how tools are executed. Handlers and schemas come in as
plain functions and dicts; the rest of the registry shape is derived.
"""

from __future__ import annotations

from typing import Callable

_RISK_DEFAULT_THRESHOLDS: dict[str, float | None] = {
    "safe": None,
    "write": 0.85,
    "destructive": 0.95,
}


def build_tool_registry(
    handlers: dict[str, tuple[Callable, str]],
    schemas: dict[str, dict],
) -> dict[str, dict]:
    """
    handlers: {name: (handler_callable, risk)}
    schemas:  {name: input_schema_dict}

    Returns a dict[name -> entry] where each entry has:
        schema, handler, risk, confidence_threshold,
        pre_hooks, post_hooks, preview
    """
    tools: dict[str, dict] = {}
    for name, (handler, risk) in handlers.items():
        entry = {
            "schema": schemas[name],
            "handler": handler,
            "risk": risk,
            "confidence_threshold": _RISK_DEFAULT_THRESHOLDS.get(risk),
            "pre_hooks": [],
            "post_hooks": [],
            "preview": risk == "destructive",
        }
        if risk in ("write", "destructive"):
            entry["pre_hooks"].append("validate_schema")
            entry["post_hooks"].append("audit_log")
        tools[name] = entry
    return tools
```

- [ ] **Step 4: Switch AgentService to use it**

In `agent_service.py`, find `_register_tools`. Replace the manual dict construction + stamp loops with:

```python
from src.services.tool_registry import build_tool_registry

def _register_tools(self) -> dict[str, dict]:
    handlers = {
        "list_tasks":  (self._tool_list_tasks, "safe"),
        "list_habits": (self._tool_list_habits, "safe"),
        # ... all the existing entries in (handler, risk) form
    }
    schemas = {
        "list_tasks":  {"name": "list_tasks", "description": "...", "input_schema": {...}},
        # ... existing schemas
    }
    return build_tool_registry(handlers, schemas)
```

This is a mechanical refactor. The OLD code has the schemas mixed inline; pull them into the `schemas` dict and reference by name in `handlers`. Read the existing `_register_tools` carefully — it's ~600 lines.

If the refactor turns out to be too sprawling for one task, ship a minimal version: keep `_register_tools` returning the existing dict, but have it delegate the per-entry stamping to `build_tool_registry` instead of doing it inline. Either way, the final dict shape must match what `_execute_tool_inner` expects.

- [ ] **Step 5: Run full suite**

```bash
python -m pytest tests/test_tool_registry.py -v
python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: 5 new pass; full suite at 337.

- [ ] **Step 6: Commit**

```bash
cd /home/marcellmc/dev/mazkir
git add apps/vault-server/src/services/tool_registry.py apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_tool_registry.py
git commit -m "refactor(vault-server): extract tool registry build into tool_registry.py (P3 rollover)"
```

---

## Task 2: Extract `_execute_tool` into `tool_executor.py` (P3 rollover)

Pull the per-call execution path (pre-hook → handler → post-hook → status propagation → error-code override → span attrs) out of `AgentService`. Keeps `agent_service.py` focused on the loop, not the per-call wiring.

**Files:**
- Create: `apps/vault-server/src/services/tool_executor.py`
- Modify: `apps/vault-server/src/services/agent_service.py`

- [ ] **Step 1: Read existing `_execute_tool` / `_execute_tool_inner`**

```bash
grep -n "_execute_tool" apps/vault-server/src/services/agent_service.py
```

Understand what state it depends on: `self.tools`, `self.vault`, `self.memory` (the ctx dict), `with_span_status`, the OTel tracer, the preview gate, the audit-log post-hook invocation.

- [ ] **Step 2: Implement `tool_executor.py`**

Create `apps/vault-server/src/services/tool_executor.py`:

```python
"""Per-tool-call execution: pre-hooks → handler → post-hooks → status
propagation → application-level error override.

The executor takes the tool registry and the OTel-friendly span attrs as
input. It is decoupled from AgentService's loop and from the tool registry's
construction.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from opentelemetry import trace as _otel_trace
from opentelemetry.trace import Status, StatusCode
from openinference.semconv.trace import SpanAttributes

from src.services.hooks import run_pre_hooks, run_post_hooks
from src.services.tool_response import err, ok, ErrorCode
from src.services.tracing_helpers import with_span_status

logger = logging.getLogger(__name__)
_tracer = _otel_trace.get_tracer("mazkir.tool_executor")


def execute_tool(
    *,
    name: str,
    params: dict,
    risk: str,
    tools: dict,
    ctx: dict,
) -> dict:
    """Run a tool by name. Returns the normalized response.

    `ctx` must include at minimum {"tool": <registry-entry>, "vault": ...,
    "memory": ...}; the executor sets ctx["tool"] from the registry.
    """
    tool = tools[name]
    ctx = {**ctx, "tool": tool}

    attrs = {
        "tool.name": name,
        "tool.risk": risk,
        SpanAttributes.INPUT_VALUE: json.dumps(params, default=str)[:2000],
    }

    with _tracer.start_as_current_span("agent.tool_call", attributes=attrs) as span:
        with with_span_status(span):
            pre_hooks = tool.get("pre_hooks", [])
            blocked = run_pre_hooks(pre_hooks, params, ctx)
            if blocked is not None:
                result = blocked
            else:
                handler = tool["handler"]
                raw = handler(params)
                if isinstance(raw, dict) and "ok" in raw and ("data" in raw or "error" in raw):
                    result = raw
                else:
                    items = raw.pop("_items", []) if isinstance(raw, dict) else []
                    result = ok(raw if isinstance(raw, dict) else {"value": raw}, items=items)

                post_hooks = tool.get("post_hooks", [])
                if post_hooks:
                    run_post_hooks(post_hooks, params, result, ctx)

            span.set_attribute(SpanAttributes.OUTPUT_VALUE, json.dumps(result, default=str)[:2000])

        if not result.get("ok", True):
            code = result.get("error", {}).get("code", "UNKNOWN")
            span.set_status(Status(StatusCode.ERROR, code))
            span.set_attribute("tool.error.code", code)

    return result
```

- [ ] **Step 3: Switch AgentService to call it**

In `agent_service.py`, find every call site of `_execute_tool` / `_execute_tool_inner`. Replace the bodies of those methods with a delegation:

```python
def _execute_tool_inner(self, name: str, params: dict, risk: str) -> dict:
    from src.services.tool_executor import execute_tool
    return execute_tool(
        name=name,
        params=params,
        risk=risk,
        tools=self.tools,
        ctx={"vault": self.vault, "memory": self.memory},
    )
```

(`_execute_tool` likely wraps `_execute_tool_inner` with extra preview/confirmation logic — leave that wrapping in agent_service.py for now.)

- [ ] **Step 4: Run full suite**

```bash
python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: 337 still.

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/tool_executor.py apps/vault-server/src/services/agent_service.py
git commit -m "refactor(vault-server): extract per-call tool execution into tool_executor.py (P3 rollover)"
```

---

## Task 3: `DailyTasksService` — parse and write the `## Tasks` section

Foundation for the four daily-tier tools. Handles checkbox parsing, optional inline `HH:MM` and `(NNm)` annotations, nested children (sub-checkboxes, plain bullets, numbered).

**Files:**
- Create: `apps/vault-server/src/services/daily_tasks.py`
- Create: `apps/vault-server/tests/test_daily_tasks.py`

- [ ] **Step 1: Failing tests**

```python
"""Tests for DailyTasksService — parse/write ## Tasks section."""

import pytest

from src.services.daily_tasks import (
    DailyTask,
    parse_tasks_section,
    render_tasks_section,
)


def test_parse_empty_section():
    body = "Some body text.\n\n## Tasks\n\n## Notes\nstuff"
    tasks = parse_tasks_section(body)
    assert tasks == []


def test_parse_single_unchecked_task():
    body = "## Tasks\n- [ ] Walk dog\n"
    tasks = parse_tasks_section(body)
    assert len(tasks) == 1
    assert tasks[0].text == "Walk dog"
    assert tasks[0].state == "unchecked"
    assert tasks[0].scheduled_at is None
    assert tasks[0].duration_minutes is None
    assert tasks[0].children == []


def test_parse_checked_task():
    body = "## Tasks\n- [x] Done thing\n"
    tasks = parse_tasks_section(body)
    assert tasks[0].state == "checked"


def test_parse_task_with_time_and_duration():
    body = "## Tasks\n- [ ] 14:00 — Visit dentist (60m)\n"
    tasks = parse_tasks_section(body)
    assert tasks[0].text == "Visit dentist"
    assert tasks[0].scheduled_at == "14:00"
    assert tasks[0].duration_minutes == 60


def test_parse_task_with_children():
    body = (
        "## Tasks\n"
        "- [ ] Plan picnic\n"
        "  - [ ] Buy bread\n"
        "  - check weather forecast\n"
        "  - bring blanket\n"
    )
    tasks = parse_tasks_section(body)
    assert len(tasks) == 1
    assert len(tasks[0].children) == 3
    assert tasks[0].children[0].text == "Buy bread"
    assert tasks[0].children[0].state == "unchecked"
    assert tasks[0].children[1].text == "check weather forecast"
    assert tasks[0].children[1].state == "note"


def test_render_round_trip_preserves_structure():
    body_in = "## Tasks\n- [ ] Walk dog\n- [x] Pay rent\n"
    tasks = parse_tasks_section(body_in)
    rendered = render_tasks_section(tasks)
    assert "- [ ] Walk dog" in rendered
    assert "- [x] Pay rent" in rendered


def test_parse_strikethrough_moved_task():
    body = "## Tasks\n- [ ] ~~Order phone~~ — moved to [[2026-06-05#Tasks]]\n"
    tasks = parse_tasks_section(body)
    assert tasks[0].state == "moved"
    assert tasks[0].text == "Order phone"
```

- [ ] **Step 2: Run, expect failure**

```bash
python -m pytest tests/test_daily_tasks.py -v
```

- [ ] **Step 3: Implement `daily_tasks.py`**

```python
"""Parser/writer for the `## Tasks` section in daily notes.

Format:
    ## Tasks
    - [ ] 14:00 — Visit dentist (60m)
      - [ ] bring insurance card
      - check tooth still hurts
    - [x] Walk dog
    - [ ] ~~Order phone~~ — moved to [[2026-06-05#Tasks]]

State markers:
    - [ ]   unchecked
    - [x]   checked (done)
    - [ ] ~~text~~ — moved to [[...]]   moved (strikethrough)
    plain bullet at child indent   note

Inline time + duration annotation on the parent line:
    `HH:MM — text (NNm)`
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

TaskState = Literal["unchecked", "checked", "moved", "note"]


@dataclass
class DailyTask:
    text: str
    state: TaskState = "unchecked"
    scheduled_at: str | None = None        # "HH:MM"
    duration_minutes: int | None = None
    annotation: str | None = None          # e.g. "moved to [[...]]"
    children: list["DailyTask"] = field(default_factory=list)


_SECTION_RE = re.compile(r"##\s+Tasks\s*\n(.*?)(?=\n##\s|\Z)", re.DOTALL | re.IGNORECASE)
_LINE_RE = re.compile(
    r"^(?P<indent>\s*)"
    r"(?:-\s+\[(?P<box>[ x])\]\s+)?"              # optional checkbox
    r"(?P<rest>.*)$"
)
_TIME_RE = re.compile(r"^(?P<time>\d{1,2}:\d{2})\s+—\s+(?P<text>.*)$")
_DURATION_RE = re.compile(r"\((?P<n>\d+)m\)\s*$")
_STRIKE_RE = re.compile(r"^~~(?P<text>.*?)~~(?:\s+—\s+(?P<ann>.*))?$")
_MOVED_RE = re.compile(r"moved to\s+\[\[")


def parse_tasks_section(body: str) -> list[DailyTask]:
    m = _SECTION_RE.search(body)
    if not m:
        return []

    raw_lines = m.group(1).splitlines()

    # Two-pass: parse each line into (indent, kind, fields), then nest.
    parsed: list[tuple[int, dict]] = []
    for line in raw_lines:
        if not line.strip():
            continue
        lm = _LINE_RE.match(line)
        if not lm:
            continue
        indent = len(lm.group("indent")) // 2  # 2-space indent unit
        rest = lm.group("rest")
        box = lm.group("box")

        if box is not None:
            # checkbox line — top-level or child sub-task
            text = rest
            scheduled_at = None
            duration = None
            annotation = None
            state: TaskState = "checked" if box == "x" else "unchecked"

            sm = _STRIKE_RE.match(text)
            if sm:
                state = "moved"
                text = sm.group("text")
                annotation = sm.group("ann")

            tm = _TIME_RE.match(text)
            if tm:
                scheduled_at = tm.group("time")
                text = tm.group("text")

            dm = _DURATION_RE.search(text)
            if dm:
                duration = int(dm.group("n"))
                text = _DURATION_RE.sub("", text).rstrip()

            # also catch "moved to [[" annotation when it follows a `— ` outside ~~~~
            if annotation is None and _MOVED_RE.search(text):
                parts = text.split(" — ", 1)
                if len(parts) == 2 and "moved to" in parts[1]:
                    text = parts[0].strip("~ ")
                    annotation = parts[1]
                    state = "moved"

            parsed.append((indent, {
                "text": text.strip(),
                "state": state,
                "scheduled_at": scheduled_at,
                "duration_minutes": duration,
                "annotation": annotation,
                "children": [],
            }))
        else:
            # plain bullet / numbered / note line — child only
            note_text = rest.lstrip("- ").lstrip()
            note_text = re.sub(r"^\d+\.\s+", "", note_text)
            parsed.append((indent, {
                "text": note_text.strip(),
                "state": "note",
                "scheduled_at": None,
                "duration_minutes": None,
                "annotation": None,
                "children": [],
            }))

    # Nest by indent
    roots: list[DailyTask] = []
    stack: list[tuple[int, DailyTask]] = []
    for indent, fields in parsed:
        task = DailyTask(**fields)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if stack:
            stack[-1][1].children.append(task)
        else:
            roots.append(task)
        stack.append((indent, task))
    return roots


def render_tasks_section(tasks: list[DailyTask]) -> str:
    lines = ["## Tasks"]
    def emit(task: DailyTask, depth: int) -> None:
        prefix = "  " * depth
        head = ""
        if task.state == "note":
            head = f"{prefix}- {task.text}"
        else:
            box = "x" if task.state == "checked" else " "
            content = task.text
            if task.state == "moved":
                content = f"~~{content}~~"
            if task.scheduled_at:
                content = f"{task.scheduled_at} — {content}"
            if task.duration_minutes:
                content = f"{content} ({task.duration_minutes}m)"
            if task.annotation:
                content = f"{content} — {task.annotation}"
            head = f"{prefix}- [{box}] {content}"
        lines.append(head)
        for child in task.children:
            emit(child, depth + 1)
    for t in tasks:
        emit(t, 0)
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Tests pass**

```bash
python -m pytest tests/test_daily_tasks.py -v
python -m pytest tests/ -q 2>&1 | tail -3
```

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/daily_tasks.py apps/vault-server/tests/test_daily_tasks.py
git commit -m "feat(vault-server): DailyTasksService parses and renders ## Tasks section"
```

---

## Task 4: `daily_add_task` tool

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py` (registration + handler)
- Create: `apps/vault-server/tests/test_daily_tools.py`

- [ ] **Step 1: Failing test**

```python
"""Tests for the four daily-tier tools."""

import pytest
from unittest.mock import MagicMock

from src.services.agent_service import AgentService
from src.services.daily_tasks import DailyTask


def _agent_with_vault(daily_body: str):
    claude = MagicMock()
    vault = MagicMock()
    memory = MagicMock()
    vault.read_daily_note.return_value = {"metadata": {}, "content": daily_body}
    vault.write_daily_note = MagicMock()
    return AgentService(claude=claude, vault=vault, memory=memory)


def test_daily_add_task_appends_to_section():
    agent = _agent_with_vault("## Tasks\n- [ ] Existing\n\n## Notes\n")
    result = agent._tool_daily_add_task({"text": "Buy milk"})
    assert result["ok"] is True
    args, _ = agent.vault.write_daily_note.call_args
    new_body = args[1]
    assert "- [ ] Existing" in new_body
    assert "- [ ] Buy milk" in new_body


def test_daily_add_task_with_time_and_duration():
    agent = _agent_with_vault("## Tasks\n\n")
    result = agent._tool_daily_add_task({
        "text": "Visit dentist",
        "scheduled_at": "14:00",
        "duration_minutes": 60,
    })
    assert result["ok"] is True
    new_body = agent.vault.write_daily_note.call_args.args[1]
    assert "14:00 — Visit dentist (60m)" in new_body


def test_daily_add_task_creates_section_if_missing():
    agent = _agent_with_vault("Some body text.\n")
    result = agent._tool_daily_add_task({"text": "First task"})
    assert result["ok"] is True
    new_body = agent.vault.write_daily_note.call_args.args[1]
    assert "## Tasks" in new_body
    assert "- [ ] First task" in new_body
```

- [ ] **Step 2: Implement**

Add to `agent_service.py`:

```python
"daily_add_task": {
    "schema": {
        "name": "daily_add_task",
        "description": (
            "Add a checkbox task to today's daily note `## Tasks` section. "
            "Optional `scheduled_at` (HH:MM) and `duration_minutes` produce the "
            "inline `HH:MM — text (NNm)` annotation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "scheduled_at": {"type": ["string", "null"], "description": "HH:MM"},
                "duration_minutes": {"type": ["integer", "null"]},
                "date": {"type": ["string", "null"], "description": "YYYY-MM-DD; default today"},
                "_confidence": {"type": "number"},
                "_reasoning": {"type": "string"},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    },
    "handler": self._tool_daily_add_task,
    "risk": "write",
},
```

Handler:

```python
def _tool_daily_add_task(self, params: dict) -> dict:
    from src.services.daily_tasks import DailyTask, parse_tasks_section, render_tasks_section
    import datetime as dt

    date_str = params.get("date") or dt.date.today().isoformat()
    daily = self.vault.read_daily_note(date_str)
    body = daily["content"]
    tasks = parse_tasks_section(body)

    tasks.append(DailyTask(
        text=params["text"],
        state="unchecked",
        scheduled_at=params.get("scheduled_at"),
        duration_minutes=params.get("duration_minutes"),
    ))
    new_section = render_tasks_section(tasks)
    new_body = _replace_or_append_section(body, "Tasks", new_section)
    self.vault.write_daily_note(date_str, new_body)
    return ok({"date": date_str, "text": params["text"]}, items=[f"10-daily/{date_str}.md"])
```

Add a small helper `_replace_or_append_section(body, name, new_section)` either in agent_service.py or daily_tasks.py — it locates `## {name}` and replaces through to the next `##` (or EOF), or appends if missing.

- [ ] **Step 3: Run tests + commit**

```bash
python -m pytest tests/test_daily_tools.py::test_daily_add_task_appends_to_section tests/test_daily_tools.py::test_daily_add_task_with_time_and_duration tests/test_daily_tools.py::test_daily_add_task_creates_section_if_missing -v
git add apps/vault-server/src/services/agent_service.py apps/vault-server/src/services/daily_tasks.py apps/vault-server/tests/test_daily_tools.py
git commit -m "feat(vault-server): daily_add_task tool"
```

---

## Task 5: `daily_set_task_state` tool

Collapsed check / uncheck / move into one tool.

**Files:** modify `agent_service.py`, extend `test_daily_tools.py`.

- [ ] **Step 1: Tests**

```python
def test_daily_check_task_by_text_substring():
    agent = _agent_with_vault("## Tasks\n- [ ] Buy milk\n- [ ] Walk dog\n")
    result = agent._tool_daily_set_task_state({"text": "milk", "state": "checked"})
    assert result["ok"] is True
    new_body = agent.vault.write_daily_note.call_args.args[1]
    assert "- [x] Buy milk" in new_body
    assert "- [ ] Walk dog" in new_body


def test_daily_uncheck_task():
    agent = _agent_with_vault("## Tasks\n- [x] Buy milk\n")
    result = agent._tool_daily_set_task_state({"text": "milk", "state": "unchecked"})
    assert result["ok"] is True
    new_body = agent.vault.write_daily_note.call_args.args[1]
    assert "- [ ] Buy milk" in new_body


def test_daily_set_state_ambiguous_returns_error():
    agent = _agent_with_vault("## Tasks\n- [ ] Buy milk\n- [ ] Buy bread\n")
    result = agent._tool_daily_set_task_state({"text": "Buy", "state": "checked"})
    assert result["ok"] is False
    assert result["error"]["code"] == "AMBIGUOUS_MATCH"
```

- [ ] **Step 2: Implement**

Schema: `text, state (enum: checked|unchecked|moved), date?, _confidence, _reasoning`.

Handler:
```python
def _tool_daily_set_task_state(self, params: dict) -> dict:
    from src.services.daily_tasks import parse_tasks_section, render_tasks_section
    import datetime as dt

    date_str = params.get("date") or dt.date.today().isoformat()
    body = self.vault.read_daily_note(date_str)["content"]
    tasks = parse_tasks_section(body)

    q = params["text"].lower()
    matches = [t for t in tasks if q in t.text.lower()]
    if not matches:
        return err(ErrorCode.PATH_NOT_FOUND, f"No daily task matches '{params['text']}'")
    if len(matches) > 1:
        return err(
            ErrorCode.AMBIGUOUS_MATCH,
            f"Multiple daily tasks match '{params['text']}'",
            details={"candidates": [t.text for t in matches]},
        )
    target = matches[0]
    target.state = params["state"]

    new_body = _replace_or_append_section(body, "Tasks", render_tasks_section(tasks))
    self.vault.write_daily_note(date_str, new_body)
    return ok({"text": target.text, "state": target.state})
```

- [ ] **Step 3: Test + commit**

```bash
git commit -m "feat(vault-server): daily_set_task_state tool (check/uncheck/move)"
```

---

## Task 6: `daily_rollover` tool

Copy unchecked top-level items from a source date to the target date, strikethrough originals, anchor `moved from` link to the first-original.

**Files:** modify `agent_service.py`, extend `test_daily_tools.py`.

- [ ] **Step 1: Tests**

```python
def test_daily_rollover_copies_unchecked_items():
    claude = MagicMock(); vault = MagicMock(); memory = MagicMock()
    vault.read_daily_note.side_effect = lambda d: (
        {"metadata": {}, "content": "## Tasks\n- [ ] Order phone\n- [x] Walk dog\n"}
        if d == "2026-06-04"
        else {"metadata": {}, "content": "## Tasks\n"}
    )
    vault.write_daily_note = MagicMock()
    agent = AgentService(claude=claude, vault=vault, memory=memory)

    result = agent._tool_daily_rollover({"from_date": "2026-06-04", "to_date": "2026-06-05"})
    assert result["ok"] is True
    # Two writes — yesterday strikethrough + today copy
    assert vault.write_daily_note.call_count == 2


def test_daily_rollover_skips_when_target_already_has_item():
    """Idempotency: re-running rollover doesn't duplicate."""
    # ... similar mock setup ...
    # Assert target's tasks unchanged on second run.
```

- [ ] **Step 2: Implement**

Schema: `from_date?, to_date?` (default yesterday → today).

Handler logic:
1. Read source + target.
2. For each unchecked top-level task in source:
   - Skip if target already has a task with the same text + `moved from` annotation matching source's first-original date.
   - In source: change state to `moved`, annotation = `moved to [[<to_date>#Tasks]]`.
   - In target: append a copy with annotation `moved from [[<first_original_date>#Tasks]]`.
3. Walk the chain to find first-original: look for existing `moved from [[X#Tasks]]` annotation in the source item; if present, that X is the first-original; else source date is the first-original.
4. Write both files. (Even if no changes — skip writes if nothing changed.)

Risk: `write`.

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(vault-server): daily_rollover tool with first-original chain anchor"
```

---

## Task 7: `promote_daily_task` tool

Convert a daily checkbox to a file-tier task. Preserve first-original `created` date.

**Files:** modify `agent_service.py`, extend `test_daily_tools.py`.

- [ ] **Step 1: Tests**

```python
def test_promote_daily_task_creates_file_with_first_original_date():
    claude = MagicMock(); vault = MagicMock(); memory = MagicMock()
    vault.read_daily_note.return_value = {
        "metadata": {},
        "content": "## Tasks\n- [ ] Order phone — moved from [[2026-05-21#Tasks]]\n",
    }
    vault.create_task.return_value = {
        "path": "40-tasks/active/order-phone.md",
        "metadata": {"name": "Order phone", "created": "2026-05-21"},
    }
    vault.write_daily_note = MagicMock()
    agent = AgentService(claude=claude, vault=vault, memory=memory)

    result = agent._tool_promote_daily_task({"text": "Order phone"})
    assert result["ok"] is True
    kwargs = vault.create_task.call_args.kwargs
    # created must be the first-original date, not today
    # (vault.create_task may take an explicit created kwarg or use a date_override)
```

The exact kwarg used to pass first-original date depends on vault_service. If `create_task` doesn't accept a `created` override, extend it minimally to accept one (or post-edit the file after creation).

- [ ] **Step 2: Implement**

Handler logic:
1. Find the daily checkbox by text substring (ambiguity → AMBIGUOUS_MATCH).
2. Walk `moved from [[X#Tasks]]` annotations backward to find first-original date.
3. Create file-tier task via `vault.create_task(name=text, created=first_original_date, …)`. Add optional `fields` param to let the agent override priority/due_date.
4. Replace the daily checkbox line with `- [ ] [[<slug>]]` (the wikilink resolves to the new file).
5. If a first-original chain exists, also edit the first-original day's line to `- [x] [[<slug>]] — promoted to file on <today>` (best-effort; skip if first-original file doesn't exist).

Risk: `write`. Schema: `text, fields?, date?` (date = day where the checkbox currently lives).

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(vault-server): promote_daily_task tool with first-original chain walk"
```

---

## Task 8: `list_tasks` returns grouped object

`{daily_pending, daily_done_today, file_tier_by_priority, overdue}`. Replaces flat list.

**Files:** modify `agent_service.py`, update existing `list_tasks` tests.

- [ ] **Step 1: Failing test**

```python
def test_list_tasks_returns_grouped_object(mock_services):
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)
    agent.vault.list_active_tasks.return_value = [
        {"path": "40-tasks/active/x.md", "metadata": {"name": "X", "priority": 3}}
    ]
    agent.vault.read_daily_note.return_value = {"metadata": {}, "content": "## Tasks\n- [ ] Walk dog\n- [x] Done\n"}
    result = agent._tool_list_tasks({})
    assert result["ok"] is True
    data = result["data"]
    assert "daily_pending" in data
    assert "daily_done_today" in data
    assert "file_tier_by_priority" in data
    assert "overdue" in data
```

- [ ] **Step 2: Implement**

```python
def _tool_list_tasks(self, params: dict) -> dict:
    import datetime as dt
    from src.services.daily_tasks import parse_tasks_section

    today = dt.date.today().isoformat()
    daily = self.vault.read_daily_note(today)
    daily_tasks = parse_tasks_section(daily["content"])
    daily_pending = [
        {"text": t.text, "scheduled_at": t.scheduled_at, "duration_minutes": t.duration_minutes}
        for t in daily_tasks if t.state == "unchecked"
    ]
    daily_done = [{"text": t.text} for t in daily_tasks if t.state == "checked"]

    file_tier = self.vault.list_active_tasks()
    by_priority: dict[int, list] = {}
    overdue: list = []
    for t in file_tier:
        meta = t["metadata"]
        prio = int(meta.get("priority", 3))
        by_priority.setdefault(prio, []).append({
            "path": t["path"],
            "name": meta.get("name", ""),
            "priority": prio,
            "due_date": meta.get("due_date"),
            "scheduled_at": meta.get("scheduled_at"),
        })
        if meta.get("due_date") and meta["due_date"] < today and meta.get("status") == "active":
            overdue.append({"path": t["path"], "name": meta.get("name", ""), "due_date": meta["due_date"]})

    return ok({
        "daily_pending": daily_pending,
        "daily_done_today": daily_done,
        "file_tier_by_priority": by_priority,
        "overdue": overdue,
    })
```

Update existing `test_list_tasks_*` assertions in `test_agent_service.py` to match the new shape.

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(vault-server): list_tasks returns grouped daily+file-tier object"
```

---

## Task 9: Calendar filter via `GOOGLE_CALENDAR_INCLUDE`

Verify allowlist works; tighten default behavior so empty env doesn't pull holidays.

**Files:**
- Modify: `apps/vault-server/src/services/calendar_service.py` (verify `_calendar_include` already applied)
- Modify: `apps/vault-server/src/config.py` (document)

- [ ] **Step 1: Audit existing code**

```bash
grep -n "_calendar_include\|google_calendar_include\|GOOGLE_CALENDAR_INCLUDE" apps/vault-server/src/services/calendar_service.py apps/vault-server/src/config.py
```

P1 design doc noted `calendar_include` already exists but isn't enforced when empty. Check the current default. If empty == "include all", change to "include only Mazkir" (or only the env-listed calendars).

- [ ] **Step 2: Update default**

If `_calendar_include` is empty AND `all_calendars=True`, restrict to `["Mazkir"]` by default. Document in config that an explicit env override widens.

- [ ] **Step 3: Test + commit**

Add a test that `get_todays_events` with an empty include list returns only Mazkir-calendar events when given a multi-calendar mock.

```bash
git commit -m "fix(vault-server): default calendar allowlist excludes subscribed calendars (holidays, etc.)"
```

---

## Task 10: `/day` redesign — schedule + notes only

**Files:**
- Modify: `apps/vault-server/src/api/routes/daily.py`
- Modify: `apps/vault-server/tests/test_daily.py` (or wherever the route is tested)
- Modify: `apps/telegram-bot/src/formatters/telegram.ts` — `formatDay`
- Update: `packages/shared-types/src/daily.ts` (or `index.ts`) — `DailyResponse` shape

- [ ] **Step 1: Define new shape**

```ts
// packages/shared-types/src/daily.ts
export interface DailyScheduleItem {
  start: string;         // ISO datetime or HH:MM
  end?: string;
  title: string;
  source: "calendar" | "daily-task" | "habit";
  completed: boolean;
}

export interface DailyNote {
  text?: string;
  photo_path?: string;
  caption?: string;
}

export interface DailyResponse {
  date: string;
  tokens_today: number;
  tokens_total: number;
  schedule: DailyScheduleItem[];
  notes: DailyNote[];
}
```

- [ ] **Step 2: Update route**

`/day` returns the new shape:
- `schedule`: union of (filtered calendar events) + (timed daily checkboxes) + (scheduled habits with `scheduled_at`).
- `notes`: today's `## Notes` section captures + photos.
- Sorted by start time.

Drop the standalone `habits` and `tasks` arrays.

- [ ] **Step 3: Bot formatter**

`apps/telegram-bot/src/formatters/telegram.ts` `formatDay`:

```ts
export function formatDay(data: DailyResponse): string {
  const lines: string[] = [];
  lines.push(`📅 <b>Daily Note — ${data.date}</b>`);
  lines.push(`🪙 Tokens today: <b>${data.tokens_today}</b> | Total: <b>${data.tokens_total}</b>`);
  lines.push("");
  if (data.schedule.length > 0) {
    lines.push("📆 <b>Schedule</b>");
    for (const item of data.schedule) {
      const icon = item.completed ? "✅" : item.source === "habit" ? "🔁" : "⏳";
      const time = formatScheduleTime(item.start, item.end);
      lines.push(`  ${icon} ${time} — ${item.title}`);
    }
  }
  if (data.notes.length > 0) {
    lines.push("");
    lines.push("📝 <b>Notes</b>");
    for (const n of data.notes) {
      const text = n.text ?? (n.caption ? `📷 ${n.caption}` : "📷");
      lines.push(`  ${text}`);
    }
  }
  return lines.join("\n");
}
```

- [ ] **Step 4: Tests + commits**

```bash
# vault-server
python -m pytest apps/vault-server/tests/ -q 2>&1 | tail -3
# bot
cd apps/telegram-bot && npx vitest run 2>&1 | tail -10
git commit -m "feat(/day): time-based schedule + notes feed, drop standalone tasks/habits sections"
```

---

## Task 11: Switch `attach_to_daily` to wikilink embeds

**Files:** modify `agent_service.py` `_tool_attach_to_daily`.

- [ ] **Step 1: Test**

```python
def test_attach_to_daily_emits_wikilink_embed(mock_services):
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)
    agent.vault.append_to_daily_section.return_value = {"path": "10-daily/2026-06-04.md"}
    result = agent._tool_attach_to_daily({
        "vault_path": "data/media/2026-06-04/photo_xyz.jpg",
        "caption": "A nice picture",
    })
    assert result["ok"] is True
    content = agent.vault.append_to_daily_section.call_args.kwargs["content"]
    assert "![[photo_xyz.jpg]]" in content
    assert "![](" not in content  # no old-style relative path
```

- [ ] **Step 2: Implement**

Update `_tool_attach_to_daily` to emit `![[<filename>]]` (Obsidian wikilink embed) instead of `![](../../{vault_path})`.

```bash
git commit -m "feat(vault-server): attach_to_daily emits Obsidian wikilink embeds for media"
```

---

## Task 12: Media path → `memory/00-system/media/`

**Files:**
- Modify: `apps/vault-server/src/config.py` — `media_path` default
- Modify: `apps/vault-server/src/api/routes/media.py` — read from new path
- Modify: `memory/.gitignore` — exclude `00-system/media/`

- [ ] **Step 1: Update default**

```python
# config.py
media_path: Path = Path(os.getenv(
    "MEDIA_PATH",
    str(Path.home() / "dev" / "mazkir" / "memory" / "00-system" / "media"),
))
```

- [ ] **Step 2: Verify media route**

`apps/vault-server/src/api/routes/media.py` resolves files relative to `settings.media_path`. With the new default, no code change is needed — `settings.media_path / date / filename` already points to the new location.

- [ ] **Step 3: Add fallback search**

If a file isn't found at the date-keyed path, walk the vault's `00-system/media/` tree to find any matching filename (so the webapp's wikilink-to-URL resolver works when dates don't line up).

- [ ] **Step 4: gitignore in nested vault repo**

```bash
cd /home/marcellmc/dev/mazkir/memory
echo "00-system/media/" >> .gitignore
git add .gitignore
git commit -m "chore: gitignore media binaries in vault"
cd /home/marcellmc/dev/mazkir
```

- [ ] **Step 5: Test + commit (outer repo)**

```bash
git commit -m "feat(vault-server): default media_path inside Obsidian vault (E2)"
```

---

## Task 13: Migration script — `data/media/` → `memory/00-system/media/`

**Files:**
- Create: `apps/vault-server/scripts/migrate_media_to_vault.py`

- [ ] **Step 1: Implement**

```python
"""One-shot migration: move data/media/{date}/* → memory/00-system/media/{date}/*
and rewrite ![](../../data/media/{date}/{file}) → ![[{file}]] in daily notes.
"""

from pathlib import Path
import re
import shutil

REPO = Path.home() / "dev" / "mazkir"
OLD = REPO / "data" / "media"
NEW = REPO / "memory" / "00-system" / "media"
DAILY = REPO / "memory" / "10-daily"

EMBED_RE = re.compile(
    r"!\[([^\]]*)\]\(\.\./\.\./data/media/(\d{4}-\d{2}-\d{2})/([^)]+)\)"
)


def main(dry_run: bool = False) -> None:
    NEW.mkdir(parents=True, exist_ok=True)

    moved_dates: list[Path] = []
    if OLD.exists():
        for date_dir in sorted(OLD.iterdir()):
            if not date_dir.is_dir():
                continue
            target = NEW / date_dir.name
            print(f"  move {date_dir} → {target}")
            if not dry_run:
                if target.exists():
                    # merge: copy files individually
                    for f in date_dir.iterdir():
                        shutil.copy2(f, target / f.name)
                    shutil.rmtree(date_dir)
                else:
                    shutil.move(str(date_dir), str(target))
            moved_dates.append(target)

    rewritten = 0
    if DAILY.exists():
        for md in sorted(DAILY.rglob("*.md")):
            text = md.read_text()
            new = EMBED_RE.sub(lambda m: f"![[{m.group(3)}]]", text)
            if new != text:
                print(f"  rewrite {md}")
                if not dry_run:
                    md.write_text(new)
                rewritten += 1

    print(f"\nMoved {len(moved_dates)} date dirs. Rewrote {rewritten} daily notes.")


if __name__ == "__main__":
    import sys
    main(dry_run="--dry-run" in sys.argv)
```

- [ ] **Step 2: Dry-run + apply**

```bash
cd /home/marcellmc/dev/mazkir
source apps/vault-server/venv/bin/activate
python apps/vault-server/scripts/migrate_media_to_vault.py --dry-run
# review output, then:
python apps/vault-server/scripts/migrate_media_to_vault.py
```

- [ ] **Step 3: Commit script**

```bash
git add apps/vault-server/scripts/migrate_media_to_vault.py
git commit -m "feat(vault-server): media migration script (data/media/ → vault)"
```

The actual file moves don't need a code commit — they're filesystem changes. The nested vault repo can commit the new media folder presence if desired (but `00-system/media/` is in `.gitignore` now per T12, so binaries don't enter git).

---

## Task 14: Update skills — add daily-tier tools to capture + manager

**Files:**
- Modify: `memory/00-system/mazkir-skills/capture.md`
- Modify: `memory/00-system/mazkir-skills/manager.md`

- [ ] **Step 1: capture.md**

Add `daily_add_task` and `daily_set_task_state` to the `tools:` list.

- [ ] **Step 2: manager.md**

Add `daily_add_task`, `daily_set_task_state`, `daily_rollover`, `promote_daily_task` to the `tools:` list.

- [ ] **Step 3: Verify parser sees the new tools**

```bash
cd /home/marcellmc/dev/mazkir/apps/vault-server
source venv/bin/activate
python -c "
from pathlib import Path
from src.services.skill_registry import SkillRegistry
r = SkillRegistry(skills_dir=Path('/home/marcellmc/dev/mazkir/memory/00-system/mazkir-skills'))
r.load()
for s in r.list():
    print(s.name, [t for t in s.tools if 'daily' in t])
"
```

- [ ] **Step 4: Commit in nested vault repo**

```bash
cd /home/marcellmc/dev/mazkir/memory
git add 00-system/mazkir-skills/capture.md 00-system/mazkir-skills/manager.md
git commit -m "feat(skills): add daily-tier tools to capture and manager"
cd /home/marcellmc/dev/mazkir
```

---

## Task 15: Final sweep + CLAUDE.md

- [ ] **Step 1: Full test suite**

```bash
cd /home/marcellmc/dev/mazkir/apps/vault-server
source venv/bin/activate
python -m pytest tests/ -v 2>&1 | tail -15
```

Expected: all green, ~352 tests.

- [ ] **Step 2: Turbo test (includes bot's vitest)**

```bash
cd /home/marcellmc/dev/mazkir
npx turbo test 2>&1 | tail -10
```

- [ ] **Step 3: CLAUDE.md updates**

Add bullets under Architecture / Current Capabilities:

> **Two-tier tasks (P4):** Default capture is a `- [ ]` line in the daily note's `## Tasks` section. Multi-day items promote to `40-tasks/active/{slug}.md` files via `promote_daily_task`. Daily-tier tools: `daily_add_task`, `daily_set_task_state` (check/uncheck/move), `daily_rollover` (yesterday's unfinished → today, anchored to first-original date), `promote_daily_task`.
>
> **`/day` as time-based feed (P4):** Schedule (calendar events filtered by `GOOGLE_CALENDAR_INCLUDE` + timed daily checkboxes + scheduled habits) and Notes (today's captures + photos). No standalone Tasks or Habits sections — use `/tasks` and `/habits` for those.
>
> **Media in vault (P4):** Default `MEDIA_PATH` is `memory/00-system/media/{YYYY-MM-DD}/`. Daily-note photo embeds are Obsidian wikilinks (`![[photo.jpg]]`). The folder is gitignored in the nested vault repo.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude-md): document daily-tier tasks, /day redesign, and media in vault"
```

---

## Self-review notes

Coverage:

| Spec item | Task(s) |
| --- | --- |
| P3 rollover: extract tool registry | 1 |
| P3 rollover: extract tool executor | 2 |
| DailyTasksService parse/render | 3 |
| daily_add_task | 4 |
| daily_set_task_state | 5 |
| daily_rollover with chain anchor | 6 |
| promote_daily_task with first-original walk | 7 |
| list_tasks returns grouped object | 8 |
| Calendar allowlist enforced | 9 |
| /day redesigned (schedule + notes) | 10 |
| attach_to_daily wikilink embeds | 11 |
| Media path → vault | 12 |
| Migration script | 13 |
| Skills updated | 14 |
| CLAUDE.md refresh | 15 |

**Out of scope:** GCal sync as `sync_to_calendar` post-hook (P5), parallel exec (P5), streaming (P5), B5 snapshot cache, schema migration for existing file-tier tasks.

**Open implementation questions:**
- `_replace_or_append_section` helper: ship it inside `daily_tasks.py` (lower coupling) vs `vault_service.py` (more general utility). T3 sketches the function inside `daily_tasks.py`; either is fine.
- `promote_daily_task`'s `created` override on `vault.create_task`: T1 of P1 added optional date kwargs to `create_task` — confirm `created` is among them; if not, add it minimally.
- Calendar default-include behavior: defaulting empty include → ["Mazkir"] may break users who rely on seeing other calendars. Mitigation: explicit `GOOGLE_CALENDAR_INCLUDE=Mazkir,Work` in `.env`. Document in CLAUDE.md.
