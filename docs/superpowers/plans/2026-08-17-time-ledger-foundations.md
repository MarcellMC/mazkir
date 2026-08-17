# Time Ledger Foundations — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the event store a correct, faceted time ledger — fixing the three bugs that corrupt it today, and adding the two-facet schema plus the target config the weekly readout will run on.

**Architecture:** Three phases, strictly ordered. Phase A fixes correctness bugs in the existing calendar-sync and event-update paths; these are independently shippable and Phase B is gated on them. Phase B makes habits completable several times a day, counting completions from the habit note's `## Completion Log` rather than a mutable counter. Phase C introduces `time-matrix.yaml`, renames `activity_category` to `activity`, and adds the `category` / `tags` / `state` fields to the event shape.

**Tech Stack:** Python 3.14, FastAPI, pytest, PyYAML, Pydantic settings. Vault is markdown-with-YAML-frontmatter; the event store is JSON at `data/events/{date}.json`.

**Spec:** `docs/plans/2026-07-27-time-management-system-design.md`

## Global Constraints

- Every tool returns the `{ok, data|error, _items}` shape from `src/services/tool_response.py`. Never return a bare dict.
- Post-hooks never raise. Failures are logged at WARNING **and** recorded on the tool result (§3.4). Exceptions must not propagate out of a hook.
- Run tests from `apps/vault-server` with the venv active: `source venv/bin/activate && python -m pytest tests/ -q`.
- `tests/conftest.py` redirects `LOGS_DIR` and `MAZKIR_AUDIT_LOG_PATH` to temp dirs. Never write to `data/logs/` from a test.
- Fixtures available from `conftest.py`: `vault_path` (temp vault with templates + samples), `vault_service` (a real `VaultService` on it), `mock_services` (dict of MagicMocks).
- No category or activity name may be hardcoded in Python. All vocabularies come from `time-matrix.yaml`.
- Commit after every task. Conventional-commit prefixes (`fix:`, `feat:`, `test:`, `refactor:`).

## Scope note

This plan covers **Phase 1 of v1**: the ledger's data correctness and schema. The remaining v1 surface — classification (§3.2), the three write paths (§3.1), retrospective NL parsing (§4.3), the batch edit/preview flow (§4.1–4.2), gap computation (§5), and the Telegram readout (§6) — is a second plan, because it depends on every schema decision here being settled and because it produces a separately demoable increment ("the human can log and read"). This plan produces "the stored data is correct and correctly shaped".

## File Structure

**Created:**
- `apps/vault-server/src/services/time_matrix.py` — loads and validates `time-matrix.yaml`. Sole owner of the target vocabulary.
- `apps/vault-server/src/services/completion_log.py` — parses/renders the habit note's `## Completion Log` section. Pure functions, no I/O.
- `apps/vault-server/tests/test_sync_to_calendar_hook.py`
- `apps/vault-server/tests/test_time_matrix.py`
- `apps/vault-server/tests/test_completion_log.py`
- `memory/00-system/time-matrix.yaml` — user data, seeded once.

**Modified:**
- `apps/vault-server/src/services/hooks/sync_to_calendar.py` — persist returned event id; record sync outcome.
- `apps/vault-server/src/services/events_service.py` — `update_event` returns persisted state; new fields defaulted on save; legacy field normalised on read.
- `apps/vault-server/src/services/agent_service.py` — `_static_guidelines` gains the write-reporting rule; `_tool_complete_habit` rewritten for `daily_target`.
- `apps/vault-server/src/services/merger_service.py`, `generation_service.py`, `api/routes/generate.py` — `activity_category` → `activity`.
- `apps/vault-server/src/api/routes/daily.py` — read `scheduled_at` with a `scheduled_time` fallback.
- `memory/00-system/templates/_habit_.md` — `scheduled_time` → `scheduled_at`; add `daily_target`, `activity`.
- `packages/shared-types/src/events.ts` — mirror the renamed/added fields.

---

## Phase A — Correctness bugs

### Task 1: Persist the calendar event id returned by sync

Root cause of the duplicate-calendar-entry bug: `sync_habit` creates an event and returns its id, but the hook discards it, so `google_event_id` stays null and the next completion creates another event.

**Files:**
- Modify: `apps/vault-server/src/services/hooks/sync_to_calendar.py:70-77`
- Test: `apps/vault-server/tests/test_sync_to_calendar_hook.py` (create)

**Interfaces:**
- Consumes: `sync_to_calendar(params: dict, output: dict, ctx: Any) -> None` (existing signature, unchanged).
- Produces: nothing new for later tasks; the hook now calls `vault.update_file(path, {"google_event_id": <id>})` when the item had none.

- [ ] **Step 1: Write the failing tests**

Create `apps/vault-server/tests/test_sync_to_calendar_hook.py`:

```python
"""Tests for the sync_to_calendar post-hook."""
from unittest.mock import MagicMock

from src.services.hooks.sync_to_calendar import sync_to_calendar


def _ctx(calendar, vault, tool_name="complete_habit"):
    return {
        "calendar": calendar,
        "vault": vault,
        "tool": {"schema": {"name": tool_name}},
    }


def _output(path="20-habits/dog-walk.md"):
    return {"ok": True, "data": {}, "_items": [path]}


def test_persists_new_event_id_to_the_habit_file():
    calendar = MagicMock()
    calendar.is_initialized = True
    calendar.sync_habit.return_value = "gcal_evt_1"

    vault = MagicMock()
    vault.read_file.return_value = {
        "metadata": {"type": "habit", "name": "Dog Walk", "google_event_id": None}
    }

    sync_to_calendar({}, _output(), _ctx(calendar, vault))

    vault.update_file.assert_called_once_with(
        "20-habits/dog-walk.md", {"google_event_id": "gcal_evt_1"}
    )


def test_existing_event_id_is_marked_complete_not_recreated():
    calendar = MagicMock()
    calendar.is_initialized = True

    vault = MagicMock()
    vault.read_file.return_value = {
        "metadata": {"type": "habit", "name": "Workout", "google_event_id": "gcal_old"}
    }

    sync_to_calendar({}, _output("20-habits/workout.md"), _ctx(calendar, vault))

    calendar.mark_event_complete.assert_called_once_with("gcal_old")
    calendar.sync_habit.assert_not_called()
    vault.update_file.assert_not_called()


def test_two_completions_create_only_one_calendar_event():
    """Regression: three dog walks produced three calendar entries."""
    calendar = MagicMock()
    calendar.is_initialized = True
    calendar.sync_habit.return_value = "gcal_evt_1"

    stored = {"type": "habit", "name": "Dog Walk", "google_event_id": None}
    vault = MagicMock()
    vault.read_file.side_effect = lambda p: {"metadata": dict(stored)}
    vault.update_file.side_effect = lambda p, updates: stored.update(updates)

    sync_to_calendar({}, _output(), _ctx(calendar, vault))
    sync_to_calendar({}, _output(), _ctx(calendar, vault))

    assert calendar.sync_habit.call_count == 1
    calendar.mark_event_complete.assert_called_once_with("gcal_evt_1")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_sync_to_calendar_hook.py -v`
Expected: `test_persists_new_event_id_to_the_habit_file` and `test_two_completions_create_only_one_calendar_event` FAIL (`update_file` never called; `sync_habit.call_count == 2`). `test_existing_event_id_is_marked_complete_not_recreated` already passes.

