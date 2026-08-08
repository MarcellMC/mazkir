# Devcontainer Foundation (session.sh) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `session.sh` — one script that provisions, launches, lists, and cleans containerized coding sessions — so manual devcontainer sessions work correctly on their own, before Mazkir is wired to it.

**Architecture:** A single bash entry point owns clone provisioning (with a GitHub remote, not the local path it currently inherits), session `.env` generation for container paths, three launch modes, and a four-predicate cleanup gate. The devcontainer image gains a Python toolchain so the backend is runnable inside a session without per-session bootstrap. Everything is driven by pytest against throwaway git repos, plus one opt-in smoke test that boots a real container.

**Tech Stack:** bash, Docker + docker compose, pytest (via `apps/vault-server/venv`), git.

**Spec:** `docs/superpowers/specs/2026-08-08-agent-sessions-design.md`

## Global Constraints

- Session worktree root is `~/dev/agent-sessions/<name>/`. Never `.claude/worktrees/` — that belongs to Claude Code's native linked worktrees.
- Branch naming is `coding-agent/<name>` in both repos.
- **No time-based deletion, ever.** Removal requires all four predicates in Task 6 or an explicit `--force`.
- Secrets never appear in `docker run` argv. Use `--env-file` with mode 0600, unlinked after Docker reads it.
- No `/var/run/docker.sock` mount under any circumstance.
- Clones, never `git worktree add`: a linked worktree's `.git` is a pointer to an absolute host path that does not resolve inside a container.
- Container home is `/home/marcellmc`, workspace is `/workspace`, vault is `/workspace/memory`.
- Tests run with `cd apps/vault-server && source venv/bin/activate`.

---

### Task 1: Add a Python toolchain to the devcontainer image

The image is `node:22-slim` with no Python at all, while the primary backend is Python. Sessions currently download `uv` and build a venv themselves.

**Files:**
- Create: `infra/coding-agent/smoke-test.sh`
- Modify: `infra/coding-agent/Dockerfile`

**Interfaces:**
- Produces: `smoke-test.sh`, a shell script that boots the real image and asserts capabilities. Later tasks append assertions to it.

- [ ] **Step 1: Write the failing assertion**

Create `infra/coding-agent/smoke-test.sh`:

```bash
#!/usr/bin/env bash
# infra/coding-agent/smoke-test.sh
#
# Opt-in smoke test: boots the real devcontainer image and asserts the
# things unit tests cannot. Requires Docker and network. Not part of
# `turbo test` -- run before merging any container change.
set -uo pipefail

IMAGE="${IMAGE:-mazkir-coding-agent:latest}"
failures=0

check() {
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then
    echo "  PASS  $name"
  else
    echo "  FAIL  $name"
    failures=$((failures + 1))
  fi
}

echo "== image capabilities =="
check "python3 present"  docker run --rm "$IMAGE" python3 --version
check "uv present"       docker run --rm "$IMAGE" uv --version
check "node present"     docker run --rm "$IMAGE" node --version
check "git present"      docker run --rm "$IMAGE" git --version
check "gh present"       docker run --rm "$IMAGE" gh --version
check "claude present"   docker run --rm "$IMAGE" claude --version

echo
if [ "$failures" -ne 0 ]; then
  echo "SMOKE TEST FAILED: $failures check(s) failed"
  exit 1
fi
echo "SMOKE TEST PASSED"
```

- [ ] **Step 2: Run it to verify Python checks fail**

```bash
chmod +x infra/coding-agent/smoke-test.sh
./infra/coding-agent/smoke-test.sh
```

Expected: `FAIL python3 present` and `FAIL uv present`; node/git/gh/claude PASS. Exit code 1.

- [ ] **Step 3: Add the toolchain to the Dockerfile**

In `infra/coding-agent/Dockerfile`, add `python3`, `python3-venv`, and `python3-dev` to the existing first `apt-get install` list (alongside `git`, `curl`, `tmux`, …), then add this block immediately after the `npm install -g @anthropic-ai/claude-code` line:

```dockerfile
# uv: the project's Python apps are installed with it, and a session that
# has to bootstrap its own interpreter wastes minutes and leaves a broken
# venv behind. Installed to /usr/local/bin so it is on PATH for every user.
RUN curl -fsSL https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
```

- [ ] **Step 4: Rebuild and re-run the smoke test**

```bash
docker build -t mazkir-coding-agent:latest infra/coding-agent/
./infra/coding-agent/smoke-test.sh
```

Expected: all six checks PASS, `SMOKE TEST PASSED`, exit 0.

- [ ] **Step 5: Commit**

```bash
git add infra/coding-agent/Dockerfile infra/coding-agent/smoke-test.sh
git commit -m "feat(coding-agent): add Python toolchain and a real-container smoke test

The image is node:22-slim with no Python, while the primary backend is
Python -- sessions were downloading uv and building a venv themselves,
then leaving a broken one behind. Adds python3 + uv, and a smoke test
that asserts image capabilities against a real container, which is the
class of defect the mocked suite cannot catch."
```

---

### Task 2: Provision a clone with a GitHub remote

