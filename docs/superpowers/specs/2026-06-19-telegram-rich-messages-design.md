# Telegram Rich Messages Adoption — Design

**Date:** 2026-06-19
**Status:** Approved (design); implementation plan pending
**Scope:** `apps/telegram-bot`

> **Revision note (2026-06-19):** An earlier draft of this design assumed
> `sendRichMessage` took a structured **block-object tree** (`RichBlock` /
> `RichText`) that the bot would build with helpers. That was wrong. Verifying
> against the published `@grammyjs/types@3.28.0` `rich.d.ts` showed the send API
> takes an **extended markup string** instead. This document reflects the
> corrected model. The block-builder / walker / `markdownToRich` AST machinery
> from the earlier draft is dropped.

## Background

Telegram **Bot API 10.1** (released 2026-06-11) added "Rich Messages." The send
side is:

```typescript
// @grammyjs/types@3.28.0
interface InputRichMessage {
  html?: string;       // extended Telegram rich HTML
  markdown?: string;   // extended Telegram rich markdown
  is_rtl?: boolean;
  skip_entity_detection?: boolean;
}
// sendRichMessage(chat_id, { rich_message: InputRichMessage, ... })
// sendRichMessageDraft(chat_id, { rich_message: InputRichMessage, ... })  // streaming
```

So a bot sends rich content as an **HTML or markdown string in an extended
dialect** — not a block tree. The extended dialect adds block-level constructs
on top of classic `parse_mode`:

- HTML: `<h1>`–`<h6>`, `<ul>`/`<ol>`, `<table>`, `<blockquote>` (expandable),
  `<details>`, `<hr>`, plus custom `<tg-collage>`, `<tg-slideshow>`,
  `<tg-math-block>`.
- Markdown: headings, lists, tables, blockquotes, fenced code.

The `RichBlock` / `RichText` union in the API is the **parsed/received** form of
a rich message — never what the bot constructs to send.

**Limits:** ≤ 32 768 UTF-8 chars; ≤ 500 blocks (incl. nested / list items /
table rows); ≤ 16 nesting levels; ≤ 50 media; ≤ 20 table columns.

**No `editRichMessage`.** `editMessageText` cannot edit rich content — editing a
rich message strips its formatting (confirmed by early-adopter reports). To
"edit" a rich message you must delete and resend. This is the central
constraint shaping scope.

## The editing constraint shapes scope

The bot's inline-keyboard UI is **edit-driven**: `/tasks` sends a list with a
keyboard; tapping `editMessageText`s the same message into a task detail, into a
refreshed list after completion, or (via the nav keyboard on `/day`) into
habits/goals/calendar views. Verified `editMessageText` targets:
`formatTasks`, `formatHabits`, `formatGoals`, `formatCalendar`,
`formatTaskDetail`. `/day` holds the nav keyboard.

Because rich messages can't be edited in place, **only send-once surfaces can be
rich.** The user rejected the delete-and-resend workaround (messages jumping to
the chat bottom on every tap). Therefore the edit-driven command digests **stay
on classic HTML `parse_mode`**, and rich is applied only where a message is sent
once and never edited.

## Send-once surfaces (rich candidates)

