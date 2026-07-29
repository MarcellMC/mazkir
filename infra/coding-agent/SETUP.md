# infra/coding-agent/SETUP.md

One-time manual steps required before the Coding-Handoff feature works
end-to-end. None of these are automated by application code — see
`docs/plans/2026-07-27-coding-handoff-design.md` for why.

## 1. Build the image

    docker build -t mazkir-coding-agent:latest infra/coding-agent/

Smoke-test it (the image has no `ENTRYPOINT`, so args after the image name
are exec'd directly as the container's command):

    docker run --rm mazkir-coding-agent:latest claude --version

Expected: prints a Claude Code CLI version string.

**Note on the container's user:** the image runs as the base `node:22-slim`
image's existing `node` user (UID 1000) rather than a freshly created one.
This matters because bind-mounted worktrees are owned by whatever UID owns
them on the host — a fresh `useradd` would land on the next free UID
(1001), which doesn't match a typical single-user host's UID (1000) and
silently breaks write access to the mounted worktree (confirmed: the
container could read files but not edit or create any). This assumes your
host user is UID 1000 (true for a typical single-user Linux setup, verify
with `id -u`) — if it isn't, the container won't be able to write to
bind-mounted worktrees either, and the fix is to adjust the Dockerfile's
user to match your actual host UID.

## 2. Authenticate Claude Code (once, persists on a named volume)

    docker volume create mazkir-claude-auth
    docker run -it --rm -v mazkir-claude-auth:/home/node/.claude mazkir-coding-agent:latest claude auth login

Follow the printed OAuth URL, approve from your phone/browser. This must be
a real claude.ai account login (Pro/Max) — an API key will not work with
Remote Control. Every subsequent spawned container reuses this volume and
is already authenticated. Re-run this step only if the token is revoked or
expires.

**Onboarding state (theme, subscription-vs-API choice) needs a second file.**
It lives in `~/.claude.json` — a file *sibling to* `~/.claude/`, which the
volume above doesn't cover (confirmed: it resets on every container run
without this). Named volumes can't target a single file (confirmed:
Docker refuses with "not a directory"), so this needs a host-side bind
mount instead:

    mkdir -p ~/.config/mazkir && echo '{}' > ~/.config/mazkir/coding-agent-claude-home.json
    docker run -it --rm \
      -v mazkir-claude-auth:/home/node/.claude \
      -v ~/.config/mazkir/coding-agent-claude-home.json:/home/node/.claude.json \
      mazkir-coding-agent:latest claude auth login

Go through the theme/billing prompts once here too — they'll persist in
that file from now on.

## 3. Create a scoped GitHub PAT

Create a fine-grained personal access token:

1. github.com → Settings → Developer settings → Personal access tokens →
   Fine-grained tokens → Generate new token
2. Resource owner: your account. Repository access: "Only select
   repositories" → `mazkir` only.
3. Repository permissions → **Contents: Read and write**. Leave everything
   else (especially **Administration**) at "No access" — this keeps the
   token unable to touch or bypass the branch protection set up in step 4.
4. Generate, copy the value immediately (shown once).

Store the token value in a file on your host that is never committed —
e.g. `~/.config/mazkir/coding-agent-github-token`, `chmod 600` — and point
`CODING_AGENT_GITHUB_TOKEN_PATH` at it in `vault-server`'s `.env`.