A clone currently inherits the *local path* as `origin`, so `git push` writes into the user's own checkout, the `GIT_CONFIG` insteadOf rewrite never fires, and `gh pr create` has no GitHub remote. This is the blocker for the push+PR definition of done.

**Files:**
- Create: `infra/coding-agent/session.sh`
- Create: `apps/vault-server/tests/test_session_script.py`

**Interfaces:**
- Produces: `session.sh provision <name> --repo=<path> --root=<path>` — clones, rewrites origin to the source repo's GitHub URL, creates branch `coding-agent/<name>`. Exits non-zero with a message on failure.

- [ ] **Step 1: Write the failing test**

Create `apps/vault-server/tests/test_session_script.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd apps/vault-server && source venv/bin/activate
python -m pytest tests/test_session_script.py -v
```

Expected: all four FAIL — `session.sh` does not exist yet.

- [ ] **Step 3: Write session.sh with the provision subcommand**

Create `infra/coding-agent/session.sh`:

```bash
#!/usr/bin/env bash
# infra/coding-agent/session.sh
#
# Single entry point for containerized coding sessions: provision, launch,
# list, clean. Mazkir's vault-server shells out to this rather than
# building its own `docker run` arguments, so the automated and manual
# paths cannot drift -- they did before, and the divergence broke every
# automated session (see docs/superpowers/specs/2026-08-08-agent-sessions-design.md §11.1).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_ROOT="${AGENT_SESSIONS_ROOT:-$HOME/dev/agent-sessions}"
DEFAULT_REPO="${MAZKIR_REPO_PATH:-$HOME/dev/mazkir}"

die() { echo "session.sh: $*" >&2; exit 1; }

# Read the source repo's GitHub URL. A clone would otherwise inherit the
# local filesystem path as origin: `git push` would write into the user's
# own checkout, the GIT_CONFIG insteadOf rewrite (which only matches
# git@github.com: URLs) would never fire, and `gh pr create` would have no
# GitHub remote to target.
source_remote_url() {
  local repo="$1" url
  url="$(git -C "$repo" remote get-url origin 2>/dev/null || true)"
  [ -n "$url" ] || die "source repo $repo has no origin remote"
  case "$url" in
    /*|.*|"") die "source repo origin is not a remote URL: $url" ;;
    *://*|*@*:*) ;;
    *) die "source repo origin is not a remote URL: $url" ;;
  esac
  printf '%s' "$url"
}

# Clone + rewrite origin + branch. Idempotent: an existing directory is
# reused untouched, since it may hold unpushed work that exists nowhere
# else (a clone is its own object database).
provision_clone() {
  local repo="$1" dest="$2" branch="$3" url
  if [ -d "$dest" ]; then
    echo "session.sh: reusing existing clone at $dest"
    return 0
  fi
  url="$(source_remote_url "$repo")"
  git clone --quiet "$repo" "$dest"
  git -C "$dest" remote set-url origin "$url"
  git -C "$dest" checkout --quiet -b "$branch"
}

cmd_provision() {
  local name="" repo="$DEFAULT_REPO" root="$DEFAULT_ROOT"
  name="$1"; shift
  [ -n "$name" ] || die "usage: session.sh provision <name> [--repo=PATH] [--root=PATH]"
  for arg in "$@"; do
    case "$arg" in
      --repo=*) repo="${arg#--repo=}" ;;
      --root=*) root="${arg#--root=}" ;;
      *) die "unknown option: $arg" ;;
    esac
  done

  mkdir -p "$root"
  provision_clone "$repo" "$root/$name" "coding-agent/$name"
  echo "$root/$name"
}

main() {
  [ "$#" -ge 1 ] || die "usage: session.sh <provision|launch|list|clean> ..."
  local cmd="$1"; shift
  case "$cmd" in
    provision) cmd_provision "$@" ;;
    *) die "unknown command: $cmd" ;;
  esac
}

main "$@"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
chmod +x infra/coding-agent/session.sh
cd apps/vault-server && source venv/bin/activate
python -m pytest tests/test_session_script.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add infra/coding-agent/session.sh apps/vault-server/tests/test_session_script.py
git commit -m "feat(coding-agent): add session.sh provisioning with a GitHub origin

A clone inherits the local filesystem path as origin, so git push wrote
into the user's own checkout, the GIT_CONFIG insteadOf rewrite never
fired, and gh pr create had no GitHub remote. Provisioning now rewrites
origin to the source repo's GitHub URL and refuses outright when that
URL is itself a local path, rather than silently producing a clone that
can never push."
```

---

### Task 3: Provision the nested vault clone

Mazkir spans two repos. The vault clone is nested at `<session>/memory` to mirror the host layout, and is an independent clone of `mazkir-memory` with its own push state.

**Files:**
- Modify: `infra/coding-agent/session.sh`
- Modify: `apps/vault-server/tests/test_session_script.py`

**Interfaces:**
- Consumes: `provision_clone()` from Task 2.
- Produces: `session.sh provision <name> --vault-repo=<path>` — additionally clones the vault to `<session>/memory`.

- [ ] **Step 1: Write the failing test**

Append to `apps/vault-server/tests/test_session_script.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd apps/vault-server && source venv/bin/activate
python -m pytest tests/test_session_script.py -k vault -v
```

