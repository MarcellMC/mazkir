# Time Management Phase 2 — Capture Surface (Design)

**Status:** Design, approved in conversation 2026-08-21. Not yet planned.
**Parent:** `docs/plans/2026-07-27-time-management-system-design.md` (Block A). That doc owns the *data model*; this one owns the *interaction*.
**Phase 1 shipped:** PR #8 (`c911d43`), vault commit `cf14ac1`.
**Ship 1 shipped:** PR #9 (`3eb8b2c`), vault commit `fb824da`.
**Ship 2 shipped:** PR #11 (`934c003`).
**Ship 3 shipped:** see `docs/superpowers/specs/2026-09-05-ship3-agent-action-memory-design.md`.

> **Two decisions from the Ship 2 design supersede parts of this document.**
> 1. The events ledger is the source of truth for temporal data; daily notes are a worksurface. A timed checkbox becomes a block by *inference*, regenerated on every open — so promotion needs no write path. See the Ship 2 design §2.1.
> 2. Rich messages **are** editable (`editMessageText.rich_message`, Bot API 10.1) and carry their own buttons (Bot API 10.3). This retires §3's `·20·` selected-state hack, and likely retires §3's numeric block picker for Ship 5 — an inline button *can* sit on a block's row. See the Ship 2 design §2.2.

## 1. What changed the plan

Phase 1 made the ledger correct. Two live failures on 2026-08-20 then reshaped what Phase 2 should be, and both are more instructive than the features they displaced.

**Bug A — `/day` hides untimed todos.** `routes/daily.py:95` filters daily checkboxes on `scheduled_at`, so a todo with a duration but no start time is parsed and then dropped. The user added two todos, they were written correctly, and they were invisible. See §8.

**Bug B — the agent denied a write it had made.** The todos *were* added successfully on the first attempt. Asked "where did you add those?", the agent called no tools, reasoned from its current skill's tool list, and concluded it had never been able to add them — then added them again, producing duplicates. See §9.

Bug B is the more serious of the two, and it exposed that §3.4's invariant is one-directional: Phase 1 forbade *claiming* an unconfirmed write, but said nothing about *denying* an unchecked one. The mirror failure costs just as much trust and, here, corrupted data.

A third input, from the same session: **daily todos already carry `duration_minutes`.** An unscheduled todo is therefore a block with a known length and no start time yet — exactly the raw material a planning-stage suggester needs. Bug A and that idea are the same shape.

## 2. Ship order

Value-ordered rather than phase-ordered. Each ships independently.

| # | Ship | Size | Why here |
|---|------|------|----------|
| 1 | See my todos (Bug A) | ~2 | Highest value, no dependencies |
| 2 | [Navigable `/day`, rendering blocks read-only](../superpowers/specs/2026-08-29-ship2-navigable-day-design.md) | ~6 | The surface everything later writes to |
| 3 | Bug B — the agent can't deny its own work | ~3 | Before any new write path inherits it |
| 4 | NL logging + simple single edits | ~5 | The only capture path sleep and meals will ever have |
| 5 | Inferred capture: suggested→approved, gaps | ~6 | Reduces typing once capture already works |
| 6 | Classification | ~4 | Needs blocks to classify |
| 7 | Batch edit → preview → accept all | ~4 | Needs blocks *and* addressing |
| 8 | Timers | ~2 | NL already covers this ground retrospectively |
| 9 | Weekly readout | ~5 | The old "2b" |

**Why NL logging (4) precedes inference (5).** Sleep and eating have no automatic signal — no calendar entry, no distinguishable location, no habit fires. They are also the two buckets the user most wants to fix. Shipping inference first fills `dev` and `work` (which the calendar already covers) while leaving those two empty, which is precisely backwards. After Ship 4 a full day can be logged by talking; Ship 5 then makes it *cheaper*, not *possible*.

## 3. The `/day` surface

`/day` becomes a browsable day viewer with an edit mode, replacing the current one-shot feed. It is the entry point; there is no separate `/reconcile`.

**View mode.** Opens today and sets it as the selected date. Navigation re-renders the *same* message.

```
Thu 20 Aug · today                     11.2h accounted · 3 pending

  07:00–07:40  Dog walk         dog × personal        ✓
  09:05–10:00  Standup          meetings × work       •
  10:00–13:00  Feature work     dev × work            •
  ⚠ 13:00–14:15  unaccounted                       1.2h
  ─────────────────────── now ───────────────────────
  19:00–20:00  Dog walk         dog × personal        ⟳

  ── todos ──
  ☐ Order dog food (30m)
  ☐ Bring the bicycle to repair shop (60m)

  [ 17 ][ 18 ][ 19 ][·20·][ 21 ][ 22 ][ 23 ]
  [  ◀  ][   ✎ edit   ][  ▶  ]
```

