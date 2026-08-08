"""CodingTasksService — assembles task briefs, launches coding sessions via
infra/coding-agent/session.sh, and tracks their lifecycle in
data/coding-tasks/{id}.json.

Provisioning, credentials, and container launching all live in session.sh,
not here: a second implementation is what let the automated and manual
paths drift apart, and the divergence broke every automated session.

Mirrors the JSON-per-id storage pattern used by EventsService
(src/services/events_service.py).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.services.telegram_notifier import TelegramNotifier

logger = logging.getLogger(__name__)

DEFAULT_TRACE_WINDOW_MINUTES = 30

# The closing instruction is the only thing that differs between lanes.
#
# Autonomous exits when done, so "done" has to mean the work is durable: a
# clone is its own object database, and anything committed but never pushed
# exists in exactly one disposable place. The previous wording ("do not
# push to master/origin directly") was read by a real session as
# do-not-push-at-all -- it committed locally and reported "not pushed
# anywhere, per the constraints".
_LANE_INSTRUCTIONS = {
    "autonomous": (
        "- When the work is done: commit, `git push -u origin {branch}`, then\n"
        "  `gh pr create`. The upstream is mandatory. Do this separately for\n"
        "  /workspace and /workspace/memory if you touched both.\n"
        "- Do not push to master. It is branch-protected; open a PR.\n"
    ),
    "handoff-checkpoints": (
        "- Work in steps and stop to check in at each natural checkpoint. A\n"
        "  human will join this session to steer it.\n"
        "- Do not push to master. Leave landing decisions to the human.\n"
    ),
    "handoff-run-through": (
        "- Run to completion, then report what you did and wait. A human will\n"
        "  join this session to review.\n"
        "- Do not push to master. Leave landing decisions to the human.\n"
    ),
    "handoff-wait": (
        "- Do not start yet. Read the task above and wait for instructions; a\n"
        "  human will join this session and drive it.\n"
    ),
}

DEFAULT_LANE = "handoff-checkpoints"


class CodingTasksService:
    def __init__(
        self,
        data_path: Path,
        repo_path: Path,
        worktrees_path: Path,
        docker_image: str,
        notifier: TelegramNotifier,
        audit_log_path: Path | None = None,
        github_token_path: Path | None = None,
        vault_repo_path: Path | None = None,
        claude_json_path: Path | None = None,
        session_script: Path | None = None,
    ):
        self.data_path = Path(data_path)
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.repo_path = Path(repo_path)
        self.worktrees_path = Path(worktrees_path)
        self.worktrees_path.mkdir(parents=True, exist_ok=True)
        self.docker_image = docker_image
        self.notifier = notifier
        self.audit_log_path = Path(audit_log_path) if audit_log_path else None
        self.github_token_path = Path(github_token_path) if github_token_path else None
        self.vault_repo_path = Path(vault_repo_path) if vault_repo_path else None
        self.claude_json_path = Path(claude_json_path) if claude_json_path else None
        self.session_script = Path(session_script) if session_script else None

    def _file_path(self, task_id: str) -> Path:
        return self.data_path / f"{task_id}.json"

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        path = self._file_path(task_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception as e:
            logger.error(f"Failed to read coding task {task_id}: {e}")
            return None

    def save_task(self, task: dict[str, Any]) -> None:
        """Persist a task via write-to-temp + atomic rename.

        The background poller reads these files on its own schedule while
        request handlers write them, so a plain write_text would let a reader
        catch a truncated file — and a write that died partway would leave
        that truncation as the permanent stored state.
        """
        path = self._file_path(task["id"])
        tmp_path = path.with_name(f".{path.name}.tmp")
        try:
            tmp_path.write_text(json.dumps(task, indent=2))
            os.replace(tmp_path, path)
        finally:
            tmp_path.unlink(missing_ok=True)

    def list_tasks(self, status: str | None = None) -> list[dict[str, Any]]:
        tasks = []
        for p in sorted(self.data_path.glob("*.json")):
            try:
                tasks.append(json.loads(p.read_text()))
            except Exception as e:
                logger.error(f"Skipping unreadable coding task file {p}: {e}")
                continue
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
        session_mode: str = DEFAULT_LANE,
    ) -> str:
        trace_line = trace_id if trace_id else "not found"
        lane = _LANE_INSTRUCTIONS.get(session_mode, _LANE_INSTRUCTIONS[DEFAULT_LANE])
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
            f"- Run `{test_command}` before considering this done.\n"
            f"{lane.format(branch=branch)}"
            "- Summarize what changed and why in your final message.\n\n"
            "Read `infra/coding-agent/CONVENTIONS.md` first — it covers the two-repo\n"
            "layout, why `memory/` may be empty, and why you must never guess at\n"
            "absolute host paths. See CLAUDE.md for the architecture map.\n"
        )

    # session.sh owns provisioning, credentials, and launching for every
    # lane. Building a second docker invocation here is what let the
    # automated and manual paths drift apart: docker-compose.yml mounted
    # ~/.claude.json and spawn_container did not, so every automated session
    # booted on an empty config and exited within ~14 seconds.
    #
    # The four hand-off variants collapse to two session.sh modes: they
    # differ only in the brief, which is already baked into the prompt file.
    # handoff-wait maps to manual precisely because it must NOT be seeded --
    # the session idles until a human drives it.
    _MODE_MAP = {
        "autonomous": "autonomous",
        "handoff-checkpoints": "handoff",
        "handoff-run-through": "handoff",
        "handoff-wait": "manual",
    }

    def launch(self, task: dict[str, Any]) -> dict[str, Any]:
        """Provision and start a session via session.sh, persisting state.

        Returns the task rather than raising, so callers that build a normal
        'ok' response from the return value (propose_coding_session) need no
        special casing -- they just see status == 'failed'.
        """
        session_mode = task.get("session_mode", DEFAULT_LANE)
        mode = self._MODE_MAP.get(session_mode, "handoff")

        prompt_path = self.data_path / f"{task['id']}-prompt.md"
        prompt_path.write_text(task["prompt"])

        cmd = [
            str(self.session_script), "start", task["id"],
            f"--mode={mode}",
            f"--root={self.worktrees_path}",
        ]
        if mode != "manual":
            cmd.append(f"--prompt-file={prompt_path}")

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except Exception as e:
            logger.error(f"session.sh failed for task {task['id']}: {e}")
            task["worktree_path"] = str(self.worktrees_path / task["id"])
            task["container_id"] = None
            task["status"] = "failed"
            task["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            task["summary"] = f"Failed to launch coding session: {e}"
            self.save_task(task)
            self.notifier.send_message(
                task.get("chat_id"),
                f"Coding session FAILED: {task.get('task_description', '?')}\n\n"
                f"Branch: {task['branch']}\nWorktree: {task['worktree_path']}\n\n"
                f"{task['summary'][-500:]}",
            )
            return task

        task["worktree_path"] = str(self.worktrees_path / task["id"])
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

    def _log_file_path(self, task_id: str) -> Path:
        return self.data_path / f"{task_id}.log"

    def _save_logs(self, task_id: str, logs: str) -> None:
        """Persist the container's full transcript next to its task JSON.

        `summary` only keeps the tail, and the container -- the sole other
        copy -- is removed right after, so a failed session would otherwise
        leave nothing to debug from.
        """
        try:
            self._log_file_path(task_id).write_text(logs)
        except OSError as e:
            logger.warning(f"failed to persist logs for task {task_id}: {e}")

    def _remove_container(self, container_id: str) -> None:
        """Reap an exited container. `docker run -d` can't use --rm (the logs
        have to outlive the process), so removal happens here instead, once
        the transcript is safely on disk. Best-effort: a container that is
        already gone is not a reason to fail the transition."""
        try:
            subprocess.run(
                ["docker", "rm", container_id],
                capture_output=True, text=True, check=False,
            )
        except Exception as e:
            logger.warning(f"failed to remove container {container_id}: {e}")

    def _clean_session(self, task_id: str) -> str | None:
        """Ask session.sh whether this session is safe to remove, and remove
        it if so.

        The four retention predicates live there and only there -- a second
        implementation here would be a second place to be wrong about
        destroying unpushed work, which exists in exactly one place because
        a clone is its own object database.

        A refusal is the expected outcome for a session that did not push,
        not a failure. Returns the reason it was kept, or None when removed.
        """
        if not self.session_script:
            return None
        try:
            subprocess.run(
                [str(self.session_script), "clean", task_id,
                 f"--root={self.worktrees_path}"],
                check=True, capture_output=True, text=True,
            )
            return None
        except subprocess.CalledProcessError as e:
            note = (e.stderr or "").strip() or "cleanup refused"
            logger.info(f"session {task_id} kept: {note}")
            return note
        except Exception as e:
            logger.warning(f"cleanup failed for session {task_id}: {e}")
            return str(e)

    def check_running_tasks(self) -> list[dict[str, Any]]:
        """Poll all 'running' tasks; for any whose container has exited, mark
        done (exit 0) or failed (non-zero), capture a summary from its logs,
        reap the container, and notify via Telegram. Returns the tasks that
        transitioned this call."""
        transitioned = []
        for task in self.list_tasks(status="running"):
            # Hand-off and manual sessions stay alive by design: there is no
            # completion to detect, and polling would transition them the
            # moment the user closed the container. A task with no
            # session_mode predates the field, so it defaults to the
            # unmonitored lane rather than being reaped unexpectedly.
            if task.get("session_mode", DEFAULT_LANE) != "autonomous":
                continue
            container_id = task.get("container_id") or f"mazkir-coding-{task['id']}"
            if self._container_running(container_id):
                continue
            logs = self._container_logs(container_id)
            exit_code = self._container_exit_code(container_id)
            task["status"] = "done" if exit_code == 0 else "failed"
            task["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            task["summary"] = logs[-2000:]
            self._save_logs(task["id"], logs)
            task["log_path"] = str(self._log_file_path(task["id"]))
            self.save_task(task)
            self._remove_container(container_id)

            note = self._clean_session(task["id"])
            if note:
                task["cleanup_note"] = note
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
