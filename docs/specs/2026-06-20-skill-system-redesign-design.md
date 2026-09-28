# Skill System Redesign — Domain-Oriented Skills + Knowledge Read Fix

**Date:** 2026-06-20
**Status:** Approved (design)

## Problem

Two concrete failures in the current three-skill system (`capture` / `manager` / `recall`):

1. **Search-but-can't-read.** `MemoryService.search_knowledge` (`memory_service.py:256`)
   returns only `{path, name, tags, score}` — never the note body. There is **no tool
   anywhere** to read a knowledge note's full content by path. The `recall` agent can
   confirm a note exists but cannot open it, so it cannot actually answer "what did I
   write about X".

2. **Won't converse.** The `recall` skill prompt is scoped to *"questions about what is
   already in the vault"* and explicitly carries no license for general conversation. A
   general question (e.g. "explain this ML concept") gets refused with "I'm not a
   general-purpose tutor or Q&A bot". The user wants Mazkir to hold a normal
   conversation and pull vault data as needed.

The current split is organized by *interaction style* (quick-capture vs. deliberate-manage
vs. read-only-recall). The redesign reorganizes by **domain**, which is also more
extensible as new capabilities are added later.

## Design

### New skill set

The `capture` / `manager` / `recall` trio is replaced by four domain skills. Files live in
`memory/00-system/skills/` (**renamed** from `mazkir-skills/`).

| Skill | File | Model | Purpose |
|---|---|---|---|
| **mazkir** *(router fallback)* | `mazkir.md` | `claude-sonnet-4-6` | Converse, answer general questions, read/pull vault data, file loose daily-journal lines. Hands off writes to domain skills. |
| **time-management** | `time-management.md` | `claude-sonnet-4-6` | Tasks, habits, goals, events, daily tasks, schedule, rollover. |
| **knowledge-management** | `knowledge-management.md` | `claude-sonnet-4-6` | Read, summarize, and file knowledge notes. |
| **motivation-management** | `motivation-management.md` | `claude-haiku-4-5` | Tokens. Thin placeholder to grow. |

#### `mazkir` (fallback, conversational)

- **Tools (read-only + daily journal):** `search_knowledge`, `read_knowledge` *(new)*,
  `get_related`, `list_tasks`, `list_habits`, `list_goals`, `list_events`, `get_daily`,
  `read_daily_section`, `get_tokens`, `attach_to_daily`, `edit_daily_section`.
- **max_iterations:** 8
- **next_skills:** `[time-management, knowledge-management, motivation-management]`
- **Prompt** explicitly licenses general conversation and Q&A: Mazkir is a capable
  assistant that *also* has the user's vault — not a vault-only lookup bot. It answers
  general questions directly, and uses its read tools to ground answers in the vault when
  relevant. It owns loose daily-journal capture (`attach_to_daily`, `edit_daily_section`).
  Any task/habit/goal/event change → `next_skill: time-management`. Saving a durable
  knowledge note → `next_skill: knowledge-management`.

#### `time-management`

- **Tools:** `list_tasks`, `list_habits`, `list_goals`, `list_events`, `get_daily`,
  `read_daily_section`, `create_task`, `update_task`, `complete_task`, `delete_task`,
  `archive_task`, `create_habit`, `update_habit`, `complete_habit`, `delete_habit`,
  `create_goal`, `update_goal`, `archive_goal`, `create_event`, `update_event`,
  `attach_photo_to_event`, `daily_add_task`, `daily_set_task_state`, `daily_rollover`,
  `promote_daily_task`.
- **max_iterations:** 10
- **next_skills:** `[mazkir, knowledge-management]`
- **Prompt** carries over the planning/priority/confidence/error-handling guidance from the
  current `manager` prompt (priority 5=highest, read-before-write, `_confidence` gates,
  `ALREADY_DONE` / `STATE_CONFLICT` / `CANCELLED_BY_USER` handling, parallel batching).

#### `knowledge-management`

- **Tools:** `search_knowledge`, `read_knowledge` *(new)*, `get_related`, `save_knowledge`.
- **max_iterations:** 5
- **next_skills:** `[mazkir, time-management]`
- **Prompt:** read/summarize/file knowledge notes. Canonical flow `search_knowledge` →
  `read_knowledge(path)` → answer or dedup before `save_knowledge`. Time-anchored content
  is not knowledge → `next_skill: time-management` for `create_event`.

