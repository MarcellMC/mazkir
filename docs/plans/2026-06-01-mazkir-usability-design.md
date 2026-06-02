# Mazkir Usability Overhaul — Design (Checkpoint)

**Status:** Brainstorm in progress. Blocks D and E are locked. Blocks A, B, C, F are pending.

**Goal:** Make Mazkir more usable. Standard vault operations must be reliable, deterministic, and guard-railed; common workflows must be obvious; only necessary context goes into LLM requests; all observability instrumentation gaps are closed.

---

## Scope: Blocks A–F

| Block | Theme | Status |
| --- | --- | --- |
| A | Correctness — vault ops are deterministic | pending design |
| B | Context optimization — only send what's needed | pending design |
| C | Observability — close gaps | pending design |
| D | Workflows, schemas, tools, sub-agents | locked (D1–D4) |
| E | Broken integrations — GCal sync, media path | locked (E1, E2) |
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

## D3 — Sub-agent / skill architecture

Goal: split the 27-tool surface across specialized sub-agents so per-call schema cost is lower, prompts can specialize, and the user can manage the catalog from the vault.

### Framework

**B + C hybrid.** A **"Mazkir skill"** is a markdown file under `memory/00-system/mazkir-skills/`. Each file defines one sub-agent. Frontmatter declares model + tool list + composition rules; body is the skill's system prompt.

```yaml
---
name: capture
description: Fast inbox-style captures (text, photos, new items)
when_to_use: |
  - User dumps text or a photo with no clear intent
  - "Save this", "remember this", "add task", "note that ..."
tools: [daily_add_task, daily_set_task_state, save_knowledge, attach_to_daily, edit_daily_section, create_task, create_habit, create_goal]
model: claude-haiku-4-5
max_iterations: 3
next_skills: [manager, recall]
---

# Capture Skill — system prompt

You receive quick captures from the user. Your job:
- Classify the content (task / note / knowledge / photo).
- Use the right tool to file it.
- Be terse; only ask for clarification when intent is ambiguous.
- If the user asked for follow-up action, hand off via next_skill: manager.
```

### Router

A small LLM call (Haiku, no tools) that takes:
- User message + recent conversation tail
- Each skill's `name` + `description` + `when_to_use`

and returns the chosen skill name. **Fallback when uncertain: `manager`** (broadest toolbox).

### Composition — chained `next_skill`

After a skill's agent loop completes, it may emit `next_skill: <name>` in its final output. Control hands off to that skill with shared conversation history.

- **Loop cap:** 3 total skill hops per user turn.
- **Cycle protection:** router tracks visited skills, refuses revisits.
- **Allowed transitions** (declared per-skill via `next_skills` frontmatter):
  - `capture` → `manager`, `recall`
  - `manager` → `recall`
  - `recall` → `capture`, `manager`

Rationale over router-driven sequential: the skill that just ran has the most accurate picture of what's done and what comes next. Pre-planning a chain at routing time loses that information.

### Skill catalog (v1)

Three skills, lean for a single-user assistant.

| Skill | Purpose | Model | Max iter | Tools |
| --- | --- | --- | --- | --- |
| `capture` | Fast inbox writes — text, photos, new items | Haiku 4.5 | 3 | `daily_add_task`, `daily_set_task_state`, `save_knowledge`, `attach_to_daily`, `edit_daily_section`, `create_task`, `create_habit`, `create_goal` |
| `manager` | Deliberate organization, edits, schedule, destructive ops | Sonnet 4.6 | 10 | `list_tasks`, `list_habits`, `list_goals`, `list_events`, `get_daily`, `read_daily_section`, `update_task`, `update_habit`, `update_goal`, `complete_task`, `complete_habit`, `delete_task`, `archive_task`, `delete_habit`, `archive_goal`, `create_event`, `update_event`, `attach_photo_to_event`, `attach_to_daily`, `edit_daily_section`, `daily_add_task`, `daily_set_task_state`, `daily_rollover`, `promote_daily_task`, `search_knowledge`, `get_tokens` |
| `recall` | Read-only search, retrieval, summaries | Haiku 4.5 | 5 | `search_knowledge` (keyword + graph modes), `list_tasks`, `list_habits`, `list_goals`, `list_events`, `get_daily`, `read_daily_section`, `get_tokens` |

Deterministic slash commands (`/tasks`, `/habits`, `/goals`, `/day`, `/tokens`, `/calendar`) **bypass the router entirely** — no skill, no LLM call.

### Transparency

Skill choice is **traced only**, not surfaced in user-facing replies. Phoenix span attributes added:

- `skill.name` — active skill on a span
- `skill.previous` — set on hand-off targets
- `skill.next_skill` — set if the loop emitted one
- `skill.routing_reason` — short string from the router classifier

### Confidence gate

Stays global at **0.85** for write + destructive risk. Per-skill thresholds deferred to D4 along with broader confirmation-UX review.

