# Time Management System — Design

**Status:** Design. Revised 2026-08-17 after a full brainstorming pass; supersedes the 2026-07-27 draft.
**Parent doc:** `docs/plans/2026-07-27-p6-roadmap-and-agentic-frameworks.md` (Block A)
**Scope:** a time-accounting ledger, a weekly proportional readout, and a multi-completions-per-day fix for habits. The day-schedule suggestion feature is deferred to v2 — see §9.

## 1. What this is

The system exists to serve one loop, in this order:

**log → measure → plan → perform.**

Each rung is useful on its own, and each is a precondition for the next. The 2026-07-27 draft started at *plan* — a matrix config plus a greedy allocator — but nothing in Mazkir records how long anything takes, so the allocator would have been built against a guess. It also assumed a hand-maintained matrix, which is the one artifact the user has said he won't maintain: the sketch was drawn 2026-06-20 and has been inert prose ever since.

So the order is inverted. **v1 is log + measure only.** Once several weeks of real data exist, the observed distribution seeds the matrix and the allocator gets built against fact.

Two goals shape everything below:

- **Motivation is an output, not a side effect.** The token ledger and streak fields already exist and go unused. Logging should earn tokens and the weekly readout should read as an achievement view, not a variance report. This is the thing that makes the loop self-sustaining.
- **This is meant to ship.** No category name appears anywhere in code — categories are user data throughout, and a fresh user with no sketch must be able to bootstrap by logging.

### 1.1 v1 scope

| In v1 | Deferred to v2 |
|---|---|
| Block ledger (extended events store) | Day-schedule suggestions |
| Three write paths + approval gate | GCal push of suggested blocks |
| Reconciliation via Telegram + NL | Webapp reconciliation + day timeline |
| Weekly proportional readout | Matrix revision proposals from real data |
| Habit multi-completion fix (§7) | Tag query engine |
| `scheduled_at` / `scheduled_time` bug (§8) | `tm-day-bd` bug (§8) |

## 2. Data model

### 2.1 Blocks live in the events store

The ledger extends `data/events/{date}.json` rather than introducing a parallel store. The existing event shape already carries `start_time`, `end_time`, `duration_minutes`, `source`, `source_ids`, and a merge-and-preserve refresh algorithm fed by exactly the sources the ledger needs.

```jsonc
{
  // existing, unchanged
  "id": "evt_a1b2c3d4",
  "name": "Mazkir refactor",
  "start_time": "2026-08-17T20:00:00",
  "end_time":   "2026-08-17T22:30:00",
  "duration_minutes": 150,
  "source": "manual",
  "source_ids": {}, "photos": [], "assets": null, "location": null,

  // repurposed
  "activity_category": "dev",       // now the activity facet (§2.2)

  // new
  "domain": "personal",             // the domain facet (§2.2)
  "tags":   ["mazkir"],             // free, optional, never required
  "state":  "approved"              // "suggested" | "approved" (§3.3)
}
```

`source` gains `timer` and `manual` alongside the existing `calendar`, `timeline`, `merged`, `habit`.

There is deliberately **no** separate `bucket` field. An earlier draft added one and it duplicated `activity_category`; instead `activity_category` keeps its name and takes on a stricter, user-defined vocabulary. `CATEGORY_KEYWORDS` moves out of `merger_service.py` and into user config (§3.2) — which the shipping goal required anyway.

Consequences to accept: `generation_service.py` builds image prompts from `activity_category`, so prompts shift from `"representing cafe activity"` to `"representing dev activity"` — duller, tolerable. Existing event files carry `gym|walk|cafe|shopping|social` values that are not activity names; they are left alone and simply read as unmatched, since the readout only covers weeks after logging begins.

### 2.2 Two facets, not a tree

An activity has two simultaneous truths, and a flat list records only one. A single-parent tree does not fix this — it forces cross-cutting activities to be duplicated as separate nodes, so "total dev hours" spans branches the tree says are unrelated.

Every block therefore carries two required, independent axes:

| | activity — *what were you doing* | domain — *whose was it* |
|---|---|---|
| SWE day job | `dev` | `work` |
| pet project | `dev` | `personal` |
| music hobby | `music` | `personal` |
| music, once paid | `music` | `work` |
| accounting (job) | `org` | `work` |
| accounting (home) | `org` | `house` |
| workout | `fitness` | `personal` |

Each axis is a complete partition, so both sum to 100% of the week independently. Every case above is a re-tag rather than a restructure — music turning professional flips one field.

This also explains why the original hand-drawn matrix does not add up: `dev`, `org` and `music` are activities while `work` and `house` are domains. The sketch mixed both axes into one column.

**`work` is therefore not an activity at all.** Nobody spends an hour "working" — they spend it on `dev`, `org` or `meetings`, and what makes those hours the day job is the *domain*. The activity axis lists only things you can actually be observed doing; `work` appears solely as a domain. The same reasoning applies to `house`, which is a domain, though `house` also survives as an activity meaning chores specifically.

`tags` is a third, free-form layer that nothing depends on being complete — project names, contexts, `outdoors`. It carries no weight in v1; the query engine that reads it is v2. It exists in v1 purely so the data is there on the day queries are wanted.

### 2.3 Targets: `memory/00-system/time-matrix.yaml`

Targets are **proportions, not absolute hours**. "18h dev" is a number that has to be defended every week; "11% of my week on dev" self-normalizes across a week with a wedding in it, and it cannot fail to add up.

The denominator is the **full 168 hours, sleep included**. That is what makes the sustainability question impossible to hide: a plan leaving five hours a night is visible on its face.

```yaml
version: 2
# Shares are % of the 168-hour week. Each axis must sum to 100.

activities:
  sleep:        { share: 33 }
  dev:          { share: 17 }   # day job + pet projects, split by domain
  org:          { share:  9 }
  eat:          { share:  7 }
  house:        { share:  7 }
  meetings:     { share:  6 }
  slack:        { share:  5 }
  commute:      { share:  4 }
  fitness:      { share:  3 }
  dog:          { share:  3 }
  music:        { share:  3 }
  unstructured: { share:  3 }

domains:
  personal: { share: 58 }
  work:     { share: 21 }
  house:    { share: 21 }

calendars:                                   # see §3.2
  "Work":   { activity: work, domain: work }
  "Mazkir": { activity: dev,  domain: personal }
```

Each axis is **validated on load with a hard error if it does not sum to 100**, making "my table doesn't add up" structurally impossible rather than something to notice later.

Ground truth for the seed values is the photo at `memory/00-system/media/2026-06-20/photo_2026-06-20_05-00-22.jpg`, not the knowledge note `60-knowledge/notes/time-management-matrix-sketch.md`, whose transcription is garbled (`mux` for music, `work 30-30`, spurious `hack` / `Wars` rows). The note stays a knowledge artifact and is not a data source. Matrix rows read from the photo: dev 18h/wk · 5–6 d/wk · 2 h/day; org 0–3 h/day; music 3–6 h/wk · 5–6 d/wk · 0–6 h/day; work 30–36 h/wk · 1–6 d/wk (marked ⊗ immovable); house 7 d/wk · 1–2 h/day; dog (marked ° mandatory); plus `other`, `unstructured`, `commute`, and the `inflatory` bucket for force-majeure overruns.

`fitness` is a new activity with no row in the sketch — `workout` had no home in the original matrix. Expect the sum-to-100 rule to keep surfacing gaps like this.

**The matrix is not a file the user maintains.** It is seeded once from the sketch as a rough prior. From v2 onward Mazkir proposes revisions from observed data — *"you've targeted 11% dev and hit 6% three weeks running; lower the target or protect the time?"* — accepted or adjusted in one tap. An assistant that keeps your intentions current is the product; a config file you hand-edit is the thing that went inert for two months.

## 3. How blocks are created

### 3.1 Three write paths

- **Inferred** — Google Calendar events, Google Takeout location visits (`timeline_service`, which already yields per-visit durations), and scheduled habits.
- **Live** — timer start/stop.
- **After the fact** — natural-language logging, and habit completions (which mint a block via a post-hook, structurally identical to the existing `sync_to_calendar` hook).

