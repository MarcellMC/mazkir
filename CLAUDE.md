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
│   │   │       ├── skill_registry.py # Loads skill definitions from memory/00-system/skills/
│   │   │       ├── skill_executor.py # Skill loop extracted from AgentService (P3)
│   │   │       ├── preview.py        # Destructive-action preview rendering
│   │   │       ├── resolver.py       # Tool input resolution + schema validation
│   │   │       ├── tool_response.py  # Typed tool result helpers
│   │   │       ├── tracing_helpers.py # with_span_status ctx mgr + span I/O helpers (P3)
│   │   │       ├── tool_registry.py  # Risk-class thresholds + pre/post hook stamps + preview flag (P4)
│   │   │       ├── tool_executor.py  # Per-call execution path (pre-hooks → handler → post-hooks → error override) (P4)
│   │   │       ├── daily_tasks.py    # Module functions: parse/render ## Tasks + whole-note todos (P4)
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
│       │       ├── time-management/   # Daily/weekly note feed with date scrubber
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
- `/day` (bot command; the endpoint is `GET /daily`) - Browsable day viewer backed by the events ledger (Ship 2). Returns `{date, tokens_today, tokens_total, blocks[], gaps[], coverage{}, todos[], notes[]}` for any `?date=`. Blocks are merged events — calendar, timeline visits, transit, timed checkboxes from the daily note, and scheduled habits — sorted by start. `gaps[]` are unaccounted spans, rendered as `⚠` rows. `coverage{}` carries `covered_minutes`, `unaccounted_minutes` and `elapsed_minutes` — the last drives the `now` divider (see the architecture note below). `todos[]` carries every checkbox in the note that has not been moved away, from any section; the bot renders the untimed ones under a Todos block, since timed ones already appear as blocks. Notes parsed from `## Notes` section, checkbox lines excluded. Standalone tasks/habits arrays dropped — use `/tasks` and `/habits`. Rendered as a rich message with in-body date-navigation buttons, edited in place on each tap.
- `/tasks` - Active tasks by priority. Rich message: the per-task buttons are in the message **body** (numbered, matching the numbered list), and tapping one opens the detail view with in-body Complete / Back buttons.
- `/habits` - Habit tracker with streaks. Rich message: one in-body Complete button per habit not yet done today.
- `/goals` - Goals with progress bars. Rich message: numbered in-body buttons open a goal's detail view, which offers Back only (goals have no completion endpoint).
- `/tokens` - Motivation token balance
- `/calendar` - Today's schedule from Google Calendar
- `/sync_calendar` - Sync habits/tasks to Google Calendar
- NL messages routed through agent loop with conversational context, multi-step actions, and knowledge recall
- Photo messages — downloaded, EXIF extracted (GPS/timestamp/camera), saved to `memory/00-system/media/{YYYY-MM-DD}/` (vault, gitignored) with sidecar `metadata.json`, embedded in daily note as Obsidian wikilinks (`![[photo.jpg]]`), sent to Claude vision with EXIF context
- Location/venue messages — coordinates passed through agent loop
- Reply-to context and forwarded messages — included as context for the agent

