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
# A session inherits no model choice from the host -- it gets whatever the
# image's Claude config defaults to, which is not necessarily a model this
# account can spend on. One autonomous session exited having done nothing
# but print "You've hit your monthly spend limit ... keep using Fable 5".
# Pin it here so every lane, automated and manual, agrees. Set to empty to
# defer to the container's own default.
DEFAULT_MODEL="${CODING_AGENT_MODEL-opus}"

die() { echo "session.sh: $*" >&2; exit 1; }

# Holds the credential env file so the EXIT trap can find it. Deliberately
# global: a trap body is expanded when it fires, by which point a `local`
# inside cmd_launch has gone out of scope and would expand to empty --
# leaving a file containing the GitHub PAT in TMPDIR after every launch.
CREDENTIAL_ENV_FILE_TO_CLEAN=""
cleanup_credential_env_file() {
  [ -n "$CREDENTIAL_ENV_FILE_TO_CLEAN" ] && rm -f "$CREDENTIAL_ENV_FILE_TO_CLEAN"
  CREDENTIAL_ENV_FILE_TO_CLEAN=""
}

# Read the source repo's GitHub URL. A clone would otherwise inherit the
# local filesystem path as origin: `git push` would write into the user's
# own checkout, the GIT_CONFIG insteadOf rewrite (which only matches
# git@github.com: URLs) would never fire, and `gh pr create` would have no
# GitHub remote to target.
source_remote_url() {
  local repo="$1" url
  # `git remote get-url` EXPANDS insteadOf rewrites. Inside a session the
  # container injects
  #   url.https://x-access-token:<token>@github.com/.insteadOf = git@github.com:
  # so get-url would hand back a token-bearing URL, and set-url would then
  # write that token straight into the new clone's .git/config -- exactly
  # what routing the credential through an env-file exists to prevent.
  # Read the configured value instead.
  url="$(git -C "$repo" config --get remote.origin.url 2>/dev/null || true)"
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
  local repo="$1" label="$2" dirty
  [ -d "$repo/.git" ] || return 0
  # Ignore two entries that are never workspace content:
  #   .coding-task-prompt.md  -- scratch written by launch
  #   memory/                 -- the nested vault clone, a separate repo
  #                              evaluated on its own below. Without this
  #                              the parent reports "uncommitted changes"
  #                              whenever a vault clone exists, masking the
  #                              real reason. (The real repo gitignores it,
  #                              but the check must not depend on that.)
  dirty="$(git -C "$repo" status --porcelain 2>/dev/null \
    | grep -v '^?? \.coding-task-prompt\.md$' \
    | grep -v '^?? memory/$' || true)"
  if [ -n "$dirty" ]; then
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

# Scope a GitHub credential to this one container via a mode-0600 file.
# Never -e flags: argv is copied into container metadata, where `docker
# inspect` echoes it back for as long as the container exists, and is
# visible in the host process list while the command runs.
# GIT_CONFIG_* drives an insteadOf rewrite so `git push` authenticates;
# GH_TOKEN authenticates `gh` itself for `gh pr create`, which a session
# needs because master takes PRs only.
#
# Always returns a path: compose's env_file key requires the file to exist,
# so an unconfigured token yields an empty file rather than no file.
write_credential_env_file() {
  local token_file="$1" out token=""
  out="$(mktemp -t mazkir-session-XXXXXX.env)"
  chmod 600 "$out"
  if [ -n "$token_file" ] && [ -f "$token_file" ]; then
    token="$(tr -d '[:space:]' < "$token_file")"
  fi
  : > "$out"
  if [ -n "$token" ]; then
    {
      echo "GIT_CONFIG_COUNT=1"
      echo "GIT_CONFIG_KEY_0=url.https://x-access-token:${token}@github.com/.insteadOf"
      echo "GIT_CONFIG_VALUE_0=git@github.com:"
      echo "GH_TOKEN=${token}"
    } >> "$out"
  fi
  # Same reasoning as the GitHub token: through the file, never argv.
  if [ -n "${DOPPLER_TOKEN:-}" ]; then
    echo "DOPPLER_TOKEN=${DOPPLER_TOKEN}" >> "$out"
  fi
  printf '%s' "$out"
}

cmd_launch() {
  local name="" root="$DEFAULT_ROOT" mode="manual" prompt_file="" dry_run=0
  local keep_env_file=0 detach=0 model="$DEFAULT_MODEL"
  local token_file="${CODING_AGENT_GITHUB_TOKEN_PATH:-}"
  name="$1"; shift
  [ -n "$name" ] || die "usage: session.sh launch <name> [--mode=MODE] [--prompt-file=PATH]"
  for arg in "$@"; do
    case "$arg" in
      --root=*) root="${arg#--root=}" ;;
      --mode=*) mode="${arg#--mode=}" ;;
      --prompt-file=*) prompt_file="${arg#--prompt-file=}" ;;
      --model=*) model="${arg#--model=}" ;;
      --github-token-file=*) token_file="${arg#--github-token-file=}" ;;
      --dry-run) dry_run=1 ;;
      --detach) detach=1 ;;
      --keep-env-file) keep_env_file=1 ;;
      *) die "unknown option: $arg" ;;
    esac
  done

  local session="$root/$name"
  [ -d "$session" ] || die "no such session: $name (looked in $root)"

  local brief=""
  if [ -n "$prompt_file" ]; then
    [ -f "$prompt_file" ] || die "no such prompt file: $prompt_file"
    # Read once: --prompt-file may be a process substitution (a fifo),
    # which cannot be read a second time to copy it.
    brief="$(cat "$prompt_file")"
    # Kept on disk so a human taking the session over can read the task.
    printf '%s' "$brief" > "$session/.coding-task-prompt.md"
  fi

  # `claude -p` takes prompt TEXT; handing it a path makes the path the
  # entire prompt. --remote-control starts an interactive session, which is
  # the only kind Remote Control can attach to -- and the reason hand-off
  # and manual sessions appear in Claude Mobile while autonomous ones
  # never do.
  local claude_args=(claude --dangerously-skip-permissions)
  # Before the mode flags: -p and --remote-control take the brief as a
  # positional, so anything appended after them lands inside the prompt.
  # An `[ -n "$x" ] && ...` one-liner would abort the whole script under
  # `set -e` whenever the test is false, i.e. exactly in the --model= case.
  if [ -n "$model" ]; then
    claude_args+=(--model "$model")
  fi
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

  # The credential reaches the container through compose's env_file key,
  # not argv. CREDENTIAL_ENV_FILE is substituted into docker-compose.yml.
  local env_file compose_args
  env_file="$(write_credential_env_file "$token_file")"
  export CREDENTIAL_ENV_FILE="$env_file"
  CREDENTIAL_ENV_FILE_TO_CLEAN="$env_file"

  # `docker compose run` is foreground by default, which is what a human at
  # a terminal wants and exactly wrong for a caller that must return: a
  # server launching a session would block for the session's entire life.
  #
  # Detached runs also skip --rm and take an explicit name: the poller reads
  # `docker logs` AFTER the container exits to build its summary, so
  # auto-removal would destroy the transcript, and it needs a predictable
  # name because compose otherwise generates one per run.
  compose_args=(docker compose -f "$SCRIPT_DIR/docker-compose.yml" run)
  if [ "$detach" -eq 1 ]; then
    compose_args+=(-d --name "mazkir-coding-$name")
  else
    compose_args+=(--rm)
  fi
  compose_args+=(devcontainer "${claude_args[@]}")

  if [ "$dry_run" -eq 1 ]; then
    printf '%s\n' "${compose_args[*]}"
    if [ "$keep_env_file" -eq 1 ]; then
      CREDENTIAL_ENV_FILE_TO_CLEAN=""
      printf '%s\n' "$env_file"
    else
      cleanup_credential_env_file
    fi
    return 0
  fi

  # Fires on normal return, on error under set -e, and on interrupt.
  trap cleanup_credential_env_file EXIT INT TERM
  "${compose_args[@]}"
}

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

  cmd_provision "$name" ${provision_args[@]+"${provision_args[@]}"} >/dev/null
  cmd_launch "$name" ${launch_args[@]+"${launch_args[@]}"}
}

