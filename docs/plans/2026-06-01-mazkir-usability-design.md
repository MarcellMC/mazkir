# Mazkir Usability Overhaul — Design (Checkpoint)

**Status:** Brainstorm complete. All blocks (A, B, C, D, E, F) are locked. Ready for implementation planning.

**Goal:** Make Mazkir more usable. Standard vault operations must be reliable, deterministic, and guard-railed; common workflows must be obvious; only necessary context goes into LLM requests; all observability instrumentation gaps are closed.

---

## Scope: Blocks A–F

| Block | Theme | Status |
| --- | --- | --- |
| A | Correctness — vault ops are deterministic | locked |
| B | Context optimization — only send what's needed | locked |
| C | Observability — close gaps | locked |
| D | Workflows, schemas, tools, sub-agents | locked (D1–D4) |
| E | Broken integrations — GCal sync, media path | locked (E1, E2) |
| F | Latency (mostly falls out of A+B) | locked |

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

## B — Context optimization

### Root cause analysis (the lecture-notes leak)

Two paths bloat the system prompt today:

1. **`_gather_relevant_knowledge`** (`memory_service.py:426`) walks `items_referenced` from the conversation history. For each path, it splits the stem on hyphens (`learn-ai-engineering.md` → `learn`, `ai`, `engineering`) and runs `search_knowledge(term, limit=2)`. **The full content of every hit lands in `## Relevant knowledge`.** A goal titled "Learn AI engineering" pulls in every knowledge note with "ai" in its name or tags. That's the lecture-notes leak.
2. **All preferences dumped every turn.** Same function reads every `00-system/preferences/*.md` and concatenates content. Dir is empty today; mechanism is the trap.

Plus:
- **`_build_vault_snapshot`** (`memory_service.py:373`) lists every active task with name + priority + due, every habit with streak, every goal with progress. Grows linearly with vault size.
- **27 tool schemas** sent in every Claude call (~3–4 k tokens).
- **No prompt caching** — full system prompt billed at fresh rate every turn.
- **`items_referenced`** grows monotonically across the conversation; never pruned. Drives the leak above and adds bytes to the conversation file.

### B1 — Stop auto-dumping knowledge content

Delete the `items_referenced` → `search_knowledge` → "dump full content" path from `_gather_relevant_knowledge`. The agent already has `search_knowledge` as a tool and uses it when actually needed.

```python
# memory_service.py
def assemble_context(self, chat_id: int) -> ConversationContext:
    conversation = self.load_conversation(chat_id)
    return ConversationContext(
        messages=conversation["messages"],
        summary=conversation["summary"],
        vault_snapshot=self._build_vault_snapshot(),   # see B2 — no longer takes conversation
        knowledge="",                                   # gone
    )
# _gather_relevant_knowledge function deleted
```

### B2 — Vault snapshot → summary line

Replace per-item listings with one-line counts. Full data via `list_tasks` / `list_habits` / `list_goals` / `list_events` tools on demand.

```
Vault: 3 active tasks (1 overdue), 5 habits (2 done today), 2 active goals, 47 tokens today
```

The agent has tools to drill in; no need to spoon-feed the catalogue every turn.

### B3 — Skill-specific prompts & tool subsets (already in D3)

Each skill's system prompt is purpose-built and concise. Tool schemas per skill: `capture` ≈ 8, `recall` ≈ 7, `manager` ≈ 20 — vs current 27 always loaded. Counted at the system-prompt layer this is the biggest single reduction.

### B4 — Prompt caching

Wrap the static prefix of the system prompt with Anthropic's `cache_control`. The prefix (tool schemas + skill body + base guidelines) is identical across turns within a conversation. Dynamic tail (current date, vault summary numbers, recent message log) stays uncached.

```python
system = [
    {
        "type": "text",
        "text": skill.system_prompt_static_prefix,   # tool docs, base guidelines
        "cache_control": {"type": "ephemeral"},
    },
    {
        "type": "text",
        "text": f"\nCurrent time: {now}\n\n{vault_summary}",
    },
]
```

5-min TTL. Cache hits cost ~10% of fresh input. Big win on multi-turn conversations.

