# Vault Server

FastAPI backend for Mazkir. Owns all business logic: Obsidian vault CRUD, Claude AI agent loop, Google Calendar sync, timeline parsing, event persistence, and image generation.

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
| POST | `/message` | Agent loop: tool-use with confidence gate + Claude vision |
| POST | `/message/confirm` | Confirmation for low-confidence actions |
| GET | `/timeline/{date}` | Google Takeout location history for a date |
| GET | `/events/{date}` | Auto-merges calendar+timeline+habits+daily, persists enriched events |
| POST | `/events/{date}/refresh` | Force-refresh events from sources |
| PATCH | `/events/{date}/{event_id}` | Update a single persisted event |
| POST | `/generate` | AI image generation via Replicate (SDXL) |
| GET | `/imagery/search` | Wikimedia Commons geosearch for location imagery |

## Services

- **VaultService** - Obsidian vault file CRUD (read/write markdown + YAML frontmatter)
- **ClaudeService** - Claude API thin wrapper
- **MemoryService** - Three-tier memory: short-term (conversations), mid-term (vault state), long-term (knowledge graph)
- **AgentService** - Agent loop with tool registry + confidence gate
- **CalendarService** - Google Calendar OAuth2, event sync
- **TimelineService** - Google Takeout Semantic Location History parser
- **MergerService** - Event merging + fuzzy matching across sources
- **EventsService** - Persisted event storage with source-ID reconciliation
- **ExifService** - EXIF metadata extraction (GPS, timestamp, camera) via Pillow
- **GenerationService** - Replicate image generation
- **ImageryService** - Wikimedia Commons geosearch

## Project Structure

```
src/
├── main.py              # FastAPI app with lifespan, service singletons
├── config.py            # Pydantic settings (from .env)
├── auth.py              # API key middleware (X-API-Key header)
├── api/routes/
│   ├── daily.py         # GET /daily
│   ├── tasks.py         # CRUD /tasks
│   ├── habits.py        # CRUD /habits
│   ├── goals.py         # CRUD /goals
│   ├── tokens.py        # GET /tokens
│   ├── calendar.py      # GET/POST /calendar
│   ├── message.py       # POST /message (agent loop)
│   ├── timeline.py      # GET /timeline/{date}
│   ├── events.py        # GET/POST/PATCH /events (unified, auto-refresh)
│   ├── generate.py      # POST /generate
│   └── imagery.py       # GET /imagery/search
└── services/
    ├── vault_service.py
    ├── claude_service.py
    ├── memory_service.py
    ├── agent_service.py
    ├── calendar_service.py
    ├── timeline_service.py
    ├── merger_service.py
    ├── events_service.py
    ├── exif_service.py
    ├── generation_service.py
    └── imagery_service.py
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
