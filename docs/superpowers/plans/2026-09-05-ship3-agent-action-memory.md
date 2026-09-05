# Ship 3 — Agent Action Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The agent reads what it actually did in earlier turns, so it can no longer deny its own writes.

**Architecture:** `AgentService` already writes a rich per-turn tool audit to `data/logs/agent-turns.jsonl` that nothing reads. A new pure module, `services/turn_trace.py`, reads that file, renders each turn's calls as one compact block, and attaches it to the assistant message it belongs to. `MemoryService.assemble_context` calls it, so the trace arrives in the prompt unasked — no new tool, no new store, no vault writes. Three prompt lines forbid denying a past action without checking.

**Tech Stack:** Python 3.14, FastAPI, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-05-ship3-agent-action-memory-design.md`

## Global Constraints

- **No new dependencies.** Standard library `json` and `pathlib` only.
- **A mismatch omits the trace; it never guesses.** This is the ship's one non-negotiable property (spec §4.2). Attaching the wrong trace is a worse version of the bug being fixed.
- **The reader never raises.** A missing file, a torn final line, an unparseable row and a non-dict row all degrade to "fewer records", never to an exception. `assemble_context` runs on every turn.
- **Nothing is written to the vault.** Traces live only in the in-memory `messages` list handed to Claude. The conversation note is untouched (spec §3.3).
- **Backwards compatible construction.** `MemoryService(logs_dir=...)` is optional and defaults to `None`, which disables traces. Existing tests construct `MemoryService` without it and must keep passing.
- **Trace vocabulary** — exact strings, used verbatim in tests:
  - header: `Tools I called this turn` (plus `, as <skill>` when the skill is known)
  - no calls: `[Tools I called this turn: none]`
  - outcomes: `ok` · the error code (e.g. `SCHEMA_INVALID`) · `proposed, awaiting confirmation — NOT executed` · `no result recorded`
- **Param budget:** rendered params are truncated to 80 characters followed by `…` (U+2026).

## File Structure

| File | Responsibility |
|---|---|
| `src/services/turn_trace.py` *(new)* | Pure module: read records, render a trace, join traces to messages. No service dependencies. |
| `tests/test_turn_trace.py` *(new)* | Unit tests for all three functions. |
| `src/services/memory_service.py` | Gains `logs_dir`; `assemble_context` attaches traces. |
| `src/main.py` | Passes `settings.logs_dir` into `MemoryService`. |
| `src/services/agent_service.py` | Threads `skill` through the loop into the audit record; adds three prompt guidelines. |
| `src/services/skill_executor.py` | Passes the active skill's name into `run_loop`. |
| `tests/test_memory_service.py` | Integration of traces into `assemble_context`. |
| `tests/test_agent_service.py` | `skill` in the audit record; guideline strings in the static prefix. |

Task order follows the dependency chain: `skill` must exist in the record (Task 1) before the renderer can show it (Task 3).

---

### Task 1: Record the routed skill in the turn audit

The agent's denial happened because a skill hop changed its tool list. `skill.name` currently reaches only the OTel span (`skill_executor.py:133`), so the audit record — which is about to become memory — cannot say which skill was active. Thread it through the two-hop chain `SkillExecutor.run` → `AgentService._run_loop` → `_run_agent_turn` → `_emit_turn_audit`.

**Files:**
- Modify: `src/services/agent_service.py` (`_run_loop`, `_run_agent_turn`, `_emit_turn_audit`)
- Modify: `src/services/skill_executor.py:142` (the `self._run_loop(...)` call)
- Test: `tests/test_agent_service.py`

**Interfaces:**
- Consumes: nothing.
- Produces: turn audit records gain an optional `"skill": str | None` key. Task 3's renderer reads `record.get("skill")`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_service.py`:

```python
class TestSkillInTurnAudit:
    def test_emit_turn_audit_records_skill(self, agent, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            "src.services.agent_service.emit_agent_turn",
            lambda record: captured.update(record),
        )

        agent._emit_turn_audit(
            chat_id=123,
            user_text="add two todos",
            tools_audit=[],
            assistant_text="Added both.",
            items_referenced=[],
            awaiting_confirmation=False,
            pending_action_id=None,
            prior_action_id=None,
            iters=1,
            stop_reason="end_turn",
            skill="time-management",
        )

        assert captured["skill"] == "time-management"

    def test_emit_turn_audit_skill_defaults_to_none(self, agent, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            "src.services.agent_service.emit_agent_turn",
            lambda record: captured.update(record),
        )

        agent._emit_turn_audit(
            chat_id=123,
            user_text="hi",
            tools_audit=[],
            assistant_text="hello",
            items_referenced=[],
            awaiting_confirmation=False,
            pending_action_id=None,
            prior_action_id=None,
            iters=1,
            stop_reason="end_turn",
        )

        assert captured["skill"] is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_agent_service.py -k SkillInTurnAudit -v
```

Expected: FAIL — `_emit_turn_audit() got an unexpected keyword argument 'skill'`.

- [ ] **Step 3: Add the parameter to `_emit_turn_audit`**

