# Mazkir - Personal AI Assistant

A personal AI assistant that provides natural language CRUD operations for managing tasks, habits, and goals through a Telegram bot, backed by a FastAPI server and an Obsidian vault.

## Architecture

```
User (Telegram)
     │
     ▼
telegram-py-client        Thin UI layer (Telethon)
     │  HTTP
     ▼
vault-server               FastAPI backend (all business logic)
     │
     ├──► Obsidian vault    Markdown + YAML frontmatter (~/pkm/)
     ├──► Claude API        Intent parsing & NL responses
     └──► Google Calendar   Habit/task scheduling
```

## Monorepo Structure

```
~/dev/mazkir/
├── apps/
│   ├── telegram-py-client/   # Telegram bot (Python, Telethon)
│   └── vault-server/         # FastAPI REST API (Python)
├── memory/                   # Obsidian vault (symlink → ~/pkm/, separate git repo)
├── docs/plans/               # Design and migration docs
├── turbo.json                # Turborepo config
└── CLAUDE.md                 # Detailed project reference
```

## Features

- `/day` - Daily note with habits, tokens, and calendar
- `/tasks` - Active tasks by priority
- `/habits` - Habit tracker with streaks
- `/goals` - Goals with progress bars
- `/tokens` - Motivation token balance
- `/calendar` - Today's schedule from Google Calendar
- `/sync_calendar` - Sync habits/tasks to Google Calendar
- Natural language: "I completed gym", "Create task: buy milk", "Done with groceries"

## Quick Start

```bash
# Start both apps with Turborepo
npx turbo dev

# Or start individually:
# vault-server (port 8000)
cd apps/vault-server && source venv/bin/activate && python -m uvicorn src.main:app --reload --port 8000

# telegram client (requires vault-server running)
cd apps/telegram-py-client && source venv/bin/activate && python -m src.main
```

## Tech Stack

- **Bot**: Telethon (Telegram MTProto API)
- **Backend**: FastAPI + uvicorn
- **AI**: Claude API (Anthropic SDK)
- **Data**: Obsidian vault (markdown + YAML frontmatter)
- **Calendar**: Google Calendar API (OAuth2)
- **Language**: Python 3.14+

## Documentation

- [`CLAUDE.md`](CLAUDE.md) - Full project reference (start here for development)
- [`apps/vault-server/README.md`](apps/vault-server/README.md) - Backend API docs
- [`apps/telegram-py-client/README.md`](apps/telegram-py-client/README.md) - Telegram bot docs
- [`memory/AGENTS.md`](memory/AGENTS.md) - Vault schemas and data formats
- [`personal-ai-assistant-roadmap.md`](personal-ai-assistant-roadmap.md) - Project roadmap

## License

MIT