### B5 — Vault snapshot cache (deferred)

Cache the summary string for ~30 s with vault-mtime invalidation. Saves N file-frontmatter reads per turn during multi-turn bursts. **Deferred** — ship after measuring whether snapshot computation shows up as hot in traces.

### B6 — Preferences pattern (forward-looking, falls out of B1)

B1 deletes `_gather_relevant_knowledge` entirely, which is where preferences were also auto-dumped. So B6 is satisfied by B1 for free. When you start writing preferences, add a `list_preferences` read-only tool and (optionally) a `"You have N saved preferences"` hint in the system prompt. **Tool itself deferred** until preferences exist (YAGNI).

### B7 — Remove `items_referenced` entirely

Vestigial once B1 + B2 land. The `[referenced]` marker disappears with B2's summary-only snapshot. The agent has conversation history + tool results — that's enough recency signal.

- Stop writing `items_referenced` on `save_turn`
- Drop the field from the conversation YAML schema
- Remove the unused load path

### Measurement (Block C handoff)

Add to every `messages.create` and `agent.handle_message` span:

| Attribute | Source |
| --- | --- |
| `system_prompt.token_estimate` | `len(prompt) // 4` cheap proxy |
| `llm.token_count.prompt_cached_read` | Anthropic API response field |
| `llm.token_count.prompt_cached_write` | Anthropic API response field |
| `vault.snapshot.compute_ms` | Wall time of `_build_vault_snapshot` |

Validates B1+B2 by watching `system_prompt.token_estimate` drop. Validates B4 by watching `cache_read` rise on second+ turns of a conversation.

### Expected impact

Rough order-of-magnitude on a typical agent turn:

| Source | Before | After (B1+B2+B3+B4) |
| --- | --- | --- |
| Tool schemas | ~3.5 k | ~1.5 k (per skill) |
| Vault snapshot | ~0.5–2 k | ~0.05 k (one line) |
| Knowledge auto-dump | ~1–5 k | 0 |
| Preferences dump | 0 today | 0 (capped by B6) |
| Conversation tail | ~1–3 k | unchanged |
| Static guidelines | ~0.5 k | unchanged but cached |
| **Total fresh input** | **~6–14 k** | **~3–4 k uncached + ~1.5 k cached at 10% rate** |

Multi-turn conversations get the cache hit, dropping effective billed input further.

---

## F — Latency

Most latency wins from May 21 are already addressed:
- 112 s Migdal turn → A1–A3 (no retry loops)
- 30 s `messages.create` → B1+B2+B4 (smaller prompts + cache hits)
- 27-tool surface per call → D3 (skill-scoped toolboxes)

F catalogues what's left.

### F1 — Parallel tool execution

The bulk-complete trace (`351698572ac…`) emitted 11 tool calls in a single Claude response (visible: no `messages.create` between them in the span list). The handler ran them **serially** — 13.7 s wall time for what could be ~1–2 s in parallel.

**Change:** wrap independent tool calls in `asyncio.gather`. Each tool in the registry declares `safe_for_parallel: bool` (default True for read-only; False where shared state matters). When a batch contains any unsafe tool, the whole batch falls back to serial.

```python
TOOL_REGISTRY["complete_task"]["safe_for_parallel"] = True
TOOL_REGISTRY["daily_add_task"]["safe_for_parallel"] = False   # writes one daily section
TOOL_REGISTRY["update_task"]["safe_for_parallel"] = True       # different paths
TOOL_REGISTRY["daily_rollover"]["safe_for_parallel"] = False   # mutates today's daily
TOOL_REGISTRY["complete_habit"]["safe_for_parallel"] = False   # mutates token ledger
```

Confidence gates + previews apply per-call before execution; the parallel batch waits for all confirmations to resolve before firing.

### F2 — Streaming responses to Telegram

Currently the bot waits for the full `agent.handle_message` to complete, then sends one message. Switch to Anthropic SDK streaming + Telegram `editMessageText`:

1. Bot sends placeholder ("…") on receipt.
2. As tokens stream from Claude, bot edits the message every ~500 ms or every newline.
3. Final edit on stream completion.