| Surface | Send-once? | Decision |
|---------|-----------|----------|
| NL agent replies (non-stream) | Yes | **Rich** — `{ markdown: response }` (agent already emits markdown; near pass-through) |
| NL agent replies (streaming) | Yes | **Rich** — `sendRichMessageDraft` (purpose-built for progressive content) |
| `/tokens` | Yes — no keyboard, not a nav/edit target | **Rich (first)** — `{ html }` |
| Task detail | Only if delivery changes | **Deferred** — would require switching list→detail from `editMessageText` to a fresh send |
| `/tasks`, `/habits`, `/goals`, `/calendar`, `/day` | No — edit targets | **Stay classic HTML** |

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Send mechanism | Extended markup **string** via `sendRichMessage` / `sendRichMessageDraft` | Matches the verified `InputRichMessage` shape; no block builder. |
| Dialect per surface | NL replies → `markdown`; `/tokens` → `html` | NL agent text is already markdown (pass-through); command formatters already build HTML strings. |
| Scope | Rich only on **send-once** surfaces | `editMessageText` cannot edit rich; delete-and-resend rejected. |
| Sequencing | **`/tokens` first as a spike**, evaluate live, then NL replies | User wants to see it rendered before committing to NL + deciding on other sections. |
| Task detail + other digests | Deferred / classic HTML | Edit-driven; reconsider only after the `/tokens` evaluation. |
| Failure handling | Plain-text catch-all (tag-stripped) around every rich send | A rejected/oversized rich payload must never drop a message. |
| Backend | Unchanged | vault-server stays Telegram-agnostic. Optional later: a prompt nudge for clean agent markdown. |

## Architecture

### Formatter contract

Rich formatters return `InputRichMessage` (i.e. `{ html }` or `{ markdown }`),
not a string. `formatTokens` is rewritten to build an extended-HTML string and
return `{ html }`. NL replies build `{ markdown: response.response }` inline at
the send site (no dedicated formatter).

### Send helper — `src/bot-utils/send-rich.ts`

```typescript
sendRich(ctx, msg: InputRichMessage, extra?): Promise<void>
```

Calls the grammY rich-send method (exact context/api method name reconciled
against the installed types during implementation) and, on any failure, falls
back to `ctx.reply(plainText)` where `plainText` is the rich content with markup
stripped. Every rich send goes through this helper. This is the only place the
grammY rich-send method name appears.

### Streaming

The streaming path in `src/conversations/message.ts` replaces the
placeholder-message + `editMessageText`-HTML loop with `sendRichMessageDraft`
(its purpose: progressive rich content). Accumulate SSE text deltas into a
buffer, push the buffer as `{ markdown: buffer }` on the ~500 ms tick, finalize.
`editMessageText` is not used on the rich path.

## Data flow

```
/tokens:        handler ─► formatTokens(data): {html} ─► sendRich ─► sendRichMessage
NL (non-stream): POST /message ─► response.response (md) ─► {markdown} ─► sendRich ─► sendRichMessage
NL (stream):     SSE deltas ─► accumulate ─► {markdown: buffer} ─► sendRichMessageDraft ─► finalize
```

Backend (`vault-server`) contracts are unchanged.

## Error handling

- Every rich send routes through the `sendRich` plain-text catch-all.
- Respect the 32 768-char / 500-block limits: NL replies are bounded by the
  agent; if a reply could exceed limits, the catch-all plain-text path covers
  it. Revisit truncation only if it occurs in practice.

## Testing

- `formatTokens` unit test: assert the returned `{ html }` string contains the
  expected balance / milestone substrings (still string `.toContain` checks).
- `sendRich` test: success calls the rich method; failure falls back to a
  tag-stripped plain `ctx.reply`.
- Manual pass against real Telegram: `/tokens` renders correctly (the spike
  checkpoint); then an NL query and a streamed reply.

## Build order

1. Dependency bump (`grammy@^1.44` / `@grammyjs/types@^3.28`) + verify API
   surface + `sendRich` helper.
2. **`/tokens` → rich.** → **CHECKPOINT: evaluate live; decide keep / rethink.**
3. NL non-stream → `{ markdown }` via `sendRich`.
4. NL streaming → `sendRichMessageDraft`.

## Out of scope (pending the `/tokens` evaluation)

- Task detail as a fresh rich send (expandable `<details>` body) — revisit after
  the spike.
- Rich for the edit-driven command digests (`/tasks`, `/habits`, `/goals`,
  `/calendar`, `/day`) — incompatible with in-place edit; would need a UI
  rework.
- Block-object builders / walkers / `markdownToRich` AST — not needed under the
  string model.
- Neutral cross-client block model in `@mazkir/shared-types`.
- Custom emoji, math, maps, collages/slideshows.