`✓` approved · `•` elapsed, awaiting approval · `⟳` still ahead, not approvable.

**Week bar.** Feasible — Telegram allows up to 8 buttons per row and numeric labels render on narrow screens. Inline keyboards have no selected state, so the current day is marked in the label itself. **Needs a real-device check before committing.**

**Edit mode.** The `✎ edit` button re-renders the same message with blocks numbered and a compact numeric keyboard. Telegram cannot attach a keyboard to a row, so blocks are addressed by number:

```
[1][2][3][4][+ gap]        ← numbers only, 5 per row
[ approve all ][ ← back ]
```

Tapping a number opens a per-block menu — approve, dismiss, change activity, change times — with back returning to the list. `dismiss` drops a *suggested* block from the current view only (§4: dismissal is not persisted); on an *approved* block the same slot reads `unapprove` and returns it to suggested. There is no separate delete, because an unapproved block is already uncounted. Ten blocks is two compact rows, not ten towering ones.

**Cross-midnight.** The view shows *logical* blocks; storage splits at 00:00 (Phase 1, §4.2). Approving a block spanning midnight approves both fragments. Otherwise last night's sleep would need approving twice on two different days — unworkable for the one habit most in need of measurement.

## 4. Ledger behaviour

**Re-inference on every open**, reconciled against already-approved blocks by `source_id`, reusing the events store's existing refresh matching.

**Two states only:**

```
suggested   ephemeral. Regenerated by inference on every open. Never persisted.
approved    persisted, counted. Matched by source_id so re-inference keeps
            it rather than duplicating it.
```

**No `rejected` tombstone.** An earlier draft proposed one so re-inference could not resurrect a dismissed block. It was dropped because rejected and never-approved are *identical* to the numbers — only approved blocks count — which makes rejection display state, not data. Tombstones would have added a third state to every read path and accumulated dead records indefinitely, to prevent one extra dismissal on a day being actively worked.

This also dissolves the parent doc's §11 retention question: ephemeral suggestions need no retention policy.

**Residual, accepted:** dismissing a block and later tapping `approve all` without reading will sweep it back in. That is the same exposure as approve-all over any wrong suggestion, and is addressed by §5's confidence handling rather than by persisting dismissals.

## 5. Classification

**`misc` is a real activity bucket, not `unaccounted`.** These are different states and conflating them corrupts coverage:

- `unaccounted` — no idea what happened in this span. A genuine gap.
- `misc` — the time is fully accounted; only its label is missing.

Filing the second under the first makes coverage look worse than reality and hides real gaps behind noise. `misc` takes a share in the matrix, carved from `unstructured`. A rising `misc` line is then its own signal: either too much is being skipped, or a bucket is missing.

**The prompt sits after approval**, as a skippable per-block queue. Approve-all is never blocked.

Note the ship boundary: **Ship 5 delivers approval without any classification queue** — blocks approve with `activity` unset. **Ship 6 adds the queue.** Between the two, unclassified time is visible as such rather than silently bucketed, which is the same principle as §5's `misc`/`unaccounted` split.


```
[ approve all ]  → "Approved 7. One needs an activity:"
                     [ shopping ][ slack ][ eat ][ other… ][ skip ]
                  → "Noted — Dizengoff Center → shopping."
```

- Candidates come from the matrix, ranked by the classifier's best guesses.
- `skip` files it as `misc` — a decision, never asked again.
- **Ignoring** the queue leaves the block unclassified; it re-queues next reconciliation. Skip closes it, ignoring defers it.
- Title → facet mappings are remembered, so the ask-rate decays to near zero within weeks. This is what makes asking affordable rather than a daily tax.

**Resolution order** (parent doc §3.2, unchanged): explicit on the item → calendar-name rule → classifier → remembered mapping → no match.

**`other…` creates a bucket.** A new activity that isn't in the matrix yet can be created at the moment of classification. **New buckets enter at share 0**, so the sum-to-100 validation still passes unchanged and the readout surfaces them as unbudgeted — *"4h on `reading` with no allocation, want to give it one?"* That is the matrix-revision-proposal mechanism arriving early and for free.

*Implementation consequence:* `time_matrix.py` becomes read-write. PyYAML drops comments on round-trip, which would destroy the seed file's explanatory header — so either `ruamel.yaml` for round-trip fidelity, or targeted text insertion rather than full re-serialisation.

## 6. NL logging and correcting

Two different capabilities that an earlier draft wrongly lumped together.

**NL logging** creates a block — *"slept 03:05 to 12:15"*, *"just got back from the dog walk"*. Depends only on the events store and one tool. Ships at #4.

