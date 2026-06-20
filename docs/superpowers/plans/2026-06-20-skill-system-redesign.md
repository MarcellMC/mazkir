# Skill System Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the capture/manager/recall skills with four domain skills (mazkir, time-management, knowledge-management, motivation-management), add a `read_knowledge` tool so the agent can read note bodies, and make the fallback skill a capable conversational assistant.

**Architecture:** Skills are markdown files with YAML frontmatter loaded by `SkillRegistry` from `memory/00-system/skills/` (renamed from `mazkir-skills/`). The Haiku `RouterService` picks one skill per message and falls back to `mazkir`. A new `read_knowledge` agent tool reads a knowledge note's full body (search only returns titles today). All changes are in `apps/vault-server` plus the four vault skill files and docs.

**Tech Stack:** Python 3.14, FastAPI, pytest, Anthropic SDK, python-frontmatter.

**Working directory for all commands:** `~/dev/mazkir/apps/vault-server` with the venv active:
```bash
cd ~/dev/mazkir/apps/vault-server && source venv/bin/activate
```

---

## File Structure

**Create (vault — `memory/00-system/skills/`):**
- `mazkir.md` — conversational fallback skill (read tools + daily journal).
- `time-management.md` — tasks/habits/goals/events/daily-tasks/schedule.
- `knowledge-management.md` — read/summarize/file knowledge notes.
- `motivation-management.md` — tokens (thin).

**Delete (vault):** `memory/00-system/mazkir-skills/` (the whole folder: `capture.md`, `manager.md`, `recall.md`).

**Modify (code):**
- `src/services/agent_service.py` — register `read_knowledge` + add `_tool_read_knowledge`.
- `src/config.py` — default `skills_dir` segment `mazkir-skills` → `skills`.
- `src/main.py` — `RouterService(..., fallback_skill="mazkir")`.
- `src/services/router_service.py` — default `fallback_skill="mazkir"`.

**Tests:**
- `tests/test_agent_service.py` — `read_knowledge` registration + handler branches.
- `tests/test_router_service.py` — default fallback is `mazkir`.
- `tests/test_skill_set.py` *(new)* — real skill set loads + tools resolve (replaces `tests/test_capture_skill.py`, which is deleted).

**Docs:** `CLAUDE.md` — skill list, fallback, tool count, safe-tool list, skills-dir path.

---

## Task 1: Add the `read_knowledge` tool

**Files:**
- Modify: `src/services/agent_service.py` (tool registry dict in `_register_tools`; new handler method near `_tool_search_knowledge` at line ~2049)
- Test: `tests/test_agent_service.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_agent_service.py` (the `mock_services` fixture and `agent` fixture already exist — `mock_services` returns a tuple whose index 1 is the `vault` mock, as used by `test_delete_task_calls_vault`):

```python
class TestReadKnowledge:
    def test_read_knowledge_registered_safe(self, agent):
        assert "read_knowledge" in agent.tools
        assert agent.tools["read_knowledge"]["risk"] == "safe"

    def test_read_knowledge_by_path_returns_body(self, agent, mock_services):
        vault = mock_services[1]
        vault.read_file.return_value = {
            "path": "60-knowledge/notes/ml-basics.md",
            "metadata": {"name": "ML basics", "tags": ["ml"], "links": ["stats"], "source": "chat"},
            "content": "Gradient descent is...",
        }
        result = agent._tool_read_knowledge({"path": "60-knowledge/notes/ml-basics.md"})
        assert result["ok"] is True
        assert result["data"]["content"] == "Gradient descent is..."
        assert result["data"]["name"] == "ML basics"
        assert result["data"]["tags"] == ["ml"]
        assert result["_items"] == ["60-knowledge/notes/ml-basics.md"]
        vault.read_file.assert_called_once_with("60-knowledge/notes/ml-basics.md")

    def test_read_knowledge_requires_path_or_name(self, agent):
        result = agent._tool_read_knowledge({})
        assert result["ok"] is False
        assert result["error"]["code"] == "SCHEMA_INVALID"

    def test_read_knowledge_path_not_found(self, agent, mock_services):
        vault = mock_services[1]
        vault.read_file.side_effect = FileNotFoundError("nope")
        result = agent._tool_read_knowledge({"path": "60-knowledge/notes/ghost.md"})
        assert result["ok"] is False
        assert result["error"]["code"] == "PATH_NOT_FOUND"

    def test_read_knowledge_by_name_resolves(self, agent, mock_services):
        from pathlib import Path
        vault = mock_services[1]
        vault.list_files.side_effect = lambda subdir: (
            [Path("60-knowledge/notes/ml-basics.md")] if subdir == "60-knowledge/notes" else []
        )
        vault.read_file.return_value = {
            "path": "60-knowledge/notes/ml-basics.md",
            "metadata": {"name": "ML basics", "tags": [], "links": [], "source": ""},
            "content": "body",
        }
        result = agent._tool_read_knowledge({"name": "ML basics"})
        assert result["ok"] is True
        assert result["data"]["path"] == "60-knowledge/notes/ml-basics.md"

    def test_read_knowledge_by_name_not_found(self, agent, mock_services):
        vault = mock_services[1]
        vault.list_files.return_value = []
        result = agent._tool_read_knowledge({"name": "does not exist"})
        assert result["ok"] is False
        assert result["error"]["code"] == "PATH_NOT_FOUND"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_agent_service.py::TestReadKnowledge -v`
