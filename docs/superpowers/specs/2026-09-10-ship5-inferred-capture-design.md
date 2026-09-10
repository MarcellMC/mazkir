# Ship 5 — Inferred Capture (Design)

**Status:** Design, approved in conversation 2026-09-10. Not yet planned.
**Parent:** `docs/plans/2026-08-21-time-management-phase2-capture-design.md` §2 (ship 5), §3 (the `/day` surface), §4 (ledger behaviour).
**Predecessor:** `docs/superpowers/specs/2026-09-08-ship4-nl-logging-design.md`.
**Reordered:** Ship 5 was scheduled after Ship 4b. Swapped on 2026-09-10 — see §1.3.

## 1. What this ship is

### 1.1 The one-line version

Ship 4 made Mazkir able to record what it is told. Ship 5 makes it show you
a filled-in day and take yes or no for an answer.

Your input changes from *composing a description* to *correcting a draft*.
That is the whole point; everything below serves it.

### 1.2 What is broken today

`/day` counts every block it can draw. A meeting you skipped counts as an
hour spent, a recurring habit block counts whether or not you did it, and
there is no way to say otherwise. "11.2h covered" therefore means "11.2h
that something guessed happened", which is not a number a weekly readout
can be built on.

The `state` field already exists on every event and defaults to
`"suggested"`. Nothing has ever written `"approved"` —
`api/routes/daily.py:31` says so in a comment. `reconcile` already
preserves `state` across merges. The field is in place and inert.

### 1.3 Why this precedes Ship 4b

The phase doc put 4b (ambient capture) first, but its stated argument —
"hands first, then ears" — is an argument for Ship 4 before 4b, not for 4b
before 5. Nothing defends that particular order.

Ship 5 also partly dissolves what 4b solves. 4b's four obstacles all bite
hardest when talking is the only input path: a dropped clause in a
multi-part sentence, a habit missed because the user said "went for a run"
instead of "workout" (measured at 38 against a floor of 60). Once tapping
is the primary path and talking the exception, those failures become both
rarer and *visible* — a missed block sits in the draft instead of never
being learned about.

Cost of the swap, accepted: 4b's habit-alias fix is what makes logging pay
tokens reliably, and that waits. Token economics for blocks was already
Ship 9, so the two were separated in time regardless.

## 2. The state model

### 2.1 Derived where it can be, stored where it must be

The obvious implementation — write `state: "approved"` on every confirmed
block — walks into a trap the code already documents.
`services/events_service.py:45`:

> Stale rows for these two linger until Ship 5 gives them stable identity.

`note_line` hashes the checkbox's date, section, text and time.
`habit_slug` blocks are suppressed when a calendar event claims the habit.
Persist an approval against either id, then fix a typo in the checkbox, and
the persisted row matches nothing on the next merge — and because
`daily-note` and `habit` are excluded from `_DELETABLE_SOURCE_SYSTEMS`, the
row is preserved *beside* the freshly-inferred block. The same block
renders twice: once approved and stale, once pending and real.

The auto-approval rule (§2.3) dissolves this rather than solving it. The
sources with unstable ids are exactly the human-created ones, and those
auto-approve — which needs no row, because it can be computed from the
source at read time. A checked checkbox *is* the approval.

So:

- **Derived** — for anything a human action created. `resolve_state(event)`
  sits beside Ship 4's `is_complete(event)` and follows the same reasoning:
  a stored status that restates the checkbox's state is stale the moment the
  checkbox changes, and the checkbox is right there.
- **Stored** — only when the user taps `✓` or `✕` on a machine-inferred
  block. Those are calendar and timeline, which are in
  `_DELETABLE_SOURCE_SYSTEMS` *precisely because* their ids come from
  upstream and are stable across merges.

The rows we persist are exactly the rows whose ids can bear it. Line 45's
comment is deleted rather than answered.

### 2.2 `state` must default to absent

`_normalize` and `save_events` currently `setdefault("state", "suggested")`,
which makes "never touched" indistinguishable from "explicitly pending".
Absent must mean *derive it*. This is the same shape as Ship 4's
`user_set`: a stored value overrides, and its absence tracks the source.

Migration: existing rows carrying `"suggested"` are indistinguishable from
untouched ones, which is correct — nothing has ever approved anything, so
every existing row *is* untouched. `_normalize` drops a bare `"suggested"`
on read. `"approved"` and `"dismissed"` are the only values ever stored.