Retrospective phrasing (parent doc §4.3) is part of logging quality: the distinction that matters is **which end of the interval the utterance anchors**. Getting it backwards shifts the block by its own length, which is what happened on 2026-08-16.

**NL correcting** modifies an existing block — *"move gym -30m"*, *"2 was dev not meetings"*. Needs blocks to exist *and* a way to address them (§7). Simple single corrections by descriptive reference ship at #4; the batch flow ships at #7.

**Batch edit → preview → accept** (parent doc §4.1) stays as designed: several edits in one message, one preview showing the resolved intervals, one approval. Nothing is written until the tap.

## 7. Addressing blocks

**The 2026-08-20 numbering bug.** `formatTasks` numbers file-tier tasks only, high→medium→low. `_tool_list_tasks` numbers daily todos first, *then* file-tier. With two daily todos present, "complete 1" resolves to a different item than the one on screen — silent wrong-item resolution, not a failure to resolve. The `"n": n` comment claiming "matching UI order" is exactly the assumption that rots when two files own the same rule.

**Rule:** ordinals are never stored. One deterministic sort per item type, implemented identically on both sides, so both compute the same numbers from the same data:

| type | sort |
|---|---|
| events / blocks | start timestamp |
| tasks | priority, then alphabetical |
| goals | alphabetical |

**Open:** an event ordinal only means something relative to a selected date, so the agent must know which day is on screen when the user types "2 was dev not meetings". Candidate approaches — the bot passing `selected_date` on `POST /message`, versus server-side per-chat state — are recorded in §10 pending a decision.

## 8. Bug A — untimed todos are invisible

`routes/daily.py:95` requires `scheduled_at`, so a todo with `duration_minutes` and no start is dropped. Verified against the live note: both todos parse, both filtered out.

**Fix (Ship 1):** `/day` returns untimed daily todos as their own list alongside the schedule, and the bot renders them. Purely additive — no dependency on the block redesign, so it ships immediately.

**Forward-looking:** an untimed todo carrying a duration is a *block candidate* — known length, no start time. Ship 9 and the parent doc's day-schedule suggestions should treat it that way rather than inventing a separate concept.

## 9. Bug B — the agent can't deny its own work

**What happened.** Turn 1 routed to `time-management`, which holds `daily_add_task`; both writes succeeded. Turn 2 ("where did you add those?") is a question, so the router sent it to `mazkir`, whose tool list has no task-creation tool at all. The agent inspected its *current* tools, found none, and reasoned backwards to "I actually didn't add them." It held `read_daily_section` and `get_daily` and used neither — one iteration, zero tool calls, straight to a confident denial.

**Root cause.** The agent reasons about past actions using the current turn's capabilities. Conversation memory stores what it *said*, never what it *did* or what it could do at the time, so a skill hop silently rewrites its sense of its own past.

**Fix, two halves:**

1. **Make the past factual.** *(Shipped, Ship 3.)* `MemoryService.assemble_context` reads this chat's records from `data/logs/agent-turns.jsonl` and attaches each turn's tool calls to the assistant message that turn produced. `services/turn_trace.py` owns it.
2. **The mirror invariant.** §3.4 forbids reporting a write the tool result does not confirm. Add its complement: **never deny a past action without checking.** Read tools are available in every skill; the failure was behavioural, not capability.

**Secondary finding:** `agent-turns.jsonl` records tools but not the routed skill, which made this materially harder to diagnose. Worth adding while touching that code. Fixed in Ship 3 — `_run_agent_turn` now takes `skill` and records it.

## 10. Open questions

- **Selected-date propagation** (§7) — bot-supplied on `POST /message`, or server-side per-chat state. The first avoids a second copy of something the message already encodes; the second lets any surface set it. Undecided.
- **Week bar rendering** — needs a real-device check on narrow screens before committing to 7 buttons.
- **Todo/Task rename** — unresolved since Phase 1. Still recommended out of this work.
- **Token economics for logging** — rate per block, per approved day, or per streak, and how it interacts with `tokens_per_completion`. Deferred to Ship 9.
- **Timer UX** — the interaction (`/start dev`, keyboard, NL phrase) is unspecified. Deferred to Ship 8.

## 11. Carried forward from Phase 1

- `habits.py` reads "today" in `VAULT_TIMEZONE` but writes via the server clock — inert while they match. Fix in Ship 5, which is the code that cares.
- `packages/shared-types` and the bot formatter do not surface `completions_today` / `daily_target`, so the bot shows a binary checkbox where the API can say 1/2. Fix in Ship 2, the same rendering pass.
- `CLAUDE.md` has two stale claims: the "known pre-existing `import.meta.env` errors" no longer reproduce, and the webapp section still lists a `dayplanner/` feature that is now `time-management/`. Fix in Ship 1.