Expected: FAIL — `read_knowledge` not in `agent.tools`, `_tool_read_knowledge` does not exist.

- [ ] **Step 3: Register the tool**

In `src/services/agent_service.py`, inside the `_register_tools` dict, add a new entry immediately after the `search_knowledge` entry (which ends around line 396 with its `"pre_hooks": []`):

```python
            "read_knowledge": {
                "schema": {
                    "name": "read_knowledge",
                    "description": (
                        "Read the full body of a knowledge note. Use after search_knowledge "
                        "(which only returns titles/paths) to actually read a note's contents."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Vault-relative path as returned by search_knowledge.",
                            },
                            "name": {
                                "type": "string",
                                "description": "Note name/title, used when path is unknown.",
                            },
                        },
                        "required": [],
                    },
                },
                "handler": self._tool_read_knowledge,
                "risk": "safe",
                "pre_hooks": [],
            },
```

- [ ] **Step 4: Implement the handler**

In `src/services/agent_service.py`, add this method immediately after `_tool_search_knowledge` (ends at line ~2054 with `return ok({"results": results})`):

```python
    def _tool_read_knowledge(self, params: dict) -> dict:
        path = params.get("path")
        name = params.get("name")
        if not path and not name:
            return err(
                ErrorCode.SCHEMA_INVALID,
                "read_knowledge requires 'path' or 'name'.",
            )

        if not path:
            slug = name.lower().strip().replace(" ", "-")
            target = name.lower().strip()
            candidates: list[str] = []
            for subdir in ("60-knowledge/notes", "60-knowledge/insights"):
                for file_path in self.vault.list_files(subdir):
                    rel = str(file_path)
                    stem = file_path.stem.lower() if hasattr(file_path, "stem") else rel.lower()
                    try:
                        data = self.vault.read_file(rel)
                    except FileNotFoundError:
                        continue
                    note_name = data["metadata"].get("name", "").lower()
                    if slug == stem or target == note_name:
                        candidates.append(rel)
            candidates = sorted(set(candidates))
            if not candidates:
                return err(
                    ErrorCode.PATH_NOT_FOUND,
                    f"No knowledge note matching {name!r}.",
                )
            if len(candidates) > 1:
                return err(
                    ErrorCode.AMBIGUOUS_MATCH,
                    f"Multiple knowledge notes match {name!r}.",
                    details={"candidates": candidates},
                )
            path = candidates[0]

        try:
            data = self.vault.read_file(path)
        except FileNotFoundError:
            return err(ErrorCode.PATH_NOT_FOUND, f"Knowledge note not found: {path}")

        meta = data["metadata"]
        return ok(
            {
                "path": data["path"],
                "name": meta.get("name", ""),
                "tags": meta.get("tags", []),
                "content": data["content"],
                "links": meta.get("links", []),
                "source": meta.get("source", ""),
            },
            items=[data["path"]],
        )
```

