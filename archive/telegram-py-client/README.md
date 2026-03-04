# Telegram Client

Thin Telegram UI layer for Mazkir. Receives user messages, calls the [vault-server](../vault-server/) API, and formats responses for Telegram display.

This client contains **no business logic** — all CRUD operations, AI processing, and calendar sync are handled by the vault-server.

## Commands

- `/start` - Welcome message and quick guide
- `/day` - Today's daily note with habits, tokens, and calendar
- `/tasks` - Active tasks sorted by priority
- `/habits` - Habit tracker with streaks
- `/goals` - Active goals with progress bars
- `/tokens` - Motivation token balance
- `/calendar` - Today's schedule from all calendars
- `/sync_calendar` - Sync habits/tasks to Google Calendar
- `/help` - Full command reference

## Natural Language

Powered by Claude API (via vault-server), the bot understands:

```
"I completed gym"          → Habit completion
"Create task: buy milk"    → Task creation
"Done with groceries"      → Task completion
"Create goal: learn piano" → Goal creation
"Show my streaks"          → Query
```

## Project Structure

```
src/
├── main.py           # Bot entrypoint
├── config.py         # Pydantic settings (from .env)
├── api_client.py     # HTTP client for vault-server (httpx)
└── bot/
    ├── client.py     # Telethon client setup
    └── handlers.py   # Command routing → API calls → Telegram formatting
```

## Setup

```bash
cd apps/telegram-py-client
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Environment Variables

Create `.env` in this directory:

```bash
# Telegram (from https://my.telegram.org)
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_PHONE=+1234567890
TELEGRAM_SESSION_NAME=mazkir_bot_session

# Auth
AUTHORIZED_USER_ID=123456789         # Your Telegram user ID

# Vault Server
VAULT_SERVER_URL=http://localhost:8000
VAULT_SERVER_API_KEY=                # Must match vault-server API_KEY
```

## Running

Requires vault-server running on port 8000.

```bash
source venv/bin/activate
python -m src.main
```

## Adding a New Command

1. Add handler function in `src/bot/handlers.py`
2. Add API method in `src/api_client.py` (if new endpoint needed)
3. Register handler in `get_handlers()` at the bottom of handlers.py
4. Format response with emojis for Telegram display

### Telethon Markdown

Telethon uses its own markdown syntax:
- Bold: `**text**`
- Italic: `__text__` (double underscores, not single)
- Code: `` `text` ``
- Link: `[text](url)`
