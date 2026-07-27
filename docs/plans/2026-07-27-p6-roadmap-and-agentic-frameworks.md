# P6 Roadmap + Agentic Frameworks Evaluation

**Status:** Research / decomposition — no implementation committed yet.
**Purpose:** Capture the framework-adoption analysis and next-phase roadmap decisions from a planning session, before picking the first sub-project to spec and build.

## 1. Agentic frameworks: should Mazkir adopt one?

Prompted by noticing overlap between Mazkir's hand-rolled agent loop (skills, hooks, tool registry, confidence gating) and what off-the-shelf frameworks now provide.

### Landscape (as of mid-2026)

- **Pydantic AI** (Python, Pydantic/FastAPI team) — typed tool schemas via Pydantic models, `pydantic-graph` agent graph, durable execution (resume across crashes/restarts), human-in-the-loop tool approval, MCP support, Logfire tracing. Best fit: one well-defined agent talking to typed tools inside an existing Python service.
- **LangGraph** (LangChain team) — explicit graph-based orchestration: cycles, branching, retries, durable checkpoints, human-approval nodes. Best fit: production agents needing auditability/determinism (regulated environments, "prove what happened at each step").
- **LangChain** — broad integration ecosystem (vector stores, loaders, retrievers), still common in job listings/legacy RAG stacks, reputation dinged for "kitchen sink" abstraction overhead. Best fit: RAG glue code, less so new agent cores.
- **CrewAI** — role-based multi-agent prototyping (specialist agents collaborating). Doesn't match Mazkir's single-user/single-assistant shape.
- **Mastra** (TypeScript, ex-Gatsby, v1.0 Jan 2026) — agents + durable workflows + memory + tools + evals + observability bundled. TS equivalent of Pydantic AI; only relevant if `telegram-bot` ever took on agent-loop logic (it currently doesn't).
- **OpenAI Agents SDK, Google ADK, Microsoft Agent Framework** — noted, not deeply evaluated; GPT-centric / enterprise-oriented respectively.
- **Claude Agent SDK** — the SDK Claude Code itself runs on. Distinct from the above: it's a coding-capable agent engine (file edits, bash, code search), not a generic "build your own agent" toolkit. See §3.3 for deep dive.

### Recommendation: no migration, borrow selectively

Mazkir's `agent_service.py` / `skill_executor.py` / `tool_registry.py` / `parallel_executor.py` / `hooks/` already went through three hardening passes (P3 tracing/caching, P4 tool-registry extraction, P5 parallel execution + streaming + GCal hooks). It works and is observed (Phoenix + structured logs + audit log). What a framework would replace is the *plumbing* (tool-call loop, schema validation, retry/streaming boilerplate) — maybe 20% of the system. The parts that are actually Mazkir-specific — confidence-tiered auto-execute thresholds, destructive-action preview/confirm, the Haiku-classifier skill router with cycle detection, GCal-sync-as-post-hook — are bespoke policy no framework ships. No concrete pain point currently justifies a rewrite of a working, hardened core.

**Decision:** do nothing to the architecture today. Interesting patterns worth keeping in mind for later, without adopting a new dependency:
- **Durable execution pattern** — Pydantic AI's checkpoint-between-graph-nodes idea. Mazkir's agent loop currently loses a whole turn on a mid-loop crash; worth revisiting if that ever actually bites.
- **MCP as an interop option** — not adopting a framework, just keeping MCP in reserve as a standard wire format if an off-the-shelf tool (e.g. a calendar/email MCP server) is ever worth plugging in instead of hand-rolling another `*_service.py`.
- **LangGraph's mental model matches Mazkir's own architecture** — the skill-router → skill-executor → confidence-gate → possible-hop flow *is* a graph with typed state, i.e. what LangGraph formalizes. Worth knowing for job-market purposes even without adopting it: Mazkir already built the pattern LangGraph productizes.

One block below (Coding-Handoff) is the exception where a framework — specifically Claude Agent SDK — is a genuinely strong fit, not a generic LLM-agent framework.

## 2. P6 Roadmap: sub-project decomposition

Deferred: **broken streak feature** — least significant item, left as-is for now.

Three independent blocks, each to be brainstormed/spec'd separately:

### Block A — Time Management System
Merges: habit-creation friction reduction, tracking currently-untracked recurring habits (dog walking, sleeping, household tasks, cooking, eating), the `tm-day-bd` sliding-div frontend bug, and the flagship "sustainable day schedule" feature.

Requirements captured so far:
- Use the hand-drawn time-allocation matrix (`memory/60-knowledge/notes/time-management-matrix-sketch.md`, source photo `memory/00-system/media/2026-06-20/photo_2026-06-20_05-00-22.jpg`) as a *prior*, so Mazkir can suggest a day schedule even before real habit-tracking data exists. Matrix categories: `dev` (18 hrs/wk), `org`, `music` (3–6 hrs/wk), `work` (30–36 hrs/wk), `house` (7 days/wk, 1–2 hrs/day), `dog` (weekly, unfilled — already flagged as untracked back in June), plus `commute`, `mandatory`, `immovable`, and `inflatory` (unpredictable/force-majeure) hour buckets.
- Combine matrix + real Google Calendar events to suggest a day plan.
- Surface the plan in the web app, in `/day`, and/or synced to GCal.
- Support easy on-the-fly adjustment — e.g. logging a dog walk or gym session should let Mazkir automatically reflow the rest of the day's plan.
- Likely needs frontend work (beyond the `tm-day-bd` bugfix).
- **Open question (unresolved):** how and when should Mazkir actually *suggest* the plan, without adding friction. This is the key design question for the eventual brainstorming session.
- Related prior notes surfaced during research: *Track and Plan* ("track → analyze → plan"), *Habitica-style Tasks*, *Periodic Tasks* (laundry, shopping, hygiene, workout, work-report) — all relevant background for habit tracking / gamification decisions in this block.

### Block B — Knowledge Management
To be brainstormed separately. Scope so far:
- Better use of tags and links; inline tasks vs. task files; closer compliance with the user's former (pre-Mazkir) Obsidian workflow.
- Wants documented conventions for a friction-free, intuitive workflow — not fully there yet despite progress.
- Action item before brainstorming: search old notes on tags-vs-links, hierarchies, rigidity, to help formalize conventions.
- Open question: whether a dedicated frontend page (MOC / "command center") is needed for linking data, adding context to tasks/goals, tracking/managing, and pulling relevant info while working with Mazkir.

### Block C — Coding-Handoff (analyzed in depth this session, see §3)
Framed by the user as potentially high-impact for dev velocity, but with real risk of large implementation cost without payoff — deliberately treated as risk/payoff analysis first, not an immediate spec.

**v1 design written:** `docs/plans/2026-07-27-coding-handoff-design.md` — a "Tier 1+" hybrid (always-confirm trigger, containerized worktree session via a real `claude --dangerously-skip-permissions` CLI process, supervised via Remote Control rather than custom hook-based checkpoints). Tier 2/3 and multi-agent teams remain future extensions.

## 3. Coding-Handoff: analysis

### 3.1 Motivation and pain profile
Today, when something goes wrong in a Mazkir interaction, the user has to separately open a Claude Code session and reconstruct context there. Pain profile: **occasional but sharp** — roughly weekly, not constant, but breaks flow each time it happens. This calibrates the investment level: doesn't (yet) justify a large, high-risk infra build, but is worth solving cheaply first.

Desired end-state per the user: different tasks should route to different autonomy levels — small, well-scoped bugfixes fully autonomous; complex design decisions keep a human in the loop. The appealing "send out a team of autonomous agents" idea was also raised.

### 3.2 Three tiers

**Tier 1 — Prep & notify.** Mazkir recognizes a coding need, assembles a task brief (conversation context, symptom, likely file/service, maybe a relevant trace_id), and delivers it (Telegram message / pre-seeded prompt) so the user launches Claude Code themselves.
- Infra: minimal — a new skill + a context-assembly/handoff tool.
- Risk: ~none — human always drives, in the existing trusted environment.
- Effort: small.
- Payoff: removes the "reconstruct context from scratch" tax — likely captures most of the actual (weekly, sharp) pain cheaply.

**Tier 2 — Launch & supervise.** Mazkir spawns a coding session in an isolated git worktree; pauses at checkpoints (before tests, before commit) for async human approval via Telegram, then resumes.
- Infra: worktree automation, programmatic session spawn (Claude Agent SDK `query()`), a checkpoint/approval bridge — can reuse the existing confidence-gate + Telegram-confirm pattern already built for destructive tool calls.
- Confirmed mechanism (§3.3): `PreToolUse` hook matched on the gating action (e.g. `git commit`/`git push`) returning `permissionDecision: "defer"` pauses and ends the query, persisting a `session_id`; resuming later via `resume: session_id` restores full conversation/tool-result history (not file state — that's separate).
- **Alternative worth weighing:** instead of hand-rolling the hook/defer/Telegram-approval loop, dispatch a real interactive/backgrounded Claude Code session (e.g. via Dispatch) and supervise it using Anthropic's own **Remote Control** / **Agent View** features from phone or PC — no custom approval infra needed, at the cost of Mazkir's own policy layer not being in the loop. Worth deciding between "Mazkir enforces gates programmatically" vs. "human supervises via existing multi-device tooling" when this block is actually spec'd.
- Risk: bounded by approval gates; still needs basic scoping of what the session can see while investigating.
- Effort: medium.

**Tier 3 — Fully autonomous.** Session runs end-to-end unsupervised (fix, test, commit, open PR), inside a sandbox.
- Infra: everything in Tier 2, plus a **self-built sandbox** — confirmed the Agent SDK does *not* provide sandboxing itself; permission modes (`acceptEdits`, `bypassPermissions`, etc.) control what Claude asks permission for, not what it's physically capable of touching. Real isolation (containers, gVisor, Firecracker VMs, bubblewrap) is entirely the host's responsibility to build, per Anthropic's documented secure-deployment patterns.
- **Managed Agents** (a *separate* Anthropic API product, not the Agent SDK) offers an Anthropic-hosted managed sandbox — worth investigating as an alternative to self-hosting a container, though its fit with a git-worktree-based coding workflow is unconfirmed.
- Self-verification (running the existing test suite before declaring done) is a prompting/hook concern, not an SDK feature.
- Risk: real and different in kind — unsupervised write access to a system with real calendar, real Telegram bot, real personal data. Needs actual security engineering: scoped credentials (no real `.env`/OAuth tokens in the sandbox), resource/time limits, a kill switch, PR-based landing (never direct-to-main).
- Effort: large.
- Payoff: highest ceiling, but only for genuinely self-verifiable tasks (existing test reproduces the bug) — worth checking how much of `vault-server`'s test coverage actually supports that before assuming most bugfixes qualify.

**Multi-agent "team" extension (Tier 3+).** Structurally similar to how this very planning session dispatches subagents, and exactly what Claude Agent SDK's subagent feature is for — **with a correction**: subagents (`agents` dict passed to `query()`) run concurrently but share the parent session's working directory; there is no built-in per-agent worktree isolation. Getting N agents onto N isolated worktrees requires orchestrating N independent top-level `query()` calls (each with its own `cwd`) and aggregating results in Mazkir's own code — a real multiplier on Tier 3's effort and risk, not a freebie once Tier 3 exists.

### 3.3 Claude Agent SDK — confirmed capabilities (researched this session)

- **Programmatic invocation:** `query()` (Python `claude-agent-sdk`, TS `@anthropic-ai/claude-agent-sdk`) runs the full agentic coding loop headlessly; bundles the Claude Code binary (no separate install). Python's `ClaudeSDKClient` supports multi-turn conversations in-process. Typed message stream: `SystemMessage`, `AssistantMessage`, `ToolUseBlock`, `ResultMessage`.
- **Permission modes:** `default`, `dontAsk`, `acceptEdits`, `bypassPermissions`, `plan`, `auto` — switchable mid-session via `setPermissionMode()`.
- **`canUseTool` callback** exists but is *not* a general approval gate — it only fires at the tail of a permission-evaluation chain and is skipped under `bypassPermissions`.
- **Hooks are the real gating mechanism:** `PreToolUse`/`PostToolUse` hooks run before/after every tool call; a `PreToolUse` hook can `deny` (block, even under `bypassPermissions`) or `defer` (pause + end the query for later resume), and can rewrite inputs via `updatedInput`. Matchable by tool name (e.g. `Bash`, `Write|Edit`).
- **Session resume:** sessions persist as JSONL under `~/.claude/projects/<encoded-cwd>/`; resuming via `resume: session_id` restores conversation/tool-result history (not file state, which needs separate checkpointing). Sessions can also be `fork`ed. Cross-host resume needs manual session-file handling or a custom `SessionStore`.
- **Sandboxing:** not provided by the SDK. Documented patterns (containers, gVisor, Firecracker, bubblewrap) are the host's responsibility to implement. **Managed Agents** is a separate, Anthropic-hosted product offering a managed sandbox — different integration model than the Agent SDK.
- **Subagents:** `agents` dict of `AgentDefinition` (description, prompt, tool whitelist, model override) passed to `query()` options; run concurrently but **share the parent session's cwd** — no built-in worktree/directory isolation per agent.
- **Remote control:** `claude remote-control` and Agent View (`claude agents`) only apply to real interactive/Dispatch-launched Claude Code sessions running as local processes — **not** to sessions spawned headlessly via the SDK's `query()`. There is no documented way to remotely attach to and steer a live SDK-spawned session from another device. Session resume (`resume: session_id`) is asynchronous replay, not live remote control — an important distinction.
- **Plugins:** fully supported via a `plugins` SDK option (`{ type: "local", path: "..." }`), local-path only (no live marketplace pull at spawn time). Plugins bundle skills/agents/hooks/MCP servers identically to interactive Claude Code; namespaced invocation (`/plugin-name:skill-name`). Same API in Python and TS. Distinct from the separate `mcp` config option. Practical implication: the Tier 2/3 checkpoint-gating hook logic could be packaged as its own local plugin rather than wired ad hoc into `vault-server`, keeping it modular and testable independently.

### 3.4 Framework fit for this block specifically
Generic agent frameworks (Pydantic AI, LangChain, LangGraph, CrewAI, Mastra) are not a fit for *doing the coding* — none of them ship Claude Code's file-edit/diff, sandboxed-bash, and code-search toolset; building that on top of a generic framework would mean reimplementing Claude Code from scratch. Claude Agent SDK is the only new dependency worth adding, and only for this block. LangGraph's checkpoint/human-approval primitives are the closest generic-framework match to Tier 2's shape, but the SDK's own `PreToolUse`-`defer` + `resume: session_id` already covers the durability need natively — adopting LangGraph on top would mean running two orchestration paradigms for no real gain. Any remaining bookkeeping (which tier a task runs at, what a paused session is waiting on, aggregating a multi-worktree "team") is lightweight enough to track in Mazkir's own data model, consistent with the rest of the system.

### 3.5 Open questions carried forward
- How the task-complexity router (which tier a given task should run at) should actually classify tasks — likely start conservative (default Tier 2, promote to Tier 3 only for a narrow pre-approved category), mirroring Mazkir's existing safe/write/destructive tool risk classes.
- Whether Tier 2 supervision should be Mazkir-enforced (hooks + Telegram approval, custom-built) or human-driven via Remote Control/Agent View (existing Anthropic tooling, less custom infra, less Mazkir-side policy control).
- Whether Managed Agents is a viable sandbox for Tier 3 instead of self-hosting a container — needs its own investigation.
- Real test coverage in `vault-server`/`telegram-bot` as a gate on how much of Tier 3's promised value is actually reachable (self-verifiable tasks only).

## 4. Next steps
Three blocks (A/B/C above) each need their own brainstorming session → spec → plan → implementation cycle. None has been committed to a design yet.

**Confirmed brainstorming order:** Coding-Handoff (Block C) first, then Knowledge Management (Block B), then Time Management System (Block A).
