# Telegram Bot Rewrite Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rewrite `apps/telegram-py-client` (Python/Telethon) as `apps/telegram-bot` (TypeScript/grammY) with inline keyboards, Mini App button, and menu button support.

**Architecture:** Thin TypeScript client using grammY (Bot API) calling vault-server REST endpoints. Shared types package (`@mazkir/shared-types`) extracted from existing webapp models, consumed by both the new bot and `telegram-web-app`.

**Tech Stack:** TypeScript, grammY, Vitest, node-fetch (native), dotenv

**Design doc:** `docs/plans/2026-03-02-telegram-bot-rewrite-design.md`

**Reference implementation:** `apps/telegram-py-client/src/bot/handlers.py` (port all formatting logic from here)

---

### Task 1: Create shared types package

**Files:**
- Create: `packages/shared-types/package.json`
- Create: `packages/shared-types/tsconfig.json`
- Create: `packages/shared-types/src/index.ts`
- Create: `packages/shared-types/src/events.ts`
- Create: `packages/shared-types/src/daily.ts`
- Create: `packages/shared-types/src/tokens.ts`
- Create: `packages/shared-types/src/tasks.ts`
- Create: `packages/shared-types/src/habits.ts`
- Create: `packages/shared-types/src/goals.ts`
- Create: `packages/shared-types/src/generation.ts`
- Create: `packages/shared-types/src/message.ts`
- Modify: `package.json` (root) — add `"packages/*"` to workspaces
- Modify: `turbo.json` — add `build` task with dependsOn
- Modify: `apps/telegram-web-app/package.json` — add `@mazkir/shared-types` dependency
- Modify: `apps/telegram-web-app/src/models/event.ts` — replace local types with re-exports from shared
- Modify: `apps/telegram-web-app/src/services/api.ts` — import GenerateRequest/Response/ImageryResult from shared

**Step 1: Create packages/shared-types scaffolding**

`packages/shared-types/package.json`:
```json
{
  "name": "@mazkir/shared-types",
  "version": "0.0.1",
  "private": true,
  "type": "module",
  "main": "./src/index.ts",
  "types": "./src/index.ts",
  "scripts": {
    "build": "tsc --noEmit",
    "lint": "tsc --noEmit"
  },
  "devDependencies": {
    "typescript": "^5.6.0"
  }
}
```

`packages/shared-types/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2020",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "skipLibCheck": true,
    "noEmit": true,
    "isolatedModules": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true
  },
  "include": ["src"]
}
```

**Step 2: Extract types from webapp into shared package**

Move existing types from `apps/telegram-web-app/src/models/event.ts` and `apps/telegram-web-app/src/services/api.ts` into the shared package. Add new types for endpoints the bot uses that the webapp doesn't.

`packages/shared-types/src/events.ts` — copy `MergedEvent`, `MergedEventsResponse` from `apps/telegram-web-app/src/models/event.ts`

`packages/shared-types/src/daily.ts`:
```typescript
export interface HabitStatus {
  name: string;
  completed: boolean;
  streak: number;
}

export interface CalendarEvent {
  id: string;
  summary: string;
  start: string;
  end: string;
  completed: boolean;
  calendar: string;
}

export interface DailyResponse {
  date: string;
  day_of_week: string;
  tokens_earned: number;
  tokens_total: number;
  habits: HabitStatus[];
  calendar_events: CalendarEvent[];
}
```

`packages/shared-types/src/tokens.ts`:
```typescript
export interface TokensResponse {
  total: number;
  today: number;
  all_time: number;
}
```

`packages/shared-types/src/tasks.ts`:
```typescript
export interface Task {
  name: string;
  status: string;
  priority: number;
  due_date?: string;
  category?: string;
}

export interface TasksResponse {
  tasks: Task[];
}
```

`packages/shared-types/src/habits.ts`:
```typescript
export interface Habit {
  name: string;
  frequency: string;
  streak: number;
  last_completed?: string;
  tokens_per_completion: number;
  completed_today: boolean;
}

export interface HabitsResponse {
  habits: Habit[];
}
```

`packages/shared-types/src/goals.ts`:
```typescript
export interface Goal {
  name: string;
  status: string;
  priority: number;
  progress: number;
  target_date?: string;
}

export interface GoalsResponse {
  goals: Goal[];
}
```

`packages/shared-types/src/generation.ts` — move `GenerateRequest`, `GenerateResponse`, `ImageryResult` from `apps/telegram-web-app/src/services/api.ts`

`packages/shared-types/src/message.ts`:
```typescript
export type Intent =
  | "HABIT_COMPLETION"
  | "HABIT_CREATION"
  | "TASK_CREATION"
  | "TASK_COMPLETION"
  | "GOAL_CREATION"
  | "QUERY"
  | "GENERAL_CHAT";

export interface MessageRequest {
  text: string;
  chat_id: number;
}

export interface MessageResponse {
  intent: Intent;
  response: string;
  data?: Record<string, unknown>;
  awaiting_confirmation?: boolean;
  pending_action_id?: string;
}

export interface ConfirmationRequest {
  chat_id: number;
  action_id: string;
  response: string;
}
```

`packages/shared-types/src/index.ts`:
```typescript
export * from "./events.js";
export * from "./daily.js";
export * from "./tokens.js";
export * from "./tasks.js";
export * from "./habits.js";
export * from "./goals.js";
export * from "./generation.js";
export * from "./message.js";
```

**Step 3: Update root workspace and turbo config**

Root `package.json` — change workspaces from `["apps/*"]` to `["apps/*", "packages/*"]`.

