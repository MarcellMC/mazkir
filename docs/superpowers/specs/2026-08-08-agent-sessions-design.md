# Agent Sessions (v2): Two-Lane Coding Sessions on a Shared Devcontainer — Design

**Status:** Design, approved. Not yet planned/implemented.
**Supersedes the session-launch portion of:** `docs/plans/2026-07-27-coding-handoff-design.md` (v1).
**Parent doc:** `docs/plans/2026-07-27-p6-roadmap-and-agentic-frameworks.md` (Block C).

## 1. Why this exists

v1's design was explicit that supervision would come from Claude's Remote Control:

> v1 uses a real Claude Code CLI process **specifically so Remote Control works**, since
> Remote Control only attaches to real interactive/CLI-style sessions, not headless SDK
> sessions. — `2026-07-27-coding-handoff-design.md` §2

The implementation shipped `claude --dangerously-skip-permissions -p "<brief>"`. `-p`
is print mode: non-interactive, exits when done, and Remote Control cannot attach.
The supervision mechanism the design leaned on was never built, and Tier 2 (hook/defer
checkpoints) had been deferred *because* Remote Control was expected to cover
intervention.

Real use confirmed the gap: most coding tasks arising from Mazkir conversations need
the user in the loop. A session that runs unattended and hands back a branch
reproduces most of the cost the feature was meant to remove.

This design keeps the autonomous path — it becomes more useful as skills mature — but
makes the supervised hand-off a first-class, separate lane rather than an accident of
which flag was passed.

## 2. Scope

**In scope:** two session lanes, a shared devcontainer base used by all entry points,
worktree provisioning and cleanup policy, mode selection from Telegram, and fixing the
defects in §11 that block any of the above.

**Out of scope:** Tier 2 hook/defer checkpoint gating, Tier 3 unsupervised
task-classifier routing, multi-agent teams, and a separate test-scoped
secrets/vault environment (see §10).

## 3. Two lanes

Both lanes use the same image, the same compose definition, and the same provisioning
code. They differ in the final command and in whether anything watches the result.

| | Autonomous | Hand-off | Manual |
|---|---|---|---|
| Started by | `propose_coding_session` | `propose_coding_session` | user runs `session.sh` |
| Command | `claude … -p "<brief>"` | `claude … --remote-control <name> "<brief>"` | `claude … --remote-control <name>` |
| Seed prompt | brief + push/PR mandate | brief | none |
| Monitored | yes — poller watches exit | no | no |
| Telegram notify | on completion | none — the session name is returned in the confirmation reply | never |
| Cleanup | automatic if §7 predicates pass | manual | manual |

Hand-off and manual are the same thing modulo who typed the command and whether a
brief is seeded. They must share one implementation.

### 3.1 Hand-off variants are a property of the prompt

The three behaviours the user asked for are **not** three infrastructure paths. They
are the same interactive invocation with different brief wording, and all three live
inside the hand-off lane:

| Variant | Seed prompt |
|---|---|
| `checkpoints` | brief + "stop and check in at natural checkpoints" |
| `run-through` | brief + "run to completion, then report and wait" |
| `wait-for-me` | none; brief sits in `.coding-task-prompt.md` unread |

All three stay alive after the agent stops, which is what distinguishes them from the
autonomous lane. Only autonomous (`-p`) is structurally different, because it exits —
and that exit is what the poller, the notification, and automatic cleanup all key off.

## 4. Components

`infra/coding-agent/` is the reusable base. One responsibility per file.

| File | Responsibility |
|---|---|
| `Dockerfile` | Image. Gains `python3` + `uv` (§9). Otherwise unchanged. |
| `docker-compose.yml` | The single container definition, parameterized by env. |
| `entrypoint.sh` | Apply dotfiles via stow, exec the requested command. Unchanged. |
| `session.sh` | Provision + launch + list + clean. The one implementation. |
| `CONVENTIONS.md` | Rules for agents working inside a session. Must become reachable (§11.8). |

### 4.1 `session.sh` is the single entry point

`CodingTasksService.spawn_container` shells out to `session.sh` rather than building
`docker run` arguments itself.