### Implementation sketch

- New `apps/vault-server/src/services/skill_registry.py`: parses skill markdown files at startup, validates frontmatter, exposes `get(name)` / `list()`.
- `AgentService.handle_message`:
  1. Call `router_service.pick(user_msg, history)` → skill name
  2. Loop: load skill, run agent loop with its tools + system prompt, capture `next_skill` from final block, hop until cap or `null`.
- Tools dict in `AgentService` stays the central registry. Skills reference tools by name; loader resolves to schemas + handlers.

---

## D4 — Confidence gate, preview, and hook framework

### Per-tool thresholds

Threshold lives on the **tool**, not the skill. Each tool in the registry declares:

```python
TOOL_REGISTRY["delete_task"] = {
    "risk": "destructive",
    "confidence_threshold": 0.95,
    "preview": True,
    "auth_level": "user",         # extensible: "biometric", "2fa", "user-typed-confirmation"
    "pre_hooks": [],               # ordered list of pre-execution check names
    "post_hooks": [],              # ordered list of post-execution side-effect names
    "handler": ...,
}
```

Default per risk class:

| Risk | Default threshold | Default preview |
| --- | --- | --- |
| safe (read) | n/a (no gate) | n/a |
| write | 0.85 | False |
| destructive | 0.95 | True |