### 2.3 What `✓` and `✕` write

Neither button is one operation. Both dispatch on the block's source
system, and mostly onto write paths that already exist.

| source | `✓` | `✕` |
|---|---|---|
| calendar | store `approved` | store `dismissed` |
| timeline visit / transit | store `approved` | store `dismissed` |
| habit, ticked | derived-approved; no buttons shown | untick the habit |
| habit, not fired | **tick the habit** → derived-approved | store `dismissed` |
| checkbox, checked | derived-approved; no buttons shown | uncheck it |
| checkbox, timed, unchecked | **check it** → derived-approved | store `dismissed` |
| manual / spoken (`create_event`) | born approved | `delete_event` |
| gap proposal | `create_event` → born approved | create it, then store `dismissed` (§4.3) |

**Rows that are already approved carry no buttons** (§5.2), so the `✕`
column above describes what dismissal *means* for each source, not
something reachable from every row. In this ship, un-confirming an approved
block is done by talking — *"that standup didn't happen"* — or by unticking
in `/habits`. See §9.

The derivation keys on the **source system**, not on `completed`. Calendar
events carry `completed` too — `merger_service.py:279,297` set it from
Google's green colour or a `✅` summary prefix — and a completed calendar
event is still machine-inferred intent. Source system comes from the
`source_ids` key via the existing `_SOURCE_SYSTEM_BY_ID_KEY`.

```python
def resolve_state(event: dict) -> str:
    """"approved" | "pending" | "dismissed". Derived unless stored."""
    stored = event.get("state")
    if stored in ("approved", "dismissed"):
        return stored
    if event.get("source") in ("manual", "photo"):
        return "approved"
    systems = {
        _SOURCE_SYSTEM_BY_ID_KEY.get(k)
        for k in (event.get("source_ids") or {})
    }
    if systems & {"habit", "daily-note"} and event.get("completed"):
        return "approved"
    return "pending"
```

### 2.4 Approving pays tokens, deliberately

`✓` on an unfired habit block goes through the existing
`habit_completion.complete_habit`, which awards tokens and may advance the
streak. That is intended, not incidental: the parent design's first stated
goal is that "motivation is an output, not a side effect", and confirming
you did the thing is when payment is due.

`✕` on a ticked habit block unticks it, which reverses the streak and the
tokens. Symmetry is the point — a `✓` you can't take back is a `✓` you
hesitate over.

### 2.5 Dismissed blocks vanish and their time reopens

A dismissed block is not rendered, not counted, and **the span it occupied
becomes a `░` gap**. That is correct: a meeting you skipped means that hour
really is unaccounted, and the gap is then the prompt to say what you did
instead.

Dismissal never touches Google Calendar in this ship. See §6.3 and §9.

Residual, accepted: a `dismissed` habit-derived row whose habit is later
shadowed by a calendar event matches nothing on the next merge, and (not
being in `_DELETABLE_SOURCE_SYSTEMS`) lingers in the store. It renders
nothing, so the cost is invisible clutter.

## 3. Coverage — three numbers, two unions

| | |
|---|---|
| `confirmed_minutes` | union of approved intervals, clipped to elapsed |
| `pending_minutes` | union of pending intervals, minus anything confirmed |
| gaps + `unaccounted_minutes` | computed over **all** blocks, approved and pending together |

The two different unions are load-bearing. If gaps were computed over
approved blocks only, every pending block would sit inside a `░` row
covering the same span — two rows claiming the same time with opposite
meanings. Computing gaps over everything means `░` always means *nothing is
there at all*, so it can never overlap a `●` row.

Only `confirmed_minutes` reaches the weekly readout (Ship 9).

`services/day_coverage.py` stays pure arithmetic and gains no new concepts.
It is called twice with different interval sets. `covered_minutes` is
retained as the union over all blocks — the existing field keeps its
existing meaning, so the webapp and any other consumer do not break.

Still-ahead blocks contribute to neither number: `day_coverage` already
clips intervals to `elapsed_minutes`.

## 4. Gap proposals

### 4.1 Guess when there is a basis; ask otherwise

Decided 2026-09-10: *"If there is data to infer from — try to guess,
otherwise ask me."*

The data is the events store itself — the last 14 days of
`data/events/{date}.json`, approved blocks only. No new store, no network,
no accumulation mechanism to build.

Ladder, first hit wins:

1. **History.** For a gap `[s, e)` on date `d`, collect approved blocks
   from the previous 14 date files that overlap the same clock window by at
   least half the gap's length. If the most frequent `name` among them
   appears on at least 3 distinct days, propose it.
2. **The overnight rule.** A gap that fully contains 02:00–05:00 proposes
   `Sleep`. This is a cold-start seed only — with history present, step 1
   fires first and wins.
3. **Nothing.** The gap keeps its `+ <duration>` button and asks.

Step 1's day count is shown in the row (`Sleep? (11/14)`) so the user can
judge the proposal rather than trust it.

Rejected: proposing from photo EXIF or from timeline coordinates. A gap
means no source emitted anything for that span, so timeline is already
silent there by construction; EXIF is a narrow special case that history
subsumes once it exists.

### 4.2 A proposal is computed, never stored

A proposal is derived at render time, exactly like a gap. Nothing is
written until it is approved.

`✓` on a proposal therefore cannot carry the proposed name in its callback
data — a name can exceed the 64-byte budget, and a client-supplied name is
a client-supplied write. Instead the callback carries only the interval,
and **the server recomputes the proposal for that interval** before
creating the block. Deterministic, because the history it reads is the
same. Callback shape: `prop:<date>:<start_min>:<end_min>`.

### 4.3 Dismissing a proposal must silence it

A proposal is recomputed on every open, so `✕` on one would be undone by
the next render — it would propose `Sleep` again, forever. That contradicts
the whole reason dismissal persists.

So `✕` on a proposal **creates the block and immediately stores it
`dismissed`**: a `manual` row, rendering nothing, counting nothing, with
its span reopened as a `░` gap. The proposal step in §4.1 then skips any
gap overlapped by a dismissed row.

This reuses the events store as its own tombstone rather than introducing a
per-date list of refused intervals. The row *is* the record that this span
was offered and refused.

### 4.4 What a fill does

`+ 1.2h` on an unproposed gap asks *"13:00–14:15 — what was that?"* and the
answer becomes a block through the existing `create_event`. The gap has no
id, so the endpoint keys on the interval rather than an identifier.

## 5. The `/day` surface

Every choice below was prototyped on-device on 2026-09-10 and chosen from
side-by-side renders. Prototype letters refer to that conversation and are
not reproduced here; the outcomes are.

### 5.1 Glyphs

| glyph | meaning |
|---|---|
| `✓` | settled — counts toward `confirmed` |
| `●` | happened, waiting on you |
| `░` | unaccounted |
| `◌` | still ahead — no buttons |

`✅` (completed) is **folded into `✓` and dropped.** The two occupied the
same slot with nearly the same meaning; where they diverged — a Google
entry Google marks green, which is `completed` yet machine-inferred — the
honest answer is `●`, because "the source says it was done" is one input to
approval, not approval itself.

`⚠` is replaced by `░`. A gap is absence, not an error, and `⚠` rendered in
emoji presentation at a size that dominated the row.

`⟳` is replaced by `◌`, pairing with `●`: filled means it happened, dotted
means it has not. In this ship the marker also explains a *missing
affordance* — an ahead row has no buttons, because a 19:00 dog walk cannot
be confirmed at 14:00.

### 5.2 Controls live in the row

Verified on device: **a `<tg-button-row>` inside a `<td>` renders as
compact pills sized to their content.** The same row at top level always
stretches full width; inside an `<li>` it is hoisted out of the list and
stretched. So table cells are the only place compact buttons exist.

This overturns two things. The Ship 2 doc's guess that "an inline button
can sit on a block's row" is correct, and its numeric block picker is
retired. And `@grammyjs/types` is **not** the authority here: the bot
resolves the hoisted root copy at 3.28.0 despite `grammy ^1.46.0`, and that
version's rich grammar predates buttons entirely — it documents
`RichBlockTableCell.text` as inline-only and lists no button block at all.
On-device probes decide questions like this, not the types.

Pending rows carry `[✓][✕][✎]` in the third column. Approved rows carry
their facet label there instead. The two states are mutually exclusive, so
the column never holds both and the table stays three columns wide.

Two consequences of that trade, both accepted:

- **An approved row has no controls at all.** Un-confirming is by talking
  (§2.3). Adding a lone `[✎]` to approved rows would evict the facet label
  from the only cell that can hold it.
