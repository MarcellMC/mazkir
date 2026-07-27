"""CodingTasksService — provisions isolated worktree+container coding
sessions and tracks their lifecycle in data/coding-tasks/{id}.json.

Mirrors the JSON-per-id storage pattern used by EventsService
(src/services/events_service.py).
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.services.telegram_notifier import TelegramNotifier

logger = logging.getLogger(__name__)

DEFAULT_TRACE_WINDOW_MINUTES = 30


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
