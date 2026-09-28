# Rich View Navigation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate the two kinds of button in the Telegram bot — navigation *between* views lives in the message's `reply_markup` keyboard; navigation *within* a view lives in the message body.

**Architecture:** `/tasks`, `/habits` and `/goals` currently send HTML `parse_mode` messages whose single `reply_markup` carries both kinds of button at once. A Telegram message has only one `reply_markup`, so the split requires the in-view buttons to move into the message body — which means these views become **rich messages**, as `/day` already is. Each view gains a `build*Rich()` formatter emitting `<tg-button-row>` elements, and its keyboard shrinks to cross-view navigation only.

**Tech Stack:** TypeScript / grammY 1.46 / `@grammyjs/types` 5.0.0 / vitest. Bot only — no server changes.

**Spec:** none. This plan is the specification; the user's requirement is quoted in §1 below.

---

## 1. What the user asked for

> Navigation between views (tasks, habits, goals, day) with keyboard. In-view navigation — in-message buttons (reorganize existing buttons accordingly).

Plus: a "back to day" control on each view, which is satisfied by the cross-view keyboard carrying a `📅 Day` button.

`/day` already follows this rule: its week bar and arrows are in-body `<tg-button-row>` elements, and its `reply_markup` carries only `📋 Tasks` / `💪 Habits` / `🎯 Goals`. This plan brings the other three views into line.

## 2. Read this before writing code

You are working in a repo where several non-obvious things have already caused real damage. None of these are hypothetical.

**Never write to `data/events/`.** It is the user's real event store. A live-verification step during the previous ship overwrote five files with `[]`; one date's data was unrecoverable. Nothing in this plan needs it — the bot never touches it — but do not start the server against it either.

**Never write to any path starting `memory/`.** That is the user's live Obsidian vault, a separate nested git repo, gitignored, and absent from a worktree.

**Never `git add -A`.** `node_modules` symlinks live at the repo root and inside `apps/telegram-bot`. A broad add commits them as tracked symlinks pointing at absolute host paths. Stage named paths only.

**`package-lock.json` is gitignored.** `git add` on it silently does nothing.

**Every commit must typecheck.** A commit that does not build is a bisect hazard. If deleting a formatter breaks its caller, update the caller in the same commit.

## 3. Platform constraints that are easy to get wrong

These were established the hard way during Ship 2. Each cost at least one review round.

**Button labels take plain text only.** `@grammyjs/types@5.0.0`, on `RichMessageButton`:

> *Text of the button. May contain only plain text, RichTextCustomEmoji and RichTextDateTime entities.*

No bold, no italic, no superscript, no font size. `style` offers exactly `"danger"` (red), `"success"` (green), `"primary"` (blue) and `"link"` — there is no other colour. Do not attempt `<b>`, `<sub>` or size markup inside a `<tg-button>`; it will not render.

**`editMessageText` takes rich content as its *first* argument.** The signature is `editMessageText(text: string | InputRichMessage, other?)`, and `rich_message` is *excluded* from `other`. Call `ctx.editMessageText(msg)`, not `ctx.editMessageText("", { rich_message: msg })`.

**"message is not modified" is a no-op, not a failure.** Re-rendering a message with identical content makes Telegram reject the edit. `editRich` already special-cases this (`src/bot-utils/send-rich.ts`) — if it routed through the plain-text fallback instead, the fallback would succeed and permanently strip every in-body button, since they are not in `reply_markup`. When you add new in-body buttons, that protection is what keeps them alive. Do not weaken it.

**The fallback must carry `extra`.** `sendRich` and `editRich` both degrade to plain text if a rich payload is rejected. Both pass `extra` through on the fallback path, because dropping it strips the keyboard and leaves a prompt the user cannot answer. Preserve that when you add call sites.

**Escape all user text.** `escapeHtml` from `src/formatters/telegram.ts` is the right tool — rich messages here are authored as HTML because button syntax has no markdown form. Task names, habit names, goal names and note text are all user-supplied.

## 4. Current state

Every list view follows the same shape today:

```typescript
const text = formatTasks(tasks);            // HTML string
const kb   = buildTasksKeyboard(tasks);     // in-view buttons + a 📅 Day button
await ctx.reply(text, { parse_mode: "HTML", reply_markup: kb });
```

