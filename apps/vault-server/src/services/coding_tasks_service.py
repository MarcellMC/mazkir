"""CodingTasksService — provisions isolated worktree+container coding
sessions and tracks their lifecycle in data/coding-tasks/{id}.json.

Mirrors the JSON-per-id storage pattern used by EventsService
(src/services/events_service.py).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
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
