---
status: active
last_updated: 2026-02-05
project: Mazkir
version: 0.3.0
---

# Mazkir - Personal AI Assistant

## Project Overview

Mazkir is a personal AI assistant system that provides natural language CRUD operations for managing tasks, habits, and goals through a Telegram bot interface, with data stored in an Obsidian vault.

**Current Phase:** Calendar sync integration
**Primary Interface:** Telegram bot (`tg-mazkir`)
**Data Layer:** Obsidian PKM vault (`pkm/`)

## Repository Structure

```
~/dev/
├── mazkir/              # Project coordination (this repo)
│   ├── CLAUDE.md        # This file - project entry point
│   └── personal-ai-assistant-roadmap.md
│
├── tg-mazkir/           # Telegram bot implementation
│   ├── src/
│   │   ├── bot/handlers.py       # Command and NL handlers
│   │   └── services/
│   │       ├── vault_service.py  # Vault read/write operations
│   │       └── claude_service.py # Claude API integration
│   ├── README.md
│   ├── tg-mazkir-AGENTS.md       # Bot architecture
│   └── tg-mazkir-IMPLEMENTATION.md
│
~/pkm/                   # Obsidian vault (data layer)
├── AGENTS.md            # Vault schemas and workflows
├── 00-system/templates/ # Note templates
├── 10-daily/            # Daily notes
├── 20-habits/           # Habit files
├── 30-goals/            # Goal files
└── 40-tasks/            # Task files
```

## Current Capabilities

### Working
- `/day` - View today's daily note (auto-creates if missing)
- `/tasks` - List active tasks by priority
- `/habits` - Show habit tracker with streaks
- `/goals` - Display active goals with progress
- `/tokens` - Check motivation token balance
- NL habit completion: "I completed gym"
- NL habit creation: "Create habit: morning run"
- NL task creation: "Create task: buy milk"
- NL task completion: "Done with buy groceries"
- NL goal creation: "Create goal: learn python"
- Template-based file creation with full schemas
- Task archival on completion with token awards

### In Development
- Google Calendar sync (habits, tasks with due dates)
- Calendar event viewing in /day

### Planned
- Notes management via `60-knowledge/notes/`
- Weekly/monthly reviews
- Telegram WebApp for visualizations

## Data Schemas

All vault files use YAML frontmatter. See `pkm/AGENTS.md` for complete schemas.

### Quick Reference

**Task** (`40-tasks/active/*.md`):
```yaml
type: task
name: "Task description"
status: active          # active, done, archived
priority: 3             # 1-5 (5=highest)
due_date: 2026-02-10    # optional
category: personal      # work, personal, health, learning
```

**Habit** (`20-habits/*.md`):
```yaml
type: habit
name: "Habit Name"
frequency: daily        # daily, 3x/week, weekly
streak: 0
last_completed: null    # YYYY-MM-DD
status: active
tokens_per_completion: 5
```

**Goal** (`30-goals/YYYY/*.md`):
```yaml
type: goal
name: "Goal Name"
status: in-progress     # not-started, in-progress, completed
priority: high          # high, medium, low
progress: 0             # 0-100
target_date: 2026-06-30
```

## Development Guidelines

### When modifying vault files:
1. Always update the `updated` field
2. Preserve existing frontmatter fields
3. Use templates from `00-system/templates/` for new files
4. File names: lowercase, hyphens (e.g., `buy-groceries.md`)

### When adding bot features:
1. Add handler to `tg-mazkir/src/bot/handlers.py`
2. Add vault operation to `vault_service.py` if needed
3. Update intent parsing in `claude_service.py` if NL
4. Test with real vault

### Priority Order for Development
1. Google Calendar API integration
2. Sync habits/tasks to calendar
3. Show calendar in /day command
4. NL calendar queries

## Quick Commands for Development

```bash
# Start bot
cd ~/dev/tg-mazkir && source venv/bin/activate && python -m src.main

# Check vault structure
ls -la ~/pkm/{10-daily,20-habits,30-goals,40-tasks}

# View recent changes
cd ~/pkm && git log --oneline -10
```

## Related Documentation

- **Bot Architecture:** `~/dev/tg-mazkir/tg-mazkir-AGENTS.md`
- **Vault Schemas:** `~/pkm/AGENTS.md`
- **Project Roadmap:** `~/dev/mazkir/personal-ai-assistant-roadmap.md`
- **Implementation Details:** `~/dev/tg-mazkir/tg-mazkir-IMPLEMENTATION.md`
