import json
import subprocess
from datetime import datetime, timedelta, timezone
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
