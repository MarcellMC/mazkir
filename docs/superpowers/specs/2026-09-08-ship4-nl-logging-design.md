# Ship 4 — NL logging and single-block edits (Design)

**Status:** Design, approved in conversation 2026-09-08. Not yet planned.
**Parent:** `docs/plans/2026-08-21-time-management-phase2-capture-design.md` §6 — this is ship #4 of that document's ship order.
**Builds on:** Ship 2 (PR #11), Ship 3 (PR #14, `ce960e5`), and PR #15 (`c3ffcee`).

## 1. What this ship is for

The parent document put NL logging before inferred capture for one reason: *"Sleep and eating have no automatic signal — no calendar entry, no distinguishable location, no habit fires. They are also the two buckets the user most wants to fix."* Everything the ledger knows today, it learned from a calendar, a location history, or a checkbox. The two largest spans of a real day are invisible to all three.

So the goal is narrow and testable: **after this ship, a full day can be logged by talking.** "Slept 23:30 to 07:15." "Just got back from the dog walk." "Lunch 13:00 to 13:45." And when one of those comes out wrong — as it will — a single sentence corrects it.

That second half turns out to be the harder one, and PR #15 is the reason it is now urgent rather than theoretical.

### 1.1 What PR #15 already settled

PR #15 landed three things this ship would otherwise have had to build:

- **`delete_event`** — destructive tier, always previewed by name and time, deletes the Google Calendar entry when Mazkir owns it, and returns `reappears_from_source: true` for note-, habit- and calendar-derived blocks it cannot permanently remove. This is a better answer than the boundary this design originally proposed (delete only user-created blocks, defer the rest to Ship 5's unapprove): it does the harder thing and is honest about what will come back.
- **`EventsService.resolve_event_date`** — an event ID is global; a `date` argument is only a hint. `update_event`, `delete_event` and `attach_photo_to_event` all resolve through it.
- **Cross-date moves** — `update_event(new_date=…)` relocates the row to the target day's file and detaches `source_ids` into `moved_from_source_ids`, because `reconcile` would otherwise delete the moved event on the next read.

Its own follow-up — registering `delete_event` in `time-management.md`'s `tools:` frontmatter, which its container could not reach because the vault is a separate repo — was completed on 2026-09-08 (vault commit `0f22833`).

### 1.2 The bug PR #15 makes reachable

An in-place edit is reverted by the next re-inference. `reconcile`'s matched branch (`events_service.py:482`) overwrites `name`, `start_time`, `end_time` and `location` from the fresh source on every merge; only `photos`, `assets`, `id` and `state` survive.

Verified against `c3ffcee`:

```
rename "Daily sync" → "Standup"          ✓ persisted
reconcile (calendar answers, unchanged)  → "Daily sync"
```

`test_same_day_update_leaves_source_ids_alone` deliberately pins this, and correctly — detaching `source_ids` on every edit would sever blocks from sources whose later changes should still flow through. PR #15 did not introduce the revert; it fixed the resolution bugs that were preventing anyone from reaching it. §2 is the fix.

### 1.3 Two more findings from the PR #15 review

Both verified against the branch, both in this ship's path:

1. **A start-only time update stretches the block instead of moving it.** `Gym 18:00–19:00` plus `update_event(start_time="17:30")` yields `17:30–19:00`, 90 minutes. "Move gym −30m" therefore comes out right only if the model computes *both* ends — the arithmetic that shifted a block by its own length on 2026-08-16. §3.1 and §4.4 address it.
2. **Nothing rejects an inverted interval.** `update_event(start_time="21:00")` on a block ending at 19:00 persists `start 21:00 / end 19:00 / duration_minutes 0`. Coverage survives (`day_coverage.py:103` drops intervals where `end <= start`), so the numbers stay honest, but `/day` renders `21:00–19:00` and the block counts for nothing. §4.4 adds the guard.

## 2. The data model: three axes, one new field

The `state` string on an event has been quietly asked to carry three unrelated questions. They have different granularity and different lifetimes, and collapsing them is what makes partial capture feel impossible:

| Axis | Question | Granularity | Stored? |
|---|---|---|---|
| **Provenance** | did this value come from a source, or from the user? | per **field** | yes — §2.1 |
| **Completeness** | does it have enough to be a block yet? | per block | no — derived, §2.3 |
| **Approval** | does it count? | per block | yes — `state`, Ship 5 |

This ship introduces the first and derives the second. `state` is not touched; it remains the stub Ship 5 will fill.

### 2.1 `user_set` — per-field provenance

One new persisted field on every event:

```json
{
  "id": "evt_35bc840e",
  "name": "Standup",
  "start_time": "2026-09-08T10:15:00",
  "end_time": null,
  "source": "calendar",
  "source_ids": { "calendar_id": "b59k4aen6c897prakg3nuirb64" },
  "user_set": { "name": "Standup", "start_time": "2026-09-08T10:15:00" }
}
```

`save_events` defaults it to `{}` alongside the other `setdefault` calls (`events_service.py:131–138`).

**Settable keys** — exactly these five: `name`, `start_time`, `end_time`, `location`, `activity`. Anything else in the map is ignored on re-application, so a stray key cannot corrupt a merge.

**Explicitly not settable:** `completed` and `habit`, which `reconcile` re-derives from checkbox and habit-log state on every merge and which are stale the instant the vault changes — reconcile's own comment says so; and `id`, `source_ids`, `state`, `photos`, `assets`, which are already preserved by other means.

**The change to `reconcile`** is one step at the end of the matched branch:

```python
matched_existing["completed"] = fresh.get("completed", False)
matched_existing["habit"] = fresh.get("habit")
_apply_user_set(matched_existing)     # new — last word goes to the user
result.append(matched_existing)
```

where `_apply_user_set` copies the settable keys over the merged values and recomputes `duration_minutes` when it moved either end. Unmatched fresh events carry no `user_set`; unmatched persisted events are untouched, so their pins already survive.

**Why store the value rather than a `provenance: {field: "user"}` map.** With a separate provenance map the value lives in two places and they can disagree — a merge that overwrites `name` while the map still claims "user" leaves no way to recover what the user actually said. Storing the value makes re-application idempotent and self-evidencing: the pin *is* the data.

**Reverting a pin.** `update_event` gains `revert_fields: [str]`, which deletes those keys from `user_set` so the source resumes winning. It is applied **before** the call's own field updates, so naming a field in both reverts it and then pins the new value — the only reading under which a single call cannot contradict itself. Without it the mechanism has no escape hatch: a mistaken rename could be renamed again but never returned to tracking the calendar.

### 2.2 Why `user_set` and `moved_from_source_ids` both exist

Two mechanisms now stop a source from undoing a user's change, and a future reader will be tempted to collapse them. They answer different questions:

- **Detach** (`moved_from_source_ids`, PR #15) is for **relocation**. The event has left the day its source owns. `reconcile` at the target date can never match it, so keeping live `source_ids` there would get it deleted. This is structural, not stylistic.
- **`user_set`** is for **override**. The event is still that source's, on that source's day; one field is now the user's. The source's other changes should keep flowing.

Collapsing them in either direction breaks something: detaching on every edit severs blocks that should keep tracking their calendar entry, and pinning instead of detaching on a move re-introduces the deletion PR #15 fixed.

### 2.3 Completeness is derived, never stored

```python
def is_complete(event: dict) -> bool:      # events_service.py, module level
    return bool(event.get("start_time")) and bool(event.get("end_time"))
```

Nothing persists this. A status that restates what the fields already say is a status that goes stale — and the fields are right there.

Today an event missing either end is **silently dropped**. `_build_blocks_and_coverage` (`routes/daily.py`) does `if start is None or end is None: continue`, which is Bug A's exact shape: parsed correctly, written correctly, invisible. So `/daily` gains a fourth array beside `blocks[]`, `gaps[]` and `todos[]`:

```python
class DailyIncomplete(BaseModel):
    id: str
    title: str
    start: str | None = None      # "HH:MM" when known
    end: str | None = None
    missing: list[str]            # subset of ["start_time", "end_time"]
    source: str
```

The routing rule in `_build_blocks_and_coverage` distinguishes *absent* from *belongs to another day*, because `minutes_into_day` returns `None` for both:

```python
start_raw, end_raw = e.get("start_time"), e.get("end_time")
start = minutes_into_day(start_raw or "", date)
end = _end_minutes(end_raw or "", date)
if start is not None and end is not None:
    ...append to blocks, append interval...
elif not start_raw or not end_raw:
    ...append to incomplete...           # a field is genuinely missing
else:
    continue                             # present but another day — drop, as today
```

**Coverage is unchanged.** An incomplete block contributes no interval, so its time stays in `unaccounted` and its `⚠` gap row remains. That is the point: the gap is the reason to finish the block. A half-block that quietly claimed the span would be §5's `misc`/`unaccounted` conflation in a new costume.

## 3. Logging

### 3.1 `create_event` takes any two of three

Today `start_time` is required and the model does the arithmetic. New signature — `name` is the only requirement, and the caller supplies any two of **`start_time`**, **`end_time`**, **`duration_minutes`**:

| Given | Result |
|---|---|
| start + end | duration derived |
| start + duration | end derived |
| end + duration | start derived — *"just got back from the 40-minute dog walk"* |
| all three, consistent | accepted |
| all three, inconsistent | `SCHEMA_INVALID` naming the conflict — never silently pick one |
| exactly one | incomplete block, persisted, no calendar sync |
| none | incomplete block with no time at all — allowed |

Deriving server-side is the whole point: interval arithmetic is the thing the model has already been observed getting wrong, and it is trivially correct in Python.

**Anchoring.** Which end of the interval an utterance anchors is the distinction that matters, and getting it backwards shifts a block by its own length. Rules go in `memory/00-system/skills/time-management.md`:

- *"just got back from X"*, *"finished X"* → the utterance anchors the **end**; end is now, start is unknown.
- *"starting X"*, *"heading out for X"* → anchors the **start**; end is unknown.
- *"X from A to B"*, *"slept A to B"* → both ends given.
- **Never invent a missing time.** Write the block incomplete and ask. An incomplete block is a correct record of an incomplete statement; a guessed one is a wrong record of a confident one.
- Prefer `duration_minutes` to computing a second timestamp.

### 3.2 Incomplete blocks are a two-step conversation

A block written with one end is not a failure state — it is the natural result of how people talk about time. `/day` renders them in their own section (§7.1), and Mazkir raises them when you next talk (§7.2) rather than leaving a pile nobody completes.

This is what defuses the anchoring bug rather than merely documenting it: the correct behaviour for *"just got back from the dog walk"* stops being "guess the start" and becomes "write the end, leave the start null, ask."

### 3.3 Cross-midnight

Sleep is this ship's headline case and it crosses midnight almost every night. Storage splits at 00:00 — Phase 1 §4.2, restated in the parent document §3 — and `merger_service.py:309` currently *clamps* a past-midnight block to 23:59 with a comment deferring the split.

`create_event` normalizes bare `HH:MM` values against the event's date **first**, then splits when the resolved interval spans a boundary — either the end's date is later than the start's, or both resolved to the same date and the end is earlier, which means the next day:

- fragment 1: `start → {day1}T23:59:59`
- fragment 2: `{day2}T00:00:00 → end`
- each written to its own date file, with its own `duration_minutes`
- both carry the same new `logical_id` (a uuid; `save_events` defaults it to `None`)

Splitting server-side rather than asking the model for two `create_event` calls is deliberate, for the same reason as §3.1.

**`logical_id` is written but nothing branches on it in Ship 4.** It is surfaced by `list_events` so the agent can see two rows are one thing, and that is all. It is written now because the link is unrecoverable later, and Ship 5 needs it: *"Approving a block spanning midnight approves both fragments."*

**Editing a fragment edits only that fragment.** "Sleep ended at 8" moves fragment 2's end; "sleep started at 23:00" moves fragment 1's start. Both read naturally, so Ship 4 needs no cross-fragment propagation.

**A midnight-spanning block is not synced to the calendar** — `calendar_sync: {ok: false, attempted: false, reason: "crosses_midnight"}`. Google stores such an event natively as one, which would then hand a single fresh event to two per-day fragments on the next merge, across a query window this design has not verified. Sleep still gets logged, counted, and closes its gap; only its calendar row waits for the ship that fixes the merger's midnight handling.

## 4. Editing

### 4.1 The agent must see the day the user sees

`_tool_list_events` reads the raw persisted file via `EventsService.get_events`. `/day` renders `get_events_preview`, which reconciles *without* persisting — Ship 2 made that deliberate so browsing a date could never rewrite it. The two can disagree completely, and `routes/events.py`'s own docstring says so.

Three moves:

1. **`_merge_from_sources` moves out of `routes/events.py` into `services/day_assembly.py`**, unchanged and still async. Both event routes import it from there.
2. **`_maybe_await` moves out of `services/hooks/sync_to_calendar.py:45` into `services/async_bridge.py`.** Tool handlers are strictly synchronous — neither `tool_executor` nor `parallel_executor` ever awaits one — so a bridge is the only option short of making the whole execution path async, which is out of scope. `_tool_create_event` already open-codes this dance and `_tool_delete_event` already imports the private helper across module boundaries; one shared home replaces both.
3. **`_tool_list_events` returns the reconciled day**, with `complete` and `logical_id` on each row.

`list_events` stays `safe` and `safe_for_parallel` — it still writes nothing — but it is no longer trivially cheap, since it now reaches the calendar. Its docstring says so.

### 4.2 Addressing by description

`services/block_resolver.py`, mirroring `services/resolver.py`'s ladder exactly so both behave the same way under ambiguity:

```
resolve_block(reference: str, candidates: list[dict]) -> dict
```

1. exact `id` match → score 100
2. exact `name` match (case-sensitive) → score 100
3. case-insensitive substring of `name` — unique hit → score 95; multiple → `AMBIGUOUS_MATCH`
4. `rapidfuzz.fuzz.token_set_ratio` ranked; below 60 → `PATH_NOT_FOUND`; top two within `SCORE_AMBIGUOUS_DELTA` (10.0) → `AMBIGUOUS_MATCH`

Candidates come from the reconciled view of the dates being searched (§5). `AMBIGUOUS_MATCH` details carry `{id, name, start_time, date}` per candidate, so the agent can name the day when two days both have a "dog walk" — the existing prompt rule already tells it to surface candidates rather than guess.

`update_event` and `delete_event` accept **either** `event_id` or `block_reference`. No ordinals: the parent document §7 fixes numbering, and both it and the batch flow are Ship 7.

### 4.3 Materialising a block that was never persisted

An inferred block — a calendar event, a timeline visit, a timed checkbox — has no row to update. When a write tool is given a `block_reference`:

1. assemble the day via `services/day_assembly.py`
2. `refresh_events` (reconcile **and** save) for that date
3. resolve the reference against the result
4. act on the resulting `event_id` through PR #15's existing path

Persisting here does not contradict Ship 2. Navigation must not write; an explicit edit must. `GET /events/{date}` already persists for exactly this reason.

### 4.4 Interval guards

Both from the §1.3 findings, both landing on `update_event`:

- **`shift_minutes: int`** (signed) moves **both** ends by the same amount. This is what "move gym −30m" means, and it removes the model's need to compute two new timestamps. Rejected with `SCHEMA_INVALID` when the block is incomplete, since there is nothing coherent to shift.
- **Reject inverted intervals.** After updates are applied, if both times are present and `end < start`, return `SCHEMA_INVALID` naming the resulting interval and write nothing. `end == start` stays legal — a zero-length event is a moment, not a contradiction, and `create_event` already defaults `end` to `start`.

While in this function, `update_event` stops mutating the `updates` dict it is handed (`events_service.py:216`). Harmless today, since every caller builds it locally, but it is a side effect on an argument.

## 5. Which day is being talked about

The parent document §10 left this undecided between a bot-supplied value and server-side per-chat state. **Decision: bot-supplied**, with a staleness rule and two guards.

**The hint.** `POST /message` gains an optional `selected_date`. The bot keeps a per-chat record of the date its `/day` view is showing, updated whenever `/day` renders or a date button is tapped.

**Staleness.** The bot attaches `selected_date` only while the day view is still the last message it sent to that chat. Sending anything else — an agent reply, `/tasks`, a photo acknowledgement — drops it. The reasoning: if the day view has scrolled off behind other bot output, it is no longer what the user is looking at, and a date they have forgotten selecting must not silently steer a much later message. No clock and no tuning parameter. Implemented as a grammY API transformer (`bot.api.config.use`) observing outgoing `sendMessage` / `sendRichMessage` / `editMessageText`, so no send site has to remember to update it. The record is in-memory and evaporates on restart, falling back to today.

**Guard 1 — the hint steers resolution, never the write.** `resolve_block` searches the hinted day **and** today, deduped. One match acts. Two return `AMBIGUOUS_MATCH` with both dates. Zero says so. A stale hint therefore only matters when the referenced block exists on the stale day and nowhere else.

**Guard 2 — any write to a day that is not today names that day in the reply.** *"Moved Gym on **Thu 20 Aug** to 18:30–19:30."* The risk of a sticky date is a silent edit to a past day; naming the date removes the "silently," and every edit in this ship is non-destructive enough to correct in one more sentence.

The hint also enters the dynamic system tail as one line — *"The user is currently viewing 2026-08-20"* — so the agent can reason about it rather than only the resolver consuming it.

## 6. Calendar sync

Mazkir writes only to its own calendar: `ensure_mazkir_calendar` (`calendar_service.py:146`) provisions it and every write passes `calendarId=self._calendar_id`. So a block from a work calendar cannot be damaged by any of this — the API returns 404 and the write fails safe. What is missing is that the failure reports as `delete_failed`, which does not say why.

**Carry the owning calendar through the merge.** `get_todays_events_with_status` already returns `'calendar': cal['name']` per event, and `_calendar_source_ids` (`merger_service.py:92`) drops it. `MergedEvent` gains a `calendar: str | None` field carrying it. Mazkir then knows before calling whether it owns an event, reports `not_in_mazkir_calendar` without a wasted round trip, and no longer has to infer ownership from a 404.

**`CalendarService.update_event(event_id, name=None, start=None, end=None, date=None) -> bool`** is new — `create_event` and `delete_event` exist, update does not. It issues `events().patch` against `self._calendar_id`.

**The sync rules**, evaluated after every event write:

| Situation | Action | `calendar_sync.reason` |
|---|---|---|
| block is incomplete | skip | `incomplete` |
| block crosses midnight | skip | `crosses_midnight` |
| photo event | skip | `not_applicable` (unchanged) |
| calendar not configured | skip | `calendar_not_configured` (unchanged) |
| has `calendar_id`, Mazkir owns it | patch | — |
| has `calendar_id`, another calendar | skip | `not_in_mazkir_calendar` |
| no `calendar_id`, now complete | create, store the id | — |

The last row is what makes *"sync it once it's complete"* work without a flag to remember: the presence of `calendar_id` already records whether the block is in the calendar, and the edit that fills the last missing field is what triggers the create.

**A consequence worth taking.** PR #15 handles a cross-date move by detaching `source_ids` into `moved_from_source_ids` and marking the event `manual`, because the Google entry stays on the old day and `reconcile` at the target date would otherwise delete the moved row. That workaround exists *only* because there was no way to move the Google entry. With `CalendarService.update_event` available, a move of a Mazkir-owned event patches the upstream entry's date too — the entry moves, `reconcile` at the new date matches it, and the block keeps tracking its source instead of being orphaned into `manual`. The detach path stays for events Mazkir does not own, where it remains the only correct answer.

Every branch emits the existing `{ok, attempted, reason?, event_id?}` shape, so the agent's reporting rule keeps working unchanged — and `attempted: true` on a real failure still means "tell the user this did not happen."

## 7. Surfacing

### 7.1 `/day` renders incomplete blocks

A new section below the timeline, in the same rich-message body as the rest of the view:

```
  ── needs a time ──
  ⁇ Dog walk          ended 16:40, no start
  ⁇ Lunch             13:00, no end
```

Read-only text, no buttons: completing a block happens by talking, and a button that opens a conversation is new machinery this ship does not need. The section is omitted entirely when empty.

### 7.2 Mazkir raises them — push, not pull

Ship 3's finding applies directly: the agent will not call a tool to discover something it does not know to look for. Bug B was not a capability gap — the agent held two read tools and used neither.

So incomplete blocks go **into the context**, as one line in the dynamic system tail built alongside `Current date/time` in `agent_service.py`:

```
Incomplete blocks today: 2 (Dog walk — no start time; Lunch — no end time)
```

This is cheap. Incomplete blocks are always user-created, so they are always in the persisted store: a local file read, not a merge, and no network on the per-turn path.

The accompanying prompt rule is deliberately restrained — mention them once, when it is natural, and drop it if the user does not engage. The failure mode of a nag is that the user stops reading the replies, which costs more than an unfinished block.

## 8. What this ship does not do

- **Approval.** `state` stays a stub; every block counts the moment it is written. Ship 5.
- **The classification queue** and `misc` as a bucket. `activity` is settable here, but nothing asks for it. Ship 6.
- **Ordinals and batch edits.** Addressing is descriptive only. Ship 7.
- **Timers.** Ship 8.
- **Calendar sync for midnight-spanning blocks**, and cross-fragment edit propagation. §3.3.
- **Inferred durations.** Mazkir asks rather than guesses. Inference is Ship 5, and the guessing is not good enough yet.
- **Working out what to log from a message that did not ask.** Multi-intent extraction, habit matching against prose rather than habit names, and a policy for volunteered facts are Ship 4b — see the parent document §12. This ship makes the ledger able to *hold* what such a layer would produce; it does not produce it.
- **Deleting a source-derived block permanently.** PR #15's `reappears_from_source` is the honest answer until Ship 5's unapprove exists.

## 9. Testing

**`events_service`** — `user_set` survives reconcile; is re-applied *after* the fresh overwrite; recomputes `duration_minutes` when it moves an end; ignores non-settable keys; an empty map is a no-op. `revert_fields` restores source tracking. `is_complete` across all four presence combinations. The inverted-interval rejection, and `end == start` still accepted. `updates` is not mutated.

**`create_event`** — each of the three two-of-three derivations; three consistent values accepted; three inconsistent rejected with `SCHEMA_INVALID`; one value yields an incomplete block that is persisted and not synced; cross-midnight produces two fragments in two files sharing one `logical_id`, with correct per-fragment durations and `reason: "crosses_midnight"`.

**`block_resolver`** — each rung of the ladder; unique substring; ambiguous substring; fuzzy above and below the floor; the `SCORE_AMBIGUOUS_DELTA` tie; candidates carry their date. Searching two dates finds a block on either and reports ambiguity when both have one.

**Event tools** — `update_event` by `block_reference` materialises an unpersisted calendar block and pins the change; the pin survives a subsequent reconcile (the §1.2 regression, asserted directly); `shift_minutes` moves both ends; `delete_event` by reference. `list_events` returns the reconciled view, not the raw file.

**Calendar** — every row of §6's table, asserted on the emitted `calendar_sync`; a block completed by an edit gets created and its id stored; a non-Mazkir calendar reports `not_in_mazkir_calendar` without calling the API.

**`/daily`** — `incomplete[]` is populated and `blocks[]` is not, for a block missing an end; coverage and gaps are unchanged by its presence; an event belonging to another day is still dropped rather than reported incomplete.

**Bot** — `selected_date` is attached while the day view is the last sent message and dropped after any other send; the incomplete section renders and is omitted when empty.

**Agent context** — the incomplete-blocks line appears in the dynamic tail and is absent when there are none.

## 10. Open questions and carried forward

**Resolved by this design:** the parent document §10's selected-date propagation question — bot-supplied, dropped when the day view is no longer the last message sent (§5).

**Still open, unchanged:**

- **Week bar rendering** — needs a real-device check on narrow screens before committing to 7 buttons.
- **Todo/Task rename** — unresolved since Phase 1, still recommended out of this work.
- **Token economics for logging** — Ship 9.
- **Timer UX** — Ship 8.

**New, deferred:**

- **Unpinning UX.** `revert_fields` is a tool parameter with no natural phrasing behind it yet. Whether *"use the calendar's name for that"* should route to it is a prompt question this ship does not answer.
- **Pins on a block that later loses its source.** If a calendar event is deleted upstream and `reconcile` drops the persisted event, its `user_set` goes with it. Correct today, but worth revisiting when Ship 5 makes approved blocks durable.
