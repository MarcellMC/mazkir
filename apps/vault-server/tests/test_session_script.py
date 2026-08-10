"""Tests for infra/coding-agent/session.sh.

Provisioning is where this feature has actually broken -- twice -- so it
gets real tests driving the real script against throwaway git repos,
rather than assertions on a mocked argv.
"""

import subprocess
from pathlib import Path

import pytest

SESSION_SH = Path(__file__).resolve().parents[3] / "infra" / "coding-agent" / "session.sh"


def _git(*args, cwd):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def source_repo(tmp_path):
    """A repo shaped like the real mazkir checkout: a commit, and a
    GitHub SSH origin."""
    repo = tmp_path / "source"
    repo.mkdir()
    _git("init", "-b", "master", cwd=repo)
    _git("config", "user.email", "test@test.com", cwd=repo)
    _git("config", "user.name", "Test", cwd=repo)
    (repo / "README.md").write_text("hello")
    _git("add", "README.md", cwd=repo)
    _git("commit", "-m", "initial", cwd=repo)
    _git("remote", "add", "origin", "git@github.com:Test/source.git", cwd=repo)
    return repo


def _provision(name, source_repo, root, *extra):
    return subprocess.run(
        [str(SESSION_SH), "provision", name,
         f"--repo={source_repo}", f"--root={root}", *extra],
        capture_output=True, text=True,
    )


def test_provision_creates_clone_on_a_session_branch(source_repo, tmp_path):
    root = tmp_path / "agent-sessions"
    result = _provision("fix-thing", source_repo, root)

    assert result.returncode == 0, result.stderr
    session = root / "fix-thing"
    assert (session / "README.md").exists()
    assert (session / ".git").is_dir()
    assert _git("rev-parse", "--abbrev-ref", "HEAD", cwd=session) == "coding-agent/fix-thing"


def test_provision_rewrites_origin_to_the_github_url(source_repo, tmp_path):
    """A clone inherits the local path as origin, so `git push` would write
    into the user's own checkout and `gh pr create` would have no GitHub
    remote to target."""
    root = tmp_path / "agent-sessions"
    _provision("fix-thing", source_repo, root)

    origin = _git("remote", "get-url", "origin", cwd=root / "fix-thing")
    assert origin == "git@github.com:Test/source.git"


def test_provision_refuses_when_source_origin_is_not_a_remote_url(tmp_path):
    """Guard against silently provisioning a clone that can never push."""
    repo = tmp_path / "local-only"
    repo.mkdir()
    _git("init", "-b", "master", cwd=repo)
    _git("config", "user.email", "t@t.com", cwd=repo)
    _git("config", "user.name", "T", cwd=repo)
    (repo / "f.txt").write_text("x")
    _git("add", "f.txt", cwd=repo)
    _git("commit", "-m", "init", cwd=repo)
    _git("remote", "add", "origin", str(tmp_path / "somewhere"), cwd=repo)

    result = _provision("x", repo, tmp_path / "agent-sessions")

    assert result.returncode != 0
    assert "not a remote URL" in (result.stdout + result.stderr)


def test_provision_is_idempotent_for_an_existing_session(source_repo, tmp_path):
    root = tmp_path / "agent-sessions"
    _provision("fix-thing", source_repo, root)
    (root / "fix-thing" / "scratch.txt").write_text("work in progress")

    result = _provision("fix-thing", source_repo, root)

    assert result.returncode == 0, result.stderr
    assert (root / "fix-thing" / "scratch.txt").read_text() == "work in progress"


@pytest.fixture
def vault_repo(tmp_path):
    repo = tmp_path / "vault-source"
    repo.mkdir()
    _git("init", "-b", "master", cwd=repo)
    _git("config", "user.email", "test@test.com", cwd=repo)
    _git("config", "user.name", "Test", cwd=repo)
    (repo / "AGENTS.md").write_text("vault schemas")
    _git("add", "AGENTS.md", cwd=repo)
    _git("commit", "-m", "initial", cwd=repo)
    _git("remote", "add", "origin", "git@github.com:Test/vault.git", cwd=repo)
    return repo


