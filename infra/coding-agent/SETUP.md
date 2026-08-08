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

**The container's home directory is also moved to `/home/marcellmc`**
(matching the actual host user), not left at the default `/home/node`.
Confirmed necessary, not cosmetic: Claude Code's own plugin state
(`installed_plugins.json`, `known_marketplaces.json`) records absolute host
paths like `/home/marcellmc/.claude/plugins/marketplaces/...`. Since these
files are bind-mounted from the host (not copied), mounting them at any
other path leaves every recorded location pointing somewhere that doesn't
exist in the container — this was the actual cause of "cache-miss"
marketplace-load errors and every plugin showing disabled, even after the
read-write mount fix below. If your host username/home differs from
`marcellmc`, update the `usermod -d` target in the Dockerfile and every
`/home/marcellmc/...` mount target in `docker-compose.yml` and
`spawn_container` to match.

## 2. Authenticate Claude Code (once, persists on a named volume)

    docker volume create mazkir-claude-auth
    docker run -it --rm -v mazkir-claude-auth:/home/marcellmc/.claude mazkir-coding-agent:latest claude auth login

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
      -v mazkir-claude-auth:/home/marcellmc/.claude \
      -v ~/.config/mazkir/coding-agent-claude-home.json:/home/marcellmc/.claude.json \
      mazkir-coding-agent:latest claude auth login

Go through the theme/billing prompts once here too — they'll persist in
that file from now on.

**Point `vault-server` at the same file.** Both the automated path
(`spawn_container`) and the interactive one (`session.sh`) must mount
it, or the automated containers fall back to the empty `.claude.json` the
Dockerfile touches — Claude Code rejects that as corrupt
("JSON Parse error: Unexpected EOF") and the session exits within seconds
having done nothing. Set in `vault-server`'s `.env`:

    CODING_AGENT_CLAUDE_JSON_PATH=~/.config/mazkir/coding-agent-claude-home.json

(This is the default, so it only needs setting if you put the file
elsewhere.) The same file also carries per-project trust. A container whose
`/workspace` isn't trusted starts with every `permissions.allow` entry
ignored, so make sure the JSON contains:

    {"projects": {"/workspace": {"hasTrustDialogAccepted": true}}}

Note both paths mount this file read-write and Claude Code writes to it, so
concurrent sessions share one state file — fine for a solo maintainer
running one task at a time, worth revisiting before running tasks in
parallel.

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
into the container through a **mode-0600 temp file** referenced by
`docker run --env-file`, which is unlinked as soon as Docker has read it.
The file sets:

- `GIT_CONFIG_COUNT`/`GIT_CONFIG_KEY_0`/`GIT_CONFIG_VALUE_0` — an
  `insteadOf` rewrite from the repo's SSH remote to
  `https://x-access-token:<token>@github.com/`, so `git push` authenticates.
- `GH_TOKEN` — authenticates `gh` itself, which the session needs for
  `gh pr create`. Since `master` takes PRs only (step 4), a container that
  can push but can't open a PR has no way to land anything.

Deliberately **not** `-e` flags: anything passed in `docker run`'s argv is
copied into the container's metadata, where `docker inspect` echoes it back
for as long as the container exists, and is visible in the host process
list while the command runs. An `--env-file` keeps the token out of both.