In `src/services/agent_service.py`, change the signature (currently ending `stop_reason: str | None,`) and the emitted dict:

```python
    def _emit_turn_audit(
        self,
        chat_id: int,
        user_text: str,
        tools_audit: list[dict],
        assistant_text: str,
        items_referenced: list[str],
        awaiting_confirmation: bool,
        pending_action_id: str | None,
        prior_action_id: str | None,
        iters: int,
        stop_reason: str | None,
        skill: str | None = None,
    ) -> None:
        emit_agent_turn({
            "chat_id": chat_id,
            "skill": skill,
            "user_text": user_text,
            "tools": tools_audit,
            "assistant_text": assistant_text,
            "items_referenced": items_referenced,
            "awaiting_confirmation": awaiting_confirmation,
            "pending_action_id": pending_action_id,
            "prior_action_id": prior_action_id,
            "iters": iters,
            "stop_reason": stop_reason,
        })
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_agent_service.py -k SkillInTurnAudit -v
```

Expected: PASS.

- [ ] **Step 5: Thread `skill` down the call chain**

Add `skill: str | None = None` to `_run_agent_turn`'s signature, immediately after `model: str | None = None,`:

```python
    def _run_agent_turn(
        self,
        chat_id: int,
        original_text: str,
        messages: list[dict],
        system: str,
        tool_schemas: list[dict],
        max_iterations: int,
        pre_tools: list[dict] | None = None,
        action_id: str | None = None,
        cache_static_prefix: str | None = None,
        model: str | None = None,
        skill: str | None = None,
    ) -> AgentResponse:
```

Both `_emit_turn_audit(...)` call sites inside `_run_agent_turn` (around `:1541` and `:1598`) gain `skill=skill,` as their last argument.

Add the same parameter to `_run_loop`, after `model: str | None = None,`, and pass it on:

```python
        result = self._run_agent_turn(
            chat_id=chat_id,
            original_text=log_text,
            messages=messages,
            system=system,
            tool_schemas=tool_schemas,
            max_iterations=max_iterations,
            cache_static_prefix=cache_static_prefix,
            model=model,
            skill=skill,
        )
```

In `src/services/skill_executor.py`, the `self._run_loop(...)` call at `:142` gains one argument:

```python
                    outcome = LoopOutcome(*self._run_loop(
                        chat_id=chat_id,
                        log_text=user_msg,
                        messages=messages,
                        system=system,
                        tool_schemas=tool_schemas,
                        max_iterations=skill.max_iterations,
                        cache_static_prefix=cache_static_prefix,
                        model=skill.model,
                        skill=skill.name,
                    ))
```

- [ ] **Step 6: Run the full suite**

```bash
python -m pytest tests/ -q
```

Expected: PASS, no regressions. Some `_run_loop` test doubles are `MagicMock`s and accept the new kwarg silently; any that assert on exact call kwargs need updating to include `skill`.

- [ ] **Step 7: Commit**

```bash
git add apps/vault-server/src/services/agent_service.py \
        apps/vault-server/src/services/skill_executor.py \
        apps/vault-server/tests/test_agent_service.py
git commit -m "feat(agent): record the routed skill in the turn audit"
```

---

### Task 2: Read turn records from the audit log

The reader. `data/logs/agent-turns.jsonl` is a log, not a database — it must be read defensively (spec §3.1).

**Files:**
- Create: `src/services/turn_trace.py`
- Test: `tests/test_turn_trace.py` *(new)*

**Interfaces:**
- Consumes: records written by Task 1.
- Produces: `read_turn_records(logs_dir: Path | str, chat_id: int, date: str) -> list[dict]` — records for that chat and date, in file (chronological) order. `date` is `"YYYY-MM-DD"`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_turn_trace.py`:

```python
"""Tests for turn_trace — reading, rendering and joining per-turn tool traces."""

import json

import pytest

from src.services.turn_trace import read_turn_records


def _write_log(logs_dir, rows):
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / "agent-turns.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