def test_provision_nests_an_independent_vault_clone(source_repo, vault_repo, tmp_path):
    root = tmp_path / "agent-sessions"
    result = _provision("fix-thing", source_repo, root, f"--vault-repo={vault_repo}")

    assert result.returncode == 0, result.stderr
    memory = root / "fix-thing" / "memory"
    assert (memory / "AGENTS.md").exists()
    assert (memory / ".git").is_dir(), "vault must be its own clone, not part of the parent"
    assert _git("remote", "get-url", "origin", cwd=memory) == "git@github.com:Test/vault.git"
    assert _git("rev-parse", "--abbrev-ref", "HEAD", cwd=memory) == "coding-agent/fix-thing"


def test_provision_without_vault_repo_leaves_memory_absent(source_repo, tmp_path):
    """No vault mount is deliberate, not a bug for the session to route
    around -- see infra/coding-agent/CONVENTIONS.md."""
    root = tmp_path / "agent-sessions"
    _provision("no-vault", source_repo, root)

    assert not (root / "no-vault" / "memory").exists()


def test_provision_rolls_back_the_mazkir_clone_when_the_vault_clone_fails(
    source_repo, tmp_path
):
    """An orphaned directory is worse than none: provision reuses an
    existing path as-is, so a retry would silently get a stale clone."""
    root = tmp_path / "agent-sessions"
    result = _provision(
        "boom", source_repo, root, f"--vault-repo={tmp_path / 'does-not-exist'}"
    )

    assert result.returncode != 0
    assert not (root / "boom").exists()


CONTAINER_PATH_VARS = {
    "VAULT_PATH": "/workspace/memory",
    "MAZKIR_SKILLS_DIR": "/workspace/memory/00-system/skills",
    "MEDIA_PATH": "/workspace/memory/00-system/media",
    "TIMELINE_DATA_PATH": "/workspace/data/timeline",
    "EVENTS_DATA_PATH": "/workspace/data/events",
    "LOGS_DIR": "/workspace/data/logs",
    "CODING_TASKS_DATA_PATH": "/workspace/data/coding-tasks",
    "CODING_AGENT_WORKTREES_PATH": "/workspace/.agent-sessions",
    "MAZKIR_REPO_PATH": "/workspace",
    "MAZKIR_VAULT_REPO_PATH": "/workspace/memory",
}


def _env_map(path):
    out = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def test_provision_writes_a_session_env_with_container_paths(source_repo, tmp_path):
    """config.py's defaults resolve under ~/dev/mazkir, which does not
    exist in a container where the repo is mounted at /workspace."""
    (source_repo / "apps" / "vault-server").mkdir(parents=True)
    (source_repo / "apps" / "vault-server" / ".env.example").write_text(
        "API_KEY=\nVAULT_PATH=/home/marcellmc/pkm\nCLAUDE_MODEL=claude-sonnet-4-6\n"
    )
    _git("add", "-A", cwd=source_repo)
    _git("commit", "-m", "add env example", cwd=source_repo)

    root = tmp_path / "agent-sessions"
    _provision("envtest", source_repo, root)

    env = _env_map(root / "envtest" / "apps" / "vault-server" / ".env")
    for key, expected in CONTAINER_PATH_VARS.items():
        assert env.get(key) == expected, f"{key} should be {expected}, got {env.get(key)}"
    assert env["CLAUDE_MODEL"] == "claude-sonnet-4-6", "non-path values carry over"


def test_provision_without_env_example_still_succeeds(source_repo, tmp_path):
    root = tmp_path / "agent-sessions"
    result = _provision("noenv", source_repo, root)

    assert result.returncode == 0, result.stderr
    assert not (root / "noenv" / "apps" / "vault-server" / ".env").exists()


def _list(root):
    return subprocess.run(
        [str(SESSION_SH), "list", f"--root={root}"],
        capture_output=True, text=True,
    )


