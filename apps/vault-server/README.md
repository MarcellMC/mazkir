# Vault Server

FastAPI backend for Mazkir. Owns all business logic: Obsidian vault CRUD, Claude AI integration, and Google Calendar sync.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/daily` | Today's daily note with habits and calendar |
| GET | `/tasks` | List active tasks by priority |
| POST | `/tasks` | Create a task |
| PATCH | `/tasks/{name}` | Complete a task |
| GET | `/habits` | List habits with streaks |
| POST | `/habits` | Create a habit |
| PATCH | `/habits/{name}` | Complete a habit |
| GET | `/goals` | List active goals |
| POST | `/goals` | Create a goal |
| GET | `/tokens` | Token balance (total, today, all-time) |
| GET | `/calendar` | Today's Google Calendar events |
| POST | `/calendar/sync` | Sync habits/tasks to Google Calendar |
| POST | `/message` | Natural language intent routing |

## Services

- **VaultService** (`services/vault_service.py`) - Obsidian vault file CRUD (read/write markdown + YAML frontmatter)
- **ClaudeService** (`services/claude_service.py`) - Claude API for intent parsing and NL responses
- **CalendarService** (`services/calendar_service.py`) - Google Calendar OAuth2, event sync, completion marking

## Project Structure

```
src/
├── main.py              # FastAPI app with lifespan, service singletons
├── config.py            # Pydantic settings (from .env)
├── auth.py              # API key middleware (X-API-Key header)
├── api/routes/
│   ├── __init__.py      # Shared helpers (item_name)
│   ├── daily.py         # GET /daily
│   ├── tasks.py         # CRUD /tasks
│   ├── habits.py        # CRUD /habits
│   ├── goals.py         # CRUD /goals
│   ├── tokens.py        # GET /tokens
│   ├── calendar.py      # GET/POST /calendar
│   └── message.py       # POST /message (NL routing)
└── services/
    ├── vault_service.py
    ├── claude_service.py
    └── calendar_service.py
```

## Setup

```bash
cd apps/vault-server
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Environment Variables

Create `.env` in this directory:

```bash
# Vault
VAULT_PATH=/home/user/pkm           # Path to Obsidian vault
VAULT_TIMEZONE=America/Chicago       # Your timezone

# Claude API
ANTHROPIC_API_KEY=sk-ant-...         # From console.anthropic.com

# Auth (optional - empty means no auth)
API_KEY=                             # Shared secret for telegram client

# Google Calendar (optional)
ENABLE_CALENDAR_SYNC=true
GOOGLE_CREDENTIALS_PATH=./google_credentials.json
GOOGLE_TOKEN_PATH=~/.config/mazkir/google_token.json
GOOGLE_CALENDAR_ID=                  # Auto-created if empty
```

## Running

```bash
source venv/bin/activate
python -m uvicorn src.main:app --reload --port 8000
```

Test: `curl http://localhost:8000/health`

## Adding a New Route

1. Create route file in `src/api/routes/`
2. Add service methods if needed
3. Register router in `src/main.py`
