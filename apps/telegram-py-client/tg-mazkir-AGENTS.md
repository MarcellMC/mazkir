# AI Agent Instructions for tg-mazkir

**Project:** tg-mazkir - Telegram Bot Interface for Mazkir PKM  
**Version:** 2.0 (Repurposed for Personal AI Assistant)  
**Last Updated:** 2026-01-08  
**Owner:** Marc  

---

## Overview

**tg-mazkir** is a Telegram bot that serves as the mobile/chat interface for the Mazkir Personal Knowledge Management (PKM) system. It provides quick access to daily notes, habits, tasks, and motivation tokens through chat commands and will eventually include a Telegram WebApp for rich visualizations.

### Original Purpose (v1.0)
- Message analyzer for Telegram channels
- Semantic search with vector embeddings
- LLM-powered insights

### New Purpose (v2.0)
- Personal AI Assistant chat interface
- Quick-log commands for habits and tasks
- Daily note viewer and editor
- Token balance and progress tracking
- Telegram WebApp for visualizations

---

## Architecture

### System Components

```
┌─────────────────────────────────────────────┐
│           User (Telegram Client)            │
└──────────────┬──────────────────────────────┘
               │
       ┌───────┴────────┐
       │   tg-mazkir    │
       │  Telegram Bot  │
       │   (Telethon)   │
       └───┬────────┬───┘
           │        │
     ┌─────▼─┐  ┌──▼──────────────┐
     │Claude │  │ Obsidian Vault  │
     │ API   │  │ /home/.../pkm   │
     │(Sonnet│  │ (Direct FS)     │
     └───────┘  └─────────────────┘
```

### Technology Stack

**Existing (Keep):**
- Python 3.10+
- Telethon (MTProto API)
- PostgreSQL with pgvector
- SQLAlchemy 2.0 (async)
- Docker Compose

**New Additions:**
- Anthropic Python SDK (Claude API)
- python-frontmatter (parse vault notes)
- watchdog (optional: watch vault changes)
- Telegram WebApp (HTML/CSS/JS)

**Remove/Deprecate:**
- LangChain (use Anthropic SDK directly)
- Ollama embeddings (not needed for v2.0)
- Message analyzer features (archive for now)

---

## Key Concepts

### 1. Vault Integration

**Vault Location:** `/home/marcellmc/pkm` (configurable via env)

**Access Method:** Direct filesystem access (read/write)
- Bot runs on same machine as vault
- Uses Python to read/write markdown files
- Parses YAML frontmatter for metadata

**Vault Structure:**
```
/home/marcellmc/pkm/
├── AGENTS.md              ← Vault documentation
├── 00-system/
│   ├── motivation-tokens.md
│   └── templates/
├── 10-daily/              ← Daily notes
│   └── YYYY-MM-DD.md
├── 20-habits/             ← Habit files
│   └── [habit-name].md
├── 30-goals/
├── 40-tasks/
│   └── active/
└── 60-knowledge/
```

### 2. Claude Integration

**API Usage:**
- Model: `claude-sonnet-4-20250514`
- Max tokens: 4000 (adjust based on response needs)
- System prompt: Include vault context and user info

**Workflow:**
```python
# User sends message to bot
user_message = "I completed gym"

# Bot calls Claude with vault context
response = claude_client.messages.create(
    model="claude-sonnet-4-20250514",
    system=f"""
You are Marc's Personal AI Assistant.
You have access to his Obsidian vault at {VAULT_PATH}.
Current date: {today}
User's timezone: Asia/Jerusalem

Vault structure: [read from AGENTS.md]
""",
    messages=[{
        "role": "user",
        "content": user_message
    }]
)

# Claude responds with actions
# Bot executes file operations
# Bot sends confirmation to user
```

### 3. Command Architecture

**Two types of commands:**

**A. Slash Commands** (Quick access)
- `/day` - Show today's daily note
- `/tasks` - List active tasks
- `/habits` - Habit tracker summary
- `/tokens` - Token balance

**B. Natural Language** (via Claude)
- "I completed gym" → Update habit, award tokens
- "What's my streak?" → Query habit files
- "Create task: buy groceries" → Create task file

---

## Bot Commands Specification

### `/start`

**Purpose:** Welcome message and bot introduction

**Response:**
```
👋 Welcome to Mazkir!

Your Personal AI Assistant for productivity and motivation.

Quick commands:
/day - Today's note
/tasks - Active tasks
/habits - Habit tracker
/tokens - Token balance
/help - Full command list

Or just chat naturally:
"I completed gym"
"Show my streaks"
"Create task: buy milk"
```