- [ ] **Step 3: Persist the returned id**

In `apps/vault-server/src/services/hooks/sync_to_calendar.py`, replace the tail of `sync_to_calendar` (currently lines 72-77):

```python
        event_id = None
        if item_type == "task":
            event_id = _maybe_await(calendar.sync_task(item))
        elif item_type == "habit":
            event_id = _maybe_await(calendar.sync_habit(item))

        if event_id and not meta.get("google_event_id"):
            vault.update_file(path, {"google_event_id": event_id})
    except Exception as e:
        logger.warning("sync_to_calendar hook failed: %s", e)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_sync_to_calendar_hook.py -v`
Expected: 3 passed.

- [ ] **Step 5: Run the full suite for regressions**

Run: `python -m pytest tests/ -q`
Expected: no new failures.

- [ ] **Step 6: Commit**

```bash
git add apps/vault-server/src/services/hooks/sync_to_calendar.py \
        apps/vault-server/tests/test_sync_to_calendar_hook.py
git commit -m "fix(calendar): persist google_event_id so repeat completions reuse one event"
```

---

### Task 2: Record the calendar-sync outcome on the tool result

Implements the first half of §3.4. Today a failed or skipped sync is only logged at WARNING, so the agent has no way to know it did not happen — which is how it claimed a sync it had not performed.

**Files:**
- Modify: `apps/vault-server/src/services/hooks/sync_to_calendar.py`
- Test: `apps/vault-server/tests/test_sync_to_calendar_hook.py`

**Interfaces:**
- Produces: on every invocation the hook sets `output["data"]["calendar_sync"]` to `{"ok": True, "event_id": str}` or `{"ok": False, "reason": str}`. Task 4's prompt rule and any later surface read this key.

- [ ] **Step 1: Write the failing tests**

Append to `apps/vault-server/tests/test_sync_to_calendar_hook.py`:

```python
def test_reports_when_calendar_is_not_configured():
    output = _output()
    sync_to_calendar({}, output, _ctx(None, MagicMock()))

    assert output["data"]["calendar_sync"] == {
        "ok": False,
        "reason": "calendar_not_configured",
    }


def test_reports_failure_when_sync_raises():
    calendar = MagicMock()
    calendar.is_initialized = True
    calendar.sync_habit.side_effect = RuntimeError("gcal down")

    vault = MagicMock()
    vault.read_file.return_value = {
        "metadata": {"type": "habit", "google_event_id": None}
    }

    output = _output()
    sync_to_calendar({}, output, _ctx(calendar, vault))

    assert output["data"]["calendar_sync"]["ok"] is False
    assert "gcal down" in output["data"]["calendar_sync"]["reason"]


def test_reports_success_with_the_event_id():
    calendar = MagicMock()
    calendar.is_initialized = True
    calendar.sync_habit.return_value = "gcal_evt_1"

    vault = MagicMock()
    vault.read_file.return_value = {
        "metadata": {"type": "habit", "google_event_id": None}
    }

    output = _output()
    sync_to_calendar({}, output, _ctx(calendar, vault))

    assert output["data"]["calendar_sync"] == {"ok": True, "event_id": "gcal_evt_1"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_sync_to_calendar_hook.py -v -k report`
Expected: 3 FAIL with `KeyError: 'calendar_sync'`.

- [ ] **Step 3: Add the recorder and stamp every exit path**

In `apps/vault-server/src/services/hooks/sync_to_calendar.py`, add above `sync_to_calendar`:

```python
def _record(output: dict, **fields) -> None:
    """Stamp the calendar-sync outcome onto the tool result.

    The agent is instructed never to claim a sync it cannot see, so every
    exit path from this hook must leave a verdict here.
    """
    data = output.get("data")
    if isinstance(data, dict):
        data["calendar_sync"] = fields
```

Then stamp each exit. The full rewritten body:

```python
def sync_to_calendar(params: dict, output: dict, ctx: Any) -> None:
    """Post-hook: push changes to Google Calendar (best-effort)."""
    try:
        calendar = (ctx or {}).get("calendar")
        if calendar is None or not getattr(calendar, "is_initialized", False):
            _record(output, ok=False, reason="calendar_not_configured")
            return
        if not output.get("ok", False):
            _record(output, ok=False, reason="tool_failed")
            return

        tool_name = ctx.get("tool", {}).get("schema", {}).get("name", "")

        if tool_name in _DELETE_TOOLS:
            _record(output, ok=False, reason="not_applicable")
            return

        items = output.get("_items") or []
        if not items:
            _record(output, ok=False, reason="no_items")
            return
        path = items[0]

        vault = ctx.get("vault")
        if vault is None:
            _record(output, ok=False, reason="vault_unavailable")
            return

        try:
            item = vault.read_file(path)
        except Exception:
            _record(output, ok=False, reason="path_unreadable")
            return
        meta = item.get("metadata", {})
        item_type = meta.get("type")

        if tool_name in _COMPLETE_TOOLS and meta.get("google_event_id"):
            _maybe_await(calendar.mark_event_complete(meta["google_event_id"]))
            _record(output, ok=True, event_id=meta["google_event_id"])
            return

        event_id = None
        if item_type == "task":
            event_id = _maybe_await(calendar.sync_task(item))
        elif item_type == "habit":
            event_id = _maybe_await(calendar.sync_habit(item))

        if event_id and not meta.get("google_event_id"):
            vault.update_file(path, {"google_event_id": event_id})

        if event_id:
            _record(output, ok=True, event_id=event_id)
        else:
            _record(output, ok=False, reason="no_event_created")
    except Exception as e:
        logger.warning("sync_to_calendar hook failed: %s", e)
        _record(output, ok=False, reason=str(e))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_sync_to_calendar_hook.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/hooks/sync_to_calendar.py \
        apps/vault-server/tests/test_sync_to_calendar_hook.py
git commit -m "feat(calendar): record sync outcome on the tool result"
```

---

### Task 3: `update_event` returns the persisted event

Second half of the silent-failure bug. `update_event` returns `{"updated": True, "event_id": ...}`, so the agent knows only that *something* happened and narrates the time it asked for — which is how "moved back to 15:59" was reported for a write that had not taken effect.

**Files:**
- Modify: `apps/vault-server/src/services/events_service.py:124-151`
- Modify: `apps/vault-server/src/services/agent_service.py:2755-2763` (`_tool_update_event` tail)
- Test: `apps/vault-server/tests/test_events_service.py`

**Interfaces:**
- Consumes: `EventsService.update_event(date: str, event_id: str, updates: dict) -> dict`
- Produces: on success returns `{"updated": True, "event": dict}` where `event` is the event as persisted; on failure `{"error": str}` (unchanged). `_tool_update_event` passes this straight into `ok()`, so the agent sees `data.event`.

- [ ] **Step 1: Write the failing test**

Append to `apps/vault-server/tests/test_events_service.py`:

