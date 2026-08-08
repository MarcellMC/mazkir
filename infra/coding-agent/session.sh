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
  echo "$dest"
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
