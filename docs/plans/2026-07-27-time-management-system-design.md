# Time Management System — Design

**Status:** Design, not yet planned/implemented.
**Parent doc:** `docs/plans/2026-07-27-p6-roadmap-and-agentic-frameworks.md` (Block A)
**Scope:** untracked-habit modeling, a multi-completions-per-day fix for habits, a structured time-allocation matrix, and the flagship day-schedule suggestion feature (pull-based). The `tm-day-bd` frontend bug stays folded into this block but needs no design — it's a straightforward implementation-time fix.

## 1. Untracked habits (dog walking, sleeping, household, cooking, eating)

**Decision:** reuse the existing Habit schema — no new "time-block" concept. These are still tracked as Habits.

### 1.1 Todo/Task rename (adopted now)

Inspired by Habitica's terminology (Habits / Dailies / Todos), the user proposed renaming: the inline daily-note checkbox item becomes **"Todo"**; the file-tier item (`40-tasks/active/*.md`) becomes **"Task"**. This is adopted now as a pure rename — no schema change. The fuller Habitica-style reclassification (splitting "Habit" into strict Habits vs. streak-bound Dailies) is **parked**, not adopted — it's a much larger change touching schemas, tool names, `CLAUDE.md`, `memory/AGENTS.md`, templates, and the terminology already committed in the Knowledge Management design doc. Tracked as a future candidate block in the parent roadmap doc.

Implementation note: existing docs (`CLAUDE.md`, the Knowledge Management design doc, templates) still use the old "task"/"daily task" terminology and need a consistency pass during implementation planning — not retroactively edited as part of this design.

### 1.2 Multi-completions-per-day fix (real bug, found via live testing)

Discovered this session: `_tool_complete_habit` (`agent_service.py:2707`) rejects a second same-day completion outright — `if habit["metadata"].get("last_completed") == today: return err(ALREADY_DONE, ...)`. This blocks habits like dog walking that legitimately need multiple completions per day. The habit template already has an unused `## Completion Log` section — the handler currently only touches frontmatter fields and never writes to it.

**Fix:**
- Add `daily_target` (int, default 1) as a new field, **orthogonal to `frequency`** (which stays about how often per week — daily/weekly/Nx-per-week). E.g. dog walking: `frequency: daily`, `daily_target: 2`.
- Use the **Completion Log** as the source of truth for today's progress — append a timestamped entry per completion, count today's entries to know progress, rather than a separate mutable counter that could drift. This finally makes the existing template section meaningful.
- `_tool_complete_habit` only returns `ALREADY_DONE` once today's count reaches `daily_target`.
- **Tokens**: awarded on every completion (`tokens_per_completion` as today) — no special-casing for partial vs. full days.
- **Streak**: only advances once `daily_target` is fully met for the day — a habit with 1 of 2 dog walks done does not advance the streak. This keeps the streak meaningful ("I actually did enough today") rather than lenient.

## 2. Flagship: sustainable day schedule

### 2.1 Trigger model: pull-only

**Decision:** no proactive push (no scheduled morning briefing). The webapp, `/day`, and calendar sync all compute the current best plan **on access**, from live state — nothing is precomputed or cached ahead of time.

This resolves the "on-the-fly adjustment" requirement largely for free: because the plan is recomputed fresh every time it's requested rather than cached, completing a habit (e.g. a dog walk) simply changes the inputs for the next computation — no separate "reflow" logic needed, just "always compute from current state."

**GCal is the one exception that doesn't map cleanly onto pull** — nobody "pulls" their phone's calendar app through Mazkir. Resolution: extend the existing `/sync_calendar` command (which already syncs habits/tasks to GCal) to also push suggested (non-fixed) schedule blocks to GCal **on demand**, rather than building a new continuous auto-sync mechanism. This stays consistent with "pull, no proactive automation" while still giving GCal visibility.

### 2.2 Structured matrix data

**Decision:** a new structured config file (e.g. `memory/00-system/time-matrix.yaml`) holding categories and their weekly/daily targets, separate from the existing free-text knowledge note (`60-knowledge/notes/time-management-matrix-sketch.md`, source photo `00-system/media/2026-06-20/photo_2026-06-20_05-00-22.jpg`), which remains as the original sketch/history rather than becoming the live config. The scheduling computation reads from the structured file; the note stays a knowledge artifact, not a data source.

Categories/targets to formalize from the hand-drawn matrix: `dev` (18 hrs/wk), `org`, `music` (3–6 hrs/wk), `work` (30–36 hrs/wk), `house` (7 days/wk, 1–2 hrs/day), `dog`, plus the special buckets `commute`, `mandatory`, `immovable`, `inflatory`.

### 2.3 Allocation approach (v1 scope)

A simple rule-based greedy fill for v1, not an optimization solver: take today's fixed calendar events as anchors, subtract time already logged this week per category (from completed habits/tasks) against the matrix's targets, and fill remaining free blocks in the day with whichever categories are furthest behind their target. More sophisticated allocation logic (true optimization, conflict resolution across competing under-budget categories) is an explicit non-goal for v1 — revisit only if the simple heuristic proves inadequate in practice.

### 2.4 Surfacing

Same underlying computation surfaced in three places: the web app (a day-schedule view, likely extending or sitting alongside the existing `dayplanner` feature), the `/day` bot command output, and Google Calendar (via the extended `/sync_calendar`, on demand).

## 3. Out of scope for this design
- The full Habitica-style Habit/Daily reclassification (parked as a future roadmap candidate).
- Proactive/scheduled push suggestions (explicitly rejected in favor of pull-only).
- Sophisticated scheduling optimization (v1 is a simple greedy heuristic).
- The `tm-day-bd` frontend bugfix itself (small, handled at implementation time, no design needed).

## 4. Next steps
Implementation planning covers: the habit multi-completion fix (§1.2), the structured matrix config file + allocation heuristic (§2.2–2.3), surfacing in webapp/`/day`/GCal (§2.4), and the `tm-day-bd` bugfix.
