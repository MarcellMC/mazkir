import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

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

    def test_get_task_returns_none_for_corrupt_json_instead_of_raising(self, service):
        """A crash mid-save_task (non-atomic write) can leave a truncated or
        otherwise corrupt JSON file behind. get_task must not blow up on it."""
        (service.data_path / "ct_corrupt.json").write_text('{"id": "ct_corrupt", "status": "run')

        assert service.get_task("ct_corrupt") is None

    def test_list_tasks_skips_corrupt_file_and_still_returns_valid_ones(self, service):
        """The background poller calls list_tasks(status='running') every
        30s for ALL tasks -- one corrupt file must not stall polling for
        every other (valid) task."""
        service.save_task({"id": "ct_1", "status": "running"})
        (service.data_path / "ct_corrupt.json").write_text("not json at all {{{")
        service.save_task({"id": "ct_2", "status": "running"})

        tasks = service.list_tasks(status="running")

        assert {t["id"] for t in tasks} == {"ct_1", "ct_2"}


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

    def test_spawn_container_without_token_path_adds_no_git_config_env(self, tmp_path, service):
        worktree_path = tmp_path / "worktrees" / "ct_no_token"
        worktree_path.mkdir(parents=True)

        with patch("src.services.coding_tasks_service.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="containerid456\n", returncode=0)
            service.spawn_container("ct_no_token", worktree_path, "do the thing")

        args = mock_run.call_args[0][0]
        assert "GIT_CONFIG_COUNT=1" not in args
        assert not any(a.startswith("GIT_CONFIG_KEY_0=") for a in args)

    def test_spawn_container_with_token_path_injects_scoped_git_credential(self, tmp_path):
        token_path = tmp_path / "github-token"
        token_path.write_text("ghp_faketoken123\n")
        service = CodingTasksService(
            data_path=tmp_path / "coding-tasks",
            repo_path=tmp_path / "repo",
            worktrees_path=tmp_path / "worktrees",
            docker_image="mazkir-coding-agent:test",
            notifier=TelegramNotifier(bot_token=None),
            github_token_path=token_path,
        )
        worktree_path = tmp_path / "worktrees" / "ct_with_token"
        worktree_path.mkdir(parents=True)

        with patch("src.services.coding_tasks_service.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="containerid789\n", returncode=0)
            service.spawn_container("ct_with_token", worktree_path, "do the thing")

        args = mock_run.call_args[0][0]
        assert "GIT_CONFIG_COUNT=1" in args
        key_flag = next(a for a in args if a.startswith("GIT_CONFIG_KEY_0="))
        assert key_flag == (
            "GIT_CONFIG_KEY_0=url.https://x-access-token:ghp_faketoken123@github.com/.insteadOf"
        )
        assert "GIT_CONFIG_VALUE_0=git@github.com:" in args
        e_index = [i for i, a in enumerate(args) if a == "-e"]
        assert len(e_index) >= 3
        assert not any("faketoken" in p.read_text() for p in worktree_path.glob("*") if p.is_file())

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

        # Capture the real subprocess.run before patching: coding_tasks_service does
        # `import subprocess` (whole module), so patching ".run" on it patches the
        # very same module object this test file imported. Referring to the
        # (patched) `subprocess.run` name from inside the fallback branch would
        # recurse into the mock forever instead of reaching the real git call.
        real_run = subprocess.run

        with patch("src.services.coding_tasks_service.subprocess.run") as mock_run:
            def _fake_run(args, **kwargs):
                if args[:2] == ["docker", "run"]:
                    return MagicMock(stdout="containerid123\n", returncode=0)
                return real_run(args, **kwargs)
            mock_run.side_effect = _fake_run

            launched = service.launch(task)

        assert launched["status"] == "running"
        assert launched["container_id"] == "containerid123"
        assert launched["worktree_path"] == str(tmp_path / "worktrees" / "ct_abc123")
        assert launched["started_at"] is not None
        assert service.get_task("ct_abc123")["status"] == "running"

    def test_launch_rolls_back_worktree_and_marks_failed_when_spawn_fails(self, tmp_path, git_repo):
        """If spawn_container fails (docker daemon down, image missing, etc.)
        after create_worktree already succeeded, the worktree/branch must not
        be left orphaned, and the task must transition to a terminal 'failed'
        state (with a notification) instead of staying stuck in 'proposed'
        forever -- which would also block any retry of the same task_id since
        create_worktree isn't idempotent."""
        service = CodingTasksService(
            data_path=tmp_path / "coding-tasks",
            repo_path=git_repo,
            worktrees_path=tmp_path / "worktrees",
            docker_image="mazkir-coding-agent:test",
            notifier=TelegramNotifier(bot_token=None),
        )
        task = {
            "id": "ct_fail1", "chat_id": 42, "branch": "coding-agent/ct_fail1",
            "prompt": "fix the bug", "status": "proposed",
            "task_description": "fix the bug",
        }
        worktree_path = tmp_path / "worktrees" / "ct_fail1"

        real_run = subprocess.run

        def _fake_run(args, **kwargs):
            if args[:2] == ["docker", "run"]:
                raise subprocess.CalledProcessError(1, args, output="", stderr="docker: Cannot connect to the Docker daemon")
            return real_run(args, **kwargs)

        with patch("src.services.coding_tasks_service.subprocess.run", side_effect=_fake_run):
            with patch.object(service.notifier, "send_message") as mock_notify:
                launched = service.launch(task)

        assert launched["status"] == "failed"
        assert launched["container_id"] is None
        assert launched["finished_at"] is not None
        assert "Docker daemon" in launched["summary"] or "docker" in launched["summary"].lower()

        # Persisted state matches the failed status returned.
        saved = service.get_task("ct_fail1")
        assert saved["status"] == "failed"

        # Worktree directory was cleaned up rather than left orphaned.
        assert not worktree_path.exists()

        # Notification was sent about the failure.
        mock_notify.assert_called_once()
        notified_chat_id, notified_text = mock_notify.call_args[0]
        assert notified_chat_id == 42
        assert "FAILED" in notified_text


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
