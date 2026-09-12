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
- `GET /daily?date=YYYY-MM-DD` - Day view (Ship 2): `{date, tokens_today, tokens_total, blocks[], gaps[], coverage{covered_minutes, unaccounted_minutes, elapsed_minutes, confirmed_minutes, pending_minutes}, todos[], notes[]}`. Delegates block-building to the events service rather than re-merging. `schedule[]` was removed in Ship 2 — everything it carried now arrives as a block. Reconciles **without persisting**: it calls `get_events_preview`, which runs `EventsService.reconcile` (pure) rather than `refresh_events` (reconcile + save), so navigation taps can never mutate the event store. `GET /events/{date}` still persists deliberately — the agent's `list_events` / `attach_photo_to_event` / `update_event` tools read the raw persisted store and would otherwise be unable to reference a non-manual event by id. `gaps[].proposal` carries the suggested activity name when `gap_proposals.py` has one (Ship 5).
- `POST /daily/{date}/approve-all` - Approve all pending blocks for a date (Ship 5): no request body — `date` is already a path param → processes blocks that have `elapsed`, auto-skips still-ahead ones, updates their state to `approved`, stamps them with the block's own date (not today)
- `POST /daily/{date}/gaps/fill` - Fill a gap with a proposed activity (Ship 5): `{start, end, name?}` → a gap has no id (it is derived, not stored), so this keys on the interval rather than an index; absent `name` recomputes the proposal for that interval server-side rather than trusting a client-supplied name
- `GET /timeline/{date}` - Google Takeout location history for a date
- `POST /generate` - AI image generation via Replicate (SDXL)
- `GET /events/{date}` - Auto-merges calendar+timeline+habits+daily notes, reconciles with persisted data (preserving photos/assets/manual events), returns enriched events
- `POST /events/{date}/refresh` - Force-refresh events from sources (same as GET, explicit intent)
- `POST /events/{date}/{id}/state` - Update event approval state (Ship 5): `{state: "approved"|"dismissed"}` → updates the persisted state and returns the updated event; `"pending"` is rejected with 422, since pending is derived (`resolve_state`) and never a stored value
- `PATCH /events/{date}/{event_id}` - Update a single persisted event; now pins whichever of `name`/`location` (the `USER_SETTABLE_FIELDS` the request body can carry) are present to `user_set`, so the next reconcile does not overwrite them from the source — `photos`/`assets` are never pinned this way, since they are preserved by other means (Ship 5)
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
- **Agent loop** (`AgentService`) replaces intent-parse-then-route: Claude tool-use with 34 registered tools (incl. `propose_coding_session`, `attach_to_daily`, `list_events`, `attach_photo_to_event`, `create_event`, `update_event`, `delete_event`, `update_task`, `update_habit`, `update_goal`, `read_daily_section`, `read_knowledge`, `edit_daily_section`, `delete_task`, `archive_task`, `delete_habit`, `archive_goal`, `daily_add_task`, `daily_set_task_state`, `daily_rollover`, `promote_daily_task`), max 10 iterations, confidence-based auto-execute (≥0.85) or human confirmation, Claude vision for photo messages with EXIF context. All tool calls return `{ok, data|error, _items}`; agent reacts to `error.code` (PATH_NOT_FOUND, AMBIGUOUS_MATCH, SCHEMA_INVALID, STATE_CONFLICT, ALREADY_DONE, EXTERNAL_FAILURE, AUTH_REQUIRED, CANCELLED_BY_USER).
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
- **Session auth is synced from the host, never logged in inside the container (2026-09-02):** the `mazkir-claude-auth` volume holds its own OAuth credential whose refresh token is shorter-lived than the gaps between sessions — one authenticated in July was found in September holding `accessToken:""` and a `refreshTokenExpiresAt` a week past, a failed refresh having blanked it on the way out. `session.sh launch` therefore copies `~/.claude/.credentials.json` onto the volume before every launch (`sync_claude_credentials`; `session.sh auth` to do it by hand, `--no-credential-sync` to skip), so the host copy is authoritative and the volume never reaches the expiry cliff. A blank host credential is detected and skipped rather than copied over a possibly-valid one. This matters because an in-container login is nearly unfinishable: the image has no browser, no `DISPLAY` and no clipboard binary. For when one is unavoidable, `infra/coding-agent/open-url.sh` installs as `/usr/local/bin/xdg-open` (what Claude Code actually shells out to) and delivers the URL three ways — a file on the `/workspace` bind mount, OSC 52 to the host clipboard, and printed alone on its own line. `repo_keep_reason` filters the captured `.claude-auth-url` so logging in once cannot make a session look permanently dirty.
- **Confirmation choices:** `AgentResponse.confirmation_choices` lets the server name the options a confirmation offers; the bot renders them as an inline keyboard and knows nothing about the underlying tool. Absent means the classic free-text yes/no gate.
- **Events ledger owns temporal data (Ship 2):** daily notes are a worksurface; the ledger is the source of truth for anything with a time. A timed checkbox becomes a block by *inference* — `MergerService` reads the note body on every merge and emits one block per timed checkbox, matched across opens by `source_ids`. Nothing is persisted and no write path is involved. Scheduled habits with no matching calendar event become standalone blocks the same way.
- **An event ID is global; a `date` argument is only a hint:** `list_events` hands the agent IDs for whatever date it was asked about, so `update_event`, `delete_event` and `attach_photo_to_event` all resolve the ID through `EventsService.resolve_event_date` (hint first, then a scan of every date file) rather than trusting the caller. `update_event` used to default the hint to today and look nowhere else, which made every update to an event on another day fail with `PATH_NOT_FOUND` on an ID the agent had just been given.
- **The file an event lives in is the day it belongs to:** `/day` and `list_events` read `data/events/{date}.json` and never re-check the timestamps inside, so an update that lands an event on another date (`new_date`, or a `start_time` on a different day) moves its row to that date's file. A cross-date move also detaches `source_ids` into `moved_from_source_ids` and marks the event `manual` — otherwise `reconcile` at the target date finds no fresh event matching those ids and, for a calendar or timeline event, deletes it on the next read, silently undoing the move. `CalendarService` has no move call, so the upstream Google Calendar entry stays on the old date; `update_event` reports that as `calendar_sync` with `attempted: true` so the agent has to say it out loud.
- **`delete_event` deletes upstream too:** a duplicate removed only from the store is re-merged back on the next read, so the tool deletes the Google Calendar entry (best-effort) when the event carries a `calendar_id`. Note- and habit-derived events cannot be deleted this way at all — `MergerService` regenerates them from the checkbox or the habit — so the result carries `reappears_from_source: true` and the agent is told to say so rather than promise a deletion that will not hold.
- **`source_ids` on merged events (Ship 2):** every event `MergerService` produces carries exactly one `source_ids` entry, so `EventsService.reconcile` can match it to its persisted counterpart (`refresh_events` is `reconcile` plus `save_events` — see the bullet below). Before this, merged events had no `source_ids` at all — every open assigned a new `id` and discarded anything set on the event, which would have made Ship 5's approval impossible to persist.
- **A source that fails to answer must never delete its events (Ship 2):** `EventsService.refresh_events` used to delete any persisted event whose `source_ids` did not match a fresh one. `_merge_from_sources` swallows source failures, so an expired token, a network blip and a genuinely empty calendar were indistinguishable — an unreachable calendar silently deleted every persisted calendar event for that date. This destroyed real data during this ship's development. Now `_merge_from_sources` returns `(events, available_sources)`, and an unmatched persisted event is dropped only when the source system that would have produced it actually answered. Availability is a **positive signal** — `calendar.get_todays_events_with_status` returns `(events, ok)`, since the plain `get_todays_events` catches `HttpError` and returns `[]`; timeline is gated on its data path existing; an empty `GOOGLE_CALENDAR_INCLUDE` match counts as unavailable because no API call was made. A persisted event's source system is derived from its `source_ids` **key**, not its `source` field, which is muddied by `"merged"` and `"manual"`. `available_sources=None` preserves everything, so a caller that has not been updated cannot delete data, and an unmapped `source_ids` key is likewise never deletable.
- **Coverage arithmetic (Ship 2):** `services/day_coverage.py` is pure arithmetic over minute offsets. Two numbers — `covered` (union of block intervals, clipped to elapsed time) and `unaccounted` (`elapsed − covered`). Overlapping blocks count once. Every maximal unaccounted span becomes a `⚠` gap row, overnight included: sleep is the largest unlogged span and surfacing it is the point.
- **Per-field provenance (Ship 4):** an event's `user_set` map holds the fields the user set explicitly — one of `name`, `start_time`, `end_time`, `location`, `activity`. `reconcile` merges from the source as usual and then re-applies `user_set` last, so a rename or a corrected time survives re-inference while every unpinned field keeps tracking its source. This is the fix for a rename that persisted and then silently reverted on the next `/day` open. It is *not* the same mechanism as `moved_from_source_ids`: detach is for relocation (the event left the day its source owns and can never be matched there again), pinning is for override (the event is still that source's, but one field is now the user's). `revert_fields` on `update_event` removes a pin.
- **Completeness is derived (Ship 4):** `is_complete(event)` is `start_time and end_time`, computed wherever it is needed and never stored — a status that restates the timestamps goes stale. A block missing either end used to be dropped by `_build_blocks_and_coverage`; it now arrives as `/daily`'s `incomplete[]` and contributes nothing to coverage, so the gap it sits in stays visible as the prompt to finish it. `create_event` takes any two of `start_time` / `end_time` / `duration_minutes` and derives the third; given one, it writes an incomplete block rather than inventing the rest.
- **Cross-midnight blocks split (Ship 4):** `create_event` splits at 00:00 into one fragment per day, sharing a `logical_id` that nothing reads yet — Ship 5 needs it to approve both halves of a night's sleep at once, and the link is unrecoverable if not written at creation. Such a block is deliberately not synced to Google (`reason: "crosses_midnight"`): Google stores it natively as one event, which would hand a single fresh event to two per-day fragments on the next merge.
- **`list_events` returns the reconciled day (Ship 4):** it read the raw persisted file while `/day` rendered a reconciled, deliberately unpersisted view, so the two could disagree entirely. `services/day_assembly.py` now owns the source fan-out and both callers use it. On a source failure `list_events` falls back to the persisted store and sets `degraded: true` — an empty list would read to the agent as "that block does not exist", which is the shape of the denial bug Ship 3 fixed.
- **Calendar edits propagate (Ship 4):** `CalendarService.update_event` patches Mazkir's own calendar; before it existed, an edit made by talking changed the ledger and never reached Google, and the next merge read the unchanged Google values back over it. `MergedEvent.calendar` carries the owning calendar's name through the merge, so an event in another calendar reports `not_in_mazkir_calendar` rather than issuing a doomed call and reading a 404 as an unexplained failure.
- **The selected-date hint (Ship 4):** the bot passes `selected_date` on `POST /message` while the `/day` view is still the last message it sent to that chat, and drops it after any other send. Two guards make a stale hint harmless: `block_reference` resolves against the hinted day *and* today (so a stale hint only matters when the block exists on that day alone), and any write to a day that is not today names the day in the reply.
- **Approval is derived where it can be, stored where it must be (Ship 5):** `services/approval.py`'s `resolve_state(event)` answers `approved`/`pending`/`dismissed`. A stored `state` wins; otherwise a block a *human action* created is approved — a habit you ticked, a checkbox you checked, anything `create_event` wrote — and a machine-inferred one is pending. It keys on the **source system**, not on `completed`: a calendar entry carries `completed` too (Google's green colour, `merger_service.py:279`) while still being intent rather than evidence. The payoff is that the only persisted state rows are calendar and timeline, whose ids come from upstream and are stable — so approval never keys to a `note_line` hash or a `habit_slug`, which is the stale-duplicate trap `events_service.py`'s own comment used to warn about. `state` therefore defaults to **absent**, and a legacy `"suggested"` is dropped on read.
- **A manual event's own origin outlives the calendar's echo (2026-09-12):** `create_event` writes `source: "manual"` and then syncs to Google, which puts a `calendar_id` into `source_ids`. The next merge reads that entry back and matches it, so `reconcile`'s "re-derive from the source" step used to rewrite `source` to `"calendar"` — and since `resolve_state` keys on `source`, every block the user dictated came back **pending**, asking them to approve what they had just said out loud, with `confirmed_minutes` stuck at 0. The same echo imported the `📅 ` prefix `calendar_service.py:465` adds on the way out, so names grew a calendar emoji on their second read. The rule is that a row Mazkir authored has no independent upstream witness: when the persisted event's `source` is `manual`/`photo`, `reconcile` keeps its own `source` **and** `name`. Times and location still track the source, because those a user may genuinely have edited in Google, and `user_set` is what protects a deliberate override. Note that `GET /events/{date}` persists, so a single read of a downgraded day made the loss permanent — the repair is not re-derivable and had to be written back by hand.
- **Coverage is two unions over one block list (Ship 5):** gaps and `unaccounted_minutes` come from **every** drawable block, so a `░` row always means nothing is there at all and can never overlap a pending block; `confirmed_minutes` comes from approved blocks only and is the one number the weekly readout may read. `pending_minutes` subtracts what is already confirmed, so two overlapping blocks of different states never exceed the wall clock. `covered_minutes` keeps its Ship 2 meaning. `day_coverage.py` is unchanged — it is simply called twice.
- **Gap proposals read your own history (Ship 5):** `services/gap_proposals.py` looks at approved blocks in the last 14 date files, keeps those covering at least half the gap, and proposes the most frequent name if it appears on at least 3 distinct days. An overnight gap containing 02:00–05:00 falls back to `Sleep` as a cold-start seed, which history beats once there is any. A refused proposal **reappears** on the next open — deliberately, rather than leaving behind a row whose only purpose is suppression. `✓` on a proposal sends only the interval and the server recomputes the name, so a client can never write a name of its choosing.
- **✕ on a proposal is remembered in the bot, not the vault (2026-09-12):** "writes nothing" and "then re-render" contradicted each other — `prop:dismiss` correctly persisted no tombstone, and `rerender` then recomputed the same proposal and drew it straight back, so the toast said *Skipped* while the row never moved. `src/state/dismissed-proposals.ts` holds the refusal in memory, keyed by chat + date + **interval** (one day can offer the same name for two holes, and refusing one says nothing about the other), with a 30-minute TTL — so it is gone now and free to ask later, which is the agreed behaviour and needs no stored record. Applied in the callback re-render paths (`day-actions.ts`'s `rerender` and the `day:(.+)` nav handler) but **not** in the `/day` command, which is what makes "a later open asks again" true. The gap row itself stays and falls back to `+ Xh`: that time genuinely is unaccounted, and dropping the row would misreport the day.
- **✎ on a proposal banks it, then edits the block (2026-09-12):** the nudge pad needs a block to operate on, and a proposal has none — so `prop:edit` replied with a chat prompt, which made the 5/15/30 view unreachable from a gap and left the user typing. It now calls `gaps/fill` first (no name, so the server still decides it) and opens `buildBlockEditRich` on the block that creates. Tapping ✎ already means "roughly this, let me fix it", so banking the interval takes no decision on the user's behalf: walking away leaves exactly what `✓` would have. A 422 — nothing to propose for that interval — falls back to asking, since there is then no guess to adjust.
- **`days_seen: 0` is a seed, not an observation (2026-09-12):** the overnight fallback returns a count of zero, and the row rendered it as `0/14`, which reads as *never seen this* — evidence against the very guess it labels. It renders `a guess` instead, and a real count only when there is one.
- **Approving a habit block ticks the habit (Ship 5):** one tap confirms the block and pays the tokens, stamped on the **block's** date rather than today. Nothing unticks a habit or retracts tokens — approval is one-way from `/day`, and an approved row carries no buttons at all.
- **In-cell buttons are the only compact ones (Ship 5):** a `<tg-button-row>` inside a `<td>` renders as pills sized to their content; the same row at top level stretches full width, and inside an `<li>` Telegram hoists it out of the list and stretches it. Verified on device — `@grammyjs/types` cannot answer this, because the bot resolves the hoisted root copy at 3.28.0 despite `grammy ^1.46.0`, and that version's rich grammar predates buttons entirely. `/day` therefore puts `[✓][✕][✎]` in each pending row's third column, and the edit view puts its nudge pads in cells.
- **The `/day` glyphs (Ship 5):** `✓` settled · `●` happened, waiting on you · `░` unaccounted · `◌` still ahead, no buttons. `✅`, `⚠` and `⟳` are gone; completion folds into `✓`, because "the source says it was done" is one input to approval rather than approval itself.
- **Block edit drafts live in callback data (Ship 5):** `adj:<date>:<id>:<start_delta>:<end_delta>` carries the whole pending edit in about 40 of Telegram's 64 bytes, so nothing is written until save, there is no server-side edit state to evict, and a button on an old message cannot apply its offsets to something since changed. Each nudge button carries the *accumulated* draft rather than its own step, which is what makes the callback self-sufficient. The date rides along for the same reason the selected date lives in `day:2026-09-10` — a control drawn while browsing a past day must address that day, not today.
- **Approving a checkbox block ticks it wherever it lives (Ship 5):** `services/daily_tasks.py`'s `set_todo_checked(body, text, checked)` flips one checkbox anywhere in the note, matched by its text, as an **in-place single-line edit**. It exists because `MergerService` builds note-derived blocks from `parse_all_todos` — section-agnostic, per Ship 1 — while `daily_set_task_state` parses `parse_tasks_section` and rewrites via `replace_or_append_section(body, "Tasks", …)`, so it can only see and only write the `## Tasks` section. Routing approval through that would have made a timed checkbox under any other heading a tappable block whose ✓ returned 404. The in-place edit is also strictly safer than a whole-section rewrite: approving a block cannot disturb another section's formatting, ordering or annotations. `"not_found"` maps to 404, `"ambiguous"` to 409.
- **A `date` path param is typed, never a raw string (Ship 5):** every `date` in `api/routes/events.py` **and** `api/routes/daily.py` (`get_daily`, `fill_gap`, `approve_all`) is declared `date: date_type` (`daily.py` imports the alias as `dt_date`), so FastAPI rejects anything that is not a real calendar date with a 422 before a handler runs. This is load-bearing rather than tidy: `EventsService._file_path` builds `self.events_path / f"{date}.json"`, so an unvalidated string lets the request path choose a filesystem **write** target via `save_events`. `routes/daily.py` records having made the same change after `?date=../../../../etc/hosts` read an arbitrary file off disk. Note that `_set_state_for_approve_all` and `_fill_gap_for_approve_all` call `set_event_state` / `fill_gap` as direct Python calls rather than over HTTP, so FastAPI's coercion never runs there and each seam converts the string itself — a test pins the `set_event_state` conversion, because every other approve-all test mocks the seam and would not catch its absence.
- New features → add route to vault-server, then add UI in telegram bot or web app

### Agent tool risk levels
- **safe** (read-only): `list_tasks`, `list_habits`, `list_goals`, `get_daily`, `get_tokens`, `search_knowledge`, `read_knowledge`, `get_related`, `read_daily_section`, `list_events` (Ship 4: now merges from calendar/timeline via `day_assembly.merge_from_sources`, so it reaches the network and is not free — still `safe` risk-class since it writes nothing)
- **write** (auto-execute at ≥0.85 confidence): `create_task`, `create_habit`, `create_goal`, `update_task`, `update_habit`, `update_goal`, `save_knowledge`, `attach_to_daily`, `edit_daily_section`, `attach_photo_to_event`, `create_event`, `update_event`, `daily_add_task`, `daily_set_task_state`, `daily_rollover`, `promote_daily_task`, `propose_coding_session` (write tier but `preview: True`, so always confirmed regardless of confidence)
- **destructive** (auto-execute at ≥0.95 confidence): `complete_task`, `complete_habit`, `delete_task`, `archive_task`, `delete_habit`, `archive_goal`, `delete_event`
- Confidence thresholds are per-tool with risk-class defaults: `safe` ungated, `write` ≥0.85, `destructive` ≥0.95.
- Destructive tools always render a preview ("Would delete X / Would archive Y") and require explicit yes/no confirmation before execution, regardless of confidence.

### Observability (P3)

- **Span input/output:** Owned spans (`agent.handle_message`, `agent.loop`, `agent.tool_call`, `skill.<name>`) carry `input.value` and `output.value` attributes (truncated at 2000 chars with a `truncated: true` marker). Visible in Phoenix span detail view.
- **Status propagation:** Manual spans use the `with_span_status` context manager from `services/tracing_helpers.py`. Exceptions are recorded automatically; `agent.tool_call` additionally marks ERROR when the handler returns `ok=False` even without raising.
- **trace_id in logs:** Every structured log record carries a `trace_id` field (when inside an active span context). Grep a log line in `data/logs/vault-server.jsonl`, copy the `trace_id`, and paste it into Phoenix to jump straight to the trace.
- **`agent-turns.jsonl` is memory, not just audit (Ship 3):** `MemoryService.assemble_context` reads this chat's records for today and attaches each turn's calls to the assistant message that turn produced, as `[Tools I called this turn, as <skill>: …]`. The agent therefore reads what it actually did instead of inferring it from its *current* skill's tool list — the failure that made it deny its own writes on 2026-08-20. `services/turn_trace.py` owns reading, rendering and the join; it never raises, so a torn log line costs one trace rather than the turn. The join matches on exact `user_text` walking from the tail, and **a mismatch attaches nothing** — a wrong trace would be a worse version of the bug, arriving dressed as evidence. Deleting `data/logs/` now costs the agent this memory; the prompt invariant ("never deny a past action without checking") is the safety net that holds without it.
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