### `/day` - Daily Note Viewer

**Purpose:** Show current daily note with formatting

**Implementation:**
1. Read file: `10-daily/{today}.md`
2. Parse frontmatter
3. Format for Telegram (Markdown)
4. Send as message

**Response Format:**
```
📅 *Tuesday, January 7, 2026*

🪙 *Tokens Today:* 15
💰 *Total Bank:* 245 tokens

🎯 *Daily Habits*
✅ Gym (13 day streak)
✅ Reading
⏳ Meditation

📋 *Tasks*
• Buy groceries (due today)
• File taxes (overdue!)

🍽️ *Food Log*
Breakfast: Oatmeal, coffee
Lunch: Not logged yet
Dinner: Not logged yet

---
[Edit Note] [View Full]
```

**Inline Buttons:**
- `[Edit Note]` → Open in Telegram WebApp editor
- `[View Full]` → Send full markdown content

### `/tasks` - Task List

**Purpose:** Show active tasks sorted by priority

**Implementation:**
1. List files in `40-tasks/active/`
2. Parse frontmatter (priority, due_date, status)
3. Sort by priority (high → low), then due_date
4. Format for display

**Response Format:**
```
📋 *Active Tasks*

🔴 *High Priority*
• File taxes (overdue: 2026-01-05)
• Buy groceries (due today)

🟡 *Medium Priority*
• Update resume
• Schedule dentist

🟢 *Low Priority*
• Read chapter 5
• Organize photos

---
Total: 6 active tasks
[Add Task] [View All]
```

**Inline Buttons:**
- `[Add Task]` → Prompt for task creation
- `[View All]` → Include completed tasks

### `/habits` - Habit Tracker Summary

**Purpose:** Show all active habits with streaks

**Implementation:**
1. List files in `20-habits/` where `status: active`
2. Parse frontmatter (streak, last_completed, tokens_per_completion)
3. Sort by streak (descending)
4. Calculate status (completed today? overdue?)

**Response Format:**
```
💪 *Habit Tracker*

🔥 *Active Streaks*
• Gym: 13 days ✅ (today)
• Reading: 8 days ✅ (today)
• Meditation: 5 days ⏳ (pending)

⚠️ *Broken Streaks*
• Morning pages: Was 12, reset yesterday

📊 *Stats*
Completion rate this week: 85%
Total habits: 4 active
Average streak: 6.5 days

---
[Log Habit] [View Details]
```

**Inline Buttons:**
- `[Log Habit]` → Quick-log interface
- `[View Details]` → Full habit history

### `/tokens` - Token Balance

**Purpose:** Show motivation token balance and recent earnings

**Implementation:**
1. Read `00-system/motivation-tokens.md`
2. Parse frontmatter (total_tokens, tokens_today)
3. Read today's daily note for breakdown
4. Show recent transactions

**Response Format:**
```
🪙 *Motivation Tokens*

💰 *Current Balance:* 245 tokens
📈 *Today's Earnings:* +15 tokens

*Today's Activities:*
09:00 | Gym workout | +10
14:30 | Reading | +5

*This Week:* 87 tokens
*This Month:* 342 tokens
*All Time:* 1,245 tokens

🎯 *Next Milestone*
250 tokens: Unlock weekly review report
(5 tokens away!)

---
[Token History] [Redeem]
```

**Inline Buttons:**
- `[Token History]` → Show weekly/monthly breakdown
- `[Redeem]` → (Future) Token spending UI

### `/help` - Command Reference

**Purpose:** Full command list and usage guide

**Response:**
```
📖 *Mazkir Bot Commands*

*Quick Access*
/day - Today's daily note
/tasks - Your active tasks
/habits - Habit tracker
/tokens - Token balance

*Natural Language*
Just chat naturally! Examples:
• "I completed gym"
• "Show my streaks"
• "Create task: buy milk"
• "What's my progress on learning ML?"

*Settings*
/settings - Configure notifications
/timezone - Set your timezone

*More Info*
/about - About this bot
/privacy - Privacy policy

Need help? Just ask!
```

---

## Natural Language Processing

### Via Claude API

**User Message → Bot Workflow:**

