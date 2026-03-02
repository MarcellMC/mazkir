# Telegram Bot Rewrite: Python/Telethon → TypeScript/grammY

**Date:** 2026-03-02
**Status:** Approved

## Motivation

The current `telegram-py-client` (653 lines, Python/Telethon) was originally built with Python for ML capabilities. Now that all AI logic lives in `vault-server`, the client is purely a thin presentation layer. The original language rationale no longer applies.

**Goals:**
- Better developer experience (TypeScript types, shared tooling with webapp)
- Ecosystem unification (TS bot + TS webapp = shared types, one toolchain)
- Extensibility for inline keyboards, menus, streaming responses
- Native Turborepo integration (no Python venv friction)

## Decision

**Rewrite in TypeScript using grammY framework, targeting the Bot API.**

Alternatives considered:
- **Go (telebot/gotgbot):** No shared ecosystem, verbose for a thin client, awkward Turborepo integration
- **Python (python-telegram-bot):** Doesn't solve DX or ecosystem unification goals

## Architecture

### New App: `apps/telegram-bot`

```
apps/telegram-bot/
├── src/
│   ├── index.ts              # Bot entrypoint
│   ├── config.ts             # Environment config (dotenv + type-safe)
│   ├── bot.ts                # grammY bot setup, middleware, error handling
│   ├── api/
│   │   └── client.ts         # HTTP client for vault-server (fetch-based)
│   ├── commands/
│   │   ├── start.ts          # /start welcome + Mini App button
│   │   ├── day.ts            # /day daily summary
│   │   ├── tasks.ts          # /tasks listing
│   │   ├── habits.ts         # /habits tracker
│   │   ├── goals.ts          # /goals progress
│   │   ├── tokens.ts         # /tokens balance
│   │   ├── calendar.ts       # /calendar events
│   │   └── sync.ts           # /sync_calendar
│   ├── menus/
│   │   └── main-menu.ts      # Inline keyboard menus
│   ├── conversations/
│   │   └── message.ts        # NL message handling (catch-all)
│   └── formatters/
│       └── telegram.ts       # Response formatting (markdown, progress bars)
├── package.json
├── tsconfig.json
└── .env
```

### Shared Types Package: `packages/shared-types`

```
packages/shared-types/
├── src/
│   ├── index.ts           # Re-exports all types
│   ├── events.ts          # MergedEvent, MergedEventsResponse
│   ├── daily.ts           # DailyResponse, HabitStatus, CalendarEvent
│   ├── tokens.ts          # TokensResponse
│   ├── tasks.ts           # Task, TasksResponse
│   ├── habits.ts          # Habit, HabitsResponse
│   ├── goals.ts           # Goal, GoalsResponse
│   ├── generation.ts      # GenerateRequest, GenerateResponse, ImageryResult
│   └── message.ts         # MessageRequest, MessageResponse, Intent types
├── package.json           # name: "@mazkir/shared-types"
└── tsconfig.json
```

- Pure TypeScript interfaces, no runtime code, zero bundle impact
- Root `package.json` workspaces: `["apps/*", "packages/*"]`
- Both `telegram-bot` and `telegram-web-app` import from `@mazkir/shared-types`

## Features

### Bot Interface

**BotFather Configuration:**
- Command menu via `/setcommands` — same 9 commands as current
- Menu button set to open the Mini App URL via `setChatMenuButton`

**Inline Keyboards:**
- `/day` response: `[📋 Tasks] [💪 Habits] [🎯 Goals] [📅 Calendar]`
- `/tasks` response: per-task `[✅ Complete]` buttons
- `/habits` response: per-habit `[✅ Done]` buttons
- `/start` response: `[🚀 Open App]` WebApp button

**Callback Handlers:**
- `habit:complete:<name>` — marks habit done, edits original message
- `task:complete:<name>` — marks task done, edits original message
- `nav:<command>` — navigation buttons triggering command responses

**Mini App Launch:**
- Inline `WebAppInfo` button from `/start` and as persistent keyboard
- URL configured via `WEBAPP_URL` env var

**Natural Language:**
- Catch-all handler sends to `/message` endpoint
- Formats response based on intent (same as current)

### Streaming Responses (Phase 2)

**Flow:**
```
User sends NL message
  → Bot sends "thinking..." placeholder
  → Bot calls vault-server POST /message/stream (new SSE endpoint)
  → Debounced editMessageText every ~300ms as tokens arrive
  → Final edit with complete response + inline buttons
```

**vault-server changes required:**
- New `POST /message/stream` endpoint returning SSE via `StreamingResponse`
- `claude_service.py` gets `stream_message()` using Anthropic SDK streaming
- SSE events: `{"type": "token", "text": "..."}` and `{"type": "done", "intent": "...", "data": {...}}`

**Bot-side:**
- Native `fetch()` with `ReadableStream` for SSE consumption
- 300ms debounce on `editMessageText` (~3 edits/sec, within Telegram limits)
- Fallback to non-streaming `/message` if stream endpoint unavailable

## Migration Strategy

**Parallel operation:**
1. Build `apps/telegram-bot` alongside `apps/telegram-py-client`
2. Test with separate bot token (BotFather test bot) during development
3. Swap production bot token once feature-complete
4. Remove `apps/telegram-py-client` after validation

**Feature parity checklist:**
- [ ] All 9 commands produce equivalent output
- [ ] NL message handling (intent routing + formatted responses)
- [ ] Inline keyboards (complete habit/task)
- [ ] Mini App button opens webapp
- [ ] Menu button configured
- [ ] Error handling (vault-server down, auth failures)
- [ ] Authorization check (single user ID)

## Testing

- **Framework:** Vitest (consistent with telegram-web-app)
- **Unit tests:** Formatters (pure functions), API client (mocked fetch), callback data parsing
- **No E2E:** Telegram API mocking is fragile and low value for a thin client

## Phasing

**Phase 1 — Rewrite with feature parity:**
- All commands, NL handling, inline keyboards, Mini App button, menu button
- Long polling mode

**Phase 2 — Streaming:**
- vault-server SSE endpoint
- Edit-in-place streaming in bot
- Debounced message updates

**Not in initial scope:**
- Webhook mode (can switch later for production)
- Session/conversation state (grammY conversations plugin — add when needed)
