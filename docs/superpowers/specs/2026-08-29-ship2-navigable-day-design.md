# Ship 2 — Navigable `/day` (Design)

**Status:** Design, approved in conversation 2026-08-29. Not yet planned.
**Parent:** `docs/plans/2026-08-21-time-management-phase2-capture-design.md` §2, ship 2. That doc owns the interaction model across all nine ships; this one owns Ship 2.
**Ship 1 shipped:** PR #9 (`3eb8b2c`), vault commit `fb824da`.

## 1. What this ship is

`/day` stops being a one-shot feed of today and becomes a browsable day viewer backed by the events ledger. It is read-only: no approval, no classification, no edit mode. Those are Ships 5 and 6.

It matters more than its size suggests, because it is the surface every later ship writes to. Getting the block shape and the addressing mechanism right here is what makes Ships 5–7 small.

## 2. Two decisions taken since the parent doc

Both came out of the design conversation and both change what the parent doc assumed.

### 2.1 The events ledger is the source of truth for temporal data

The user's framing, which supersedes the parent doc's implicit split:

> The events ledger should become the source of truth for everything concerning scheduling, planning, temporal data. Daily notes are for thinking, quick note taking — a worksurface. Once a todo gets a scheduled time and duration, and/or is registered as completed, it's promoted to the events storage.

The consequence that makes this cheap: **promotion is inference, not a write.** The checkbox stays in the note and the ledger regenerates the block from it on every open, exactly as it regenerates blocks from calendar entries. So Ship 2 needs no promotion trigger, no sync path, and no new writes — the block already exists by the time `/day` reads.

This also settles what happens to `schedule[]`: it is deleted rather than preserved. Everything it carried arrives as a block instead.

### 2.2 Rich messages are editable, and carry their own buttons

`CLAUDE.md` states that rich messages cannot be edited in place, and `src/bot-utils/send-rich.ts` carries a comment asserting the same. **Both are wrong, and were wrong when written.**

Bot API 10.1 (11 Jun 2026) — the release that introduced rich messages — also added `rich_message` to `editMessageText`. The installed `@grammyjs/types@3.28.0` says so directly:

```ts
/** Use this method to edit text, rich and game messages. */
editMessageText(args: {
  text?: string;                    // required if rich_message isn't specified
  rich_message?: InputRichMessage;  // required if text isn't specified
  reply_markup?: InlineKeyboardMarkup;
})
```

Bot API 10.3 (24 Aug 2026) then added rich **buttons** — `RichBlockButtons`, `RichTextButton`, `RichMessageButton` — which carry `callback_data` (1–64 bytes, the same CallbackQuery flow as inline keyboards) plus a `style` of `primary` / `success` / `danger` / `link`. Buttons live in the message *body*, either as a row (`<tg-button-row>`, 1–8 buttons, with `align`) or inline inside a paragraph.

Two consequences:

- **The week bar gets real selected state.** The parent doc works around its absence — *"Inline keyboards have no selected state, so the current day is marked in the label itself"* (`·20·`). `style="primary"` retires that hack.
- **Ship 5's numeric block picker is probably unnecessary.** The parent doc reasons *"Telegram cannot attach a keyboard to a row, so blocks are addressed by number"* and derives the `[1][2][3][4]` picker from it. An inline `<tg-button>` **can** sit on a block's row. That would remove the numeric addressing scheme, and with it the entire failure class §7 of the parent doc documents — two sides computing different numbers for the same list. Out of scope here; recorded because it changes Ship 5's design.

## 3. Data flow

### 3.1 `/daily` becomes the day composer

It gains `?date=YYYY-MM-DD` (default today) and returns:

```
{ date, tokens_today, tokens_total,
  blocks[],         ← replaces schedule[]
  gaps[],           ← computed, never stored; each becomes a ⚠ row
  coverage{},       ← covered / unaccounted, in minutes
  todos[], notes[]  ← unchanged from Ship 1
}
```

One call per navigation tap. `/daily` **delegates** block-building to the events service rather than re-merging from sources. Two routes implementing the same merge is precisely how the parent doc's §7 numbering bug happened; a second instance is not worth the round trip it saves.

