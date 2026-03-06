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
│   │   │       ├── claude_service.py # Claude API (thin wrapper)
│   │   │       ├── memory_service.py # Three-tier memory + graph index
│   │   │       ├── agent_service.py  # Agent loop + tool registry + confidence gate
│   │   │       ├── calendar_service.py # Google Calendar sync
│   │   │       ├── timeline_service.py # Google Takeout parser
│   │   │       ├── merger_service.py   # Event merging + fuzzy matching
│   │   │       ├── events_service.py  # Persisted event storage + merge
│   │   │       ├── exif_service.py   # EXIF metadata extraction (Pillow)
│   │   │       ├── generation_service.py # Replicate image generation
│   │   │       └── imagery_service.py  # Wikimedia Commons geosearch
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
│   │   └── preferences/              # Inferred user patterns
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
│   ├── media/                         # Saved photo attachments ({YYYY-MM-DD}/*.jpg + metadata.json)
│   ├── events/                        # Persisted merged events ({YYYY-MM-DD}.json)
│   └── timeline/                      # Google Takeout Semantic Location History
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
- `/day` - Today's daily note with habits, calendar events, and notes (photo captions)
- `/tasks` - Active tasks by priority
- `/habits` - Habit tracker with streaks
- `/goals` - Goals with progress bars
- `/tokens` - Motivation token balance
- `/calendar` - Today's schedule from Google Calendar
- `/sync_calendar` - Sync habits/tasks to Google Calendar
- NL messages routed through agent loop with conversational context, multi-step actions, and knowledge recall
- Photo messages — downloaded, EXIF extracted (GPS/timestamp/camera), saved to `data/media/` with sidecar `metadata.json`, sent to Claude vision with EXIF context
- Location/venue messages — coordinates passed through agent loop
- Reply-to context and forwarded messages — included as context for the agent

### Telegram Mini App (Web)
- **Dayplanner** - Enriched timeline with date navigation, merging calendar events, Google Takeout location history, habits, and daily notes
- **Playground** - AI asset generation with date navigation (micro icons, route sketches, keyframe scenes, full day maps) using Replicate + Wikimedia Commons imagery

### vault-server API Endpoints
- `POST /message` - Agent loop: `{text, chat_id, attachments?, reply_to?, forwarded_from?}` → multi-turn tool-use with confidence gate + Claude vision
- `POST /message/confirm` - Confirmation for low-confidence actions: `{chat_id, action_id, response}`
- `GET /timeline/{date}` - Google Takeout location history for a date
- `POST /generate` - AI image generation via Replicate (SDXL)
- `GET /events/{date}` - Auto-merges calendar+timeline+habits+daily notes, reconciles with persisted data (preserving photos/assets/manual events), returns enriched events
- `POST /events/{date}/refresh` - Force-refresh events from sources (same as GET, explicit intent)
- `PATCH /events/{date}/{event_id}` - Update a single persisted event
- `GET /imagery/search?lat=&lng=` - Wikimedia Commons geosearch for location imagery

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
- **Agent loop** (`AgentService`) replaces intent-parse-then-route: Claude tool-use with 19 registered tools (incl. `attach_to_daily`, `list_events`, `attach_photo_to_event`, `create_event`), max 10 iterations, confidence-based auto-execute (≥0.85) or human confirmation, Claude vision for photo messages with EXIF context
- **Events persistence** (`EventsService`): merged events stored in `data/events/{date}.json`, supports create/attach/refresh with source-ID matching to preserve photos across re-merges
- **EXIF extraction** (`exif_service`): extracts GPS coordinates, timestamp, camera info from photo EXIF data using Pillow
- **Memory system** (`MemoryService`): short-term (conversation sliding window, 20 messages + decay), mid-term (vault state snapshot in system prompt), long-term (knowledge graph + keyword search)
- **telegram-bot** is a thin TypeScript UI layer (grammY + API calls + inline keyboards + NL routing)
- **telegram-web-app** is a React SPA consuming vault-server REST endpoints
- **@mazkir/shared-types** provides TypeScript interfaces shared between telegram-bot and telegram-web-app
- New features → add route to vault-server, then add UI in telegram bot or web app

### When adding vault-server routes:
1. Create route in `apps/vault-server/src/api/routes/`
2. Add service method to relevant service if needed
3. Register router in `apps/vault-server/src/main.py`

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
