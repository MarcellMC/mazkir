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

    def test_save_task_leaves_prior_state_intact_when_the_write_dies_partway(self, service):
        """The poller reads these files on its own schedule while handlers
        write them. A half-written file must never become the stored state."""
        original = {"id": "ct_1", "status": "running", "chat_id": 42}
        service.save_task(original)

        def half_write(self, data, *args, **kwargs):
            with open(self, "w") as f:
                f.write(data[: len(data) // 2])
            raise OSError("no space left on device")

        with patch.object(Path, "write_text", half_write):
            with pytest.raises(OSError):
                service.save_task({"id": "ct_1", "status": "done", "chat_id": 42})

        assert service.get_task("ct_1") == original

    def test_save_task_leaves_no_temp_file_behind_when_the_write_fails(self, service):
        service.save_task({"id": "ct_1", "status": "running"})

        def boom(self, data, *args, **kwargs):
            raise OSError("no space left on device")

        with patch.object(Path, "write_text", boom):
            with pytest.raises(OSError):
                service.save_task({"id": "ct_1", "status": "done"})

        assert [p.name for p in service.data_path.iterdir()] == ["ct_1.json"]

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
        # Not "do not push to master/origin": a real session read that as
        # do-not-push-at-all and left its work inside a disposable clone.
        # The lane instruction now says what to avoid without forbidding the
        # branch push that makes the work durable.
        assert "Do not push to master." in brief
        assert "CLAUDE.md" in brief

    def test_missing_trace_id_shows_not_found(self, service):
        brief = service.assemble_brief(
            task_description="x", conversation_excerpt="y", likely_area="z",
            branch="b", worktree_path=Path("/tmp/w"), test_command="t",
            trace_id=None, reported_at=datetime(2026, 7, 27, 14, 32, tzinfo=timezone.utc),
        )
        assert "not found" in brief


# The git_repo/vault_repo fixtures and the TestCreateWorktree /
# TestSpawnAndLaunch classes were removed here. Cloning, remote rewriting,
# credential handling, and container launching all moved into
# infra/coding-agent/session.sh, and are covered by
# tests/test_session_script.py driving the real script. Keeping a second
# set of assertions here would recreate the drift this change removes.


class TestCheckRunningTasks:
    @staticmethod
    def _exited_container(exit_code="0\n", logs="all done", stderr=""):
        """subprocess.run fake for a container that has already exited."""
        def _fake_run(args, **kwargs):
            if args[:2] == ["docker", "inspect"] and "State.Running" in args[3]:
                return MagicMock(stdout="false\n", returncode=0)
            if args[:2] == ["docker", "inspect"] and "State.ExitCode" in args[3]:
                return MagicMock(stdout=exit_code, returncode=0)
            if args[:2] == ["docker", "logs"]:
                return MagicMock(stdout=logs, stderr=stderr, returncode=0)
            if args[:2] == ["docker", "rm"]:
                return MagicMock(stdout="", stderr="", returncode=0)
            raise AssertionError(f"unexpected subprocess call: {args}")
        return _fake_run

    def test_removes_container_after_terminal_transition(self, service):
        """`docker run -d` without --rm leaves the container behind forever;
        nothing else ever reaps it."""
        service.save_task({
            "id": "ct_1", "chat_id": 42, "status": "running",
            "container_id": "c1", "task_description": "fix it",
            "branch": "coding-agent/ct_1", "worktree_path": "/tmp/w1",
        })
        calls = []
        fake = self._exited_container()
        def _record(args, **kwargs):
            calls.append(args)
            return fake(args, **kwargs)

        with patch("src.services.coding_tasks_service.subprocess.run", side_effect=_record):
            with patch.object(service.notifier, "send_message"):
                service.check_running_tasks()

        assert any(a[:2] == ["docker", "rm"] and "c1" in a for a in calls)

    def test_does_not_remove_a_still_running_container(self, service):
        service.save_task({
            "id": "ct_1", "chat_id": 42, "status": "running",
            "container_id": "c1", "task_description": "fix it",
            "branch": "coding-agent/ct_1", "worktree_path": "/tmp/w1",
        })
        calls = []
        def _fake_run(args, **kwargs):
            calls.append(args)
            return MagicMock(stdout="true\n", returncode=0)

        with patch("src.services.coding_tasks_service.subprocess.run", side_effect=_fake_run):
            service.check_running_tasks()

        assert not any(a[:2] == ["docker", "rm"] for a in calls)

    def test_persists_full_logs_before_removing_the_container(self, service):
        """summary keeps only the tail; removing the container destroys the
        only other copy, so the full transcript has to be saved first."""
        long_logs = "line\n" * 2000
        service.save_task({
            "id": "ct_1", "chat_id": 42, "status": "running",
            "container_id": "c1", "task_description": "fix it",
            "branch": "coding-agent/ct_1", "worktree_path": "/tmp/w1",
        })
        with patch(
            "src.services.coding_tasks_service.subprocess.run",
            side_effect=self._exited_container(logs=long_logs),
        ):
            with patch.object(service.notifier, "send_message"):
                service.check_running_tasks()

        log_file = service.data_path / "ct_1.log"
        assert log_file.exists()
        assert log_file.read_text() == long_logs
        assert len(service.get_task("ct_1")["summary"]) <= 2000

    def test_failed_container_removal_does_not_break_the_transition(self, service):
        service.save_task({
            "id": "ct_1", "chat_id": 42, "status": "running",
            "container_id": "c1", "task_description": "fix it",
            "branch": "coding-agent/ct_1", "worktree_path": "/tmp/w1",
        })
        fake = self._exited_container()
        def _fake_run(args, **kwargs):
            if args[:2] == ["docker", "rm"]:
                raise subprocess.CalledProcessError(1, args)
            return fake(args, **kwargs)

        with patch("src.services.coding_tasks_service.subprocess.run", side_effect=_fake_run):
            with patch.object(service.notifier, "send_message") as mock_notify:
                transitioned = service.check_running_tasks()

        assert len(transitioned) == 1
        assert service.get_task("ct_1")["status"] == "done"
        mock_notify.assert_called_once()

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


class TestBriefPerLane:
    def _brief(self, service, mode):
        return service.assemble_brief(
            task_description="fix the thing",
            conversation_excerpt="it is broken",
            likely_area="apps/vault-server",
            branch="coding-agent/ct_1",
            worktree_path=Path("/workspace"),
            test_command="npx turbo test",
            trace_id=None,
            reported_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
            session_mode=mode,
        )

    def test_autonomous_brief_mandates_push_and_pr(self, service):
        """A clone is its own object database: work committed and never
        pushed exists in exactly one place, and that place is disposable.
        The old wording made a real session skip pushing entirely."""
        brief = self._brief(service, "autonomous")

        assert "git push -u origin" in brief
        assert "gh pr create" in brief

    def test_checkpoints_brief_asks_the_session_to_stop_and_wait(self, service):
        brief = self._brief(service, "handoff-checkpoints")

        assert "check in" in brief.lower()
        assert "gh pr create" not in brief

    def test_run_through_brief_asks_for_completion_then_a_report(self, service):
        brief = self._brief(service, "handoff-run-through")

        assert "run to completion" in brief.lower()

    def test_wait_brief_tells_the_session_to_do_nothing_yet(self, service):
        brief = self._brief(service, "handoff-wait")

        assert "do not start" in brief.lower()

    def test_unknown_mode_falls_back_to_the_supervised_lane(self, service):
        brief = self._brief(service, "nonsense")

        assert "check in" in brief.lower()

    def test_every_brief_points_at_the_conventions(self, service):
        """CONVENTIONS.md ships in every clone but nothing autoloads it,
        so the two-repo warning was never read by the agents it targets."""
        for mode in ("autonomous", "handoff-checkpoints",
                     "handoff-run-through", "handoff-wait"):
            assert "infra/coding-agent/CONVENTIONS.md" in self._brief(service, mode)


class TestLaunchViaSessionScript:
    def _service(self, tmp_path):
        return CodingTasksService(
            data_path=tmp_path / "coding-tasks",
            repo_path=tmp_path / "repo",
            worktrees_path=tmp_path / "agent-sessions",
            docker_image="mazkir-coding-agent:test",
            notifier=TelegramNotifier(bot_token=None),
            session_script=tmp_path / "session.sh",
        )

    def _task(self, task_id, mode):
        return {
            "id": task_id, "chat_id": 42, "branch": f"coding-agent/{task_id}",
            "prompt": "the actual brief text", "status": "proposed",
            "task_description": "fix it", "session_mode": mode,
        }

    def test_launch_shells_out_to_session_script(self, tmp_path):
        """One implementation for automated and manual paths. They drifted
        before: docker-compose.yml mounted ~/.claude.json and
        spawn_container did not, so every automated session died on boot."""
        service = self._service(tmp_path)

        with patch("src.services.coding_tasks_service.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            service.launch(self._task("ct_1", "autonomous"))

        args = mock_run.call_args[0][0]
        assert args[0] == str(tmp_path / "session.sh")
        assert args[1] == "start"
        assert "ct_1" in args
        assert "--mode=autonomous" in args
        assert f"--root={tmp_path / 'agent-sessions'}" in args

    def test_launch_maps_handoff_variants_to_the_handoff_mode(self, tmp_path):
        """session.sh knows three modes; the variants differ only in the
        brief, which is already baked into the prompt file."""
        service = self._service(tmp_path)

        with patch("src.services.coding_tasks_service.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            service.launch(self._task("ct_2", "handoff-run-through"))

        assert "--mode=handoff" in mock_run.call_args[0][0]

    def test_wait_variant_maps_to_manual_with_no_seed_prompt(self, tmp_path):
        """handoff-wait means the session idles until a human drives it, so
        it must not be seeded with a prompt that starts work."""
        service = self._service(tmp_path)

        with patch("src.services.coding_tasks_service.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            service.launch(self._task("ct_3", "handoff-wait"))

        args = mock_run.call_args[0][0]
        assert "--mode=manual" in args
        assert not any(a.startswith("--prompt-file=") for a in args)

    def test_launch_writes_the_brief_to_the_prompt_file_it_passes(self, tmp_path):
        service = self._service(tmp_path)

        with patch("src.services.coding_tasks_service.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            service.launch(self._task("ct_4", "autonomous"))

        args = mock_run.call_args[0][0]
        prompt_arg = next(a for a in args if a.startswith("--prompt-file="))
        assert Path(prompt_arg.split("=", 1)[1]).read_text() == "the actual brief text"

    def test_launch_marks_failed_and_notifies_when_the_script_fails(self, tmp_path):
        service = self._service(tmp_path)

        with patch("src.services.coding_tasks_service.subprocess.run",
                   side_effect=subprocess.CalledProcessError(1, "session.sh", stderr="boom")):
            with patch.object(service.notifier, "send_message") as mock_notify:
                launched = service.launch(self._task("ct_5", "autonomous"))

        assert launched["status"] == "failed"
        assert service.get_task("ct_5")["status"] == "failed"
        mock_notify.assert_called_once()