`/daily` has exactly one real consumer — the bot's `/day`. The webapp's `getDaily()` is dead code and its time-management feed reads notes directly (`listNotes` / `getNote` / `setNoteCheckbox`). Reshaping the response breaks nothing.

### 3.2 `MergerService` gains the two inputs it lacks

This is the substance of the ship.

| Input | Today | After |
|---|---|---|
| Daily note | frontmatter only (`daily` arg is `metadata`) | **body too** — timed checkboxes become blocks |
| Habits | only *attached* to a name-matching calendar event | **standalone blocks** when they carry `scheduled_at` |

Without both, moving `/day` to the ledger would silently drop two things visible on screen today: timed checkboxes and scheduled habits with no matching calendar entry.

Note-derived blocks get `source: "daily-note"` and a `source_ids` entry derived from the note line, so `EventsService.refresh_events` matches them across opens the same way it matches `calendar_id`. They stay `suggested` and ephemeral — regenerated from the note on every open — which is why nothing needs persisting and no write path appears.

### 3.3 Gaps

Computed per request, never stored. Two numbers:

- **covered** — sum of block durations, clipped at midnight
- **unaccounted** — elapsed time not covered by any block. `elapsed − covered`, where `elapsed` is midnight→now on today and the full 24h on a past day. Future time on today's date is never unaccounted; it simply hasn't happened.

Worked example — Friday, clock at 15:00, three blocks logged:

```
covered      07:00–07:40 (40m) + 09:05–10:00 (55m) + 12:00–13:00 (60m)  =  2.6h
unaccounted  elapsed 15.0h − covered 2.6h                               = 12.4h
⚠ rows       00:00–07:00 (7.0h) · 07:40–09:05 (1.4h)
             10:00–12:00 (2.0h) · 13:00–15:00 (2.0h)                    = 12.4h ✓
```

Every maximal unaccounted span becomes a **`⚠` row** in the timeline, sitting between blocks in chronological order and showing its own duration. `⚠` marks a hole — *"something happened here and nothing knows what"* — as opposed to a block, which is a claim about time. It is the only marker in Ship 2 that invites action, and acting on it is Ship 4 (say what you did) or Ship 5 (approve an inferred guess).

**An earlier draft split this into three numbers** — `gaps` for holes between the first and last block, `untracked` for everything outside that window — to keep a seven-hour overnight `⚠` from appearing every morning and training the reader to ignore the marker. That was wrong twice.

The boundary was arbitrary: on a day whose last block ends at 13:00 with the clock at 15:00, those two hours are elapsed and unaccounted, identical in kind to a hole at 10:00–12:00, yet they landed in a different bucket purely for falling after the last block — and would silently reclassify the moment anything was logged at 16:00.

More importantly it hid the point. The parent doc §2 states that sleep and eating have no automatic signal and *"are also the two buckets the user most wants to fix."* The three-number rule filed the single largest unlogged span in the day under the label that gets no `⚠`. A standing `⚠ 00:00–07:00` row is not noise; it is a prompt to log sleep, and it disappears the moment Ship 4 can accept *"slept 23:30 to 07:00"*. If it still reads as shouty in practice, the fix is display-level — collapse a leading overnight gap into one quiet row — not a second number with a fuzzy definition.

### 3.4 Cleanup carried by this pass

- **`_infer_category`'s `CATEGORY_KEYWORDS`** (gym / walk / cafe / shopping / work / social) comes out. It targets the single-facet model Phase 1 replaced; leaving it means blocks arrive pre-labelled from a vocabulary that no longer exists.
- **`completions_today` / `daily_target`** reach `packages/shared-types` and the formatter, so a habit renders `1/2` rather than a binary box. Carried forward from Phase 1 (parent doc §11) and explicitly assigned to this rendering pass.

## 4. Rendering

`/day` is a rich message authored as **HTML** — button syntax is HTML-only, which conveniently means Ship 1's `escapeHtml` remains exactly the right tool for user text. No new escaping rules.

Navigation edits the same message via `editMessageText({ rich_message, ... })`. Callback data is `day:2026-08-29`: stateless, well inside 64 bytes, and it leaves the parent doc's §10 selected-date question open rather than pre-answering it. `day:today` is the one special token, so the *today* button needs no date arithmetic on the sending side and stays correct if the message is tapped after midnight.