def _push_to_a_bare_upstream(session, tmp_path, name):
    """Give a session a real upstream so predicates 2 and 3 can pass."""
    bare = tmp_path / f"{name}.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    _git("remote", "set-url", "origin", str(bare), cwd=session)
    _git("push", "-u", "origin", "HEAD", cwd=session)


def test_list_reports_uncommitted_work_as_keep(source_repo, tmp_path):
    root = tmp_path / "agent-sessions"
    _provision("dirty", source_repo, root)
    (root / "dirty" / "new.txt").write_text("uncommitted")

    out = _list(root).stdout

    assert "dirty" in out
    assert "KEEP" in out
    assert "uncommitted" in out


def test_list_reports_no_upstream_as_keep(source_repo, tmp_path):
    root = tmp_path / "agent-sessions"
    _provision("noupstream", source_repo, root)

    out = _list(root).stdout

    assert "KEEP" in out
    assert "no upstream" in out


def test_list_reports_a_fully_pushed_session_as_safe(source_repo, tmp_path):
    root = tmp_path / "agent-sessions"
    _provision("pushed", source_repo, root)
    _push_to_a_bare_upstream(root / "pushed", tmp_path, "pushed")

    out = _list(root).stdout

    assert "SAFE" in out


def test_list_reports_unpushed_commits_as_keep(source_repo, tmp_path):
    root = tmp_path / "agent-sessions"
    _provision("ahead", source_repo, root)
    session = root / "ahead"
    _push_to_a_bare_upstream(session, tmp_path, "ahead")
    (session / "later.txt").write_text("after push")
    _git("add", "later.txt", cwd=session)
    _git("commit", "-m", "unpushed work", cwd=session)

    out = _list(root).stdout

    assert "KEEP" in out
    assert "unpushed" in out


def test_list_on_an_empty_root_says_so(tmp_path):
    root = tmp_path / "agent-sessions"
    root.mkdir()

    result = _list(root)

    assert result.returncode == 0
    assert "no sessions" in result.stdout.lower()


def _clean(name, root, *extra):
    return subprocess.run(
        [str(SESSION_SH), "clean", name, f"--root={root}", *extra],
        capture_output=True, text=True,
    )


def test_clean_removes_a_fully_pushed_session(source_repo, tmp_path):
    root = tmp_path / "agent-sessions"
    _provision("pushed", source_repo, root)
    _push_to_a_bare_upstream(root / "pushed", tmp_path, "pushed")

    result = _clean("pushed", root)

    assert result.returncode == 0, result.stderr
    assert not (root / "pushed").exists()


def test_clean_refuses_when_work_is_unpushed(source_repo, tmp_path):
    root = tmp_path / "agent-sessions"
    _provision("ahead", source_repo, root)
    session = root / "ahead"
    _push_to_a_bare_upstream(session, tmp_path, "ahead")
    (session / "later.txt").write_text("after push")
    _git("add", "later.txt", cwd=session)
    _git("commit", "-m", "unpushed", cwd=session)

    result = _clean("ahead", root)

    assert result.returncode != 0
    assert "unpushed" in (result.stdout + result.stderr)
    assert session.exists(), "refusing must not delete anything"


def test_clean_refuses_when_only_the_vault_clone_is_dirty(
    source_repo, vault_repo, tmp_path
):
    """The vault is nested inside the workspace, so removing the parent
    destroys it -- its push state has to be checked independently."""
    root = tmp_path / "agent-sessions"
    _provision("twins", source_repo, root, f"--vault-repo={vault_repo}")
    session = root / "twins"
    _push_to_a_bare_upstream(session, tmp_path, "twins")
    (session / "memory" / "note.md").write_text("unsaved vault work")

    result = _clean("twins", root)

    assert result.returncode != 0
    assert "memory" in (result.stdout + result.stderr)
    assert session.exists()


def test_clean_force_removes_despite_unpushed_work(source_repo, tmp_path):
    root = tmp_path / "agent-sessions"
    _provision("forced", source_repo, root)
    (root / "forced" / "scratch.txt").write_text("uncommitted")

    result = _clean("forced", root, "--force")

    assert result.returncode == 0, result.stderr
    assert not (root / "forced").exists()