`turbo.json` — add build task with dependency ordering:
```json
{
  "$schema": "https://turbo.build/schema.json",
  "tasks": {
    "build": {
      "dependsOn": ["^build"]
    },
    "dev": {
      "cache": false,
      "persistent": true,
      "dependsOn": ["^build"]
    },
    "test": {},
    "lint": {}
  }
}
```

**Step 4: Update webapp to use shared types**

Add `"@mazkir/shared-types": "*"` to `apps/telegram-web-app/package.json` dependencies.

Replace `apps/telegram-web-app/src/models/event.ts` contents with:
```typescript
export type {
  MergedEvent,
  MergedEventsResponse,
  DailyResponse,
  TokensResponse,
  HabitStatus,
  CalendarEvent,
} from "@mazkir/shared-types";
```

Update `apps/telegram-web-app/src/services/api.ts` — import `GenerateRequest`, `GenerateResponse`, `ImageryResult` from `@mazkir/shared-types` instead of defining them locally.

**Step 5: Install and verify**

Run: `cd ~/dev/mazkir && npm install`
Run: `cd ~/dev/mazkir/packages/shared-types && npx tsc --noEmit`
Expected: No errors

Run: `cd ~/dev/mazkir/apps/telegram-web-app && npx tsc -b`
Expected: No errors (webapp compiles with shared types)

Run: `cd ~/dev/mazkir/apps/telegram-web-app && npx vitest run`
Expected: Existing webapp tests still pass

**Step 6: Commit**

```bash
git add packages/shared-types/ package.json turbo.json apps/telegram-web-app/package.json apps/telegram-web-app/src/models/event.ts apps/telegram-web-app/src/services/api.ts package-lock.json
git commit -m "feat: add @mazkir/shared-types package, extract types from webapp"
```

---

### Task 2: Scaffold telegram-bot app

**Files:**
- Create: `apps/telegram-bot/package.json`
- Create: `apps/telegram-bot/tsconfig.json`
- Create: `apps/telegram-bot/src/index.ts`
- Create: `apps/telegram-bot/src/config.ts`
- Create: `apps/telegram-bot/src/bot.ts`
- Create: `apps/telegram-bot/.env.example`

**Step 1: Create package.json**

```json
{
  "name": "telegram-bot",
  "private": true,
  "version": "0.0.1",
  "type": "module",
  "scripts": {
    "dev": "tsx watch src/index.ts",
    "start": "tsx src/index.ts",
    "build": "tsc --noEmit",
    "test": "vitest run",
    "lint": "tsc --noEmit"
  },
  "dependencies": {
    "grammy": "^1.31.0",
    "dotenv": "^16.4.0",
    "@mazkir/shared-types": "*"
  },
  "devDependencies": {
    "typescript": "^5.6.0",
    "tsx": "^4.19.0",
    "vitest": "^2.1.0",
    "@types/node": "^22.0.0"
  }
}
```

**Step 2: Create tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "skipLibCheck": true,
    "noEmit": true,
    "isolatedModules": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "noUncheckedIndexedAccess": true,
    "esModuleInterop": true,
    "resolveJsonModule": true,
    "baseUrl": ".",
    "paths": {
      "@/*": ["src/*"]
    }
  },
  "include": ["src"]
}
```

**Step 3: Create config.ts**

```typescript
import "dotenv/config";

interface Config {
  botToken: string;
  authorizedUserId: number;
  vaultServerUrl: string;
  vaultServerApiKey: string;
  webappUrl: string;
  logLevel: string;
}

function loadConfig(): Config {
  const botToken = process.env.TELEGRAM_BOT_TOKEN;
  const authorizedUserId = Number(process.env.AUTHORIZED_USER_ID);

  if (!botToken) throw new Error("TELEGRAM_BOT_TOKEN is required");
  if (!authorizedUserId || authorizedUserId <= 0)
    throw new Error("AUTHORIZED_USER_ID must be a positive number");

  return {
    botToken,
    authorizedUserId,
    vaultServerUrl: process.env.VAULT_SERVER_URL ?? "http://localhost:8000",
    vaultServerApiKey: process.env.VAULT_SERVER_API_KEY ?? "",
    webappUrl: process.env.WEBAPP_URL ?? "http://localhost:5173",
    logLevel: process.env.LOG_LEVEL ?? "INFO",
  };
}

export const config = loadConfig();
```

**Step 4: Create bot.ts (grammY setup + auth middleware)**

```typescript
import { Bot } from "grammy";
import { config } from "./config.js";

export const bot = new Bot(config.botToken);

// Authorization middleware — reject messages from unauthorized users
bot.use(async (ctx, next) => {
  if (ctx.from?.id !== config.authorizedUserId) {
    return; // silently ignore
  }
  await next();
});
```

**Step 5: Create index.ts (entrypoint)**

```typescript
import { bot } from "./bot.js";

async function main() {
  console.log("Starting Mazkir bot...");
  const me = await bot.api.getMe();
  console.log(`Bot started as @${me.username}`);
  bot.start();
}