The `now` divider is rendered as an `<hr>` splitting the timeline into elapsed and ahead, on today only.

```html
<h2>Fri 29 Aug · today</h2>
<p>2.6h covered · 12.4h unaccounted</p>

<table>
  <tr><td>⚠ 00:00–07:00</td><td>—</td><td>7.0h</td></tr>
  <tr><td>07:00–07:40</td><td>Dog walk</td><td>1/2</td></tr>
  <tr><td>⚠ 07:40–09:05</td><td>—</td><td>1.4h</td></tr>
  <tr><td>09:05–10:00</td><td>Standup</td><td>meetings × work</td></tr>
  <tr><td>⚠ 10:00–12:00</td><td>—</td><td>2.0h</td></tr>
  <tr><td>12:00–13:00</td><td>Feature work</td><td>dev × work</td></tr>
  <tr><td>⚠ 13:00–15:00</td><td>—</td><td>2.0h</td></tr>
</table>

<hr>                          <!-- the `now` divider, today only -->

<table>
  <tr><td>19:00–20:00</td><td>Dog walk</td><td>⟳</td></tr>
</table>

<ul>
  <li><input type="checkbox">Order dog food (30m)</li>
  <li><input type="checkbox" checked>Walk dog</li>
</ul>

<tg-button-row align="center">
  <tg-button type="callback_data" data="day:2026-08-28">28</tg-button>
  <tg-button type="callback_data" data="day:2026-08-29" style="primary">29</tg-button>
  <tg-button type="callback_data" data="day:2026-08-30">30</tg-button>
</tg-button-row>
<tg-button-row align="center">
  <tg-button type="callback_data" data="day:2026-08-28">◀</tg-button>
  <tg-button type="callback_data" data="day:today">today</tg-button>
  <tg-button type="callback_data" data="day:2026-08-30">▶</tg-button>
</tg-button-row>
```

**Rich vs HTML `parse_mode`**, which is why the message is rich at all:

| | HTML `parse_mode` | Rich |
|---|---|---|
| Length limit | 4,096 | **32,768** |
| Todos | `☐` / `☑️` emoji | **native task-list items** |
| Timeline | manual space padding | **tables with column alignment** |
| Structure | `<b>` only | headings, dividers, blockquotes, collapsible `details` |
| Bad input | **whole message rejected (400)** | degrades to wrong formatting |

The last row is the one that matters. Ship 1 shipped an escaping fix because a single `<` in a todo killed the entire digest and `day.ts` misreported it as the server being down. Rich still needs escaping, but a miss renders ugly instead of losing the message.

The 32k budget also removes the truncation logic an earlier draft of this design proposed.

**Conventions:**

- **State markers:** `⟳` for blocks still ahead; nothing for elapsed. The parent doc's `✓ approved` and `• awaiting approval` arrive with Ship 5. A "pending" marker before approval exists would mark every block on every day — noise, not signal.
- **The facet column renders only when populated.** With classification at Ship 6, most blocks have no `activity × category`. A column of dashes teaches the reader to ignore it.
- **`📅 Calendar` comes off the button row.** `/day` now renders calendar-derived blocks directly, so a separate calendar command is a second view of the same data.

**Edge cases:**

| Case | Behaviour |
|---|---|
| Day with no blocks | Header shows `no blocks`; todos and notes still render |
| Future date | No `now` divider, no gaps — planned blocks only |
| Block spanning midnight | Rendered clipped to the day; Ship 5 handles approving both fragments |
| Rich payload rejected | Fall back to plain text, as `sendRich` already does on send |

**`editRich` becomes `sendRich`'s sibling**, sharing its fallback. If rich renders badly on the user's client, that path is the escape hatch.

**`day.ts`'s bare catch** currently reports every failure as *"Is vault-server running?"* — including a Telegram send failure. Since this ship rewrites the file, it separates fetch failures from send failures.

## 5. Dependency upgrade

Rich buttons need `grammy ^1.44.0 → ^1.46.0`, which pulls `@grammyjs/types 3.28.0 → 5.0.0` exactly (grammy pins it).