| View | List formatter | Keyboard | In-view callbacks |
|---|---|---|---|
| `/tasks` | `formatTasks` | `buildTasksKeyboard` | `task:view:<slug>` |
| task detail | `formatTaskDetail` | `buildTaskDetailKeyboard` | `task:done:<slug>`, `nav:tasks` |
| `/habits` | `formatHabits` | `buildHabitsKeyboard` | `habit:complete:<name>` |
| `/goals` | `formatGoals` | `buildGoalsKeyboard` | `goal:view:<slug>` |
| goal detail | `formatGoalDetail` | `buildGoalDetailKeyboard` | `nav:goals` |

Each keyboard currently ends with `kb.row().text("📅 Day", "nav:day")` and a comment calling that an interim — those comments come out as part of this work.

`/day` is the reference implementation: `src/formatters/day-rich.ts` builds the body with `<tg-button-row>`, `src/keyboards/day.ts` builds the cross-view keyboard, and `src/commands/day.ts` sends them together.

## 5. A live bug to fix on the way

`callbacks/index.ts`, the `habit:complete:` handler:

```typescript
await ctx.editMessageText(formatHabits(habits), { parse_mode: "HTML" });
```

No `reply_markup`. **Completing a habit strips the keyboard**, so the user loses every button on that message and has to re-issue `/habits`. Task 3 fixes this by construction; do not leave it in place if you reorder the tasks.

## 6. File Structure

**Created:**
- `apps/telegram-bot/src/keyboards/nav.ts` — the one cross-view keyboard builder, parameterised by which view is current
- `apps/telegram-bot/src/formatters/tasks-rich.ts` — `buildTasksRich`, `buildTaskDetailRich`
- `apps/telegram-bot/src/formatters/habits-rich.ts` — `buildHabitsRich`
- `apps/telegram-bot/src/formatters/goals-rich.ts` — `buildGoalsRich`, `buildGoalDetailRich`
- `apps/telegram-bot/tests/formatters/tasks-rich.test.ts`
- `apps/telegram-bot/tests/formatters/habits-rich.test.ts`
- `apps/telegram-bot/tests/formatters/goals-rich.test.ts`

**Modified:**
- `apps/telegram-bot/src/commands/{tasks,habits,goals,day}.ts`
- `apps/telegram-bot/src/callbacks/index.ts`
- `apps/telegram-bot/src/keyboards/{tasks,habits,goals,day}.ts` — the list-button builders are replaced by the rich formatters; the slug helpers stay
- `apps/telegram-bot/src/formatters/telegram.ts` — the five HTML formatters are deleted once nothing calls them
- `CLAUDE.md`

Separate files per view rather than one `views-rich.ts`: each is ~60 lines with its own tests, and `telegram.ts` is already ~260 lines of mixed responsibilities — the pattern this repo is moving away from.

## Global Constraints

- Bot tests: `cd apps/telegram-bot && npx vitest run`. **Baseline: 115 passing (14 files).**
- Server suite must stay at **859 passing** plus one pre-existing `StarletteDeprecationWarning`: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/ -q`. The venv is a symlink; never recreate it.
- Webapp: 21 passing.
- Typechecks, both must be clean: `npx tsc -b packages/shared-types` from the repo root, `npx tsc --noEmit -p tsconfig.json` from `apps/telegram-bot`.
- Every commit typechecks and passes. Conventional prefixes. Each message ends with:
  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  Claude-Session: <this session's URL>
  ```

---

### Task 1: One cross-view keyboard, used everywhere

**Files:**
- Create: `apps/telegram-bot/src/keyboards/nav.ts`
- Modify: `apps/telegram-bot/src/keyboards/day.ts`, `apps/telegram-bot/src/commands/day.ts`, `apps/telegram-bot/src/callbacks/index.ts`
- Test: `apps/telegram-bot/tests/keyboards/nav.test.ts` (new)

**Interfaces:**
- Produces, used by Tasks 2–4: `buildNavKeyboard(current: "day" | "tasks" | "habits" | "goals"): InlineKeyboard`

- [ ] **Step 1: Write the failing test**

