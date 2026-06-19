# Telegram Rich Messages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adopt Bot API 10.1 Rich Messages on the bot's send-once surfaces — `/tokens` first (spike), then NL agent replies (non-stream + streaming) — leaving the edit-driven keyboard UI on classic HTML.

**Architecture:** Rich messages are sent as an extended markup **string** in `InputRichMessage` (`{ html }` or `{ markdown }`) via `sendRichMessage` / `sendRichMessageDraft`. There is no block-builder and no `editMessageText` on the rich path (rich messages can't be edited in place). A `sendRich` wrapper sends the rich payload with a tag-stripped plain-text catch-all. The vault-server backend is unchanged.

**Tech Stack:** TypeScript, grammY ≥1.44 / @grammyjs/types ≥3.28, vitest, tsx.

**Spec:** `docs/superpowers/specs/2026-06-19-telegram-rich-messages-design.md`

---

## Working directory

All paths are relative to `apps/telegram-bot/` unless prefixed otherwise. Run all commands from `apps/telegram-bot/`. Test shorthand: `npx vitest run <path>`.

## Key facts (verified against `@grammyjs/types@3.28.0`)

- `InputRichMessage = { html?: string; markdown?: string; is_rtl?: boolean; skip_entity_detection?: boolean }`.
- `sendRichMessage(chat_id, { rich_message: InputRichMessage })` and `sendRichMessageDraft(...)` (streaming) carry the content in `rich_message`.
- Extended HTML adds `<h1>`–`<h6>`, `<table>`, `<details>`, `<hr>`, expandable `<blockquote>` on top of classic parse-mode tags.
- **No `editRichMessage`; `editMessageText` strips rich formatting.** Rich is therefore applied only to send-once surfaces.
- Limits: ≤ 32 768 chars, ≤ 500 blocks, ≤ 16 nesting, ≤ 20 table columns.

## File structure

| File | Responsibility | Action |
|------|----------------|--------|
| `package.json` | grammY dependency versions | Modify |
| `src/bot-utils/send-rich.ts` | `sendRich()` rich send + tag-stripped plain-text catch-all | Create |
| `src/formatters/telegram.ts` | `formatTokens` returns `InputRichMessage` (`{ html }`) | Modify |
| `src/commands/tokens.ts` | Send via `sendRich` | Modify |
| `src/conversations/message.ts` | NL non-stream + streaming paths → rich | Modify |
| `tests/formatters/telegram.test.ts` | `formatTokens` test asserts on returned html | Modify |
| `tests/bot-utils/send-rich.test.ts` | `sendRich` success + fallback | Create |

---

## Task 1: Dependency bump + API reconciliation

**Files:**
- Modify: `apps/telegram-bot/package.json`

- [ ] **Step 1: Bump grammY in `package.json`**

```jsonc
// from
"grammy": "^1.31.0",
// to
"grammy": "^1.44.0",
```
If `@grammyjs/types` is pinned in `package.json`, set it to `^3.28.0`; otherwise it resolves transitively.

- [ ] **Step 2: Install**

Run (from repo root so the lockfile updates):
```bash
cd /home/marcellmc/dev/mazkir && npm install
```
Expected: `node -e "console.log(require('@grammyjs/types/package.json').version)"` prints `3.28.x`+.

- [ ] **Step 3: Confirm the rich API is present and record method names**

Run:
```bash
cd /home/marcellmc/dev/mazkir/apps/telegram-bot
grep -rn "sendRichMessage\|sendRichMessageDraft\|InputRichMessage" node_modules/@grammyjs/types/*.d.ts | head
```
Expected: matches (none existed before the bump). Record in a scratch comment in `src/bot-utils/send-rich.ts` (created in Task 2) the exact grammY **context** method for replying with a rich message (grammY convention: `ctx.replyWithRichMessage(input, other?)`) and the **api** methods (`ctx.api.sendRichMessage(chat_id, ...)`, `ctx.api.sendRichMessageDraft(chat_id, ...)`), confirming the `rich_message` param name and argument order.

- [ ] **Step 4: Verify existing build/tests are still green**

Run: `npx vitest run`
Expected: PASS (nothing else changed yet).

- [ ] **Step 5: Commit**

```bash
cd /home/marcellmc/dev/mazkir
git add apps/telegram-bot/package.json package-lock.json
git commit -m "chore(bot): bump grammY to 1.44 for Bot API 10.1 rich messages"
```

---

## Task 2: `sendRich` helper with tag-stripped plain-text catch-all

**Files:**
- Create: `apps/telegram-bot/src/bot-utils/send-rich.ts`
- Test: `apps/telegram-bot/tests/bot-utils/send-rich.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
// tests/bot-utils/send-rich.test.ts
import { describe, it, expect, vi } from "vitest";
import { sendRich, richToPlainText } from "../../src/bot-utils/send-rich.js";

function fakeCtx() {
  return {
    replyWithRichMessage: vi.fn().mockResolvedValue({ message_id: 1 }),
    reply: vi.fn().mockResolvedValue({ message_id: 2 }),
  };
}

describe("richToPlainText", () => {
  it("strips html tags and decodes basic entities", () => {
    expect(richToPlainText({ html: "<h2>Tokens</h2><b>42</b> &amp; up" }))
      .toBe("Tokens 42 & up");
  });
  it("returns markdown text as-is", () => {
    expect(richToPlainText({ markdown: "## Hi\n- a" })).toContain("Hi");
  });
});

describe("sendRich", () => {
  it("sends the rich message when the API succeeds", async () => {
    const ctx = fakeCtx();
    await sendRich(ctx as any, { html: "<b>hi</b>" });
    expect(ctx.replyWithRichMessage).toHaveBeenCalledOnce();
    expect(ctx.reply).not.toHaveBeenCalled();
  });
  it("falls back to plain text when the rich send throws", async () => {
    const ctx = fakeCtx();
    ctx.replyWithRichMessage.mockRejectedValueOnce(new Error("bad block"));
    await sendRich(ctx as any, { html: "<h2>T</h2>a &amp; b" });
    expect(ctx.reply).toHaveBeenCalledOnce();
    expect(ctx.reply.mock.calls[0][0]).toBe("T a & b");
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npx vitest run tests/bot-utils/send-rich.test.ts`
Expected: FAIL — cannot resolve `send-rich.js`.

- [ ] **Step 3: Implement `send-rich.ts`**

```typescript
// src/bot-utils/send-rich.ts
import type { Context } from "grammy";
import type { InputRichMessage } from "@grammyjs/types";
import { markActiveSpanError } from "../tracing-utils.js";

// Rich content is an extended markup string in InputRichMessage. Send via the
// grammY rich method confirmed in Task 1 Step 3 (ctx.replyWithRichMessage).
// There is no editMessageText on the rich path — rich is send-once only.

/** Best-effort plain text for the catch-all fallback: strip tags + decode the
 *  few entities our formatters emit. Never throws. */
export function richToPlainText(msg: InputRichMessage): string {
  const raw = msg.html ?? msg.markdown ?? "";
  return raw
    .replace(/<[^>]+>/g, " ")   // tags become a space so adjacent words don't merge
    .replaceAll("&amp;", "&")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replace(/\s+/g, " ")
    .trim();
}

/** Send a rich message; fall back to plain text if the payload is rejected or
 *  oversized. A bad rich payload must never drop the message. `extra` carries
 *  reply_markup etc. */
export async function sendRich(
  ctx: Context,
  msg: InputRichMessage,
  extra?: Record<string, unknown>,
): Promise<void> {
  try {
    await ctx.replyWithRichMessage(msg, extra as never);
  } catch (err) {
    markActiveSpanError(err);
    await ctx.reply(richToPlainText(msg));
  }
}
```

> If Task 1 Step 3 shows a different context method name, use it here — this is the only place it appears.

- [ ] **Step 4: Run to verify it passes**

Run: `npx vitest run tests/bot-utils/send-rich.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/telegram-bot/src/bot-utils/send-rich.ts apps/telegram-bot/tests/bot-utils/send-rich.test.ts
git commit -m "feat(bot): add sendRich wrapper with plain-text catch-all"
```

---

## Task 3: `/tokens` → rich (the spike) — ⚠️ DONE THEN REVERTED

> **Outcome (2026-06-19):** Implemented and viewed live. Rich HTML collapses
> `\n` (needs `<br>`/`<p>`) and `<h2>` renders as a large serif heading; once
> corrected, rich `/tokens` is cosmetically identical to the classic-HTML
> version — a flat numeric widget gains nothing from rich. **Reverted** (commit
> `6d106b0`). Do not re-implement. Rich is scoped to NL replies (Tasks 4–5).
> The steps below are kept for the record.

**Files:**
- Modify: `apps/telegram-bot/src/formatters/telegram.ts`
- Modify: `apps/telegram-bot/src/commands/tokens.ts`
- Modify: `apps/telegram-bot/tests/formatters/telegram.test.ts`

- [ ] **Step 1: Update the `formatTokens` test to assert on returned html**

Replace the `formatTokens` describe block in `tests/formatters/telegram.test.ts`:

```typescript
describe("formatTokens", () => {
  it("returns rich html with balance and next milestone", () => {
    const msg = formatTokens({ total: 42, today: 10, all_time: 42 });
    expect(msg.html).toBeDefined();
    const html = msg.html!;
    expect(html).toContain("42");
    expect(html).toContain("50");          // next milestone
    expect(html).toContain("8 to go");
    expect(html).toContain("<h2>");        // native heading, not emoji-faked
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npx vitest run tests/formatters/telegram.test.ts`
Expected: FAIL — `formatTokens` returns a string, so `.html` is undefined.

- [ ] **Step 3: Rewrite `formatTokens` to return `InputRichMessage`**

Add the import at the top of `telegram.ts`:
```typescript
import type { InputRichMessage } from "@grammyjs/types";
```

Replace `formatTokens`:
```typescript
export function formatTokens(data: TokensResponse): InputRichMessage {
  const lines = [
    "<h2>🪙 Motivation Tokens</h2>",
    `💰 Balance: <b>${data.total}</b>`,
    `📈 Today: <b>+${data.today}</b>`,
    `🏆 All-time: <b>${data.all_time}</b>`,
  ];
  const milestones = [50, 100, 250, 500, 1000, 2500, 5000];
  const next = milestones.find((m) => m > data.total);
  if (next) {
    lines.push(`🎯 Next milestone: <b>${next}</b> (${next - data.total} to go)`);
  }
  return { html: lines.join("\n") };
}
```

> Other formatters are unchanged — they stay HTML strings for the edit-driven keyboard UI. Only `formatTokens` returns `InputRichMessage`.

- [ ] **Step 4: Update `commands/tokens.ts` to send via `sendRich`**

```typescript
import { Composer } from "grammy";
import { api } from "../api/client.js";
import { formatTokens } from "../formatters/telegram.js";
import { sendRich } from "../bot-utils/send-rich.js";
import { markActiveSpanError } from "../tracing-utils.js";

export const tokensCommand = new Composer();

tokensCommand.command("tokens", async (ctx) => {
  try {
    const data = await api.getTokens();
    await sendRich(ctx, formatTokens(data));
  } catch (err) {
    markActiveSpanError(err);
    await ctx.reply("❌ Failed to load tokens.");
  }
});
```

> Confirm the existing api method name (`api.getTokens()`) and the Composer export name against the current `tokens.ts` before editing; keep them identical.

- [ ] **Step 5: Verify build + tests**

Run:
```bash
npx tsc --noEmit && npx vitest run
```
Expected: tsc clean; all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/telegram-bot/src/formatters/telegram.ts apps/telegram-bot/src/commands/tokens.ts apps/telegram-bot/tests/formatters/telegram.test.ts
git commit -m "feat(bot): render /tokens as a rich message (spike)"
```

---

## CHECKPOINT: evaluate `/tokens` live

**Stop here and evaluate before continuing.**

- [ ] **Run the stack and view `/tokens` in Telegram**

```bash
cd /home/marcellmc/dev/mazkir/apps/vault-server && source venv/bin/activate && python -m uvicorn src.main:app --reload --port 8000
cd /home/marcellmc/dev/mazkir/apps/telegram-bot && npx tsx src/index.ts
```
Send `/tokens`. Confirm: the `<h2>` heading renders as a native rich heading; balance/milestone are correct; the message looks better than the prior emoji-only version.

- [ ] **Decision:**
  - **Keep + proceed** → continue to Task 4 (NL replies).
  - **Rethink** → the user reconsiders styling or whether to extend rich to other (send-once) sections. Revisit the spec before continuing. Do not start Task 4 until the user confirms.

---

## Task 4: NL non-stream replies → rich markdown

> Proceed only after the checkpoint decision is "keep + proceed".

**Files:**
- Modify: `apps/telegram-bot/src/conversations/message.ts`

- [ ] **Step 1: Add imports near the top of `message.ts`**

```typescript
import { sendRich } from "../bot-utils/send-rich.js";
```

- [ ] **Step 2: Replace the non-streaming branch**

Replace the non-streaming branch (currently around `message.ts:286-296`):
```typescript
      } else {
        // Non-streaming path (default)
        const response = await api.sendMessage(payload);

        if (response.awaiting_confirmation && response.pending_action_id) {
          pendingConfirmations.set(chatId, response.pending_action_id);
        }

        setActiveSpanOutput(response.response);
        // Agent already emits markdown — pass it through as a rich message.
        await sendRich(ctx, { markdown: response.response });
      }
