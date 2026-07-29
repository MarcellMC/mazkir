#!/usr/bin/env bash
# infra/coding-agent/devcontainer.sh
#
# Single command to start a fully-configured devcontainer: creates isolated
# worktrees for both the mazkir and mazkir-memory repos (so /workspace and
# /workspace/memory always exist together — see CONVENTIONS.md), wires up
# auth/dotfiles/credentials, and starts an interactive Remote Control
# session — or execs whatever command you pass after the task name instead.
#
# Usage:
#   ./devcontainer.sh <task-name>                 # interactive Remote Control session
#   ./devcontainer.sh <task-name> <command...>    # run something else instead (e.g. bash)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAZKIR_REPO_PATH="${MAZKIR_REPO_PATH:-$HOME/dev/mazkir}"
VAULT_REPO_PATH="${VAULT_REPO_PATH:-$MAZKIR_REPO_PATH/memory}"
WORKTREES_ROOT="${WORKTREES_ROOT:-$MAZKIR_REPO_PATH/.claude/worktrees}"
GITHUB_TOKEN_PATH="${GITHUB_TOKEN_PATH:-$HOME/.config/mazkir/coding-agent-github-token}"

if [ "$#" -lt 1 ]; then
  echo "usage: $0 <task-name> [command...]" >&2
  exit 1
fi
TASK_NAME="$1"
BRANCH="coding-agent/${TASK_NAME}"

export CLAUDE_JSON_PATH="${CLAUDE_JSON_PATH:-$HOME/.config/mazkir/coding-agent-claude-home.json}"
export CLAUDE_PLUGINS_PATH="${CLAUDE_PLUGINS_PATH:-$HOME/.claude/plugins}"
export DOTFILES_PATH="${DOTFILES_PATH:-$HOME/dotfiles}"
export GH_TOKEN="${GH_TOKEN:-$(cat "$GITHUB_TOKEN_PATH" 2>/dev/null || true)}"

WORKTREE_PATH="$WORKTREES_ROOT/$TASK_NAME"
VAULT_WORKTREE_PATH="$WORKTREE_PATH/memory"

# Tolerant of a worktree directory removed out-of-band (e.g. manual rm -rf
# instead of `git worktree remove`): the branch survives that, so a bare
# `worktree add -b` would fail with "already exists" on a re-run with the
# same task name. `prune` first clears git's bookkeeping for the missing
# directory (otherwise `add` can also refuse with "already registered"),
# then the branch is reused if it exists instead of recreated.
add_worktree() {
  local repo_path="$1" worktree_path="$2" branch="$3"
  git -C "$repo_path" worktree prune
  if git -C "$repo_path" rev-parse --verify --quiet "$branch" >/dev/null; then
    echo "devcontainer.sh: reusing existing branch $branch at $worktree_path"
    git -C "$repo_path" worktree add "$worktree_path" "$branch"
  else
    echo "devcontainer.sh: creating worktree at $worktree_path (branch $branch)"
    git -C "$repo_path" worktree add -b "$branch" "$worktree_path"
  fi
}

if [ ! -d "$WORKTREE_PATH" ]; then
  add_worktree "$MAZKIR_REPO_PATH" "$WORKTREE_PATH" "$BRANCH"
fi
if [ ! -d "$VAULT_WORKTREE_PATH" ]; then
  add_worktree "$VAULT_REPO_PATH" "$VAULT_WORKTREE_PATH" "$BRANCH"
fi

export WORKTREE_PATH
export VAULT_WORKTREE_PATH

cd "$SCRIPT_DIR"
if [ "$#" -gt 1 ]; then
  shift
  exec docker compose run --rm devcontainer "$@"
else
  exec docker compose run --rm devcontainer \
    claude --dangerously-skip-permissions --remote-control "$TASK_NAME" --model opus --effort high
fi
