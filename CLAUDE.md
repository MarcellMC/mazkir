# Mazkir - Personal AI Assistant

## Project Overview

Mazkir is a personal AI assistant system with a Claude tool-use agent loop backed by a three-tier memory system (conversations, vault state, knowledge graph). It manages tasks, habits, goals, and knowledge through natural language via Telegram, with all data stored in an Obsidian vault.

**Architecture:** Turborepo monorepo with one Python backend + one TypeScript bot + one React webapp
**Primary Interface:** Telegram bot (`apps/telegram-bot`) + Telegram Mini App (`apps/telegram-web-app`)
**Backend:** FastAPI REST API (`apps/vault-server`) with agent loop + memory system
**Data Layer:** Obsidian vault (`memory/`, symlinked from `~/pkm/`) + Google Takeout timeline (`data/timeline/`) + persisted events (`data/events/`)

## Repository Structure

```
~/dev/mazkir/                          # Turborepo monorepo
├── apps/
│   ├── telegram-bot/                  # Telegram bot (TypeScript + grammY)
│   │   ├── src/
│   │   │   ├── index.ts              # Entrypoint + BotFather commands
│   │   │   ├── bot.ts                # grammY Bot + auth middleware
│   │   │   ├── config.ts             # Environment config
│   │   │   ├── api/client.ts         # vault-server API client
│   │   │   ├── commands/             # Command handlers (Composers)
│   │   │   ├── callbacks/            # Inline keyboard callback handlers
│   │   │   ├── conversations/        # NL message handler
│   │   │   └── formatters/           # Response formatters (HTML)
│   │   ├── tests/
│   │   ├── package.json
│   │   └── tsconfig.json
│   │
│   ├── telegram-py-client/            # [DEPRECATED] Old Python bot (kept for reference)
│   │   └── ...
│   │
│   ├── vault-server/                  # FastAPI backend (Python)
│   │   ├── src/
│   │   │   ├── main.py               # FastAPI app with lifespan
│   │   │   ├── config.py             # Pydantic settings
│   │   │   ├── auth.py               # API key middleware
│   │   │   ├── api/routes/           # REST endpoints
│   │   │   │   ├── tasks.py
│   │   │   │   ├── habits.py
│   │   │   │   ├── goals.py
│   │   │   │   ├── daily.py
│   │   │   │   ├── tokens.py
│   │   │   │   ├── calendar.py
│   │   │   │   ├── message.py        # Agent loop (tool-use) endpoints
│   │   │   │   ├── timeline.py       # Google Takeout timeline data
│   │   │   │   ├── events.py         # Unified events: auto-merge + persist + CRUD
│   │   │   │   ├── generate.py       # AI image generation (Replicate)
│   │   │   │   └── imagery.py        # Wikimedia Commons search
│   │   │   └── services/             # Business logic
│   │   │       ├── vault_service.py  # Obsidian vault CRUD
│   │   │       ├── claude_service.py # Claude API (thin wrapper + split system prompt for caching + stream support)
│   │   │       ├── memory_service.py # Three-tier memory + graph index
│   │   │       ├── agent_service.py  # Agent loop + tool registry + confidence gate
│   │   │       ├── router_service.py # Haiku LLM skill classifier (skill loop)
│   │   │       ├── skill_registry.py # Loads skill definitions from memory/00-system/mazkir-skills/
│   │   │       ├── skill_executor.py # Skill loop extracted from AgentService (P3)
│   │   │       ├── preview.py        # Destructive-action preview rendering
│   │   │       ├── resolver.py       # Tool input resolution + schema validation
│   │   │       ├── tool_response.py  # Typed tool result helpers
│   │   │       ├── tracing_helpers.py # with_span_status ctx mgr + span I/O helpers (P3)
│   │   │       ├── tool_registry.py  # Risk-class thresholds + pre/post hook stamps + preview flag (P4)
│   │   │       ├── tool_executor.py  # Per-call execution path (pre-hooks → handler → post-hooks → error override) (P4)
│   │   │       ├── daily_tasks.py    # DailyTasksService: parse/render ## Tasks section (P4)
│   │   │       ├── daily_schedule.py # parse/render daily-note ## Schedule section (timed events)
│   │   │       ├── parallel_executor.py # Parallel tool dispatch via asyncio.gather (P5)
│   │   │       ├── hooks/            # Pre/post tool hook registry
│   │   │       │   └── sync_to_calendar.py # Post-hook: sync task/habit writes to GCal (P5)
│   │   │       ├── tool_handlers/    # Extracted tool handler bodies (P5)
│   │   │       │   ├── __init__.py
│   │   │       │   └── daily.py      # daily_add_task, daily_set_task_state, daily_rollover, promote_daily_task
│   │   │       ├── calendar_service.py # Google Calendar sync
│   │   │       ├── timeline_service.py # Google Takeout parser
│   │   │       ├── merger_service.py   # Event merging + fuzzy matching
│   │   │       ├── events_service.py  # Persisted event storage + merge
│   │   │       ├── exif_service.py   # EXIF metadata extraction (Pillow)
│   │   │       ├── generation_service.py # Replicate image generation
│   │   │       └── imagery_service.py  # Wikimedia Commons geosearch
│   │   ├── scripts/
│   │   │   └── migrate_media_to_vault.py # Migrated 16 date dirs + rewrote 10 daily-note embeds (P4)
│   │   ├── pyproject.toml
│   │   └── .env
│   │
│   └── telegram-web-app/              # Telegram Mini App (React+Vite+Tailwind)
│       ├── src/
│       │   ├── main.tsx               # React entry point
│       │   ├── App.tsx                # Telegram SDK init + Router
│       │   ├── app/
│       │   │   ├── telegram.ts        # Telegram WebApp SDK helpers
│       │   │   └── Router.tsx         # Route definitions
│       │   ├── models/event.ts        # TypeScript interfaces
│       │   ├── services/api.ts        # vault-server API client
│       │   ├── components/            # Shared components (DateNav)
│       │   └── features/
│       │       ├── dayplanner/        # Enriched daily timeline view
│       │       └── playground/        # Asset generation playground
│       ├── package.json
│       ├── vite.config.ts
│       └── vitest.config.ts
│
├── memory/                            # Obsidian vault (nested git repo, gitignored)
│   ├── AGENTS.md                      # Vault schemas and workflows
│   ├── 00-system/
│   │   ├── templates/                 # Note templates
│   │   ├── conversations/             # Short-term memory (per day/chat)
│   │   ├── preferences/              # Inferred user patterns
│   │   └── media/                     # Photo attachments per day ({YYYY-MM-DD}/*.jpg) — gitignored in vault (P4)
│   ├── 10-daily/                      # Daily notes
│   ├── 20-habits/                     # Habit files
│   ├── 30-goals/                      # Goal files
│   ├── 40-tasks/                      # Task files
│   └── 60-knowledge/                  # Long-term memory
│       ├── notes/                     # User-captured ideas + facts
│       └── insights/                  # AI-generated connections
│
├── packages/
│   └── shared-types/                  # @mazkir/shared-types — shared TypeScript interfaces
│       ├── src/                       # Type modules (events, daily, tasks, habits, goals, etc.)
│       ├── package.json
│       └── tsconfig.json
│
├── data/                              # External data (gitignored)
│   ├── media/                         # [LEGACY] Old photo location — migrated to memory/00-system/media/ in P4
│   ├── events/                        # Persisted merged events ({YYYY-MM-DD}.json)
│   ├── timeline/                      # Google Takeout Semantic Location History
│   └── logs/                          # Structured JSON logs (vault-server.jsonl, agent-turns.jsonl, telegram-bot.jsonl, tool-calls.jsonl)
├── infra/observability/               # Local Loki + Alloy + Grafana docker-compose stack
├── docs/plans/                        # Design and implementation docs
├── turbo.json                         # Turborepo config
├── package.json                       # Root workspace config
└── CLAUDE.md                          # This file
```