```python
def test_update_event_returns_the_persisted_event(tmp_path):
    from src.services.events_service import EventsService

    svc = EventsService(tmp_path / "events")
    svc.save_events("2026-08-16", [{
        "id": "evt_1",
        "name": "Dog walk",
        "start_time": "2026-08-16T16:29:00",
        "end_time": "2026-08-16T17:09:00",
    }])

    result = svc.update_event(
        "2026-08-16", "evt_1", {"start_time": "2026-08-16T15:59:00"}
    )

    assert result["updated"] is True
    assert result["event"]["start_time"] == "2026-08-16T15:59:00"
    assert result["event"] == svc.get_events("2026-08-16")[0]


def test_update_event_missing_id_still_returns_error(tmp_path):
    from src.services.events_service import EventsService

    svc = EventsService(tmp_path / "events")
    svc.save_events("2026-08-16", [{"id": "evt_1", "name": "Dog walk"}])

    result = svc.update_event("2026-08-16", "evt_nope", {"name": "x"})

    assert "error" in result
    assert "event" not in result
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_events_service.py -v -k persisted`
Expected: FAIL with `KeyError: 'event'`.

- [ ] **Step 3: Return the persisted event**

In `apps/vault-server/src/services/events_service.py`, replace the success return inside `update_event`:

```python
                event.update(updates)
                self.save_events(date, events)
                return {"updated": True, "event": event}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_events_service.py -v`
Expected: all passed.

- [ ] **Step 5: Check the tool handler passes it through**

`_tool_update_event` ends with `return ok(result, items=items)`, so `data` now carries `event` automatically. Confirm no caller depended on `data.event_id`:

Run: `grep -rn '"event_id"' apps/vault-server/src apps/telegram-bot/src packages/shared-types/src`
Expected: matches only in `events_service.py` (the error path and `attach_photo`) and tool schemas — none reading `data.event_id` off an update response. If any consumer does, add `"event_id": event_id` alongside `"event"` rather than removing it.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: no new failures.

- [ ] **Step 7: Commit**

```bash
git add apps/vault-server/src/services/events_service.py \
        apps/vault-server/tests/test_events_service.py
git commit -m "fix(events): return the persisted event from update_event"
```

---

### Task 4: Teach the agent to report only verified writes

Completes §3.4. The mechanisms exist after Tasks 2 and 3; this makes the agent use them.

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py:1763-1801` (`_static_guidelines`)
- Test: `apps/vault-server/tests/test_agent_service.py`

**Interfaces:**
- Consumes: `AgentService._static_guidelines() -> list[str]` (a `@staticmethod`).
- Produces: no API change. The returned list gains a `## Reporting writes` block.

- [ ] **Step 1: Write the failing test**

Append to `apps/vault-server/tests/test_agent_service.py`:

```python
def test_static_guidelines_forbid_unverified_write_claims():
    from src.services.agent_service import AgentService

    text = "\n".join(AgentService._static_guidelines())

    assert "## Reporting writes" in text
    assert "calendar_sync" in text
    assert "ok: true" in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_agent_service.py -v -k unverified`
Expected: FAIL on `assert "## Reporting writes" in text`.

- [ ] **Step 3: Add the rule**

In `apps/vault-server/src/services/agent_service.py`, insert into the list returned by `_static_guidelines()`, immediately after the error-codes block and before `"## Guidelines"`:

```python
            "## Reporting writes",
            "- Never report an action as done unless the tool result says ok: true.",
            "- Describe the state the tool returned, not the state you asked for. update_event returns data.event as persisted — quote that, not your requested value.",
            "- Tool results may carry data.calendar_sync. If it is ok: false, tell the user the calendar was NOT updated and give the reason. Never claim a sync you cannot see in the result.",
            "- If a tool result is missing a field you expected, say so rather than filling it in from your own request.",
            "",
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_agent_service.py -v -k unverified`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: no new failures. (If a prompt-snapshot test exists it will need its expected text refreshed.)

- [ ] **Step 6: Commit**

```bash
git add apps/vault-server/src/services/agent_service.py \
        apps/vault-server/tests/test_agent_service.py
git commit -m "feat(agent): forbid reporting writes the tool result does not confirm"
```

---

### Task 5: Unify `scheduled_at` / `scheduled_time`

`GET /day` reads `scheduled_at`; `_habit_.md` writes `scheduled_time`. Habits created from the template never appear on the schedule. Canonical name is **`scheduled_at`** — the route and `VaultService.create_habit` already use it.

**Files:**
- Modify: `memory/00-system/templates/_habit_.md`
- Modify: `apps/vault-server/src/api/routes/daily.py:96`
- Modify: `apps/vault-server/tests/conftest.py` (`HABIT_TEMPLATE`, ~line 60)
- Test: `apps/vault-server/tests/test_daily_route.py`

**Interfaces:**
- Produces: habit frontmatter key `scheduled_at` (`"HH:MM"` or absent). Readers use `meta.get("scheduled_at") or meta.get("scheduled_time")` during the transition.

- [ ] **Step 1: Write the failing test**

Append to `apps/vault-server/tests/test_daily_route.py`:

```python
def test_habit_with_legacy_scheduled_time_still_appears(vault_service, vault_path):
    """Files written before the rename use scheduled_time; don't drop them."""
    (vault_path / "20-habits" / "legacy.md").write_text(
        "---\n"
        "type: habit\n"
        "name: Legacy habit\n"
        "status: active\n"
        "scheduled_time: '07:30'\n"
        "---\n\n# Legacy habit\n",
        encoding="utf-8",
    )

    habits = vault_service.list_active_habits()
    legacy = next(h for h in habits if h["metadata"]["name"] == "Legacy habit")
    meta = legacy["metadata"]

    assert (meta.get("scheduled_at") or meta.get("scheduled_time")) == "07:30"
```

- [ ] **Step 2: Run the test to verify it passes trivially, then add the route test**

Run: `python -m pytest tests/test_daily_route.py -v -k legacy`
Expected: PASS (it asserts the fallback expression, not the route). Now add the test that actually fails — append:

```python
def test_daily_schedule_includes_legacy_scheduled_time_habits(monkeypatch, vault_path):
    from fastapi.testclient import TestClient
    from src.services.vault_service import VaultService
    import src.main as main

    (vault_path / "20-habits" / "legacy.md").write_text(
        "---\n"
        "type: habit\n"
        "name: Legacy habit\n"
        "status: active\n"
        "scheduled_time: '07:30'\n"
        "---\n\n# Legacy habit\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(main, "get_vault", lambda: VaultService(vault_path))
    monkeypatch.setattr(main, "get_calendar", lambda: None)

    client = TestClient(main.app)
    body = client.get("/daily").json()

    titles = [item["title"] for item in body["schedule"]]
    assert "Legacy habit" in titles
```

- [ ] **Step 3: Run it to verify it fails**

Run: `python -m pytest tests/test_daily_route.py -v -k legacy_scheduled_time_habits`
Expected: FAIL — `"Legacy habit"` not in `titles`, because the route reads only `scheduled_at`.

- [ ] **Step 4: Add the fallback in the route**

In `apps/vault-server/src/api/routes/daily.py`, replace line 96:

```python
        scheduled_at = meta.get("scheduled_at") or meta.get("scheduled_time")
```

- [ ] **Step 5: Rename the field in both templates**

In `memory/00-system/templates/_habit_.md`, change `scheduled_time: null` to:

```yaml
scheduled_at: null
daily_target: 1
activity: null
```

Apply the identical change to `HABIT_TEMPLATE` in `apps/vault-server/tests/conftest.py` so the fixture matches the real template.

- [ ] **Step 6: Migrate the five existing habit files**

