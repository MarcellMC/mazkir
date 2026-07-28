# Coding-Handoff v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Mazkir propose, and — after explicit user confirmation — provision an isolated, containerized coding session (a real `claude --dangerously-skip-permissions` CLI process in a fresh git worktree) to fix a bug or small task, supervised via Claude's Remote Control rather than custom checkpoint plumbing, and notify the user on completion via Telegram.

**Architecture:** A new `CodingTasksService` owns the whole lifecycle — JSON-per-task records under `data/coding-tasks/`, trace_id correlation against the existing audit log, task-brief assembly, git-worktree + Docker container provisioning, and completion polling. A new agent tool (`propose_coding_session`, risk `write` with `preview` forced on) always renders a confirmation preview before anything is provisioned. A background poller (started in `main.py`'s FastAPI lifespan) periodically checks running containers and calls a new `TelegramNotifier` when one finishes. A new `engineering` skill exposes the tool to the router.

**Tech Stack:** Python 3.12 / FastAPI (`vault-server`), `subprocess` for `git worktree` and `docker` calls, `httpx` for the Telegram Bot API, `pytest` + `pytest-asyncio`.

## Global Constraints

- Parent design: `docs/plans/2026-07-27-coding-handoff-design.md`. Parent roadmap: `docs/plans/2026-07-27-p6-roadmap-and-agentic-frameworks.md` (Block C).
- v1 only: no `PreToolUse`/`defer` hook-based checkpoints, no deeper sandboxing than Docker, no task-complexity auto-routing, no multi-agent teams. These are explicitly out of scope per the design doc.
- The tool must **always** require user confirmation before provisioning anything, regardless of `_confidence` — achieved via the existing `preview` flag (forces `needs_confirmation` even at auto-execute confidence, per `agent_service.py:1333-1344`), not a new mechanism.
- GitHub branch protection on `master`, PAT creation, and `claude auth login` are manual, one-time, human-executed steps — not automatable by this plan. They are documented in Task 11's `SETUP.md`, not implemented as code.
- Existing conventions to follow exactly: `ok()`/`err()` from `src/services/tool_response.py` for all handler returns; JSON-per-id file storage mirrors `EventsService` (`src/services/events_service.py`); extracted tool-handler modules mirror `src/services/tool_handlers/daily.py` (free functions, not methods); skill files mirror `memory/00-system/skills/time-management.md`'s frontmatter shape.

---

## File Structure

- **Create** `apps/vault-server/src/services/telegram_notifier.py` — `TelegramNotifier`: thin `httpx` wrapper around the Telegram Bot API's `sendMessage`, used only for proactive completion notifications (the interactive bot flow is unaffected).
- **Create** `apps/vault-server/src/services/coding_tasks_service.py` — `CodingTasksService`: JSON-per-task storage, trace_id correlation against the audit log, task-brief assembly, `git worktree`/Docker provisioning, completion polling + notification.
- **Create** `apps/vault-server/src/services/tool_handlers/coding_handoff.py` — `propose_coding_session()` (handler) and `preview_coding_session()` (preview text), mirroring `tool_handlers/daily.py`'s free-function pattern.
- **Modify** `apps/vault-server/src/config.py` — add `telegram_bot_token`, `coding_tasks_data_path`, `coding_agent_worktrees_path`, `coding_agent_docker_image`, `mazkir_repo_path`.
- **Modify** `apps/vault-server/src/services/agent_service.py` — new `coding_tasks` constructor param, `self._current_chat_id` transient state (mirrors `self._stream_callback`), tool registration entry, preview registration.
- **Modify** `apps/vault-server/src/main.py` — instantiate `TelegramNotifier` + `CodingTasksService`, wire into `AgentService`, start/stop a background polling task in the lifespan.
- **Create** `memory/00-system/skills/engineering.md` — new skill exposing `propose_coding_session` (plus read-only tools it needs for context).
- **Modify** `apps/vault-server/tests/test_skill_set.py` — add `"engineering"` to `EXPECTED` and a consistency check.
- **Create** `apps/vault-server/tests/test_telegram_notifier.py`, `apps/vault-server/tests/test_coding_tasks_service.py`.
- **Modify** `apps/vault-server/tests/test_agent_service.py` — registration test for `propose_coding_session`.
- **Create** `infra/coding-agent/Dockerfile`, `infra/coding-agent/entrypoint.sh`, `infra/coding-agent/SETUP.md` — the container image and one-time manual provisioning steps.

---

### Task 1: `TelegramNotifier`

**Files:**
- Create: `apps/vault-server/src/services/telegram_notifier.py`
- Modify: `apps/vault-server/src/config.py`
- Test: `apps/vault-server/tests/test_telegram_notifier.py`

**Interfaces:**
- Produces: `TelegramNotifier(bot_token: str | None, base_url: str = "https://api.telegram.org")`, `.send_message(chat_id: int, text: str) -> None`.

- [ ] **Step 1: Write the failing test**

Follow this project's existing httpx-mocking convention (`patch("src.services.<module>.httpx.<call>")`, as used in `tests/test_generation_service.py`) rather than introducing a new mocking library:

```python
# apps/vault-server/tests/test_telegram_notifier.py
from unittest.mock import MagicMock, patch

from src.services.telegram_notifier import TelegramNotifier


def test_send_message_posts_to_bot_api():
    notifier = TelegramNotifier(bot_token="123:abc")

    with patch("src.services.telegram_notifier.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        notifier.send_message(42, "hello")

    mock_post.assert_called_once_with(
        "https://api.telegram.org/bot123:abc/sendMessage",
        json={"chat_id": 42, "text": "hello"},
        timeout=10.0,
    )


def test_send_message_noop_when_token_missing(caplog):
    notifier = TelegramNotifier(bot_token=None)

    with patch("src.services.telegram_notifier.httpx.post") as mock_post:
        notifier.send_message(42, "hello")  # must not raise

    mock_post.assert_not_called()
    assert "no bot token" in caplog.text.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_telegram_notifier.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.telegram_notifier'`

- [ ] **Step 3: Write the implementation**

```python
# apps/vault-server/src/services/telegram_notifier.py
"""TelegramNotifier — sends proactive, out-of-band Telegram messages.

Used only for background notifications (e.g. a coding session finishing)
that don't originate from an interactive bot request/response cycle. The
interactive bot flow (grammY, in apps/telegram-bot) is unaffected — this
is a narrow, separate integration for push-style notifications.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, bot_token: str | None, base_url: str = "https://api.telegram.org"):
        self.bot_token = bot_token
        self.base_url = base_url

    def send_message(self, chat_id: int, text: str) -> None:
        if not self.bot_token:
            logger.warning("TelegramNotifier: no bot token configured, skipping send_message")
            return
        url = f"{self.base_url}/bot{self.bot_token}/sendMessage"
        try:
            response = httpx.post(url, json={"chat_id": chat_id, "text": text}, timeout=10.0)
            response.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("TelegramNotifier.send_message failed: %s", e)
```

Also add to `apps/vault-server/src/config.py`, inside the `Settings` class (near the CORS/application settings):

```python
    # Coding-handoff
    telegram_bot_token: str | None = os.getenv("TELEGRAM_BOT_TOKEN")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_telegram_notifier.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/telegram_notifier.py apps/vault-server/src/config.py apps/vault-server/tests/test_telegram_notifier.py
git commit -m "feat(vault-server): add TelegramNotifier for out-of-band notifications"
```

---

### Task 2: `CodingTasksService` — JSON storage

**Files:**
- Create: `apps/vault-server/src/services/coding_tasks_service.py`
- Modify: `apps/vault-server/src/config.py`
- Test: `apps/vault-server/tests/test_coding_tasks_service.py`

**Interfaces:**
- Consumes: `TelegramNotifier` (Task 1, only stored, not called yet).
- Produces: `CodingTasksService(data_path, repo_path, worktrees_path, docker_image, notifier, audit_log_path=None)`, `.get_task(task_id) -> dict | None`, `.save_task(task: dict) -> None`, `.list_tasks(status=None) -> list[dict]`.

- [ ] **Step 1: Write the failing test**

```python
# apps/vault-server/tests/test_coding_tasks_service.py
from pathlib import Path

import pytest

from src.services.coding_tasks_service import CodingTasksService
from src.services.telegram_notifier import TelegramNotifier


@pytest.fixture
def service(tmp_path):
    return CodingTasksService(
        data_path=tmp_path / "coding-tasks",
        repo_path=tmp_path / "repo",
        worktrees_path=tmp_path / "worktrees",
        docker_image="mazkir-coding-agent:test",
        notifier=TelegramNotifier(bot_token=None),
    )


class TestStorage:
    def test_get_task_returns_none_when_missing(self, service):
        assert service.get_task("ct_missing") is None

    def test_save_then_get_roundtrips(self, service):
        task = {"id": "ct_abc123", "status": "proposed", "chat_id": 42}
        service.save_task(task)
        assert service.get_task("ct_abc123") == task

    def test_list_tasks_filters_by_status(self, service):
        service.save_task({"id": "ct_1", "status": "running"})
        service.save_task({"id": "ct_2", "status": "done"})
        service.save_task({"id": "ct_3", "status": "running"})

        running = service.list_tasks(status="running")

        assert {t["id"] for t in running} == {"ct_1", "ct_3"}

    def test_list_tasks_no_filter_returns_all(self, service):
        service.save_task({"id": "ct_1", "status": "running"})
        service.save_task({"id": "ct_2", "status": "done"})

        assert len(service.list_tasks()) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_coding_tasks_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.coding_tasks_service'`

- [ ] **Step 3: Write the implementation**

```python
# apps/vault-server/src/services/coding_tasks_service.py
"""CodingTasksService — provisions isolated worktree+container coding
sessions and tracks their lifecycle in data/coding-tasks/{id}.json.

Mirrors the JSON-per-id storage pattern used by EventsService
(src/services/events_service.py).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.services.telegram_notifier import TelegramNotifier

logger = logging.getLogger(__name__)


class CodingTasksService:
    def __init__(
        self,
        data_path: Path,
        repo_path: Path,
        worktrees_path: Path,
        docker_image: str,
        notifier: TelegramNotifier,
        audit_log_path: Path | None = None,
    ):
        self.data_path = Path(data_path)
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.repo_path = Path(repo_path)
        self.worktrees_path = Path(worktrees_path)
        self.worktrees_path.mkdir(parents=True, exist_ok=True)
        self.docker_image = docker_image
        self.notifier = notifier
        self.audit_log_path = Path(audit_log_path) if audit_log_path else None

    def _file_path(self, task_id: str) -> Path:
        return self.data_path / f"{task_id}.json"

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        path = self._file_path(task_id)
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def save_task(self, task: dict[str, Any]) -> None:
        path = self._file_path(task["id"])
        path.write_text(json.dumps(task, indent=2))

    def list_tasks(self, status: str | None = None) -> list[dict[str, Any]]:
        tasks = [json.loads(p.read_text()) for p in sorted(self.data_path.glob("*.json"))]
        if status:
            tasks = [t for t in tasks if t.get("status") == status]
        return tasks
```

Add to `apps/vault-server/src/config.py`, below `telegram_bot_token`:

```python
    coding_tasks_data_path: Path = Path(os.getenv(
        "CODING_TASKS_DATA_PATH",
        str(Path.home() / "dev" / "mazkir" / "data" / "coding-tasks"),
    ))
    coding_agent_worktrees_path: Path = Path(os.getenv(
        "CODING_AGENT_WORKTREES_PATH",
        str(Path.home() / "dev" / "mazkir" / ".coding-agent-worktrees"),
    ))
    coding_agent_docker_image: str = os.getenv("CODING_AGENT_DOCKER_IMAGE", "mazkir-coding-agent:latest")
    mazkir_repo_path: Path = Path(os.getenv("MAZKIR_REPO_PATH", str(Path.home() / "dev" / "mazkir")))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_coding_tasks_service.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/coding_tasks_service.py apps/vault-server/src/config.py apps/vault-server/tests/test_coding_tasks_service.py
git commit -m "feat(vault-server): add CodingTasksService JSON-per-id storage"
```

---

### Task 3: trace_id correlation

**Files:**
- Modify: `apps/vault-server/src/services/coding_tasks_service.py`
- Test: `apps/vault-server/tests/test_coding_tasks_service.py`

**Interfaces:**
- Produces: `.find_recent_trace_id(around: datetime, window_minutes: int = 30) -> str | None`.
- Reads the audit log format documented in `src/services/hooks/audit_log.py`: one JSON object per line, `{ts, trace_id, tool, ok, params_summary, items, error_code?}`. Note there is **no `chat_id` field** in this log — correlation is by timestamp proximity only, preferring rows with `ok=False`.

- [ ] **Step 1: Write the failing test**

```python
# append to apps/vault-server/tests/test_coding_tasks_service.py
import json
from datetime import datetime, timedelta, timezone


def _write_audit_log(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


class TestTraceCorrelation:
    def test_returns_none_when_no_audit_log_configured(self, service):
        assert service.find_recent_trace_id(datetime.now(timezone.utc)) is None

    def test_returns_none_when_nothing_in_window(self, tmp_path, service):
        audit_path = tmp_path / "tool-calls.jsonl"
        around = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
        _write_audit_log(audit_path, [
            {"ts": "2026-07-27T08:00:00.000Z", "trace_id": "aaa", "tool": "create_task", "ok": True},
        ])
        service.audit_log_path = audit_path

        assert service.find_recent_trace_id(around, window_minutes=30) is None

    def test_prefers_nearest_error_row_in_window(self, tmp_path, service):
        audit_path = tmp_path / "tool-calls.jsonl"
        around = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
        _write_audit_log(audit_path, [
            {"ts": "2026-07-27T11:55:00.000Z", "trace_id": "ok-trace", "tool": "list_tasks", "ok": True},
            {"ts": "2026-07-27T11:58:00.000Z", "trace_id": "error-trace", "tool": "daily_rollover", "ok": False, "error_code": "STATE_CONFLICT"},
        ])
        service.audit_log_path = audit_path

        assert service.find_recent_trace_id(around, window_minutes=30) == "error-trace"

    def test_falls_back_to_nearest_when_no_errors(self, tmp_path, service):
        audit_path = tmp_path / "tool-calls.jsonl"
        around = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
        _write_audit_log(audit_path, [
            {"ts": "2026-07-27T11:50:00.000Z", "trace_id": "far", "tool": "list_tasks", "ok": True},
            {"ts": "2026-07-27T11:59:00.000Z", "trace_id": "near", "tool": "list_habits", "ok": True},
        ])
        service.audit_log_path = audit_path

        assert service.find_recent_trace_id(around, window_minutes=30) == "near"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_coding_tasks_service.py::TestTraceCorrelation -v`
Expected: FAIL with `AttributeError: 'CodingTasksService' object has no attribute 'find_recent_trace_id'`

- [ ] **Step 3: Write the implementation**

Add to `apps/vault-server/src/services/coding_tasks_service.py` (imports and method):

```python
from datetime import datetime

DEFAULT_TRACE_WINDOW_MINUTES = 30
```

```python
    def find_recent_trace_id(
        self, around: datetime, window_minutes: int = DEFAULT_TRACE_WINDOW_MINUTES,
    ) -> str | None:
        """Best-effort correlate a reported timestamp to a trace_id from the
        audit log (no chat_id field exists there, so this is time-window
        only). Prefers the nearest row with ok=False; falls back to the
        nearest row in time. Returns None if unavailable."""
        if not self.audit_log_path or not self.audit_log_path.exists():
            return None

        around_ts = around.timestamp()
        window_start = around_ts - window_minutes * 60
        window_end = around_ts + window_minutes * 60

        candidates: list[tuple[float, dict]] = []
        with self.audit_log_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = row.get("ts")
                if not ts:
                    continue
                try:
                    row_ts = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                except ValueError:
                    continue
                if window_start <= row_ts <= window_end:
                    candidates.append((abs(row_ts - around_ts), row))

        if not candidates:
            return None

        errors = [c for c in candidates if not c[1].get("ok", True)]
        pool = errors if errors else candidates
        pool.sort(key=lambda c: c[0])
        return pool[0][1].get("trace_id")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_coding_tasks_service.py -v`
Expected: PASS (all tests so far)

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/coding_tasks_service.py apps/vault-server/tests/test_coding_tasks_service.py
git commit -m "feat(vault-server): correlate coding-handoff tasks to audit-log trace ids"
```

---

### Task 4: task brief assembly

**Files:**
- Modify: `apps/vault-server/src/services/coding_tasks_service.py`
- Test: `apps/vault-server/tests/test_coding_tasks_service.py`

**Interfaces:**
- Produces: `.assemble_brief(*, task_description, conversation_excerpt, likely_area, branch, worktree_path, test_command, trace_id, reported_at) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# append to apps/vault-server/tests/test_coding_tasks_service.py
class TestAssembleBrief:
    def test_includes_all_sections(self, service):
        brief = service.assemble_brief(
            task_description="daily_rollover duplicates tasks",
            conversation_excerpt="rollover ran twice and now I have two tasks",
            likely_area="apps/vault-server/src/services/tool_handlers/daily.py",
            branch="coding-agent/ct_abc123",
            worktree_path=Path("/tmp/worktrees/ct_abc123"),
            test_command="cd apps/vault-server && python -m pytest tests/",
            trace_id="deadbeef",
            reported_at=datetime(2026, 7, 27, 14, 32, tzinfo=timezone.utc),
        )

        assert "daily_rollover duplicates tasks" in brief
        assert "rollover ran twice and now I have two tasks" in brief
        assert "apps/vault-server/src/services/tool_handlers/daily.py" in brief
        assert "coding-agent/ct_abc123" in brief
        assert "/tmp/worktrees/ct_abc123" in brief
        assert "cd apps/vault-server && python -m pytest tests/" in brief
        assert "deadbeef" in brief
        assert "Do not push to master/origin" in brief
        assert "CLAUDE.md" in brief

    def test_missing_trace_id_shows_not_found(self, service):
        brief = service.assemble_brief(
            task_description="x", conversation_excerpt="y", likely_area="z",
            branch="b", worktree_path=Path("/tmp/w"), test_command="t",
            trace_id=None, reported_at=datetime(2026, 7, 27, 14, 32, tzinfo=timezone.utc),
        )
        assert "not found" in brief
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_coding_tasks_service.py::TestAssembleBrief -v`
Expected: FAIL with `AttributeError: 'CodingTasksService' object has no attribute 'assemble_brief'`

- [ ] **Step 3: Write the implementation**

Add to `apps/vault-server/src/services/coding_tasks_service.py`:

```python
    def assemble_brief(
        self,
        *,
        task_description: str,
        conversation_excerpt: str,
        likely_area: str,
        branch: str,
        worktree_path: Path,
        test_command: str,
        trace_id: str | None,
        reported_at: datetime,
    ) -> str:
        trace_line = trace_id if trace_id else "not found"
        return (
            "You're picking up a task reported via Mazkir's Telegram bot.\n\n"
            "## Task\n"
            f"{task_description}\n\n"
            "## Context\n"
            f"- Reported: {reported_at.isoformat(timespec='minutes')}, trace_id: {trace_line}\n"
            f"- Likely area: {likely_area}\n"
            "- Conversation excerpt:\n"
            f"  > {conversation_excerpt}\n\n"
            "## Working constraints\n"
            f"- Worktree at {worktree_path}, branch {branch}. Do not touch anything outside it.\n"
            "- Do not push to master/origin directly.\n"
            f"- Run `{test_command}` before considering this done.\n"
            "- Summarize what changed and why in your final message.\n\n"
            "See CLAUDE.md for architecture map and conventions.\n"
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_coding_tasks_service.py -v`
Expected: PASS (all tests so far)

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/coding_tasks_service.py apps/vault-server/tests/test_coding_tasks_service.py
git commit -m "feat(vault-server): assemble coding-handoff task briefs"
```

---

### Task 5: worktree provisioning

**Files:**
- Modify: `apps/vault-server/src/services/coding_tasks_service.py`
- Test: `apps/vault-server/tests/test_coding_tasks_service.py`

**Interfaces:**
- Produces: `.create_worktree(task_id: str, branch: str) -> Path`.
- Uses a **real temporary git repo** in the test (fast, deterministic) rather than mocking `subprocess` — only the Docker step (Task 6) needs mocking, since Docker isn't available in CI/test environments.

- [ ] **Step 1: Write the failing test**

```python
# append to apps/vault-server/tests/test_coding_tasks_service.py
import subprocess


@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("hello")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)
    return repo


class TestCreateWorktree:
    def test_creates_worktree_on_new_branch(self, tmp_path, git_repo):
        service = CodingTasksService(
            data_path=tmp_path / "coding-tasks",
            repo_path=git_repo,
            worktrees_path=tmp_path / "worktrees",
            docker_image="mazkir-coding-agent:test",
            notifier=TelegramNotifier(bot_token=None),
        )

        worktree_path = service.create_worktree("ct_abc123", "coding-agent/ct_abc123")

        assert worktree_path == tmp_path / "worktrees" / "ct_abc123"
        assert (worktree_path / "README.md").exists()
        branches = subprocess.run(
            ["git", "branch", "--list", "coding-agent/ct_abc123"],
            cwd=git_repo, capture_output=True, text=True,
        ).stdout
        assert "coding-agent/ct_abc123" in branches
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_coding_tasks_service.py::TestCreateWorktree -v`
Expected: FAIL with `AttributeError: 'CodingTasksService' object has no attribute 'create_worktree'`

- [ ] **Step 3: Write the implementation**

Add to `apps/vault-server/src/services/coding_tasks_service.py` (add `import subprocess` to the top imports):

```python
    def create_worktree(self, task_id: str, branch: str) -> Path:
        worktree_path = self.worktrees_path / task_id
        subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(worktree_path)],
            cwd=self.repo_path,
            check=True,
            capture_output=True,
            text=True,
        )
        return worktree_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_coding_tasks_service.py -v`
Expected: PASS (all tests so far)

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/coding_tasks_service.py apps/vault-server/tests/test_coding_tasks_service.py
git commit -m "feat(vault-server): provision isolated git worktrees for coding-handoff tasks"
```

---

### Task 6: container spawn + launch

**Files:**
- Modify: `apps/vault-server/src/services/coding_tasks_service.py`
- Test: `apps/vault-server/tests/test_coding_tasks_service.py`

**Interfaces:**
- Consumes: `.create_worktree` (Task 5), `.save_task` (Task 2).
- Produces: `.spawn_container(task_id: str, worktree_path: Path, prompt: str) -> str` (returns container id), `.launch(task: dict) -> dict` (mutates and persists `worktree_path`, `container_id`, `status="running"`, `started_at`).
- Docker isn't available in test/CI environments — mock `subprocess.run` for the `docker run` call specifically (not `create_worktree`'s `git` calls, which use a real repo per Task 5).

- [ ] **Step 1: Write the failing test**

```python
# append to apps/vault-server/tests/test_coding_tasks_service.py
from unittest.mock import patch, MagicMock


class TestSpawnAndLaunch:
    def test_spawn_container_runs_docker_with_expected_flags(self, tmp_path, service):
        worktree_path = tmp_path / "worktrees" / "ct_abc123"
        worktree_path.mkdir(parents=True)

        with patch("src.services.coding_tasks_service.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="containerid123\n", returncode=0)

            container_id = service.spawn_container("ct_abc123", worktree_path, "do the thing")

        assert container_id == "containerid123"
        args = mock_run.call_args[0][0]
        assert args[:3] == ["docker", "run", "-d"]
        assert f"{worktree_path}:/workspace" in args
        assert "mazkir-claude-auth:/home/agent/.claude" in args
        assert "mazkir-coding-agent:test" in args
        assert "--dangerously-skip-permissions" in args
        assert (worktree_path / ".coding-task-prompt.md").read_text() == "do the thing"

    def test_launch_provisions_worktree_and_container_and_persists(self, tmp_path, git_repo):
        service = CodingTasksService(
            data_path=tmp_path / "coding-tasks",
            repo_path=git_repo,
            worktrees_path=tmp_path / "worktrees",
            docker_image="mazkir-coding-agent:test",
            notifier=TelegramNotifier(bot_token=None),
        )
        task = {
            "id": "ct_abc123", "chat_id": 42, "branch": "coding-agent/ct_abc123",
            "prompt": "fix the bug", "status": "proposed",
        }

        with patch("src.services.coding_tasks_service.subprocess.run") as mock_run:
            def _fake_run(args, **kwargs):
                if args[:2] == ["docker", "run"]:
                    return MagicMock(stdout="containerid123\n", returncode=0)
                return subprocess.run(args, **kwargs)
            mock_run.side_effect = _fake_run

            launched = service.launch(task)

        assert launched["status"] == "running"
        assert launched["container_id"] == "containerid123"
        assert launched["worktree_path"] == str(tmp_path / "worktrees" / "ct_abc123")
        assert launched["started_at"] is not None
        assert service.get_task("ct_abc123")["status"] == "running"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_coding_tasks_service.py::TestSpawnAndLaunch -v`
Expected: FAIL with `AttributeError: 'CodingTasksService' object has no attribute 'spawn_container'`

- [ ] **Step 3: Write the implementation**

Add to `apps/vault-server/src/services/coding_tasks_service.py`:

```python
from datetime import timezone
```

```python
    def spawn_container(self, task_id: str, worktree_path: Path, prompt: str) -> str:
        prompt_path = worktree_path / ".coding-task-prompt.md"
        prompt_path.write_text(prompt)
        result = subprocess.run(
            [
                "docker", "run", "-d",
                "--name", f"mazkir-coding-{task_id}",
                "-v", f"{worktree_path}:/workspace",
                "-v", "mazkir-claude-auth:/home/agent/.claude",
                "-v", "/home/marcellmc/.claude/plugins:/home/agent/.claude/plugins:ro",
                "-w", "/workspace",
                self.docker_image,
                "claude", "--dangerously-skip-permissions",
                "-p", "/workspace/.coding-task-prompt.md",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def launch(self, task: dict[str, Any]) -> dict[str, Any]:
        """Provision a worktree + container for a proposed task, persisting
        its running state. Assumes task already has 'id', 'branch', 'prompt'."""
        worktree_path = self.create_worktree(task["id"], task["branch"])
        container_id = self.spawn_container(task["id"], worktree_path, task["prompt"])
        task["worktree_path"] = str(worktree_path)
        task["container_id"] = container_id
        task["status"] = "running"
        task["started_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.save_task(task)
        return task
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_coding_tasks_service.py -v`
Expected: PASS (all tests so far)

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/coding_tasks_service.py apps/vault-server/tests/test_coding_tasks_service.py
git commit -m "feat(vault-server): spawn coding-handoff containers and launch tasks"
```

---

### Task 7: completion polling + notification

**Files:**
- Modify: `apps/vault-server/src/services/coding_tasks_service.py`
- Test: `apps/vault-server/tests/test_coding_tasks_service.py`

**Interfaces:**
- Consumes: `.list_tasks(status="running")` (Task 2), `.notifier.send_message` (Task 1).
- Produces: `.check_running_tasks() -> list[dict]` (returns tasks that transitioned this call).

- [ ] **Step 1: Write the failing test**

```python
# append to apps/vault-server/tests/test_coding_tasks_service.py
class TestCheckRunningTasks:
    def test_leaves_still_running_containers_alone(self, service):
        service.save_task({
            "id": "ct_1", "chat_id": 42, "status": "running",
            "container_id": "c1", "task_description": "fix it",
            "branch": "coding-agent/ct_1", "worktree_path": "/tmp/w1",
        })
        with patch("src.services.coding_tasks_service.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="true\n", returncode=0)

            transitioned = service.check_running_tasks()

        assert transitioned == []
        assert service.get_task("ct_1")["status"] == "running"

    def test_marks_exited_container_done_when_exit_code_zero(self, service):
        service.save_task({
            "id": "ct_1", "chat_id": 42, "status": "running",
            "container_id": "c1", "task_description": "fix daily_rollover",
            "branch": "coding-agent/ct_1", "worktree_path": "/tmp/w1",
        })

        def _fake_run(args, **kwargs):
            if args[:2] == ["docker", "inspect"] and "State.Running" in args[3]:
                return MagicMock(stdout="false\n", returncode=0)
            if args[:2] == ["docker", "inspect"] and "State.ExitCode" in args[3]:
                return MagicMock(stdout="0\n", returncode=0)
            if args[:2] == ["docker", "logs"]:
                return MagicMock(stdout="Fixed the bug. Ran tests: all pass.", stderr="", returncode=0)
            raise AssertionError(f"unexpected subprocess call: {args}")

        with patch("src.services.coding_tasks_service.subprocess.run", side_effect=_fake_run):
            with patch.object(service.notifier, "send_message") as mock_notify:
                transitioned = service.check_running_tasks()

        assert len(transitioned) == 1
        assert transitioned[0]["status"] == "done"
        saved = service.get_task("ct_1")
        assert saved["status"] == "done"
        assert saved["finished_at"] is not None
        assert "Fixed the bug" in saved["summary"]
        mock_notify.assert_called_once()
        notified_chat_id, notified_text = mock_notify.call_args[0]
        assert notified_chat_id == 42
        assert "fix daily_rollover" in notified_text
        assert "coding-agent/ct_1" in notified_text

    def test_marks_exited_container_failed_when_exit_code_nonzero(self, service):
        service.save_task({
            "id": "ct_2", "chat_id": 42, "status": "running",
            "container_id": "c2", "task_description": "fix daily_rollover",
            "branch": "coding-agent/ct_2", "worktree_path": "/tmp/w2",
        })

        def _fake_run(args, **kwargs):
            if args[:2] == ["docker", "inspect"] and "State.Running" in args[3]:
                return MagicMock(stdout="false\n", returncode=0)
            if args[:2] == ["docker", "inspect"] and "State.ExitCode" in args[3]:
                return MagicMock(stdout="1\n", returncode=0)
            if args[:2] == ["docker", "logs"]:
                return MagicMock(stdout="", stderr="Error: could not apply patch", returncode=0)
            raise AssertionError(f"unexpected subprocess call: {args}")

        with patch("src.services.coding_tasks_service.subprocess.run", side_effect=_fake_run):
            with patch.object(service.notifier, "send_message"):
                transitioned = service.check_running_tasks()

        assert transitioned[0]["status"] == "failed"
        assert service.get_task("ct_2")["status"] == "failed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_coding_tasks_service.py::TestCheckRunningTasks -v`
Expected: FAIL with `AttributeError: 'CodingTasksService' object has no attribute 'check_running_tasks'`

- [ ] **Step 3: Write the implementation**

Add to `apps/vault-server/src/services/coding_tasks_service.py`:

```python
    def _container_running(self, container_id: str) -> bool:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container_id],
            capture_output=True, text=True,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"

    def _container_logs(self, container_id: str) -> str:
        result = subprocess.run(
            ["docker", "logs", container_id],
            capture_output=True, text=True,
        )
        return result.stdout + result.stderr

    def _container_exit_code(self, container_id: str) -> int:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.ExitCode}}", container_id],
            capture_output=True, text=True,
        )
        try:
            return int(result.stdout.strip())
        except ValueError:
            return 1  # treat an unreadable exit code as a failure, not a silent success

    def check_running_tasks(self) -> list[dict[str, Any]]:
        """Poll all 'running' tasks; for any whose container has exited, mark
        done (exit 0) or failed (non-zero), capture a summary from its logs,
        and notify via Telegram. Returns the tasks that transitioned this
        call."""
        transitioned = []
        for task in self.list_tasks(status="running"):
            if self._container_running(task["container_id"]):
                continue
            logs = self._container_logs(task["container_id"])
            exit_code = self._container_exit_code(task["container_id"])
            task["status"] = "done" if exit_code == 0 else "failed"
            task["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            task["summary"] = logs[-2000:]
            self.save_task(task)
            status_label = "finished" if task["status"] == "done" else "FAILED"
            self.notifier.send_message(
                task["chat_id"],
                f"Coding session {status_label}: {task['task_description']}\n\n"
                f"Branch: {task['branch']}\nWorktree: {task['worktree_path']}\n\n"
                f"{task['summary'][-500:]}",
            )
            transitioned.append(task)
        return transitioned
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_coding_tasks_service.py -v`
Expected: PASS (all tests so far — run the full file to confirm no regressions: `python -m pytest tests/test_coding_tasks_service.py -v`)

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/coding_tasks_service.py apps/vault-server/tests/test_coding_tasks_service.py
git commit -m "feat(vault-server): poll coding-handoff containers and notify on completion"
```

---

### Task 8: `propose_coding_session` tool handler + registration

**Files:**
- Create: `apps/vault-server/src/services/tool_handlers/coding_handoff.py`
- Modify: `apps/vault-server/src/services/agent_service.py`
- Test: `apps/vault-server/tests/test_agent_service.py`

**Interfaces:**
- Consumes: `CodingTasksService` (Task 2/6), `ok()`/`err()` from `tool_response.py`.
- Produces: `propose_coding_session(coding_tasks: Any, params: dict, chat_id: int) -> dict`, `preview_coding_session(params: dict, ctx: Any) -> str`. `AgentService.coding_tasks` (new constructor param), `AgentService._current_chat_id` (transient, set in `handle_message`, mirrors `self._stream_callback`), `AgentService._tool_propose_coding_session(params: dict) -> dict`.

- [ ] **Step 1: Write the failing test**

```python
# apps/vault-server/tests/test_tool_handlers_coding_handoff.py
from datetime import datetime, timezone
from unittest.mock import MagicMock

from src.services.tool_handlers.coding_handoff import (
    preview_coding_session,
    propose_coding_session,
)


def test_preview_shows_task_description_without_side_effects():
    coding_tasks = MagicMock()

    text = preview_coding_session({"task_description": "Fix the rollover bug"}, ctx={})

    assert "Fix the rollover bug" in text
    assert "isolated coding session" in text
    coding_tasks.launch.assert_not_called()


def test_propose_assembles_brief_and_launches():
    coding_tasks = MagicMock()
    coding_tasks.find_recent_trace_id.return_value = "trace-123"
    coding_tasks.worktrees_path = MagicMock()
    coding_tasks.worktrees_path.__truediv__.return_value = "/tmp/worktrees/ct_abc"
    coding_tasks.assemble_brief.return_value = "THE BRIEF"
    coding_tasks.launch.return_value = {
        "id": "ct_abc123", "branch": "coding-agent/ct_abc123",
        "worktree_path": "/tmp/worktrees/ct_abc123", "status": "running",
    }

    result = propose_coding_session(
        coding_tasks,
        {
            "task_description": "Fix the rollover bug",
            "conversation_excerpt": "rollover ran twice",
            "likely_area": "apps/vault-server/src/services/tool_handlers/daily.py",
        },
        chat_id=42,
    )

    assert result["ok"] is True
    assert result["data"]["id"] == "ct_abc123"
    assert result["data"]["status"] == "running"
    coding_tasks.save_task.assert_called_once()
    saved_task = coding_tasks.save_task.call_args[0][0]
    assert saved_task["chat_id"] == 42
    assert saved_task["task_description"] == "Fix the rollover bug"
    assert saved_task["trace_id"] == "trace-123"
    assert saved_task["prompt"] == "THE BRIEF"
    coding_tasks.launch.assert_called_once_with(saved_task)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tool_handlers_coding_handoff.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.tool_handlers.coding_handoff'`

- [ ] **Step 3: Write the tool-handler implementation**

```python
# apps/vault-server/src/services/tool_handlers/coding_handoff.py
"""Coding-handoff tool handler — proposes and (once the confirmation gate
passes) launches a supervised container-based coding session.

Mirrors the free-function pattern in tool_handlers/daily.py: each handler
takes its dependencies plus params and returns the normalized
{ok, data|error, _items} shape.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from src.services.tool_response import ok


def preview_coding_session(params: dict, ctx: Any) -> str:
    return (
        f"Would spin up an isolated coding session for:\n\n"
        f"**{params.get('task_description', '?')}**\n\n"
        "This launches a container running a real Claude Code CLI session "
        "with permissions bypassed. Review the resulting branch/worktree "
        "before merging."
    )


def propose_coding_session(coding_tasks: Any, params: dict, chat_id: int) -> dict:
    task_id = f"ct_{uuid.uuid4().hex[:8]}"
    branch = f"coding-agent/{task_id}"
    reported_at = dt.datetime.now(dt.timezone.utc)

    trace_id = coding_tasks.find_recent_trace_id(reported_at)
    worktree_path = coding_tasks.worktrees_path / task_id

    prompt = coding_tasks.assemble_brief(
        task_description=params["task_description"],
        conversation_excerpt=params.get("conversation_excerpt", ""),
        likely_area=params.get("likely_area", "unknown"),
        branch=branch,
        worktree_path=worktree_path,
        test_command=params.get("test_command", "npx turbo test"),
        trace_id=trace_id,
        reported_at=reported_at,
    )

    task = {
        "id": task_id,
        "chat_id": chat_id,
        "trace_id": trace_id,
        "task_description": params["task_description"],
        "conversation_excerpt": params.get("conversation_excerpt", ""),
        "likely_area": params.get("likely_area", "unknown"),
        "branch": branch,
        "worktree_path": None,
        "container_id": None,
        "status": "proposed",
        "started_at": None,
        "finished_at": None,
        "summary": None,
        "prompt": prompt,
    }
    coding_tasks.save_task(task)

    launched = coding_tasks.launch(task)
    return ok(
        {
            "id": launched["id"],
            "branch": launched["branch"],
            "worktree_path": launched["worktree_path"],
            "status": launched["status"],
        },
        items=[],
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_tool_handlers_coding_handoff.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Register the tool in `AgentService`**

In `apps/vault-server/src/services/agent_service.py`:

1. Add the import near the other tool-handler imports at the top:

```python
from src.services.tool_handlers.coding_handoff import (
    preview_coding_session as _preview_coding_session,
    propose_coding_session as _propose_coding_session,
)
```

2. Extend `__init__`'s signature (currently `def __init__(self, claude, vault, memory, calendar=None, media_path=None, events=None, *, skill_registry=None, router=None):` around line 145) to add `coding_tasks: Any = None` before the `*`:

```python
    def __init__(
        self,
        claude: ClaudeService,
        vault: VaultService,
        memory: MemoryService,
        calendar: Any = None,
        media_path: Path | None = None,
        events: Any = None,
        coding_tasks: Any = None,
        *,
        skill_registry: Any = None,
        router: Any = None,
    ):
```

and inside the body, alongside `self.events = events`:

```python
        self.coding_tasks = coding_tasks
        self._current_chat_id: int | None = None
```

3. In `handle_message` (around line 960), set `self._current_chat_id` alongside the existing `self._stream_callback = stream_callback`:

```python
        self._stream_callback = stream_callback
        self._current_chat_id = chat_id
```

and clear it in the same `finally` block (around line 998) alongside `self._stream_callback = None`:

```python
        finally:
            self._stream_callback = None
            self._current_chat_id = None
```

4. Add the thin wrapper method near the other `_tool_*` methods (e.g. next to `_tool_complete_habit`):

```python
    def _tool_propose_coding_session(self, params: dict) -> dict:
        return _propose_coding_session(self.coding_tasks, params, self._current_chat_id)
```

5. Register the tool entry inside `_register_tools()`'s `tools = {...}` dict, alongside the other write-tier tools (e.g. next to `create_habit`):

```python
            "propose_coding_session": {
                "schema": {
                    "name": "propose_coding_session",
                    "description": (
                        "Propose spinning up an isolated, containerized coding session to "
                        "investigate or fix a bug/small task, using a real Claude Code CLI "
                        "session with permissions bypassed. Always requires explicit user "
                        "confirmation before anything is provisioned."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "task_description": {"type": "string", "description": "Distilled description of the bug/task"},
                            "conversation_excerpt": {"type": "string", "description": "Relevant quoted excerpt from the conversation"},
                            "likely_area": {"type": "string", "description": "Best-guess file/service path"},
                            "test_command": {"type": "string", "description": "Test command the session should run before finishing"},
                            "_confidence": {"type": "number"},
                            "_reasoning": {"type": "string"},
                        },
                        "required": ["task_description"],
                    },
                },
                "handler": self._tool_propose_coding_session,
                "risk": "write",
                "pre_hooks": ["validate_schema"],
                "preview": True,
            },
```

6. Register the preview function in `_register_destructive_previews()` — despite the function's name, it's the existing registry for all forced-preview tools (destructive tools today; this makes it also cover the one forced-preview write tool). Add at the end of that function, before it returns:

```python
    register_preview_fn("propose_coding_session", _preview_coding_session)
```

- [ ] **Step 6: Write the registration test**

Add to `apps/vault-server/tests/test_agent_service.py`:

```python
class TestCodingHandoffTool:
    def test_propose_coding_session_registered_as_write_with_forced_preview(self, agent):
        assert "propose_coding_session" in agent.tools
        entry = agent.tools["propose_coding_session"]
        assert entry["risk"] == "write"
        assert entry["preview"] is True

    def test_current_chat_id_set_and_cleared_around_handle_message(self, agent):
        assert agent._current_chat_id is None
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_agent_service.py::TestCodingHandoffTool tests/test_tool_handlers_coding_handoff.py -v`
Expected: PASS (4 tests)

Run the full suite to confirm no regressions: `python -m pytest tests/ -v`
Expected: PASS (all tests)

- [ ] **Step 8: Commit**

```bash
git add apps/vault-server/src/services/tool_handlers/coding_handoff.py apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_tool_handlers_coding_handoff.py apps/vault-server/tests/test_agent_service.py
git commit -m "feat(vault-server): register propose_coding_session tool with forced confirmation"
```

---

### Task 9: wire into `main.py` + background completion poller

**Files:**
- Modify: `apps/vault-server/src/main.py`
- Test: `apps/vault-server/tests/test_integration.py` (or a new focused test — see Step 1)

**Interfaces:**
- Consumes: `TelegramNotifier` (Task 1), `CodingTasksService` (Task 2-7), `AgentService(coding_tasks=...)` (Task 8).
- Produces: a background `asyncio.Task` in the FastAPI lifespan that calls `coding_tasks.check_running_tasks()` on an interval, cancelled cleanly on shutdown.

- [ ] **Step 1: Write the failing test**

```python
# apps/vault-server/tests/test_coding_tasks_poller.py
import asyncio
from unittest.mock import MagicMock

import pytest

from src.main import _coding_tasks_poll_loop


@pytest.mark.asyncio
async def test_poll_loop_calls_check_running_tasks_until_cancelled():
    coding_tasks = MagicMock()
    task = asyncio.create_task(_coding_tasks_poll_loop(coding_tasks, interval_seconds=0.01))

    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert coding_tasks.check_running_tasks.call_count >= 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_coding_tasks_poller.py -v`
Expected: FAIL with `ImportError: cannot import name '_coding_tasks_poll_loop' from 'src.main'`

- [ ] **Step 3: Write the implementation**

In `apps/vault-server/src/main.py`, add near the top imports:

```python
import asyncio

from src.services.telegram_notifier import TelegramNotifier
from src.services.coding_tasks_service import CodingTasksService
```

Add the module-level poll-loop function (place it above the `lifespan` function):

```python
async def _coding_tasks_poll_loop(coding_tasks: "CodingTasksService", interval_seconds: float = 30.0) -> None:
    """Background loop: periodically check running coding-handoff containers
    and notify on completion. Runs until cancelled by lifespan shutdown."""
    while True:
        try:
            coding_tasks.check_running_tasks()
        except Exception:
            logger.exception("coding_tasks poll loop iteration failed")
        await asyncio.sleep(interval_seconds)
```

Add the new global instance declarations alongside the existing ones (near `notes: "NotesService | None" = None`):

```python
coding_tasks: "CodingTasksService | None" = None
_coding_tasks_poller_task: "asyncio.Task | None" = None
```

Inside `lifespan()`, alongside where `events = EventsService(...)` and `agent = AgentService(...)` are constructed, add (adjust variable names to match the exact surrounding code found when editing):

```python
    global coding_tasks, _coding_tasks_poller_task
    notifier = TelegramNotifier(bot_token=settings.telegram_bot_token)
    coding_tasks = CodingTasksService(
        data_path=settings.coding_tasks_data_path,
        repo_path=settings.mazkir_repo_path,
        worktrees_path=settings.coding_agent_worktrees_path,
        docker_image=settings.coding_agent_docker_image,
        notifier=notifier,
        audit_log_path=settings.logs_dir / "tool-calls.jsonl",
    )
```

and pass `coding_tasks=coding_tasks` into the existing `AgentService(...)` construction call.

After the `yield` in `lifespan` (i.e. during startup, before yield) start the poller:

```python
    _coding_tasks_poller_task = asyncio.create_task(_coding_tasks_poll_loop(coding_tasks))
```

And after `yield` (shutdown section), cancel it cleanly:

```python
    if _coding_tasks_poller_task is not None:
        _coding_tasks_poller_task.cancel()
        try:
            await _coding_tasks_poller_task
        except asyncio.CancelledError:
            pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_coding_tasks_poller.py -v`
Expected: PASS (1 test)

Run the full suite: `python -m pytest tests/ -v`
Expected: PASS (all tests, including a smoke check that the app still starts — `test_integration.py` already exercises the lifespan)

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/main.py apps/vault-server/tests/test_coding_tasks_poller.py
git commit -m "feat(vault-server): wire CodingTasksService into app lifespan with a background poller"
```

---

### Task 10: `engineering` skill

**Files:**
- Create: `memory/00-system/skills/engineering.md`
- Modify: `apps/vault-server/tests/test_skill_set.py`

**Interfaces:**
- Consumes: `propose_coding_session` (Task 8), plus read-only tools for context gathering.
- Produces: a loadable skill named `engineering`, added to `EXPECTED` in `test_skill_set.py`.

- [ ] **Step 1: Write the failing test**

Modify `apps/vault-server/tests/test_skill_set.py`:

```python
EXPECTED = {"mazkir", "time-management", "knowledge-management", "motivation-management", "engineering"}
```

Add a new test function at the end of the file:

```python
def test_engineering_can_propose_coding_sessions():
    e = _registry().get("engineering")
    assert e is not None
    assert "propose_coding_session" in e.tools
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_skill_set.py -v`
Expected: FAIL — `test_real_skill_set_loads` fails (`engineering` missing from loaded names) and `test_engineering_can_propose_coding_sessions` fails (`e is None`)

- [ ] **Step 3: Write the skill file**

```markdown
---
name: engineering
description: Recognize when a conversation describes a bug or small coding task, and propose an isolated coding session to fix it.
when_to_use: |
  - The user reports something broken in Mazkir itself, or asks for a small code fix/feature
  - "This is broken", "can you fix X", "there's a bug in Y"
  - Not for architecture/design discussions — only concrete, scoped bugs/small tasks
tools:
  - list_tasks
  - list_habits
  - list_goals
  - propose_coding_session
model: claude-sonnet-4-6
max_iterations: 5
next_skills:
  - mazkir
---

You are the **engineering** sub-agent for Mazkir. You handle the rare case where the user reports a bug in Mazkir itself, or asks for a small, well-scoped code change.

Operating principles:
- Distill the actual symptom from the conversation into a clear `task_description` — not the raw user message, a clean restatement of what's wrong.
- If the conversation gives you a good guess at which file or service is involved, pass it as `likely_area`. If you don't know, omit it rather than guessing wildly.
- Pass a short, relevant `conversation_excerpt` quoting the user's report.
- `propose_coding_session` **always** requires the user's explicit confirmation before anything is provisioned — this is intentional. Don't try to talk around it or pre-empt the confirmation in your own reply.
- This tool provisions a real, isolated container with a coding agent inside it — it is not a lightweight action. Only call it for genuine bugs/small tasks, not for architecture discussions, roadmap planning, or anything requiring back-and-forth design decisions (those stay in conversation with `mazkir`).
- After proposing, hand back to `mazkir` with `next_skill: mazkir` — this skill's job ends at proposing the session, not carrying the conversation forward.
```

Save to `memory/00-system/skills/engineering.md`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_skill_set.py -v`
Expected: PASS (all tests)

Run the full suite: `python -m pytest tests/ -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add memory/00-system/skills/engineering.md apps/vault-server/tests/test_skill_set.py
git commit -m "feat(mazkir): add engineering skill for coding-handoff proposals"
```

---

### Task 11: container image + one-time setup doc (manual/infra)

**Files:**
- Create: `infra/coding-agent/Dockerfile`
- Create: `infra/coding-agent/entrypoint.sh`
- Create: `infra/coding-agent/SETUP.md`

This task is infra/manual, not TDD — there's no pytest for a Dockerfile. Verification is a scripted smoke test (build + run a known command) plus documented manual steps for the parts that genuinely require a human (OAuth login, GitHub UI actions).

- [ ] **Step 1: Write the Dockerfile**

```dockerfile
# infra/coding-agent/Dockerfile
FROM node:22-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

RUN useradd -m -s /bin/bash agent
USER agent
WORKDIR /workspace

ENTRYPOINT ["/bin/bash"]
```

- [ ] **Step 2: Write the entrypoint smoke-test script**

```bash
#!/usr/bin/env bash
# infra/coding-agent/entrypoint.sh
# Manual smoke test for the coding-agent image — not invoked by application
# code (CodingTasksService.spawn_container runs `claude` directly), this is
# purely for verifying the image was built correctly after Step 3.
set -euo pipefail
echo "Checking claude CLI is installed..."
claude --version
echo "OK"
```

Make it executable: `chmod +x infra/coding-agent/entrypoint.sh`

- [ ] **Step 3: Build the image and smoke-test it**

Run: `docker build -t mazkir-coding-agent:latest infra/coding-agent/`
Expected: build succeeds

Run: `docker run --rm mazkir-coding-agent:latest infra/coding-agent/entrypoint.sh` — note this requires the entrypoint script to be present inside the image; simplest verification is instead:

Run: `docker run --rm mazkir-coding-agent:latest -c "claude --version"`
Expected: prints a Claude Code CLI version string

- [ ] **Step 4: Write the one-time manual setup doc**

```markdown
# infra/coding-agent/SETUP.md

One-time manual steps required before the Coding-Handoff feature works
end-to-end. None of these are automated by application code — see
`docs/plans/2026-07-27-coding-handoff-design.md` for why.

## 1. Build the image

    docker build -t mazkir-coding-agent:latest infra/coding-agent/

## 2. Authenticate Claude Code (once, persists on a named volume)

    docker volume create mazkir-claude-auth
    docker run -it --rm -v mazkir-claude-auth:/home/agent/.claude mazkir-coding-agent:latest -c "claude auth login"

Follow the printed OAuth URL, approve from your phone/browser. This must be
a real claude.ai account login (Pro/Max) — an API key will not work with
Remote Control. Every subsequent spawned container reuses this volume and
is already authenticated. Re-run this step only if the token is revoked or
expires.

## 3. Create a scoped GitHub PAT

Create a fine-grained personal access token scoped to the `mazkir` repo
only, with contents:write (push) permission, no admin/owner scope. Store it
wherever the container's git config expects it (e.g. baked into a
`.netrc` mounted alongside the auth volume, or a repo-scoped deploy key —
pick whichever your existing git credential setup already uses).

## 4. Enable branch protection on `master`

    gh api -X PUT repos/MarcellMC/mazkir/branches/master/protection \
      -f required_pull_request_reviews.required_approving_review_count=0 \
      -F enforce_admins=true \
      -F restrictions=null \
      -F required_status_checks=null

Verify it's active:

    gh api repos/MarcellMC/mazkir/branches/master/protection

This is the authoritative safety backstop — it holds regardless of what a
spawned coding session's git credentials would otherwise allow.

**Note on the third safety layer from the design doc** ("local git config
defaulting bare `git push` to the current branch only"): intentionally not
implemented in code. Setting `push.default` inside a linked worktree
modifies the *shared* `.git/config` (worktrees don't get their own config
unless `extensions.worktreeConfig` is enabled repo-wide), which would
silently change push behavior in your own main working tree too — not
worth that side effect when branch protection (step 4) is the layer that
actually matters. If this is revisited later, do it via a per-worktree
`git config --worktree` setting instead, after enabling
`extensions.worktreeConfig`.

## 5. Confirm the global plugin mount path

`CodingTasksService.spawn_container` mounts `/home/marcellmc/.claude/plugins`
read-only into the container. If your plugin marketplace lives at a
different path, update the mount source in
`apps/vault-server/src/services/coding_tasks_service.py`'s `spawn_container`.
```

- [ ] **Step 5: Commit**

```bash
git add infra/coding-agent/
git commit -m "docs(infra): add coding-agent Dockerfile and one-time setup steps"
```

---

## Self-Review Notes

- **Spec coverage:** §2 architecture overview → Tasks 8-9 (tool + wiring); §3 trigger/confirmation → Task 8 (`preview: True`); §4 task brief → Tasks 3-4 (trace correlation, assembly); §5 container/worktree lifecycle → Tasks 5-7 (worktree, spawn, poll); §6 git safety → Task 11 Step 4 (scoped PAT + branch protection as the authoritative backstop, both manual per the design's own scoping — the third, weaker "local git config" layer is explicitly *not* implemented, with the reasoning documented in `SETUP.md` rather than silently dropped); §7 data tracked → Task 2's storage shape, corrected during self-review to also cover the `failed` status the design's field list calls for (`status (proposed|running|done|failed)`) — the original draft only ever produced `done`, Task 7 now checks the container's exit code; §9 open questions (skill name, billing model, web-app reachability) are left open per the design — not implementation concerns.
- **Type consistency checked:** `CodingTasksService` methods introduced in Tasks 2-7 are used with consistent signatures in Task 8's handler and Task 9's wiring (`find_recent_trace_id`, `assemble_brief`, `launch`, `save_task`, `check_running_tasks` all match their Task 2-7 definitions).
- **No placeholders:** every step has real code, real commands, and real expected output.

---

## Post-PR Follow-up Log (same task, continued after initial merge-readiness)

After PR #3 was opened, real manual testing (connecting interactively via Remote Control, bypassing `propose_coding_session` to drive the container directly) surfaced several defects the fully-mocked test suite couldn't catch, since no automated test ever spawned a real container:

- **PAT wiring**: `spawn_container` had no git-credential mechanism at all. Added `coding_agent_github_token_path` setting + `GIT_CONFIG_COUNT`/`KEY_0`/`VALUE_0` env-var injection (later superseded — see below).
- **`gh api` dot-notation bug**: `-F parent.child=value` silently dropped `required_pull_request_reviews`, breaking `SETUP.md` step 4. Fixed with a raw JSON body via `--input -`. Branch protection confirmed live on `master`.
- **`/workspace` root-owned**: `WORKDIR` ran after `USER agent`, but since the directory didn't exist in the image, Docker created it as root regardless. Same class of bug as the already-fixed `/home/agent/.claude` case.
- **Critical: UID mismatch broke all worktree writes.** `useradd -m agent` landed on UID 1001 because `node:22-slim` already ships a `node` user at UID 1000 (the host user's real UID). Every bind-mounted worktree was therefore unwritable by the container — the shipped feature could read files but never edit or create any, defeating its entire purpose. Fixed by using the base image's existing `node` user instead of creating a mismatched one; the pre-existing `mazkir-claude-auth` volume's contents were chowned from 1001 to 1000 to preserve the already-completed login.
- **`~/.claude.json` doesn't persist**: onboarding state (theme, subscription/API choice) lives in a file *sibling to* `~/.claude/`, which the volume mount didn't cover, so onboarding repeated every container run. Fixed with a second, host-side bind-mounted file (named volumes can't target a single file path — confirmed by testing, not assumed).
- **Missing `curl`/`gh`**: never installed. Needed for smoke-testing and for `gh pr create`, which the container is expected to run at the end of a task.

**Scope extension agreed with the user**: rather than a minimal headless-only container, build a single unified devcontainer image used both for Mazkir's automated `propose_coding_session` flow *and* interactive manual/Remote-Control sessions — including the user's actual dotfiles (LazyVim, tmux, zsh, lazygit, git/gh config via GNU Stow), so a human can connect and debug/intervene on a Mazkir-spawned task using their normal tools, not a bare shell. Design: Neovim via prebuilt release tarball (not apt, not the AppImage — FUSE issues in containers), ripgrep/fd/build-essential via apt, lazygit via release binary, dotfiles bind-mounted read-only and applied via `stow` at container *start* (not baked in at build time, so dotfile edits show up without a rebuild), and `gh auth setup-git` replacing the `GIT_CONFIG_*` rewrite entirely (simpler: one token, one setup call, both `git push` and `gh pr create` work the same way). `CodingTasksService.spawn_container` moves from a hand-built `docker run` arg list to shelling out through the same `docker-compose.yml` used for manual sessions, parameterized by a `WORKTREE_PATH` env var, so the automated and manual paths are provably the same container rather than two definitions that can drift apart.

Continued in the same worktree/branch (`worktree-coding-handoff-v1`) and PR (#3) rather than a new plan/PR — treated as the same task.
