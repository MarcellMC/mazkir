# Mazkir Monorepo Migration Design

**Date:** 2026-02-28
**Status:** Approved

## Goal

Reorganize Mazkir from three separate locations (`~/dev/mazkir/`, `~/dev/tg-mazkir/`, `~/pkm/`) into a Turborepo monorepo at `~/dev/mazkir/`. Extract vault business logic from the Telegram bot into a standalone REST API server.

## Monorepo Structure

```
~/dev/mazkir/                          # Turborepo monorepo
├── apps/
│   ├── telegram-py-client/            # Thin Telegram bot (Python)
│   │   ├── src/
│   │   │   ├── main.py
│   │   │   ├── bot/handlers.py        # Command routing → API calls
│   │   │   ├── bot/client.py          # Telegram client setup
│   │   │   └── api_client.py          # HTTP client for vault-server
│   │   ├── pyproject.toml
│   │   └── .env
│   │
│   └── vault-server/                  # FastAPI full backend (Python)
│       ├── src/
│       │   ├── main.py
│       │   ├── api/routes/            # REST endpoints
│       │   │   ├── tasks.py
│       │   │   ├── habits.py
│       │   │   ├── goals.py
│       │   │   ├── daily.py
│       │   │   └── calendar.py
│       │   └── services/              # Migrated from tg-mazkir
│       │       ├── vault_service.py
│       │       ├── claude_service.py
│       │       └── calendar_service.py
│       ├── pyproject.toml
│       └── .env
│
├── memory/                            # Obsidian vault (nested git repo, gitignored)
├── docs/plans/
├── turbo.json
├── package.json
├── .gitignore
└── CLAUDE.md
```

**Symlink:** `~/pkm/` → `~/dev/mazkir/memory/`

## GitHub Repo Reorganization

1. Rename `MarcellMC/mazkir` → `MarcellMC/mazkir-memory` (vault data, keeps history)
2. Rename `MarcellMC/mazkir-bot` → `MarcellMC/mazkir` (monorepo, keeps history)

Both repos stay active. No archiving.

## Vault Server (FastAPI REST API)

Full backend owning all business logic. tg-mazkir and future clients (WebApp, CLI, MCP) are thin consumers.

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/daily` | Get today's daily note (auto-create if missing) |
| GET | `/tasks` | List active tasks |
| POST | `/tasks` | Create a task |
| PATCH | `/tasks/{name}` | Update/complete a task |
| GET | `/habits` | List habits with streaks |
| POST | `/habits` | Create a habit |
| PATCH | `/habits/{name}` | Update/complete a habit |
| GET | `/goals` | List goals with progress |
| POST | `/goals` | Create a goal |
| PATCH | `/goals/{name}` | Update a goal |
| GET | `/tokens` | Get token balance |
| POST | `/message` | Natural language → Claude parses intent → executes → returns response |
| POST | `/calendar/sync` | Trigger calendar sync |
| GET | `/calendar/events` | Get upcoming calendar events |

### Auth

Simple API key / shared secret (single-user system).

### Services (migrated from tg-mazkir)

- **vault_service.py** — Obsidian vault file CRUD via python-frontmatter
- **claude_service.py** — Claude API integration, NL intent parsing, system prompt with AGENTS.md context
- **calendar_service.py** — Google Calendar OAuth2, habit/task event sync, IPv4 workaround

## Telegram Client Refactoring

### What stays in telegram-py-client
- Telegram client setup (`client.py`)
- Command handlers — reduced to: parse command → call API → format response
- `@authorized_only` decorator
- Telegram-specific formatting
- `api_client.py` — HTTP client wrapping vault-server calls

### What moves to vault-server
- `vault_service.py` — all vault file operations
- `claude_service.py` — Claude API integration, intent parsing
- `calendar_service.py` — Google Calendar sync
- Business logic (token awards, streak calculation, task archival)

### What gets dropped
- `database/` directory (legacy v1.0, unused)
- `llm_service.py`, `embedding_service.py`, `message_ingestion.py` (if unused)

## Migration Steps

1. **Rename GitHub repos**
   - `MarcellMC/mazkir` → `MarcellMC/mazkir-memory`
   - `MarcellMC/mazkir-bot` → `MarcellMC/mazkir`

2. **Set up monorepo skeleton**
   - In newly-renamed `mazkir` repo: create `apps/`, `turbo.json`, root `package.json`
   - Move existing bot code into `apps/telegram-py-client/`
   - Create empty `apps/vault-server/` with FastAPI scaffold

3. **Move vault into place**
   - Move `~/pkm/` contents to `~/dev/mazkir/memory/`
   - Update `memory/.git` remote URL to `mazkir-memory`
   - Add `memory/` to monorepo `.gitignore`
   - Create symlink `~/pkm/` → `~/dev/mazkir/memory/`

4. **Build vault-server**
   - Scaffold FastAPI app with routes
   - Migrate services from telegram-py-client
   - Create REST endpoints wrapping services

5. **Refactor telegram-py-client**
   - Create `api_client.py` for vault-server HTTP calls
   - Replace direct service calls with API client calls
   - Remove migrated services and legacy database code

6. **Update configuration**
   - Update `CLAUDE.md` for new structure
   - Update `.env` files for both apps
   - Update Obsidian git plugin config if needed

## Tooling

- **Monorepo:** Turborepo (supports future JS/TS WebApp alongside Python apps)
- **Vault server framework:** FastAPI (async Python, matches existing stack)
- **Dependency management:** Each app has its own `pyproject.toml`
- **Vault data:** Nested git repo inside `memory/`, gitignored by monorepo

## Future Considerations

- `packages/` directory for shared Python types when needed
- MCP server interface for vault-server
- Telegram WebApp (JS/TS) as another app in `apps/`