```bash
cd ~/dev/mazkir/memory
grep -l 'scheduled_time:' 20-habits/*.md | xargs -r sed -i 's/^scheduled_time:/scheduled_at:/'
grep -rn 'scheduled_time\|scheduled_at\|daily_target' 20-habits/*.md
```

Expected: no `scheduled_time` remains. Add `daily_target: 1` to any habit lacking it (Task 7 defaults it at read time, so this is cosmetic).

- [ ] **Step 7: Run the tests**

Run: `python -m pytest tests/test_daily_route.py tests/test_habit_operations.py -v`
Expected: all passed.

- [ ] **Step 8: Commit**

```bash
git add apps/vault-server/src/api/routes/daily.py \
        apps/vault-server/tests/conftest.py \
        apps/vault-server/tests/test_daily_route.py
git commit -m "fix(daily): read scheduled_at with a scheduled_time fallback"
cd memory && git add 00-system/templates/_habit_.md 20-habits/ \
  && git commit -m "chore(habits): rename scheduled_time to scheduled_at, add daily_target"
```

> **Note:** `memory/` is a separate git repo. Commit it separately, as above.

---

## Phase B — Multi-completions per day

> **Gated on Phase A.** `daily_target > 1` makes multiple same-day completions normal, which would fire the Task 1 bug twice daily on the very habit that motivated this change.

### Task 6: Completion Log parser and renderer

The habit template has carried an unused `## Completion Log` section since the start. It becomes the source of truth for today's progress — counting entries rather than keeping a mutable counter that can drift.

**Files:**
- Create: `apps/vault-server/src/services/completion_log.py`
- Test: `apps/vault-server/tests/test_completion_log.py` (create)

**Interfaces:**
- Produces, used by Task 7:
  - `parse_completion_log(body: str) -> list[CompletionEntry]`
  - `append_completion(body: str, at: datetime) -> str` — returns the new body
  - `count_on(entries: list[CompletionEntry], day: date) -> int`
  - `@dataclass CompletionEntry: at: datetime`

Line format, one per completion, newest last:

```markdown
## Completion Log
- 2026-08-16T07:12:00
- 2026-08-16T19:40:00
```

- [ ] **Step 1: Write the failing tests**

Create `apps/vault-server/tests/test_completion_log.py`:

```python
"""Tests for the habit ## Completion Log section."""
import datetime as dt

from src.services.completion_log import (
    CompletionEntry,
    append_completion,
    count_on,
    parse_completion_log,
)

BODY = """\
# Dog Walk

## Goal


## Completion Log
- 2026-08-16T07:12:00
- 2026-08-16T19:40:00
- 2026-08-15T08:00:00

## Notes
"""


def test_parses_entries_in_file_order():
    entries = parse_completion_log(BODY)
    assert [e.at for e in entries] == [
        dt.datetime(2026, 8, 16, 7, 12),
        dt.datetime(2026, 8, 16, 19, 40),
        dt.datetime(2026, 8, 15, 8, 0),
    ]


def test_missing_section_parses_as_empty():
    assert parse_completion_log("# Dog Walk\n\n## Notes\n") == []


def test_malformed_lines_are_skipped():
    body = "## Completion Log\n- not a date\n- 2026-08-16T07:12:00\n"
    assert [e.at for e in parse_completion_log(body)] == [
        dt.datetime(2026, 8, 16, 7, 12)
    ]


def test_count_on_counts_only_that_day():
    entries = parse_completion_log(BODY)
    assert count_on(entries, dt.date(2026, 8, 16)) == 2
    assert count_on(entries, dt.date(2026, 8, 15)) == 1
    assert count_on(entries, dt.date(2026, 8, 14)) == 0


def test_append_adds_a_line_and_preserves_other_sections():
    new_body = append_completion(BODY, dt.datetime(2026, 8, 17, 6, 5))

    assert "- 2026-08-17T06:05:00" in new_body
    assert count_on(parse_completion_log(new_body), dt.date(2026, 8, 17)) == 1
    assert "## Notes" in new_body
    assert "## Goal" in new_body


def test_append_creates_the_section_when_absent():
    new_body = append_completion("# Dog Walk\n", dt.datetime(2026, 8, 17, 6, 5))

    assert "## Completion Log" in new_body
    assert count_on(parse_completion_log(new_body), dt.date(2026, 8, 17)) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_completion_log.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'src.services.completion_log'`.

- [ ] **Step 3: Write the module**

Create `apps/vault-server/src/services/completion_log.py`:

```python
"""Parser/renderer for the `## Completion Log` section of a habit note.

Source of truth for how many times a habit was completed on a given day.
Counting entries beats a mutable counter: the log cannot drift out of sync
with itself, and it doubles as an audit trail.

Format — one ISO timestamp per line, file order preserved:

    ## Completion Log
    - 2026-08-16T07:12:00
    - 2026-08-16T19:40:00
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from src.services.daily_tasks import replace_or_append_section

_SECTION_RE = re.compile(
    r"##\s+Completion Log\s*\n(.*?)(?=^##\s|\Z)",
    re.DOTALL | re.IGNORECASE | re.MULTILINE,
)
_ENTRY_RE = re.compile(r"^\s*-\s+(?P<ts>\S+)\s*$")


@dataclass(frozen=True)
class CompletionEntry:
    at: dt.datetime


def parse_completion_log(body: str) -> list[CompletionEntry]:
    """Return every well-formed entry, in file order. Malformed lines are skipped."""
    match = _SECTION_RE.search(body)
    if not match:
        return []

    entries: list[CompletionEntry] = []
    for line in match.group(1).splitlines():
        m = _ENTRY_RE.match(line)
        if not m:
            continue
        try:
            entries.append(CompletionEntry(at=dt.datetime.fromisoformat(m.group("ts"))))
        except ValueError:
            continue
    return entries


def count_on(entries: list[CompletionEntry], day: dt.date) -> int:
    """How many of `entries` fall on `day`."""
    return sum(1 for e in entries if e.at.date() == day)


def render_completion_log(entries: list[CompletionEntry]) -> str:
    """Render the section body (without its heading)."""
    lines = [f"- {e.at.isoformat()}" for e in entries]
    return "\n".join(lines) + "\n"