Create `apps/telegram-bot/tests/keyboards/nav.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { buildNavKeyboard } from "../../src/keyboards/nav.js";

function labels(kb: ReturnType<typeof buildNavKeyboard>): string[] {
  return kb.inline_keyboard.flat().map((b) => b.text);
}
function data(kb: ReturnType<typeof buildNavKeyboard>): string[] {
  return kb.inline_keyboard.flat().map((b) => ("callback_data" in b ? b.callback_data : ""));
}

describe("buildNavKeyboard", () => {
  it("offers the other three views, never the current one", () => {
    expect(data(buildNavKeyboard("day"))).toEqual(["nav:tasks", "nav:habits", "nav:goals"]);
    expect(data(buildNavKeyboard("tasks"))).toEqual(["nav:day", "nav:habits", "nav:goals"]);
    expect(data(buildNavKeyboard("goals"))).toEqual(["nav:day", "nav:tasks", "nav:habits"]);
  });

  it("keeps a stable order so buttons do not move between views", () => {
    // Day first where present, then tasks, habits, goals — so a given view
    // always sits in the same position and taps become muscle memory.
    expect(labels(buildNavKeyboard("habits"))).toEqual(["📅 Day", "📋 Tasks", "🎯 Goals"]);
  });

  it("fits on one row", () => {
    expect(buildNavKeyboard("day").inline_keyboard).toHaveLength(1);
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd apps/telegram-bot && npx vitest run tests/keyboards/nav.test.ts
```
Expected: FAIL — `src/keyboards/nav.ts` does not exist.

- [ ] **Step 3: Write it**

Create `apps/telegram-bot/src/keyboards/nav.ts`:

```typescript
import { InlineKeyboard } from "grammy";

export type ViewName = "day" | "tasks" | "habits" | "goals";

const VIEWS: { name: ViewName; label: string }[] = [
  { name: "day", label: "📅 Day" },
  { name: "tasks", label: "📋 Tasks" },
  { name: "habits", label: "💪 Habits" },
  { name: "goals", label: "🎯 Goals" },
];

/** The cross-view keyboard: where you can go from here.
 *
 *  This is the ONLY thing that belongs in a view's `reply_markup`. Anything
 *  that navigates *within* a view — opening a task, completing a habit,
 *  changing the day — goes in the message body as a `<tg-button-row>`, so
 *  the two kinds of control stay visually distinct.
 *
 *  The current view is omitted rather than disabled: a button that re-renders
 *  the message you are already looking at makes Telegram reject the edit as
 *  "not modified", which is a no-op the bot then has to special-case. */
export function buildNavKeyboard(current: ViewName): InlineKeyboard {
  const kb = new InlineKeyboard();
  for (const v of VIEWS) {
    if (v.name === current) continue;
    kb.text(v.label, `nav:${v.name}`);
  }
  return kb;
}
```

- [ ] **Step 4: Run it and watch it pass**

```bash
cd apps/telegram-bot && npx vitest run tests/keyboards/nav.test.ts
```
Expected: PASS, 3 tests.

- [ ] **Step 5: Point `/day` at it**

Delete `src/keyboards/day.ts` and replace its uses in `src/commands/day.ts` and in the `day:` handler in `src/callbacks/index.ts` with `buildNavKeyboard("day")`. The rendered keyboard is identical, so no `/day` test should change.

- [ ] **Step 6: Verify and commit**

```bash
cd apps/telegram-bot && npx tsc --noEmit -p tsconfig.json && npx vitest run
git add apps/telegram-bot/src/keyboards/nav.ts apps/telegram-bot/tests/keyboards/nav.test.ts \
        apps/telegram-bot/src/commands/day.ts apps/telegram-bot/src/callbacks/index.ts
git rm apps/telegram-bot/src/keyboards/day.ts
git commit -m "refactor(bot): one cross-view keyboard for every view"
```

---

### Task 2: `/tasks` becomes a rich view

**Files:**
- Create: `apps/telegram-bot/src/formatters/tasks-rich.ts`, `apps/telegram-bot/tests/formatters/tasks-rich.test.ts`
- Modify: `apps/telegram-bot/src/commands/tasks.ts`, `apps/telegram-bot/src/callbacks/index.ts`, `apps/telegram-bot/src/keyboards/tasks.ts`

**Interfaces:**
- Consumes: `buildNavKeyboard` (Task 1); `escapeHtml` from `../formatters/telegram.js`; `taskSlug` from `../keyboards/tasks.js`
- Produces: `buildTasksRich(tasks: Task[]): InputRichMessage<InputFile>`, `buildTaskDetailRich(detail: TaskDetail): InputRichMessage<InputFile>`