Touches: `claude_service.create` → `claude_service.stream`; `agent_service._run_loop` to surface stream chunks; bot's reply handler to apply the edit-loop.

Telegram rate limits: `editMessageText` allows ~20/sec per chat. 500 ms cadence is well inside. Throttle to avoid drift.

Cost: meaningful refactor (~150–200 lines across two services + bot). Big perceived-latency win.

### F3 — Haiku for capture and recall (D3-aligned)

Already in D3 spec; called out here for completeness:

| Skill | Model | Typical wall time (after B) |
| --- | --- | --- |
| `capture` | Haiku 4.5 | 2–4 s |
| `recall` | Haiku 4.5 | 3–5 s |
| `manager` | Sonnet 4.6 | 5–10 s |

Independent of streaming or caching — pure model-choice win.

### F4 — Encourage parallel batching in skill prompts

Append to `capture` and `manager` system prompts:

> "When you have multiple independent tool calls (completing several tasks, adding several daily items, etc.), emit them in a single response block as parallel calls rather than across iterations. Combined with the parallel executor this gives the user near-instant responses for bulk operations."

Claude already does this most of the time; the explicit reminder helps consistency.

### Expected impact (Block F + upstream wins)

| Scenario | Before | After |
| --- | --- | --- |
| Single capture ("Save this quote") | 5–8 s | 2–4 s (Haiku + cache) |
| Bulk complete (11 tasks) | 13.7 s | 1–3 s (parallel exec) |
| Migdal-text attach | 112 s | 5–8 s (no retries + typed mutator + Haiku) |
| Daily review with multiple updates | 20–40 s | 5–10 s (smaller prompt + parallel tools + Sonnet) |

Perceived latency further reduced by F2 streaming.

### Out of scope for F

- Anthropic prompt-cache TTL tuning (stick with ephemeral / 5-min)
- Provider switching
- Self-hosted inference

---

## C — Observability gaps

### Current state (from May 21 trace review)

- `agent.loop` spans set only `iteration` + span kind — no input/output values
- `agent.tool_call` sets `output.value` but **never** `input.value`
- Status doesn't propagate: ERROR trace `122b1a07` had an inner POST error but root `telegram.update` stayed OK
- Auto-instrumented HTTP/SDK spans (FastAPI, Anthropic) carry low-semantic attrs only (URLs, status codes)

### C1 — Fill input / output gaps

Set OpenInference `input.value` / `output.value` on every span we own.

| Span | input.value | output.value |
| --- | --- | --- |
| `agent.handle_message` | `user_msg` (text + attachments summary) | response text |
| `agent.loop` | last user/tool-result block (truncated) | `stop_reason` + first text block (truncated) |
| `agent.tool_call` | params JSON (truncated 2 k) | normalized result JSON (truncated 2 k) |
| `agent.router` (new) | user_msg | chosen skill name + routing reason |
| `POST /message` | request body summary (chat_id + text length + attachment count) | response summary |
| `POST /message/confirm` | action_id + response | result summary |

Truncate at 2 k chars; set `truncated: true` attribute when applied.

### C2 — Error status propagation

Manual spans need explicit status setting on failure. Pattern:

```python
with _tracer.start_as_current_span("agent.tool_call", attributes=attrs) as span:
    try:
        output = handler(params)
        if not output.get("ok", True):
            span.set_status(Status(StatusCode.ERROR, output["error"]["code"]))
            span.set_attribute("tool.error.code", output["error"]["code"])
        else:
            span.set_status(Status(StatusCode.OK))
        span.set_attribute(SpanAttributes.OUTPUT_VALUE, json.dumps(output)[:2000])
        return output
    except Exception as e:
        span.record_exception(e)
        span.set_status(Status(StatusCode.ERROR, str(e)))
        raise
```

Apply to `agent.handle_message`, `agent.loop`, `agent.tool_call`, `agent.router`. Outer-span propagation is automatic via OpenTelemetry's status semantics.

### C3 — Investigate ERROR trace `122b1a07` — dropped

