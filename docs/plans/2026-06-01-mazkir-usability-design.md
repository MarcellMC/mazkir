# Mazkir Usability Overhaul — Design (Checkpoint)

**Status:** Brainstorm in progress. This is a mid-design checkpoint after Block D parts 1–2 are locked. Blocks A, B, C, E, F are pending. D3, D4 are pending.

**Goal:** Make Mazkir more usable. Standard vault operations must be reliable, deterministic, and guard-railed; common workflows must be obvious; only necessary context goes into LLM requests; all observability instrumentation gaps are closed.

---

## Scope: Blocks A–F

| Block | Theme | Status |
| --- | --- | --- |
| A | Correctness — vault ops are deterministic | pending design |
| B | Context optimization — only send what's needed | pending design |
| C | Observability — close gaps | pending design |
| D | Workflows, schemas, tools, sub-agents | D1+D2 locked here; D3, D4 pending |
| E | Broken integrations — GCal sync, media path | pending design |
| F | Latency (mostly falls out of A+B) | pending design |

---

## D1 — Workflows (grouped capture / plan / review)

### Capture (low-friction inbox)
- Capture text / quote / mood → daily note
- Capture photo → daily, optionally to event
- **Capture note onto an existing task / habit / goal** — handled by typed mutators' `append_note`
- Add new task / habit / goal
- Save knowledge note (free-text, taggable)
- Photo with GPS → auto-create event (automatic)

### Plan (structured, today / this-week)
- **Daily overview (`/day`) — redesigned as a time-based feed**
  - **Schedule** section: events from filtered Google Calendars + timed daily-tier tasks + timed scheduled habits
  - **Notes** section: today's captures + photos
  - No standalone Tasks section in `/day` (use `/tasks`)
  - No standalone Habits section in `/day` (use `/habits`)
  - Calendar filter via `GOOGLE_CALENDAR_INCLUDE` env-var allowlist (e.g. `"Mazkir,Work"`); drops national-holiday and other subscribed calendars
- `/tasks`, `/habits`, `/goals` — list views (unchanged)
- Day plan / events (webapp dayplanner) — unchanged
- Calendar sync (write-back to GCal) — **currently broken, Block E1**

### Review
- Recall + knowledge search — `search_knowledge` (folds `get_related`)
- End-of-day review — **parked** for now

---

## D — Schema design

Principle: **frontmatter holds current intent**, **body holds history & nested structure**.

### Task (file tier)

```yaml
type: task
name: ...
status: active
priority: 3
category: ...
scheduled_at: 2026-06-01T14:00     # ISO datetime, optional (null = unscheduled)
duration_minutes: 60                # optional
due_date: 2026-06-05                # hard deadline (existing field, semantics unchanged)
due_soft: 2026-06-03                # optional soft deadline
created: 2026-05-21                 # automatic; preserves original first-appearance date when promoted
updated: 2026-06-01                 # automatic
completed: null
```

### Habit

```yaml
type: habit
name: ...
frequency: daily
streak: 7
tokens_per_completion: 5
scheduled_at: "07:00"               # recurring "HH:MM" daily slot (null = anytime)
duration_minutes: 30                # optional
created: 2026-04-01
updated: 2026-06-01
last_completed: 2026-05-31
```

### Goal

```yaml
type: goal
name: ...
status: active
progress: 30
start_date: 2026-01-01
target_date: 2026-12-31
created: 2026-01-01
updated: 2026-06-01
completed: null
```

### Choices made (with rationale)
- **Flat fields, no `schedule:` group.** Cleaner Dataview queries, simpler mutators, only ~6 related fields.
- **`duration_minutes`, not `scheduled_end`.** More natural for time estimation; survives reschedule without paired-field updates; UI / GCal sync derives the absolute end.
- **Keep `due_date` (hard) + add optional `due_soft`.** Soft is a nudge (show as ⚠️ within 3 days); hard is the alert.
- **No `parent_*` fields.** Hierarchy lives as nested checkboxes in body. Avoids the "decrease complexity by adding complexity" trap.

### History — in body

Markdown `## History` section, **append-only**, maintained by mutators:

```markdown
## History
- 2026-05-21 14:00 — Created (due_date: 2026-05-30)
- 2026-05-23 09:12 — Postponed scheduled_at: 2026-05-22 → 2026-05-25
- 2026-05-25 14:00 — Note appended: "Migdal sent missing-docs message"
```

