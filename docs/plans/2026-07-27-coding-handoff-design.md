# Coding-Handoff (v1): Supervised Container-Based Coding Sessions — Design

**Status:** Design, not yet planned/implemented.
**Parent doc:** `docs/plans/2026-07-27-p6-roadmap-and-agentic-frameworks.md` (Block C)
**Scope:** v1 only — the "Tier 1+" hybrid described below. Tier 2 (custom hook/defer checkpoints without Remote Control), Tier 3 (fully unsupervised, task-classifier-routed autonomy), and multi-agent teams remain future extensions, not part of this design.

## 1. Problem

When something goes wrong in a Mazkir interaction (a bug, a needed small fix), the user currently has to separately open a Claude Code session and reconstruct context there by hand. Pain profile: occasional but sharp — roughly weekly, not constant, but breaks flow each time. The fix should capture most of that cost cheaply, without building the larger (and riskier) fully-autonomous infrastructure this could eventually grow into.

## 2. Architecture overview

1. During a normal conversation, a skill recognizes the message describes a bug/coding task.
2. It assembles a task brief (see §4) and always asks for explicit confirmation before doing anything else — no auto-launch, regardless of confidence. This reuses the existing confirm flow (`POST /message/confirm`), the same pattern already used for destructive tools.
3. On confirmation, `vault-server` provisions an isolated git worktree + Docker container (see §5) and execs a real `claude --dangerously-skip-permissions` CLI session inside it, seeded with the task brief as its initial prompt.
4. The session works unattended, with two safety backstops instead of interactive per-action approval: GitHub branch protection (§6) blocks anything from landing on `master` directly, and the container has no access to real secrets.
5. `vault-server` tracks the spawned process and notifies the user via Telegram once it exits, with a summary and a way to open the session in **Remote Control** (session URL / name at claude.ai/code) if they want to inspect or have already inspected it live from their phone.
6. The user reviews the resulting branch/diff and merges (or discards) it themselves — nothing auto-merges.

This is deliberately not the Claude Agent SDK's `query()` + hooks path (that remains relevant for a future Tier 2/3 where Mazkir itself needs to enforce checkpoints programmatically) — v1 uses a real Claude Code CLI process specifically so Remote Control works, since Remote Control only attaches to real interactive/CLI-style sessions, not headless SDK sessions.

## 3. Trigger and confirmation

- New skill (working name: `engineering`) added to the router alongside `mazkir` / `time-management` / `knowledge-management` / `motivation-management`, following the existing skill-registry pattern.
- Recognizes candidate coding tasks from conversation (bug reports, "this is broken," explicit requests like "can you fix X").
- Always confirms before provisioning anything — this is a hard rule for v1, not confidence-gated, because spinning up a container with bypassed permissions is more consequential than any existing write-tier action. Confirmation preview shows the assembled task brief so the user can adjust or cancel before a container ever starts.

## 4. Task brief assembly

A new tool builds the initial prompt from:
- A distilled task description from the conversation.
- A likely file/service area, guessed from Mazkir's own architecture map (`CLAUDE.md`).
- A relevant `trace_id`, obtained one of two ways:
  - **Live case** (bug surfaces in the same turn): read directly off the currently active tracing span (`services/tracing_helpers.py`) — no search needed.
  - **Retrospective case** (bug reported after the fact): correlate by scanning `data/logs/tool-calls.jsonl` for the conversation's `chat_id` within a time window around the reported timestamp, preferring entries with `ok=False`/`error_code` set; falling back to nearest-in-time otherwise. This is approximate for silent logic bugs (no exception to anchor on) — acceptable for v1, and worth surfacing to the user as "best guess" rather than certainty.
- Explicit working constraints embedded in the prompt: worktree path, branch name, "do not push to master," which test command to run before finishing, and a note to summarize the outcome in the final message.
- A pointer to `CLAUDE.md` for conventions.

Example shape:

```
You're picking up a task reported via Mazkir's Telegram bot.

## Task
<distilled symptom/request>

## Context
- Reported: <timestamp>, trace_id: <trace_id or "not found">
- Likely area: <best-guess path>
- Conversation excerpt:
  > <quoted excerpt>

## Working constraints
- Worktree at <path>, branch coding-agent/<slug>. Do not touch anything
  outside it. Do not push to master/origin directly.
- Run <test command> before considering this done.
- Summarize what changed and why in your final message.

See CLAUDE.md for architecture map and conventions.
```

Note: the `trace_id` is included for the *human* to cross-reference in Phoenix if they want to dig deeper — the containerized session itself won't have Phoenix access in v1, so it can't use the trace_id to investigate on its own.

## 5. Container + worktree lifecycle

- One Docker container + one fresh git worktree per task (reusing the existing `.claude/worktrees/` pattern already present in this repo).
- **Auth:** the container's `claude` CLI identity comes from `claude auth login` (claude.ai OAuth — required for Remote Control; an API key won't work for this). This is a one-time setup: run the container interactively once, log in, and persist the credential on a mounted volume that every future container reuses. No per-task login.
- **Plugins:** project-scoped skills (`.claude/skills/`, `CLAUDE.md`) come free with the worktree checkout. Global plugin marketplace (`superpowers`, `frontend-design`, `skill-creator`, `feature-dev`, `claude-md-management` — installed at `~/.claude/plugins/`, not per-project) needs to be explicitly available in the container: mount the host's `~/.claude/plugins/` read-only rather than maintaining a separate copy, so it stays in sync with whatever's installed on the regular dev machine.
- **Secrets:** the container gets no access to `vault-server`'s real `.env` (no Google OAuth token, no Telegram bot token, no API keys beyond what `claude auth login` itself needs). It's editing code, not running the live service.
- **Completion tracking:** `vault-server` launches the container as a process it manages directly (not via the SDK), so it can just wait on process exit — no separate polling/webhook mechanism needed. On exit, it reads the resulting `git log`/diff in the worktree and the CLI's final transcript message, and sends a Telegram summary.
- **Cleanup:** not automated in v1 — worktrees/containers are cheap enough to leave around and manually `docker rm` / `git worktree remove` until this becomes annoying enough to script.

## 6. Git safety model

Layered, not reliant on any single mechanism:
- **GitHub branch protection on `master`** (require PRs, no direct pushes) — this is the authoritative backstop; it holds server-side regardless of what happens inside the container.
- A scoped, fine-grained PAT for the container (push-capable on feature branches, not an admin/owner credential).
- Local git config defaulting bare `git push` to the current branch only, so an unqualified push can't accidentally target master even before GitHub's protection would catch it.

Bypass mode (`--dangerously-skip-permissions`) still hard-blocks filesystem root/home removal regardless of this config — that circuit breaker is built into the CLI itself, not something this design adds.

## 7. Data tracked

A lightweight per-task record, mirroring the existing `data/events/{date}.json` pattern rather than a vault note (this is operational tracking, not durable knowledge): `data/coding-tasks/{id}.json` — `{id, chat_id, trace_id, task_description, worktree_path, branch, container_id, status (proposed|running|done|failed), started_at, finished_at, summary}`.

## 8. Explicitly out of scope for this design
- Any hook-based (`PreToolUse`/`defer`) checkpoint gating — that's a Tier 2 concern if Remote Control supervision ever proves insufficient.
- Sandbox hardening beyond Docker (gVisor, Firecracker) — revisit if v1's container isolation proves inadequate.
- Task-complexity auto-routing / confidence-based tiering — v1 always confirms, always the same flow.
- Multi-agent parallel worktrees ("send a team") — noted in the parent roadmap doc as a Tier 3+ extension.
- Automating the one-time provisioning steps (Docker image build, `claude auth login`, PAT creation, branch protection setup) — manual setup, not part of the feature itself.

## 9. Open questions carried into implementation planning
- Whether CLI usage under `claude auth login` draws from Pro/Max subscription usage or metered API billing — worth confirming before relying on this for regular use.
- Exact skill name (`engineering` used as a placeholder above).
- Whether this should ever be reachable from the web app, or stays Telegram-only (current assumption: Telegram-only, since that's where the triggering conversation happens).
