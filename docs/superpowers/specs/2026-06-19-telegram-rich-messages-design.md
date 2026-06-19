# Telegram Rich Messages Adoption — Design

**Date:** 2026-06-19
**Status:** Approved (design); implementation plan pending
**Scope:** `apps/telegram-bot` (full cutover to Bot API 10.1 Rich Messages)

## Background

Telegram **Bot API 10.1** (released 2026-06-11) introduced a "Rich Messages"
system: a JSON object model (`RichMessage` / `RichBlock` / `RichText`) sent via
the new `sendRichMessage` and `sendRichMessageDraft` methods, with
`editMessageText` gaining a `rich_message` parameter. Block-level elements
include section headings, dividers, tables, lists, blockquotes / pull quotes,
preformatted code, paragraphs, math, media blocks, expandable `details`
sections, and "thinking" blocks. grammY exposes these methods as of
`grammy@1.44` / `@grammyjs/types@3.28`.

Today the bot uses HTML `parse_mode` everywhere and *fakes* structure with
emoji prefixes, Unicode bars (`progressBar()` draws `█░`), and hand-numbered
lists. Rich Messages let us replace that faking with native structure.

Mazkir is a **single-user** tool — the user controls the only Telegram client
that matters — so the usual "will end users' clients render this yet?" rollout
risk does not apply. This justifies a full cutover rather than a cautious
incremental migration or a dual-render abstraction.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Migration shape | **Full cutover** (Approach A) | Single client we control; no value in a dual-render abstraction (rejected as YAGNI) or staged hedging. |
| Surfaces | Command views, task detail, NL replies (incl. streaming) | Data-viz (raw progress bars) left as lower priority. |
| NL reply rendering | **Bot-side `markdownToRich()`** (Option 1) | No non-Telegram surface renders agent responses (web app is dayplanner + playground only), so a neutral block model in `shared-types` (Option 2) has no current reuse payoff. Claude-emits-blocks (Option 3) ruled out — fights the streaming path. |
| Backend changes | **None core** | vault-server stays Telegram-agnostic. Optional: a one-line system-prompt nudge so Claude emits clean, parser-friendly markdown — added only if the parser proves flaky. |
| Failure handling | **Plain-text escaped catch-all** around every send | A malformed/rejected rich payload must never silently drop a message. This is a last-resort catch, not the rejected dual-render layer. |

## Prerequisite

Bump dependencies in `apps/telegram-bot/package.json`:

- `grammy` `^1.31.0` → `^1.44.0`
- `@grammyjs/types` `3.25.0` → `^3.28.0` (transitive; pin if needed)

The currently installed versions predate Bot API 10.1 and do **not** expose
`sendRichMessage` (verified: no `sendRichMessage` symbol in installed
`node_modules`).

## Architecture

### Formatter contract change

Formatters in `src/formatters/telegram.ts` change from `(data) => string` (HTML)
to `(data) => InputRichMessage`. To keep them declarative rather than
hand-authoring nested JSON, add a new builder module:

**`src/formatters/rich.ts`** — composable helpers wrapping grammY's
`RichBlock` / `RichText` object literals:

- Block helpers: `heading()`, `paragraph()`, `divider()`, `list()`,
  `table()`, `blockquote({ expandable })`, `details()`, `code()`
- Inline helpers: `bold()`, `italic()`, `code()` (inline), `link()`,
  `text()`
- A top-level `richMessage(...blocks)` assembling an `InputRichMessage`.

The exact grammY type names are confirmed against `@grammyjs/types@^3.28`
during implementation; helpers isolate the rest of the codebase from that
surface.

### Send sites

- `ctx.reply(text, { parse_mode: "HTML" })` → `ctx.replyWithRichMessage(...)`
- `ctx.editMessageText(text, { parse_mode: "HTML" })` (in
  `src/callbacks/index.ts`) → its `rich_message` form
- Streaming edits in `src/conversations/message.ts` → `sendRichMessageDraft`

### Safety wrapper