There are **no default or filler blocks**, and no declared baseline for sleep, meals or commute. Those hours are unpredictable and making them predictable is itself a goal, so they must be measured rather than assumed. Auto-filled blocks would also be fiction counted as measurement, which corrupts the one thing v1 exists to produce.

Mazkir may still *suggest* a sleep or meal block from the previous day or the week's pattern. A suggestion is not a log — see §3.3.

### 3.2 Classification

Assigning facets to an inferred block, in precedence order:

1. **Explicit on the item** — a habit's own `activity_category` / `domain`, or an inline `#dev` tag on a daily todo, or the user said so in an NL log.
2. **Calendar name** — the `calendars:` map in §2.3. Highest leverage by far: one rule covers hundreds of events forever, with zero curation, and GCal is already filtered by `GOOGLE_CALENDAR_INCLUDE`.
3. **Haiku classification** — the existing router model classifies unmatched titles against the user's own vocabulary. Handles titles never seen before.
4. **Remembered** — the first resolution of a title is stored as a title → facets mapping, so recurring events cost one classification ever and a personal dictionary accumulates by itself.
5. **No match** → `unaccounted`, never `other`. A silent dump bucket would let the readout claim full coverage while telling you nothing.

Explicitly rejected: hand-curated keyword match lists. They are exactly the maintenance chore this design is trying to remove.

### 3.3 Nothing is logged without approval

Every block enters as `state: "suggested"` regardless of source — calendar and location-derived blocks included. A calendar event is an *intention*: meetings get cancelled and deep-work blocks get skipped, and counting those as logged hours is the most likely way the readout ends up flattering its reader.

Only user approval promotes `suggested` → `approved`. **Only `approved` blocks count toward the readout.**

## 4. Editing

### 4.1 Batch edit → preview → accept

Reuses machinery that already exists: `AgentResponse.confirmation_choices` already renders server-named options as an inline keyboard, and destructive tools already render a preview before executing. Applied to a batch of edits:

```
You     move gym -30m
        2nd dog walk ended 01:45
        slept 03:05 to 12:15

Mazkir  gym         18:00–19:00  →  17:30–18:30
        dog walk 2  23:30–00:15  →  23:30–01:45 ⁺¹
        sleep         — none —   →  03:05–12:15

              [ accept all ]   [ revise ]
```

Several edits, one round-trip, one approval. Nothing is written until the tap.

### 4.2 Cross-midnight

A common case, not an edge case. One rule at parse time: **if `end < start`, the end is the next day.** `23:30 → 01:45` wraps; `03:05 → 12:15` does not.

Storage **splits the block at midnight** so each date file owns only its own hours, which keeps weekly aggregation a plain sum over seven files. Display **rejoins** the fragments, showing `23:30–01:45 ⁺¹` as one row. Split for storage, joined for display.

## 5. Coverage, overlap and unaccounted time

Concurrent activities are real — eating while watching a lecture — and both deserve to be recorded. **Overlapping blocks are allowed.**

What makes this safe is computing unaccounted time from **gaps in wall-clock coverage**, not from `168 − sum(activity hours)`:

```
unaccounted = 168h − |union of all approved block intervals|
```

That is exact regardless of overlap: two blocks covering 19:30–20:15 is still just "covered". Gap detection never depended on the sum.

The cost is only that the activity column no longer sums to 168, which is fine as long as the readout says so. Targets are authored as shares and displayed as hours; actuals are raw hours; coverage and concurrency get their own lines.

This also keeps an important failure visible: with overlap allowed, a target can be **hit by double-counted hours** — 18h of dev, four of them dev-while-commuting. The `concurrent` line is what stops that from flattering the reader.

No `secondary_activity` field, and no primary/secondary ranking. Just intervals that may overlap.

## 6. Surfaces (v1)

Telegram and natural language only. No frontend work in v1.

**Telegram** handles approval well — inline keyboards give approve / reject / skip per block, a pattern this bot already uses throughout. It has no good primitive for editing a time range: no time picker, no drag-to-resize. So approval lives here, correction does not.

