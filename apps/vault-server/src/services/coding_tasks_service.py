"""CodingTasksService — provisions isolated worktree+container coding
sessions and tracks their lifecycle in data/coding-tasks/{id}.json.

Mirrors the JSON-per-id storage pattern used by EventsService
(src/services/events_service.py).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

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
        github_token_path: Path | None = None,
        vault_repo_path: Path | None = None,
        claude_json_path: Path | None = None,
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

    def _clone_repo(self, repo_path: Path, worktree_path: Path, branch: str) -> None:
        """Create an isolated, self-contained clone of repo_path at
        worktree_path, checked out on a new branch. Deliberately a clone,
        not `git worktree add`: a linked worktree's .git is just a pointer
        (`gitdir: /absolute/host/path/.git/worktrees/<name>`) back to the
        main repo's .git directory. That path is unreachable once only the
        worktree directory is mounted into a container -- confirmed
        directly: every git command inside such a container fails with
        "fatal: not a git repository", meaning a container could edit files
        but never git add/commit/push. A clone has its own fully
        self-contained .git with no external path dependency, and is fast
        here since it's a same-filesystem clone (git hardlinks the object
        database rather than copying it).

        If worktree_path already exists, this is a no-op (idempotent reuse
        for a retried task_id) -- note this means a task whose directory
        was deleted out-of-band loses any local, unpushed commits, unlike a
        linked worktree's shared object database; an acceptable trade for
        actually working inside a container at all.
        """
        if worktree_path.exists():
            return
        subprocess.run(
            ["git", "clone", str(repo_path), str(worktree_path)],
            check=True, capture_output=True, text=True,
        )
        subprocess.run(
            ["git", "checkout", "-b", branch],
            cwd=worktree_path, check=True, capture_output=True, text=True,
        )

    def create_worktree(self, task_id: str, branch: str) -> Path:
        worktree_path = self.worktrees_path / task_id
        self._clone_repo(self.repo_path, worktree_path, branch)
        return worktree_path

    def create_vault_worktree(self, task_id: str, branch: str) -> Path | None:
        """Create an isolated clone of the memory (vault) repo, nested at
        {worktrees_path}/{task_id}/memory to mirror the real host layout
        where memory/ sits inside the mazkir checkout — a fully independent
        clone of the separate mazkir-memory repo, unrelated to the mazkir
        clone's own git history. Must be called after create_worktree() for
        the same task_id, so the parent directory already exists. Returns
        the path, or None if vault_repo_path isn't configured."""
        if not self.vault_repo_path:
            return None
        worktree_path = self.worktrees_path / task_id / "memory"
        self._clone_repo(self.vault_repo_path, worktree_path, branch)
        return worktree_path

    def _remove_worktree(self, repo_path: Path, worktree_path: Path) -> None:
        # Not a registered git worktree (see _clone_repo) -- just a plain
        # directory to remove. repo_path is unused; kept for call-site
        # symmetry with the (now historical) worktree-based signature.
        shutil.rmtree(worktree_path, ignore_errors=True)

    @contextmanager
    def _git_credential_env_file(self) -> Iterator[list[str]]:
        """Yield `--env-file` flags scoping a GitHub credential to this one
        container process, or [] if no token is configured.

        The credential goes through a mode-0600 temp file rather than `-e`
        flags: anything passed in argv is copied into the container's
        metadata, where `docker inspect` will echo it back for as long as the
        container exists, and is visible in the host process list while
        `docker run` executes. The file is unlinked as soon as docker has
        read it, so the token is never at rest on disk beyond that.

        GIT_CONFIG_* drives an insteadOf rewrite so `git push` authenticates;
        GH_TOKEN separately authenticates `gh` itself for `gh pr create`,
        which the session needs because master takes PRs only.
        """
        if not self.github_token_path or not self.github_token_path.exists():
            yield []
            return
        token = self.github_token_path.read_text().strip()
        if not token:
            yield []
            return

        # mkstemp creates with 0600 and O_EXCL, so the token is never briefly
        # world-readable the way a plain open() under a default umask is.
        fd, raw_path = tempfile.mkstemp(prefix="mazkir-coding-", suffix=".env")
        env_path = Path(raw_path)
        try:
            with os.fdopen(fd, "w") as f:
                f.write(
                    "GIT_CONFIG_COUNT=1\n"
                    f"GIT_CONFIG_KEY_0=url.https://x-access-token:{token}@github.com/.insteadOf\n"
                    "GIT_CONFIG_VALUE_0=git@github.com:\n"
                    f"GH_TOKEN={token}\n"
                )
            yield ["--env-file", str(env_path)]
        finally:
            env_path.unlink(missing_ok=True)

    def spawn_container(
        self,
        task_id: str,
        worktree_path: Path,
        prompt: str,
        vault_worktree_path: Path | None = None,
    ) -> str:
        # The brief is also written to disk so a human taking the session over
        # interactively can read what the agent was asked to do, but the text
        # itself is what gets passed to `claude -p` -- that flag takes prompt
        # text, and handing it a path makes the path the entire prompt.
        prompt_path = worktree_path / ".coding-task-prompt.md"
        prompt_path.write_text(prompt)
        vault_mount_args = (
            ["-v", f"{vault_worktree_path}:/workspace/memory"]
            if vault_worktree_path else []
        )
        # ~/.claude.json is a sibling *file* of ~/.claude, so the named auth
        # volume below does not cover it -- and Docker cannot target a single
        # file with a named volume anyway. It holds onboarding state and the
        # per-project trust flag; without it the container falls back to the
        # empty file the Dockerfile touches, which Claude Code rejects as
        # corrupt ("JSON Parse error: Unexpected EOF") and then exits.
        claude_json_mount_args = (
            ["-v", f"{self.claude_json_path}:/home/marcellmc/.claude.json"]
            if self.claude_json_path else []
        )
        with self._git_credential_env_file() as credential_args:
            result = subprocess.run(
                [
                    "docker", "run", "-d",
                    "--name", f"mazkir-coding-{task_id}",
                    "-v", f"{worktree_path}:/workspace",
                    *vault_mount_args,
                    *claude_json_mount_args,
                    "-v", "mazkir-claude-auth:/home/marcellmc/.claude",
                    "-v", "/home/marcellmc/.claude/plugins:/home/marcellmc/.claude/plugins",
                    "-w", "/workspace",
                    *credential_args,
                    self.docker_image,
                    "claude", "--dangerously-skip-permissions",
                    "-p", prompt,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        return result.stdout.strip()

    def launch(self, task: dict[str, Any]) -> dict[str, Any]:
        """Provision a worktree + container for a proposed task, persisting
        its running state. Assumes task already has 'id', 'branch', 'prompt'.

        If any provisioning step fails after the mazkir clone was already
        created -- the vault clone or spawn_container -- every clone made so
        far is removed (best-effort) and the task is persisted as 'failed' +
        notified, rather than left orphaned in 'proposed' with a dangling
        directory. That directory matters: create_worktree reuses an existing
        path as-is, so an orphan would silently hand back a stale clone on
        the next retry of the same task_id. The task dict is still returned
        (not raised) so callers that build a normal 'ok' response from the
        return value (e.g. propose_coding_session) don't need special-casing
        -- they just see status == 'failed'.
        """
        worktree_path = self.create_worktree(task["id"], task["branch"])
        vault_worktree_path = None
        try:
            vault_worktree_path = self.create_vault_worktree(task["id"], task["branch"])
            container_id = self.spawn_container(
                task["id"], worktree_path, task["prompt"],
                vault_worktree_path=vault_worktree_path,
            )
        except Exception as e:
            logger.error(f"provisioning failed for task {task['id']}: {e}")
            for repo, path in ((self.repo_path, worktree_path), (self.vault_repo_path, vault_worktree_path)):
                if path is None:
                    continue
                try:
                    self._remove_worktree(repo, path)
                except Exception as cleanup_err:
                    logger.warning(
                        f"failed to clean up worktree {path} for task {task['id']} "
                        f"after provisioning failure: {cleanup_err}"
                    )
            task["worktree_path"] = str(worktree_path)
            task["vault_worktree_path"] = str(vault_worktree_path) if vault_worktree_path else None
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

        task["worktree_path"] = str(worktree_path)
        task["vault_worktree_path"] = str(vault_worktree_path) if vault_worktree_path else None
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

    def check_running_tasks(self) -> list[dict[str, Any]]:
        """Poll all 'running' tasks; for any whose container has exited, mark
        done (exit 0) or failed (non-zero), capture a summary from its logs,
        reap the container, and notify via Telegram. Returns the tasks that
        transitioned this call."""
        transitioned = []
        for task in self.list_tasks(status="running"):
            if self._container_running(task["container_id"]):
                continue
            logs = self._container_logs(task["container_id"])
            exit_code = self._container_exit_code(task["container_id"])
            task["status"] = "done" if exit_code == 0 else "failed"
            task["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            task["summary"] = logs[-2000:]
            self._save_logs(task["id"], logs)
            task["log_path"] = str(self._log_file_path(task["id"]))
            self.save_task(task)
            self._remove_container(task["container_id"])
            status_label = "finished" if task["status"] == "done" else "FAILED"
            self.notifier.send_message(
                task["chat_id"],
                f"Coding session {status_label}: {task['task_description']}\n\n"
                f"Branch: {task['branch']}\nWorktree: {task['worktree_path']}\n\n"
                f"{task['summary'][-500:]}",
            )
            transitioned.append(task)
        return transitioned