Format: `- YYYY-MM-DD HH:MM — <change summary>`. Every mutator change appends one line. Migration script can leave existing files alone (empty History section = "no recorded history").

### Migration

**Deferred.** Design ships first; migration script lands separately. Existing `due_date` semantics preserved → no change required for old files until they're touched.

---

## D — Two-tier task model

**Tier 1 — Daily-note checkbox** (default, ephemeral):
- Lives inline in the daily note's `## Tasks` section
- Standard Markdown checkbox: `- [ ] text`
- Sub-items: nested checkboxes (`- [ ] sub-task`), plain bullets (`- idea`), or numbered (`1. step`)
- No frontmatter, no individual file

**Tier 2 — Project file** (promoted, persistent):
- Lives in `40-tasks/active/<slug>.md`
- Has the schema above
- Sub-tasks / milestones still represented as nested checkboxes in body, not separate fields
- Promoted **when** lifespan exceeds a day or the item warrants its own notes

### Daily `## Tasks` section format

```markdown
## Tasks
- [ ] 14:00 — Visit dentist (60m)
  - bring insurance card
  - test if the new tooth still hurts
- [x] Walk dog
- [ ] ~~Order phone~~ — moved to [[2026-06-02#Tasks]]
- [ ] [[buy-groceries]]  ← promoted, now a file
```

Optional timing on the line: `HH:MM — text (NNm)` where the time-of-day puts it on `/day` schedule and the trailing `(NNm)` is duration.

### Roll-over semantics (`daily_rollover`)

For each unchecked top-level item in yesterday's `## Tasks`:

1. **In the original**: apply strikethrough to the parent line and append `— moved to [[<today_date>#Tasks]]`. Children stay as captured (already-checked sub-tasks remain `[x]`).

   ```markdown
   - [ ] ~~Order phone~~ — moved to [[2026-06-01#Tasks]]
     - check AliExpress prices first
   ```
2. **In today's daily**: copy the whole block (parent + all nested children) with the parent annotated:

   ```markdown
   - [ ] Order phone — moved from [[2026-05-21#Tasks]]
     - check AliExpress prices first
   ```
3. **Chain anchor**: the `moved from` link always points to the **first original**, not the previous day. If today's copy rolls over tomorrow, tomorrow's line reads `moved from [[2026-05-21#Tasks]]` (the original day-1).
4. **Strikethrough**, not `[x]`, distinguishes "moved" from "completed".

### Promotion semantics (`promote_daily_task`)

1. Walk `moved from` chain to find first-original date
2. Create `40-tasks/active/<slug>.md` with:
   - `created: <first_original_date>`
   - Other fields from current daily line + optional `fields` override
   - Body initialized with:
     - `## Sub-tasks` — nested checkbox children
     - `## Notes` — plain bullet / numbered children
     - `## History` — `- <today> HH:MM — Promoted from [[<first_original_date>#Tasks]]`
3. Replace today's line with `- [ ] [[<slug>]]`
4. Replace first-original line with `- [x] [[<slug>]] — promoted to file on <today>`

State changes (check / uncheck / strikethrough) on a parent **never cascade** to children. Explicit operations only.

---

## D2 — Tool catalog (post-D1, pre-D3)

Risk levels unchanged: **safe** (read), **write**, **destructive**. Auto-execute threshold: **≥ 0.85 confidence**.

### Read (safe)
- `list_tasks(group_by?)` → grouped object: `{daily_pending, daily_done_today, file_tier_by_priority, overdue}`. Single source for both tiers.
- `list_habits`
- `list_goals`
- `get_daily`
- `read_daily_section` (named section only — saves tokens)
- `get_tokens`
- `search_knowledge(query, mode?: "keyword"|"graph", limit?, depth?)` — folds `get_related`
- `list_events`

### Write
- `create_task` (new schema fields)
- `create_habit`, `create_goal`
- `update_task(name_or_path, fields)` — typed mutator (replaces `update_item`)
  - Explicit fields: `priority?, status?, category?, scheduled_at?, duration_minutes?, due_date?, due_soft?, append_note?` (markdown, appended with timestamp to body)
  - Auto-appends `## History` line
