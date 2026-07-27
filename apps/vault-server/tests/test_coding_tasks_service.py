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