main().catch((err) => {
  console.error("Fatal error:", err);
  process.exit(1);
});
```

**Step 6: Create .env.example**

```
TELEGRAM_BOT_TOKEN=
AUTHORIZED_USER_ID=
VAULT_SERVER_URL=http://localhost:8000
VAULT_SERVER_API_KEY=
WEBAPP_URL=http://localhost:5173
LOG_LEVEL=INFO
```

**Step 7: Install and verify bot starts**

Run: `cd ~/dev/mazkir && npm install`
Run: Copy `.env` from `apps/telegram-py-client/.env`, adapting variable names (drop `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE`), save to `apps/telegram-bot/.env`
Run: `cd ~/dev/mazkir/apps/telegram-bot && npx tsx src/index.ts`
Expected: "Bot started as @YourBotName" (then Ctrl+C to stop — no handlers yet)

Note: Use a **test bot token** from BotFather during development to avoid conflicting with the running Python bot.

**Step 8: Commit**

```bash
git add apps/telegram-bot/ package-lock.json
git commit -m "feat: scaffold telegram-bot app (TypeScript + grammY)"
```

---

### Task 3: API client

**Files:**
- Create: `apps/telegram-bot/src/api/client.ts`
- Create: `apps/telegram-bot/tests/api/client.test.ts`

**Step 1: Write the failing test**

`apps/telegram-bot/tests/api/client.test.ts`:
```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock config before importing client
vi.mock("../../src/config.js", () => ({
  config: {
    vaultServerUrl: "http://localhost:8000",
    vaultServerApiKey: "test-key",
  },
}));

const { createApiClient } = await import("../../src/api/client.js");

describe("ApiClient", () => {
  let api: ReturnType<typeof createApiClient>;

  beforeEach(() => {
    api = createApiClient("http://localhost:8000", "test-key");
    vi.restoreAllMocks();
  });

  it("getDaily fetches /daily", async () => {
    const mockResponse = {
      date: "2026-03-02",
      day_of_week: "Monday",
      tokens_earned: 10,
      tokens_total: 100,
      habits: [],
      calendar_events: [],
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(mockResponse), { status: 200 })
    );

    const result = await api.getDaily();
    expect(result).toEqual(mockResponse);
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/daily",
      expect.objectContaining({
        headers: expect.objectContaining({
          "X-API-Key": "test-key",
        }),
      })
    );
  });

  it("completeTask sends PATCH with completed: true", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ success: true }), { status: 200 })
    );

    await api.completeTask("buy-milk");
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/tasks/buy-milk",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ completed: true }),
      })
    );
  });

  it("throws on non-2xx response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("Not found", { status: 404 })
    );

    await expect(api.getDaily()).rejects.toThrow("404");
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd ~/dev/mazkir/apps/telegram-bot && npx vitest run tests/api/client.test.ts`
Expected: FAIL — module `../../src/api/client.js` not found

**Step 3: Implement API client**

`apps/telegram-bot/src/api/client.ts`:
```typescript
import type {
  DailyResponse,
  Task,
  Habit,
  Goal,
  TokensResponse,
  CalendarEvent,
  MessageResponse,
} from "@mazkir/shared-types";