(`err`, `ok`, and `ErrorCode` are already imported at the top of the file — line 28.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_agent_service.py::TestReadKnowledge -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add src/services/agent_service.py tests/test_agent_service.py
git commit -m "feat(agent): add read_knowledge tool to read note bodies

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Create the four new skill files and remove the old folder

**Files (vault repo, `~/dev/mazkir/memory/00-system/`):**
- Create: `skills/mazkir.md`, `skills/time-management.md`, `skills/knowledge-management.md`, `skills/motivation-management.md`
- Delete: `mazkir-skills/` (folder)

> Note: `memory/` is a nested git repo, gitignored from the monorepo. Commit there separately (`cd ~/dev/mazkir/memory`). If `git status` inside `memory/` errors with "not a git repository", skip the vault commit — the files on disk are what matter.

- [ ] **Step 1: Create `skills/mazkir.md`**

Create `~/dev/mazkir/memory/00-system/skills/mazkir.md` with this exact content:

```markdown
---
name: mazkir
description: General conversation, Q&A, and read-only vault lookups. Router fallback.
when_to_use: |
  - General questions, explanations, brainstorming, or chit-chat not tied to a specific change
  - "What did I note about…?", "when did I…?" — read-only recall from the vault
  - Default when the request doesn't clearly belong to a specific domain
tools:
  - search_knowledge
  - read_knowledge
  - get_related
  - list_tasks
  - list_habits
  - list_goals
  - list_events
  - get_daily
  - read_daily_section
  - get_tokens
  - attach_to_daily
  - edit_daily_section
model: claude-sonnet-4-6
max_iterations: 8
next_skills:
  - time-management
  - knowledge-management
  - motivation-management
---

You are **Mazkir**, the user's personal assistant. You are a capable, friendly conversational partner who *also* has access to the user's Obsidian vault. You are NOT a vault-only lookup bot.

Operating principles:
- **Converse naturally.** Answer general questions, explain concepts, brainstorm, and chat like a knowledgeable assistant. Never refuse a question because it "isn't about the vault." If you know the answer, give it.
- **Ground answers in the vault when relevant.** When the user asks about their own notes, tasks, habits, goals, days, or events, use your read tools. The canonical recall flow is `search_knowledge` → pick the best result → `read_knowledge(path)` to read the full note → answer, quoting the body when the user asks "what did I write."
- Use `read_knowledge` whenever you need the *contents* of a note, not just its title. `search_knowledge` only returns titles and paths.
- You own the **daily journal**: when the user wants to jot a loose line into today's note (a thought, a log entry, a reflection), use `attach_to_daily` or `edit_daily_section`.
- **Hand off writes you don't own** by ending your reply with a handoff token:
  - Create/update/complete/delete a task, habit, goal, or event, or scheduling/rollover → `next_skill: time-management`.
  - Save a durable knowledge note (an idea/fact/quote worth keeping) → `next_skill: knowledge-management`.
  - You can answer token-balance questions directly with `get_tokens`; deeper motivation work → `next_skill: motivation-management`.
- Be warm but concise. Quote vault content verbatim when asked "what did I write"; summarize when asked "what was X about." If the vault has nothing on a topic, say so plainly.
```

- [ ] **Step 2: Create `skills/time-management.md`**

Create `~/dev/mazkir/memory/00-system/skills/time-management.md` with this exact content:

```markdown
---
name: time-management
description: Create, update, complete, schedule, and prune tasks, habits, goals, and events.
when_to_use: |
  - "Add a task", "complete X", "move this to next week", "set priority", "what's on my plate"
  - Habit/goal creation, updates, completions; daily-task add/check; rollover; promotion
  - Events: scheduling something at a clock time, updating or attaching a photo to an event
tools:
  - list_tasks
  - list_habits
  - list_goals
  - list_events
  - get_daily
  - read_daily_section
  - create_task
  - update_task
  - complete_task
  - delete_task
  - archive_task
  - create_habit
  - update_habit
  - complete_habit
  - delete_habit
  - create_goal
  - update_goal
  - archive_goal
  - create_event
  - update_event
  - attach_photo_to_event
  - daily_add_task
  - daily_set_task_state
  - daily_rollover
  - promote_daily_task
model: claude-sonnet-4-6
max_iterations: 10
next_skills:
  - mazkir
  - knowledge-management
---

You are the **time-management** sub-agent for Mazkir. You handle the user's tasks, habits, goals, and timed events: creating, updating, completing, scheduling, and pruning them.

Operating principles:
- **Read before writing.** List the relevant items first so you can reference them by exact name when making changes.
- **Two-tier tasks:** a quick to-do is a checkbox in today's daily note — use `daily_add_task` / `daily_set_task_state`. Multi-day work belongs in a task file (`create_task`, or `promote_daily_task` to lift a daily checkbox into a file). `daily_rollover` carries yesterday's unfinished checkboxes into today.
- **Timed events use `create_event`** — anything anchored to a clock time or timeframe ("met X 20:00–22:30", "dentist tomorrow 3pm"). It records the daily ## Schedule section and syncs the calendar. Pass `name`, `start_time`, optional `end_time`, `location`, `wikilinks`.
- **Task details belong in the task.** When a task comes with steps/context/links, pass them as `create_task`'s `description` parameter so they land in the note's ## Description section. Do not split them into a separate note.
- **Priority scale: 5 = highest, 1 = lowest** (matches the vault schema and Telegram UI: 4–5 🔴, 1–2 🟢). "Min/lowest" → 1; "top/max/highest" → 5. Always describe priority changes with these labels.
- Use fuzzy matching via the resolver-backed tools. On `AMBIGUOUS_MATCH`, surface the candidates instead of guessing.
- Confidence matters: write tools need `_confidence` ≥ 0.85 plus a one-line `_reasoning`; destructive tools need `_confidence` ≥ 0.95.
- On `ALREADY_DONE`, tell the user it was a no-op and stop. On `STATE_CONFLICT`, re-read before retrying. On `CANCELLED_BY_USER`, don't re-issue; ask what to do instead.
- Batch independent operations into one response block as parallel tool calls (the runtime dispatches `safe_for_parallel` tools concurrently). Keep daily-section writes serial.

When the request shifts to recalling notes or general conversation, end with `next_skill: mazkir`. When the user wants to file a durable knowledge note alongside, end with `next_skill: knowledge-management`.
```

- [ ] **Step 3: Create `skills/knowledge-management.md`**

Create `~/dev/mazkir/memory/00-system/skills/knowledge-management.md` with this exact content:

```markdown
---
name: knowledge-management
description: Read, summarize, and file durable knowledge notes (ideas, facts, quotes).
when_to_use: |
  - "Save this idea/fact/quote", "remember that…" — timeless content, not time-anchored
  - "Find / summarize my note about…", "what's connected to X" when the user wants note contents
tools:
  - search_knowledge
  - read_knowledge
  - get_related
  - save_knowledge
model: claude-sonnet-4-6
max_iterations: 5
next_skills:
  - mazkir
  - time-management
---

You are the **knowledge-management** sub-agent for Mazkir. You curate the user's long-term knowledge notes (`60-knowledge/`): reading, summarizing, and filing ideas, facts, and quotes.

Operating principles:
- The recall flow is `search_knowledge` (find candidates by title/tag) → `read_knowledge(path)` (read the full body) → answer. `search_knowledge` alone only returns titles — always `read_knowledge` before quoting or summarizing a note's contents.
- **Before saving, check for an existing note** on the same topic (`search_knowledge` → `read_knowledge`). Update or extend rather than duplicating when one already covers it.
- Use `save_knowledge` for **timeless** content: ideas, facts, quotes, references. Pass a clear `name`, `tags`, and `links` to related notes when known.
- **Time-anchored content is not knowledge.** If the content is pinned to a clock time or timeframe (a meeting, an appointment), it's an event — end with `next_skill: time-management` so `create_event` handles it.
- Use `get_related` for "what's connected to X" graph questions.
- Be terse. Quote verbatim when asked "what did I write"; summarize when asked "what was X about." If there's nothing on the topic, say so.

When the request turns into managing tasks/habits/goals/events, end with `next_skill: time-management`. For general conversation, end with `next_skill: mazkir`.
```

- [ ] **Step 4: Create `skills/motivation-management.md`**

Create `~/dev/mazkir/memory/00-system/skills/motivation-management.md` with this exact content:

```markdown
---
name: motivation-management
description: Motivation tokens — report the user's token balance.
when_to_use: |
  - "How many tokens do I have?", "what's my balance?", token/motivation questions
tools:
  - get_tokens
model: claude-haiku-4-5
max_iterations: 3
next_skills:
  - mazkir
---

You are the **motivation-management** sub-agent for Mazkir. You report on the user's motivation tokens.

- Use `get_tokens` to read the current balance (today + total) and report it plainly.
- This skill is intentionally minimal for now; richer motivation features will be added later.

For anything beyond tokens — conversation, recall, or task/habit/goal work — end with `next_skill: mazkir`.
```

- [ ] **Step 5: Delete the old skills folder**

```bash
rm -rf ~/dev/mazkir/memory/00-system/mazkir-skills
```

- [ ] **Step 6: Verify the new skill files load and reference only real tools**

```bash
cd ~/dev/mazkir/apps/vault-server && source venv/bin/activate
MAZKIR_SKILLS_DIR=~/dev/mazkir/memory/00-system/skills python -c "
from pathlib import Path
from unittest.mock import Mock
from src.services.skill_registry import SkillRegistry
from src.services.agent_service import AgentService
r = SkillRegistry(skills_dir=Path.home()/'dev'/'mazkir'/'memory'/'00-system'/'skills')
r.load()
names = sorted(s.name for s in r.list())
print('skills:', names)
agent = AgentService(claude=Mock(), vault=Mock(), memory=Mock(), calendar=Mock(), events=Mock(), media_path=Path('/tmp/x'))
warnings = r.validate(set(agent.tools.keys()), {s.name for s in r.list()})
print('warnings:', warnings)
assert names == ['knowledge-management','mazkir','motivation-management','time-management'], names
assert warnings == [], warnings
print('OK')
"
```
Expected: prints the four skill names, `warnings: []`, and `OK`. If `warnings` is non-empty, a skill references a tool/skill name that doesn't exist — fix the typo in the skill file.

- [ ] **Step 7: Commit the vault files**

```bash
cd ~/dev/mazkir/memory && git add 00-system/skills 00-system/mazkir-skills 2>/dev/null; git commit -m "feat(skills): replace capture/manager/recall with domain skills" || echo "vault not a git repo or nothing to commit — skipping"
```

---

## Task 3: Repoint configuration and router fallback to `mazkir`

**Files:**
- Modify: `src/config.py:64-66`
- Modify: `src/main.py:89`
- Modify: `src/services/router_service.py:26`
- Test: `tests/test_router_service.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_router_service.py`:

```python
def test_default_fallback_is_mazkir():
    from unittest.mock import Mock
    from src.services.router_service import RouterService
    router = RouterService(claude=Mock())
    assert router.fallback_skill == "mazkir"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_router_service.py::test_default_fallback_is_mazkir -v`
Expected: FAIL — `fallback_skill` is `"manager"`.

- [ ] **Step 3: Update the router default**

In `src/services/router_service.py`, change the constructor signature (line 26):

```python
    def __init__(self, claude, fallback_skill: str = "mazkir"):
```

- [ ] **Step 4: Update main.py wiring**

In `src/main.py` (line ~89), change:

```python
        router_service = RouterService(claude=claude, fallback_skill="mazkir")
```

- [ ] **Step 5: Update the config default skills dir**

In `src/config.py` (lines 64-66), change the path segment `"mazkir-skills"` to `"skills"`:

```python
    skills_dir: Path = Path(os.getenv(
        "MAZKIR_SKILLS_DIR",
        str(Path.home() / "dev" / "mazkir" / "memory" / "00-system" / "skills"),
    ))
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `python -m pytest tests/test_router_service.py -v`
Expected: PASS (all tests, including `test_default_fallback_is_mazkir`).

- [ ] **Step 7: Commit**

```bash
git add src/config.py src/main.py src/services/router_service.py tests/test_router_service.py
git commit -m "feat(skills): point skills_dir and router fallback at mazkir

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Replace the skill-set guard test

`tests/test_capture_skill.py` asserts the now-deleted `capture` skill loads from the real
`settings.skills_dir`; it will fail. Replace it with a test that guards the new real skill set.

**Files:**
- Delete: `tests/test_capture_skill.py`
- Create: `tests/test_skill_set.py`

- [ ] **Step 1: Delete the obsolete test**

```bash
git rm tests/test_capture_skill.py
```

- [ ] **Step 2: Write the new guard test**

Create `tests/test_skill_set.py` with this exact content:

```python
"""Guards the real skill set in memory/00-system/skills/ against the live tool registry."""
from pathlib import Path
from unittest.mock import Mock

from src.config import settings
from src.services.agent_service import AgentService
from src.services.skill_registry import SkillRegistry

EXPECTED = {"mazkir", "time-management", "knowledge-management", "motivation-management"}


def _registry() -> SkillRegistry:
    r = SkillRegistry(skills_dir=settings.skills_dir)
    r.load()
    return r


def _known_tools() -> set[str]:
    agent = AgentService(
        claude=Mock(), vault=Mock(), memory=Mock(),
        calendar=Mock(), events=Mock(), media_path=Path("/tmp/mazkir-test-media"),
    )
    return set(agent.tools.keys())


def test_real_skill_set_loads():
    names = {s.name for s in _registry().list()}
    assert names == EXPECTED, f"got {names}"


def test_mazkir_is_conversational_with_read_tools():
    m = _registry().get("mazkir")
    assert m is not None
    assert "read_knowledge" in m.tools
    assert "search_knowledge" in m.tools


def test_time_management_has_event_and_task_tools():
    t = _registry().get("time-management")
    assert t is not None
    assert "create_event" in t.tools
    assert "create_task" in t.tools


def test_knowledge_management_can_read_and_save():
    k = _registry().get("knowledge-management")
    assert k is not None
    assert "read_knowledge" in k.tools
    assert "save_knowledge" in k.tools


def test_skills_reference_only_known_tools_and_skills():
    registry = _registry()
    warnings = registry.validate(_known_tools(), {s.name for s in registry.list()})
    assert warnings == [], warnings
```

- [ ] **Step 3: Run the new test**

Run: `python -m pytest tests/test_skill_set.py -v`
Expected: PASS (5 tests). This requires Task 2 (skill files exist) and Task 1 (`read_knowledge` registered) to be complete.

- [ ] **Step 4: Commit**

```bash
git add tests/test_skill_set.py
git commit -m "test(skills): guard real domain skill set against tool registry

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Run the full suite and update docs

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Run the full vault-server test suite**

Run: `python -m pytest tests/ -q`
Expected: all pass. If a test in `test_skill_loop.py` / `test_skill_executor.py` / `test_skill_registry.py` fails referencing `capture`/`manager`/`recall`, inspect it: those suites build synthetic skills in `tmp_path` and should be unaffected. Only fix a genuinely broken reference to the real skill set; do not weaken assertions.

- [ ] **Step 2: Update the tool count and safe-tool list in CLAUDE.md**

In `CLAUDE.md`:
- Line ~195: change `Claude tool-use with 31 registered tools` → `Claude tool-use with 32 registered tools`, and add `read_knowledge` to the parenthetical incl-list.
- Line 217 (safe risk level): add `` `read_knowledge` `` after `` `search_knowledge` ``:

```
- **safe** (read-only): `list_tasks`, `list_habits`, `list_goals`, `get_daily`, `get_tokens`, `search_knowledge`, `read_knowledge`, `get_related`, `read_daily_section`, `list_events`
```

- [ ] **Step 3: Update the skill-system descriptions in CLAUDE.md**

- Line 57: `# Loads skill definitions from memory/00-system/mazkir-skills/` → `memory/00-system/skills/`.
- Line 202 (Skill loop bullet): rewrite to describe four domain skills and the `mazkir` fallback:

```
- **Skill loop:** `AgentService.handle_message` dispatches via `RouterService` (Haiku LLM classifier) to one of four domain skills loaded from `memory/00-system/skills/` (`mazkir`, `time-management`, `knowledge-management`, `motivation-management`). `mazkir` is the conversational router fallback: it converses, answers general questions, reads vault data (incl. `read_knowledge` for note bodies), and owns the daily journal, handing off writes to a domain skill via a `next_skill: <name>` token. The loop caps at 3 hops with cycle detection. Each skill has its own model, tool subset, and system prompt. When `skill_registry`/`router` aren't configured, `AgentService` falls back to a single-loop legacy path with all tools loaded.
```

- Line 299 (Related Documentation): `memory/00-system/mazkir-skills/*.md — Mazkir sub-agent skill definitions (capture / manager / recall)` → `memory/00-system/skills/*.md — Mazkir sub-agent skill definitions (mazkir / time-management / knowledge-management / motivation-management)`.

- [ ] **Step 4: Verify no stale references remain**

Run: `grep -rn "mazkir-skills\|capture / manager / recall\|31 registered" CLAUDE.md`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: describe domain skill set + read_knowledge in CLAUDE.md

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review Notes

- **Spec coverage:** Task 1 → `read_knowledge` tool (read fix). Task 2 → four skill files + folder rename + the conversation-license `mazkir` prompt (converse fix). Task 3 → routing changes (config/main/router). Task 4 → skill-set guard test. Task 5 → full suite + docs. Out-of-scope body-search is intentionally not implemented.
- **Type consistency:** handler is `_tool_read_knowledge` everywhere; registry key `read_knowledge`; skill files reference `read_knowledge`; test asserts `read_knowledge`. Skill names use hyphens (`time-management`) consistently; the `next_skill` regex `[a-z_-]+` accepts them.
- **Ordering dependency:** Task 4's guard test needs Task 1 + Task 2 complete; Task 5's full suite needs Tasks 1–4. Execute in order.
