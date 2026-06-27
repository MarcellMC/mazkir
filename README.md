# Mazkir - Personal AI Assistant

A personal AI assistant that provides natural language CRUD operations for managing tasks, habits, and goals through a Telegram bot, backed by a FastAPI server and an Obsidian vault.

## Architecture

```
User (Telegram)
     │
     ├──► telegram-bot           TypeScript + grammY (Bot API)
     │        │  HTTP
     │        ▼
     │    vault-server            FastAPI backend (all business logic)
     │        │
     │        ├──► Obsidian vault    Markdown + YAML frontmatter (~/pkm/)
     │        ├──► Claude API        Agent loop + tool-use + memory system
     │        ├──► Google Calendar   Habit/task scheduling
     │        └──► Google Takeout    Location history timeline
     │
     └──► telegram-web-app       React + Vite + Tailwind (Mini App)
              │  HTTP
              ▼
          vault-server
```

## Monorepo Structure

```
~/dev/mazkir/
├── apps/
│   ├── telegram-bot/            # Telegram bot (TypeScript, grammY)
│   ├── vault-server/            # FastAPI REST API (Python)
│   └── telegram-web-app/        # Telegram Mini App (React)
├── packages/
│   └── shared-types/            # @mazkir/shared-types (TypeScript interfaces)
├── memory/                      # Obsidian vault (symlink → ~/pkm/, separate git repo)
├── data/logs/                   # Structured JSON logs + per-turn agent audit
├── infra/observability/         # Local Loki + Alloy + Grafana docker-compose stack
├── docs/plans/                  # Design and migration docs
├── turbo.json                   # Turborepo config
└── CLAUDE.md                    # Detailed project reference
```

## Features

- `/day` - Daily note with habits, tokens, and calendar
- `/tasks` - Active tasks by priority (with inline complete buttons)
- `/habits` - Habit tracker with streaks (with inline complete buttons)
- `/goals` - Goals with progress bars
- `/tokens` - Motivation token balance
- `/calendar` - Today's schedule from Google Calendar
- `/sync_calendar` - Sync habits/tasks to Google Calendar
- Natural language: "I completed gym", "Create task: buy milk", "Done with groceries"
- **Mini App** - Time-management feed (continuous daily-note timeline), AI asset generation playground

## Quick Start

```bash
# Start all apps with Turborepo
npx turbo dev

# Or start individually:
# vault-server (port 8000)
cd apps/vault-server && source venv/bin/activate && python -m uvicorn src.main:app --reload --port 8000

# telegram bot (requires vault-server running)
cd apps/telegram-bot && npx tsx src/index.ts

# telegram web app (requires vault-server running)
cd apps/telegram-web-app && npm run dev

# Run tests
npx turbo test

# Test vault-server endpoints
curl http://localhost:8000/health
curl http://localhost:8000/tasks
curl http://localhost:8000/habits
curl http://localhost:8000/goals
curl http://localhost:8000/daily
curl http://localhost:8000/tokens
```

## Local URLs & Ports

| Service | URL | Port | Notes |
|---------|-----|------|-------|
| vault-server (API) | <http://localhost:8000> | 8000 | FastAPI backend; `/health`, `/docs` |
| telegram-web-app (Mini App) | <http://localhost:5173> | 5173 | Vite dev server (CORS allows `5173` only — pin with `--port 5173 --strictPort` if it drifts) |
| ↳ Time-management feed | <http://localhost:5173/time-management> | | Daily-note timeline; `/` redirects here |
| ↳ Playground | <http://localhost:5173/playground> | | AI asset generation |

The Mini App needs vault-server running on `:8000`. In a plain browser you won't get Telegram theming/SDK context, but both views render standalone for local eyeballing. Override the API base with `VITE_API_BASE` (defaults to `http://localhost:8000`).

Observability ports are listed under [Observability](#observability) below.

## Tech Stack

- **Bot**: grammY (Telegram Bot API) — TypeScript
- **Backend**: FastAPI + uvicorn — Python 3.14+
- **AI**: Claude API (Anthropic SDK) — agent loop with tool-use
- **Data**: Obsidian vault (markdown + YAML frontmatter)
- **Calendar**: Google Calendar API (OAuth2)
- **Web**: React + Vite + Tailwind (Telegram Mini App)
- **Shared Types**: `@mazkir/shared-types` (TypeScript interfaces)
- **Build**: Turborepo monorepo

## Documentation

- [`CLAUDE.md`](CLAUDE.md) - Full project reference (start here for development)
- [`memory/AGENTS.md`](memory/AGENTS.md) - Vault schemas and data formats
- [`personal-ai-assistant-roadmap.md`](personal-ai-assistant-roadmap.md) - Project roadmap
- [`docs/observability.md`](docs/observability.md) - Logs, traces, dashboards

## Observability

Distributed traces are visible in Phoenix by default; Langfuse runs side-by-side via `npx turbo dev:langfuse`.

- Phoenix: <http://localhost:6006>
- Grafana: <http://localhost:3000>
- Loki: <http://localhost:3100>
- Alloy: <http://localhost:12345>
- Audit log: `data/logs/agent-turns.jsonl`

## License

MIT