Expected: `test_provision_nests_an_independent_vault_clone` FAILS (unknown option `--vault-repo`), `test_provision_rolls_back...` FAILS.

- [ ] **Step 3: Add vault provisioning with rollback**

In `session.sh`, replace `cmd_provision` with:

```bash
cmd_provision() {
  local name="" repo="$DEFAULT_REPO" root="$DEFAULT_ROOT" vault_repo=""
  name="$1"; shift
  [ -n "$name" ] || die "usage: session.sh provision <name> [--repo=PATH] [--root=PATH] [--vault-repo=PATH]"
  for arg in "$@"; do
    case "$arg" in
      --repo=*) repo="${arg#--repo=}" ;;
      --root=*) root="${arg#--root=}" ;;
      --vault-repo=*) vault_repo="${arg#--vault-repo=}" ;;
      *) die "unknown option: $arg" ;;
    esac
  done

  local dest="$root/$name" branch="coding-agent/$name"
  mkdir -p "$root"
  provision_clone "$repo" "$dest" "$branch"

  if [ -n "$vault_repo" ]; then
    # Roll the mazkir clone back if the vault clone fails. An orphan would
    # be reused as-is by the idempotent branch above, silently handing a
    # stale clone to the next attempt at the same name.
    if ! provision_clone "$vault_repo" "$dest/memory" "$branch"; then
      rm -rf "$dest"
      die "vault clone failed; rolled back $dest"
    fi
  fi
  echo "$dest"
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd apps/vault-server && source venv/bin/activate
python -m pytest tests/test_session_script.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add infra/coding-agent/session.sh apps/vault-server/tests/test_session_script.py
git commit -m "feat(coding-agent): provision the nested vault clone with rollback

The vault is an independent clone of mazkir-memory nested at
<session>/memory, with its own origin and push state. A vault-clone
failure now rolls back the mazkir clone, since provisioning reuses an
existing directory as-is and an orphan would be handed to the next retry
as a stale clone."
```

---

### Task 4: Generate the session `.env` with container paths

Nine `config.py` defaults hardcode `Path.home() / "dev" / "mazkir"`, none of which resolve inside a container where the repo is at `/workspace`. This caused a real session to misreport five test failures as unrelated environment issues.

**Files:**
- Modify: `infra/coding-agent/session.sh`
- Modify: `apps/vault-server/tests/test_session_script.py`

**Interfaces:**
- Produces: `<session>/apps/vault-server/.env` containing `.env.example` plus container-path overrides.

- [ ] **Step 1: Write the failing test**

Append to `apps/vault-server/tests/test_session_script.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd apps/vault-server && source venv/bin/activate
python -m pytest tests/test_session_script.py -k env -v
```

Expected: `test_provision_writes_a_session_env_with_container_paths` FAILS — the `.env` file does not exist.

- [ ] **Step 3: Generate the session .env**

Add to `session.sh`, above `cmd_provision`:

```bash
# config.py's defaults resolve under $HOME/dev/mazkir, which does not exist
# in a container where the repo is mounted at /workspace. Copy the tracked
# .env.example and append container-correct overrides for every path
# setting, so tests and the server run inside a session without manual
# fixing. Secrets are deliberately not copied -- they arrive via
# --env-file at launch.
write_session_env() {
  local dest="$1"
  local example="$dest/apps/vault-server/.env.example"
  local target="$dest/apps/vault-server/.env"
  [ -f "$example" ] || return 0

  cp "$example" "$target"
  cat >> "$target" <<'ENV'

# --- appended by session.sh: container paths (override .env.example) ---
VAULT_PATH=/workspace/memory
MAZKIR_SKILLS_DIR=/workspace/memory/00-system/skills
MEDIA_PATH=/workspace/memory/00-system/media
TIMELINE_DATA_PATH=/workspace/data/timeline
EVENTS_DATA_PATH=/workspace/data/events
LOGS_DIR=/workspace/data/logs
CODING_TASKS_DATA_PATH=/workspace/data/coding-tasks
CODING_AGENT_WORKTREES_PATH=/workspace/.agent-sessions
MAZKIR_REPO_PATH=/workspace
MAZKIR_VAULT_REPO_PATH=/workspace/memory
ENV
}
```

Then call it in `cmd_provision`, immediately before the final `echo "$dest"`:

```bash
  write_session_env "$dest"
  echo "$dest"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd apps/vault-server && source venv/bin/activate
python -m pytest tests/test_session_script.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add infra/coding-agent/session.sh apps/vault-server/tests/test_session_script.py
git commit -m "feat(coding-agent): generate a session .env with container paths

Nine config.py defaults resolve under ~/dev/mazkir, which does not exist
in a container where the repo is at /workspace. A real session reported
the resulting five test failures as unrelated environment issues.
Provisioning now writes .env from the tracked .env.example plus
container-correct overrides. Secrets are not copied; they arrive via
--env-file at launch."
```

---

### Task 5: `session.sh list` — show every session and its predicates

**Files:**
- Modify: `infra/coding-agent/session.sh`
- Modify: `apps/vault-server/tests/test_session_script.py`

**Interfaces:**
- Produces: `session.sh list [--root=PATH]` printing one line per session: name, branch, and `SAFE` or `KEEP: <reason>`.
- Produces: `session_status <path>` — the shared predicate evaluator, reused by Task 6.

