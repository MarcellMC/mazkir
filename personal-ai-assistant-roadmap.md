---
title: Mazkir - Personal AI Assistant Roadmap
created: 2026-01-06
updated: 2026-02-26
version: 2.2
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
┌──────────────────────────────────────────────────┐
│              User (Telegram Client)               │
└─────────────────────┬────────────────────────────┘
                      │
          ┌───────────┴───────────┐
          │      tg-mazkir        │
          │    Telegram Bot       │
          │ (NL CRUD Interface)   │
          └───┬───────┬───────┬───┘
              │       │       │
      ┌───────▼───┐ ┌─▼───────▼──┐ ┌──────────────┐
      │ Claude API│ │ Obsidian   │ │ Google       │
      │ (Intent + │ │ Vault      │ │ Calendar     │
      │ Response) │ │ ~/pkm/     │ │ (Scheduling) │
      └───────────┘ └────────────┘ └──────────────┘
```

---

## Progress Overview

### Completed
- [x] Vault structure designed and implemented
- [x] Frontmatter schemas defined (AGENTS.md)
- [x] Telegram bot basic setup (Telethon)
- [x] Claude API integration
- [x] Slash commands: /day, /tasks, /habits, /goals, /tokens
- [x] NL habit completion ("I completed gym")
- [x] NL task creation ("Create task: buy milk")
- [x] Habit streak tracking
- [x] Token award system (basic)
- [x] Template-based file creation (task, habit, goal, daily)
- [x] NL goal creation ("Create goal: learn python")
- [x] NL habit creation ("Create habit: morning run")
- [x] NL task completion ("Done with buy groceries")
- [x] Daily note auto-creation on /day
- [x] Task archival on completion with token awards
- [x] **Google Calendar integration** (2026-02-26)
  - [x] OAuth2 authentication with token persistence
  - [x] Dedicated "Mazkir" calendar (isolated from personal events)
  - [x] Sync habits as recurring events (daily/weekly/3x per week)
  - [x] Sync tasks with due dates as calendar events
  - [x] Mark calendar events complete on habit/task completion
  - [x] `/calendar` command - show today's schedule (all calendars)
  - [x] `/sync_calendar` command - manual full sync
  - [x] `/day` shows integrated calendar view
  - [x] Auto-sync on habit/task creation
  - [x] All-day events for unscheduled habits and date-only tasks

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
~/pkm/
├── AGENTS.md               # Vault documentation
├── 00-system/
│   ├── templates/
│   │   ├── _daily_.md      # ✅ Updated
│   │   ├── _task_.md       # ✅ Updated
│   │   ├── _habit_.md      # ✅ Created
│   │   └── _goal_.md       # ✅ Created
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

**Current:**
- Telegram Bot: Telethon (MTProto)
- AI: Claude API (Anthropic SDK)
- Data: Obsidian (markdown + YAML frontmatter)
- Calendar: Google Calendar API (OAuth2)
- Parsing: python-frontmatter
- Language: Python 3.14+

**Planned:**
- PostgreSQL (analytics, future)
- Docker Compose (database)

---

## Key Decisions

### Decision 1: Telegram as Primary Interface
**Rationale:** Mobile-first, always available, NL input natural in chat context

### Decision 2: Obsidian as Data Layer
**Rationale:** Plain markdown, offline-first, full ownership, powerful linking

### Decision 3: Claude for Intent Parsing
**Rationale:** Flexible NL understanding, can handle ambiguity, easy to extend

### Decision 4: Direct Filesystem Access
**Rationale:** Simplest implementation, no sync issues, instant updates

### Decision 5: Google Calendar for Time Management
**Rationale:** Already in use, good mobile app, integrates with other tools

---

## Success Metrics

- **Daily Use:** Bot used for task/habit logging daily
- **Data Quality:** All activities have proper frontmatter
- **Response Time:** Bot responds within 2 seconds
- **Coverage:** 80% of CRUD operations via NL

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Template/code schema drift | High | Templates are source of truth, validate on write |
| Vault corruption | High | Git version control, daily commits |
| Over-engineering | Medium | MVP first, iterate based on actual use |
| Claude API costs | Low | Cache common responses, use Haiku for parsing |
| Calendar API rate limits | Low | Batch operations, local caching |

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 2.2 | 2026-02-26 | **Calendar sync complete!** Google Calendar integration with OAuth2, recurring events, auto-sync |
| 2.1 | 2026-02-05 | NL CRUD complete, next focus: Calendar sync |
| 2.0 | 2026-02-05 | Major update: reflect current state, templates fixed |
| 1.0 | 2026-01-06 | Initial roadmap |

---

## Quick Links

- **Project Entry:** `~/dev/mazkir/CLAUDE.md`
- **Bot Code:** `~/dev/tg-mazkir/src/`
- **Vault Schemas:** `~/pkm/AGENTS.md`
- **Bot Docs:** `~/dev/tg-mazkir/README.md`