def test_clean_on_a_missing_session_fails_clearly(tmp_path):
    root = tmp_path / "agent-sessions"
    root.mkdir()

    result = _clean("ghost", root)

    assert result.returncode != 0
    assert "ghost" in (result.stdout + result.stderr)


def _launch(name, root, *extra):
    return subprocess.run(
        [str(SESSION_SH), "launch", name, f"--root={root}", "--dry-run", *extra],
        capture_output=True, text=True,
    )


def test_manual_mode_starts_an_interactive_remote_control_session(source_repo, tmp_path):
    root = tmp_path / "agent-sessions"
    _provision("manual-one", source_repo, root)

    out = _launch("manual-one", root).stdout

    assert "--remote-control" in out
    assert "manual-one" in out
    assert " -p " not in out, "manual mode must not be headless"


def test_handoff_mode_seeds_the_brief_into_an_interactive_session(source_repo, tmp_path):
    """--remote-control is what makes a session attachable from Claude
    Mobile; -p is print mode and cannot be attached to."""
    root = tmp_path / "agent-sessions"
    _provision("handoff-one", source_repo, root)
    brief = tmp_path / "brief.md"
    brief.write_text("Fix the duplicate habits bug")

    out = _launch("handoff-one", root, "--mode=handoff", f"--prompt-file={brief}").stdout

    assert "--remote-control" in out
    assert "Fix the duplicate habits bug" in out
    assert " -p " not in out


def test_autonomous_mode_is_headless_and_carries_the_brief_text(source_repo, tmp_path):
    """`claude -p` takes prompt text, not a path -- passing the path makes
    the path the entire prompt."""
    root = tmp_path / "agent-sessions"
    _provision("auto-one", source_repo, root)
    brief = tmp_path / "brief.md"
    brief.write_text("Fix the duplicate habits bug")

    out = _launch("auto-one", root, "--mode=autonomous", f"--prompt-file={brief}").stdout

    assert "-p" in out
    assert "Fix the duplicate habits bug" in out
    assert "--remote-control" not in out


def test_launch_copies_the_brief_into_the_session(source_repo, tmp_path):
    root = tmp_path / "agent-sessions"
    _provision("brief-one", source_repo, root)
    brief = tmp_path / "brief.md"
    brief.write_text("the task")

    _launch("brief-one", root, "--mode=handoff", f"--prompt-file={brief}")

    assert (root / "brief-one" / ".coding-task-prompt.md").read_text() == "the task"


def test_launch_never_puts_a_token_in_argv(source_repo, tmp_path):
    """Anything in argv persists in `docker inspect` and is visible in the
    host process list. `docker compose run` has no --env-file for container
    environment (only -e, which is argv), so the credential arrives through
    the compose service's env_file key instead."""
    root = tmp_path / "agent-sessions"
    _provision("tok", source_repo, root)
    token_file = tmp_path / "token"
    token_file.write_text("ghp_secrettoken123\n")

    result = _launch("tok", root, f"--github-token-file={token_file}")

    assert "ghp_secrettoken123" not in result.stdout
    assert "-e " not in result.stdout


def test_launch_writes_the_credential_to_a_private_env_file(source_repo, tmp_path):
    root = tmp_path / "agent-sessions"
    _provision("tok2", source_repo, root)
    token_file = tmp_path / "token"
    token_file.write_text("ghp_secrettoken123\n")

    result = _launch(
        "tok2", root, f"--github-token-file={token_file}", "--keep-env-file"
    )

    env_path = Path(result.stdout.strip().splitlines()[-1])
    assert env_path.exists()
    assert oct(env_path.stat().st_mode)[-3:] == "600"
    body = env_path.read_text()
    assert "GH_TOKEN=ghp_secrettoken123" in body
    assert "GIT_CONFIG_KEY_0=url.https://x-access-token:ghp_secrettoken123@github.com/.insteadOf" in body
    env_path.unlink()