- `update_habit(name_or_path, fields)` — same pattern
- `update_goal(name_or_path, fields)` — same pattern
- `save_knowledge`
- `attach_to_daily` (photo)
- `edit_daily_section` (free-text edits & deletions in any daily section)
- `attach_photo_to_event`, `create_event`, `update_event`
- `daily_add_task(text, scheduled_at?, duration_minutes?, nested_under?)` — inserts `- [ ]` into today's `## Tasks`; `nested_under` references an existing line text or index for indentation
- `daily_set_task_state(text_or_id, state: "checked"|"unchecked"|"moved")` — collapsed check / uncheck / strikethrough-move
- `daily_rollover(from_date?, to_date?)` — defaults yesterday → today
- `promote_daily_task(text, fields?)` — see promotion semantics above

### Destructive
- `complete_task` (FIX A1: dict-iteration bug)
- `complete_habit`
- `delete_task`, `archive_task`, `delete_habit`, `archive_goal`

### Removed
- `update_item` — replaced by typed mutators
- `get_related` — folded into `search_knowledge`
- (No `daily_delete_task` — use `edit_daily_section`)

### Known bugs (confirmed via May 21 traces)
- **A1.** `agent_service._tool_complete_task` does `name, tokens, archive_path = self.vault.complete_task(...)` against a dict return. Iterates **keys**, not values. Returns literal strings `"task_name"`, `"tokens_earned"`, `"archive_path"`. Fix: `result = self.vault.complete_task(...); name = result["task_name"]; ...`
- **A2.** `update_item` accepts `updates` as raw param then calls `vault.update_file(path, updates)`. If LLM passes a JSON-encoded string, `dict.update(str)` errors with `"dictionary update sequence element #0 has length 1; 2 is required"`. Resolved by removing `update_item` entirely.
- **A3.** Migdal-text flow (112-s trace `752c3a402f3ddea6efcf936b7659e16d`) had no clean tool path. Resolved by `update_task(name, {append_note: ...})`.

---

## `/day` — concrete fixes

| Pain point | Fix |
| --- | --- |
| Standalone Habits section noisy | Drop habits section from `/day`; render scheduled habits inside Schedule only |
| Active Tasks missing | Render scheduled file-tier tasks + scheduled daily-tier tasks inside Schedule; non-timed items remain off `/day` |
| Calendar shows national holidays | `GOOGLE_CALENDAR_INCLUDE` allowlist enforced in `daily.py` route (currently `""` → no filter) |
| Readability | Schedule grouped by time-of-day (Morning / Afternoon / Evening) or as a single chronological list — TBD |

Coupling: a scheduled item only appears on `/day` if it has `scheduled_at` set. For file-tier tasks/habits, sync to GCal (Block E1) makes them visible on the schedule when pulled via the calendar filter — or `/day` queries the vault directly and unions the result.

---

## Pending / not-yet-discussed

- **D3 — sub-agent / skill architecture for Mazkir.** Goal: split the 27-tool surface across specialized sub-agents (e.g. capture sub-agent, planner sub-agent, event sub-agent, recall sub-agent), each with a tight toolbox so per-call schema cost is lower. Open: routing strategy, shared state, confirmation flows.
- **D4 — confidence gate review.** Current threshold 0.85 across write+destructive. Open: per-tool thresholds? confirmation UX in Telegram?
- **A — Block A correctness work** (fix A1, retire `update_item`, schema validation guard-rails, fuzzy path resolution standardized).
- **B — context optimization.** Audit what enters system prompt; the May 21 example of lecture notes leaking in is the canonical bug. Right-size short/mid/long-term memory layers per request type. Token usage measurement.
- **C — observability gaps.** Empty `input.value` / `output.value` on `POST /message`, `agent.loop`, `agent.tool_call` spans; investigate ERROR trace `122b1a07…`; add the open-coding / axial-coding workflow for ongoing trace review.
- **E1 — calendar sync** (events written locally but not pushed to GCal).
- **E2 — media path.** Move from `data/media/` into `memory/…` so Obsidian sees attachments (probably `memory/90-attachments/{date}/`).
- **F — latency** (largely falls out of A + B).

---

## Open questions to revisit

- `/day` Schedule layout: chronological list, or grouped by part-of-day?
- Where does `memory/90-attachments/` live within the Obsidian vault structure? (Block E2)
- Should mutators expose a dry-run (`preview: true`) for confirmation flows? (Block D4)
- Do we need separate `archive_habit` (currently no such tool)?