Exposure is one file: `src/bot-utils/send-rich.ts` imports `InputRichMessage` twice. It is generic in 5.0.0 (`InputRichMessage<F>`), so that file needs a type argument. Types 5.0.0 is a major bump, so other signatures may have shifted — `npx tsc -b` plus the 85-test bot suite is the gate, and the upgrade lands as its own commit so a dependency problem cannot be mistaken for a Ship 2 bug.

## 6. Ship boundary

Explicitly **not** in this ship:

| Deferred | To | Why |
|---|---|---|
| Approve / unapprove; `✓` and `•` markers | Ship 5 | No write path in a read-only ship |
| Gap-fitting for completed untimed todos | Ship 5 | The guess and the ability to correct it ship together |
| Classification; populating `activity × category` | Ship 6 | Needs blocks to classify |
| Per-block inline buttons replacing the numeric picker | Ship 5 | Ship 2 proves the mechanism; Ship 5 spends it |
| Selected-date propagation to the agent (parent §10) | Ship 4 / 7 | Nothing needs it until NL addressing exists |

On the deferred gap-fitting: the user's position is that *"if I bothered to add a duration to a todo, I'd want it to appear in the timeline and the time accounted — infer the start/end if possible, I'll review and edit on reconciliation."* That is right, and it is Ship 5's job. Ship 5 is literally *"Inferred capture: suggested→approved, gaps"*. Placing guesses in Ship 2 would show uncorrectable inferred blocks for a whole ship, with no approve affordance and no gap machinery to place them well. Until then a completed untimed todo renders under Todos as done and contributes nothing to coverage, which is honest — nothing knows when it happened.

## 7. Verification

**Server.** Gap arithmetic gets dedicated tests — `now` handling, midnight clipping, single-block days, empty days — since it is the arithmetic most likely to be subtly wrong. Merger tests for both new inputs, particularly that note-derived blocks reconcile by `source_ids` across repeated opens rather than duplicating on every read.

**Bot.** Formatter tests over a `DailyResponse` fixture: block rows, gap rows, the `now` divider, empty states, and the escaping Ship 1 added. A callback test that `day:<date>` edits the existing message rather than posting a new one.

**Run the read path over real data before calling it done.** The Ship 1 whole-branch review named this as the gap that let two Important findings through: every review round stayed inside one function's logic, and nobody ran the feature against the actual daily-note template or a live note until the end. For this ship that means: the template, several real notes, and at least one day with no data.

**Two checks only the user can do**, both after it runs: whether the seven-button week bar wraps on a narrow phone, and whether the rich table renders legibly. Both have a defined fallback — collapse to arrows-only, and plain text respectively.

## 8. Corrections this ship carries

- `CLAUDE.md`: rich messages **can** be edited (`editMessageText` + `rich_message`, Bot API 10.1). The dependent claim — that command digests stay HTML `parse_mode` "because their inline-keyboard UI is edit-driven" — is void with it.
- `src/bot-utils/send-rich.ts`: the comment *"There is no editMessageText on the rich path — rich is send-once only"* is wrong.
- Parent doc §10: the week-bar device check is resolved to "build it behind a config switch, verify on hardware".

## 9. Open questions

- **Overnight `⚠` rows** (§3.3) — a standing gap for unlogged sleep is intended as a prompt, but it is unproven in daily use. If it reads as noise, collapse a leading overnight gap into one quiet row rather than reintroducing a second coverage number.
- **Rich rendering fidelity** — tables and native checkboxes are unverified on the user's client.
- **Where `notes[]` goes long-term.** The user's model has some daily-note content graduating to knowledge storage. Not this ship, but it means `notes[]` in `/daily` is a temporary home.
- Carried from the parent doc, untouched here: selected-date propagation, Todo/Task rename, token economics, timer UX.

## 10. Sources

- [Bot API changelog](https://core.telegram.org/bots/api-changelog) — 10.1 (11 Jun 2026) rich messages + `editMessageText.rich_message`; 10.3 (24 Aug 2026) rich buttons
- [editMessageText](https://core.telegram.org/bots/api#editmessagetext)
- [RichBlockButtons](https://core.telegram.org/bots/api#richblockbuttons)
- `@grammyjs/types@5.0.0` `rich.d.ts` — button class definitions and the HTML/Markdown syntax reference