- [ ] **Step 1: Write the failing tests**

Create `apps/telegram-bot/tests/formatters/tasks-rich.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { buildTasksRich, buildTaskDetailRich } from "../../src/formatters/tasks-rich.js";

const task = (o: object) => ({
  name: "Order dog food", slug: "order-dog-food", priority: 3,
  status: "active", category: null, due_date: null, ...o,
});
const html = (fn: () => { html?: string }) => fn().html ?? "";

describe("buildTasksRich", () => {
  it("renders one in-body button per task", () => {
    const out = html(() => buildTasksRich([
      task({ name: "Order dog food", slug: "order-dog-food" }),
      task({ name: "Fix the bike", slug: "fix-the-bike" }),
    ] as never));
    expect(out).toContain('data="task:view:order-dog-food"');
    expect(out).toContain('data="task:view:fix-the-bike"');
    expect(out).toContain("<tg-button-row");
  });

  it("escapes task names", () => {
    const out = html(() => buildTasksRich([task({ name: "Email <boss> re R&D" })] as never));
    expect(out).toContain("Email &lt;boss&gt; re R&amp;D");
    expect(out).not.toContain("<boss>");
  });

  it("groups by priority, highest first", () => {
    const out = html(() => buildTasksRich([
      task({ name: "Low", priority: 1 }),
      task({ name: "High", priority: 5 }),
    ] as never));
    expect(out.indexOf("High")).toBeLessThan(out.indexOf("Low"));
  });

  it("says so when there is nothing to do", () => {
    expect(html(() => buildTasksRich([] as never))).toContain("No active tasks");
  });

  it("caps the button rows so the message stays usable", () => {
    const many = Array.from({ length: 20 }, (_, i) =>
      task({ name: `T${i}`, slug: `t-${i}` }));
    const out = html(() => buildTasksRich(many as never));
    const buttons = out.match(/data="task:view:/g) ?? [];
    expect(buttons.length).toBeLessThanOrEqual(8);
    expect(out).toContain("more");
  });
});

describe("buildTaskDetailRich", () => {
  it("puts Complete and Back in the body, not the keyboard", () => {
    const out = html(() => buildTaskDetailRich(
      task({ name: "Order dog food", slug: "order-dog-food" }) as never));
    expect(out).toContain('data="task:done:order-dog-food"');
    expect(out).toContain('data="nav:tasks"');
  });

  it("styles Complete as the affirmative action", () => {
    const out = html(() => buildTaskDetailRich(task({}) as never));
    expect(out).toMatch(/data="task:done:[^"]*" style="success"/);
  });
});
```

- [ ] **Step 2: Run them and watch them fail**

```bash
cd apps/telegram-bot && npx vitest run tests/formatters/tasks-rich.test.ts
```
Expected: FAIL — module not found.

- [ ] **Step 3: Write the formatter**

Create `apps/telegram-bot/src/formatters/tasks-rich.ts`. Model it on `src/formatters/day-rich.ts` — same HTML-authoring approach, same `escapeHtml` discipline.

Read `formatTasks` and `formatTaskDetail` in `src/formatters/telegram.ts` first and carry over their body content (priority grouping, the emoji, the fields shown in the detail view). You are changing where the *buttons* live, not what the message says.

Requirements:
- List: a heading, the grouped task lines, then `<tg-button-row>`s of `task:view:<slug>` buttons. **1–8 buttons per row** is the platform limit — with a cap of 8 buttons total, one row suffices, but if you raise the cap, split rows.
- Cap at 8 buttons; if more tasks exist, say `…and N more` in the body.
- Detail: the task's fields, then a row with `task:done:<slug>` styled `"success"` and `nav:tasks` for back.

- [ ] **Step 4: Run them and watch them pass**

```bash
cd apps/telegram-bot && npx vitest run tests/formatters/tasks-rich.test.ts
```

- [ ] **Step 5: Rewire the command and callbacks**

`src/commands/tasks.ts`:

```typescript
const tasks: Task[] = await api.listTasks();
await sendRich(ctx, buildTasksRich(tasks), { reply_markup: buildNavKeyboard("tasks") });
```

Keep the existing try/catch and its logging. Follow `src/commands/day.ts`'s pattern of separating fetch, render and send failures so each reports its own cause.