Tools may override (e.g. `daily_add_task` is write but could drop to 0.75 because it's low-stakes).

### Preview for destructive ops — always on

Every destructive tool defines a `preview_fn(params) → str` that formats a human-readable description of what would change. Flow:

1. Tool call resolved with `_confidence ≥ threshold`
2. If `preview = True`: bot sends "Would do: <preview>" with **yes / no** inline keyboard
3. On `yes`: handler runs. On `no`: action discarded, agent loop resumes with a tool-result like `{cancelled: true}`

Example preview output for `delete_task`:

```
Would delete:
  • Submit missing documents to Migdal Insurance
  • Priority 2, no due date
  • Has 1 note (Hebrew text from Migdal Insurance)
  • Created 2026-04-15

Yes / No
```

### Confirmation UX

- **Buttons:** yes / no only. Keep minimal.
- **Timeout:** none. Pending confirmations stay pending. Bot persists them in vault-server state (already does via `chat_id` + `action_id`).
- **State drift protection:** before executing a confirmed action, handler re-reads the target file and verifies the expected pre-state. If something changed since the confirmation was issued, the handler returns `{error: "Target changed since confirmation issued; please re-issue."}` and the agent re-runs.

### Hooks framework (forward-looking)

The `pre_hooks` and `post_hooks` lists let us layer behavior without touching tool handlers:

- `validate_schema` — input schema check beyond Claude SDK's basic validation
- `check_path_exists` — resolve fuzzy paths to canonical ones
- `audit_log` — write to `data/logs/agent-turns.jsonl` (already exists)
- `notify_calendar` — push state changes to GCal
- `require_2fa` — future: pause + send Telegram TOTP prompt
- `require_biometric` — future: WebAuthn ping to webapp

Implementation: each hook is a registered function in `apps/vault-server/src/services/hooks/`. Tool execution wraps:

```python
for hook_name in tool["pre_hooks"]:
    result = HOOKS[hook_name](params, ctx)
    if result.blocked: return result.to_tool_response()
output = tool["handler"](params)
for hook_name in tool["post_hooks"]:
    HOOKS[hook_name](params, output, ctx)
return output
```

**v1 ships with**: `validate_schema` (all write/destructive), `check_path_exists` (all that take paths), `audit_log` (all write/destructive). `require_2fa` / `require_biometric` not implemented but the registry slot exists.

### Skill gates

Skills do **not** override per-tool thresholds. The skill's tool subset determines what's reachable; the tool determines its own gate. `recall` simply has no write/destructive tools, so no gate fires.

### Telegram preview flow

```
User: "delete the dentist task"
  Bot → Mazkir: agent.handle_message
    Router: → manager
    Manager skill: delete_task with confidence 0.92
      Preview: "Would delete: Visit dentist (P3, due 2026-06-10)..."
    Bot ← Mazkir: pending_action {id: x, preview: "..."}
  Bot: shows preview text + [✅] [❌]
User taps ✅
  Bot → Mazkir: /message/confirm {action_id: x, response: "yes"}
    Manager skill: pre_hooks pass, handler runs, post_hooks run
  Bot ← Mazkir: "Deleted: Visit dentist"
```

---

## E — Broken integrations

### E1 — Google Calendar sync (write-back)

**Root cause:** the sync code exists and is correct (`calendar_service.py:674` `sync_habit`, `:703` `sync_task`), but it's not called from all write paths:

- `POST /tasks` (REST route) does call `calendar.sync_task` on create — wired
- `_tool_create_task` (agent) calls `vault.create_task` directly — **never syncs**
- `_tool_complete_task` only marks an existing GCal event done; doesn't create one if missing
- Agent's future `update_task` will face the same problem

Also possible: `ENABLE_CALENDAR_SYNC=false` (the env default) — needs verification before code change, but irrelevant once the hook is wired (hook simply no-ops if calendar is uninitialized).

**Fix:** wire calendar sync as a D4 **post-hook** on `create_task`, `update_task`, `complete_task`, `create_habit`, `update_habit`, `complete_habit`, `archive_task`, `delete_task`, `archive_goal`.

```python
TOOL_REGISTRY["create_task"]["post_hooks"] = ["sync_to_calendar"]
TOOL_REGISTRY["update_task"]["post_hooks"] = ["sync_to_calendar"]
TOOL_REGISTRY["complete_task"]["post_hooks"] = ["sync_to_calendar"]
# ... etc

def sync_to_calendar(params: dict, output: dict, ctx) -> None:
    if not ctx.calendar or not ctx.calendar.is_initialized:
        return
    item_path = output.get("_items", [None])[0]
    if not item_path: return
    item = ctx.vault.read_file(item_path)
    if item["metadata"]["type"] == "task":
        ctx.calendar.sync_task(item)   # creates or updates GCal event
    elif item["metadata"]["type"] == "habit":
        ctx.calendar.sync_habit(item)
```

Single hook covers all write paths (REST + agent + future skills) because tool execution runs through one registry.

**Bonus benefits:**
- Idempotent — `sync_task` checks `google_event_id` and updates vs creates
- Calendar sync now respects D4 confidence gates and previews (e.g. deleting a task previews "would also delete GCal event 'X' on 2026-06-10")
- Sync failure logs but doesn't block the write — best-effort semantics preserved

### E2 — Media path inside the Obsidian vault

**Move from** `data/media/{date}/` **to** `memory/00-system/media/{date}/`.

Existing daily-note embeds (`![](../../data/media/...)`) get rewritten to **Obsidian wikilink embeds** (`![[photo.jpg]]`). Wikilink embeds are Obsidian-native: it resolves the filename by searching all attachment folders in the vault, so the path stays robust to future moves. The webapp resolves wikilinks by asking vault-server for the path.

**Configuration:**
- `MEDIA_PATH` default → `~/dev/mazkir/memory/00-system/media` (env can still override)
- `memory/.gitignore` (the nested vault repo): add `00-system/media/` so binaries don't bloat the vault git history

**`attach_to_daily` change:**

```python
# before
lines.append(f"![{caption}](../../{vault_path})")
# after
filename = Path(vault_path).name
lines.append(f"![[{filename}]]")
lines.append(f"*{time_str} — {caption}*")
```

**Webapp media route change** (`apps/vault-server/src/api/routes/media.py:16`):

```python
# before
file_path = settings.media_path / date / filename
# after — same code, but settings.media_path now points inside vault
file_path = settings.media_path / date / filename     # path resolution unchanged
# add fallback: if not file_path.exists(), search vault for wikilink-style {filename}
```

Add a `vault.find_attachment(filename)` helper for wikilink resolution in case dates ever shift.

**Migration script** (`apps/vault-server/scripts/migrate_media_to_vault.py`):

```python
# 1. Move files
shutil.move(old_path / date, new_path / date)        # per date directory
# 2. Rewrite daily-note embeds
for daily in vault.list_files("10-daily"):
    content = vault.read_raw(daily)
    new_content = re.sub(
        r"!\[([^\]]*)\]\(\.\./\.\./data/media/(\d{4}-\d{2}-\d{2})/([^)]+)\)",
        lambda m: f"![[{m.group(3)}]]",
        content,
    )
    if new_content != content:
        vault.write_raw(daily, new_content)
# 3. Move sidecar metadata.json files (already in same dir, moves automatically)
# 4. Add memory/.gitignore entry
# 5. Print summary: files moved, daily notes rewritten
```

Run once, commit the rewrites in mazkir-memory repo, commit code changes in mazkir repo separately.

**Agent photo-save path:**

```python
# agent_service.py:992 — before
media_dir = self.media_path / today
# after — self.media_path now defaults inside vault, no code change required
```

Just the default path changes. The agent emits wikilink-format embeds via `attach_to_daily` afterward.

### Knock-on: scheduled_at for tasks needs GCal sync too

Once `update_task` supports `scheduled_at` + `duration_minutes` (D-schema), the `sync_to_calendar` post-hook also needs to update the GCal event time. `calendar_service._build_task_event` already reads metadata, so as long as it learns the new fields, the hook covers this path too.

Action item: extend `_build_task_event` to use `scheduled_at` + `duration_minutes` when present; fall back to `due_date` (current behavior) otherwise. Same for `_build_habit_event`.

---

## Pending / not-yet-discussed
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