**Natural language** handles adding and correcting: *"slept 23:15 to 6:45"*, *"the 2pm block was dev, not work"*, *"add 40m dog walk at 7"*, resolved through the batch flow in §4.1.

**The weekly readout** renders as a monospace block in Telegram (`/week`):

```
Week 33 · Mon–Thu · 96h elapsed

                target   actual                  vs
  sleep          31.7h    27.5h   ▓▓▓▓▓▓▓▓░░   −4.2
  dev            16.3h    14.0h   ▓▓▓▓▓▓▓▓▓░   −2.3
  org             8.6h     7.0h   ▓▓▓▓▓▓▓▓░░   −1.6
  eat             6.7h     6.0h   ▓▓▓▓▓▓▓▓▓░   −0.7
  house           6.7h     7.5h   ▓▓▓▓▓▓▓▓▓▓   +0.8
  meetings        5.8h     8.0h   ▓▓▓▓▓▓▓▓▓▓   +2.2
  slack           4.8h     6.0h   ▓▓▓▓▓▓▓▓▓▓   +1.2
  commute         3.8h     5.0h   ▓▓▓▓▓▓▓▓▓▓   +1.2
  fitness         2.9h     1.0h   ▓▓▓░░░░░░░   −1.9
  dog             2.9h     4.0h   ▓▓▓▓▓▓▓▓▓▓   +1.1
  music           2.9h     0.0h   ░░░░░░░░░░   −2.9
  unstructured    2.9h     6.0h   ▓▓▓▓▓▓▓▓▓▓   +3.1
  ────────────────────────────────────────────────────
  by domain      target   actual                  vs
  personal       55.7h    51.0h   ▓▓▓▓▓▓▓▓▓░   −4.7
  work           20.2h    27.0h   ▓▓▓▓▓▓▓▓▓▓   +6.8
  house          20.2h    14.0h   ▓▓▓▓▓▓▓░░░   −6.2
  ────────────────────────────────────────────────────
  coverage       88.0h of 96     ▓▓▓▓▓▓▓▓▓░    92%
  unaccounted     8.0h
  concurrent      4.0h   counted under two activities

  🔥 dog walk 6   🔥 workout 2   ·   +45 tokens this week
```

The reconciliation view is the same data for a single day, with gaps flagged as the only thing actually asking for attention:

```
Yesterday · Wed 16 Aug                    103 / 168h accounted

  07:00–07:40  Dog walk            dog × personal      habit
  08:30–09:05  Commute             commute × work      timeline
  09:05–10:00  Standup + reviews   meetings × work     gcal
  10:00–17:40  Feature work        dev × work          gcal
  18:10–19:00  ⚠ unaccounted       —
  20:00–22:30  Mazkir refactor     dev × personal      gcal

        [ approve all ]   [ fix 18:10 ]   [ revise ]
```

The webapp day timeline is v2. Rendering overlap there is the standard calendar problem with the standard answer — concurrent blocks split the column — so it is a rendering decision, not a data-model one.

## 7. Habit multi-completions per day

A real bug, found by live testing. `_tool_complete_habit` (`agent_service.py:2805`) rejects a second same-day completion outright:

```python
if habit["metadata"].get("last_completed") == today:
    return err(ErrorCode.ALREADY_DONE, ...)
```

This blocks habits like dog walking that legitimately need several completions a day. The habit template already carries an unused `## Completion Log` section; the handler only ever touches frontmatter.

Fix:

- Add `daily_target` (int, default 1), **orthogonal to `frequency`** (which stays about how often per week). Dog walking: `frequency: daily`, `daily_target: 2`.
- Use the **Completion Log** as the source of truth for today's progress — append a timestamped entry per completion and count today's entries, rather than a mutable counter that can drift. This finally makes the template section meaningful.
- Return `ALREADY_DONE` only once today's count reaches `daily_target`.
- **Tokens** awarded on every completion, as today. No special casing for partial days.
- **Streak** advances only once `daily_target` is fully met, so one of two dog walks does not advance it. Keeps the streak meaning "I did enough today".

Habits also gain `activity_category`, `domain` and `default_duration_minutes`, so a completion mints a correctly-faceted block. These are explicit rather than classified because there are five habit files and they are authored once.