A single helper (e.g. `sendRich(ctx, richMessage, fallbackText)`) wraps the
send in `try/catch`; on any failure it falls back to `ctx.reply(escapeHtml(
fallbackText))` as plain text. Every send goes through this helper.

## Per-surface mapping

### Command views (`src/formatters/telegram.ts`)

These format **already-structured typed data** from vault-server — purely a bot
concern, no backend involvement.

| Formatter | Rich rendering |
|-----------|----------------|
| `formatDay` | Section heading (`Daily Note — {date}`) + definition list for tokens + `list` for schedule + notes section |
| `formatTasks` | Heading + native `list` items per priority group — removes the hand-numbering counter `n` |
| `formatHabits` | `table` (habit · streak · done) + average-streak paragraph |
| `formatGoals` | `table` (goal · progress · target); `progressBar()` **retained** as cell text (no native progress block) |
| `formatTokens` | Definition list + milestone paragraph |
| `formatCalendar` | `list` of timed items |

### Task detail (`formatTaskDetail`)

Heading = task name; metadata as a list/table; the note body goes in an
**expandable blockquote / `details` block**. This lets us **drop the 800-char
`DETAIL_BODY_MAX` truncation** and present the full body collapsed.

### NL agent replies

Claude returns a text/markdown string (`MessageResponse.response`). A new
shared bot-side converter:

**`markdownToRich(md: string): InputRichMessage`** — parses headings, lists,
fenced code, blockquotes, and inline emphasis/links into rich blocks. Used by
**both** paths:

- **Non-stream** (`src/conversations/message.ts`): `POST /message` → string →
  `markdownToRich()` → `sendRichMessage`.
- **Stream** (`STREAM_RESPONSES=true`): SSE deltas accumulate into a buffer →
  `markdownToRich(partial)` → `sendRichMessageDraft` on the ~500 ms tick →
  finalize. This replaces the current placeholder-message + `editMessageText`
  HTML loop with the API purpose-built for progressive AI content.

## Data flow

```
Command:        handler ─► formatter ─► InputRichMessage ─► sendRich ─► sendRichMessage
NL (non-stream): POST /message ─► string ─► markdownToRich() ─► sendRich ─► sendRichMessage
NL (stream):     SSE deltas ─► accumulate ─► markdownToRich(partial) ─► sendRichMessageDraft ─► finalize
```

Backend (`vault-server`) data contracts are **unchanged**.

## Error handling

- Every send routes through the plain-text catch-all wrapper (see Safety
  wrapper above).
- **Open item:** confirm Rich Message structural limits (max blocks / nesting /
  payload size) against the 10.1 docs during implementation; if a formatter can
  exceed them (e.g. a very long task list), truncate gracefully before send.

## Testing

- **Formatter unit tests** (vitest): replace HTML string assertions with
  `InputRichMessage` object-shape assertions. Existing specs in
  `apps/telegram-bot/tests` updated accordingly.
- **`markdownToRich()`** gets its own suite: headings, nested lists, fenced
  code with language, blockquotes, inline bold/italic/links, and degenerate
  input (empty, partial mid-stream buffers).
- **Manual pass** against real Telegram: each command (`/day`, `/tasks`,
  `/habits`, `/goals`, `/tokens`, `/calendar`), one NL query, and one streamed
  reply — confirm rendering and the plain-text fallback path.

## Build order

1. Dependency bump + `src/formatters/rich.ts` helpers + `sendRich` catch-all.
2. Command formatters + their handlers + callback (`editMessageText`) edits.
3. Task detail (expandable body, drop truncation).
4. `markdownToRich()` + NL non-stream path.
5. Streaming via `sendRichMessageDraft`.

## Out of scope

- Neutral cross-client block model in `@mazkir/shared-types` (Option 2) — defer
  until a non-Telegram surface renders agent responses.
- Backend agent-response changes beyond an optional prompt nudge.
- Native progress-bar / data-viz blocks (no native primitive; Unicode bar kept).
- Custom emoji (`tg-emoji`), math, maps, collages/slideshows — not needed by
  current surfaces.