```python
async def handle_message(message):
    """Process natural language message via Claude"""
    
    # 1. Build system prompt with vault context
    system_prompt = f"""
You are Marc's Personal AI Assistant with access to his Obsidian vault.

Current date: {datetime.now().strftime('%Y-%m-%d')}
Current time: {datetime.now().strftime('%H:%M')}
Timezone: Asia/Jerusalem

Vault location: {VAULT_PATH}
Read the AGENTS.md file for vault structure and workflows.

When the user completes an activity:
1. Identify the activity (habit/task/goal)
2. Read the relevant file from the vault
3. Update the file (streak, status, etc.)
4. Calculate tokens earned
5. Update motivation-tokens.md
6. Update today's daily note
7. Respond with encouragement and stats

Available tools:
- read_file(path)
- write_file(path, content)
- list_directory(path)
- parse_frontmatter(content)
- update_frontmatter(content, updates)
"""
    
    # 2. Call Claude
    response = anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        system=system_prompt,
        messages=[{
            "role": "user",
            "content": message.text
        }]
    )
    
    # 3. Parse Claude's response
    # Claude may return:
    # - Text response (send to user)
    # - File operations (execute them)
    # - Multiple steps (execute sequentially)
    
    # 4. Execute file operations
    for action in parse_actions(response):
        if action['type'] == 'update_habit':
            update_habit_file(action['habit'], action['updates'])
        elif action['type'] == 'award_tokens':
            award_tokens(action['amount'], action['activity'])
        # ... etc
    
    # 5. Send response to user
    await message.reply(response.content[0].text)
```

### Example Interactions

**User:** "I completed gym"

**Claude Response:**
```
💪 Excellent! Gym workout completed!

Streak: 12 → 13 days 🔥
Tokens: +10 🪙
New balance: 245 tokens

Keep it up! You're 5 tokens away from unlocking your weekly review report.
```

**Bot Actions (behind the scenes):**
1. Read `20-habits/gym-workout.md`
2. Update: `streak: 13`, `last_completed: 2026-01-07`
3. Update `00-system/motivation-tokens.md`: `+10 tokens`
4. Update `10-daily/2026-01-07.md`: Add to completed_habits
5. Send response

---

**User:** "Create task: buy groceries for dinner, high priority"

**Claude Response:**
```
✅ Task created: Buy groceries for dinner

Priority: High
Category: Personal
Due: Today (inferred)
Tokens on completion: 15

Added to your task list. Use /tasks to view all active tasks.
```

**Bot Actions:**
1. Create `40-tasks/active/buy-groceries-for-dinner.md`
2. Populate frontmatter (priority: 5, due_date: today, etc.)
3. Add to today's daily note task list
4. Send confirmation

---

**User:** "What's my longest streak?"

**Claude Response:**
```
🏆 Your longest streaks:

1. Reading: 42 days (Nov-Dec 2025)
2. Gym: 28 days (Aug-Sep 2025)
3. Meditation: 14 days (current!)

Your current gym streak of 13 days is your second-best this year. Keep going! 💪
```

**Bot Actions:**
1. List all files in `20-habits/`
2. Parse `longest_streak` from each
3. Sort and format
4. Send response

---

## Database Schema Changes

### v2.0 Database Structure

**Existing tables to keep:**
- `messages` (for future message archival feature)
- `alembic_version` (migration tracking)

**New tables to add:**

```sql
-- User settings and preferences
CREATE TABLE users (
    user_id BIGINT PRIMARY KEY,
    telegram_username TEXT,
    timezone TEXT DEFAULT 'Asia/Jerusalem',
    vault_path TEXT DEFAULT '/home/marcellmc/pkm',
    notification_enabled BOOLEAN DEFAULT TRUE,
    notification_time TIME DEFAULT '09:00:00',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Command usage analytics
CREATE TABLE command_logs (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id),
    command TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT NOW(),
    response_time_ms INTEGER,
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT
);

-- Token transactions (mirror vault for analytics)
CREATE TABLE token_transactions (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id),
    timestamp TIMESTAMP DEFAULT NOW(),
    activity TEXT NOT NULL,
    tokens_earned INTEGER NOT NULL,
    balance_after INTEGER NOT NULL,
    source_file TEXT  -- Path to habit/task file
);

-- Habit completion log (for analytics)
CREATE TABLE habit_completions (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id),
    habit_name TEXT NOT NULL,
    completed_at TIMESTAMP DEFAULT NOW(),
    streak INTEGER,
    tokens_earned INTEGER
);
```

**Why keep database when vault is source of truth?**
- Analytics and trends (faster than parsing all markdown)
- Notification scheduling
- Command usage tracking
- Future: Multi-user support

---

## Configuration

### Environment Variables