usage() {
  cat <<'USAGE'
session.sh -- containerized coding sessions

  session.sh start <name> [--mode=manual|handoff|autonomous] [--prompt-file=PATH]
      Provision (if needed) and launch. The command you normally want.
      manual      interactive Remote Control session, no seed prompt
      handoff     interactive Remote Control session seeded with a brief
      autonomous  headless `claude -p`; exits when done

  session.sh provision <name> [--repo=PATH] [--vault-repo=PATH] [--root=PATH]
  session.sh launch <name> [--mode=MODE] [--prompt-file=PATH] [--model=NAME]
                           [--dry-run]
  session.sh list [--root=PATH]
      One line per session: name, branch, and SAFE or KEEP: <reason>.
  session.sh clean <name> [--root=PATH] [--force]
      Remove a session only if nothing in it exists nowhere else.

Interactive sessions appear in Claude Mobile under <name>. There is no
session URL to copy -- find them by name.

Sessions run on opus by default (CODING_AGENT_MODEL, or --model=NAME per
launch). A session inherits nothing from the host shell, so without this it
would use whatever the image's Claude config defaults to. --model= (empty)
defers to that container default.

Sessions live in $HOME/dev/agent-sessions by default (AGENT_SESSIONS_ROOT).
Deliberately not .claude/worktrees/, which belongs to Claude Code's own
linked worktrees.
USAGE
  exit 0
}

main() {
  [ "$#" -ge 1 ] || usage
  local cmd="$1"; shift
  case "$cmd" in
    provision) cmd_provision "$@" ;;
    list) cmd_list "$@" ;;
    clean) cmd_clean "$@" ;;
    launch) cmd_launch "$@" ;;
    start) cmd_start "$@" ;;
    -h|--help|help) usage ;;
    *) die "unknown command: $cmd" ;;
  esac
}

main "$@"
