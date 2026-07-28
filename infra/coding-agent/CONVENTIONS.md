# infra/coding-agent/CONVENTIONS.md

Conventions for any coding agent (Mazkir-spawned or a human-driven
interactive session) working inside this devcontainer. Read this before
doing anything destructive or confusing-seeming.

## You're in an isolated worktree, not the real checkout

`/workspace` is a real `git worktree` of the `mazkir` repo, on its own
branch. It shares the repo's object database with the main checkout on the
host, but it is its own working directory — changes here don't touch the
main checkout until you push and someone merges. Feel free to experiment,
commit, and reset within it.

## Two repos, not one

Mazkir spans two separate GitHub repositories:

- `MarcellMC/mazkir` — the code, mounted at `/workspace`.
- `MarcellMC/mazkir-memory` — the Obsidian vault, mounted (if the task
  needs it) at `/workspace/memory`.

`/workspace/memory` is **its own independent git worktree**, of a
completely different repo, just mounted at the path that mirrors the real
host layout (`memory/` sits inside the mazkir checkout there too — see
`CLAUDE.md`). Do not assume it's part of the same git history as
`/workspace`, and do not try to `git add`/commit vault changes from within
the mazkir repo's context (wrong repo, wrong remote). Commit and push each
one separately, and open a PR against each repo independently if both need
changes.

If `/workspace/memory` doesn't exist or is empty, the task didn't request
vault access — don't go looking for another path to reach it. There isn't
one mounted, and that's deliberate, not a bug for you to route around.

## Never guess at absolute host paths

The only things visible to you are what's explicitly mounted. If a file or
directory documented elsewhere (`CLAUDE.md`, a skill file) seems to be
missing, stop and say so rather than trying `/home/marcellmc/...` or any
other absolute host path — a prior incident during this feature's own
build happened exactly this way: an agent found an empty `memory/` in an
isolated worktree, went looking for the "real" path instead of asking, and
ended up committing directly into the live vault outside of any review
process.

## Branch naming

Match the existing convention: `coding-agent/{task-id-or-slug}` for both
repos when a task spans both. If you're driving this interactively rather
than via `propose_coding_session`, pick a clear, descriptive branch name
following the same `coding-agent/...` prefix so it's identifiable later.

## Landing changes

Push via the credential already configured (`gh auth setup-git` — see
`entrypoint.sh`), open a PR with `gh pr create`. `master` on the `mazkir`
repo has branch protection (PRs required, no direct pushes, even for
admins) — this is the authoritative safety backstop regardless of what
runs inside this container. Nothing merges without a PR.