#### `motivation-management`

- **Tools:** `get_tokens`.
- **max_iterations:** 3
- **next_skills:** `[mazkir]`
- **Prompt:** report token balance; placeholder skill, kept thin intentionally.

### New tool: `read_knowledge`

Fixes failure #1. Risk class: **safe** (read-only, ungated).

- **Schema / input:**
  - `path` (string, optional) — vault-relative path as returned by `search_knowledge`.
  - `name` (string, optional) — human-readable note name / slug, used when `path` is absent.
  - At least one of `path` / `name` required.
- **Handler `_tool_read_knowledge`:**
  - If `path` given: `self.vault.read_file(path)`.
  - Else resolve `name` to a path under `60-knowledge/notes` / `60-knowledge/insights`
    (slugify + match against `list_files`; on multiple matches return `AMBIGUOUS_MATCH`
    with candidates; on none return `PATH_NOT_FOUND`).
  - **Returns** `ok({path, name, tags, content, links, source})` with `items=[path]`.
- **Registered to:** `mazkir`, `knowledge-management`.
- **Docs/count:** add to the safe-tool list and tool count in `CLAUDE.md`; add to
  `_register_tools()`.

### Routing changes

- Router fallback flips `manager` → `mazkir` in two places:
  - `main.py:89` `RouterService(claude=claude, fallback_skill="mazkir")`
  - `router_service.py:26` default param `fallback_skill: str = "mazkir"`
- `config.py:64-66` default `skills_dir` path segment `"mazkir-skills"` → `"skills"`
  (env override `MAZKIR_SKILLS_DIR` unchanged).
- Router catalog is data-driven from each skill's `description` / `when_to_use`; updated
  automatically once the new skill files exist. Write clear `when_to_use` strings so the
  Haiku router separates the four domains.
- The `next_skill` parser (`skill_executor.py:167`, regex `[a-z_-]+`) already accepts
  hyphenated names like `time-management`. No code change needed there.

### Folder rename

`memory/00-system/mazkir-skills/` → `memory/00-system/skills/`. This is in the nested
vault git repo. Move the directory, delete the three old skill files, add the four new
ones.

## Out of scope (flagged, not doing)

`search_knowledge` scores only on note **name / tags / filename**, not body text, so
"find my note about X" still misses when X appears only in the body. That is a separate
retrieval-quality improvement. The read bug is fixed independently by `read_knowledge`.
Body-text search can be a later pass.

## Files touched

**Vault (`memory/` nested repo):**
- `memory/00-system/skills/mazkir.md` *(new)*
- `memory/00-system/skills/time-management.md` *(new)*
- `memory/00-system/skills/knowledge-management.md` *(new)*
- `memory/00-system/skills/motivation-management.md` *(new)*
- delete `memory/00-system/mazkir-skills/{capture,manager,recall}.md` (folder removed)

**Code (`apps/vault-server`):**
- `src/config.py` — default `skills_dir` segment.
- `src/main.py` — `fallback_skill="mazkir"`.
- `src/services/router_service.py` — default `fallback_skill`.
- `src/services/agent_service.py` — register `read_knowledge` tool + `_tool_read_knowledge` handler.

**Tests:**
- `test_agent_service.py` — `read_knowledge` registration + handler (path branch, name
  branch, ambiguous, not-found).
- Skill-loading / router tests that reference old skill names or `mazkir-skills` path.

**Docs:**
- `CLAUDE.md` — skill list, fallback skill, tool count, safe-tool list, skills dir path,
  the `memory/00-system/skills/` reference in the repo tree.

## Testing strategy

- **Unit:** `read_knowledge` handler — `path` branch returns full content; `name` branch
  resolves; `AMBIGUOUS_MATCH` and `PATH_NOT_FOUND` error codes.
- **Skill registry:** all four new skills load; `validate()` reports zero unknown-tool /
  unknown-next_skill warnings against the live tool + skill sets.
- **Router:** fallback resolves to `mazkir`; representative messages route to the intended
  domain (a planning request → time-management, a "save this idea" → knowledge-management,
  a general question → mazkir).
- **Manual smoke:** a general question gets a conversational answer (no refusal); "what did
  I note about X" performs `search_knowledge` → `read_knowledge` → quotes the body.