def test_launch_on_a_missing_session_fails_clearly(tmp_path):
    root = tmp_path / "agent-sessions"
    root.mkdir()

    result = _launch("ghost", root)

    assert result.returncode != 0
    assert "ghost" in (result.stdout + result.stderr)


def test_start_provisions_then_launches(source_repo, tmp_path):
    root = tmp_path / "agent-sessions"
    result = subprocess.run(
        [str(SESSION_SH), "start", "combined",
         f"--repo={source_repo}", f"--root={root}", "--dry-run"],
        capture_output=True, text=True,
    )

    assert result.returncode == 0, result.stderr
    assert (root / "combined" / ".git").is_dir()
    assert "--remote-control" in result.stdout


def test_default_root_is_agent_sessions_not_claude_worktrees(tmp_path):
    """.claude/worktrees/ belongs to Claude Code's native linked worktrees.
    Mixing clones into it made a 91MB clone invisible to every cleanup."""
    import os

    result = subprocess.run(
        [str(SESSION_SH), "list"],
        capture_output=True, text=True,
        env={**os.environ, "HOME": str(tmp_path), "AGENT_SESSIONS_ROOT": ""},
    )

    assert "agent-sessions" in result.stdout
    assert ".claude/worktrees" not in result.stdout


def test_launch_removes_the_credential_env_file_after_running(source_repo, tmp_path):
    """The env file holds the GitHub PAT. A trap that expands $env_file at
    EXIT time reads it after cmd_launch's `local` has gone out of scope,
    leaving the token in TMPDIR after every real launch."""
    import os

    root = tmp_path / "agent-sessions"
    _provision("leak", source_repo, root)
    token_file = tmp_path / "token"
    token_file.write_text("ghp_secrettoken123\n")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "docker").write_text("#!/bin/sh\nexit 0\n")
    (fake_bin / "docker").chmod(0o755)

    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()

    subprocess.run(
        [str(SESSION_SH), "launch", "leak", f"--root={root}",
         f"--github-token-file={token_file}"],
        capture_output=True, text=True,
        env={**os.environ,
             "PATH": f"{fake_bin}:{os.environ['PATH']}",
             "TMPDIR": str(tmpdir)},
    )

    leftovers = list(tmpdir.glob("mazkir-session-*.env"))
    assert leftovers == [], f"credential file left behind: {leftovers}"


def test_detach_runs_the_container_in_the_background(source_repo, tmp_path):
    """`docker compose run` is foreground by default, so a caller that is
    not a human at a terminal blocks for the whole session -- the server
    hung for 130s on a real autonomous launch."""
    root = tmp_path / "agent-sessions"
    _provision("bg", source_repo, root)
    brief = tmp_path / "brief.md"
    brief.write_text("do the thing")

    out = _launch("bg", root, "--mode=autonomous", f"--prompt-file={brief}",
                  "--detach").stdout

    assert " -d " in f" {out} "


def test_detach_names_the_container_predictably(source_repo, tmp_path):
    """The poller looks the container up by name after launch returns."""
    root = tmp_path / "agent-sessions"
    _provision("named", source_repo, root)
    brief = tmp_path / "brief.md"
    brief.write_text("x")

    out = _launch("named", root, "--mode=autonomous", f"--prompt-file={brief}",
                  "--detach").stdout

    assert "--name mazkir-coding-named" in out


def test_detach_keeps_the_container_so_logs_survive_the_exit(source_repo, tmp_path):
    """--rm would delete the container the instant it exits, destroying the
    transcript the poller reads to build its summary."""
    root = tmp_path / "agent-sessions"
    _provision("keep", source_repo, root)
    brief = tmp_path / "brief.md"
    brief.write_text("x")

    out = _launch("keep", root, "--mode=autonomous", f"--prompt-file={brief}",
                  "--detach").stdout

    assert "--rm" not in out


def test_without_detach_the_run_stays_in_the_foreground(source_repo, tmp_path):
    """A human running `session.sh start` wants the TTY."""
    root = tmp_path / "agent-sessions"
    _provision("fg", source_repo, root)

    out = _launch("fg", root).stdout

    assert " -d " not in f" {out} "
    assert "--rm" in out