In `src/callbacks/index.ts`, the three handlers that render tasks — `nav:tasks`, `task:view:`, `task:done:` — switch to `editRich(ctx, <rich>, { reply_markup: buildNavKeyboard("tasks") })`.

Then delete `buildTasksKeyboard` and `buildTaskDetailKeyboard` from `src/keyboards/tasks.ts`, keeping `taskSlug`.

- [ ] **Step 6: Verify and commit**

```bash
cd apps/telegram-bot && npx tsc --noEmit -p tsconfig.json && npx vitest run
```

Existing tests referencing `buildTasksKeyboard` or `formatTasks` will fail to compile. Update them to the rich equivalents, or delete ones that only asserted the old keyboard's shape — that concept is deliberately gone. Say which you did in your report.

```bash
git add apps/telegram-bot/src/formatters/tasks-rich.ts apps/telegram-bot/tests/formatters/tasks-rich.test.ts \
        apps/telegram-bot/src/commands/tasks.ts apps/telegram-bot/src/callbacks/index.ts \
        apps/telegram-bot/src/keyboards/tasks.ts
git commit -m "feat(bot): /tasks renders in-view buttons in the message body"
```

---

### Task 3: `/habits` becomes a rich view, and stops losing its keyboard

**Files:**
- Create: `apps/telegram-bot/src/formatters/habits-rich.ts`, `apps/telegram-bot/tests/formatters/habits-rich.test.ts`
- Modify: `apps/telegram-bot/src/commands/habits.ts`, `apps/telegram-bot/src/callbacks/index.ts`
- Delete: `apps/telegram-bot/src/keyboards/habits.ts`

**Interfaces:**
- Produces: `buildHabitsRich(habits: Habit[]): InputRichMessage<InputFile>`

- [ ] **Step 1: Write the failing tests**

Create `apps/telegram-bot/tests/formatters/habits-rich.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { buildHabitsRich } from "../../src/formatters/habits-rich.js";

const habit = (o: object) => ({
  name: "Dog walk", frequency: "daily", streak: 3,
  tokens_per_completion: 5, completed_today: false, ...o,
});
const html = (h: unknown[]) => buildHabitsRich(h as never).html ?? "";

describe("buildHabitsRich", () => {
  it("offers a complete button only for habits not yet done", () => {
    const out = html([
      habit({ name: "Dog walk", completed_today: false }),
      habit({ name: "Workout", completed_today: true }),
    ]);
    expect(out).toContain('data="habit:complete:Dog walk"');
    expect(out).not.toContain('data="habit:complete:Workout"');
  });

  it("keeps the streak from the old formatter", () => {
    const out = html([habit({ streak: 7 })]);
    expect(out).toContain("7");
  });

  it("escapes habit names in the body", () => {
    const out = html([habit({ name: "Read <Dune> & rest" })]);
    expect(out).toContain("Read &lt;Dune&gt; &amp; rest");
  });

  it("renders a body even when every habit is done", () => {
    const out = html([habit({ completed_today: true })]);
    expect(out).toContain("Dog walk");
    expect(out).not.toContain("<tg-button-row");
  });
});
```

- [ ] **Step 2: Run them and watch them fail**

```bash
cd apps/telegram-bot && npx vitest run tests/formatters/habits-rich.test.ts
```

- [ ] **Step 3: Write the formatter**

Create `apps/telegram-bot/src/formatters/habits-rich.ts`, carrying over `formatHabits`'s body content — the ✅/⏳ icon, the streak, and the average-streak footer — and emitting `habit:complete:<name>` buttons in `<tg-button-row>`s for habits where `completed_today` is false.

**Do not render partial progress here.** `/daily` shows habits as `1/2` because its blocks carry `completions_today` and `daily_target`, but the `Habit` type returned by `GET /habits` has neither — only `completed_today` and `streak`. The helpers exist server-side in `services/habit_completion.py`; surfacing them on `/habits` means extending that route and `packages/shared-types/src/habits.ts`, which is a separate change and is **not** in this plan. Write what the data supports.

**Note on the callback payload:** `habit:complete:` carries the habit *name*, not a slug, and names can contain spaces and non-ASCII. `callback_data` is limited to **1–64 bytes of UTF-8** — a long Hebrew habit name could exceed it. Check the existing behaviour before changing it; if you find names that overflow, report it rather than silently switching to slugs, because the server resolves by name today.