- **GCal sync as post-hook (P5):** Every task/habit write fires the `sync_to_calendar` post-hook (`services/hooks/sync_to_calendar.py`), which reads the affected vault path from `output._items`, loads the metadata, and dispatches to `CalendarService.sync_task` / `sync_habit` / `mark_event_complete` (all async; bridged via `_maybe_await`). Failures log at WARNING and never block the tool result. Wired into `create_task`, `update_task`, `complete_task`, `archive_task`, `delete_task`, `create_habit`, `update_habit`, `complete_habit`, `delete_habit`.
- **Parallel tool execution (P5):** Each tool entry carries `safe_for_parallel: bool`. Read tools default safe; file-tier writes touching distinct paths (`create/update/complete/archive/delete` on task/habit/goal + `save_knowledge`) are overridden to safe; daily-section writes (`daily_*`, `attach_to_daily`, `edit_daily_section`) and event writes stay unsafe. The agent loop dispatches a batch of auto-execute tool calls via `parallel_executor.execute_calls_maybe_parallel` — concurrent via `asyncio.gather` in a worker thread when all calls are safe, serial fallback otherwise. Bulk-completion latency (May 21 trace: 13.7 s for 11 calls) drops to ~1–2 s.
- **Streaming responses (P5):** `ClaudeService.create(stream=True, on_chunk=…)` uses the Anthropic SDK's `messages.stream` context manager and forwards `text_delta` events. `AgentService.handle_message(stream_callback=…)` buffers per iteration and flushes chunks to the callback **only** on the final iteration (`stop_reason=end_turn` with no tool calls). The `/message?stream=true` route returns Server-Sent Events; the bot (with `STREAM_RESPONSES=true`) renders the reply as a Bot API 10.1 rich message — it pushes animated `sendRichMessageDraft` previews (keyed by a non-zero `draft_id`) every ~500 ms as chunks arrive, then persists the final message via `sendRichMessage`. Tool-use iterations stay hidden.
- **Tool handler split (P5):** `services/tool_handlers/daily.py` owns the daily-tier handler bodies (`daily_add_task`, `daily_set_task_state`, `daily_rollover`, `promote_daily_task`). AgentService delegates via thin wrappers. Other handler groups remain in `agent_service.py`; extraction continues incrementally.
- **`daily_set_task_state` walks nested children (P5):** the matcher now flattens the task tree depth-first; a substring matching both a top-level task and a sub-task correctly returns `AMBIGUOUS_MATCH` with all candidates.
- **Unified timed-event capture:** `create_event` is the canonical "timed thing" action — it writes the events store, syncs Google Calendar (best-effort), AND appends a line to the daily note's `## Schedule` section (`services/daily_schedule.py`), skipped for `photo_path` events. The `capture` skill now includes `create_event` and a prompt rule routing time-anchored content there instead of `save_knowledge`.

### Telegram Mini App (Web)
- **Time-management** - Continuous virtualized feed of daily and weekly notes with a date scrubber, rendered faithfully (sections, photos, wikilinks)
- **Playground** - AI asset generation with date navigation (micro icons, route sketches, keyframe scenes, full day maps) using Replicate + Wikimedia Commons imagery

### vault-server API Endpoints
- `POST /message` - Agent loop: `{text, chat_id, attachments?, reply_to?, forwarded_from?}` → multi-turn tool-use with confidence gate + Claude vision
- `POST /message/confirm` - Confirmation for low-confidence actions: `{chat_id, action_id, response}`
- `GET /daily?date=YYYY-MM-DD` - Day view (Ship 2): `{date, tokens_today, tokens_total, blocks[], gaps[], coverage{covered_minutes, unaccounted_minutes, elapsed_minutes}, todos[], notes[]}`. Delegates block-building to the events service rather than re-merging. `schedule[]` was removed in Ship 2 — everything it carried now arrives as a block. Reconciles **without persisting**: it calls `get_events_preview`, which runs `EventsService.reconcile` (pure) rather than `refresh_events` (reconcile + save), so navigation taps can never mutate the event store. `GET /events/{date}` still persists deliberately — the agent's `list_events` / `attach_photo_to_event` / `update_event` tools read the raw persisted store and would otherwise be unable to reference a non-manual event by id.
- `GET /timeline/{date}` - Google Takeout location history for a date
- `POST /generate` - AI image generation via Replicate (SDXL)
- `GET /events/{date}` - Auto-merges calendar+timeline+habits+daily notes, reconciles with persisted data (preserving photos/assets/manual events), returns enriched events
- `POST /events/{date}/refresh` - Force-refresh events from sources (same as GET, explicit intent)
- `PATCH /events/{date}/{event_id}` - Update a single persisted event
- `GET /imagery/search?lat=&lng=` - Wikimedia Commons geosearch for location imagery
- `GET /media/{date}/{file}` - Serve photo from vault media dir; falls back to vault-wide filename search when date URL doesn't match storage location

## Data Schemas

All vault files use YAML frontmatter. See `memory/AGENTS.md` for complete schemas.

**Task** (`memory/40-tasks/active/*.md`): type, name, status, priority (1-5, 5=highest), due_date, category
**Habit** (`memory/20-habits/*.md`): type, name, frequency, streak, last_completed, tokens_per_completion
**Goal** (`memory/30-goals/YYYY/*.md`): type, name, status, priority, progress (0-100), target_date
**Conversation** (`memory/00-system/conversations/{date}/{chat_id}.md`): type, chat_id, date, summary, items_referenced
**Knowledge** (`memory/60-knowledge/notes/*.md`): type, name, tags, links, source, source_ref
**Preference** (`memory/00-system/preferences/*.md`): type, name, tags, source (inferred), confidence, observations