- **In this ship that cell is usually empty**, because `activity` and
  `category` are always unset until Ship 6. That is the status quo — the
  current formatter already renders an empty third cell when a block has
  neither facets nor `habit_progress`. The facet labels in the prototypes
  are Ship 6 output, shown to check the layout, not this ship's.

`✕` is the only negative action on this surface. `cancel` and `delete`
touch Google Calendar and live in the edit view (§6.3), where there is room
to say what they do.

### 5.3 Summary row and refresh

The header keeps its `<h2>`. Below it, a one-row table: the coverage
summary in the left cell wrapped in `<sub>`, and `⟲` right-aligned in the
second cell via `<td align="right">`.

`<td align="…">` is the only alignment mechanism the rich grammar offers —
`<p>` has none. That is also why the header cannot move into the table:
table cells take inline formatting only, so an `<h2>` inside one degrades
to bold body text.

### 5.4 The now divider

```html
<table><tr><td align="center"><sub>············ now ············</sub></td></tr></table>
```

A centred table cell, subscript, middle dots. The old divider was a `<p>`
of `─` at body size, which could not be centred at all — it only looked
centred when the dash count happened to match the message width, which is
why it drifted.

Suppression rule is unchanged from Ship 2: shown only when
`0 < elapsed_minutes < 1440` and both sides are non-empty.

### 5.5 The tail

One rule for all navigation, week bar and nav grouped beneath it:

```
…content…
<p>&nbsp;</p><hr>
[week bar]
<p>&nbsp;</p>
[‹][today][›]
```

This removes an `<hr>` rather than adding one. `day-rich.ts` already
records that the now divider "stopped being unambiguous once the
week-bar/nav spacer added a second `<hr>` with an unrelated meaning" — with
this tail, the message is back to one rule, and the now divider is again
the only mid-message separator.

### 5.6 approve-all

Decided 2026-09-10: approve-all **includes proposals.** The
recommendation was to exclude them; the user chose otherwise and the
decision stands.

Two mitigations, neither of which weakens it:

- The button names its count (`✓ approve all 3`), and every item it will
  act on is visible in the table above it.
- The reply enumerates what was banked and marks guesses as guesses —
  *"Approved 3, including Sleep 00:20–06:40 (a guess)."* A wrong sleep
  block is then correctable in the same breath, rather than discovered in
  the Ship 9 readout.

On a past date, approve-all stamps habit completions on **that** date
(§8.2).

## 6. The edit view

Reached by `✎`. Re-renders the same message; `← back` returns to the day.

### 6.1 Nudges

`start` and `end` each get two explicit button rows, magnitudes aligned in
columns and largest on the outside:

```
start 09:05    [−30][−15][−5]
               [+30][+15][+5]
```

Two explicit rows, not one row of six: six buttons in a single row wrap to
3+3 at phone width on their own, so the wrap point has to be ours or the
arrangement is Telegram's to choose.

### 6.2 Drafts ride in the callback data

Each tap re-renders with new times; nothing is written until `✓ save &
approve`. The pending offsets live **in the callback data**, not on the
server: `adj:<id>:<start_delta>:<end_delta>` is about 20 of the 64 bytes
available.

Three consequences, all wanted: no server-side edit state to evict, no
leak when the screen is abandoned, and a button on yesterday's message
cannot apply its offsets to something since changed. It is the same
reasoning the day view already uses for the selected date, which lives in
`day:2026-09-10` rather than in bot memory.

`✓ save & approve` is one button, not two. Bothering to fix the times is
taken as confirmation that it happened.

Renaming has no button. Ship 4 already renames by talking, and a button
whose only power is to open a text prompt is not an improvement on saying
it.

### 6.3 `cancel` and `delete`

Both live here under a `this event` heading, and both are **deferred from
this ship** — see §9. The design is recorded because the buttons' existence
shapes the view:

- `cancel` — patch the Google entry to `status: "cancelled"`. Verified:
  `calendar_service.py:702` calls `events().list()` with no `showDeleted`,
  which defaults false, so a cancelled entry drops out of the merge and
  stops being re-suggested. Reversible, and it keeps the record that the
  event was planned.
- `delete` — `events().delete()`. Confirmed first, then no undo.

Both are limited to Mazkir's own calendar: `CalendarService` scopes every
write to `self._calendar_id`, so an entry in another calendar must report
`not_in_mazkir_calendar` rather than issue a doomed call.

## 7. API surface