```

- [ ] **Step 3: Verify build + tests**

Run:
```bash
npx tsc --noEmit && npx vitest run
```
Expected: tsc clean; all tests PASS (`buildMessagePayload` tests are unaffected — only the reply send changed).

- [ ] **Step 4: Manual check**

With `STREAM_RESPONSES` unset/false, send a free-text question (e.g. "summarise my tasks as a list"). Confirm the reply renders as rich markdown (lists/headings). If the agent's markdown ever produces an invalid rich payload, the `sendRich` catch-all sends plain text — confirm no dropped messages.

- [ ] **Step 5: Commit**

```bash
git add apps/telegram-bot/src/conversations/message.ts
git commit -m "feat(bot): render non-streaming agent replies as rich messages"
```

---

## Task 5: Streaming replies → `sendRichMessageDraft`

**Files:**
- Modify: `apps/telegram-bot/src/conversations/message.ts`

- [ ] **Step 1: Replace the streaming branch**

Replace the `if (config.streamResponses) { ... }` block (currently `message.ts:217-285`). Use the draft method signature confirmed in Task 1 Step 3; the shape below is illustrative.

```typescript
      if (config.streamResponses) {
        // Streaming: progressively push the accumulating buffer as a rich draft,
        // then finalize. editMessageText is NOT used (it can't edit rich content).
        // Drafts are ephemeral 30s previews keyed by a non-zero draft_id; sending
        // the same draft_id animates the update. Persist by sending the complete
        // message via sendRich (sendRichMessage) at the end.
        let buffered = "";
        let lastEdit = Date.now();
        const EDIT_INTERVAL_MS = 500;
        const draftId = (Date.now() % 2_000_000_000) || 1; // non-zero, stable per stream

        const pushDraft = async () => {
          try {
            // Context alias injects chat_id; signature is
            // replyWithRichMessageDraft(rich_message, { draft_id }).
            await ctx.replyWithRichMessageDraft(
              { markdown: buffered },
              { draft_id: draftId },
            );
          } catch {
            // rate-limit / partial-parse errors are non-fatal mid-stream
          }
        };

        try {
          const response = await streamMessage(payload, async (chunk) => {
            buffered += chunk;
            if (Date.now() - lastEdit > EDIT_INTERVAL_MS) {
              await pushDraft();
              lastEdit = Date.now();
            }
          });

          if (response.awaiting_confirmation && response.pending_action_id) {
            pendingConfirmations.set(chatId, response.pending_action_id);
          }
          setActiveSpanOutput(response.response);

          // Finalize as a full rich message (catch-all → plain text on failure).
          await sendRich(ctx, { markdown: response.response });
        } catch (streamErr) {
          // Fall back to non-streaming on any stream error.
          try {
            const response = await api.sendMessage(payload);
            if (response.awaiting_confirmation && response.pending_action_id) {
              pendingConfirmations.set(chatId, response.pending_action_id);
            }
            setActiveSpanOutput(response.response);
            await sendRich(ctx, { markdown: response.response });
          } catch (fallbackErr) {
            markActiveSpanError(fallbackErr);
            await ctx.reply("❌ Something went wrong. Is vault-server running?");
          }
        }
      } else {
```

> Verified API (Task 1): `ctx.replyWithRichMessageDraft(rich_message, { draft_id })` — `draft_id` is a required non-zero number; reusing it animates the same preview, which is ephemeral (~30s). The draft does NOT persist — you finalize by sending the complete message via `sendRich` (which calls `sendRichMessage`). The streaming contract (accumulate buffer → push `{ markdown }` on a 500 ms tick → finalize with `sendRich`) drops the old placeholder-message + `editMessageText` pattern entirely.

- [ ] **Step 2: Verify build + tests**

Run:
```bash
npx tsc --noEmit && npx vitest run
```
Expected: tsc clean; all tests PASS.

- [ ] **Step 3: Manual check**

Set `STREAM_RESPONSES=true`, restart the bot, send a question that yields a long answer. Confirm the draft updates progressively and finalizes as clean rich markdown.

- [ ] **Step 4: Commit**

```bash
git add apps/telegram-bot/src/conversations/message.ts
git commit -m "feat(bot): stream agent replies via sendRichMessageDraft"
```

---

## Notes for the implementer

- **Single reconciliation point:** grammY's exact 10.1 method names/arg shapes are pinned in Task 1 Step 3 and appear only in `send-rich.ts` (context reply method) and `message.ts` (`sendRichMessageDraft`). Adjust to match the installed types; the `sendRich(ctx, InputRichMessage, extra?)` signature stays stable.
- **Other formatters stay HTML.** `formatTasks`, `formatHabits`, `formatGoals`, `formatCalendar`, `formatTaskDetail`, `formatDay` remain string-returning HTML formatters sent via `parse_mode: "HTML"` — they are edit-driven (`editMessageText`) and rich can't be edited in place. Do not change them in this plan.
- **DRY/YAGNI:** no block builder, no walkers, no `markdownToRich` AST, no dual HTML renderer — all out of scope under the string model.
- **Deferred (post-checkpoint):** task detail as a fresh rich send (expandable `<details>` body); reconsider only if the `/tokens` evaluation prompts extending rich further.
