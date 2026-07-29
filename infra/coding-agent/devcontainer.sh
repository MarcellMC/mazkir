#!/usr/bin/env bash
# infra/coding-agent/devcontainer.sh
#
# Single command to start a fully-configured devcontainer: creates isolated
# clones of both the mazkir and mazkir-memory repos (so /workspace and
# /workspace/memory always exist together — see CONVENTIONS.md), wires up
# auth/dotfiles/credentials, and starts an interactive Remote Control
# session — or execs whatever command you pass after the task name instead.
#
# Clones, not `git worktree add`: a linked worktree's .git is just a
# pointer (`gitdir: /absolute/host/path/.git/worktrees/<name>`) back to the
# main repo's .git directory. That path doesn't exist inside a container
# that only mounts the worktree directory — confirmed directly: every git
# command inside such a container fails with "fatal: not a git
# repository", meaning the container could edit files but never
# git add/commit/push. A clone is fully self-contained (its own real .git
# directory) and just as fast here, since it's a same-filesystem clone
# (git hardlinks the object database rather than copying it).
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

# Idempotent: if worktree_path already exists (a resumed task, or one
# whose directory survived), reuse it as-is rather than re-cloning. Note
# that if the directory was deleted out-of-band since the last run, any
# local unpushed commits in it are gone -- they lived only in that clone's
# own object database, not the source repo's. Accepted trade for clones
# actually working inside a container at all.
add_worktree() {
  local repo_path="$1" worktree_path="$2" branch="$3"
  if [ -d "$worktree_path" ]; then
    echo "devcontainer.sh: reusing existing clone at $worktree_path"
    return
  fi
  echo "devcontainer.sh: cloning $repo_path to $worktree_path (branch $branch)"
  git clone "$repo_path" "$worktree_path"
  git -C "$worktree_path" checkout -b "$branch"
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