- [ ] **Step 1: Write the failing test**

Append to `apps/vault-server/tests/test_session_script.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd apps/vault-server && source venv/bin/activate
python -m pytest tests/test_session_script.py -k list -v
```

Expected: all five FAIL — `unknown command: list`.

- [ ] **Step 3: Implement the predicate evaluator and list**

Add to `session.sh`, above `main()`:

```bash
# The retention predicates. A worktree is removable only when a repo holds
# nothing that exists nowhere else. Deliberately conservative: a clone with
# no upstream is kept even when it demonstrably holds no work, because the
# cost of a false positive is destroying commits that exist in exactly one
# place. There is no time-based deletion.
#
# Echoes "" when safe, or a human-readable reason to keep.
repo_keep_reason() {
  local repo="$1" label="$2"
  [ -d "$repo/.git" ] || return 0
  if [ -n "$(git -C "$repo" status --porcelain 2>/dev/null | grep -v '^?? \.coding-task-prompt\.md$' || true)" ]; then
    printf '%s has uncommitted changes' "$label"; return 0
  fi
  if ! git -C "$repo" rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
    printf '%s has no upstream' "$label"; return 0
  fi
  if [ -n "$(git -C "$repo" log --oneline '@{u}..HEAD' 2>/dev/null || true)" ]; then
    printf '%s has unpushed commits' "$label"; return 0
  fi
  printf ''
}

# Evaluate both repos. Echoes "" when the whole session is safe to remove.
session_keep_reason() {
  local session="$1" reason
  reason="$(repo_keep_reason "$session" "workspace")"
  [ -z "$reason" ] || { printf '%s' "$reason"; return 0; }
  if [ -d "$session/memory/.git" ]; then
    reason="$(repo_keep_reason "$session/memory" "memory")"
    [ -z "$reason" ] || { printf '%s' "$reason"; return 0; }
  fi
  printf ''
}

cmd_list() {
  local root="$DEFAULT_ROOT"
  for arg in "$@"; do
    case "$arg" in
      --root=*) root="${arg#--root=}" ;;
      *) die "unknown option: $arg" ;;
    esac
  done

  local found=0
  for session in "$root"/*/; do
    [ -d "$session" ] || continue
    found=1
    local name branch reason
    name="$(basename "$session")"
    branch="$(git -C "$session" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
    reason="$(session_keep_reason "${session%/}")"
    if [ -z "$reason" ]; then
      printf '%-28s %-32s SAFE\n' "$name" "$branch"
    else
      printf '%-28s %-32s KEEP: %s\n' "$name" "$branch" "$reason"
    fi
  done
  [ "$found" -eq 1 ] || echo "no sessions in $root"
}
```

Register it in `main()`:

```bash
    provision) cmd_provision "$@" ;;
    list) cmd_list "$@" ;;
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd apps/vault-server && source venv/bin/activate
python -m pytest tests/test_session_script.py -v
```

Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git add infra/coding-agent/session.sh apps/vault-server/tests/test_session_script.py
git commit -m "feat(coding-agent): add session.sh list with retention predicates

Evaluates the four predicates against both the workspace and the nested
vault clone, which have independent push states, and reports SAFE or the
specific reason to keep. No time-based deletion: a clone with no upstream
is kept even when it holds no work, because destroying commits that exist
in exactly one place is not worth the disk it saves."
```

---

### Task 6: `session.sh clean` — remove only what is safe

**Files:**
- Modify: `infra/coding-agent/session.sh`
- Modify: `apps/vault-server/tests/test_session_script.py`

**Interfaces:**
- Consumes: `session_keep_reason()` from Task 5.
- Produces: `session.sh clean <name> [--root=PATH] [--force]` — exit 0 and remove on safe, exit non-zero and keep otherwise.

- [ ] **Step 1: Write the failing test**

Append to `apps/vault-server/tests/test_session_script.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd apps/vault-server && source venv/bin/activate
python -m pytest tests/test_session_script.py -k clean -v
```

Expected: all five FAIL — `unknown command: clean`.

- [ ] **Step 3: Implement clean**

Add to `session.sh`, above `main()`:

```bash
cmd_clean() {
  local name="" root="$DEFAULT_ROOT" force=0
  name="$1"; shift
  [ -n "$name" ] || die "usage: session.sh clean <name> [--root=PATH] [--force]"
  for arg in "$@"; do
    case "$arg" in
      --root=*) root="${arg#--root=}" ;;
      --force) force=1 ;;
      *) die "unknown option: $arg" ;;
    esac
  done

  local session="$root/$name"
  [ -d "$session" ] || die "no such session: $name (looked in $root)"

  if [ "$force" -eq 0 ]; then
    local reason
    reason="$(session_keep_reason "$session")"
    [ -z "$reason" ] || die "refusing to remove $name: $reason (use --force to override)"
  fi

  rm -rf "$session"
  echo "removed $session"
}
```

Register it in `main()`:

```bash
    list) cmd_list "$@" ;;
    clean) cmd_clean "$@" ;;
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd apps/vault-server && source venv/bin/activate
python -m pytest tests/test_session_script.py -v
```

Expected: 19 passed.

- [ ] **Step 5: Commit**

```bash
git add infra/coding-agent/session.sh apps/vault-server/tests/test_session_script.py
git commit -m "feat(coding-agent): add session.sh clean gated on the predicates