- [ ] **Step 4: Run them and watch them pass**

- [ ] **Step 5: Rewire, and fix the keyboard-loss bug**

`src/commands/habits.ts` uses `sendRich(ctx, buildHabitsRich(habits), { reply_markup: buildNavKeyboard("habits") })`.

In `src/callbacks/index.ts`, **the `habit:complete:` handler currently re-renders with:**

```typescript
await ctx.editMessageText(formatHabits(habits), { parse_mode: "HTML" });
```

with no `reply_markup` at all — so completing a habit strips every button from the message and the user has to re-issue `/habits`. Rewrite it, and `nav:habits`, to `editRich(ctx, buildHabitsRich(habits), { reply_markup: buildNavKeyboard("habits") })`.

Add a regression test asserting the keyboard survives a completion. Delete `src/keyboards/habits.ts`.

- [ ] **Step 6: Verify and commit**

```bash
cd apps/telegram-bot && npx tsc --noEmit -p tsconfig.json && npx vitest run
git add apps/telegram-bot/src/formatters/habits-rich.ts apps/telegram-bot/tests/formatters/habits-rich.test.ts \
        apps/telegram-bot/src/commands/habits.ts apps/telegram-bot/src/callbacks/index.ts
git rm apps/telegram-bot/src/keyboards/habits.ts
git commit -m "feat(bot): /habits renders in-view buttons in the body, and keeps its keyboard"
```

---

### Task 4: `/goals` becomes a rich view

**Files:**
- Create: `apps/telegram-bot/src/formatters/goals-rich.ts`, `apps/telegram-bot/tests/formatters/goals-rich.test.ts`
- Modify: `apps/telegram-bot/src/commands/goals.ts`, `apps/telegram-bot/src/callbacks/index.ts`, `apps/telegram-bot/src/keyboards/goals.ts`

**Interfaces:**
- Produces: `buildGoalsRich(goals: Goal[]): InputRichMessage<InputFile>`, `buildGoalDetailRich(detail: GoalDetail): InputRichMessage<InputFile>`

- [ ] **Step 1: Write the failing tests**

Create `apps/telegram-bot/tests/formatters/goals-rich.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { buildGoalsRich, buildGoalDetailRich } from "../../src/formatters/goals-rich.js";

const goal = (o: object) => ({
  name: "Ship Mazkir", slug: "ship-mazkir", priority: "high",
  status: "active", progress: 40, target_date: null, ...o,
});
const html = (fn: () => { html?: string }) => fn().html ?? "";

describe("buildGoalsRich", () => {
  it("renders one in-body button per goal", () => {
    const out = html(() => buildGoalsRich([goal({ slug: "ship-mazkir" })] as never));
    expect(out).toContain('data="goal:view:ship-mazkir"');
  });

  it("keeps the progress bar from the old formatter", () => {
    const out = html(() => buildGoalsRich([goal({ progress: 40 })] as never));
    expect(out).toMatch(/40\s*%/);
  });

  it("escapes goal names", () => {
    const out = html(() => buildGoalsRich([goal({ name: "A & B <c>" })] as never));
    expect(out).toContain("A &amp; B &lt;c&gt;");
  });

  it("says so when there are none", () => {
    expect(html(() => buildGoalsRich([] as never))).toContain("No");
  });
});

describe("buildGoalDetailRich", () => {
  it("offers only Back — goals have no completion endpoint", () => {
    const out = html(() => buildGoalDetailRich(goal({}) as never));
    expect(out).toContain('data="nav:goals"');
    expect(out).not.toContain("goal:done");
  });
});
```

- [ ] **Step 2: Run them and watch them fail**

- [ ] **Step 3: Write the formatter**

Create `apps/telegram-bot/src/formatters/goals-rich.ts`, carrying over `formatGoals` and `formatGoalDetail`'s body content — including the progress bar and `goalPriorityEmoji`, which maps `high`/`medium`/`low` onto the numeric scale. Cap the button count at 8 as in Task 2.

- [ ] **Step 4: Run them and watch them pass**

- [ ] **Step 5: Rewire**

`src/commands/goals.ts` and the `nav:goals` / `goal:view:` handlers, exactly as Task 2 did for tasks. Delete `buildGoalsKeyboard` and `buildGoalDetailKeyboard` from `src/keyboards/goals.ts`, keeping `goalSlug`.