## Development Guidelines

### Architecture
- **vault-server** owns ALL business logic (vault CRUD, Claude AI, calendar sync, timeline, generation)
- **Agent loop** (`AgentService`) replaces intent-parse-then-route: Claude tool-use with 33 registered tools (incl. `propose_coding_session`, `attach_to_daily`, `list_events`, `attach_photo_to_event`, `create_event`, `update_event`, `update_task`, `update_habit`, `update_goal`, `read_daily_section`, `read_knowledge`, `edit_daily_section`, `delete_task`, `archive_task`, `delete_habit`, `archive_goal`, `daily_add_task`, `daily_set_task_state`, `daily_rollover`, `promote_daily_task`), max 10 iterations, confidence-based auto-execute (≥0.85) or human confirmation, Claude vision for photo messages with EXIF context. All tool calls return `{ok, data|error, _items}`; agent reacts to `error.code` (PATH_NOT_FOUND, AMBIGUOUS_MATCH, SCHEMA_INVALID, STATE_CONFLICT, ALREADY_DONE, EXTERNAL_FAILURE, AUTH_REQUIRED, CANCELLED_BY_USER).
- **Events persistence** (`EventsService`): merged events stored in `data/events/{date}.json`, supports create/attach/refresh with source-ID matching to preserve photos across re-merges
- **EXIF extraction** (`exif_service`): extracts GPS coordinates, timestamp, camera info from photo EXIF data using Pillow
- **Memory system** (`MemoryService`): short-term (conversation sliding window, 20 messages + decay), mid-term (vault state snapshot in system prompt), long-term (knowledge graph + keyword search)
- **telegram-bot** is a thin TypeScript UI layer (grammY + API calls + inline keyboards + NL routing)
- **telegram-web-app** is a React SPA consuming vault-server REST endpoints
- **@mazkir/shared-types** provides TypeScript interfaces shared between telegram-bot and telegram-web-app
- **Skill loop:** `AgentService.handle_message` dispatches via `RouterService` (Haiku LLM classifier) to one of five domain skills loaded from `memory/00-system/skills/` (`mazkir`, `time-management`, `knowledge-management`, `motivation-management`, `engineering`). `mazkir` is the conversational router fallback: it converses, answers general questions, reads vault data (incl. `read_knowledge` for note bodies), and owns the daily journal, handing off writes to a domain skill via a `next_skill: <name>` token. The loop caps at 3 hops with cycle detection. Each skill has its own model, tool subset, and system prompt. When `skill_registry`/`router` aren't configured, `AgentService` falls back to a single-loop legacy path with all tools loaded.
- **Skill executor module (P3):** Skill loop extracted to `services/skill_executor.py`. `AgentService` constructs a `SkillExecutor` when both `skill_registry` and `router` are present and delegates the per-turn loop to it.
- **Two-tier tasks (P4):** Default capture is a `- [ ]` line in the daily note's `## Tasks` section. Multi-day items promote to `40-tasks/active/{slug}.md` files via `promote_daily_task`. Daily-tier tools: `daily_add_task`, `daily_set_task_state` (check/uncheck/move), `daily_rollover` (yesterday's unfinished → today, anchored to first-original date via the `moved from [[...]]` chain), `promote_daily_task`. The `## Tasks` section is parsed/rendered by module functions in `services/daily_tasks.py` (there is no `DailyTasksService` class).
- **`/daily` as day view (P4 → todos in Ship 1 → blocks/gaps/coverage in Ship 2):** `GET /daily` returns `{date, tokens_today, tokens_total, blocks[], gaps[], coverage{}, todos[], notes[]}` — see the endpoint list above and the events-ledger bullets below for the current shape. `schedule[]` (P4) no longer exists; everything it carried now arrives as a block. Notes are parsed from today's `## Notes` section, with checkbox lines excluded so they do not render twice. Standalone `tasks`/`habits` arrays dropped — use `/tasks` and `/habits` for those.
- **Todos are section-agnostic (Ship 1):** any `- [ ]` line anywhere in the daily note is a todo, not only ones under `## Tasks`. `parse_all_todos` (`services/daily_tasks.py`) walks the whole note, records the enclosing `## Heading` on each todo, and excludes `moved` items. `/day` returns them as `todos[]` and the bot renders the untimed ones under a Todos block.
- **Daily-note line parsing (Ship 1):** `_parse_task_content` is the single rule shared by `parse_tasks_section` and `parse_all_todos`. It peels decorations in the exact inverse of `render_tasks_section` — annotation, duration, time, strike — because peeling in any other order strands markup inside `text`. Such bugs survive a round-trip unchanged and stay invisible until something reads a field, so assert on fields, not on re-rendered output. The struck-comment boundary is the closing `~~`, never a particular em dash.
- **Media in vault (P4):** Default `MEDIA_PATH` is `~/dev/mazkir/memory/00-system/media/{YYYY-MM-DD}/`. Daily-note photo embeds are Obsidian wikilinks (`![[photo.jpg]]`). The folder is gitignored in the nested vault repo (binaries don't bloat git). The `/media/{date}/{file}` route falls back to vault-wide filename search when the date URL doesn't match storage location. Migration script at `apps/vault-server/scripts/migrate_media_to_vault.py` moved 16 date dirs + rewrote 10 daily-note embeds.
- **`list_tasks` returns grouped object (P4):** `{daily_pending, daily_done_today, file_tier_by_priority (dict keyed by int priority), overdue (file-tier tasks past due_date with status=active)}`. Replaces the flat list.
- **Tool registry + executor extracted (P4):** `services/tool_registry.py` owns risk-class threshold defaults + pre/post hook stamps + preview flag. `services/tool_executor.py` owns the per-call execution path (pre-hooks → handler → post-hooks → status propagation → error code override). `AgentService` delegates both.
- **Context assembly (P3):** `MemoryService.assemble_context` returns the conversation sliding window + a one-line vault summary. Knowledge auto-dump and `items_referenced` retired in P3; the agent calls `search_knowledge` explicitly when it needs notes. `_build_vault_snapshot` returns a single line of counts (active tasks / habits / goals / tokens), not per-item listings.
- **Prompt caching (P3):** The system prompt is split into a static prefix (active skill's system prompt + base guidelines + tool docs — identical across turns) and a dynamic tail (current date + vault summary line — changes each turn). The static prefix is sent with Anthropic's `cache_control: ephemeral`. Watch `llm.token_count.prompt_cached_read` in Phoenix to confirm cache hits on repeated calls from the same chat.
- **GCal sync post-hook (P5):** `services/hooks/sync_to_calendar.py` implements `sync_to_calendar_hook(tool_name, output, services)`. Registered as a post-hook on all task/habit write tools. Reads `output._items`, detects item type from vault path prefix (`40-tasks` → task, `20-habits` → habit), calls `CalendarService.sync_task` / `sync_habit` / `mark_event_complete` as appropriate. Never raises — failures are WARNING-logged with the trace_id so they correlate to the Phoenix span.
- **Parallel tool execution (P5):** `services/parallel_executor.py` exports `execute_calls_maybe_parallel(calls, executor_fn, safe_predicate)`. The tool registry's `safe_for_parallel` flag drives the predicate. When a batch is fully safe, calls run via `asyncio.gather` dispatched from a background thread. Serial fallback when any call is unsafe or the batch has side effects on the same path. AgentService passes the batch to this helper after the confidence gate instead of looping serially.
- **Streaming responses (P5):** `ClaudeService.create(stream=True, on_chunk=callback)` wraps `client.messages.stream(...)` and calls `callback(delta_text)` for each `text_delta` event. `AgentService.handle_message(stream_callback=cb)` accumulates text per iteration; on the final iteration (`stop_reason=end_turn`, no tool calls) it flushes accumulated chunks through the callback. Intermediate tool-use iterations are not streamed. The `/message?stream=true` endpoint returns `text/event-stream` (SSE); the Telegram bot renders agent NL replies as **Bot API 10.1 rich messages**: streaming (env `STREAM_RESPONSES=true`) pushes `replyWithRichMessageDraft` previews (non-zero `draft_id`, ephemeral ~30 s) on each ~500 ms tick and finalizes with `sendRichMessage`; non-streaming sends `{ markdown: response }` directly. Both go through the `sendRich` wrapper (`src/bot-utils/send-rich.ts`), which falls back to plain text if a rich payload is rejected. Rich messages **can** be edited in place — `editMessageText` takes a `rich_message` parameter, added in Bot API 10.1 alongside rich messages themselves. `/day`, `/tasks`, `/habits` and `/goals` all use that path. The remaining command digests (`/tokens`, `/calendar`) are still classic HTML `parse_mode` because nothing has needed converting them, not because rich cannot be edited.
- **The `now` divider and the ahead-marker (Ship 2):** on today's date `/day` splits its timeline into two tables with an `<hr>` between them — what has elapsed above, what is still scheduled below — and marks each still-to-come block with `⟳`. The signal is `coverage.elapsed_minutes`, which the server sends because it already computes it for `day_coverage`; deriving "now" a second time in the bot would be a second thing to get wrong. That field also carries the "is it today" question for free: a past day is `1440`, a future day is `0`, and only today falls strictly between — so the divider shows exactly when `0 < elapsed_minutes < 1440`, with no timezone comparison in the bot at all. It is suppressed when either side would be empty, because a divider above or below everything is noise. Gap rows never carry `⟳`: a gap in the future is not a gap, and the server already excludes future time from `unaccounted`. `⟳` shares the time-cell prefix slot with `✅` (completed), since a block cannot be both.
- **Two kinds of button (2026-08-30):** navigation *between* views (`/day`, `/tasks`, `/habits`, `/goals`) lives in the message's `reply_markup`, built by `buildNavKeyboard(current)` (`src/keyboards/nav.ts`) — it omits the current view rather than disabling it, because a button that re-renders the message you are already looking at makes Telegram reject the edit as "not modified". Navigation *within* a view — opening a task, completing a habit, changing the day — lives in the message **body** as `<tg-button-row>` elements, which requires the view to be a rich message. A Telegram message has only one `reply_markup`, so this split is what makes both kinds of control coexist. All four views are now rich messages; `src/formatters/telegram.ts` keeps the shared helpers (`escapeHtml`, `progressBar`, `stripEmptySections`, `formatTime`) and the views that are still classic HTML `parse_mode` — `formatCalendar`, `formatTokens`, `formatNlResponse`.
- **Button labels take plain text only.** No bold, italic, superscript or font size inside a `<tg-button>`; `style` offers only `danger`/`success`/`primary`/`link`. Rich formatting works in the message body, not in button labels. `/tasks` and `/goals` therefore label their in-body buttons with the list *number* and let the body carry the names — a row renders its buttons side by side, so eight name-width labels would each be unreadable.
- **Rich messages carry their own buttons (Ship 2):** Bot API 10.3 added rich **buttons** — `<tg-button-row>`, 1–8 buttons per row, each with `callback_data` and a `style` of `primary`/`success`/`danger`/`link`. Buttons live in the message *body*, not in `reply_markup`, which is why `/day`'s date navigation is rendered inline rather than as an inline keyboard. This is why grammy was upgraded to 1.46 (`@grammyjs/types` 5.0.0) in this ship. A consequence: degrading a rich message to plain text strips its navigation entirely, so `editRich` (`src/bot-utils/send-rich.ts`) treats Telegram's "message is not modified" response as a no-op rather than routing it through the plain-text fallback — re-tapping the day already on screen must not silently delete the buttons.
- **Coding sessions:** `propose_coding_session` (write tier, always confirmed) offers four lanes as inline-keyboard buttons at the gate. `autonomous` runs headless `claude -p`, is polled for exit, notified on completion, and its worktree auto-removed when the four retention predicates pass. The three hand-off variants (`handoff-checkpoints`, `handoff-run-through`, `handoff-wait`) run interactive `claude --remote-control <id>`, are attachable from Claude Mobile by name, and are **never** monitored or auto-cleaned. All lanes go through `infra/coding-agent/session.sh`; `CodingTasksService` shells out to it rather than building its own docker invocation, so the automated and manual paths cannot drift. Sessions live in `~/dev/agent-sessions/<id>/` on branch `coding-agent/<id>`.
- **Confirmation choices:** `AgentResponse.confirmation_choices` lets the server name the options a confirmation offers; the bot renders them as an inline keyboard and knows nothing about the underlying tool. Absent means the classic free-text yes/no gate.
- **Events ledger owns temporal data (Ship 2):** daily notes are a worksurface; the ledger is the source of truth for anything with a time. A timed checkbox becomes a block by *inference* — `MergerService` reads the note body on every merge and emits one block per timed checkbox, matched across opens by `source_ids`. Nothing is persisted and no write path is involved. Scheduled habits with no matching calendar event become standalone blocks the same way.
- **`source_ids` on merged events (Ship 2):** every event `MergerService` produces carries exactly one `source_ids` entry, so `EventsService.reconcile` can match it to its persisted counterpart (`refresh_events` is `reconcile` plus `save_events` — see the bullet below). Before this, merged events had no `source_ids` at all — every open assigned a new `id` and discarded anything set on the event, which would have made Ship 5's approval impossible to persist.
- **A source that fails to answer must never delete its events (Ship 2):** `EventsService.refresh_events` used to delete any persisted event whose `source_ids` did not match a fresh one. `_merge_from_sources` swallows source failures, so an expired token, a network blip and a genuinely empty calendar were indistinguishable — an unreachable calendar silently deleted every persisted calendar event for that date. This destroyed real data during this ship's development. Now `_merge_from_sources` returns `(events, available_sources)`, and an unmatched persisted event is dropped only when the source system that would have produced it actually answered. Availability is a **positive signal** — `calendar.get_todays_events_with_status` returns `(events, ok)`, since the plain `get_todays_events` catches `HttpError` and returns `[]`; timeline is gated on its data path existing; an empty `GOOGLE_CALENDAR_INCLUDE` match counts as unavailable because no API call was made. A persisted event's source system is derived from its `source_ids` **key**, not its `source` field, which is muddied by `"merged"` and `"manual"`. `available_sources=None` preserves everything, so a caller that has not been updated cannot delete data, and an unmapped `source_ids` key is likewise never deletable.
- **Coverage arithmetic (Ship 2):** `services/day_coverage.py` is pure arithmetic over minute offsets. Two numbers — `covered` (union of block intervals, clipped to elapsed time) and `unaccounted` (`elapsed − covered`). Overlapping blocks count once. Every maximal unaccounted span becomes a `⚠` gap row, overnight included: sleep is the largest unlogged span and surfacing it is the point.
- New features → add route to vault-server, then add UI in telegram bot or web app

### Agent tool risk levels
- **safe** (read-only): `list_tasks`, `list_habits`, `list_goals`, `get_daily`, `get_tokens`, `search_knowledge`, `read_knowledge`, `get_related`, `read_daily_section`, `list_events`
- **write** (auto-execute at ≥0.85 confidence): `create_task`, `create_habit`, `create_goal`, `update_task`, `update_habit`, `update_goal`, `save_knowledge`, `attach_to_daily`, `edit_daily_section`, `attach_photo_to_event`, `create_event`, `update_event`, `daily_add_task`, `daily_set_task_state`, `daily_rollover`, `promote_daily_task`, `propose_coding_session` (write tier but `preview: True`, so always confirmed regardless of confidence)
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

## Ending a Coding Session

If you are running inside a containerized session (`/workspace` is a clone,
not the real checkout), finish like this:

1. Commit everything.
2. `git push -u origin <branch>` — upstream is mandatory. Do this separately
   for `/workspace` and `/workspace/memory` if you touched both; they are
   different repos with independent push states.
3. Open a PR if the work is meant to land. `master` takes PRs only.
4. Confirm `git status` is clean and nothing is unpushed, and say so in your
   final message.

You cannot delete your own worktree — `/workspace` is a bind mount and your
working directory is inside it. Step 4 is what allows the host to reclaim it
via `session.sh clean`, which refuses while anything is unpushed.

Read `infra/coding-agent/CONVENTIONS.md` before doing anything else in a
session: it covers the two-repo layout, why `memory/` may be empty, and why
you must never guess at absolute host paths.

## Related Documentation

- **Coding Session Conventions:** `infra/coding-agent/CONVENTIONS.md` — rules for agents working inside a containerized session (two repos, isolated clone, landing changes)
- **Coding Session Setup:** `infra/coding-agent/SETUP.md` — one-time setup; `session.sh` usage, modes, and cleanup
- **Agent Sessions Design:** `docs/superpowers/specs/2026-08-08-agent-sessions-design.md` — two-lane design (autonomous vs hand-off)
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
- **Skill Definitions:** `memory/00-system/skills/*.md` — Mazkir sub-agent skill definitions (mazkir / time-management / knowledge-management / motivation-management)
- **P4 Daily Tier + Media Plan:** `docs/plans/2026-06-04-mazkir-p4-daily-tier-media-plan.md`
- **P5 Integrations + Latency Plan:** `docs/plans/2026-06-04-mazkir-p5-integrations-latency-plan.md`