Removes a session only when both repos hold nothing that exists nowhere
else, naming the failing predicate when it refuses. --force overrides.
Nothing is ever removed on a timer."
```

---

### Task 7: Launch the three modes through docker compose

**Files:**
- Modify: `infra/coding-agent/docker-compose.yml`
- Modify: `infra/coding-agent/session.sh`
- Modify: `apps/vault-server/tests/test_session_script.py`

**Interfaces:**
- Produces: `session.sh launch <name> [--mode=manual|handoff|autonomous] [--prompt-file=PATH] [--root=PATH] [--dry-run]`. `--dry-run` prints the resolved `docker compose` argv without executing, which is what the tests assert against.

- [ ] **Step 1: Write the failing test**

Append to `apps/vault-server/tests/test_session_script.py`:

```python
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
    host process list."""
    root = tmp_path / "agent-sessions"
    _provision("tok", source_repo, root)
    token_file = tmp_path / "token"
    token_file.write_text("ghp_secrettoken123\n")

    out = _launch("tok", root, f"--github-token-file={token_file}").stdout

    assert "ghp_secrettoken123" not in out
    assert "--env-file" in out


def test_launch_on_a_missing_session_fails_clearly(tmp_path):
    root = tmp_path / "agent-sessions"
    root.mkdir()

    result = _launch("ghost", root)

    assert result.returncode != 0
    assert "ghost" in (result.stdout + result.stderr)
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd apps/vault-server && source venv/bin/activate
python -m pytest tests/test_session_script.py -k "mode or launch" -v
```

Expected: all six FAIL — `unknown command: launch`.

- [ ] **Step 3: Parameterize compose and implement launch**

Replace `infra/coding-agent/docker-compose.yml` with:

```yaml
# infra/coding-agent/docker-compose.yml
#
# THE container definition. Both session.sh (manual/hand-off) and
# vault-server's spawn_container go through this, so the automated and
# manual paths cannot drift -- they did before, and the .claude.json mount
# existed here but not in spawn_container, which broke every automated
# session. Invoke via session.sh, which resolves every variable below
# (compose does no shell-style ~ expansion).
services:
  devcontainer:
    image: mazkir-coding-agent:latest
    build: .
    working_dir: /workspace
    stdin_open: true
    tty: true
    volumes:
      - mazkir-claude-auth:/home/marcellmc/.claude
      - ${CLAUDE_JSON_PATH}:/home/marcellmc/.claude.json
      - ${CLAUDE_PLUGINS_PATH}:/home/marcellmc/.claude/plugins
      - ${DOTFILES_PATH}:/home/marcellmc/dotfiles:ro
      - ${WORKTREE_PATH}:/workspace

volumes:
  mazkir-claude-auth:
    external: true
```

Add to `session.sh`, above `main()`:

```bash
# Scope a GitHub credential to this one container via a mode-0600 file.
# Never -e flags: argv is copied into container metadata, where `docker
# inspect` echoes it back for as long as the container exists, and is
# visible in the host process list while docker run executes.
# GIT_CONFIG_* drives an insteadOf rewrite so `git push` authenticates;
# GH_TOKEN authenticates `gh` itself for `gh pr create`, which the session
# needs because master takes PRs only.
write_credential_env_file() {
  local token_file="$1" out token
  [ -n "$token_file" ] && [ -f "$token_file" ] || return 0
  token="$(tr -d '[:space:]' < "$token_file")"
  [ -n "$token" ] || return 0
  out="$(mktemp -t mazkir-session-XXXXXX.env)"
  chmod 600 "$out"
  {
    echo "GIT_CONFIG_COUNT=1"
    echo "GIT_CONFIG_KEY_0=url.https://x-access-token:${token}@github.com/.insteadOf"
    echo "GIT_CONFIG_VALUE_0=git@github.com:"
    echo "GH_TOKEN=${token}"
  } > "$out"
  printf '%s' "$out"
}

cmd_launch() {
  local name="" root="$DEFAULT_ROOT" mode="manual" prompt_file="" dry_run=0
  local token_file="${CODING_AGENT_GITHUB_TOKEN_PATH:-}"
  name="$1"; shift
  [ -n "$name" ] || die "usage: session.sh launch <name> [--mode=MODE] [--prompt-file=PATH]"
  for arg in "$@"; do
    case "$arg" in
      --root=*) root="${arg#--root=}" ;;
      --mode=*) mode="${arg#--mode=}" ;;
      --prompt-file=*) prompt_file="${arg#--prompt-file=}" ;;
      --github-token-file=*) token_file="${arg#--github-token-file=}" ;;
      --dry-run) dry_run=1 ;;
      *) die "unknown option: $arg" ;;
    esac
  done

  local session="$root/$name"
  [ -d "$session" ] || die "no such session: $name (looked in $root)"

  local brief=""
  if [ -n "$prompt_file" ]; then
    [ -f "$prompt_file" ] || die "no such prompt file: $prompt_file"
    brief="$(cat "$prompt_file")"
    # Kept on disk so a human taking the session over can read the task.
    cp "$prompt_file" "$session/.coding-task-prompt.md"
  fi

  # `claude -p` takes prompt TEXT; handing it a path makes the path the
  # entire prompt. --remote-control starts an interactive session, which is
  # the only kind Remote Control can attach to.
  local claude_args=(claude --dangerously-skip-permissions)
  case "$mode" in
    autonomous)
      [ -n "$brief" ] || die "autonomous mode requires --prompt-file"
      claude_args+=(-p "$brief")
      ;;
    handoff)
      [ -n "$brief" ] || die "handoff mode requires --prompt-file"
      claude_args+=(--remote-control "$name" "$brief")
      ;;
    manual)
      claude_args+=(--remote-control "$name")
      ;;
    *) die "unknown mode: $mode (expected autonomous, handoff, or manual)" ;;
  esac

  export WORKTREE_PATH="$session"
  export CLAUDE_JSON_PATH="${CLAUDE_JSON_PATH:-$HOME/.config/mazkir/coding-agent-claude-home.json}"
  export CLAUDE_PLUGINS_PATH="${CLAUDE_PLUGINS_PATH:-$HOME/.claude/plugins}"
  export DOTFILES_PATH="${DOTFILES_PATH:-$HOME/dotfiles}"

  local env_file compose_args
  env_file="$(write_credential_env_file "$token_file")"
  compose_args=(docker compose -f "$SCRIPT_DIR/docker-compose.yml" run --rm)
  [ -n "$env_file" ] && compose_args+=(--env-file "$env_file")
  compose_args+=(devcontainer "${claude_args[@]}")

  if [ "$dry_run" -eq 1 ]; then
    printf '%s\n' "${compose_args[*]}"
    [ -n "$env_file" ] && rm -f "$env_file"
    return 0
  fi

  trap '[ -n "${env_file:-}" ] && rm -f "$env_file"' EXIT
  "${compose_args[@]}"
}
```

Register it in `main()`:

```bash
    clean) cmd_clean "$@" ;;
    launch) cmd_launch "$@" ;;
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd apps/vault-server && source venv/bin/activate
python -m pytest tests/test_session_script.py -v
```

Expected: 25 passed.

- [ ] **Step 5: Commit**

```bash
git add infra/coding-agent/session.sh infra/coding-agent/docker-compose.yml apps/vault-server/tests/test_session_script.py
git commit -m "feat(coding-agent): launch autonomous, hand-off, and manual modes

All three go through one compose definition. Hand-off and manual use
--remote-control, which starts an interactive session and is the only
kind Remote Control can attach to; autonomous keeps -p. The brief is
passed as prompt text, never as a path, and the GitHub credential goes
through a mode-0600 env-file so it never reaches docker argv."
```

---

### Task 8: Retire `devcontainer.sh` and move the worktree root

`devcontainer.sh` writes clones into `.claude/worktrees/`, the directory Claude Code uses for its own linked worktrees. The clone is invisible to `git worktree list` and to every cleanup path.

**Files:**
- Delete: `infra/coding-agent/devcontainer.sh`
- Modify: `infra/coding-agent/session.sh`
- Modify: `apps/vault-server/tests/test_session_script.py`

**Interfaces:**
- Produces: `session.sh start <name> [options]` — provision then launch, the one command a human runs.

- [ ] **Step 1: Write the failing test**

Append to `apps/vault-server/tests/test_session_script.py`:

```python
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


def test_default_root_is_agent_sessions_not_claude_worktrees(tmp_path, monkeypatch):
    """.claude/worktrees/ belongs to Claude Code's native linked worktrees.
    Mixing clones into it made a 91MB clone invisible to every cleanup."""
    result = subprocess.run(
        [str(SESSION_SH), "list"],
        capture_output=True, text=True, env={**__import__("os").environ, "HOME": str(tmp_path)},
    )

    assert "agent-sessions" in result.stdout
    assert ".claude/worktrees" not in result.stdout
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd apps/vault-server && source venv/bin/activate
python -m pytest tests/test_session_script.py -k "start or default_root" -v
```

Expected: `test_start_provisions_then_launches` FAILS (`unknown command: start`).

- [ ] **Step 3: Add the start subcommand and delete devcontainer.sh**

Add to `session.sh`, above `main()`:

```bash
# The one command a human runs: provision if needed, then launch.
cmd_start() {
  local name="$1"; shift
  [ -n "$name" ] || die "usage: session.sh start <name> [options]"

  local provision_args=() launch_args=()
  for arg in "$@"; do
    case "$arg" in
      --repo=*|--vault-repo=*) provision_args+=("$arg") ;;
      --root=*) provision_args+=("$arg"); launch_args+=("$arg") ;;
      *) launch_args+=("$arg") ;;
    esac
  done

  cmd_provision "$name" "${provision_args[@]+"${provision_args[@]}"}" >/dev/null
  cmd_launch "$name" "${launch_args[@]+"${launch_args[@]}"}"
}
```

Register it in `main()` and add usage text:

```bash
    launch) cmd_launch "$@" ;;
    start) cmd_start "$@" ;;
    -h|--help|help) usage ;;
```

Add a `usage()` function above `main()`:

```bash
usage() {
  cat <<'USAGE'
session.sh -- containerized coding sessions

  session.sh start <name> [--mode=manual|handoff|autonomous] [--prompt-file=PATH]
      Provision (if needed) and launch. The command you normally want.
      manual      interactive Remote Control session, no seed prompt
      handoff     interactive Remote Control session seeded with a brief
      autonomous  headless `claude -p`; exits when done

  session.sh provision <name> [--repo=PATH] [--vault-repo=PATH] [--root=PATH]
  session.sh launch <name> [--mode=MODE] [--prompt-file=PATH] [--dry-run]
  session.sh list [--root=PATH]
      One line per session: name, branch, and SAFE or KEEP: <reason>.
  session.sh clean <name> [--root=PATH] [--force]
      Remove a session only if nothing in it exists nowhere else.

Sessions live in $HOME/dev/agent-sessions by default (AGENT_SESSIONS_ROOT).
USAGE
  exit 0
}
```

Then remove the superseded script:

```bash
git rm infra/coding-agent/devcontainer.sh
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd apps/vault-server && source venv/bin/activate
python -m pytest tests/test_session_script.py -v
```

Expected: 27 passed.

- [ ] **Step 5: Commit**

```bash
git add infra/coding-agent/session.sh apps/vault-server/tests/test_session_script.py
git commit -m "feat(coding-agent): replace devcontainer.sh with session.sh start

devcontainer.sh wrote full clones into .claude/worktrees/, the directory
Claude Code uses for its own linked worktrees -- invisible to git
worktree list and to every cleanup path, which is how a 91MB abandoned
clone went unnoticed. Sessions now live in ~/dev/agent-sessions."
```

---

### Task 9: Extend the smoke test to cover provisioning and push

Every defect that reached the user this week would have been caught here; none were caught by the mocked suite.

**Files:**
- Modify: `infra/coding-agent/smoke-test.sh`

- [ ] **Step 1: Add the session-level assertions**

Append to `infra/coding-agent/smoke-test.sh`, before the final `if [ "$failures" -ne 0 ]` block:

```bash
echo
echo "== session provisioning =="
SMOKE_ROOT="$(mktemp -d)"
SMOKE_NAME="smoke-$$"
cleanup_smoke() {
  "$SCRIPT_DIR/session.sh" clean "$SMOKE_NAME" --root="$SMOKE_ROOT" --force >/dev/null 2>&1 || true
  rm -rf "$SMOKE_ROOT"
}
trap cleanup_smoke EXIT
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"$SCRIPT_DIR/session.sh" provision "$SMOKE_NAME" --root="$SMOKE_ROOT" >/dev/null

check "clone has a GitHub origin" bash -c \
  "git -C '$SMOKE_ROOT/$SMOKE_NAME' remote get-url origin | grep -q github.com"
check "session .env has container paths" bash -c \
  "grep -q '^VAULT_PATH=/workspace/memory$' '$SMOKE_ROOT/$SMOKE_NAME/apps/vault-server/.env'"

echo
echo "== container boots against a real session =="
check "agent answers in the session" bash -c \
  "'$SCRIPT_DIR/session.sh' launch '$SMOKE_NAME' --root='$SMOKE_ROOT' --mode=autonomous \
     --prompt-file=<(echo 'Reply with exactly: BOOT OK') 2>&1 | grep -q 'BOOT OK'"
check "CLAUDE.md is autoloaded" bash -c \
  "'$SCRIPT_DIR/session.sh' launch '$SMOKE_NAME' --root='$SMOKE_ROOT' --mode=autonomous \
     --prompt-file=<(echo 'Without reading any files, what port does vault-server run on?') 2>&1 | grep -q '8000'"
```

Move the `SCRIPT_DIR` assignment to the top of the file, immediately after `set -uo pipefail`, so it is defined before first use.

- [ ] **Step 2: Run the smoke test**

```bash
./infra/coding-agent/smoke-test.sh
```

Expected: all checks PASS, `SMOKE TEST PASSED`. If `clone has a GitHub origin` fails, Task 2's remote rewrite regressed. If `agent answers` fails, the container is not booting — check `~/.claude.json` is mounted.

- [ ] **Step 3: Commit**

```bash
git add infra/coding-agent/smoke-test.sh
git commit -m "test(coding-agent): smoke-test provisioning and real container boot

The branch shipped 541 passing tests and still broke on first real use,
because no test ever started a container. These assertions cover exactly
that gap: GitHub origin, container paths in .env, a booting agent, and
CLAUDE.md autoloading."
```

---

### Task 10: Documentation

**Files:**
- Modify: `infra/coding-agent/SETUP.md`
- Modify: `infra/coding-agent/CONVENTIONS.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update SETUP.md**

Replace every `./devcontainer.sh <task-name>` reference with `./session.sh start <name>`. Add a section after step 4:

```markdown
## 5. Running sessions

    ./infra/coding-agent/session.sh start my-task            # interactive, Remote Control
    ./infra/coding-agent/session.sh list                     # what exists, and what is safe to remove
    ./infra/coding-agent/session.sh clean my-task            # remove, if nothing is unpushed

Sessions live in `~/dev/agent-sessions/` (override with `AGENT_SESSIONS_ROOT`).
They are deliberately **not** in `.claude/worktrees/`, which belongs to
Claude Code's own linked worktrees — mixing clones into it makes them
invisible to `git worktree list` and to every cleanup path.

Interactive sessions appear in Claude Mobile under the name you passed.
There is no session URL to copy; find them by name.

After changing anything in `infra/coding-agent/`, run:

    ./infra/coding-agent/smoke-test.sh

It boots a real container. The mocked test suite cannot catch image,
mount, or provisioning defects — every one that has reached production
was found this way.
```

- [ ] **Step 2: Make CONVENTIONS.md reachable**

Add to the top of `infra/coding-agent/CONVENTIONS.md`, immediately under the title:

```markdown
> If you are an agent working inside a session, read this file **before**
> doing anything. `CLAUDE.md` links here; the task brief points here.
> The rules below exist because each was violated once, expensively.
```

Update the "Landing changes" section to state the autonomous definition of done:

```markdown
For an autonomous session, "done" means: commit, `git push -u origin
<branch>` (upstream is mandatory — it is what lets the host reclaim the
worktree), and `gh pr create`. Work that is committed but never pushed
exists only in this clone, and this clone is disposable.
```

- [ ] **Step 3: Update CLAUDE.md**

Add to the "Related Documentation" list:

```markdown
- **Coding Session Conventions:** `infra/coding-agent/CONVENTIONS.md` — rules for agents working inside a containerized session (two repos, isolated clone, landing changes)
- **Agent Sessions Design:** `docs/superpowers/specs/2026-08-08-agent-sessions-design.md`
```

Add a new top-level section before "Related Documentation":

```markdown
## Ending a Coding Session

If you are running inside a containerized session (`/workspace` is a clone,
not the real checkout), finish like this:

1. Commit everything.
2. `git push -u origin <branch>` — upstream is mandatory. Do this separately
   for `/workspace` and `/workspace/memory` if you touched both; they are
   different repos with independent push states.
3. Open a PR if the work is meant to land. `master` takes PRs only.
4. Confirm `git status` is clean and nothing is unpushed, and say so in your
   final message.

You cannot delete your own worktree — `/workspace` is a bind mount and your
working directory is inside it. Step 4 is what allows the host to reclaim it
via `session.sh clean`.
```

- [ ] **Step 4: Verify the docs are accurate**

```bash
grep -rn "devcontainer.sh" infra/ docs/ CLAUDE.md || echo "no stale references"
./infra/coding-agent/session.sh --help
```

Expected: no stale `devcontainer.sh` references; help text lists `start`, `provision`, `launch`, `list`, `clean`.

- [ ] **Step 5: Commit**

```bash
git add infra/coding-agent/SETUP.md infra/coding-agent/CONVENTIONS.md CLAUDE.md
git commit -m "docs: document session.sh and make CONVENTIONS.md reachable

CONVENTIONS.md was present in every clone but nothing autoloaded it and
CLAUDE.md never referenced it, so the two-repo warning and the
absolute-host-path rule were never read by the agents they were written
for. CLAUDE.md now links to it and gains an 'ending a session' section
stating the push-with-upstream requirement that cleanup depends on."
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §3 two lanes / §3.1 hand-off variants | 7 (`--mode`) |
| §4 components, `session.sh` single entry point | 2, 5, 6, 7, 8 |
| §5 naming (`<name>` in three places) | 2, 7 |
| §6 provisioning, GitHub origin, root outside repo | 2, 3, 8 |
| §7 four predicates, no time-based deletion | 5, 6 |
| §7.1 ending a session | 10 |
| §9.1 no docker.sock | Global constraint; compose in Task 7 mounts no socket |
| §9.2 Python toolchain, session `.env` | 1, 4 |
| §11.2 local-path origin | 2 |
| §11.3 PAT out of argv | 7 |
| §11.5 nine host-path defaults | 4 |
| §11.6 brief mandates push | 10 (CONVENTIONS.md); brief text itself is plan 2 |
| §11.7 `.claude/worktrees/` mixing | 8 |
| §11.8 CONVENTIONS.md unreachable | 10 |
| §13 unit + smoke testing | 2–9 |
| §14 documentation | 10 |

**Deferred to plan 2 (Mazkir integration), by design:** §8 Telegram mode
buttons and `confirmation_choices`; §11.4 `sendRich` dropping `extra`;
§11.1 already fixed and committed (`dbcc8a7`); `spawn_container` shelling
out to `session.sh`; the autonomous brief's push/PR mandate in
`assemble_brief`; the poller calling `session.sh clean`; §10 Doppler.

**Placeholder scan:** none — every step carries runnable code or an exact command.

**Type consistency:** `provision_clone()`, `source_remote_url()`,
`write_session_env()`, `repo_keep_reason()`, `session_keep_reason()`,
`write_credential_env_file()`, and the `cmd_*` handlers are each defined
once and referenced consistently. Test helpers `_provision`, `_list`,
`_clean`, `_launch`, `_git`, `_push_to_a_bare_upstream`, `_env_map` are
defined before first use, and the `source_repo` / `vault_repo` fixtures
keep their names throughout.
