# Mazkir - Personal AI Assistant

## Project Overview

Mazkir is a personal AI assistant system with a Claude tool-use agent loop backed by a three-tier memory system (conversations, vault state, knowledge graph). It manages tasks, habits, goals, and knowledge through natural language via Telegram, with all data stored in an Obsidian vault.

**Architecture:** Turborepo monorepo with two Python apps + one React webapp
**Primary Interface:** Telegram bot (`apps/telegram-py-client`) + Telegram Mini App (`apps/telegram-web-app`)
**Backend:** FastAPI REST API (`apps/vault-server`) with agent loop + memory system
**Data Layer:** Obsidian vault (`memory/`, symlinked from `~/pkm/`) + Google Takeout timeline (`data/timeline/`)

## Repository Structure

```
~/dev/mazkir/                          # Turborepo monorepo
├── apps/
│   ├── telegram-py-client/            # Thin Telegram bot (Python)
│   │   ├── src/
│   │   │   ├── main.py               # Bot entrypoint
│   │   │   ├── bot/handlers.py       # Command routing → API calls
│   │   │   ├── bot/client.py         # Telegram client setup
│   │   │   └── api_client.py         # HTTP client for vault-server
│   │   ├── pyproject.toml
│   │   └── .env
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
│   │   │   │   ├── merged_events.py  # Calendar+timeline+habits merge
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
├── data/                              # External data (gitignored)
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
- `/day` - Today's daily note with habits and calendar events
- `/tasks` - Active tasks by priority
- `/habits` - Habit tracker with streaks
- `/goals` - Goals with progress bars
- `/tokens` - Motivation token balance
- `/calendar` - Today's schedule from Google Calendar
- `/sync_calendar` - Sync habits/tasks to Google Calendar
- NL messages routed through agent loop with conversational context, multi-step actions, and knowledge recall

### Telegram Mini App (Web)
- **Dayplanner** - Enriched timeline merging calendar events, Google Takeout location history, habits, and daily notes
- **Playground** - AI asset generation (micro icons, route sketches, keyframe scenes, full day maps) using Replicate + Wikimedia Commons imagery

### vault-server API Endpoints
- `POST /message` - Agent loop: `{text, chat_id}` → multi-turn tool-use with confidence gate
- `POST /message/confirm` - Confirmation for low-confidence actions: `{chat_id, action_id, response}`
- `GET /timeline/{date}` - Google Takeout location history for a date
- `GET /merged-events/{date}` - Calendar + timeline + habits merged into enriched events
- `POST /generate` - AI image generation via Replicate (SDXL)
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
- **Agent loop** (`AgentService`) replaces intent-parse-then-route: Claude tool-use with 15 registered tools, max 10 iterations, confidence-based auto-execute (≥0.85) or human confirmation
- **Memory system** (`MemoryService`): short-term (conversation sliding window, 20 messages + decay), mid-term (vault state snapshot in system prompt), long-term (knowledge graph + keyword search)
- **telegram-py-client** is a thin UI layer (API calls + Telegram formatting + confirmation routing)
- **telegram-web-app** is a React SPA consuming vault-server REST endpoints
- New features → add route to vault-server, then add UI in telegram client or web app

### When adding vault-server routes:
1. Create route in `apps/vault-server/src/api/routes/`
2. Add service method to relevant service if needed
3. Register router in `apps/vault-server/src/main.py`

### When adding telegram commands:
1. Add handler in `apps/telegram-py-client/src/bot/handlers.py`
2. Add API method in `apps/telegram-py-client/src/api_client.py`
3. Format response for Telegram display

### When modifying vault files:
1. Always update the `updated` field
2. Preserve existing frontmatter fields
3. Use templates from `memory/00-system/templates/`
4. File names: lowercase, hyphens (e.g., `buy-groceries.md`)

## Quick Commands

```bash
# Start vault-server
cd ~/dev/mazkir/apps/vault-server && source venv/bin/activate && python -m uvicorn src.main:app --reload --port 8000

# Start telegram client (requires vault-server running)
cd ~/dev/mazkir/apps/telegram-py-client && source venv/bin/activate && python -m src.main

# Start telegram web app (requires vault-server running)
cd ~/dev/mazkir/apps/telegram-web-app && npm run dev  # http://localhost:5173

# Start all with Turborepo
cd ~/dev/mazkir && npx turbo dev

# Run tests
cd ~/dev/mazkir && npx turbo test          # All apps
cd ~/dev/mazkir/apps/vault-server && source venv/bin/activate && python -m pytest tests/  # Server only
cd ~/dev/mazkir/apps/telegram-web-app && npx vitest run  # Webapp only

# Test vault-server endpoints
curl http://localhost:8000/health
curl http://localhost:8000/tasks
curl http://localhost:8000/merged-events/2026-03-02
```

## Related Documentation

- **Vault Schemas:** `memory/AGENTS.md`
- **Project Roadmap:** `personal-ai-assistant-roadmap.md`
- **Memory System Design:** `docs/plans/2026-03-02-memory-system-design.md`
- **Memory System Plan:** `docs/plans/2026-03-02-memory-system-plan.md`
- **Migration Design:** `docs/plans/2026-02-28-monorepo-migration-design.md`
- **Bot Architecture:** `apps/telegram-py-client/tg-mazkir-AGENTS.md`
- **WebApp Design:** `docs/plans/2026-02-28-telegram-webapp-design.md`
- **WebApp Implementation Plan:** `docs/plans/2026-02-28-telegram-webapp-plan.md`