Transient error from May 21. Not pursuing — if a recurring pattern emerges in future trace review, revisit.

### C4 — New attributes from A, B, D3, D4

| Source | Attribute | Span(s) |
| --- | --- | --- |
| D3 | `skill.name` | every span after router pick |
| D3 | `skill.previous` | hand-off targets |
| D3 | `skill.next_skill` | when a loop emits next_skill |
| D3 | `skill.routing_reason` | `agent.router` |
| A | `tool.ok` | `agent.tool_call` |
| A | `tool.error.code` | `agent.tool_call` on failure |
| D4 | `confirmation.required` | `agent.tool_call` when gate fires |
| D4 | `confirmation.outcome` | `POST /message/confirm` |
| B | `system_prompt.token_estimate` | `agent.loop` |
| B | `llm.token_count.prompt_cached_read` | `messages.create` (from Anthropic response) |
| B | `llm.token_count.prompt_cached_write` | `messages.create` |
| B | `vault.snapshot.compute_ms` | `agent.handle_message` |

### C5 — Logs ↔ traces correlation

Add `trace_id` to every line written to `data/logs/agent-turns.jsonl` (and `vault-server.jsonl`, `telegram-bot.jsonl`).

```python
from opentelemetry.trace import get_current_span
ctx = get_current_span().get_span_context()
trace_id = format(ctx.trace_id, "032x") if ctx.is_valid else None
logger.info(..., extra={..., "trace_id": trace_id})
```

This unlocks: copy the `trace_id` from any log line, paste into Phoenix UI, jump straight to the trace.

### C6 — Open-coding review cadence — skipped

Reviewing on demand (per-incident or when something feels off). The `phoenix-cli` skill workflow is documented in the skill itself; no separate process needed.

### Out of scope for C