export function createApiClient(baseUrl: string, apiKey: string) {
  async function request<T>(path: string, options?: RequestInit): Promise<T> {
    const res = await fetch(`${baseUrl}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(apiKey ? { "X-API-Key": apiKey } : {}),
        ...options?.headers,
      },
    });
    if (!res.ok) {
      throw new Error(`API error: ${res.status} ${res.statusText}`);
    }
    return res.json() as Promise<T>;
  }

  return {
    // Daily
    getDaily: () => request<DailyResponse>("/daily"),

    // Tasks
    listTasks: () => request<Task[]>("/tasks"),
    createTask: (data: Record<string, unknown>) =>
      request<Task>("/tasks", { method: "POST", body: JSON.stringify(data) }),
    completeTask: (name: string) =>
      request<unknown>(`/tasks/${encodeURIComponent(name)}`, {
        method: "PATCH",
        body: JSON.stringify({ completed: true }),
      }),

    // Habits
    listHabits: () => request<Habit[]>("/habits"),
    createHabit: (data: Record<string, unknown>) =>
      request<Habit>("/habits", { method: "POST", body: JSON.stringify(data) }),
    completeHabit: (name: string) =>
      request<unknown>(`/habits/${encodeURIComponent(name)}`, {
        method: "PATCH",
        body: JSON.stringify({ completed: true }),
      }),

    // Goals
    listGoals: () => request<Goal[]>("/goals"),
    createGoal: (data: Record<string, unknown>) =>
      request<Goal>("/goals", { method: "POST", body: JSON.stringify(data) }),

    // Tokens
    getTokens: () => request<TokensResponse>("/tokens"),

    // Calendar
    getCalendarEvents: () => request<CalendarEvent[]>("/calendar/events"),
    syncCalendar: () =>
      request<Record<string, unknown>>("/calendar/sync", { method: "POST" }),

    // Message (NL)
    sendMessage: (text: string, chatId: number) =>
      request<MessageResponse>("/message", {
        method: "POST",
        body: JSON.stringify({ text, chat_id: chatId }),
      }),
    sendConfirmation: (chatId: number, actionId: string, response: string) =>
      request<MessageResponse>("/message/confirm", {
        method: "POST",
        body: JSON.stringify({
          chat_id: chatId,
          action_id: actionId,
          response,
        }),
      }),
  };
}
```

**Step 4: Run tests**

Run: `cd ~/dev/mazkir/apps/telegram-bot && npx vitest run tests/api/client.test.ts`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add apps/telegram-bot/src/api/ apps/telegram-bot/tests/
git commit -m "feat(telegram-bot): add vault-server API client with tests"
```

---

### Task 4: Response formatters

**Files:**
- Create: `apps/telegram-bot/src/formatters/telegram.ts`
- Create: `apps/telegram-bot/tests/formatters/telegram.test.ts`

**Step 1: Write the failing tests**

`apps/telegram-bot/tests/formatters/telegram.test.ts`:
```typescript
import { describe, it, expect } from "vitest";
import {
  formatDay,
  formatTasks,
  formatHabits,
  formatGoals,
  formatTokens,
  formatCalendar,
  formatTime,
  progressBar,
} from "../../src/formatters/telegram.js";

describe("progressBar", () => {
  it("renders 50% as half filled", () => {
    expect(progressBar(50)).toBe("█████░░░░░");
  });
  it("renders 0%", () => {
    expect(progressBar(0)).toBe("░░░░░░░░░░");
  });
  it("renders 100%", () => {
    expect(progressBar(100)).toBe("██████████");
  });
});

describe("formatTime", () => {
  it("formats ISO datetime to HH:MM", () => {
    expect(formatTime("2026-03-02T14:30:00")).toBe("14:30");
  });
  it("returns 'All day' for date-only strings", () => {
    expect(formatTime("2026-03-02")).toBe("All day");
  });
});

describe("formatTasks", () => {
  it("groups by priority", () => {
    const tasks = [
      { name: "urgent", status: "active", priority: 5 },
      { name: "low", status: "active", priority: 1 },
    ];
    const result = formatTasks(tasks);
    expect(result).toContain("🔴");
    expect(result).toContain("urgent");
    expect(result).toContain("🟢");
    expect(result).toContain("low");
  });
  it("shows empty message when no tasks", () => {
    const result = formatTasks([]);
    expect(result).toContain("No active tasks");
  });
});

describe("formatGoals", () => {
  it("shows progress bar", () => {
    const goals = [
      { name: "learn-rust", status: "active", priority: 4, progress: 70 },
    ];
    const result = formatGoals(goals);
    expect(result).toContain("█");
    expect(result).toContain("70%");
  });
});
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/dev/mazkir/apps/telegram-bot && npx vitest run tests/formatters/telegram.test.ts`
Expected: FAIL — module not found

**Step 3: Implement formatters**

Port all formatting logic from `apps/telegram-py-client/src/bot/handlers.py`. Use HTML parse mode (grammY default, more predictable than MarkdownV2 for special characters).

`apps/telegram-bot/src/formatters/telegram.ts`:
```typescript
import type {
  DailyResponse,
  Task,
  Habit,
  Goal,
  TokensResponse,
  CalendarEvent,
  MessageResponse,
} from "@mazkir/shared-types";

export function progressBar(percent: number, length = 10): string {
  const filled = Math.round((percent / 100) * length);
  return "█".repeat(filled) + "░".repeat(length - filled);
}

export function formatTime(isoString: string): string {
  if (!isoString.includes("T")) return "All day";
  const date = new Date(isoString);
  return date.toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function priorityEmoji(priority: number): string {
  if (priority >= 4) return "🔴";
  if (priority === 3) return "🟡";
  return "🟢";
}

export function formatDay(data: DailyResponse): string {
  const lines: string[] = [];
  lines.push(`📅 <b>Daily Note — ${data.date}</b>`);
  lines.push(`🪙 Tokens today: <b>${data.tokens_earned}</b> | Total: <b>${data.tokens_total}</b>`);
  lines.push("");

  if (data.habits.length > 0) {
    lines.push("💪 <b>Habits</b>");
    for (const h of data.habits) {
      const icon = h.completed ? "✅" : "⏳";
      lines.push(`  ${icon} ${h.name} — 🔥 ${h.streak} day streak`);
    }
    lines.push("");
  }

  if (data.calendar_events.length > 0) {
    lines.push("📆 <b>Schedule</b>");
    for (const e of data.calendar_events) {
      const time = formatTime(e.start);
      const icon = e.completed ? "✅" : "⏳";
      const summary = e.summary.replace(/^✅\s*/, "");
      const cal = e.calendar !== "Mazkir" ? ` (${e.calendar})` : "";
      lines.push(`  ${icon} ${time} — ${summary}${cal}`);
    }
  }

  return lines.join("\n");
}

export function formatTasks(tasks: Task[]): string {
  if (tasks.length === 0) return "📋 No active tasks. Enjoy the calm!";

  const lines: string[] = ["📋 <b>Active Tasks</b>\n"];

  const high = tasks.filter((t) => t.priority >= 4);
  const medium = tasks.filter((t) => t.priority === 3);
  const low = tasks.filter((t) => t.priority <= 2);

  if (high.length > 0) {
    lines.push("🔴 <b>High Priority</b>");
    for (const t of high) lines.push(`  ⏳ ${t.name}${t.due_date ? ` (due ${t.due_date})` : ""}`);
    lines.push("");
  }
  if (medium.length > 0) {
    lines.push("🟡 <b>Medium Priority</b>");
    for (const t of medium) lines.push(`  ⏳ ${t.name}${t.due_date ? ` (due ${t.due_date})` : ""}`);
    lines.push("");
  }
  if (low.length > 0) {
    lines.push("🟢 <b>Low Priority</b>");
    for (const t of low) lines.push(`  ⏳ ${t.name}${t.due_date ? ` (due ${t.due_date})` : ""}`);
  }

  return lines.join("\n");
}

export function formatHabits(habits: Habit[]): string {
  if (habits.length === 0) return "💪 No habits tracked yet.";

  const lines: string[] = ["💪 <b>Habit Tracker</b>\n"];
  for (const h of habits) {
    const icon = h.completed_today ? "✅" : "⏳";
    lines.push(`${icon} <b>${h.name}</b> — 🔥 ${h.streak} day streak`);
  }

  const avgStreak =
    habits.length > 0
      ? Math.round(habits.reduce((s, h) => s + h.streak, 0) / habits.length)
      : 0;
  lines.push(`\n📊 Average streak: <b>${avgStreak} days</b>`);

  return lines.join("\n");
}

export function formatGoals(goals: Goal[]): string {
  if (goals.length === 0) return "🎯 No active goals.";

  const lines: string[] = ["🎯 <b>Goals</b>\n"];
  for (const g of goals) {
    const emoji = priorityEmoji(g.priority);
    const bar = progressBar(g.progress);
    lines.push(`${emoji} <b>${g.name}</b>`);
    lines.push(`   ${bar} ${g.progress}%`);
    if (g.target_date) lines.push(`   📅 Target: ${g.target_date}`);
    lines.push("");
  }

  return lines.join("\n");
}

export function formatTokens(data: TokensResponse): string {
  const lines: string[] = [];
  lines.push("🪙 <b>Motivation Tokens</b>\n");
  lines.push(`💰 Balance: <b>${data.total}</b>`);
  lines.push(`📈 Today: <b>+${data.today}</b>`);
  lines.push(`🏆 All-time: <b>${data.all_time}</b>`);

  // Next milestone
  const milestones = [50, 100, 250, 500, 1000, 2500, 5000];
  const next = milestones.find((m) => m > data.total);
  if (next) {
    lines.push(`\n🎯 Next milestone: <b>${next}</b> (${next - data.total} to go)`);
  }

  return lines.join("\n");
}

export function formatCalendar(events: CalendarEvent[]): string {
  if (events.length === 0) return "📆 No events scheduled today.";

  const lines: string[] = ["📆 <b>Today's Schedule</b>\n"];
  for (const e of events) {
    const time = formatTime(e.start);
    const icon = e.completed ? "✅" : "⏳";
    const summary = e.summary.replace(/^✅\s*/, "");
    const cal = e.calendar !== "Mazkir" ? ` (${e.calendar})` : "";
    lines.push(`${icon} <b>${time}</b> — ${summary}${cal}`);
  }

  return lines.join("\n");
}

export function formatNlResponse(data: MessageResponse): string {
  // For structured intents, format nicely. For general chat, return as-is.
  return data.response;
}
```

**Step 4: Run tests**

Run: `cd ~/dev/mazkir/apps/telegram-bot && npx vitest run tests/formatters/telegram.test.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/telegram-bot/src/formatters/ apps/telegram-bot/tests/formatters/
git commit -m "feat(telegram-bot): add Telegram response formatters with tests"
```

---

### Task 5: Command handlers

**Files:**
- Create: `apps/telegram-bot/src/commands/start.ts`
- Create: `apps/telegram-bot/src/commands/day.ts`
- Create: `apps/telegram-bot/src/commands/tasks.ts`
- Create: `apps/telegram-bot/src/commands/habits.ts`
- Create: `apps/telegram-bot/src/commands/goals.ts`
- Create: `apps/telegram-bot/src/commands/tokens.ts`
- Create: `apps/telegram-bot/src/commands/calendar.ts`
- Create: `apps/telegram-bot/src/commands/sync.ts`
- Create: `apps/telegram-bot/src/commands/help.ts`
- Create: `apps/telegram-bot/src/commands/index.ts`
- Modify: `apps/telegram-bot/src/bot.ts` — register commands

Each command handler is a `Composer` that gets merged into the bot. They call the API client, format the response, and reply with inline keyboards where appropriate.

**Step 1: Create API client singleton**

Add to `apps/telegram-bot/src/api/client.ts` at the bottom:
```typescript
import { config } from "../config.js";

export const api = createApiClient(config.vaultServerUrl, config.vaultServerApiKey);
```

**Step 2: Implement all command handlers**

`apps/telegram-bot/src/commands/start.ts`:
```typescript
import { Composer, InlineKeyboard } from "grammy";
import { config } from "../config.js";

export const startCommand = new Composer();

startCommand.command("start", async (ctx) => {
  const kb = new InlineKeyboard().webApp("🚀 Open App", config.webappUrl);

  await ctx.reply(
    [
      "👋 <b>Welcome to Mazkir!</b>",
      "",
      "Your personal assistant for tasks, habits, and goals.",
      "",
      "Quick commands:",
      "/day — Today's summary",
      "/tasks — Active tasks",
      "/habits — Habit tracker",
      "/goals — Goals & progress",
      "/tokens — Token balance",
      "/calendar — Today's schedule",
      "",
      "Or just type naturally: <i>\"I completed gym\"</i>",
    ].join("\n"),
    { parse_mode: "HTML", reply_markup: kb }
  );
});
```

`apps/telegram-bot/src/commands/day.ts`:
```typescript
import { Composer, InlineKeyboard } from "grammy";
import { api } from "../api/client.js";
import { formatDay } from "../formatters/telegram.js";

export const dayCommand = new Composer();

dayCommand.command("day", async (ctx) => {
  try {
    const data = await api.getDaily();
    const kb = new InlineKeyboard()
      .text("📋 Tasks", "nav:tasks")
      .text("💪 Habits", "nav:habits")
      .row()
      .text("🎯 Goals", "nav:goals")
      .text("📅 Calendar", "nav:calendar");

    await ctx.reply(formatDay(data), { parse_mode: "HTML", reply_markup: kb });
  } catch (err) {
    await ctx.reply("❌ Failed to load daily summary. Is vault-server running?");
  }
});
```

`apps/telegram-bot/src/commands/tasks.ts`:
```typescript
import { Composer, InlineKeyboard } from "grammy";
import { api } from "../api/client.js";
import { formatTasks } from "../formatters/telegram.js";
import type { Task } from "@mazkir/shared-types";

export const tasksCommand = new Composer();

tasksCommand.command("tasks", async (ctx) => {
  try {
    const tasks: Task[] = await api.listTasks();
    const text = formatTasks(tasks);

    const kb = new InlineKeyboard();
    for (const t of tasks.slice(0, 5)) {
      kb.text(`✅ ${t.name}`, `task:complete:${t.name}`).row();
    }

    await ctx.reply(text, { parse_mode: "HTML", reply_markup: kb });
  } catch (err) {
    await ctx.reply("❌ Failed to load tasks.");
  }
});
```

`apps/telegram-bot/src/commands/habits.ts`:
```typescript
import { Composer, InlineKeyboard } from "grammy";
import { api } from "../api/client.js";
import { formatHabits } from "../formatters/telegram.js";
import type { Habit } from "@mazkir/shared-types";

export const habitsCommand = new Composer();

habitsCommand.command("habits", async (ctx) => {
  try {
    const habits: Habit[] = await api.listHabits();
    const text = formatHabits(habits);

    const kb = new InlineKeyboard();
    for (const h of habits.filter((h) => !h.completed_today)) {
      kb.text(`✅ ${h.name}`, `habit:complete:${h.name}`).row();
    }

    await ctx.reply(text, { parse_mode: "HTML", reply_markup: kb });
  } catch (err) {
    await ctx.reply("❌ Failed to load habits.");
  }
});
```

`apps/telegram-bot/src/commands/goals.ts`:
```typescript
import { Composer } from "grammy";
import { api } from "../api/client.js";
import { formatGoals } from "../formatters/telegram.js";
import type { Goal } from "@mazkir/shared-types";

export const goalsCommand = new Composer();

goalsCommand.command("goals", async (ctx) => {
  try {
    const goals: Goal[] = await api.listGoals();
    await ctx.reply(formatGoals(goals), { parse_mode: "HTML" });
  } catch (err) {
    await ctx.reply("❌ Failed to load goals.");
  }
});
```

`apps/telegram-bot/src/commands/tokens.ts`:
```typescript
import { Composer } from "grammy";
import { api } from "../api/client.js";
import { formatTokens } from "../formatters/telegram.js";

export const tokensCommand = new Composer();

tokensCommand.command("tokens", async (ctx) => {
  try {
    const data = await api.getTokens();
    await ctx.reply(formatTokens(data), { parse_mode: "HTML" });
  } catch (err) {
    await ctx.reply("❌ Failed to load tokens.");
  }
});
```

`apps/telegram-bot/src/commands/calendar.ts`:
```typescript
import { Composer } from "grammy";
import { api } from "../api/client.js";
import { formatCalendar } from "../formatters/telegram.js";

export const calendarCommand = new Composer();

calendarCommand.command("calendar", async (ctx) => {
  try {
    const events = await api.getCalendarEvents();
    await ctx.reply(formatCalendar(events), { parse_mode: "HTML" });
  } catch (err) {
    await ctx.reply("❌ Failed to load calendar.");
  }
});
```

`apps/telegram-bot/src/commands/sync.ts`:
```typescript
import { Composer } from "grammy";
import { api } from "../api/client.js";

export const syncCommand = new Composer();

syncCommand.command("sync_calendar", async (ctx) => {
  try {
    const result = await api.syncCalendar();
    await ctx.reply("✅ Calendar synced successfully!", { parse_mode: "HTML" });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "";
    if (msg.includes("503")) {
      await ctx.reply("⚠️ Calendar sync is not configured on the server.");
    } else {
      await ctx.reply("❌ Failed to sync calendar.");
    }
  }
});
```

`apps/telegram-bot/src/commands/help.ts`:
```typescript
import { Composer } from "grammy";

export const helpCommand = new Composer();

helpCommand.command("help", async (ctx) => {
  await ctx.reply(
    [
      "📖 <b>Mazkir Commands</b>",
      "",
      "/day — Today's daily note",
      "/tasks — Active tasks by priority",
      "/habits — Habit tracker with streaks",
      "/goals — Goals with progress bars",
      "/tokens — Motivation token balance",
      "/calendar — Today's schedule",
      "/sync_calendar — Sync to Google Calendar",
      "/help — This message",
      "",
      "<b>Natural Language</b>",
      '<i>"I completed gym"</i> — Mark habit done',
      '<i>"Create task: buy milk"</i> — New task',
      '<i>"Done with groceries"</i> — Complete task',
      '<i>"Show my streaks"</i> — Query data',
    ].join("\n"),
    { parse_mode: "HTML" }
  );
});
```

`apps/telegram-bot/src/commands/index.ts`:
```typescript
export { startCommand } from "./start.js";
export { dayCommand } from "./day.js";
export { tasksCommand } from "./tasks.js";
export { habitsCommand } from "./habits.js";
export { goalsCommand } from "./goals.js";
export { tokensCommand } from "./tokens.js";
export { calendarCommand } from "./calendar.js";
export { syncCommand } from "./sync.js";
export { helpCommand } from "./help.js";
```

**Step 3: Register commands in bot.ts**

Update `apps/telegram-bot/src/bot.ts`:
```typescript
import { Bot } from "grammy";
import { config } from "./config.js";
import {
  startCommand,
  dayCommand,
  tasksCommand,
  habitsCommand,
  goalsCommand,
  tokensCommand,
  calendarCommand,
  syncCommand,
  helpCommand,
} from "./commands/index.js";

export const bot = new Bot(config.botToken);

// Authorization middleware
bot.use(async (ctx, next) => {
  if (ctx.from?.id !== config.authorizedUserId) return;
  await next();
});

// Commands
bot.use(startCommand);
bot.use(dayCommand);
bot.use(tasksCommand);
bot.use(habitsCommand);
bot.use(goalsCommand);
bot.use(tokensCommand);
bot.use(calendarCommand);
bot.use(syncCommand);
bot.use(helpCommand);
```

**Step 4: Verify TypeScript compiles**

Run: `cd ~/dev/mazkir/apps/telegram-bot && npx tsc --noEmit`
Expected: No errors

**Step 5: Commit**

```bash
git add apps/telegram-bot/src/commands/ apps/telegram-bot/src/bot.ts apps/telegram-bot/src/api/client.ts
git commit -m "feat(telegram-bot): add all command handlers with inline keyboards"
```

---

### Task 6: Callback handlers and NL message handler

**Files:**
- Create: `apps/telegram-bot/src/callbacks/index.ts`
- Create: `apps/telegram-bot/src/conversations/message.ts`
- Modify: `apps/telegram-bot/src/bot.ts` — register callbacks and message handler

**Step 1: Implement callback handler**

`apps/telegram-bot/src/callbacks/index.ts`:
```typescript
import { Composer } from "grammy";
import { api } from "../api/client.js";
import { formatTasks, formatHabits, formatCalendar, formatGoals } from "../formatters/telegram.js";

export const callbackHandlers = new Composer();

// Habit completion
callbackHandlers.callbackQuery(/^habit:complete:(.+)$/, async (ctx) => {
  const name = ctx.match[1];
  try {
    await api.completeHabit(name);
    await ctx.answerCallbackQuery({ text: `✅ ${name} completed!` });
    // Refresh the habits list in-place
    const habits = await api.listHabits();
    await ctx.editMessageText(formatHabits(habits), { parse_mode: "HTML" });
  } catch (err) {
    await ctx.answerCallbackQuery({ text: "❌ Failed to complete habit" });
  }
});

// Task completion
callbackHandlers.callbackQuery(/^task:complete:(.+)$/, async (ctx) => {
  const name = ctx.match[1];
  try {
    await api.completeTask(name);
    await ctx.answerCallbackQuery({ text: `✅ ${name} completed!` });
    const tasks = await api.listTasks();
    await ctx.editMessageText(formatTasks(tasks), { parse_mode: "HTML" });
  } catch (err) {
    await ctx.answerCallbackQuery({ text: "❌ Failed to complete task" });
  }
});

// Navigation
callbackHandlers.callbackQuery(/^nav:(.+)$/, async (ctx) => {
  const target = ctx.match[1];
  await ctx.answerCallbackQuery();
  try {
    switch (target) {
      case "tasks": {
        const tasks = await api.listTasks();
        await ctx.editMessageText(formatTasks(tasks), { parse_mode: "HTML" });
        break;
      }
      case "habits": {
        const habits = await api.listHabits();
        await ctx.editMessageText(formatHabits(habits), { parse_mode: "HTML" });
        break;
      }
      case "goals": {
        const goals = await api.listGoals();
        await ctx.editMessageText(formatGoals(goals), { parse_mode: "HTML" });
        break;
      }
      case "calendar": {
        const events = await api.getCalendarEvents();
        await ctx.editMessageText(formatCalendar(events), { parse_mode: "HTML" });
        break;
      }
    }
  } catch (err) {
    await ctx.editMessageText("❌ Failed to load data.");
  }
});

// Catch-all for unknown callbacks
callbackHandlers.on("callback_query:data", async (ctx) => {
  await ctx.answerCallbackQuery();
});
```

**Step 2: Implement NL message handler**

`apps/telegram-bot/src/conversations/message.ts`:
```typescript
import { Composer } from "grammy";
import { api } from "../api/client.js";

// Pending confirmations: chatId -> actionId
const pendingConfirmations = new Map<number, string>();

export const messageHandler = new Composer();

messageHandler.on("message:text", async (ctx) => {
  const text = ctx.message.text;
  const chatId = ctx.chat.id;

  // Skip commands (already handled)
  if (text.startsWith("/")) return;

  try {
    await ctx.replyWithChatAction("typing");

    let response;
    const pendingActionId = pendingConfirmations.get(chatId);
    if (pendingActionId) {
      pendingConfirmations.delete(chatId);
      response = await api.sendConfirmation(chatId, pendingActionId, text);
    } else {
      response = await api.sendMessage(text, chatId);
    }

    if (response.awaiting_confirmation && response.pending_action_id) {
      pendingConfirmations.set(chatId, response.pending_action_id);
    }

    await ctx.reply(response.response, { parse_mode: "HTML" });
  } catch (err) {
    await ctx.reply("❌ Something went wrong. Is vault-server running?");
  }
});
```

**Step 3: Register in bot.ts**

Add to `apps/telegram-bot/src/bot.ts` after command registrations:
```typescript
import { callbackHandlers } from "./callbacks/index.js";
import { messageHandler } from "./conversations/message.js";

// ... after command .use() calls ...

// Callbacks (inline keyboard buttons)
bot.use(callbackHandlers);

// NL message handler (catch-all, must be last)
bot.use(messageHandler);
```

**Step 4: Verify TypeScript compiles**

Run: `cd ~/dev/mazkir/apps/telegram-bot && npx tsc --noEmit`
Expected: No errors

**Step 5: Commit**

```bash
git add apps/telegram-bot/src/callbacks/ apps/telegram-bot/src/conversations/ apps/telegram-bot/src/bot.ts
git commit -m "feat(telegram-bot): add callback handlers and NL message handler"
```

---

### Task 7: Bot menu button and BotFather commands setup

**Files:**
- Modify: `apps/telegram-bot/src/index.ts` — set commands and menu button on startup

**Step 1: Update index.ts to configure BotFather commands and menu button**

```typescript
import { bot } from "./bot.js";
import { config } from "./config.js";

async function main() {
  // Set bot commands (visible in Telegram menu)
  await bot.api.setMyCommands([
    { command: "day", description: "Today's daily summary" },
    { command: "tasks", description: "Active tasks by priority" },
    { command: "habits", description: "Habit tracker with streaks" },
    { command: "goals", description: "Goals with progress bars" },
    { command: "tokens", description: "Motivation token balance" },
    { command: "calendar", description: "Today's schedule" },
    { command: "sync_calendar", description: "Sync to Google Calendar" },
    { command: "help", description: "Command reference" },
  ]);

  // Set menu button to open Mini App
  await bot.api.setChatMenuButton({
    menu_button: {
      type: "web_app",
      text: "Open App",
      web_app: { url: config.webappUrl },
    },
  });

  console.log("Starting Mazkir bot...");
  const me = await bot.api.getMe();
  console.log(`Bot started as @${me.username}`);
  console.log(`Vault server: ${config.vaultServerUrl}`);
  console.log(`Mini App: ${config.webappUrl}`);

  bot.start();
}

main().catch((err) => {
  console.error("Fatal error:", err);
  process.exit(1);
});
```

**Step 2: Verify it compiles**

Run: `cd ~/dev/mazkir/apps/telegram-bot && npx tsc --noEmit`
Expected: No errors

**Step 3: Manual test**

Run: `cd ~/dev/mazkir/apps/telegram-bot && npx tsx src/index.ts`
Expected: Bot starts, commands appear in Telegram menu, menu button shows "Open App"
Test: Send `/start`, `/day`, `/tasks`, `/habits`, `/help` in Telegram — verify formatted responses
Test: Click inline buttons — verify callbacks work

**Step 4: Commit**

```bash
git add apps/telegram-bot/src/index.ts
git commit -m "feat(telegram-bot): configure BotFather commands and Mini App menu button"
```

---

### Task 8: Integration testing and cleanup

**Files:**
- Modify: `apps/telegram-bot/src/api/client.ts` — adjust types based on actual vault-server responses
- Modify: `apps/telegram-bot/src/formatters/telegram.ts` — fix any formatting mismatches

This task is about running the bot against a live vault-server and fixing any issues.

**Step 1: Start vault-server**

Run: `cd ~/dev/mazkir/apps/vault-server && source venv/bin/activate && python -m uvicorn src.main:app --reload --port 8000`

**Step 2: Start bot with test token**

Run: `cd ~/dev/mazkir/apps/telegram-bot && npx tsx src/index.ts`

**Step 3: Test every command in Telegram**

Test each command and verify output matches the Python bot:
- [ ] `/start` — welcome message with Open App button
- [ ] `/day` — daily summary with navigation buttons
- [ ] `/tasks` — tasks grouped by priority with complete buttons
- [ ] `/habits` — habits with streaks and complete buttons
- [ ] `/goals` — goals with progress bars
- [ ] `/tokens` — token balance with milestone
- [ ] `/calendar` — today's schedule
- [ ] `/sync_calendar` — calendar sync
- [ ] `/help` — command reference
- [ ] NL: "show my tasks" — natural language query
- [ ] NL: "I completed gym" — habit completion
- [ ] Inline button: complete a habit
- [ ] Inline button: complete a task
- [ ] Navigation button: switch from /day to tasks view

**Step 4: Fix any type mismatches**

The shared types are based on reading the Python API. If vault-server returns slightly different shapes (e.g., tasks as `{tasks: [...]}` vs bare array), adjust the API client types accordingly. Inspect actual responses:

Run: `curl http://localhost:8000/tasks | jq`
Run: `curl http://localhost:8000/habits | jq`
Run: `curl http://localhost:8000/goals | jq`
Run: `curl http://localhost:8000/daily | jq`
Run: `curl http://localhost:8000/tokens | jq`

**Step 5: Run all tests**

Run: `cd ~/dev/mazkir && npx turbo test`
Expected: All tests pass (bot tests + webapp tests)

**Step 6: Commit fixes**

```bash
git add -u
git commit -m "fix(telegram-bot): adjust types and formatting for vault-server compatibility"
```

---

### Task 9: Update CLAUDE.md and project docs

**Files:**
- Modify: `CLAUDE.md` — update repository structure, add telegram-bot section, update quick commands

**Step 1: Update CLAUDE.md**

Key changes:
- Add `apps/telegram-bot/` to the repository structure tree
- Add `packages/shared-types/` to the tree
- Update "When adding telegram commands" section for the new TS bot
- Add quick command for starting the new bot: `cd ~/dev/mazkir/apps/telegram-bot && npx tsx src/index.ts`
- Note that `telegram-py-client` is deprecated (kept for reference)

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for TypeScript telegram-bot and shared-types package"
```

---

## Summary

| Task | What | Estimated LOC |
|------|------|---------------|
| 1 | Shared types package + webapp migration | ~200 |
| 2 | Bot app scaffold (config, entrypoint, auth) | ~80 |
| 3 | API client + tests | ~150 |
| 4 | Response formatters + tests | ~200 |
| 5 | All 9 command handlers | ~250 |
| 6 | Callback handlers + NL message handler | ~120 |
| 7 | Menu button + BotFather commands | ~40 |
| 8 | Integration testing + fixes | ~varies |
| 9 | Documentation update | ~50 |
| **Total** | | **~1090** |

Tasks 1-2 are foundational. Tasks 3-4 are independent of each other. Tasks 5-6 depend on 3+4. Task 7 depends on 5. Task 8 depends on all. Task 9 is last.
