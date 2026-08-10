# Knowledge Management — Design

**Status:** Design, not yet planned/implemented.
**Parent doc:** `docs/plans/2026-07-27-p6-roadmap-and-agentic-frameworks.md` (Block B)
**Scope:** Tags/links convention (v1: prompt-only), Task/Rigidity-levels decision, and a new command-center webapp page (v1: live overview + CRUD; linking deferred to v2, sketched below for complexity purposes only — not part of this build).

## 1. Background

Before Mazkir, the user maintained an Obsidian vault with its own conventions — some written down, most tacit. Researched and surfaced this session:

- **`Org. Tags vs Links.md`**: tags are status/action-type markers (`idea`, `org`, `status/active`); links connect ideas/topics. Nested status tags don't work well for tracking — "status changing only works with tasks as separate notes" (the reasoning that predates, and matches, Mazkir's existing two-tier task system).
- **`Task Levels.md` / `Rigidity Levels.md`**: an old three-stage model — checkbox → task note → Kanban — with "don't move checkboxes through periodic notes, promote to task notes instead" and an explicitly unresolved "when to promote to Kanban?" question.
- **`00-system/mocs/000 Workbench MOC.md`**: a prior hand-maintained command-center note, whose own title says "Concepts **Outdated**." Its category list (work, buy, org, dev, music, eat, cook, clean, explore, idea, city watch) closely mirrors the hand-drawn Time Management Matrix from the parent roadmap's Block A — same categorization instinct, different era. The lesson taken: a static, manually-maintained index didn't survive; it needs to be a live/generated view instead.

## 2. Tags vs Links convention

**Decision: Level 1 only (prompt convention), no retrofit, no validation layer for now.**

Add the rule explicitly to the knowledge-management skill's system prompt (`memory/00-system/skills/knowledge-management.md`): tags are short status/action-type markers; anything that's a topic, or connects to another note, is a `[[link]]`, never a tag. This is the same mechanism every other Mazkir convention uses today — no code change, no schema validation, just better instructions for `save_knowledge` to follow.

Explicitly deferred, not part of this build:
- **Level 2 (soft validation)** — a heuristic check (e.g. flagging a proposed tag that matches an existing note title) surfaced as a warning. Revisit only if the prompt-only approach turns out to drift in practice.
- **Level 3 (retrofit)** — a one-time cleanup pass over existing notes that already misuse tags-as-topics. Not scheduled.

## 3. Task/Rigidity levels

**Decision: keep `daily_rollover`'s current behavior as-is.** The old note's objection to "moving checkboxes through periodic notes" was about manual, tedious dragging in raw Obsidian — Mazkir's rollover already automates that, so the original friction doesn't apply. No auto-promotion-after-N-rollovers feature.

The old open question — "when to promote to Kanban?" — remains explicitly out of scope. No Kanban/board feature is planned as part of this design.

## 4. Command-center page

### 4.1 Current REST/frontend reality (checked, not assumed)

| Resource | GET list | GET detail | POST create | PATCH update | DELETE |
|---|---|---|---|---|---|
| Tasks | yes | yes (`/{slug}`) | yes | yes (`/{name}`) | no (agent-gated only) |
| Goals | yes | no | yes | no | no (agent-gated only) |
| Habits | yes | no | yes | yes (`/{name}`) | no (agent-gated only) |
| Notes | yes (+ `/featured`) | yes | no | checkbox-toggle only | no |

The webapp's `services/api.ts` does not call `/tasks`, `/goals`, or `/habits` today — there is no task/goal management UI in the webapp yet.

### 4.2 V1 scope: live overview + status/metadata updates + CRUD

A new webapp feature (new directory alongside `dayplanner`/`playground`, following the same Zustand-store + `api.ts`-call shape) showing:
- Active tasks (file-tier + daily-tier) and goals with progress, recent knowledge notes — replacing the old static Workbench MOC with a generated view of current vault state, in the same spirit as how `/day` assembles its feed.
- Inline status/metadata editing (priority, due date, progress, tags) against the resources above.
- Creation of new tasks/goals/notes directly from the page.

**Backend gaps to fill:**
- Goals: add `GET /goals/{slug}` and `PATCH /goals/{name}`, mirroring the existing `tasks.py` pattern — small.
- Notes: add real create + metadata-edit endpoints (tags/links/source), beyond the current read + checkbox-toggle-only surface — medium, since this means safely parsing/rewriting YAML frontmatter, not just flipping a checkbox line.
- Deletion/archival stays agent-gated (confidence-gated, previewed) rather than exposed as a raw REST `DELETE` — consistent with how every other destructive action in Mazkir already works; not treated as a gap.

**Frontend:** new feature directory, list/detail/edit views for tasks/goals/notes, reusing the established `dayplanner`/`playground` shape. No new architectural pattern.

**Sizing:** medium — comparable to a P4/P5-style phase, mostly filling in existing route patterns rather than inventing new ones.

### 4.3 Linking workbench (v2 — deferred, sketched for complexity estimation only)

Not part of this build. Sketch, for future reference:
- **Reading "what's linked to what"**: cheap — reuse the existing `get_related` tool / `memory_service.py` graph index rather than building a separate backlink index. Obsidian-style linking doesn't need a stored reverse-index; backlinks are computed by searching for `[[note-name]]` references, which the graph index already does.
- **Creating a link from the UI**: needs (a) a picker to search for a link target, reusing `search_knowledge`, and (b) an endpoint appending to the target's `links:` frontmatter list — a read-modify-write on YAML frontmatter, similar to existing `vault_service.py` field-update patterns.
- **Sizing:** small-medium, and cheaper as a v2 addition than if built standalone, since it rides on V1's note-browsing UI and existing search/graph tools.

## 5. Out of scope for this design
- Level 2/3 tags-vs-links enforcement (validation, retrofit).
- Any Kanban/board-style task representation.
- The linking workbench itself (sketched above, not built).
- Auto-promotion-after-N-rollovers or any other change to `daily_rollover` behavior.

## 6. Next steps
Implementation planning for §4.2 (command-center V1) once this design is reviewed; §4.3 (linking) revisited as a v2 once V1 is in use.
