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
