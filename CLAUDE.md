# Mazkir - Personal AI Assistant

## Project Overview

Mazkir is a personal AI assistant system that provides natural language CRUD operations for managing tasks, habits, and goals through a Telegram bot interface, backed by a FastAPI vault server and an Obsidian vault for data storage.

**Architecture:** Turborepo monorepo with two Python apps
**Primary Interface:** Telegram bot (`apps/telegram-py-client`)
**Backend:** FastAPI REST API (`apps/vault-server`)
**Data Layer:** Obsidian vault (`memory/`, symlinked from `~/pkm/`)

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
│   └── vault-server/                  # FastAPI backend (Python)
│       ├── src/
│       │   ├── main.py               # FastAPI app with lifespan
│       │   ├── config.py             # Pydantic settings
│       │   ├── auth.py               # API key middleware
│       │   ├── api/routes/           # REST endpoints
│       │   │   ├── tasks.py
│       │   │   ├── habits.py
│       │   │   ├── goals.py
│       │   │   ├── daily.py
│       │   │   ├── tokens.py
│       │   │   ├── calendar.py
│       │   │   └── message.py        # NL intent routing
│       │   └── services/             # Business logic
│       │       ├── vault_service.py  # Obsidian vault CRUD
│       │       ├── claude_service.py # Claude API integration
│       │       └── calendar_service.py # Google Calendar sync
│       ├── pyproject.toml
│       └── .env
│
├── memory/                            # Obsidian vault (nested git repo, gitignored)
│   ├── AGENTS.md                      # Vault schemas and workflows
│   ├── 00-system/templates/           # Note templates
│   ├── 10-daily/                      # Daily notes
│   ├── 20-habits/                     # Habit files
│   ├── 30-goals/                      # Goal files
│   └── 40-tasks/                      # Task files
│
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

- `/day` - Today's daily note with habits and calendar events
- `/tasks` - Active tasks by priority
- `/habits` - Habit tracker with streaks
- `/goals` - Goals with progress bars
- `/tokens` - Motivation token balance
- `/calendar` - Today's schedule from Google Calendar
- `/sync_calendar` - Sync habits/tasks to Google Calendar
- NL: "I completed gym", "Create task: buy milk", "Done with groceries", etc.

## Data Schemas

All vault files use YAML frontmatter. See `memory/AGENTS.md` for complete schemas.

**Task** (`memory/40-tasks/active/*.md`): type, name, status, priority (1-5), due_date, category
**Habit** (`memory/20-habits/*.md`): type, name, frequency, streak, last_completed, tokens_per_completion
**Goal** (`memory/30-goals/YYYY/*.md`): type, name, status, priority, progress (0-100), target_date

## Development Guidelines

### Architecture
- **vault-server** owns ALL business logic (vault CRUD, Claude AI, calendar sync)
- **telegram-py-client** is a thin UI layer (API calls + Telegram formatting)
- New features → add route to vault-server, add handler formatting to telegram client

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

# Start both with Turborepo
cd ~/dev/mazkir && npx turbo dev

# Check vault structure
ls -la ~/pkm/{10-daily,20-habits,30-goals,40-tasks}

# Test vault-server endpoints
curl http://localhost:8000/health
curl http://localhost:8000/tasks
curl http://localhost:8000/habits
```

## Related Documentation

- **Vault Schemas:** `memory/AGENTS.md`
- **Project Roadmap:** `personal-ai-assistant-roadmap.md`
- **Migration Design:** `docs/plans/2026-02-28-monorepo-migration-design.md`
- **Bot Architecture:** `apps/telegram-py-client/tg-mazkir-AGENTS.md`