class TestReadTurnRecords:
    def test_returns_empty_when_file_missing(self, tmp_path):
        assert read_turn_records(tmp_path / "nope", chat_id=1, date="2026-09-05") == []

    def test_filters_by_chat_and_date(self, tmp_path):
        _write_log(tmp_path, [
            {"ts": "2026-09-05T10:00:00+0300", "chat_id": 1, "user_text": "a"},
            {"ts": "2026-09-05T11:00:00+0300", "chat_id": 2, "user_text": "b"},
            {"ts": "2026-09-04T10:00:00+0300", "chat_id": 1, "user_text": "c"},
            {"ts": "2026-09-05T12:00:00+0300", "chat_id": 1, "user_text": "d"},
        ])

        got = read_turn_records(tmp_path, chat_id=1, date="2026-09-05")

        assert [r["user_text"] for r in got] == ["a", "d"]

    def test_preserves_file_order(self, tmp_path):
        _write_log(tmp_path, [
            {"ts": "2026-09-05T10:00:00+0300", "chat_id": 1, "user_text": str(i)}
            for i in range(5)
        ])

        got = read_turn_records(tmp_path, chat_id=1, date="2026-09-05")

        assert [r["user_text"] for r in got] == ["0", "1", "2", "3", "4"]

    def test_skips_torn_final_line(self, tmp_path):
        path = _write_log(tmp_path, [
            {"ts": "2026-09-05T10:00:00+0300", "chat_id": 1, "user_text": "good"},
        ])
        with path.open("a", encoding="utf-8") as fh:
            fh.write('{"ts": "2026-09-05T11:00:00+0300", "chat_id": 1, "user_te')

        got = read_turn_records(tmp_path, chat_id=1, date="2026-09-05")

        assert [r["user_text"] for r in got] == ["good"]

    def test_skips_blank_and_non_dict_rows(self, tmp_path):
        path = _write_log(tmp_path, [
            {"ts": "2026-09-05T10:00:00+0300", "chat_id": 1, "user_text": "good"},
        ])
        with path.open("a", encoding="utf-8") as fh:
            fh.write("\n[1, 2, 3]\n\n")

        got = read_turn_records(tmp_path, chat_id=1, date="2026-09-05")

        assert [r["user_text"] for r in got] == ["good"]

    def test_tolerates_record_without_ts_or_chat_id(self, tmp_path):
        _write_log(tmp_path, [
            {"user_text": "no ts"},
            {"ts": "2026-09-05T10:00:00+0300", "user_text": "no chat"},
            {"ts": "2026-09-05T11:00:00+0300", "chat_id": 1, "user_text": "good"},
        ])

        got = read_turn_records(tmp_path, chat_id=1, date="2026-09-05")

        assert [r["user_text"] for r in got] == ["good"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_turn_trace.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'src.services.turn_trace'`.

- [ ] **Step 3: Create the module**

Create `src/services/turn_trace.py`:

```python
"""Per-turn tool traces for the agent prompt.

AgentService already writes a rich audit record for every turn to
``data/logs/agent-turns.jsonl``.  Nothing read it, so the agent had no
factual record of its own past actions and reasoned about them from its
*current* tool list instead -- which is how it came to deny writes it had
made (Ship 3, spec section 2).

This module is the reader.  It is deliberately pure: it takes paths and
dicts, returns strings and lists, and depends on no service.  It also never
raises -- ``assemble_context`` calls it on every single turn, so a malformed
log line must cost one trace, not the whole conversation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_LOG_FILENAME = "agent-turns.jsonl"


def read_turn_records(
    logs_dir: Path | str, chat_id: int, date: str,
) -> list[dict[str, Any]]:
    """Return this chat's turn records for ``date``, in chronological order.

    Args:
        logs_dir: Directory holding ``agent-turns.jsonl``.
        chat_id: Telegram chat id to filter on.
        date: ``YYYY-MM-DD``; matched against the record's ``ts`` prefix.

    Returns:
        Matching records in file order.  Empty when the file is absent.
        Rows that are blank, unparseable or not JSON objects are skipped.
    """
    path = Path(logs_dir) / _LOG_FILENAME
    if not path.exists():
        return []

    records: list[dict[str, Any]] = []
    # errors="replace" so a partially-flushed multibyte character cannot
    # raise out of the iterator itself, before json.loads ever sees it.
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue  # torn or corrupt line -- skip it, never raise
            if not isinstance(record, dict):
                continue
            if record.get("chat_id") != chat_id:
                continue
            if not str(record.get("ts", "")).startswith(date):
                continue
            records.append(record)
    return records
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_turn_trace.py -v
```

Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/turn_trace.py apps/vault-server/tests/test_turn_trace.py
git commit -m "feat(turn-trace): read per-turn audit records defensively"
```

---

### Task 3: Render a turn record as a trace block

The log record is **not** injected verbatim — measured at p50 308 B, p90 1.2 KB, max 8.7 KB per turn, because `_summarize_result` truncates only one level deep and whole note bodies ride inside `data` (spec §5).

**Files:**
- Modify: `src/services/turn_trace.py`
- Test: `tests/test_turn_trace.py`

**Interfaces:**
- Consumes: a record dict from `read_turn_records`.
- Produces: `render_trace(record: dict) -> str` — a single bracketed block, no trailing newline. Task 4 appends it to an assistant message.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_turn_trace.py`:

```python
from src.services.turn_trace import render_trace


def _call(name, params=None, ok=True, error_code=None, pending=False, no_result=False):
    if pending:
        summary = None
    elif no_result:
        summary = None
    elif ok:
        summary = {"ok": True, "data": {}}
    else:
        summary = {"ok": False, "error": {"code": error_code, "message": "boom"}}
    call = {"name": name, "params": params or {}, "result_summary": summary}
    if pending:
        call["pending"] = True
    return call


class TestRenderTrace:
    def test_no_calls_renders_none(self):
        assert render_trace({"tools": []}) == "[Tools I called this turn: none]"

    def test_missing_tools_key_renders_none(self):
        assert render_trace({}) == "[Tools I called this turn: none]"

    def test_skill_appears_in_header(self):
        out = render_trace({"skill": "time-management", "tools": []})
        assert out == "[Tools I called this turn, as time-management: none]"

    def test_successful_call(self):
        out = render_trace({"tools": [_call("daily_add_task", {"text": "Order dog food"})]})
        assert 'daily_add_task(text="Order dog food") → ok' in out

    def test_failed_call_shows_error_code(self):
        out = render_trace({"tools": [
            _call("delete_task", {"name": "old"}, ok=False, error_code="SCHEMA_INVALID"),
        ]})
        assert "delete_task(name=\"old\") → SCHEMA_INVALID" in out

    def test_pending_call_is_marked_not_executed(self):
        out = render_trace({"tools": [_call("delete_task", {"name": "old"}, pending=True)]})
        assert "→ proposed, awaiting confirmation — NOT executed" in out
        assert "→ ok" not in out

    def test_missing_result_summary(self):
        out = render_trace({"tools": [_call("get_daily", no_result=True)]})
        assert "→ no result recorded" in out

    def test_multiple_calls_each_get_a_line(self):
        out = render_trace({"tools": [
            _call("daily_add_task", {"text": "Order dog food"}),
            _call("daily_add_task", {"text": "Bring the bicycle to repair shop"}),
        ]})
        assert out.count("daily_add_task") == 2
        assert out.startswith("[Tools I called this turn:\n")
        assert out.endswith("]")

    def test_long_params_are_truncated(self):
        body = "x" * 500
        out = render_trace({"tools": [_call("save_knowledge", {"content": body})]})
        assert "…" in out
        assert len(out) < 200
        assert body not in out

    def test_non_string_params_render_without_quotes(self):
        out = render_trace({"tools": [_call("update_goal", {"progress": 40, "done": True})]})
        assert "progress=40" in out
        assert "done=True" in out

    def test_call_without_params(self):
        out = render_trace({"tools": [_call("list_tasks")]})
        assert "list_tasks() → ok" in out
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_turn_trace.py -k RenderTrace -v
```

Expected: FAIL — `ImportError: cannot import name 'render_trace'`.

- [ ] **Step 3: Implement the renderer**

Append to `src/services/turn_trace.py`:

```python
_HEADER = "Tools I called this turn"
_MAX_PARAM_CHARS = 80
_PENDING_OUTCOME = "proposed, awaiting confirmation — NOT executed"


def _render_params(params: Any) -> str:
    """Render a call's params compactly, capped at _MAX_PARAM_CHARS."""
    if not isinstance(params, dict) or not params:
        return ""
    bits = [
        f'{k}="{v}"' if isinstance(v, str) else f"{k}={v}"
        for k, v in params.items()
    ]
    text = ", ".join(bits)
    if len(text) > _MAX_PARAM_CHARS:
        text = text[:_MAX_PARAM_CHARS] + "…"
    return text


def _render_outcome(call: dict[str, Any]) -> str:
    """Render what became of one call.

    A gated call that never ran must never read as done -- fixing false
    denial by manufacturing false claims would violate the invariant the
    'Reporting writes' guidelines already establish.
    """
    if call.get("pending"):
        return _PENDING_OUTCOME
    summary = call.get("result_summary")
    if not isinstance(summary, dict):
        return "no result recorded"
    if summary.get("ok") is True:
        return "ok"
    error = summary.get("error")
    if isinstance(error, dict) and error.get("code"):
        return str(error["code"])
    return "failed"


def render_trace(record: dict[str, Any]) -> str:
    """Render one turn record as a single bracketed trace block.

    A turn that called nothing renders an explicit ``none`` rather than
    nothing at all: an unmatched turn contributes no block (see
    ``attach_traces``), so silence would be ambiguous between "I called
    nothing" and "no record survived the join" -- and a model reasoning
    confidently from ambiguous absence is the bug this ship fixes.
    """
    skill = record.get("skill")
    header = f"{_HEADER}, as {skill}" if skill else _HEADER

    calls = record.get("tools") or []
    if not calls:
        return f"[{header}: none]"

    lines = [
        f"   {c.get('name', 'unknown')}({_render_params(c.get('params'))})"
        f" → {_render_outcome(c)}"
        for c in calls
    ]
    return f"[{header}:\n" + "\n".join(lines) + "]"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_turn_trace.py -v
```

Expected: PASS, 17 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/turn_trace.py apps/vault-server/tests/test_turn_trace.py
git commit -m "feat(turn-trace): render a turn's calls as a compact block"
```

---

### Task 4: Join traces to the messages they belong to

The join, and the ship's riskiest code. Spec §4.2: match on `user_text`, walk from the tail, and **on a mismatch attach nothing** — never a near-miss.

**Files:**
- Modify: `src/services/turn_trace.py`
- Test: `tests/test_turn_trace.py`

**Interfaces:**
- Consumes: `render_trace` from Task 3.
- Produces: `attach_traces(messages: list[dict], records: list[dict]) -> list[dict]` — a **new** list of `{"role", "content"}` dicts; input is never mutated.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_turn_trace.py`:

```python
from src.services.turn_trace import attach_traces


def _msgs(*pairs):
    """Build a message list from (user_text, assistant_text) pairs."""
    out = []
    for user, assistant in pairs:
        out.append({"role": "user", "content": user})
        out.append({"role": "assistant", "content": assistant})
    return out


def _rec(user_text, tool_name="daily_add_task", skill=None):
    record = {
        "user_text": user_text,
        "tools": [{
            "name": tool_name,
            "params": {},
            "result_summary": {"ok": True, "data": {}},
        }],
    }
    if skill:
        record["skill"] = skill
    return record


class TestAttachTraces:
    def test_attaches_trace_to_the_matching_assistant_message(self):
        messages = _msgs(("add two todos", "Added both."))
        out = attach_traces(messages, [_rec("add two todos")])

        assert out[0]["content"] == "add two todos"
        assert out[1]["content"].startswith("Added both.")
        assert "daily_add_task() → ok" in out[1]["content"]

    def test_does_not_mutate_input(self):
        messages = _msgs(("hi", "hello"))
        attach_traces(messages, [_rec("hi")])

        assert messages[1]["content"] == "hello"

    def test_no_records_leaves_messages_unchanged(self):
        messages = _msgs(("hi", "hello"))
        out = attach_traces(messages, [])

        assert out == messages

    def test_extra_older_records_are_ignored(self):
        """Decay truncates the note from the front; the log keeps everything."""
        messages = _msgs(("third", "C"))
        records = [_rec("first"), _rec("second"), _rec("third")]

        out = attach_traces(messages, records)

        assert "→ ok" in out[1]["content"]
        assert out[1]["content"].startswith("C")

    def test_duplicate_user_texts_disambiguate_by_order(self):
        messages = _msgs(("yes", "Did A."), ("yes", "Did B."))
        records = [_rec("yes", tool_name="tool_a"), _rec("yes", tool_name="tool_b")]

        out = attach_traces(messages, records)

        assert "tool_a" in out[1]["content"]
        assert "tool_b" in out[3]["content"]

    def test_pair_without_a_record_gets_nothing_and_others_still_align(self):
        """save_turn runs before _emit_turn_audit; a crash between leaves a gap."""
        messages = _msgs(("one", "A"), ("two", "B"), ("three", "C"))
        records = [_rec("one", tool_name="tool_one"), _rec("three", tool_name="tool_three")]

        out = attach_traces(messages, records)

        assert "tool_one" in out[1]["content"]
        assert out[3]["content"] == "B"          # no record -- nothing attached
        assert "tool_three" in out[5]["content"]

    def test_never_attaches_a_mismatched_trace(self):
        messages = _msgs(("what did you do?", "Nothing."))
        records = [_rec("delete everything", tool_name="delete_task")]

        out = attach_traces(messages, records)

        assert out[1]["content"] == "Nothing."
        assert "delete_task" not in out[1]["content"]

    def test_window_starting_mid_pair_is_handled(self):
        """A 20-message window can begin on an assistant message."""
        messages = [{"role": "assistant", "content": "orphan"}] + _msgs(("hi", "hello"))
        out = attach_traces(messages, [_rec("hi")])

        assert out[0]["content"] == "orphan"
        assert "→ ok" in out[2]["content"]

    def test_turn_with_no_tools_renders_none_block(self):
        messages = _msgs(("hi", "hello"))
        out = attach_traces(messages, [{"user_text": "hi", "tools": []}])

        assert out[1]["content"] == "hello\n\n[Tools I called this turn: none]"

    def test_skill_is_carried_into_the_attached_block(self):
        messages = _msgs(("add two todos", "Added both."))
        out = attach_traces(messages, [_rec("add two todos", skill="time-management")])

        assert "as time-management" in out[1]["content"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_turn_trace.py -k AttachTraces -v
```

Expected: FAIL — `ImportError: cannot import name 'attach_traces'`.

- [ ] **Step 3: Implement the join**

Append to `src/services/turn_trace.py`:

```python
def _pair_indices(messages: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """Indices of adjacent (user, assistant) message pairs, oldest first.

    ``save_turn`` always appends the two together, but the sliding window can
    begin mid-pair, so unpaired messages at either end are skipped.
    """
    pairs: list[tuple[int, int]] = []
    i = 0
    while i < len(messages) - 1:
        if (
            messages[i].get("role") == "user"
            and messages[i + 1].get("role") == "assistant"
        ):
            pairs.append((i, i + 1))
            i += 2
        else:
            i += 1
    return pairs


def attach_traces(
    messages: list[dict[str, Any]], records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach each turn's trace to the assistant message that turn produced.

    Both sequences are chronological and pair 1:1 -- every path through
    ``_run_agent_turn`` calls ``save_turn`` and then ``_emit_turn_audit``
    with the same ``original_text``.  They can still diverge two ways:
    conversation decay truncates the note from the *front* while the log
    keeps everything, and a crash between those two calls leaves a message
    pair with no record.

    So the walk runs from the tail, where the two agree, matching on exact
    ``user_text``.  On a mismatch the *pair* is skipped and nothing is
    attached, which absorbs the missing-record case while leaving surplus
    older records unconsumed.

    The invariant: a mismatch yields a missing trace, never a wrong one.
    Attaching someone else's trace would be a worse version of the bug this
    ship exists to fix, because it would arrive dressed as evidence.
    """
    out = [dict(m) for m in messages]
    pairs = _pair_indices(out)

    i = len(pairs) - 1
    j = len(records) - 1
    while i >= 0 and j >= 0:
        user_idx, assistant_idx = pairs[i]
        if out[user_idx].get("content") == records[j].get("user_text"):
            trace = render_trace(records[j])
            existing = out[assistant_idx].get("content", "")
            out[assistant_idx]["content"] = f"{existing}\n\n{trace}"
            i -= 1
            j -= 1
        else:
            i -= 1  # this pair has no record -- attach nothing, never guess
    return out
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_turn_trace.py -v
```

Expected: PASS, 27 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/turn_trace.py apps/vault-server/tests/test_turn_trace.py
git commit -m "feat(turn-trace): join traces to their turns, never guessing"
```

---

### Task 5: Wire traces into `assemble_context`

Push, not pull (spec §2): the trace has to arrive without the agent choosing to ask for it.

**Files:**
- Modify: `src/services/memory_service.py` (`__init__`, `assemble_context`)
- Modify: `src/main.py:75-79`
- Test: `tests/test_memory_service.py`

**Interfaces:**
- Consumes: `read_turn_records` (Task 2), `attach_traces` (Task 4).
- Produces: `MemoryService(vault, vault_path, timezone="Asia/Jerusalem", logs_dir=None)`. `ConversationContext.messages` carries traces when `logs_dir` is set. The dataclass shape is unchanged.

- [ ] **Step 1: Write the failing test**

Add `import json` to the file's imports (beside the existing `import datetime`), then append:

```python
class TestAssembleContextTraces:
    def _memory_with_logs(self, vault_service, vault_path, tmp_path):
        return MemoryService(
            vault=vault_service,
            vault_path=vault_path,
            timezone="Asia/Jerusalem",
            logs_dir=tmp_path / "logs",
        )

    def test_no_logs_dir_leaves_messages_untouched(self, memory_service):
        memory_service.save_turn(999, "add a todo", "Added it.", [])

        context = memory_service.assemble_context(999)

        assert context.messages[1]["content"] == "Added it."

    def test_trace_is_attached_to_the_assistant_message(
        self, vault_service, vault_path, tmp_path,
    ):
        memory = self._memory_with_logs(vault_service, vault_path, tmp_path)
        memory.save_turn(999, "add a todo", "Added it.", [])

        today = datetime.datetime.now(memory.tz).strftime("%Y-%m-%d")
        logs = tmp_path / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "agent-turns.jsonl").write_text(json.dumps({
            "ts": f"{today}T10:00:00+0300",
            "chat_id": 999,
            "skill": "time-management",
            "user_text": "add a todo",
            "tools": [{
                "name": "daily_add_task",
                "params": {"text": "Order dog food"},
                "result_summary": {"ok": True, "data": {}},
            }],
        }, ensure_ascii=False) + "\n", encoding="utf-8")

        context = memory.assemble_context(999)

        assistant = context.messages[1]["content"]
        assert assistant.startswith("Added it.")
        assert "as time-management" in assistant
        assert 'daily_add_task(text="Order dog food") → ok' in assistant

    def test_missing_log_file_is_not_an_error(
        self, vault_service, vault_path, tmp_path,
    ):
        memory = self._memory_with_logs(vault_service, vault_path, tmp_path)
        memory.save_turn(999, "add a todo", "Added it.", [])

        context = memory.assemble_context(999)

        assert context.messages[1]["content"] == "Added it."
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_memory_service.py -k AssembleContextTraces -v
```

Expected: FAIL — `MemoryService.__init__() got an unexpected keyword argument 'logs_dir'`.

- [ ] **Step 3: Add `logs_dir` and attach traces**

In `src/services/memory_service.py`, add the import beside the existing ones:

```python
from src.services.turn_trace import attach_traces, read_turn_records
```

Widen `__init__` (keep every existing line; `logs_dir` is optional so existing callers and tests are unaffected):

```python
    def __init__(
        self,
        vault: VaultService,
        vault_path: Path,
        timezone: str = "Asia/Jerusalem",
        logs_dir: Path | None = None,
    ):
        self.vault = vault
        self.vault_path = Path(vault_path)
        self.tz = pytz.timezone(timezone)
        # Where agent-turns.jsonl lives. None disables per-turn tool traces,
        # which is what every caller that predates Ship 3 gets.
        self.logs_dir = Path(logs_dir) if logs_dir else None
        self.window_size = 20  # messages before decay
        self.graph: dict[str, dict] = {}
        self._claude: Any = None  # Set after init for summarization
```

Replace the body of `assemble_context`:

```python
    def assemble_context(self, chat_id: int) -> ConversationContext:
        """Build the full context for an agent loop call.

        Combines: conversation history (short-term), vault state snapshot
        (mid-term), and relevant knowledge + preferences (long-term).

        Each turn's tool calls are attached to the assistant message that
        turn produced, so the agent reads what it actually did rather than
        inferring it from the tools its *current* skill happens to hold.
        """
        conversation = self.load_conversation(chat_id)
        messages = conversation["messages"]

        if self.logs_dir is not None:
            today = datetime.datetime.now(self.tz).strftime("%Y-%m-%d")
            records = read_turn_records(self.logs_dir, chat_id, today)
            messages = attach_traces(messages, records)

        vault_snapshot = self._build_vault_snapshot(conversation)
        knowledge = self._gather_relevant_knowledge(conversation)

        return ConversationContext(
            messages=messages,
            summary=conversation["summary"],
            vault_snapshot=vault_snapshot,
            knowledge=knowledge,
        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_memory_service.py -k AssembleContextTraces -v
```

Expected: PASS, 3 tests.

- [ ] **Step 5: Pass `logs_dir` from the app**

In `src/main.py`, extend the `MemoryService(...)` construction at `:75`:

```python
    memory = MemoryService(
        vault=vault,
        vault_path=settings.vault_path,
        timezone=settings.vault_timezone,
        logs_dir=settings.logs_dir,
    )
```

- [ ] **Step 6: Run the full suite**

```bash
python -m pytest tests/ -q
```

Expected: PASS, no regressions.

- [ ] **Step 7: Commit**

```bash
git add apps/vault-server/src/services/memory_service.py \
        apps/vault-server/src/main.py \
        apps/vault-server/tests/test_memory_service.py
git commit -m "feat(memory): attach per-turn tool traces in assemble_context"
```

---

### Task 6: The mirror invariant

The guidelines already forbid *claiming* an unconfirmed write. Spec §6 adds the complement. These land in the **cached** static prefix, so they cost nothing per turn.

**Files:**
- Modify: `src/services/agent_service.py` (`_static_guidelines`)
- Test: `tests/test_agent_service.py`

**Interfaces:**
- Consumes: the trace vocabulary from Task 3 (the guideline text quotes the header verbatim).
- Produces: nothing other tasks read.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_service.py`:

```python
class TestMirrorInvariantGuidelines:
    def test_static_prefix_forbids_unchecked_denial(self, agent):
        prefix = agent._build_static_prefix()
        assert "Never deny a past action without checking" in prefix

    def test_static_prefix_warns_that_tool_lists_change(self, agent):
        prefix = agent._build_static_prefix()
        assert "what you can do now, not what you did earlier" in prefix

    def test_static_prefix_forbids_reasoning_from_absence(self, agent):
        prefix = agent._build_static_prefix()
        assert "no record, not proof of inaction" in prefix
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_agent_service.py -k MirrorInvariantGuidelines -v
```

Expected: FAIL — three assertion errors.

- [ ] **Step 3: Add the guidelines**

In `_static_guidelines`, immediately after the last `## Reporting writes` bullet (the one beginning `"- If a tool result is missing a field you expected"`), insert:

```python
            "",
            "## Reporting past actions",
            "- Never deny a past action without checking. The [Tools I called this turn] blocks above record what you actually did — read them before saying you did not do something.",
            "- Your current tool list is what you can do now, not what you did earlier. Skills change between turns; a tool absent from your list now may have been available when you acted.",
            "- A turn with no trace block means no record, not proof of inaction. Use a read tool before denying.",
            "- A call marked 'proposed, awaiting confirmation — NOT executed' did not run. Never report it as done.",
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_agent_service.py -k MirrorInvariantGuidelines -v
```

Expected: PASS, 3 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_agent_service.py
git commit -m "feat(agent): forbid denying a past action without checking"
```

---

### Task 7: Regression test for 2026-08-20, and docs

Reconstruct the failure end to end. The test cannot assert the model's behaviour — it pins the context, which is the half we control.

**Files:**
- Test: `tests/test_memory_service.py`
- Modify: `CLAUDE.md`
- Modify: `docs/plans/2026-08-21-time-management-phase2-capture-design.md`

**Interfaces:**
- Consumes: everything from Tasks 1–6.
- Produces: nothing.

- [ ] **Step 1: Write the regression test**

Append to `tests/test_memory_service.py`:

```python
class TestBugBRegression:
    """2026-08-20: two todos were added under `time-management`, then the
    router sent the follow-up question to `mazkir`, whose tool list has no
    task-creation tool.  The agent inspected its *current* tools, concluded
    it had never added them, and added them again.

    One iteration, zero tool calls.  What was missing was not a capability
    but the fact of what it had done -- so this pins that fact into context.
    """

    def test_the_denial_turn_sees_both_writes(
        self, vault_service, vault_path, tmp_path,
    ):
        memory = MemoryService(
            vault=vault_service,
            vault_path=vault_path,
            timezone="Asia/Jerusalem",
            logs_dir=tmp_path / "logs",
        )
        chat_id = 424242

        memory.save_turn(
            chat_id,
            "add order dog food and bring the bicycle to repair shop",
            "Added both to today's note.",
            [],
        )
        memory.save_turn(chat_id, "where did you add those?", "", [])

        today = datetime.datetime.now(memory.tz).strftime("%Y-%m-%d")
        logs = tmp_path / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "agent-turns.jsonl").write_text(json.dumps({
            "ts": f"{today}T14:22:00+0300",
            "chat_id": chat_id,
            "skill": "time-management",
            "user_text": "add order dog food and bring the bicycle to repair shop",
            "tools": [
                {
                    "name": "daily_add_task",
                    "params": {"text": "Order dog food"},
                    "result_summary": {"ok": True, "data": {}},
                },
                {
                    "name": "daily_add_task",
                    "params": {"text": "Bring the bicycle to repair shop"},
                    "result_summary": {"ok": True, "data": {}},
                },
            ],
        }, ensure_ascii=False) + "\n", encoding="utf-8")

        context = memory.assemble_context(chat_id)

        # The write turn's assistant message now carries both calls...
        write_turn = context.messages[1]["content"]
        assert 'daily_add_task(text="Order dog food") → ok' in write_turn
        assert 'daily_add_task(text="Bring the bicycle to repair shop") → ok' in write_turn
        assert "as time-management" in write_turn

        # ...and the question that triggered the denial follows it.
        assert context.messages[2]["content"] == "where did you add those?"
```

- [ ] **Step 2: Run it**

```bash
python -m pytest tests/test_memory_service.py -k BugBRegression -v
```

Expected: PASS.

- [ ] **Step 3: Run every suite**

```bash
cd ~/dev/mazkir && npx turbo test
```

Expected: PASS. Baseline before this ship: **862 server, 133 bot, 21 webapp**. The bot and webapp are untouched.

- [ ] **Step 4: Update `CLAUDE.md`**

In the **Observability (P3)** section, after the `trace_id in logs` bullet, add:

```markdown
- **`agent-turns.jsonl` is memory, not just audit (Ship 3):** `MemoryService.assemble_context` reads this chat's records for today and attaches each turn's calls to the assistant message that turn produced, as `[Tools I called this turn, as <skill>: …]`. The agent therefore reads what it actually did instead of inferring it from its *current* skill's tool list — the failure that made it deny its own writes on 2026-08-20. `services/turn_trace.py` owns reading, rendering and the join; it never raises, so a torn log line costs one trace rather than the turn. The join matches on exact `user_text` walking from the tail, and **a mismatch attaches nothing** — a wrong trace would be a worse version of the bug, arriving dressed as evidence. Deleting `data/logs/` now costs the agent this memory; the prompt invariant ("never deny a past action without checking") is the safety net that holds without it.
```

In the **Agent tool risk levels** section, leave the tool lists alone — Ship 3 adds no tools.

- [ ] **Step 5: Mark Ship 3 shipped in the phase doc**

In `docs/plans/2026-08-21-time-management-phase2-capture-design.md`, update the header block to add a line beneath `**Ship 1 shipped:**`:

```markdown
**Ship 2 shipped:** PR #11 (`934c003`).
**Ship 3 shipped:** see `docs/superpowers/specs/2026-09-05-ship3-agent-action-memory-design.md`.
```

And in §9, replace the `**Fix, two halves:**` list's first item with:

```markdown
1. **Make the past factual.** *(Shipped, Ship 3.)* `MemoryService.assemble_context` reads this chat's records from `data/logs/agent-turns.jsonl` and attaches each turn's tool calls to the assistant message that turn produced. `services/turn_trace.py` owns it.
```

Leave the `**Secondary finding**` paragraph, but append: *"Fixed in Ship 3 — `_run_agent_turn` now takes `skill` and records it."*

- [ ] **Step 6: Commit**

```bash
git add apps/vault-server/tests/test_memory_service.py CLAUDE.md \
        docs/plans/2026-08-21-time-management-phase2-capture-design.md
git commit -m "test(memory): pin the 2026-08-20 denial; document Ship 3"
```

---

## Verification

Before opening the PR:

```bash
cd ~/dev/mazkir && npx turbo test
```

All three suites green. Server count should be **862 + 36 new**: 2 (Task 1, audit `skill`) + 6 (Task 2, reading) + 11 (Task 3, rendering) + 10 (Task 4, the join) + 3 (Task 5, `assemble_context`) + 3 (Task 6, guidelines) + 1 (Task 7, regression).

Manual check against the live log, read-only:

```bash
cd apps/vault-server && source venv/bin/activate && python -c "
from src.services.turn_trace import read_turn_records, render_trace
import collections
recs = [r for d in ['2026-09-01','2026-09-02'] for r in read_turn_records('../../data/logs', <YOUR_CHAT_ID>, d)]
print(len(recs), 'records')
for r in recs[-3:]:
    print(render_trace(r))
"
```

Substitute your own chat id. Confirm the blocks are compact — no note bodies, no base64 — and that any gated call reads `NOT executed`.