**Symlink:** `~/pkm/` → `~/dev/mazkir/memory/`

## GitHub Repos

- `MarcellMC/mazkir` — This monorepo (code + docs)
- `MarcellMC/mazkir-memory` — Vault data (nested git inside `memory/`)

## Current Capabilities

### Telegram Bot Commands
- `/day` - Time-based feed: `GET /day` returns `{date, tokens_today, tokens_total, schedule[], notes[]}`. Schedule items sorted by start time, sourced from `calendar` (filtered by `GOOGLE_CALENDAR_INCLUDE`), `daily-task` (timed checkboxes from today's daily note), or `habit` (habits with `scheduled_at`). Notes parsed from `## Notes` section. Standalone tasks/habits arrays dropped — use `/tasks` and `/habits`.
- `/tasks` - Active tasks by priority
- `/habits` - Habit tracker with streaks
- `/goals` - Goals with progress bars
- `/tokens` - Motivation token balance
- `/calendar` - Today's schedule from Google Calendar
- `/sync_calendar` - Sync habits/tasks to Google Calendar
- NL messages routed through agent loop with conversational context, multi-step actions, and knowledge recall
- Photo messages — downloaded, EXIF extracted (GPS/timestamp/camera), saved to `memory/00-system/media/{YYYY-MM-DD}/` (vault, gitignored) with sidecar `metadata.json`, embedded in daily note as Obsidian wikilinks (`![[photo.jpg]]`), sent to Claude vision with EXIF context
- Location/venue messages — coordinates passed through agent loop
- Reply-to context and forwarded messages — included as context for the agent

- **GCal sync as post-hook (P5):** Every task/habit write fires the `sync_to_calendar` post-hook (`services/hooks/sync_to_calendar.py`), which reads the affected vault path from `output._items`, loads the metadata, and dispatches to `CalendarService.sync_task` / `sync_habit` / `mark_event_complete` (all async; bridged via `_maybe_await`). Failures log at WARNING and never block the tool result. Wired into `create_task`, `update_task`, `complete_task`, `archive_task`, `delete_task`, `create_habit`, `update_habit`, `complete_habit`, `delete_habit`.
- **Parallel tool execution (P5):** Each tool entry carries `safe_for_parallel: bool`. Read tools default safe; file-tier writes touching distinct paths (`create/update/complete/archive/delete` on task/habit/goal + `save_knowledge`) are overridden to safe; daily-section writes (`daily_*`, `attach_to_daily`, `edit_daily_section`) and event writes stay unsafe. The agent loop dispatches a batch of auto-execute tool calls via `parallel_executor.execute_calls_maybe_parallel` — concurrent via `asyncio.gather` in a worker thread when all calls are safe, serial fallback otherwise. Bulk-completion latency (May 21 trace: 13.7 s for 11 calls) drops to ~1–2 s.
- **Streaming responses (P5):** `ClaudeService.create(stream=True, on_chunk=…)` uses the Anthropic SDK's `messages.stream` context manager and forwards `text_delta` events. `AgentService.handle_message(stream_callback=…)` buffers per iteration and flushes chunks to the callback **only** on the final iteration (`stop_reason=end_turn` with no tool calls). The `/message?stream=true` route returns Server-Sent Events; the bot (with `STREAM_RESPONSES=true`) sends a placeholder message and edits it every ~500 ms as chunks arrive. Tool-use iterations stay hidden.
- **Tool handler split (P5):** `services/tool_handlers/daily.py` owns the daily-tier handler bodies (`daily_add_task`, `daily_set_task_state`, `daily_rollover`, `promote_daily_task`). AgentService delegates via thin wrappers. Other handler groups remain in `agent_service.py`; extraction continues incrementally.
- **`daily_set_task_state` walks nested children (P5):** the matcher now flattens the task tree depth-first; a substring matching both a top-level task and a sub-task correctly returns `AMBIGUOUS_MATCH` with all candidates.
- **Unified timed-event capture:** `create_event` is the canonical "timed thing" action — it writes the events store, syncs Google Calendar (best-effort), AND appends a line to the daily note's `## Schedule` section (`services/daily_schedule.py`), skipped for `photo_path` events. The `capture` skill now includes `create_event` and a prompt rule routing time-anchored content there instead of `save_knowledge`.

### Telegram Mini App (Web)
- **Dayplanner** - Enriched timeline with date navigation, merging calendar events, Google Takeout location history, habits, and daily notes
- **Playground** - AI asset generation with date navigation (micro icons, route sketches, keyframe scenes, full day maps) using Replicate + Wikimedia Commons imagery

### vault-server API Endpoints
- `POST /message` - Agent loop: `{text, chat_id, attachments?, reply_to?, forwarded_from?}` → multi-turn tool-use with confidence gate + Claude vision
- `POST /message/confirm` - Confirmation for low-confidence actions: `{chat_id, action_id, response}`
- `GET /day` - Time-based feed: `{date, tokens_today, tokens_total, schedule[], notes[]}` — schedule sorted by start time, sources: calendar (filtered by `GOOGLE_CALENDAR_INCLUDE`, default `Mazkir` only), daily-task (timed checkboxes), habit (habits with `scheduled_at`)
- `GET /timeline/{date}` - Google Takeout location history for a date
- `POST /generate` - AI image generation via Replicate (SDXL)
- `GET /events/{date}` - Auto-merges calendar+timeline+habits+daily notes, reconciles with persisted data (preserving photos/assets/manual events), returns enriched events
- `POST /events/{date}/refresh` - Force-refresh events from sources (same as GET, explicit intent)
- `PATCH /events/{date}/{event_id}` - Update a single persisted event
- `GET /imagery/search?lat=&lng=` - Wikimedia Commons geosearch for location imagery
- `GET /media/{date}/{file}` - Serve photo from vault media dir; falls back to vault-wide filename search when date URL doesn't match storage location

## Data Schemas

All vault files use YAML frontmatter. See `memory/AGENTS.md` for complete schemas.

**Task** (`memory/40-tasks/active/*.md`): type, name, status, priority (1-5), due_date, category
**Habit** (`memory/20-habits/*.md`): type, name, frequency, streak, last_completed, tokens_per_completion
**Goal** (`memory/30-goals/YYYY/*.md`): type, name, status, priority, progress (0-100), target_date
**Conversation** (`memory/00-system/conversations/{date}/{chat_id}.md`): type, chat_id, date, summary, items_referenced
**Knowledge** (`memory/60-knowledge/notes/*.md`): type, name, tags, links, source, source_ref
**Preference** (`memory/00-system/preferences/*.md`): type, name, tags, source (inferred), confidence, observations

## Development Guidelines

### Architecture
- **vault-server** owns ALL business logic (vault CRUD, Claude AI, calendar sync, timeline, generation)
- **Agent loop** (`AgentService`) replaces intent-parse-then-route: Claude tool-use with 31 registered tools (incl. `attach_to_daily`, `list_events`, `attach_photo_to_event`, `create_event`, `update_event`, `update_task`, `update_habit`, `update_goal`, `read_daily_section`, `edit_daily_section`, `delete_task`, `archive_task`, `delete_habit`, `archive_goal`, `daily_add_task`, `daily_set_task_state`, `daily_rollover`, `promote_daily_task`), max 10 iterations, confidence-based auto-execute (≥0.85) or human confirmation, Claude vision for photo messages with EXIF context. All tool calls return `{ok, data|error, _items}`; agent reacts to `error.code` (PATH_NOT_FOUND, AMBIGUOUS_MATCH, SCHEMA_INVALID, STATE_CONFLICT, ALREADY_DONE, EXTERNAL_FAILURE, AUTH_REQUIRED, CANCELLED_BY_USER).
- **Events persistence** (`EventsService`): merged events stored in `data/events/{date}.json`, supports create/attach/refresh with source-ID matching to preserve photos across re-merges
- **EXIF extraction** (`exif_service`): extracts GPS coordinates, timestamp, camera info from photo EXIF data using Pillow
- **Memory system** (`MemoryService`): short-term (conversation sliding window, 20 messages + decay), mid-term (vault state snapshot in system prompt), long-term (knowledge graph + keyword search)
- **telegram-bot** is a thin TypeScript UI layer (grammY + API calls + inline keyboards + NL routing)
- **telegram-web-app** is a React SPA consuming vault-server REST endpoints
- **@mazkir/shared-types** provides TypeScript interfaces shared between telegram-bot and telegram-web-app
- **Skill loop:** `AgentService.handle_message` dispatches via `RouterService` (Haiku LLM classifier) to one of three skills loaded from `memory/00-system/mazkir-skills/` (`capture`, `manager`, `recall`). Skills chain via a `next_skill: <name>` token in their reply; the loop caps at 3 hops with cycle detection. Each skill has its own model, tool subset, and system prompt. When `skill_registry`/`router` aren't configured, `AgentService` falls back to a single-loop legacy path with all tools loaded.
- **Skill executor module (P3):** Skill loop extracted to `services/skill_executor.py`. `AgentService` constructs a `SkillExecutor` when both `skill_registry` and `router` are present and delegates the per-turn loop to it.
- **Two-tier tasks (P4):** Default capture is a `- [ ]` line in the daily note's `## Tasks` section. Multi-day items promote to `40-tasks/active/{slug}.md` files via `promote_daily_task`. Daily-tier tools: `daily_add_task`, `daily_set_task_state` (check/uncheck/move), `daily_rollover` (yesterday's unfinished → today, anchored to first-original date via the `moved from [[...]]` chain), `promote_daily_task`. The `## Tasks` section is parsed/rendered by `DailyTasksService` (`services/daily_tasks.py`).
- **`/day` as time-based feed (P4):** `GET /day` returns `{date, tokens_today, tokens_total, schedule[], notes[]}`. Schedule items have `{start, end?, title, source, completed, calendar_name?}` sorted by start time. Source is `calendar` (filtered by `GOOGLE_CALENDAR_INCLUDE`, defaults to `Mazkir` only — drops holidays/subscribed calendars), `daily-task` (timed checkboxes from today's daily note), or `habit` (habits with `scheduled_at`). Notes are parsed from today's `## Notes` section. Standalone `tasks`/`habits` arrays dropped — use `/tasks` and `/habits` for those.
- **Media in vault (P4):** Default `MEDIA_PATH` is `~/dev/mazkir/memory/00-system/media/{YYYY-MM-DD}/`. Daily-note photo embeds are Obsidian wikilinks (`![[photo.jpg]]`). The folder is gitignored in the nested vault repo (binaries don't bloat git). The `/media/{date}/{file}` route falls back to vault-wide filename search when the date URL doesn't match storage location. Migration script at `apps/vault-server/scripts/migrate_media_to_vault.py` moved 16 date dirs + rewrote 10 daily-note embeds.
- **`list_tasks` returns grouped object (P4):** `{daily_pending, daily_done_today, file_tier_by_priority (dict keyed by int priority), overdue (file-tier tasks past due_date with status=active)}`. Replaces the flat list.
- **Tool registry + executor extracted (P4):** `services/tool_registry.py` owns risk-class threshold defaults + pre/post hook stamps + preview flag. `services/tool_executor.py` owns the per-call execution path (pre-hooks → handler → post-hooks → status propagation → error code override). `AgentService` delegates both.
- **Context assembly (P3):** `MemoryService.assemble_context` returns the conversation sliding window + a one-line vault summary. Knowledge auto-dump and `items_referenced` retired in P3; the agent calls `search_knowledge` explicitly when it needs notes. `_build_vault_snapshot` returns a single line of counts (active tasks / habits / goals / tokens), not per-item listings.
- **Prompt caching (P3):** The system prompt is split into a static prefix (active skill's system prompt + base guidelines + tool docs — identical across turns) and a dynamic tail (current date + vault summary line — changes each turn). The static prefix is sent with Anthropic's `cache_control: ephemeral`. Watch `llm.token_count.prompt_cached_read` in Phoenix to confirm cache hits on repeated calls from the same chat.
- **GCal sync post-hook (P5):** `services/hooks/sync_to_calendar.py` implements `sync_to_calendar_hook(tool_name, output, services)`. Registered as a post-hook on all task/habit write tools. Reads `output._items`, detects item type from vault path prefix (`40-tasks` → task, `20-habits` → habit), calls `CalendarService.sync_task` / `sync_habit` / `mark_event_complete` as appropriate. Never raises — failures are WARNING-logged with the trace_id so they correlate to the Phoenix span.
- **Parallel tool execution (P5):** `services/parallel_executor.py` exports `execute_calls_maybe_parallel(calls, executor_fn, safe_predicate)`. The tool registry's `safe_for_parallel` flag drives the predicate. When a batch is fully safe, calls run via `asyncio.gather` dispatched from a background thread. Serial fallback when any call is unsafe or the batch has side effects on the same path. AgentService passes the batch to this helper after the confidence gate instead of looping serially.
- **Streaming responses (P5):** `ClaudeService.create(stream=True, on_chunk=callback)` wraps `client.messages.stream(...)` and calls `callback(delta_text)` for each `text_delta` event. `AgentService.handle_message(stream_callback=cb)` accumulates text per iteration; on the final iteration (`stop_reason=end_turn`, no tool calls) it flushes accumulated chunks through the callback. Intermediate tool-use iterations are not streamed. The `/message?stream=true` endpoint returns `text/event-stream` (SSE); the Telegram bot (env `STREAM_RESPONSES=true`) sends a placeholder and edits it on each chunk via `bot.editMessageText`.
- New features → add route to vault-server, then add UI in telegram bot or web app

### Agent tool risk levels
- **safe** (read-only): `list_tasks`, `list_habits`, `list_goals`, `get_daily`, `get_tokens`, `search_knowledge`, `get_related`, `read_daily_section`, `list_events`
- **write** (auto-execute at ≥0.85 confidence): `create_task`, `create_habit`, `create_goal`, `update_task`, `update_habit`, `update_goal`, `save_knowledge`, `attach_to_daily`, `edit_daily_section`, `attach_photo_to_event`, `create_event`, `update_event`, `daily_add_task`, `daily_set_task_state`, `daily_rollover`, `promote_daily_task`
- **destructive** (auto-execute at ≥0.95 confidence): `complete_task`, `complete_habit`, `delete_task`, `archive_task`, `delete_habit`, `archive_goal`
- Confidence thresholds are per-tool with risk-class defaults: `safe` ungated, `write` ≥0.85, `destructive` ≥0.95.
- Destructive tools always render a preview ("Would delete X / Would archive Y") and require explicit yes/no confirmation before execution, regardless of confidence.

### Observability (P3)

- **Span input/output:** Owned spans (`agent.handle_message`, `agent.loop`, `agent.tool_call`, `skill.<name>`) carry `input.value` and `output.value` attributes (truncated at 2000 chars with a `truncated: true` marker). Visible in Phoenix span detail view.
- **Status propagation:** Manual spans use the `with_span_status` context manager from `services/tracing_helpers.py`. Exceptions are recorded automatically; `agent.tool_call` additionally marks ERROR when the handler returns `ok=False` even without raising.
- **trace_id in logs:** Every structured log record carries a `trace_id` field (when inside an active span context). Grep a log line in `data/logs/vault-server.jsonl`, copy the `trace_id`, and paste it into Phoenix to jump straight to the trace.
- **Audit log:** `data/logs/tool-calls.jsonl` (path overridable via `MAZKIR_AUDIT_LOG_PATH`) records one JSON row per write/destructive tool call: `{ts, trace_id, tool, ok, error_code?, params_summary, items}`. Useful for grepping agent activity offline and correlating with Phoenix traces.

### When adding vault-server routes:
1. Create route in `apps/vault-server/src/api/routes/`
2. Add service method to relevant service if needed
3. Register router in `apps/vault-server/src/main.py`

### When adding agent tools:
1. Add tool schema + handler + risk to `_register_tools()` dict in `agent_service.py`
2. Implement `_tool_<name>` handler method (return dict, include `_items` for referenced paths)
3. For write/destructive tools: include `_confidence` and `_reasoning` in input_schema
4. Add tests in `test_agent_service.py` (registration check + handler mock test)
5. Update tool count in this file

### When adding telegram commands:
1. Create Composer in `apps/telegram-bot/src/commands/<name>.ts`
2. Add API method in `apps/telegram-bot/src/api/client.ts` if needed
3. Add formatter in `apps/telegram-bot/src/formatters/telegram.ts` if needed
4. Register Composer in `apps/telegram-bot/src/commands/index.ts` and `src/bot.ts`
5. Add shared types to `packages/shared-types/` if needed

### When modifying vault files:
1. Always update the `updated` field
2. Preserve existing frontmatter fields
3. Use templates from `memory/00-system/templates/`
4. File names: lowercase, hyphens (e.g., `buy-groceries.md`)

## Quick Commands

```bash
# Start vault-server
cd ~/dev/mazkir/apps/vault-server && source venv/bin/activate && python -m uvicorn src.main:app --reload --port 8000

# Start telegram bot (requires vault-server running)
cd ~/dev/mazkir/apps/telegram-bot && npx tsx src/index.ts

# Start telegram web app (requires vault-server running)
cd ~/dev/mazkir/apps/telegram-web-app && npm run dev  # http://localhost:5173

# Start all with Turborepo
cd ~/dev/mazkir && npx turbo dev

# Run tests
cd ~/dev/mazkir && npx turbo test          # All apps
cd ~/dev/mazkir/apps/vault-server && source venv/bin/activate && python -m pytest tests/  # Server only
cd ~/dev/mazkir/apps/telegram-bot && npx vitest run          # Bot only
cd ~/dev/mazkir/apps/telegram-web-app && npx vitest run      # Webapp only

# Test vault-server endpoints
curl http://localhost:8000/health
curl http://localhost:8000/tasks
curl http://localhost:8000/events/2026-03-05
```

## Related Documentation

- **Vault Schemas:** `memory/AGENTS.md`
- **Observability:** `docs/observability.md` — structured logs + Loki/Grafana stack + Phoenix distributed tracing
- **Project Roadmap:** `personal-ai-assistant-roadmap.md`
- **Memory System Design:** `docs/plans/2026-03-02-memory-system-design.md`
- **Memory System Plan:** `docs/plans/2026-03-02-memory-system-plan.md`
- **Migration Design:** `docs/plans/2026-02-28-monorepo-migration-design.md`
- **Bot Rewrite Design:** `docs/plans/2026-03-02-telegram-bot-rewrite-design.md`
- **Bot Rewrite Plan:** `docs/plans/2026-03-02-telegram-bot-rewrite-plan.md`
- **Legacy Bot Architecture:** `apps/telegram-py-client/tg-mazkir-AGENTS.md`
- **WebApp Design:** `docs/plans/2026-02-28-telegram-webapp-design.md`
- **WebApp Implementation Plan:** `docs/plans/2026-02-28-telegram-webapp-plan.md`
- **Rich Messages Design:** `docs/plans/2026-03-04-rich-messages-design.md`
- **Rich Messages Plan:** `docs/plans/2026-03-04-rich-messages-plan.md`
- **Photo Events Pipeline Design:** `docs/plans/2026-03-05-photo-events-pipeline-design.md`
- **Photo Events Pipeline Plan:** `docs/plans/2026-03-05-photo-events-pipeline-plan.md`
- **Skill Definitions:** `memory/00-system/mazkir-skills/*.md` — Mazkir sub-agent skill definitions (capture / manager / recall)
- **P4 Daily Tier + Media Plan:** `docs/plans/2026-06-04-mazkir-p4-daily-tier-media-plan.md`
- **P5 Integrations + Latency Plan:** `docs/plans/2026-06-04-mazkir-p5-integrations-latency-plan.md`