This section depends on nothing else in the design and can ship first.

## 8. Bugs folded in

- **`scheduled_at` vs `scheduled_time`** (v1). `GET /day` reads `habit.metadata["scheduled_at"]` (`api/routes/daily.py:96`) but `memory/00-system/templates/_habit_.md` writes `scheduled_time`. Habits created from the template never appear on the schedule. Pick one name and migrate.
- **`tm-day-bd`** (v2). A floating caption block that glides over images in the time-management note feed but stops as the timeline scrolls down. Original intent unclear; needs investigation before a fix, so it moves to v2 rather than being assumed small.

## 9. Deferred to v2

- **Matrix revision proposals** from observed data — the mechanism that keeps the matrix alive without hand-editing.
- **Day-schedule suggestions.** Still pull-only: computed on access from live state, never precomputed or cached, so completing something simply changes the inputs for the next computation and no separate reflow logic is needed. Still a simple rule-based greedy fill, not an optimizer.
  - **Open problem to solve before building it:** the matrix as drawn has no slack. Work 30–36, dev 18, music 3–6, house 7–14, plus commute, dog, org, meals and sleep, consumes essentially all 168 hours. A greedy filler on a budget with no slack always emits a completely packed day — so a feature called "sustainable day schedule" would, as specified, guarantee an unsustainable one. Either the matrix needs a protected slack bucket the filler may not touch, or the filler needs a hard cap on how much of a day it may claim.
- **GCal push** of suggested blocks, on demand via the existing `/sync_calendar` rather than a continuous auto-sync.
- **Webapp** reconciliation view and day timeline.
- **Tag query engine** — targets expressed as queries over `tags` (`"dev AND NOT work"`), as a secondary view alongside the facet readout rather than replacing it.
- **`tm-day-bd`** (§8).

## 10. Changed from the 2026-07-27 draft

| Then | Now | Why |
|---|---|---|
| Flagship was the day-schedule allocator | Allocator is v2; v1 is log + measure | Nothing records durations, so the allocator had no input and would be built against a guess |
| Absolute hours per week | Proportional shares of 168h, sleep included | Absolute hours never balance and need manual rebalancing; shares self-normalize and make the sustainability squeeze visible |
| Hand-authored `time-matrix.yaml` | Seeded once, then Mazkir proposes revisions from data | The hand-maintained artifact is the one that went inert for two months |
| One flat category list | Two facets (activity × domain) + free tags | A flat list cannot express "pet project is dev and personal"; a tree would duplicate cross-cutting nodes |
| New `bucket` field | `activity_category` repurposed + new `domain` | `bucket` duplicated an existing field |
| `work` listed as a category | `work` is a domain only, never an activity | Nobody spends an hour "working" — they spend it on `dev`, `org` or `meetings` in the work domain |
| Time inferred from completed habits/tasks | Explicit block ledger with three write paths | Boolean completions carry no duration |
| Surfaced in webapp / `/day` / GCal | Telegram + NL in v1; webapp and GCal in v2 | `dayplanner` no longer exists — it was superseded 2026-06-20 by a note feed, so there was no day view to extend |
| `tm-day-bd` a trivial implementation-time fix | v2, needs investigation | Original intended behaviour is unknown |
| Todo/Task rename adopted now | Recommended out of this block — see §11 | Pure churn across skill prompts, `CLAUDE.md`, `AGENTS.md`, templates and tests, with no behaviour change, and unrelated to everything else here |

## 11. Open questions

- **Todo/Task rename.** Recommended out of this block and handled separately if wanted at all. Needs an explicit call.
- **Timer UX.** The live start/stop path is agreed in principle; the actual interaction (`/start dev`, an inline keyboard, an NL phrase) is unspecified.
- **Token economics for logging.** Logging should earn tokens, but the rate — per block, per approved day, per streak — is undecided, and it interacts with the existing `tokens_per_completion` on habits.
- **Retention of `suggested` blocks.** How long an unapproved suggestion survives before it is dropped, and whether approving a day retroactively approves its stale suggestions.