```bash
# .env

# Telegram Bot
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_PHONE=+972xxxxxxxxx

# Claude API
ANTHROPIC_API_KEY=sk-ant-xxxxx

# Vault
VAULT_PATH=/home/marcellmc/pkm
VAULT_TIMEZONE=Asia/Jerusalem

# Database
DATABASE_URL=postgresql+asyncpg://mazkir:mazkir_dev_password@localhost:5432/mazkir

# Features
ENABLE_WEBAPP=true
ENABLE_NOTIFICATIONS=true
DEBUG=false
```

---

## Project Structure (Updated)

```
tg-mazkir/
├── src/
│   ├── bot/
│   │   ├── client.py              # Telethon client
│   │   ├── handlers.py            # Command handlers (updated)
│   │   └── middleware.py          # Auth, logging middleware
│   │
│   ├── services/
│   │   ├── claude_service.py      # Claude API wrapper (NEW)
│   │   ├── vault_service.py       # Vault read/write (NEW)
│   │   ├── token_service.py       # Token calculations (NEW)
│   │   ├── habit_service.py       # Habit operations (NEW)
│   │   └── task_service.py        # Task operations (NEW)
│   │
│   ├── database/
│   │   ├── models.py              # SQLAlchemy models (updated)
│   │   ├── connection.py          # Database setup
│   │   └── repository.py          # Data access (updated)
│   │
│   ├── webapp/
│   │   ├── static/
│   │   │   ├── css/
│   │   │   │   └── daily-note.css
│   │   │   └── js/
│   │   │       └── daily-note.js
│   │   └── templates/
│   │       └── daily-note.html
│   │
│   ├── utils/
│   │   ├── frontmatter.py         # YAML frontmatter parsing (NEW)
│   │   ├── formatters.py          # Telegram message formatting (NEW)
│   │   └── date_utils.py          # Date/time helpers (NEW)
│   │
│   ├── config.py                  # Configuration (updated)
│   └── main.py                    # Entry point (updated)
│
├── alembic/                       # Database migrations
├── docker/
├── tests/
│   ├── test_vault_service.py
│   ├── test_claude_service.py
│   └── test_handlers.py
│
├── AGENTS.md                      # This file
├── IMPLEMENTATION.md              # Detailed implementation guide
├── docker-compose.yml
├── requirements.txt               # Updated dependencies
└── README.md                      # Updated readme
```

---

## Development Workflow

### Phase 1: Core Bot Commands (Week 1)

**Day 1-2: Setup**
- [ ] Update dependencies in requirements.txt
- [ ] Add Anthropic SDK
- [ ] Add python-frontmatter
- [ ] Create new service files (vault, claude, tokens, habits, tasks)

**Day 3-4: Vault Integration**
- [ ] Implement VaultService (read/write markdown files)
- [ ] Implement frontmatter parsing
- [ ] Test reading daily notes, habits, tasks
- [ ] Test writing updates to files

**Day 5-6: Claude Integration**
- [ ] Implement ClaudeService wrapper
- [ ] Create system prompts with vault context
- [ ] Test natural language processing
- [ ] Implement action parsing and execution

**Day 7: Command Implementation**
- [ ] Implement `/day` command
- [ ] Implement `/tasks` command
- [ ] Implement `/habits` command
- [ ] Implement `/tokens` command
- [ ] Test all commands end-to-end

### Phase 2: Natural Language & Workflows (Week 2)

**Day 8-9: Activity Logging**
- [ ] "I completed [habit]" workflow
- [ ] Token award calculation
- [ ] File updates (habit, tokens, daily note)
- [ ] Response formatting

**Day 10-11: Task Management**
- [ ] "Create task: [description]" workflow
- [ ] Task completion workflow
- [ ] Task editing/deletion

**Day 12-13: Queries**
- [ ] "What's my streak?" query
- [ ] "Show my progress on [goal]" query
- [ ] General vault queries via Claude

**Day 14: Polish**
- [ ] Error handling
- [ ] User feedback messages
- [ ] Rate limiting
- [ ] Testing

### Phase 3: Telegram WebApp (Week 3)

**See WEBAPP.md for detailed specs**

---

## Important Rules for Implementation

### 1. Vault is Source of Truth

- ALWAYS read from vault files for current state
- NEVER cache vault data in memory (files can be edited in Obsidian)
- Database is for analytics only, not source data

### 2. Atomic File Operations

```python
# GOOD: Read, update, write
content = read_file(path)
updated = update_frontmatter(content, changes)
write_file(path, updated)

# BAD: Separate read/write operations
content = read_file(path)
# ... time passes, file could change ...
write_file(path, content)  # May overwrite changes
```