- `GET /daily` — `coverage` gains `confirmed_minutes` and `pending_minutes`;
  `covered_minutes` keeps its current meaning (union over all blocks). Each
  block gains its resolved `state`. Gaps gain an optional `proposal`
  (`{name, days_seen}`) when §4.1 fires. Dismissed blocks are omitted.
- `POST /events/{date}/{event_id}/state` — `{state: "approved" | "dismissed"}`,
  dispatching per §2.3. Returns what it actually wrote, including any habit
  completion and tokens, so the bot can say it.
- `POST /daily/{date}/approve-all` — one call rather than N round trips.
  Returns a per-item list, guesses flagged.
- `POST /daily/{date}/gaps/fill` — `{start, end, name?}`. With `name`, creates
  the block. Without, recomputes the proposal for that interval and creates
  that (§4.2).
- `PATCH /events/{date}/{event_id}` — gains `user_set` pinning, closing the
  recorded Ship 4 follow-up where edits through this route still revert on
  the next merge.

`GET /daily` must stay non-persisting: it reaches events through
`get_events_preview` → `reconcile`, never `refresh_events`. Approval is the
first write for a date, and it is an explicit user action, so it persists
deliberately — the same boundary Ship 4 drew for `_resolve_reference`.

## 8. Two recorded bugs this closes

### 8.1 Stale rows from unstable ids

`events_service.py:45` predicted Ship 5 would need to give `note_line` and
`habit_slug` stable identity. §2.1 makes that unnecessary instead: those
sources never get a persisted state row. The comment is deleted.

### 8.2 Habit completions stamped by the server clock

Phase-2 doc §11: *"`habits.py` reads 'today' in `VAULT_TIMEZONE` but writes
via the server clock — inert while they match. Fix in Ship 5, which is the
code that cares."*

Ship 5 is that code. `habit_completion.complete_habit(vault, path,
now=None)` does `now = now or dt.datetime.now()` — naive, server-clock.
Approving a block on a past date must stamp *that* date. The `now`
parameter already exists; callers must pass a `VAULT_TIMEZONE`-aware
datetime for the block's date, and the default must become
timezone-aware.

## 9. Out of scope

| | why |
|---|---|
| Nudging about pending blocks | Belongs to the time-awareness update, which gets its own brainstorm. Ship 5 is pull-only: nothing tells you a day has pending blocks unless you open it. |
| `cancel` / `delete` wired up | The user chose local dismissal for now, as "cheap and non-destructive", pending real use to see which action they actually reach for. §6.3 records the design. |
| Classification (`activity` / `category`) | Ship 6. Blocks approve with both unset, and unclassified time stays visible as such. |
| Weekly readout | Ship 9, the consumer of `confirmed_minutes`. |
| Proposals from EXIF or coordinates | §4.1. History subsumes them. |
| Yesterday's pending blocks expiring | They sit unconfirmed and never count until that day is opened. Honest, and nothing to undo when nudging lands. |
| Un-confirming from a `/day` row | An approved row has no buttons (§5.2). Undo by talking, or by unticking in `/habits`. A dedicated control needs a fourth column or an evicted facet label, and neither is worth it before Ship 6 fills that cell. |

**Size note.** This is at the upper end of one plan — a state model, two
coverage unions, a proposal engine, a re-rendered `/day`, a new edit view
and five endpoints. Comparable to Ship 4 (11 tasks, 26 commits). If it needs
splitting, the seam is §6: the edit view is independently useful and
nothing else depends on it.

## 10. Testing notes

- `resolve_state` is a pure function over one dict. Table-drive it: every
  source system × stored/absent × `completed` true/false. The calendar +
  `completed` case must return `"pending"` — that is the fold in §5.1, and
  it is the one a careless implementation gets wrong.
- Coverage's two unions need a case where a pending block sits inside what
  would otherwise be a gap, asserting the gap does **not** appear and
  `confirmed_minutes` does **not** include it. That single test pins §3.
- Gap proposals need a fixture of 14 date files. Assert the 3-day floor,
  assert history beats the overnight rule, and assert the overnight rule
  fires on an empty store.
- `✓` on an unfired habit block must assert the completion lands on the
  **block's** date, not today. Freeze the clock to a different day than the
  block's, or the test passes for the wrong reason.
- Dismissing a block must assert a gap opens over its span.
- Bot-side, assert the rendered HTML puts button rows inside `<td>`
  elements. A regression that moves them to top level is invisible to a
  string-contains assertion but ruins the layout.
