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

## 2. Authenticate Claude Code (once, persists on a named volume)

    docker volume create mazkir-claude-auth
    docker run -it --rm -v mazkir-claude-auth:/home/agent/.claude mazkir-coding-agent:latest claude auth login

Follow the printed OAuth URL, approve from your phone/browser. This must be
a real claude.ai account login (Pro/Max) — an API key will not work with
Remote Control. Every subsequent spawned container reuses this volume and
is already authenticated. Re-run this step only if the token is revoked or
expires.

## 3. Create a scoped GitHub PAT

Create a fine-grained personal access token scoped to the `mazkir` repo
only, with contents:write (push) permission, no admin/owner scope. Store it
wherever the container's git config expects it (e.g. baked into a
`.netrc` mounted alongside the auth volume, or a repo-scoped deploy key —
pick whichever your existing git credential setup already uses).

## 4. Enable branch protection on `master`

    gh api -X PUT repos/MarcellMC/mazkir/branches/master/protection \
      -F required_pull_request_reviews.required_approving_review_count=0 \
      -F enforce_admins=true \
      -F restrictions=null \
      -F required_status_checks=null

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

## 5. Confirm the global plugin mount path

`CodingTasksService.spawn_container` mounts `/home/marcellmc/.claude/plugins`
read-only into the container. If your plugin marketplace lives at a
different path, update the mount source in
`apps/vault-server/src/services/coding_tasks_service.py`'s `spawn_container`.