If `CODING_AGENT_GITHUB_TOKEN_PATH` is unset, containers spawn without a
push credential — they can still investigate and commit locally, just not
push or open a PR.

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
defaulting bare `git push` to the current branch only"): still not
implemented, though the original reasoning for skipping it no longer
applies. The original concern was that a linked `git worktree` shares
`.git/config` with the main checkout, so setting `push.default` inside it
would silently change push behavior on your host too. `/workspace` is now
a self-contained `git clone` instead of a linked worktree (see the
`create_worktree`/`_clone_repo` docstring in `coding_tasks_service.py` for
why — a worktree's `.git` points back to the main repo via an absolute
host path that doesn't survive being mounted into a container), so it has
its own independent config with zero shared state — setting `push.default`
inside it would be perfectly safe now. Not implemented simply because
branch protection (step 4) already is the layer that actually matters; a
reasonable follow-up if ever revisited.

## 5. Confirm the global plugin mount path and vault repo path

`CodingTasksService.spawn_container` mounts `/home/marcellmc/.claude/plugins`
into the container (read-write — confirmed Claude Code's own plugin system
needs to write to `plugins/marketplaces/...` when syncing/validating a
marketplace; a read-only mount here made every plugin show as "disabled"
and `/plugin` fail with an `EROFS` error trying to `rm` and re-sync it). If
your plugin marketplace lives at a different path, update the mount source
in `apps/vault-server/src/services/coding_tasks_service.py`'s
`spawn_container`.

`MAZKIR_VAULT_REPO_PATH` (defaults to `~/dev/mazkir/memory`) points at the
`mazkir-memory` repo — `CodingTasksService.create_vault_worktree` uses this
to provision an isolated clone of the vault, mounted at `/workspace/memory`,
alongside the mazkir clone at `/workspace`. See `CONVENTIONS.md` for how
the two repos relate inside the container.

## 6. Running sessions

`session.sh` is the single entry point. Mazkir's `vault-server` shells out
to the same script, so the automated and manual paths cannot drift — they
did before, and the divergence broke every automated session on boot.

    ./infra/coding-agent/session.sh start my-task            # interactive, Remote Control
    ./infra/coding-agent/session.sh list                     # what exists, and what is safe to remove
    ./infra/coding-agent/session.sh clean my-task            # remove, if nothing is unpushed
    ./infra/coding-agent/session.sh --help

Three modes, differing only in the final command:

| `--mode=` | Command | Appears in Claude Mobile |
|---|---|---|
| `manual` (default) | `claude --remote-control <name>` | yes |
| `handoff` | `claude --remote-control <name> "<brief>"` | yes |
| `autonomous` | `claude -p "<brief>"` | **no** — `-p` is print mode, and Remote Control only attaches to interactive sessions |

`start` creates isolated clones of both repos (mazkir at the root, the
vault nested at `memory/`, matching the host layout), rewrites each clone's
`origin` from the local path it inherits to the real GitHub URL, writes a
session `.env` with `/workspace` paths, applies your dotfiles (`~/dotfiles`
by default — see `entrypoint.sh` for the stow package list; `hypr` is
deliberately excluded, being Wayland/GUI-only), and launches.

Sessions live in `~/dev/agent-sessions/` (override with
`AGENT_SESSIONS_ROOT`). Deliberately **not** `.claude/worktrees/`, which
belongs to Claude Code's own linked worktrees — mixing clones into it makes
them invisible to `git worktree list` and to every cleanup path alike.

Override `MAZKIR_REPO_PATH`, `AGENT_SESSIONS_ROOT`, `DOTFILES_PATH`,
`CLAUDE_JSON_PATH`, `CLAUDE_PLUGINS_PATH`, or
`CODING_AGENT_GITHUB_TOKEN_PATH` as environment variables if your paths
differ from the defaults.

### Cleanup

`session.sh clean` removes a session only when **all four** hold, checked
independently for the workspace and the nested vault clone:

1. exit code 0 (autonomous sessions only)
2. the branch has an upstream
3. nothing committed that isn't on the remote
4. nothing uncommitted

Otherwise it refuses and names the failing predicate. `--force` overrides.
There is **no time-based deletion** — a clone is its own object database,
so anything committed but unpushed exists in exactly one place.

### After changing anything in `infra/coding-agent/`

    ./infra/coding-agent/smoke-test.sh

It boots a real container. The mocked test suite cannot catch image, mount,
or provisioning defects: 541 tests passed while every spawned session died
on boot.

**Known gap:** the `github` dotfiles package (your own vendored `gh` CLI
config) gets stowed as a symlink into the read-only dotfiles mount. This is
why the entrypoint does *not* run `gh auth setup-git` — it would fail
trying to write through that symlink. Git push and `gh pr create` both
still work (via `GIT_CONFIG_*` and `GH_TOKEN` respectively, neither needs
`gh auth setup-git` to have run), but any *other* `gh` state that command
would normally persist won't be. Not expected to matter for this use case;
worth knowing about if something `gh`-related seems oddly reset.
