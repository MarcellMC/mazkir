---
title: Mazkir - Personal AI Assistant Roadmap
created: 2026-01-06
updated: 2026-02-28
version: 2.3
status: active
tags: [project, roadmap, mazkir]
---

# Mazkir - Personal AI Assistant
## Project Roadmap

**Vision:** Natural language interface for personal productivity - manage tasks, habits, goals, and notes through conversational AI.

**Entry Point:** See `CLAUDE.md` for project overview and quick start.

---

## Current Architecture

```
User (Telegram)
     │
     ▼
telegram-py-client        Thin UI layer (Telethon)
     │  HTTP (httpx)
     ▼
vault-server               FastAPI backend (port 8000)
     │
     ├──► Obsidian vault    ~/pkm/ (markdown + YAML frontmatter)
     ├──► Claude API        Intent parsing & NL responses
     └──► Google Calendar   OAuth2, habit/task scheduling
```

**Monorepo:** Turborepo at `~/dev/mazkir/` with two Python apps.

---

## Progress Overview

### Completed
- [x] Vault structure designed and implemented
- [x] Frontmatter schemas defined (AGENTS.md)
- [x] Telegram bot setup (Telethon MTProto)
- [x] Claude API integration for intent parsing
- [x] Slash commands: /day, /tasks, /habits, /goals, /tokens, /calendar, /help
- [x] NL habit completion ("I completed gym")
- [x] NL task creation ("Create task: buy milk")
- [x] NL task completion ("Done with buy groceries")
- [x] NL habit creation ("Create habit: morning run")
- [x] NL goal creation ("Create goal: learn python")
- [x] Habit streak tracking
- [x] Token award system
- [x] Template-based file creation (task, habit, goal, daily)
- [x] Daily note auto-creation on /day
- [x] Task archival on completion with token awards
- [x] **Google Calendar integration** (2026-02-26)
  - [x] OAuth2 authentication with token persistence
  - [x] Dedicated "Mazkir" calendar
  - [x] Sync habits as recurring events
  - [x] Sync tasks with due dates as calendar events
  - [x] Mark calendar events complete on habit/task completion
  - [x] `/calendar` and `/sync_calendar` commands
  - [x] `/day` integrated calendar view
  - [x] Auto-sync on habit/task creation
- [x] **Monorepo migration** (2026-02-28)
  - [x] Turborepo monorepo structure
  - [x] vault-server FastAPI backend (all business logic)
  - [x] telegram-py-client thin UI layer (API calls only)
  - [x] API key auth between client and server

### Current Phase: Polish & Notes

**Priority 1 - Calendar Polish** (optional)
- [ ] NL event creation ("Schedule gym for tomorrow at 6pm")
- [ ] Conflict detection with existing events

**Priority 2 - Notes Management**
- [ ] Create `_note_.md` template
- [ ] Add note creation via NL to `60-knowledge/notes/`
- [ ] Add note search via NL
- [ ] Link notes to tasks/goals

---

### Future: Phase 2 - Analytics & WebApp
- [ ] Weekly review generation
- [ ] Streak visualizations
- [ ] Telegram WebApp dashboard
- [ ] Progress charts

### Future: Phase 3 - Advanced Features
- [ ] Carry forward incomplete tasks to next day
- [ ] Goal milestone tracking
- [ ] Health metrics integration
- [ ] Voice message transcription

---

## Vault Structure

```
~/pkm/  (symlinked from ~/dev/mazkir/memory/)
├── AGENTS.md               # Vault schemas
├── 00-system/
│   ├── templates/          # Note templates
│   └── motivation-tokens.md
├── 10-daily/               # YYYY-MM-DD.md
├── 20-habits/              # habit-name.md
├── 30-goals/
│   ├── 2026/               # Current year goals
│   └── archive/
├── 40-tasks/
│   ├── active/
│   └── archive/
├── 50-health/              # Future
└── 60-knowledge/
    └── notes/              # Future: NL-created notes
```

---

## Tech Stack

- **Bot**: Telethon (Telegram MTProto API)
- **Backend**: FastAPI + uvicorn
- **AI**: Claude API (Anthropic SDK)
- **Data**: Obsidian vault (markdown + YAML frontmatter)
- **Calendar**: Google Calendar API (OAuth2)
- **Build**: Turborepo monorepo
- **Language**: Python 3.14+

---

## Key Decisions

### Decision 1: Telegram as Primary Interface
**Rationale:** Mobile-first, always available, NL input natural in chat context

### Decision 2: Obsidian as Data Layer
**Rationale:** Plain markdown, offline-first, full ownership, powerful linking

### Decision 3: Claude for Intent Parsing
**Rationale:** Flexible NL understanding, can handle ambiguity, easy to extend

### Decision 4: Monorepo with Separate Backend
**Rationale:** Clean separation of concerns, vault-server owns all business logic, telegram client is a thin UI layer. Enables future clients (web, CLI) without duplicating logic.

### Decision 5: Google Calendar for Time Management
**Rationale:** Already in use, good mobile app, integrates with other tools

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 2.3 | 2026-02-28 | Monorepo migration complete, vault-server + thin telegram client |
| 2.2 | 2026-02-26 | Google Calendar integration with OAuth2, recurring events, auto-sync |
| 2.1 | 2026-02-05 | NL CRUD complete |
| 2.0 | 2026-02-05 | Major update: templates, streak tracking, token system |
| 1.0 | 2026-01-06 | Initial roadmap |

---

## Quick Links

- **Project Entry:** `~/dev/mazkir/CLAUDE.md`
- **Vault Server:** `~/dev/mazkir/apps/vault-server/`
- **Telegram Client:** `~/dev/mazkir/apps/telegram-py-client/`
- **Vault Schemas:** `~/pkm/AGENTS.md`