### 3. Frontmatter Preservation

When updating files:
- Parse existing frontmatter
- Update only specified fields
- Preserve all other fields
- Maintain field order when possible
- Always update `updated` timestamp

### 4. Error Handling

```python
try:
    result = vault_service.read_daily_note(today)
except FileNotFoundError:
    # Daily note doesn't exist yet - create from template
    result = vault_service.create_daily_note(today)
except Exception as e:
    # Log error, inform user gracefully
    await message.reply("Sorry, I couldn't access your daily note. Please try again.")
    logger.error(f"Error reading daily note: {e}")
```

### 5. Claude API Best Practices

- Always include current date/time in system prompt
- Include relevant vault files in context (don't send entire vault)
- Use temperature=0.7 for balanced creativity/consistency
- Implement retry logic for API failures
- Cache common responses when possible

### 6. Telegram Best Practices

- Use Markdown formatting (bold, italic, code)
- Keep messages under 4096 characters (split if needed)
- Use inline buttons for actions
- Provide quick reply keyboards where appropriate
- Handle message edits for live updates

---

## Testing Strategy

### Unit Tests

```python
# tests/test_vault_service.py
def test_read_daily_note():
    vault = VaultService(test_vault_path)
    note = vault.read_daily_note("2026-01-07")
    assert note['type'] == 'daily'
    assert 'tokens_total' in note

def test_update_habit_streak():
    vault = VaultService(test_vault_path)
    habit = vault.update_habit("gym", {"streak": 13})
    assert habit['streak'] == 13
    assert habit['last_completed'] == today
```

### Integration Tests

```python
# tests/test_bot_integration.py
async def test_day_command(bot_client):
    response = await bot_client.send_command("/day")
    assert "Tuesday, January 7, 2026" in response.text
    assert "Tokens Today" in response.text

async def test_complete_habit_workflow(bot_client):
    response = await bot_client.send_message("I completed gym")
    assert "Excellent" in response.text
    assert "Streak" in response.text
    assert "+10" in response.text
```

### Manual Test Checklist

- [ ] Send `/start` → Receive welcome message
- [ ] Send `/day` → See today's daily note
- [ ] Send `/tasks` → See active tasks
- [ ] Send `/habits` → See habit tracker
- [ ] Send `/tokens` → See token balance
- [ ] Send "I completed gym" → Habit updated, tokens awarded
- [ ] Check vault files → Changes persisted correctly
- [ ] Restart bot → Data still accessible
- [ ] Edit file in Obsidian → Bot sees changes immediately

---

## Security Considerations

### 1. File System Access

- Bot has full access to vault (read/write)
- Validate all file paths (prevent directory traversal)
- Only access files within VAULT_PATH
- Never execute user-provided code

### 2. API Keys

- Store in .env, never commit to git
- Use environment variables only
- Rotate keys regularly
- Monitor API usage

### 3. User Data

- Vault contains personal data
- Bot should only respond to authorized user (Marc)
- Implement user ID check in middleware
- No logging of message content (only metadata)

### 4. Telegram Security

- Use Telegram's built-in encryption
- Enable 2FA on Telegram account
- Restrict bot to private chat only
- No public channels/groups

---

## Deployment

### Local Development

```bash
# Start services
docker-compose up -d

# Run bot
python -m src.main
```

### Production (Systemd Service)

```ini
# /etc/systemd/system/tg-mazkir.service
[Unit]
Description=Mazkir Telegram Bot
After=network.target postgresql.service

[Service]
Type=simple
User=marcellmc
WorkingDirectory=/home/marcellmc/tg-mazkir
Environment="PATH=/home/marcellmc/tg-mazkir/venv/bin"
ExecStart=/home/marcellmc/tg-mazkir/venv/bin/python -m src.main
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable tg-mazkir
sudo systemctl start tg-mazkir
sudo systemctl status tg-mazkir
```

---

## Next Steps

1. Review this AGENTS.md
2. Read IMPLEMENTATION.md for detailed code specs
3. Implement Phase 1 (Core Commands)
4. Test with real vault
5. Iterate based on usage
6. Implement Phase 2 (Natural Language)
7. Implement Phase 3 (WebApp)

---

## Questions or Issues?

Update this file as the implementation evolves. Document decisions, challenges, and solutions for future reference.

**Last reviewed:** 2026-01-08  
**Next review:** After Phase 1 completion