Rationale: `session.sh` must work standalone when vault-server is down — that is how
container problems get debugged — so the server is simply another caller. v1's plan
already specified this ("so the automated and manual paths are provably the same
container rather than two definitions that can drift apart", plan §1551); it was not
done, the two definitions drifted, and the `.claude.json` mount existed in
`docker-compose.yml` but not in `spawn_container`, which broke every autonomous
session (§11.1).

```
session.sh <name> --mode=autonomous --prompt-file=<path>
session.sh <name> --mode=handoff    --prompt-file=<path>
session.sh <name>                       # manual; no seed prompt
session.sh list
session.sh clean <name> [--force]
```

The four-predicate check (§7) lives in `session.sh`. The autonomous poller invokes
`session.sh clean` rather than reimplementing removal, so there is one implementation
of "is this safe to delete".

## 5. Naming

One name is used in three places, so `session.sh list` can correlate them with no
database:

- worktree — `~/dev/agent-sessions/<name>/`
- branch — `coding-agent/<name>` (both repos when a task spans both)
- Remote Control session — `<name>`

Autonomous sessions use `ct_<id>`; nothing ever displays it. Hand-off and manual
sessions use a readable slug derived from the task description (e.g.
`fix-day-duplicate-habits`) because the user finds sessions by name in Claude Mobile.
No session URL is captured or delivered — discovery is by name, by explicit decision.

## 6. Provisioning

`~/dev/agent-sessions/` sits outside the repository. `.claude/worktrees/` is left
exclusively to Claude Code's native linked worktrees; mixing full clones into it is
what let a 91MB abandoned clone become invisible to both `git worktree prune` and
Claude Code's own cleanup.

Sequence, for every lane:

1. `git clone <repo_path> <session_path>` — local path, so git hardlinks the object
   database.
2. `git -C <session_path> remote set-url origin <github-url>`, reading the URL from
   the source repo's `origin`. **Required** — see §11.2.
3. `git -C <session_path> checkout -b coding-agent/<name>`.
4. Repeat 1–3 for the vault into `<session_path>/memory` against `mazkir-memory`.
5. Write the session `.env` from the tracked `.env.example` with `/workspace` paths
   (§9.2).
6. Write `.coding-task-prompt.md` when a brief exists.
7. `docker compose run` with the lane's command.

Clones rather than linked worktrees: a linked worktree's `.git` is a pointer to an
absolute host path that does not resolve inside a container, so every git command
fails with "not a git repository". This is unchanged from v1 and remains correct.

## 7. Worktree cleanup

**No time-based deletion, ever.** A worktree is removed only when all four predicates
hold:

```
1. status == "done"                  exit code 0 — autonomous only
2. git rev-parse @{u}                succeeds — branch has an upstream
3. git log @{u}..HEAD                empty — nothing committed that isn't on the remote
4. git status --porcelain            empty — nothing uncommitted
```

Predicate 1 applies only to the autonomous lane, which is the only lane with a task
`status` at all. Hand-off and manual sessions are judged on predicates 2–4, and are
only ever removed by an explicit `session.sh clean`.

Evaluated independently for **both** repos. The vault clone is nested inside the
mazkir clone, so removing the parent destroys it too, and the two have entirely
independent push states.

Predicate 2 is deliberately conservative. A clone that never set an upstream is kept
even when it demonstrably holds no work. The alternative (`git log HEAD --not
--remotes`) is more precise but depends on remote-tracking refs being current, and the
cost of a false positive — permanently destroying unpushed commits that exist nowhere
else — is not worth the disk it saves. Abandoned no-op worktrees accumulate; they are
visible in `session.sh list` and removed with `--force` when the user decides.

`session.sh clean` refuses when any predicate fails and prints which one. `--force`
overrides. Nothing is ever removed without either all four passing or the user typing
`--force`.

### 7.1 Ending a session

A session cannot delete its own worktree: `/workspace` is the bind-mount root and the
process's working directory is inside it. "The session handles cleanup" therefore
means *the session makes the worktree safe to reclaim*. `CLAUDE.md` gains:

> **Ending a coding session.** Before finishing: commit everything, `git push -u
> origin <branch>` (upstream is mandatory), separately for `/workspace` and
> `/workspace/memory` if both were touched. Open a PR if the work is meant to land.
> Confirm `git status` is clean and nothing is unpushed, and say so in your final
> message — that is what allows the worktree to be reclaimed on the host.

Host-side removal stays with `session.sh clean`. Letting a session remove its own
worktree would require host access, which §9.1 rejects.

## 8. Mode selection from Telegram

`propose_coding_session` still always requires explicit confirmation. The confirmation
now offers a choice of lane instead of yes/no.

`AgentResponse` and the `/message` + `/message/confirm` payloads gain an optional
field:

```
confirmation_choices: [{ value, label }] | null
```

When present the bot renders an inline keyboard; when absent it falls back to today's
free-text yes/no. The callback posts the chosen `value` as `response`.
`_handle_confirmation_inner` treats any known choice value as affirmative and injects
it into the pending call's parameters before execution.

This keeps the bot a presentation layer — it renders whatever choices the server names
and knows nothing about coding sessions — and generalizes to any future tool that
wants to offer options.

Choices offered, matching §3.1:

| Button | Lane | Effect |
|---|---|---|
| `Autonomous` | autonomous | runs to completion, exits, notifies |
| `Hand-off — checkpoints` | hand-off | works, stops to check in, stays alive |
| `Hand-off — run through` | hand-off | completes, reports, stays alive |
| `Hand-off — wait for me` | hand-off | idles; brief unread until you drive it |
| `Cancel` | — | nothing is provisioned |

Five buttons is more than a yes/no gate wants to carry. If it proves noisy in use,
collapse to `Autonomous` / `Hand-off` / `Cancel` with hand-off defaulting to
`checkpoints`, since that is the variant the user named first — the other two remain
reachable by asking in conversation.

**Blocked by §11.4:** `sendRich`'s fallback discards `extra`, which carries
`reply_markup`. A rejected rich payload would drop the keyboard and leave no way to
choose a mode. That must be fixed first.

## 9. Base image and environment

### 9.1 No Docker-outside-of-Docker

Mounting `/var/run/docker.sock` grants control of the host daemon, which permits
mounting any host path into a new container as root. Combined with
`--dangerously-skip-permissions`, container isolation would become advisory — and
isolation plus branch protection are the entire safety model.

The actual requirement — running a test server against worktree code — does not need
Docker. The code is already mounted at `/workspace`; it needs a Python toolchain in
the image (§9.2) and a published port. Reaching services that are already running
(Phoenix, Loki, Grafana, an external test environment) is solved by joining a shared
Docker network, which requires no daemon access.

### 9.2 Toolchain and configuration

The image is `node:22-slim` and contains **no Python at all**, while the primary
backend is Python. Sessions currently bootstrap their own interpreter. The image gains
`python3` and `uv`.

`config.py` has nine defaults hardcoding `Path.home() / "dev" / "mazkir"`:
`media_path`, `timeline_data_path`, `events_data_path`, `logs_dir`, `skills_dir`,
`coding_tasks_data_path`, `coding_agent_worktrees_path`, `mazkir_repo_path`,
`mazkir_vault_repo_path`. None resolve inside a container, where the repo is at
`/workspace`. Provisioning writes a session `.env` from the tracked `.env.example`
overriding each with its `/workspace` equivalent.

## 10. Secrets

Secrets come from Doppler: the CLI is added to the image and a token is passed via
`--env-file` (never via `-e`, see §11.3), so nothing sensitive is written into the
clone.

**Deferred by explicit decision:** a separate test-scoped Doppler project and a
separate vault instance. Sessions share the user's real credentials for now.

This knowingly relaxes v1 §4's "the container has no access to real secrets" backstop.
What still holds: the live vault is never mounted (sessions get a clone of
`mazkir-memory`, so vault changes require push + PR to land), `master` keeps branch
protection, and there is no `docker.sock`. What is given up: a misbehaving session can
spend Anthropic quota, send Telegram messages as the bot, and push wherever the PAT
reaches. All recoverable, none silent.

Revisit when sessions run unwatched, or more than one runs at a time.

## 11. Defects this design depends on fixing

All verified against the running system.

1. **`spawn_container` never mounted `~/.claude.json`.** The Dockerfile creates it
   empty via `touch`; only `docker-compose.yml` mounted the real one. Containers
   booted on an empty file, Claude Code rejected it as corrupt ("JSON Parse error:
   Unexpected EOF"), and every autonomous session exited within ~14s having done
   nothing. *Already fixed and verified on `worktree-coding-handoff-v1`.*
2. **Clones inherit a local path as `origin`.** A clone's origin is
   `/home/marcellmc/dev/mazkir`, not `git@github.com:MarcellMC/mazkir.git`. So
   `git push` writes into the user's local checkout, the `GIT_CONFIG` insteadOf
   rewrite never fires (it only matches `git@github.com:` URLs), and `gh pr create`
   has no GitHub remote. **This blocks the push+PR definition of done, and would let
   predicates 2–3 pass on a push that never reached GitHub.** Evidence it has already
   happened: `coding-agent/devcontainer-verify` exists in the main repo. Fixed by
   step 2 of §6.
3. **The GitHub PAT is passed via `-e` flags**, which persist in `docker inspect`
   output and are visible in the host process list. Replaced by a mode-0600
   `--env-file` unlinked after Docker reads it. *Already fixed on the branch.*
4. **`sendRich`'s fallback drops `extra`.** `apps/telegram-bot/src/bot-utils/send-rich.ts`
   catches a rejected rich payload and calls `ctx.reply(richToPlainText(msg))` with no
   second argument, discarding `reply_markup` — and never logs why the send failed.
   Blocks §8. Fix: preserve `extra` in the fallback and log the rejection reason.
5. **Nine `config.py` defaults assume the host layout.** See §9.2. This caused a real
   session to report five test failures as "unrelated environment issues".
6. **`assemble_brief` discourages pushing.** It says "Do not push to master/origin
   directly", which a real session read as *do not push at all* — it committed locally
   and reported "Not pushed anywhere, per the constraints". Since a clone is the only
   copy of anything committed inside it, this steers autonomous sessions into
   producing work that one `rm -rf` erases. Autonomous briefs must mandate commit →
   `git push -u` → PR. Hand-off briefs keep the current wording; the user drives.
7. **`.claude/worktrees/` mixes mechanisms.** It holds both a linked worktree
   (Claude Code's) and a full clone written by `devcontainer.sh`, invisible to
   `git worktree list` and to every cleanup path. Resolved by §6's dedicated root.
   The existing 91MB clone is left in place by user decision.
8. **`CONVENTIONS.md` is unreachable.** It is present in every clone but nothing
   autoloads it and `CLAUDE.md` never references it — so the two-repo warning, the
   "never guess at absolute host paths" rule, and the incident note about an agent
   committing into the live vault are never read. Fix: the brief instructs sessions to
   read it, and `CLAUDE.md` links to it.

Separately, `CLAUDE.md` has drifted — it documents 32 tools, four skills, and has no
coding-handoff section at all.

## 12. Error handling

- Provisioning failure rolls back every clone created so far, including the case where
  the mazkir clone succeeds and the vault clone fails. An orphaned directory is worse
  than none, because `create_worktree` reuses an existing path as-is and would hand
  back a stale clone on retry.
- `docker compose run` failure marks the task `failed` and notifies for autonomous;
  prints the error for hand-off and manual.
- A session whose predicates do not pass is never auto-removed; it appears in
  `session.sh list` with the failing predicate named.
- Container reaping and full-log persistence on terminal transition are retained from
  the current implementation: logs are written to `data/coding-tasks/{id}.log` before
  the container is removed, since removal destroys the only other copy.

## 13. Testing

The branch shipped 541 passing tests and broke on first real use, because no test ever
started a container. v1's own post-mortem records the same lesson (plan §1542). Mocked
assertions on `docker run` argv prove the string is correct, not that the container
boots.

**Unit** — `session.sh` driven by pytest against throwaway git repos in `tmp_path`:
clone, `remote set-url`, nested vault clone, generated `.env` contents, each of the
four predicates independently, `clean` refusing on unpushed work, `--force`
overriding. Provisioning is where the bugs have actually been.

**Integration (mocked)** — `CodingTasksService` asserts the `session.sh` invocation;
poller exit-detection and the "does not delete when predicates fail" path;
`confirmation_choices` rendering an inline keyboard; `sendRich` preserving `extra` and
logging the rejection reason.

**Smoke (real container, opt-in)** — one documented command that provisions a
throwaway session, boots it, asserts the agent responds, asserts `git push` reaches
GitHub, and tears everything down. Not part of `turbo test` (needs Docker and
network), but run before merging any container change. Every defect in §11 that
reached the user would have been caught by it.

## 14. Documentation

- `SETUP.md` — one-time setup, including the Doppler token and
  `CODING_AGENT_CLAUDE_JSON_PATH`.
- `CONVENTIONS.md` — rules for agents inside a session; made reachable per §11.8.
- `session.sh --help` — the three lanes, `list`, and `clean`.
- `CLAUDE.md` — an "ending a coding session" section (§7.1), a link to
  `CONVENTIONS.md`, and a coding-handoff section covering the current tool count,
  risk levels, and skill roster.
