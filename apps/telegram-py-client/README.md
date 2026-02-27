# Mazkir Bot - Telegram Interface for Mazkir PKM

A Telegram bot that provides a natural language interface to the [Mazkir Personal Knowledge Management system](https://github.com/MarcellMC/mazkir). Track habits, manage tasks, monitor goals, and earn motivation tokens - all through chat with Claude-powered natural language processing.

## Overview

Mazkir Bot bridges your Telegram messages with your Obsidian vault, allowing you to:

- ✅ **Complete habits** with natural language: "I completed gym"
- 📋 **Create tasks** on the go: "Create task: buy groceries"
- 🎯 **Track goals** with visual progress indicators
- 🪙 **Earn motivation tokens** automatically
- 📆 **Sync to Google Calendar** - habits and tasks appear on your calendar
- 💬 **Chat naturally** with AI assistant powered by Claude
- 📊 **View daily notes**, habit streaks, and task lists

## Relation to Mazkir PKM

This bot is the **Telegram interface** for the [Mazkir PKM system](https://github.com/MarcellMC/mazkir). While the main Mazkir repo contains your Obsidian vault with markdown files, this bot provides:

- **Mobile access** via Telegram
- **Natural language processing** via Claude API
- **Quick logging** of habits and tasks
- **Real-time updates** to your vault files

Both systems work on the same Obsidian vault located at `VAULT_PATH` in your filesystem.

## Features

### Commands

- `/start` - Welcome message and quick guide
- `/day` - View today's daily note with habits, tasks, tokens, and calendar
- `/tasks` - List all active tasks sorted by priority
- `/habits` - Show habit tracker with current streaks
- `/goals` - Display active goals with progress bars
- `/tokens` - Check motivation token balance
- `/calendar` - Show today's schedule from all calendars
- `/sync_calendar` - Sync all habits and tasks to Google Calendar
- `/help` - Full command reference

### Natural Language Processing

Powered by Claude API, the bot understands natural language:

**Habit Completion:**
```
You: I completed review email
Bot: 💪 Excellent! Review Email completed!
     🔥 Streak: 2 → 3 days
     🪙 Tokens: +5
     💰 New balance: 245 tokens
```

**Task Creation:**
```
You: Create task: buy milk for tomorrow
Bot: ✅ Task created: buy milk for tomorrow
     Priority: 🟡 Medium
     Status: Active
```

**Queries:**
```
You: Show my streaks
Bot: 🔥 Your Habit Streaks
     • Review Email: 3 days (best: 12)
     • Review Browser Tabs: 1 days (best: 5)
```

## Technology Stack

- **Bot Framework**: Telethon (Telegram MTProto API)
- **AI**: Claude API (Anthropic)
- **Vault**: Direct filesystem access to Obsidian markdown files
- **Parsing**: python-frontmatter for YAML metadata
- **Language**: Python 3.10+
- **Optional**: LangChain for future multi-LLM support

## Prerequisites

- Python 3.10+
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- Anthropic API Key (from [console.anthropic.com](https://console.anthropic.com))
- Obsidian vault with Mazkir structure (see [Mazkir PKM](https://github.com/MarcellMC/mazkir))

## Setup

### 1. Clone and Install

```bash
git clone https://github.com/MarcellMC/mazkir-bot.git
cd mazkir-bot

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Create Telegram Bot

1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow prompts
3. Save the **bot token** (looks like `123456789:ABCdef...`)

### 3. Get Your Telegram User ID

1. Message [@userinfobot](https://t.me/userinfobot) on Telegram
2. Save your **user ID** (a number)

### 4. Get Anthropic API Key

1. Go to [console.anthropic.com](https://console.anthropic.com/settings/keys)
2. Create a new API key
3. Save it (starts with `sk-ant-...`)

### 5. Configure Environment

```bash
cp .env.example .env
nano .env
```

Required variables:
```bash
# Telegram
TELEGRAM_API_ID=your_api_id          # From https://my.telegram.org
TELEGRAM_API_HASH=your_api_hash      # From https://my.telegram.org
TELEGRAM_PHONE=+1234567890           # Your phone (for session)
TELEGRAM_BOT_TOKEN=123456:ABCdef...  # From @BotFather

# Vault
VAULT_PATH=/home/user/pkm            # Path to your Obsidian vault
VAULT_TIMEZONE=Asia/Jerusalem        # Your timezone
AUTHORIZED_USER_ID=123456789         # Your Telegram user ID

# Claude API
ANTHROPIC_API_KEY=sk-ant-...         # From console.anthropic.com

# Database (optional, for future analytics)
DATABASE_URL=postgresql+asyncpg://...
```

### 6. Run the Bot

```bash
python3 -m src.main
```

You should see:
```
============================================================
✅ Mazkir Bot is running!
============================================================
Bot username: @your_bot
...
```

### 7. Start Chatting

Open Telegram, find your bot, and send `/start`!

## Project Structure

```
mazkir-bot/
├── src/
│   ├── bot/
│   │   └── handlers.py           # Command and message handlers
│   ├── services/
│   │   ├── vault_service.py      # Obsidian vault operations
│   │   ├── claude_service.py     # Claude API integration
│   │   └── calendar_service.py   # Google Calendar integration
│   ├── config.py                 # Configuration
│   └── main.py                   # Entry point
├── tg-mazkir-AGENTS.md          # Architecture documentation
├── tg-mazkir-IMPLEMENTATION.md  # Implementation guide
├── requirements.txt
└── .env.example
```

## Vault Structure

Your Obsidian vault should have this structure:

```
pkm/
├── AGENTS.md                # Vault documentation
├── 00-system/
│   └── motivation-tokens.md # Token ledger
├── 10-daily/
│   └── YYYY-MM-DD.md       # Daily notes
├── 20-habits/
│   └── habit-name.md       # Habit files
├── 30-goals/
│   └── YYYY/
│       └── goal-name.md    # Goal files
└── 40-tasks/
    ├── active/             # Active tasks
    └── archived/           # Archived tasks
```

See [Mazkir PKM](https://github.com/MarcellMC/mazkir) for full vault setup.

## How It Works

### Habit Completion Flow

1. User sends: "I completed gym"
2. Claude parses intent → `HABIT_COMPLETION`
3. Bot matches "gym" to habit file in `20-habits/`
4. Updates: streak, last_completed date
5. Awards tokens based on `tokens_per_completion`
6. Updates `00-system/motivation-tokens.md`
7. Responds with encouragement and stats

### File Updates

All operations directly modify markdown files in your vault:

- **Habits**: Updates frontmatter (streak, last_completed)
- **Tasks**: Creates new `.md` files in `40-tasks/active/`
- **Tokens**: Updates `00-system/motivation-tokens.md`
- **Daily Notes**: Adds entries to `10-daily/YYYY-MM-DD.md`

Changes sync instantly with Obsidian if you have the vault open.

## Development

### Adding New Commands

1. Add handler function in `src/bot/handlers.py`
2. Register in `get_handlers()` function
3. Restart bot

### Adding New Intents

1. Add intent type to `claude_service.py:parse_intent()`
2. Add handler function in `handlers.py`
3. Route intent in `handle_message()`

## Security

- Bot only responds to `AUTHORIZED_USER_ID`
- API keys stored in `.env` (never committed)
- Bot token can be regenerated via @BotFather
- Full filesystem access to vault (run on trusted system)

## Roadmap

- [x] Task completion via natural language
- [x] Google Calendar integration
- [ ] Goal progress updates via NL
- [ ] Notes management via NL
- [ ] Daily/weekly notifications
- [ ] Telegram WebApp for rich UI
- [ ] Photo uploads to daily notes
- [ ] Voice message transcription
- [ ] Weekly review generation

## Contributing

This is a personal project, but feel free to fork and adapt for your own PKM system!

## License

MIT

## Related Projects

- [Mazkir PKM](https://github.com/MarcellMC/mazkir) - The main Obsidian vault and PKM system
- This bot serves as the Telegram interface to that system

---

**Built with Claude Code** 🤖