`CodingTasksService.spawn_container` reads this file and passes the token
into the container via `GIT_CONFIG_COUNT`/`GIT_CONFIG_KEY_0`/
`GIT_CONFIG_VALUE_0` environment variables (an `insteadOf` rewrite from the
repo's SSH remote to `https://x-access-token:<token>@github.com/`), scoped
to that one container process only. This deliberately avoids writing to
any git config file: the worktree at `/workspace` shares `.git/config`
with your main checkout (same reason `push.default` is left alone
elsewhere in this doc), so anything written to a config file inside the
container would leak back into your host repo. If `CODING_AGENT_GITHUB_TOKEN_PATH`
is unset, containers spawn without a push credential — they can still
investigate and commit locally, just not push.

## 4. Enable branch protection on `master`

`gh api`'s dot-notation for nested fields (`-F parent.child=value`) does not
reliably build the required `required_pull_request_reviews` object for this
endpoint — it silently drops the field, producing a 422
("required_pull_request_reviews" wasn't supplied). Pass the full JSON body
directly instead:

    gh api -X PUT repos/MarcellMC/mazkir/branches/master/protection --input - <<'JSON'
    {
      "required_status_checks": null,
      "enforce_admins": true,
      "required_pull_request_reviews": {
        "required_approving_review_count": 0
      },
      "restrictions": null
    }
    JSON

(`required_approving_review_count: 0` means PRs are required to merge, but
no one else needs to click "approve" — appropriate for a solo maintainer.
`enforce_admins: true` means this applies to you too, not just other
contributors.)

Verify it's active:

    gh api repos/MarcellMC/mazkir/branches/master/protection

This is the authoritative safety backstop — it holds regardless of what a
spawned coding session's git credentials would otherwise allow.

**Note on the third safety layer from the design doc** ("local git config
defaulting bare `git push` to the current branch only"): intentionally not
implemented in code. Setting `push.default` inside a linked worktree
modifies the *shared* `.git/config` (worktrees don't get their own config
unless `extensions.worktreeConfig` is enabled repo-wide), which would
silently change push behavior in your own main working tree too — not
worth that side effect when branch protection (step 4) is the layer that
actually matters. If this is revisited later, do it via a per-worktree
`git config --worktree` setting instead, after enabling
`extensions.worktreeConfig`.

## 5. Confirm the global plugin mount path and vault repo path

`CodingTasksService.spawn_container` mounts `/home/marcellmc/.claude/plugins`
read-only into the container. If your plugin marketplace lives at a
different path, update the mount source in
`apps/vault-server/src/services/coding_tasks_service.py`'s `spawn_container`.

`MAZKIR_VAULT_REPO_PATH` (defaults to `~/dev/mazkir/memory`) points at the
`mazkir-memory` repo — `CodingTasksService.create_vault_worktree` uses this
to provision an isolated worktree of the vault, mounted at
`/workspace/memory`, alongside the mazkir worktree at `/workspace`. See
`CONVENTIONS.md` for how the two repos relate inside the container.

## 6. Interactive/manual devcontainer sessions

For working in the container yourself (not via `propose_coding_session`) —
the same image, with your own dotfiles applied:

    infra/coding-agent/devcontainer.sh <task-name>

This creates worktrees for both repos under `~/dev/mazkir/.claude/worktrees/<task-name>/`
(mazkir at the root, the vault nested at `memory/`, matching the real host
layout), applies your dotfiles (`~/dotfiles` by default — see
`entrypoint.sh` for the exact stow package list; `hypr` is deliberately
excluded, it's Wayland/GUI-only and meaningless in a container), and starts
an interactive Remote Control session named after the task. Pass extra
arguments to run something else instead (e.g.
`devcontainer.sh my-task bash`).

Override any of `MAZKIR_REPO_PATH`, `VAULT_REPO_PATH`, `WORKTREES_ROOT`,
`DOTFILES_PATH`, `CLAUDE_JSON_PATH`, `CLAUDE_PLUGINS_PATH`,
`GITHUB_TOKEN_PATH` as environment variables before calling the script if
your paths differ from the defaults baked in.

**Known gap:** the `github` dotfiles package (your own vendored `gh` CLI
config) gets stowed as a symlink into the read-only dotfiles mount. This is
why the entrypoint does *not* run `gh auth setup-git` — it would fail
trying to write through that symlink. Git push and `gh pr create` both
still work (via `GIT_CONFIG_*` and `GH_TOKEN` respectively, neither needs
`gh auth setup-git` to have run), but any *other* `gh` state that command
would normally persist won't be. Not expected to matter for this use case;
worth knowing about if something `gh`-related seems oddly reset.