- Backend log enrichment beyond `trace_id`
- New Grafana dashboards
- Custom Phoenix evaluators (revisit once a failure taxonomy emerges)
- Phoenix sessions (auto-grouping by `session.id` — could add later; current setup uses chat_id but doesn't tag spans with session.id)

---

## A — Correctness & guardrails

A1–A3 from the initial bug list are absorbed by D2's tool catalog redesign:
- **A1** `complete_task` dict-iteration bug → fixed when the handler reads dict keys properly (`name = result["task_name"]`, etc.)
- **A2** `update_item` JSON-string rejection → resolved by retiring `update_item` entirely; typed `update_task`/`update_habit`/`update_goal` use explicit field schemas
- **A3** missing "attach note to existing task" → typed mutators expose `append_note` field

A4 is the broader guardrails layer that makes every vault op deterministic and self-describing.

### A4.1 — Unified fuzzy-path resolver

One helper used by every name-accepting tool. Replaces the scattered `find_task_by_name` / `find_habit_by_name` / `find_goal_by_name` methods.

```python
class Resolver:
    SCORE_AMBIGUOUS_DELTA = 0.10  # if top-1 and top-2 within this, mark ambiguous

    def resolve_item(self, item_type: Literal["task","habit","goal"], query: str) -> dict:
        candidates = self._scan(item_type)
        # 1. exact path match (e.g. "40-tasks/active/foo.md")
        # 2. exact name match (case-sensitive)
        # 3. case-insensitive substring of name
        # 4. fuzzy (token-set ratio via rapidfuzz)
        ranked = self._rank(query, candidates)
        if not ranked:
            return {"ok": False, "error": {"code": "PATH_NOT_FOUND", "query": query}}
        top, *rest = ranked
        if rest and (top.score - rest[0].score) < self.SCORE_AMBIGUOUS_DELTA:
            return {
                "ok": False,
                "error": {
                    "code": "AMBIGUOUS_MATCH",
                    "query": query,
                    "candidates": [{"path": c.path, "name": c.name, "score": c.score} for c in ranked[:5]],
                },
            }
        return {"ok": True, "data": {"path": top.path, "name": top.name, "score": top.score}}
```

**Behavior on ambiguity:** return error with candidates. The agent re-prompts the user ("did you mean Migdal Insurance or Migdal Bank?") rather than silently mutating the wrong item.

### A4.2 — Normalized tool response shape

Every tool — read, write, destructive — returns one of two shapes. Wraps existing handlers; old `{"saved": ..., "deleted": ...}` keys move under `data`.

```python
# success
{
  "ok": True,
  "data": { ...tool-specific fields... },
  "_items": [ "path/that/changed.md", ... ],   # for memory layer tracking
}

# error
{
  "ok": False,
  "error": {
    "code": "PATH_NOT_FOUND",                    # see enum
    "message": "...",                            # human-readable
    "details": { ... },                          # candidate list, schema diff, etc.
  },
  "_items": [],
}
```

The agent's tool-result parsing branches on `ok`. The trace `agent.tool_call` span gets `tool.ok`, `tool.error.code` attributes (closes part of Block C).

### A4.3 — Error code enum (starting set)

| Code | When |
| --- | --- |
| `PATH_NOT_FOUND` | Resolver returned no match for a name/path query |
| `AMBIGUOUS_MATCH` | Two or more candidates within `SCORE_AMBIGUOUS_DELTA` |
| `SCHEMA_INVALID` | Pre-hook validator rejected input against tool schema |
| `STATE_CONFLICT` | Target file changed between confirmation issuance and execution; or rollover target already has the same item; or any pre-execution state assumption failed |
| `ALREADY_DONE` | Idempotency guard: action is a no-op because target is in the desired terminal state |
| `EXTERNAL_FAILURE` | External integration (GCal, Replicate) returned an error |
| `AUTH_REQUIRED` | Tool needs an auth step the user hasn't completed (placeholder slot for future 2FA/biometric hook) |
| `CANCELLED_BY_USER` | Confirmation flow returned no |

Codes are stable; messages are free-text. The agent's prompt includes a short table of "what to do on each code" so retry / re-ask behavior is consistent.

### A4.4 — Schema validation pre-hook

Implements the `validate_schema` slot from D4. Every write or destructive tool gets it by default.

```python
def validate_schema(params: dict, ctx) -> Optional[dict]:
    schema = ctx.tool["input_schema"]
    try:
        jsonschema.validate(params, schema)
    except jsonschema.ValidationError as e:
        return {
            "ok": False,
            "error": {
                "code": "SCHEMA_INVALID",
                "message": e.message,
                "details": {"path": list(e.absolute_path), "schema_path": list(e.schema_path)},
            },
        }
    return None  # pass
```

What this catches that Claude SDK doesn't:
- `additionalProperties: false` enforcement (the Migdal "JSON string for `updates`" case)
- Cross-field constraints (e.g. `scheduled_at` requires `duration_minutes`)
- Enum mismatches on `state`-style fields

### A4.5 — Idempotency

Each state-changing handler runs a pre-check; returns `ALREADY_DONE` if the operation would be a no-op.

| Tool | Idempotency check |
| --- | --- |
| `complete_task` | `metadata["status"] == "done"` → return `ALREADY_DONE` with current data. No double token award. |
| `complete_habit` | `metadata["last_completed"] == today` → `ALREADY_DONE`. Streak not incremented. |
| `daily_rollover` | For each source item, search today's `## Tasks` for `moved from [[<src_date>#Tasks]]` lines matching the item text. Skip if found. |
| `promote_daily_task` | If `40-tasks/active/<slug>.md` already exists, return existing file path + `ALREADY_DONE`. |
| `archive_task` | Already at `40-tasks/archive/<slug>.md` → `ALREADY_DONE`. |
| `delete_task` | Target absent → `ALREADY_DONE` (don't error). |
| `archive_goal` | `metadata["status"] == "archived"` → `ALREADY_DONE`. |

Idempotency checks live in the handler, not a hook — they're tool-specific.

### Out of scope for A (deferred)

- **Atomicity on multi-step writes.** `complete_task` writes archive, awards tokens, deletes original; a crash mid-flight leaves inconsistent state. Single-user single-instance system → low probability. Re-evaluate if observability surfaces real incidents.
- **Concurrency.** FastAPI async + sync vault writes work because the system is single-bot-instance. If we ever scale, vault writes need file locks. Note as known limitation.

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