def append_completion(body: str, at: dt.datetime) -> str:
    """Return `body` with one more completion recorded at `at`."""
    entries = parse_completion_log(body)
    entries.append(CompletionEntry(at=at.replace(microsecond=0)))
    return replace_or_append_section(
        body, "Completion Log", render_completion_log(entries)
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_completion_log.py -v`
Expected: 6 passed.

If `test_append_adds_a_line_and_preserves_other_sections` fails on section ordering, check `replace_or_append_section` in `src/services/daily_tasks.py:157` — it replaces in place when the heading exists and appends at the end otherwise, which is the behaviour these tests assume.

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/completion_log.py \
        apps/vault-server/tests/test_completion_log.py
git commit -m "feat(habits): add Completion Log parser and renderer"
```

---

### Task 7: `daily_target` — allow N completions per day

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py:2805-2851` (`_tool_complete_habit`)
- Test: `apps/vault-server/tests/test_agent_service.py`

**Interfaces:**
- Consumes: `parse_completion_log`, `count_on`, `append_completion` from Task 6; `VaultService.read_file`, `update_file`, `write_file`, `update_tokens`.
- Produces: `_tool_complete_habit` returns `ok({habit, old_streak, new_streak, longest_streak, tokens_earned, completions_today, daily_target}, items=[path])`, or `err(ALREADY_DONE, ...)` only once `completions_today >= daily_target`.

Semantics from spec §7:
- Tokens awarded on **every** completion.
- Streak advances **only** when the completion reaches `daily_target`.
- `last_completed` set on every completion (kept for the calendar hook and `/day`).
- `daily_target` defaults to `1` when absent, so untouched habits behave exactly as before.

- [ ] **Step 1: Write the failing tests**

Append to `apps/vault-server/tests/test_agent_service.py`:

```python
def _habit_file(name="Dog Walk", target=2, streak=3, log=""):
    return {
        "metadata": {
            "type": "habit",
            "name": name,
            "daily_target": target,
            "streak": streak,
            "longest_streak": 5,
            "last_completed": None,
            "tokens_per_completion": 5,
            "google_event_id": None,
        },
        "content": f"# {name}\n\n## Completion Log\n{log}\n",
    }


@pytest.fixture
def _resolve_ok(monkeypatch):
    """complete_habit resolves the name through resolver.resolve_item."""
    monkeypatch.setattr(
        "src.services.resolver.resolve_item",
        lambda kind, name, vault: {
            "ok": True, "data": {"path": "20-habits/dog-walk.md"}
        },
    )


def test_second_completion_of_the_day_is_allowed(agent, mock_services, _resolve_ok):
    """Regression: dog walking needs two completions a day."""
    import datetime as dt
    _, vault, _, _, _ = mock_services
    today = dt.date.today().isoformat()
    vault.read_file.return_value = _habit_file(log=f"- {today}T07:12:00\n")

    result = agent._tool_complete_habit({"habit_name": "Dog Walk"})

    assert result["ok"] is True
    assert result["data"]["completions_today"] == 2


def test_completion_beyond_the_daily_target_is_rejected(agent, mock_services, _resolve_ok):
    import datetime as dt
    _, vault, _, _, _ = mock_services
    today = dt.date.today().isoformat()
    vault.read_file.return_value = _habit_file(
        log=f"- {today}T07:12:00\n- {today}T19:40:00\n"
    )

    result = agent._tool_complete_habit({"habit_name": "Dog Walk"})

    assert result["ok"] is False
    assert result["error"]["code"] == "ALREADY_DONE"


def test_streak_advances_only_when_the_target_is_met(agent, mock_services, _resolve_ok):
    import datetime as dt
    _, vault, _, _, _ = mock_services
    today = dt.date.today().isoformat()

    vault.read_file.return_value = _habit_file(log="")
    first = agent._tool_complete_habit({"habit_name": "Dog Walk"})
    assert first["data"]["new_streak"] == 3  # unchanged: 1 of 2

    vault.read_file.return_value = _habit_file(log=f"- {today}T07:12:00\n")
    second = agent._tool_complete_habit({"habit_name": "Dog Walk"})
    assert second["data"]["new_streak"] == 4  # 2 of 2 — target met


def test_tokens_are_awarded_on_every_completion(agent, mock_services, _resolve_ok):
    _, vault, _, _, _ = mock_services
    vault.read_file.return_value = _habit_file(log="")

    result = agent._tool_complete_habit({"habit_name": "Dog Walk"})

    assert result["data"]["tokens_earned"] == 5
    vault.update_tokens.assert_called_once()


def test_habit_without_daily_target_behaves_as_before(agent, mock_services, _resolve_ok):
    import datetime as dt
    _, vault, _, _, _ = mock_services
    today = dt.date.today().isoformat()
    habit = _habit_file(target=None, log=f"- {today}T07:12:00\n")
    del habit["metadata"]["daily_target"]
    vault.read_file.return_value = habit

    result = agent._tool_complete_habit({"habit_name": "Dog Walk"})

    assert result["ok"] is False
    assert result["error"]["code"] == "ALREADY_DONE"
```

The `agent` fixture (`tests/test_agent_service.py:38`) and `mock_services` (`:11`) already exist. Note `mock_services` in this file returns a **tuple** `(claude, vault, memory, calendar, events)` — it shadows the dict-returning fixture of the same name in `conftest.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_agent_service.py -v -k "completion or streak or daily_target"`
Expected: `test_second_completion_of_the_day_is_allowed` FAILS with `ALREADY_DONE`; `test_streak_advances_only_when_the_target_is_met` FAILS (streak advances on the first).

- [ ] **Step 3: Rewrite the handler**

In `apps/vault-server/src/services/agent_service.py`, replace the whole body of `_tool_complete_habit`:

```python
    def _tool_complete_habit(self, params: dict) -> dict:
        import datetime as dt
        from src.services.completion_log import (
            append_completion,
            count_on,
            parse_completion_log,
        )
        from src.services.resolver import resolve_item

        resolved = resolve_item("habit", params["habit_name"], self.vault)
        if not resolved["ok"]:
            return resolved

        path = resolved["data"]["path"]
        habit = self.vault.read_file(path)
        meta = habit["metadata"]
        body = habit.get("content", "")

        now = dt.datetime.now()
        today = now.date()
        target = int(meta.get("daily_target") or 1)
        done_today = count_on(parse_completion_log(body), today)

        if done_today >= target:
            return err(
                ErrorCode.ALREADY_DONE,
                f"Habit '{meta.get('name', '')}' already completed "
                f"{done_today}/{target} times today",
                details={
                    "path": path,
                    "streak": meta.get("streak", 0),
                    "completions_today": done_today,
                    "daily_target": target,
                },
            )

        new_body = append_completion(body, now)
        completions_today = done_today + 1
        target_met = completions_today >= target

        old_streak = meta.get("streak", 0)
        new_streak = old_streak + 1 if target_met else old_streak
        longest = max(meta.get("longest_streak", 0), new_streak)

        self.vault.write_file(path, {
            **meta,
            "streak": new_streak,
            "longest_streak": longest,
            "last_completed": today.isoformat(),
            "updated": today.isoformat(),
        }, new_body)

        tokens = meta.get("tokens_per_completion", 5)
        self.vault.update_tokens(tokens, meta.get("name", "habit"))

        return ok(
            {
                "habit": meta.get("name", ""),
                "old_streak": old_streak,
                "new_streak": new_streak,
                "longest_streak": longest,
                "tokens_earned": tokens,
                "completions_today": completions_today,
                "daily_target": target,
            },
            items=[path],
        )
```

Note the calendar call is gone from the handler — the `sync_to_calendar` post-hook already owns it (Tasks 1–2), and doing it in both places was one of the duplication sources.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_agent_service.py -v -k "completion or streak or daily_target"`
Expected: 5 passed.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: no new failures. Existing `complete_habit` tests that asserted `update_file` was called now need `write_file` — update them; the handler must write body and frontmatter together.

- [ ] **Step 6: Set the real habit's target**

```bash
cd ~/dev/mazkir/memory
sed -i 's/^daily_target: 1$/daily_target: 2/' 20-habits/dog-walk.md
grep -n 'daily_target' 20-habits/dog-walk.md
```

Expected: `daily_target: 2`.

- [ ] **Step 7: Commit**

```bash
git add apps/vault-server/src/services/agent_service.py \
        apps/vault-server/tests/test_agent_service.py
git commit -m "feat(habits): allow daily_target completions per day"
cd memory && git add 20-habits/dog-walk.md \
  && git commit -m "chore(habits): dog walk needs two completions a day"
```

---

### Task 8: Expose completion progress on `list_habits`

Without this the agent can report "done!" without knowing whether one or both walks happened, and the Telegram habit view cannot show progress.

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py` (`_tool_list_habits`)
- Test: `apps/vault-server/tests/test_agent_service.py`

**Interfaces:**
- Produces: each habit dict in `list_habits` gains `completions_today: int` and `daily_target: int`.

- [ ] **Step 1: Write the failing test**

```python
def test_list_habits_reports_completion_progress(agent, mock_services):
    import datetime as dt
    _, vault, _, _, _ = mock_services
    today = dt.date.today().isoformat()
    vault.list_active_habits.return_value = [{
        "path": "20-habits/dog-walk.md",
        "metadata": {
            "type": "habit", "name": "Dog Walk",
            "daily_target": 2, "streak": 3, "frequency": "daily",
        },
        "content": f"## Completion Log\n- {today}T07:12:00\n",
    }]

    result = agent._tool_list_habits({})
    habit = result["data"]["habits"][0]

    assert habit["completions_today"] == 1
    assert habit["daily_target"] == 2
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_agent_service.py -v -k completion_progress`
Expected: FAIL with `KeyError: 'completions_today'`.

- [ ] **Step 3: Add the fields**

Replace `_tool_list_habits` (`apps/vault-server/src/services/agent_service.py:2121`) in full:

```python
    def _tool_list_habits(self, params: dict) -> dict:
        import datetime as dt
        from src.services.completion_log import count_on, parse_completion_log

        today = dt.date.today()
        habits = self.vault.list_active_habits()
        return ok(
            {
                "habits": [
                    {
                        "name": h["metadata"].get("name", ""),
                        "path": h["path"],
                        "streak": h["metadata"].get("streak", 0),
                        "frequency": h["metadata"].get("frequency", "daily"),
                        "completions_today": count_on(
                            parse_completion_log(h.get("content", "")), today
                        ),
                        "daily_target": int(h["metadata"].get("daily_target") or 1),
                    }
                    for h in habits
                ]
            }
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_agent_service.py -v -k completion_progress`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/agent_service.py \
        apps/vault-server/tests/test_agent_service.py
git commit -m "feat(habits): report completions_today from list_habits"
```

---

## Phase C — Ledger schema and targets

### Task 9: `time-matrix.yaml` loader and validator

Sole owner of the activity and category vocabularies. Nothing else in Python may name a bucket.

**Files:**
- Create: `apps/vault-server/src/services/time_matrix.py`
- Create: `memory/00-system/time-matrix.yaml`
- Test: `apps/vault-server/tests/test_time_matrix.py` (create)

**Interfaces:**
- Produces, used by every later task and by Plan 2:
  - `@dataclass(frozen=True) TimeMatrix` with `activities: dict[str, float]`, `categories: dict[str, float]`, `calendars: dict[str, dict[str, str]]`
  - `TimeMatrix.target_hours(axis: str, name: str, elapsed_hours: float) -> float`
  - `load_time_matrix(path: Path) -> TimeMatrix` — raises `TimeMatrixError`
  - `class TimeMatrixError(ValueError)`

- [ ] **Step 1: Write the failing tests**

Create `apps/vault-server/tests/test_time_matrix.py`:

```python
"""Tests for time-matrix.yaml loading and validation."""
import pytest

from src.services.time_matrix import (
    TimeMatrixError,
    load_time_matrix,
)

VALID = """\
version: 2
activities:
  sleep: {share: 60}
  dev:   {share: 40}
categories:
  personal: {share: 70}
  work:     {share: 30}
calendars:
  "Work":   {activity: dev, category: work}
"""


def _write(tmp_path, text):
    p = tmp_path / "time-matrix.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_loads_both_axes(tmp_path):
    m = load_time_matrix(_write(tmp_path, VALID))

    assert m.activities == {"sleep": 60.0, "dev": 40.0}
    assert m.categories == {"personal": 70.0, "work": 30.0}
    assert m.calendars == {"Work": {"activity": "dev", "category": "work"}}


def test_activity_shares_must_sum_to_100(tmp_path):
    bad = VALID.replace("dev:   {share: 40}", "dev:   {share: 30}")

    with pytest.raises(TimeMatrixError, match="activities.*sum to 100.*90"):
        load_time_matrix(_write(tmp_path, bad))


def test_category_shares_must_sum_to_100(tmp_path):
    bad = VALID.replace("work:     {share: 30}", "work:     {share: 40}")

    with pytest.raises(TimeMatrixError, match="categories.*sum to 100.*110"):
        load_time_matrix(_write(tmp_path, bad))


def test_negative_share_is_rejected(tmp_path):
    bad = VALID.replace("dev:   {share: 40}", "dev:   {share: -40}")

    with pytest.raises(TimeMatrixError, match="negative"):
        load_time_matrix(_write(tmp_path, bad))


def test_calendar_rule_must_reference_known_names(tmp_path):
    bad = VALID.replace("{activity: dev, category: work}", "{activity: nope, category: work}")

    with pytest.raises(TimeMatrixError, match="unknown activity 'nope'"):
        load_time_matrix(_write(tmp_path, bad))


def test_missing_file_raises(tmp_path):
    with pytest.raises(TimeMatrixError, match="not found"):
        load_time_matrix(tmp_path / "absent.yaml")


def test_target_hours_scales_to_elapsed(tmp_path):
    m = load_time_matrix(_write(tmp_path, VALID))

    assert m.target_hours("activities", "dev", 168.0) == pytest.approx(67.2)
    assert m.target_hours("activities", "dev", 96.0) == pytest.approx(38.4)
    assert m.target_hours("categories", "work", 96.0) == pytest.approx(28.8)


def test_target_hours_rejects_unknown_axis(tmp_path):
    m = load_time_matrix(_write(tmp_path, VALID))

    with pytest.raises(TimeMatrixError, match="unknown axis"):
        m.target_hours("domains", "work", 96.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_time_matrix.py -v`
Expected: collection error — module does not exist.

- [ ] **Step 3: Write the module**

Create `apps/vault-server/src/services/time_matrix.py`:

```python
"""Loader and validator for `memory/00-system/time-matrix.yaml`.

Sole owner of the activity and category vocabularies. No bucket name is
hardcoded anywhere in Python — the matrix is user data, which is what lets
this ship to someone who never drew the original sketch.

Both axes are complete partitions of the week, so each must sum to 100%.
That is enforced on load with a hard error rather than left to be noticed:
"my table doesn't add up" is the failure mode this validation exists for.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

_TOLERANCE = 0.01
_AXES = ("activities", "categories")


class TimeMatrixError(ValueError):
    """The matrix file is missing, malformed, or does not balance."""


@dataclass(frozen=True)
class TimeMatrix:
    activities: dict[str, float]
    categories: dict[str, float]
    calendars: dict[str, dict[str, str]]

    def target_hours(self, axis: str, name: str, elapsed_hours: float) -> float:
        """Target hours for `name` on `axis`, scaled to hours elapsed so far."""
        if axis not in _AXES:
            raise TimeMatrixError(f"unknown axis '{axis}'; expected one of {_AXES}")
        shares: dict[str, float] = getattr(self, axis)
        if name not in shares:
            raise TimeMatrixError(f"unknown {axis[:-1]} '{name}'")
        return shares[name] / 100.0 * elapsed_hours


def _parse_axis(raw: dict, axis: str) -> dict[str, float]:
    section = raw.get(axis)
    if not isinstance(section, dict) or not section:
        raise TimeMatrixError(f"'{axis}' section is missing or empty")

    shares: dict[str, float] = {}
    for name, body in section.items():
        if not isinstance(body, dict) or "share" not in body:
            raise TimeMatrixError(f"{axis}.{name} has no 'share'")
        try:
            share = float(body["share"])
        except (TypeError, ValueError):
            raise TimeMatrixError(f"{axis}.{name} share is not a number") from None
        if share < 0:
            raise TimeMatrixError(f"{axis}.{name} share is negative ({share})")
        shares[name] = share

    total = sum(shares.values())
    if abs(total - 100.0) > _TOLERANCE:
        raise TimeMatrixError(
            f"'{axis}' shares must sum to 100, got {total:g}"
        )
    return shares


def _parse_calendars(raw: dict, activities: dict, categories: dict) -> dict:
    section = raw.get("calendars") or {}
    if not isinstance(section, dict):
        raise TimeMatrixError("'calendars' must be a mapping")

    rules: dict[str, dict[str, str]] = {}
    for cal_name, rule in section.items():
        if not isinstance(rule, dict):
            raise TimeMatrixError(f"calendars.{cal_name} must be a mapping")
        activity = rule.get("activity")
        category = rule.get("category")
        if activity not in activities:
            raise TimeMatrixError(
                f"calendars.{cal_name}: unknown activity '{activity}'"
            )
        if category not in categories:
            raise TimeMatrixError(
                f"calendars.{cal_name}: unknown category '{category}'"
            )
        rules[cal_name] = {"activity": activity, "category": category}
    return rules


def load_time_matrix(path: Path) -> TimeMatrix:
    """Read and validate the matrix. Raises TimeMatrixError on any problem."""
    path = Path(path)
    if not path.exists():
        raise TimeMatrixError(f"time matrix not found at {path}")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise TimeMatrixError(f"time matrix is not valid YAML: {e}") from e

    if not isinstance(raw, dict):
        raise TimeMatrixError("time matrix must be a YAML mapping")

    activities = _parse_axis(raw, "activities")
    categories = _parse_axis(raw, "categories")
    calendars = _parse_calendars(raw, activities, categories)

    return TimeMatrix(
        activities=activities, categories=categories, calendars=calendars
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_time_matrix.py -v`
Expected: 8 passed.

- [ ] **Step 5: Seed the real matrix**

Create `memory/00-system/time-matrix.yaml`:

```yaml
version: 2
# Shares are % of the 168-hour week. Each axis must sum to 100.
# Seed values from the 2026-06-20 sketch; expect these to be wrong and to be
# corrected from real data after a few weeks of logging.

activities:
  sleep:        { share: 33 }
  dev:          { share: 17 }   # day job + pet projects, split by category
  org:          { share:  9 }
  eat:          { share:  7 }
  house:        { share:  7 }
  meetings:     { share:  6 }
  slack:        { share:  5 }
  commute:      { share:  4 }
  fitness:      { share:  3 }
  dog:          { share:  3 }
  music:        { share:  3 }
  unstructured: { share:  3 }

categories:
  personal: { share: 58 }
  work:     { share: 21 }
  house:    { share: 21 }

calendars:
  "Mazkir": { activity: dev, category: personal }
```

Verify it loads:

```bash
cd ~/dev/mazkir/apps/vault-server && source venv/bin/activate && python -c "
from pathlib import Path
from src.services.time_matrix import load_time_matrix
m = load_time_matrix(Path.home() / 'dev/mazkir/memory/00-system/time-matrix.yaml')
print('activities', sum(m.activities.values()))
print('categories', sum(m.categories.values()))
"
```

Expected: `activities 100.0` and `categories 100.0`.

- [ ] **Step 6: Commit**

```bash
git add apps/vault-server/src/services/time_matrix.py \
        apps/vault-server/tests/test_time_matrix.py
git commit -m "feat(time-matrix): add loader with sum-to-100 validation"
cd memory && git add 00-system/time-matrix.yaml \
  && git commit -m "chore(time-matrix): seed targets from the 2026-06-20 sketch"
```

---

### Task 10: Rename `activity_category` to `activity`

Mechanical but wide. Old event files keep their `activity_category` key and their `gym|walk|cafe` values; a read-time normaliser moves the key so nothing 500s, and the stale values simply read as unmatched.

**Files:**
- Modify: `apps/vault-server/src/services/merger_service.py:18,153,172,184`
- Modify: `apps/vault-server/src/services/events_service.py:106`
- Modify: `apps/vault-server/src/services/generation_service.py:35,155-156`
- Modify: `apps/vault-server/src/api/routes/generate.py:20,56`
- Modify: `packages/shared-types/src/events.ts`
- Test: `apps/vault-server/tests/test_events_service.py`, `tests/test_merger_service.py`

**Interfaces:**
- Produces: event dicts use `activity` everywhere. `EventsService.get_events` maps a legacy `activity_category` key onto `activity` on read.

- [ ] **Step 1: Write the failing test**

Append to `apps/vault-server/tests/test_events_service.py`:

```python
def test_legacy_activity_category_is_read_as_activity(tmp_path):
    import json
    from src.services.events_service import EventsService

    events_dir = tmp_path / "events"
    events_dir.mkdir()
    (events_dir / "2026-05-01.json").write_text(json.dumps([{
        "id": "evt_old",
        "name": "Coffee",
        "activity_category": "cafe",
    }]), encoding="utf-8")

    svc = EventsService(events_dir)
    event = svc.get_events("2026-05-01")[0]

    assert event["activity"] == "cafe"
    assert "activity_category" not in event


def test_new_events_are_saved_with_activity(tmp_path):
    from src.services.events_service import EventsService

    svc = EventsService(tmp_path / "events")
    svc.save_events("2026-08-17", [{"id": "evt_1", "activity": "dev"}])

    assert svc.get_events("2026-08-17")[0]["activity"] == "dev"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_events_service.py -v -k activity`
Expected: `test_legacy_activity_category_is_read_as_activity` FAILS with `KeyError: 'activity'`.

- [ ] **Step 3: Add the read-time normaliser**

In `apps/vault-server/src/services/events_service.py`, inside `get_events`, after the JSON is parsed and before returning:

```python
    @staticmethod
    def _normalize(event: dict[str, Any]) -> dict[str, Any]:
        """Migrate legacy keys on read. Files stay untouched until next save."""
        if "activity_category" in event and "activity" not in event:
            event["activity"] = event.pop("activity_category")
        return event
```

and change the return in `get_events`:

```python
        try:
            return [self._normalize(e) for e in json.loads(path.read_text())]
        except Exception as e:
            logger.error(f"Failed to read events for {date}: {e}")
            return []
```

- [ ] **Step 4: Rename the remaining call sites**

```bash
cd ~/dev/mazkir
grep -rln 'activity_category' apps/vault-server/src apps/telegram-web-app/src packages/shared-types/src \
  | xargs -r sed -i 's/activity_category/activity/g'
grep -rn 'activity_category' apps/ packages/
```

Expected: the only remaining match is `EventsService._normalize`, which must keep the legacy string. If `sed` renamed it, restore that one line by hand.

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/ -q`
Expected: all passed. `tests/test_generation_service.py` and `tests/test_merger_service.py` reference the old key and will have been renamed by the same `sed`.

- [ ] **Step 6: Check the webapp still builds**

Run: `cd ~/dev/mazkir/apps/telegram-web-app && npx tsc -b`
Expected: no new errors. (Pre-existing `import.meta.env` errors are known and unrelated — compare against `git stash` output if unsure.)

- [ ] **Step 7: Commit**

```bash
cd ~/dev/mazkir
git add apps/ packages/
git commit -m "refactor(events): rename activity_category to activity"
```

---

### Task 11: Add `category`, `tags` and `state` to the event shape

Completes the block model from spec §2.1.

**Files:**
- Modify: `apps/vault-server/src/services/events_service.py:47-60` (`save_events`)
- Modify: `packages/shared-types/src/events.ts`
- Test: `apps/vault-server/tests/test_events_service.py`

**Interfaces:**
- Produces: every saved event carries `activity: str | None`, `category: str | None`, `tags: list[str]`, `state: "suggested" | "approved"`. `state` defaults to `"suggested"` — nothing counts toward a readout until approved (§3.3).

- [ ] **Step 1: Write the failing tests**

Append to `apps/vault-server/tests/test_events_service.py`:

```python
def test_new_fields_are_defaulted_on_save(tmp_path):
    from src.services.events_service import EventsService

    svc = EventsService(tmp_path / "events")
    svc.save_events("2026-08-17", [{"id": "evt_1", "name": "Dog walk"}])

    event = svc.get_events("2026-08-17")[0]

    assert event["activity"] is None
    assert event["category"] is None
    assert event["tags"] == []
    assert event["state"] == "suggested"


def test_explicit_values_are_preserved(tmp_path):
    from src.services.events_service import EventsService

    svc = EventsService(tmp_path / "events")
    svc.save_events("2026-08-17", [{
        "id": "evt_1",
        "activity": "dev",
        "category": "personal",
        "tags": ["mazkir"],
        "state": "approved",
    }])

    event = svc.get_events("2026-08-17")[0]

    assert event["activity"] == "dev"
    assert event["category"] == "personal"
    assert event["tags"] == ["mazkir"]
    assert event["state"] == "approved"


def test_legacy_events_default_to_suggested(tmp_path):
    """Events written before this change must not silently count as logged."""
    import json
    from src.services.events_service import EventsService

    events_dir = tmp_path / "events"
    events_dir.mkdir()
    (events_dir / "2026-05-01.json").write_text(
        json.dumps([{"id": "evt_old", "name": "Coffee"}]), encoding="utf-8"
    )

    svc = EventsService(events_dir)

    assert svc.get_events("2026-05-01")[0]["state"] == "suggested"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_events_service.py -v -k "defaulted or preserved or legacy_events"`
Expected: 3 FAIL with `KeyError`.

- [ ] **Step 3: Default the fields on save and on read**

In `apps/vault-server/src/services/events_service.py`, extend `save_events`'s setdefault block:

```python
        for event in events:
            if "id" not in event:
                event["id"] = f"evt_{uuid4().hex[:8]}"
            event.setdefault("photos", [])
            event.setdefault("assets", None)
            event.setdefault("source_ids", {})
            event.setdefault("activity", None)
            event.setdefault("category", None)
            event.setdefault("tags", [])
            event.setdefault("state", "suggested")
```

and extend `_normalize` so files written before this change also read correctly:

```python
    @staticmethod
    def _normalize(event: dict[str, Any]) -> dict[str, Any]:
        """Migrate legacy keys on read. Files stay untouched until next save."""
        if "activity_category" in event and "activity" not in event:
            event["activity"] = event.pop("activity_category")
        event.setdefault("activity", None)
        event.setdefault("category", None)
        event.setdefault("tags", [])
        event.setdefault("state", "suggested")
        return event
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_events_service.py -v`
Expected: all passed.

- [ ] **Step 5: Mirror the shape in shared types**

In `packages/shared-types/src/events.ts`, add to the event interface:

```typescript
  activity: string | null;
  category: string | null;
  tags: string[];
  state: 'suggested' | 'approved';
```

Run: `cd ~/dev/mazkir && npx tsc -b packages/shared-types`
Expected: clean.

- [ ] **Step 6: Run the full suite**

Run: `cd ~/dev/mazkir/apps/vault-server && python -m pytest tests/ -q`
Expected: all passed.

- [ ] **Step 7: Commit**

```bash
cd ~/dev/mazkir
git add apps/vault-server/src/services/events_service.py \
        apps/vault-server/tests/test_events_service.py \
        packages/shared-types/src/events.ts
git commit -m "feat(events): add activity, category, tags and state to the block shape"
```

---

## Verification

After Task 11, confirm the whole thing holds together:

- [ ] `cd ~/dev/mazkir/apps/vault-server && source venv/bin/activate && python -m pytest tests/ -q` — all green
- [ ] `cd ~/dev/mazkir && npx turbo test` — all workspaces green
- [ ] `git -C ~/dev/mazkir status --porcelain` and `git -C ~/dev/mazkir/memory status --porcelain` — both clean
- [ ] Start the server and complete the dog walk twice:

```bash
cd ~/dev/mazkir/apps/vault-server && source venv/bin/activate \
  && python -m uvicorn src.main:app --port 8000 &
curl -s -XPOST localhost:8000/message -H 'content-type: application/json' \
  -d '{"text":"walked the dog","chat_id":1}' | jq '.response'
curl -s -XPOST localhost:8000/message -H 'content-type: application/json' \
  -d '{"text":"walked the dog again","chat_id":1}' | jq '.response'
```

Expected: both succeed; the second reports 2/2 and a streak increment. Check Google Calendar shows **one** dog-walk entry, not two. Check `memory/20-habits/dog-walk.md` now has a populated `## Completion Log` and a non-null `google_event_id`.

## What this plan does not cover

Deliberately deferred to the second plan, all from spec v1:

- §3.2 classification (calendar-name rules → Haiku → remembered title mappings)
- §3.1 the three write paths (inferred / live timer / after-the-fact)
- §4.3 retrospective NL phrasing ("just got back from…")
- §4.1–4.2 batch edit preview, accept-all, cross-midnight splitting
- §5 gap computation and the coverage/concurrent lines
- §6 the `/week` readout and the Telegram approval keyboard
- §2.1 **habit/task/goal `category` migration.** Task 5 adds `activity: null` to the habit template, but the existing `category` values (`personal`, `health`, `productivity`, `career`, `learning`) are not yet remapped onto the category facet (`work`, `personal`, `house`). Must happen before Plan 2 has habit completions mint blocks. Remember `personal` is valid in both vocabularies, so an unmigrated file reads as correct while meaning something else — the migration has to be explicit per file, not inferred.

## Spec deviations to note during review

1. **`default_duration_minutes` is not added.** `VaultService.create_habit` already accepts `duration_minutes` and writes it to habit frontmatter, so §7's new field would duplicate an existing one. Plan 2 should read `duration_minutes`. Update the spec to match.
2. **The calendar call was removed from `_tool_complete_habit`** (Task 7 Step 3). The `sync_to_calendar` post-hook already covers it, and running both was a duplication source the spec's §3.1 rule ("calendar is written from the block, never independently") anticipates.
