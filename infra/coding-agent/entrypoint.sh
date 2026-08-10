#!/usr/bin/env bash
# infra/coding-agent/entrypoint.sh
#
# Real container ENTRYPOINT. Applies dotfiles (if mounted), then execs
# whatever command was actually requested — preserving spawn_container's
# direct-exec invocation style
# (`docker run image claude --dangerously-skip-permissions ...`).
#
# Git push/PR credentials come entirely from GH_TOKEN + the GIT_CONFIG_*
# env vars set by the caller (spawn_container or docker-compose.yml) — not
# from `gh auth setup-git` here. That call would try to write
# ~/.config/gh/config.yml, which is a symlink into the read-only dotfiles
# mount when the `github` stow package is applied (this repo's dotfiles
# vendor their own gh config there) — confirmed failing
# ("read-only file system") without actually being needed: `gh` itself
# authenticates via GH_TOKEN directly for its own API calls (gh pr create,
# etc.), and git push already works via the GIT_CONFIG_* insteadOf rewrite.
set -uo pipefail

DOTFILES_DIR="${DOTFILES_DIR:-$HOME/dotfiles}"
STOW_PACKAGES=(lazyvim zsh tmux git github lazygit tmuxinator .claude)

if [ -d "$DOTFILES_DIR" ]; then
  echo "entrypoint: applying dotfiles from $DOTFILES_DIR"
  for pkg in "${STOW_PACKAGES[@]}"; do
    if [ -d "$DOTFILES_DIR/$pkg" ]; then
      stow -d "$DOTFILES_DIR" -t "$HOME" -R "$pkg" 2>&1 || echo "entrypoint: stow $pkg failed (non-fatal)"
    fi
  done
  # The git/ dotfiles package stows to ~/.config/.gitconfig, which is not a
  # path git reads by default (it wants ~/.gitconfig or
  # $XDG_CONFIG_HOME/git/config) — git would silently ignore it otherwise.
  if [ -f "$HOME/.config/.gitconfig" ]; then
    export GIT_CONFIG_GLOBAL="$HOME/.config/.gitconfig"
  fi
else
  echo "entrypoint: no dotfiles mounted at $DOTFILES_DIR, skipping"
fi

exec "$@"
