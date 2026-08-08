#!/usr/bin/env bash
# infra/coding-agent/session.sh
#
# Single entry point for containerized coding sessions: provision, launch,
# list, clean. Mazkir's vault-server shells out to this rather than
# building its own `docker run` arguments, so the automated and manual
# paths cannot drift -- they did before, and the divergence broke every
# automated session (see
# docs/superpowers/specs/2026-08-08-agent-sessions-design.md §11.1).
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
    /*|.*) die "source repo origin is not a remote URL: $url" ;;
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

# config.py's defaults resolve under $HOME/dev/mazkir, which does not exist
# in a container where the repo is mounted at /workspace -- a real session
# hit this and reported the resulting five test failures as unrelated
# environment issues. Copy the tracked .env.example and append
# container-correct overrides for every path setting, so tests and the
# server run inside a session without manual fixing. Secrets are
# deliberately not copied; they arrive via the credential env-file at
# launch.
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

  # Mazkir spans two repos. The vault is an independent clone of
  # mazkir-memory nested at <session>/memory, mirroring the host layout.
  # Roll the mazkir clone back if it fails: an orphan would be reused as-is
  # by provision_clone's idempotent branch, silently handing a stale clone
  # to the next attempt at the same name.
  if [ -n "$vault_repo" ]; then
    if ! provision_clone "$vault_repo" "$dest/memory" "$branch"; then
      rm -rf "$dest"
      die "vault clone failed; rolled back $dest"
    fi
  fi

  write_session_env "$dest"
  echo "$dest"
}

# The retention predicates. A worktree is removable only when a repo holds
# nothing that exists nowhere else. Deliberately conservative: a clone with
# no upstream is kept even when it demonstrably holds no work, because the
# cost of a false positive is destroying commits that exist in exactly one
# place (a clone is its own object database). There is no time-based
# deletion.
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

# Evaluate both repos. The vault clone is nested inside the workspace, so
# removing the parent destroys it -- its push state has to be checked
# independently. Echoes "" when the whole session is safe to remove.
session_keep_reason() {
  local session="$1" reason
  reason="$(repo_keep_reason "$session" "workspace")"
  if [ -n "$reason" ]; then printf '%s' "$reason"; return 0; fi
  if [ -d "$session/memory/.git" ]; then
    reason="$(repo_keep_reason "$session/memory" "memory")"
    if [ -n "$reason" ]; then printf '%s' "$reason"; return 0; fi
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

  local found=0 session name branch reason
  for session in "$root"/*/; do
    [ -d "$session" ] || continue
    found=1
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

main() {
  [ "$#" -ge 1 ] || die "usage: session.sh <provision|launch|list|clean> ..."
  local cmd="$1"; shift
  case "$cmd" in
    provision) cmd_provision "$@" ;;
    list) cmd_list "$@" ;;
    *) die "unknown command: $cmd" ;;
  esac
}

main "$@"
