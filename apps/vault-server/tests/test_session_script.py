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