- [ ] **Step 6: Verify and commit**

```bash
cd apps/telegram-bot && npx tsc --noEmit -p tsconfig.json && npx vitest run
git add apps/telegram-bot/src/formatters/goals-rich.ts apps/telegram-bot/tests/formatters/goals-rich.test.ts \
        apps/telegram-bot/src/commands/goals.ts apps/telegram-bot/src/callbacks/index.ts \
        apps/telegram-bot/src/keyboards/goals.ts
git commit -m "feat(bot): /goals renders in-view buttons in the message body"
```

---

### Task 5: Remove the dead HTML formatters and document the rule

**Files:**
- Modify: `apps/telegram-bot/src/formatters/telegram.ts`, `apps/telegram-bot/tests/formatters/telegram.test.ts`, `CLAUDE.md`

- [ ] **Step 1: Confirm nothing calls them**

```bash
cd apps/telegram-bot
for f in formatTasks formatTaskDetail formatHabits formatGoals formatGoalDetail; do
  echo "$f: $(grep -rn "$f" src/ | grep -v "formatters/telegram.ts" | wc -l) call sites outside its own file"
done
```

Expected: `0` for each. If any is non-zero, that call site was missed — fix it before continuing rather than deleting the function.

`formatCalendar` and `formatTime` stay: `/calendar` still uses them. `escapeHtml` stays and is used by every rich formatter.

- [ ] **Step 2: Delete them and their tests**

Remove the five functions from `src/formatters/telegram.ts` and their `describe` blocks from `tests/formatters/telegram.test.ts`. Delete tests that only asserted the old HTML shape; do not port them.

- [ ] **Step 3: Document the rule in CLAUDE.md**

Under "Development Guidelines → Architecture", add:

```
- **Two kinds of button (2026-08-30):** navigation *between* views (`/day`, `/tasks`, `/habits`, `/goals`) lives in the message's `reply_markup`, built by `buildNavKeyboard(current)` — it omits the current view rather than disabling it. Navigation *within* a view — opening a task, completing a habit, changing the day — lives in the message **body** as `<tg-button-row>` elements, which requires the view to be a rich message. A Telegram message has only one `reply_markup`, so this split is what makes both kinds of control coexist. Every view is now a rich message; `src/formatters/telegram.ts` keeps only `escapeHtml`, `formatTime` and `formatCalendar`.
- **Button labels take plain text only.** No bold, italic, superscript or font size inside a `<tg-button>`; `style` offers only `danger`/`success`/`primary`/`link`. Rich formatting works in the message body, not in button labels.
```

Update the `/tasks`, `/habits` and `/goals` bullets under "Telegram Bot Commands" to say they are rich messages with in-body action buttons.

- [ ] **Step 4: Verify and commit**

```bash
cd apps/telegram-bot && npx tsc --noEmit -p tsconfig.json && npx vitest run
cd ../.. && npx turbo test
git add apps/telegram-bot/src/formatters/telegram.ts apps/telegram-bot/tests/formatters/telegram.test.ts CLAUDE.md
git commit -m "refactor(bot): retire the HTML view formatters"
```

---

## Final verification

```bash
cd /home/marcellmc/dev/mazkir && npx turbo test
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/ -q
cd /home/marcellmc/dev/mazkir && npx tsc -b packages/shared-types
cd apps/telegram-bot && npx tsc --noEmit -p tsconfig.json
```

Then render each view to a file and read the HTML, rather than trusting the tests alone — use `npx tsx` with a throwaway script importing the four `build*Rich` functions. **Do not start the server or the bot to check this.**

## Only the user can verify these

Rich rendering has never been checked against a real Telegram client beyond `/day`. Ask the user to confirm, in this order:

1. **Do the in-body buttons render as buttons** in the list views, or as literal text? This is the whole premise.
2. **Does `style="success"` show** on the task-detail Complete button?
3. **Does the `reply_markup` row stay visually distinct** from the in-body buttons, or do they read as one block? If they merge, the separation the user asked for has not been achieved and the design needs revisiting.
4. **Eight in-body buttons on a narrow phone** — do they wrap sensibly?

## Known-good reference

When anything is unclear, read `src/formatters/day-rich.ts`, `src/commands/day.ts`, and the `day:` handler in `src/callbacks/index.ts`. That view already implements this pattern end to end and has been through four review rounds.
