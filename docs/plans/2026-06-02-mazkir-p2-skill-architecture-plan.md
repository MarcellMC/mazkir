# Mazkir P2 — Skill Architecture + P1 Rollovers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-agent-with-all-27-tools surface with a router + sub-agent ("skill") architecture, where each skill is a markdown file in the vault declaring its toolbox, model, and system prompt. Also fold in three follow-ups from the P1 final review.

**Architecture:** A new `SkillRegistry` loads markdown skill files from `memory/00-system/mazkir-skills/`. A new `RouterService` uses a Haiku LLM call to classify the user's intent and pick a skill. `AgentService.handle_message` becomes a skill loop: route → run skill agent loop with its restricted toolbox → detect `next_skill` handoff → cap at 3 hops. Confidence gates move from a global threshold to per-tool, defaulted by risk class. Destructive tools require a `preview` step before execution.

**Tech Stack:** Python 3.14, FastAPI, Anthropic SDK (Haiku for router/capture/recall, Sonnet for manager), `python-frontmatter` for skill files. Tests via `pytest`.

**Spec source:** `docs/plans/2026-06-01-mazkir-usability-design.md` — Blocks D3 (sub-agent architecture) and D4 (confidence gate + preview + hooks).

**Out of scope for this plan (deferred to later P-plans):**
- Daily-tier tools (`daily_add_task`, `daily_set_task_state`, `daily_rollover`, `promote_daily_task`) — P4
- Calendar sync as `post_to_calendar` post-hook — P5 (the post-hook framework lands here, but no actual post-hooks ship)
- Streaming responses to Telegram — P5
- Parallel tool execution (`safe_for_parallel`) — P5
- Media migration to vault — P4
- Schema migration for existing vault files

---

## File Structure

**Create:**
- `apps/vault-server/src/services/skill_registry.py` — parses `mazkir-skills/*.md` into `Skill` objects, validates tool references, exposes `get(name) / list()`
- `apps/vault-server/src/services/router_service.py` — LLM classifier that returns a skill name given user message + skill descriptions
- `apps/vault-server/src/services/preview.py` — registry of `preview_fn(params, ctx) → str` for destructive tools
- `apps/vault-server/tests/test_skill_registry.py`
- `apps/vault-server/tests/test_router_service.py`
- `apps/vault-server/tests/test_skill_loop.py`
- `apps/vault-server/tests/test_preview.py`
- `apps/vault-server/tests/test_per_tool_thresholds.py`
- `memory/00-system/mazkir-skills/capture.md`
- `memory/00-system/mazkir-skills/manager.md`
- `memory/00-system/mazkir-skills/recall.md`

**Modify:**
- `apps/vault-server/src/services/agent_service.py` — integrate `SkillRegistry` + `RouterService`; replace flat agent loop with skill-aware loop; per-tool confidence thresholds; preview-before-execute path; wire `post_hooks` slot; add skill / preview span attributes; rollover items (extend create_* tool schemas, swap `complete_habit` to resolver)
- `apps/vault-server/src/config.py` — add `MAZKIR_SKILLS_DIR` setting
- `apps/vault-server/src/main.py` — instantiate `SkillRegistry` and `RouterService` in lifespan, pass into `AgentService`
- `apps/vault-server/tests/test_agent_service.py` — update tests for skill-aware loop, per-tool thresholds, preview flow
- `CLAUDE.md` — document skill architecture and per-tool gate model

---

## Task 1: P1 rollover — extend `create_*` tool schemas with new fields

The P1 final reviewer flagged that `vault_service.create_task/habit/goal` accept `scheduled_at`/`duration_minutes`/`due_soft`/`start_date` (added in P1 T7), but the **agent tool registration entries** never exposed these fields to the model. Close the gap so the agent can set scheduling at creation time, not only via `update_*`.

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py`
- Modify: `apps/vault-server/tests/test_agent_service.py`

- [ ] **Step 1: Write failing tests**

Append to `apps/vault-server/tests/test_agent_service.py`:

```python
def test_create_task_tool_schema_exposes_scheduling_fields(mock_services):
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)

    props = agent.tools["create_task"]["schema"]["input_schema"]["properties"]
    assert "scheduled_at" in props
    assert "duration_minutes" in props
    assert "due_soft" in props


def test_create_task_handler_passes_scheduling_fields_through(mock_services):
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)
    agent.vault.create_task.return_value = {
        "path": "40-tasks/active/x.md",
        "metadata": {"name": "X", "scheduled_at": "2026-06-05T14:00"},
    }

    result = agent._tool_create_task({
        "name": "X",
        "priority": 3,
        "scheduled_at": "2026-06-05T14:00",
        "duration_minutes": 60,
        "due_soft": "2026-06-08",
    })

    assert result["ok"] is True
    kwargs = agent.vault.create_task.call_args.kwargs
    assert kwargs.get("scheduled_at") == "2026-06-05T14:00"
    assert kwargs.get("duration_minutes") == 60
    assert kwargs.get("due_soft") == "2026-06-08"


def test_create_habit_tool_schema_exposes_scheduling_fields(mock_services):
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)
    props = agent.tools["create_habit"]["schema"]["input_schema"]["properties"]
    assert "scheduled_at" in props
    assert "duration_minutes" in props


def test_create_goal_tool_schema_exposes_start_date(mock_services):
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)
    props = agent.tools["create_goal"]["schema"]["input_schema"]["properties"]
    assert "start_date" in props
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/marcellmc/dev/mazkir/apps/vault-server
source venv/bin/activate
python -m pytest tests/test_agent_service.py -k "schema_exposes or scheduling_fields_through or exposes_start_date" -v
```

Expected: FAIL with `assert "scheduled_at" in props` (KeyError or assertion).

- [ ] **Step 3: Extend tool registration entries**

In `agent_service.py`, locate `_register_tools` entry for `"create_task"`. Add these properties under `input_schema.properties`:

```python
"scheduled_at": {"type": ["string", "null"], "description": "ISO datetime (e.g. 2026-06-05T14:00)"},
"duration_minutes": {"type": ["integer", "null"]},
"due_soft": {"type": ["string", "null"], "description": "Soft deadline YYYY-MM-DD"},
```

Same for `"create_habit"`:

```python
"scheduled_at": {"type": ["string", "null"], "description": "Recurring daily slot HH:MM"},
"duration_minutes": {"type": ["integer", "null"]},
```

Same for `"create_goal"`:

```python
"start_date": {"type": ["string", "null"], "description": "Goal start date YYYY-MM-DD"},
```

- [ ] **Step 4: Extend the handlers to pass new fields through**

Update `_tool_create_task` to forward optional fields:

```python
def _tool_create_task(self, params: dict) -> dict:
    result = self.vault.create_task(
        name=params["name"],
        priority=params.get("priority", 3),
        due_date=params.get("due_date"),
        category=params.get("category", "general"),
        tokens_on_completion=params.get("tokens_on_completion", 5),
        scheduled_at=params.get("scheduled_at"),
        duration_minutes=params.get("duration_minutes"),
        due_soft=params.get("due_soft"),
    )
    # ... existing calendar-sync branch and return statement stay the same;
    # just make sure success path uses ok(...) (already true from P1 T18)
```

Apply the same pattern to `_tool_create_habit` (`scheduled_at`, `duration_minutes`) and `_tool_create_goal` (`start_date`). Read each handler's current code first to integrate cleanly.

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/test_agent_service.py -k "schema_exposes or scheduling_fields_through or exposes_start_date" -v
python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: 4 new tests pass, full suite green at 282.

- [ ] **Step 6: Commit**

```bash
cd /home/marcellmc/dev/mazkir
git add apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_agent_service.py
git commit -m "feat(vault-server): expose scheduling + lifecycle fields on create_* tool schemas (P1 rollover)"
```

---

## Task 2: P1 rollover — verify and reconcile real vault `status` values with the `update_task` enum

The P1 final reviewer flagged that `update_task`'s `status` enum is `["active", "blocked", "done"]`. If real vault files use other values (e.g. `in_progress`, `completed`, `cancelled`), `validate_schema` will reject those updates. Verify and decide.

**Files:**
- Modify (potentially): `apps/vault-server/src/services/agent_service.py` — widen the enum if needed.

- [ ] **Step 1: Inventory current status values across all three item types**

```bash
cd /home/marcellmc/dev/mazkir
grep -h "^status:" memory/40-tasks/**/*.md 2>/dev/null | sort -u
grep -h "^status:" memory/20-habits/*.md 2>/dev/null | sort -u
grep -h "^status:" memory/30-goals/**/*.md 2>/dev/null | sort -u
```

Capture the output. Expected: at minimum `status: active` and `status: done`.

- [ ] **Step 2: Inventory enums declared in update_* tool schemas**

```bash
grep -n '"enum"' apps/vault-server/src/services/agent_service.py | head -20
```

Note the enums declared for `update_task.status`, `update_goal.status`. (`update_habit` has no `status` field — habits use `frequency` + `last_completed`.)

- [ ] **Step 3: Reconcile**

Compare. For each mismatch:
- If a real file uses a value not in the enum → either widen the enum, OR file a separate ticket / TODO and fix the vault file.
- Preference order: widen the enum if the value is a legitimate state we want to support; rename the vault file's status if it was a typo or one-off.

Document the chosen reconciliation in this task's commit message.

- [ ] **Step 4: If the enum was widened, update the schema**

For example, if `archived` is found in `40-tasks/`:

```python
"status": {"type": "string", "enum": ["active", "blocked", "done", "archived"]},
```

Same for `update_goal` if needed.

- [ ] **Step 5: Run full test suite**

```bash
cd apps/vault-server
source venv/bin/activate
python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: 282 passing (no behavioral change from Task 1 unless an enum was widened, which still keeps all tests passing).

- [ ] **Step 6: Commit**

```bash
cd /home/marcellmc/dev/mazkir
git add apps/vault-server/src/services/agent_service.py
git commit -m "fix(vault-server): reconcile update_* status enum with real vault values (P1 rollover)"
```

If no enum change was required, commit a one-line documentation note instead (e.g. add a comment beside the enum noting the verified-against date), or skip this commit and document the verification result in the next commit's body.

---

## Task 3: P1 rollover — migrate `complete_habit` to the unified resolver

P1's T16 migrated 5 destructive handlers to `resolve_item`, intentionally skipping `_tool_complete_habit` because it used a different fuzzy-iteration approach. Migrate it now for consistency and to unlock `AMBIGUOUS_MATCH` detection.

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py`
- Modify: `apps/vault-server/tests/test_agent_service.py`

- [ ] **Step 1: Write failing tests**

Append to `apps/vault-server/tests/test_agent_service.py`:

```python
def test_complete_habit_uses_resolver_for_fuzzy_match(mock_services):
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)
    agent.vault.list_active_habits.return_value = [
        {"path": "20-habits/morning-workout.md", "metadata": {"name": "Morning workout"}}
    ]
    agent.vault.read_file.return_value = {
        "path": "20-habits/morning-workout.md",
        "metadata": {"name": "Morning workout"},
    }
    agent.vault.complete_habit.return_value = {
        "habit_name": "Morning workout",
        "streak": 8,
        "tokens_earned": 5,
    }

    result = agent._tool_complete_habit({"habit_name": "workout"})

    assert result["ok"] is True


def test_complete_habit_ambiguous_returns_candidates(mock_services):
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)
    agent.vault.list_active_habits.return_value = [
        {"path": "20-habits/morning-workout.md", "metadata": {"name": "Morning workout"}},
        {"path": "20-habits/evening-workout.md", "metadata": {"name": "Evening workout"}},
    ]
    result = agent._tool_complete_habit({"habit_name": "workout"})
    assert result["ok"] is False
    assert result["error"]["code"] == "AMBIGUOUS_MATCH"
```

- [ ] **Step 2: Run to confirm they fail**

```bash
python -m pytest tests/test_agent_service.py -k "complete_habit_uses_resolver or complete_habit_ambiguous" -v
```

Expected: FAIL — current handler uses substring iteration and won't return AMBIGUOUS_MATCH.

- [ ] **Step 3: Migrate `_tool_complete_habit`**

Find the handler. Replace the existing `list_active_habits` + manual substring loop with the resolver pattern. Preserve the existing idempotency check from P1 T14 and the calendar mark-event-complete branch.

Note: `vault.complete_habit` may currently take a habit-name string, not a path. Check its signature first; if it takes a name, you can either:
- Pass the resolved name to `complete_habit`, OR
- Refactor `vault.complete_habit` to take a path (preferred for consistency with `vault.complete_task`).

Pick the path-based refactor if it's a one-line change inside `vault_service.complete_habit`. Otherwise pass the resolved name to keep the change small.

Skeleton:

```python
def _tool_complete_habit(self, params: dict) -> dict:
    import datetime as dt
    from src.services.resolver import resolve_item

    resolved = resolve_item("habit", params["habit_name"], self.vault)
    if not resolved["ok"]:
        return resolved

    path = resolved["data"]["path"]
    habit = self.vault.read_file(path)

    today = dt.date.today().isoformat()
    if habit["metadata"].get("last_completed") == today:
        return err(
            ErrorCode.ALREADY_DONE,
            f"Habit '{habit['metadata'].get('name', '')}' already completed today",
            details={"path": path, "streak": habit["metadata"].get("streak", 0)},
        )

    # Existing complete_habit body (call vault, sync calendar, etc.)
    # Adapt to use `path` and `habit["metadata"]` instead of the previous
    # loop-found `habit` variable.

    return ok({...}, items=[path])
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_agent_service.py -k "complete_habit" -v
python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: new tests pass, existing complete_habit tests still pass (may need mock updates: switch from `list_active_habits` substring expectation to `list_active_habits` + `read_file`).

- [ ] **Step 5: Commit**

```bash
cd /home/marcellmc/dev/mazkir
git add apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_agent_service.py
git commit -m "refactor(vault-server): complete_habit uses unified resolver (P1 rollover)"
```

---

## Task 4: `SkillRegistry` — load and parse skill markdown files

**Files:**
- Create: `apps/vault-server/src/services/skill_registry.py`
- Create: `apps/vault-server/tests/test_skill_registry.py`

- [ ] **Step 1: Write failing tests**

Create `apps/vault-server/tests/test_skill_registry.py`:

```python
"""Tests for SkillRegistry — parses skill markdown files from vault."""

import pytest
from pathlib import Path

from src.services.skill_registry import Skill, SkillRegistry


def _write_skill(dir: Path, name: str, content: str) -> Path:
    dir.mkdir(parents=True, exist_ok=True)
    path = dir / f"{name}.md"
    path.write_text(content)
    return path


SAMPLE_CAPTURE = """---
name: capture
description: Fast inbox-style captures
when_to_use: |
  - User dumps text or a photo with no clear intent
tools: [save_knowledge, create_task]
model: claude-haiku-4-5
max_iterations: 3
next_skills: [manager, recall]
---

# Capture skill system prompt

You receive quick captures from the user.
"""


def test_registry_loads_skill_from_markdown(tmp_path):
    _write_skill(tmp_path, "capture", SAMPLE_CAPTURE)
    registry = SkillRegistry(skills_dir=tmp_path)
    registry.load()

    skill = registry.get("capture")
    assert isinstance(skill, Skill)
    assert skill.name == "capture"
    assert skill.description == "Fast inbox-style captures"
    assert skill.tools == ["save_knowledge", "create_task"]
    assert skill.model == "claude-haiku-4-5"
    assert skill.max_iterations == 3
    assert skill.next_skills == ["manager", "recall"]
    assert "You receive quick captures" in skill.system_prompt


def test_registry_lists_all_skills(tmp_path):
    _write_skill(tmp_path, "capture", SAMPLE_CAPTURE)
    _write_skill(tmp_path, "recall", SAMPLE_CAPTURE.replace("capture", "recall"))
    registry = SkillRegistry(skills_dir=tmp_path)
    registry.load()
    names = sorted(s.name for s in registry.list())
    assert names == ["capture", "recall"]


def test_registry_get_missing_returns_none(tmp_path):
    registry = SkillRegistry(skills_dir=tmp_path)
    registry.load()
    assert registry.get("nonexistent") is None


def test_registry_load_empty_dir_succeeds(tmp_path):
    registry = SkillRegistry(skills_dir=tmp_path)
    registry.load()
    assert registry.list() == []


def test_registry_load_missing_dir_succeeds(tmp_path):
    registry = SkillRegistry(skills_dir=tmp_path / "does-not-exist")
    registry.load()  # warns but does not raise
    assert registry.list() == []


def test_registry_skips_invalid_frontmatter(tmp_path, caplog):
    (tmp_path / "broken.md").write_text("not valid frontmatter")
    registry = SkillRegistry(skills_dir=tmp_path)
    registry.load()
    assert registry.get("broken") is None


def test_skill_defaults_when_optional_fields_absent(tmp_path):
    minimal = """---
name: minimal
description: A test skill
tools: []
model: claude-haiku-4-5
---

Body.
"""
    _write_skill(tmp_path, "minimal", minimal)
    registry = SkillRegistry(skills_dir=tmp_path)
    registry.load()
    skill = registry.get("minimal")
    assert skill.max_iterations == 5  # default
    assert skill.next_skills == []     # default
    assert skill.when_to_use == ""     # default
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_skill_registry.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.skill_registry'`.

- [ ] **Step 3: Implement `SkillRegistry`**

Create `apps/vault-server/src/services/skill_registry.py`:

```python
"""SkillRegistry — loads Mazkir sub-agent skill definitions from markdown files.

A "skill" is a markdown file with YAML frontmatter declaring:

    name: capture
    description: Short, one-line summary used by the router
    when_to_use: |
        Multi-line guidance for the router
    tools: [tool_a, tool_b]
    model: claude-haiku-4-5 | claude-sonnet-4-6 | ...
    max_iterations: 3
    next_skills: [manager, recall]   # allowed handoff targets

The body of the file becomes the skill's system prompt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import frontmatter

logger = logging.getLogger(__name__)

DEFAULT_MAX_ITERATIONS = 5


@dataclass
class Skill:
    name: str
    description: str
    system_prompt: str
    tools: list[str]
    model: str
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    next_skills: list[str] = field(default_factory=list)
    when_to_use: str = ""
    source_path: Optional[Path] = None


class SkillRegistry:
    """Loads and stores `Skill` definitions from a directory of markdown files."""

    def __init__(self, skills_dir: Path):
        self.skills_dir = Path(skills_dir)
        self._skills: dict[str, Skill] = {}

    def load(self) -> None:
        """Scan `skills_dir` for *.md files and parse them into Skill objects.

        Missing directory, empty directory, and malformed files are all
        non-fatal: a warning is logged and the file is skipped.
        """
        self._skills.clear()

        if not self.skills_dir.exists():
            logger.warning("Skills directory does not exist: %s", self.skills_dir)
            return

        for path in sorted(self.skills_dir.glob("*.md")):
            try:
                post = frontmatter.load(str(path))
            except Exception as e:
                logger.warning("Failed to parse skill %s: %s", path, e)
                continue

            meta = dict(post.metadata)
            required = ("name", "description", "tools", "model")
            if not all(k in meta for k in required):
                logger.warning(
                    "Skill %s missing required frontmatter fields (%s); skipping",
                    path, required,
                )
                continue

            skill = Skill(
                name=meta["name"],
                description=meta["description"],
                system_prompt=post.content.strip(),
                tools=list(meta["tools"]),
                model=meta["model"],
                max_iterations=int(meta.get("max_iterations", DEFAULT_MAX_ITERATIONS)),
                next_skills=list(meta.get("next_skills", [])),
                when_to_use=str(meta.get("when_to_use", "")).strip(),
                source_path=path,
            )
            self._skills[skill.name] = skill

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def list(self) -> list[Skill]:
        return list(self._skills.values())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_skill_registry.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/marcellmc/dev/mazkir
git add apps/vault-server/src/services/skill_registry.py apps/vault-server/tests/test_skill_registry.py
git commit -m "feat(vault-server): add SkillRegistry to load sub-agent skills from vault markdown"
```

---

## Task 5: `SkillRegistry` — tool-reference validation and cycle detection

Skills reference tools by name and may declare handoff targets. The registry should warn when references are stale so problems surface at startup, not at routing time.

**Files:**
- Modify: `apps/vault-server/src/services/skill_registry.py`
- Modify: `apps/vault-server/tests/test_skill_registry.py`

- [ ] **Step 1: Append failing tests**

```python
def test_validate_warns_on_unknown_tool(tmp_path, caplog):
    content = """---
name: bad
description: refs missing tool
tools: [nonexistent_tool]
model: claude-haiku-4-5
---
body
"""
    _write_skill(tmp_path, "bad", content)
    registry = SkillRegistry(skills_dir=tmp_path)
    registry.load()
    known_tools = {"save_knowledge", "create_task"}
    with caplog.at_level("WARNING"):
        warnings = registry.validate(known_tools=known_tools, known_skills={"bad"})
    assert any("nonexistent_tool" in w for w in warnings)


def test_validate_warns_on_unknown_next_skill(tmp_path):
    content = """---
name: bad
description: bad handoff target
tools: [save_knowledge]
model: claude-haiku-4-5
next_skills: [missing_skill]
---
body
"""
    _write_skill(tmp_path, "bad", content)
    registry = SkillRegistry(skills_dir=tmp_path)
    registry.load()
    warnings = registry.validate(known_tools={"save_knowledge"}, known_skills={"bad"})
    assert any("missing_skill" in w for w in warnings)


def test_validate_passes_when_references_resolve(tmp_path):
    content = """---
name: ok
description: ok
tools: [save_knowledge]
model: claude-haiku-4-5
next_skills: []
---
body
"""
    _write_skill(tmp_path, "ok", content)
    registry = SkillRegistry(skills_dir=tmp_path)
    registry.load()
    warnings = registry.validate(known_tools={"save_knowledge"}, known_skills={"ok"})
    assert warnings == []
```

- [ ] **Step 2: Run tests, see them fail**

```bash
python -m pytest tests/test_skill_registry.py -k validate -v
```

Expected: FAIL — `SkillRegistry` has no `validate` method yet.

- [ ] **Step 3: Add `validate` to `SkillRegistry`**

```python
def validate(
    self,
    known_tools: set[str],
    known_skills: set[str],
) -> list[str]:
    """Return a list of warning messages for unresolved tool / skill references.

    Warnings are logged at WARNING level and also returned so callers can
    surface them in startup logs / health checks.
    """
    warnings: list[str] = []
    for skill in self._skills.values():
        for t in skill.tools:
            if t not in known_tools:
                msg = f"Skill {skill.name!r} references unknown tool {t!r}"
                logger.warning(msg)
                warnings.append(msg)
        for n in skill.next_skills:
            if n not in known_skills:
                msg = f"Skill {skill.name!r} declares unknown next_skill {n!r}"
                logger.warning(msg)
                warnings.append(msg)
    return warnings
```

- [ ] **Step 4: Tests pass**

```bash
python -m pytest tests/test_skill_registry.py -v
```

Expected: 10 passed (7 + 3).

- [ ] **Step 5: Commit**

```bash
cd /home/marcellmc/dev/mazkir
git add apps/vault-server/src/services/skill_registry.py apps/vault-server/tests/test_skill_registry.py
git commit -m "feat(vault-server): SkillRegistry.validate warns on unresolved tool / next_skill refs"
```

---

## Task 6: Skill markdown — `capture`

**Files:**
- Create: `memory/00-system/mazkir-skills/capture.md`

- [ ] **Step 1: Ensure the parent directory exists**

```bash
mkdir -p /home/marcellmc/dev/mazkir/memory/00-system/mazkir-skills
```

- [ ] **Step 2: Write the skill file**

Create `memory/00-system/mazkir-skills/capture.md`:

```markdown
---
name: capture
description: Fast inbox-style captures — text, photos, new task/habit/goal items.
when_to_use: |
  - User dumps text, a quote, an observation, or a photo with no explicit instruction
  - "Save this", "remember this", "note that", "add task", "track this habit"
  - Single-utterance intent that maps to one quick write
tools:
  - save_knowledge
  - attach_to_daily
  - edit_daily_section
  - create_task
  - create_habit
  - create_goal
model: claude-haiku-4-5
max_iterations: 3
next_skills:
  - manager
  - recall
---

You are the **capture** sub-agent for Mazkir, the user's personal assistant. Your job is to file what the user just said quickly and quietly.

- Classify the content: is it a task to do, an idea / fact worth remembering, a note for the daily log, or a new habit / goal to track?
- Use one tool — the right one — and reply in one or two sentences confirming what you filed.
- When the captured item warrants follow-up planning (scheduling, prioritization, linking to existing items), emit `next_skill: manager` in your final response and the manager skill will pick up where you left off.
- When the user is asking a recall question disguised as a capture ("when did I last...?"), emit `next_skill: recall` instead.

Do not over-engineer. Do not ask for clarification unless the intent is genuinely ambiguous. Be terse. The user can always say more later.
```

- [ ] **Step 3: Commit (inside the nested vault repo)**

The `memory/` directory is its own git repo. Commit there:

```bash
cd /home/marcellmc/dev/mazkir/memory
git add 00-system/mazkir-skills/capture.md
git commit -m "feat(skills): add capture skill (fast inbox)"
cd /home/marcellmc/dev/mazkir
```

(If `memory/` is gitignored from the outer repo, nothing to commit in the parent. Otherwise commit `memory/` as well — it's a nested repo by convention but the outer repo may also track the skills directory.)

---

## Task 7: Skill markdown — `manager`

**Files:**
- Create: `memory/00-system/mazkir-skills/manager.md`

- [ ] **Step 1: Write the skill file**

```markdown
---
name: manager
description: Deliberate planning, edits, scheduling, completions, destructive operations.
when_to_use: |
  - Multi-step requests involving listing, comparing, or reorganizing items
  - "Complete X and Y", "move this to next week", "what's on my plate", "delete the old task"
  - Anything that needs read-then-write reasoning
  - Default fallback when the router is uncertain
tools:
  - list_tasks
  - list_habits
  - list_goals
  - list_events
  - get_daily
  - read_daily_section
  - update_task
  - update_habit
  - update_goal
  - complete_task
  - complete_habit
  - delete_task
  - archive_task
  - delete_habit
  - archive_goal
  - create_task
  - create_habit
  - create_goal
  - create_event
  - update_event
  - attach_photo_to_event
  - attach_to_daily
  - edit_daily_section
  - save_knowledge
  - search_knowledge
  - get_related
  - get_tokens
model: claude-sonnet-4-6
max_iterations: 10
next_skills:
  - recall
---

You are the **manager** sub-agent for Mazkir. You handle the user's planning and organization work: scheduling, editing, completing, and pruning tasks / habits / goals / events.

Operating principles:
- Read before writing. List the relevant items first so you can reference them by exact name when making changes.
- Be precise. When the user names a task, use fuzzy matching via the resolver-backed tools — but if `AMBIGUOUS_MATCH` comes back, surface the candidates to the user instead of guessing.
- Batch related changes in a single response block (parallel tool calls) when they're independent.
- Confidence matters. For write tools include `_confidence` ≥ 0.85 and a one-line `_reasoning`. For destructive tools include `_confidence` ≥ 0.95.
- On `ALREADY_DONE`, tell the user the action was a no-op and move on. Do not retry.
- On `STATE_CONFLICT`, re-read the target before retrying.
- On `CANCELLED_BY_USER`, do not re-issue the same action; ask what to do instead.

When the user's request shifts to retrospective recall ("when did I…?", "what notes do I have on…?"), emit `next_skill: recall`.
```

- [ ] **Step 2: Commit in the vault repo**

```bash
cd /home/marcellmc/dev/mazkir/memory
git add 00-system/mazkir-skills/manager.md
git commit -m "feat(skills): add manager skill (deliberate planning)"
cd /home/marcellmc/dev/mazkir
```

---

## Task 8: Skill markdown — `recall`

**Files:**
- Create: `memory/00-system/mazkir-skills/recall.md`

- [ ] **Step 1: Write the skill file**

```markdown
---
name: recall
description: Read-only search, retrieval, and summarization across the vault.
when_to_use: |
  - "What did I do on…?", "find my note about…", "show me everything tagged …"
  - "When was the last time…?", "remind me what I said about…"
  - Any read-only question where the user isn't asking to change state
tools:
  - search_knowledge
  - get_related
  - list_tasks
  - list_habits
  - list_goals
  - list_events
  - get_daily
  - read_daily_section
  - get_tokens
model: claude-haiku-4-5
max_iterations: 5
next_skills:
  - capture
  - manager
---

You are the **recall** sub-agent for Mazkir. You answer the user's questions about what is already in the vault — past notes, completed tasks, habit streaks, daily logs, events.

Operating principles:
- You have **no write tools**. Do not try to change state. If the user's question turns into a change request mid-response, emit `next_skill: manager`.
- Use `search_knowledge` for keyword search across notes and insights. Use `get_related` for graph traversal when the user asks "what's connected to X" or names a known topic.
- Use `list_*` and `get_daily` to surface structured data.
- Quote vault content verbatim when the user asks "what did I write"; summarize when they ask "what was about X".
- Be terse. If the answer is "I have nothing about that," say so.

When the user wants to add a fresh note alongside the recalled content, emit `next_skill: capture`.
```

- [ ] **Step 2: Commit in the vault repo**

```bash
cd /home/marcellmc/dev/mazkir/memory
git add 00-system/mazkir-skills/recall.md
git commit -m "feat(skills): add recall skill (read-only retrieval)"
cd /home/marcellmc/dev/mazkir
```

---

## Task 9: Config + lifespan — instantiate `SkillRegistry` at startup

**Files:**
- Modify: `apps/vault-server/src/config.py`
- Modify: `apps/vault-server/src/main.py`

- [ ] **Step 1: Add the env setting**

In `apps/vault-server/src/config.py`, near the other path settings (after `media_path`), add:

```python
skills_dir: Path = Path(os.getenv(
    "MAZKIR_SKILLS_DIR",
    str(Path.home() / "dev" / "mazkir" / "memory" / "00-system" / "mazkir-skills"),
))
```

- [ ] **Step 2: Load the registry in `main.py` lifespan**

In `apps/vault-server/src/main.py`, find the `lifespan` function. After other service instantiations, add:

```python
from src.services.skill_registry import SkillRegistry

skill_registry = SkillRegistry(skills_dir=settings.skills_dir)
skill_registry.load()
warnings = skill_registry.validate(
    known_tools=set(agent_service.tools.keys()),
    known_skills={s.name for s in skill_registry.list()},
)
for w in warnings:
    logger.warning("Skill validation: %s", w)
```

Pass `skill_registry` into `AgentService` constructor (we'll wire usage in T11). For now, store as an attribute.

In `AgentService.__init__`, accept an optional `skill_registry` parameter (default `None`) and store as `self.skill_registry`.

- [ ] **Step 3: Smoke-test startup**

```bash
cd /home/marcellmc/dev/mazkir/apps/vault-server
source venv/bin/activate
python -m uvicorn src.main:app --port 8001 &
sleep 3
curl -s http://localhost:8001/health
kill %1
wait %1 2>/dev/null
```

Expected: `/health` returns `{"status": "ok"}` (or your existing shape) and server logs show "Skill validation:" warnings only for the manager skill if it references `update_task` / `complete_task` etc. — which exist post-P1. Expect zero warnings.

- [ ] **Step 4: Commit**

```bash
cd /home/marcellmc/dev/mazkir
git add apps/vault-server/src/config.py apps/vault-server/src/main.py apps/vault-server/src/services/agent_service.py
git commit -m "feat(vault-server): load SkillRegistry in lifespan and inject into AgentService"
```

---

## Task 10: `RouterService` — LLM classifier picks the active skill

**Files:**
- Create: `apps/vault-server/src/services/router_service.py`
- Create: `apps/vault-server/tests/test_router_service.py`

- [ ] **Step 1: Write failing tests**

Create `apps/vault-server/tests/test_router_service.py`:

```python
"""Tests for RouterService — picks a skill given user message + skill list."""

from unittest.mock import MagicMock

import pytest

from src.services.router_service import RouterService, RouterDecision
from src.services.skill_registry import Skill


def _mk_skill(name: str, desc: str = "", when_to_use: str = "") -> Skill:
    return Skill(
        name=name,
        description=desc,
        system_prompt="",
        tools=[],
        model="claude-haiku-4-5",
        when_to_use=when_to_use,
    )


@pytest.fixture
def skills():
    return [
        _mk_skill("capture", "Fast inbox captures"),
        _mk_skill("manager", "Deliberate planning"),
        _mk_skill("recall", "Read-only retrieval"),
    ]


def test_router_returns_skill_picked_by_llm(skills):
    claude = MagicMock()
    claude.create_router_choice.return_value = {
        "skill": "manager",
        "reason": "user asked to complete multiple tasks",
    }
    router = RouterService(claude=claude, fallback_skill="manager")
    decision = router.pick("Complete all my P1 tasks", recent_messages=[], skills=skills)
    assert isinstance(decision, RouterDecision)
    assert decision.skill == "manager"
    assert "complete" in decision.reason.lower()


def test_router_falls_back_when_llm_returns_unknown_skill(skills):
    claude = MagicMock()
    claude.create_router_choice.return_value = {"skill": "nonsense", "reason": "x"}
    router = RouterService(claude=claude, fallback_skill="manager")
    decision = router.pick("foo", recent_messages=[], skills=skills)
    assert decision.skill == "manager"
    assert "fallback" in decision.reason.lower()


def test_router_falls_back_when_llm_errors(skills):
    claude = MagicMock()
    claude.create_router_choice.side_effect = RuntimeError("LLM down")
    router = RouterService(claude=claude, fallback_skill="manager")
    decision = router.pick("foo", recent_messages=[], skills=skills)
    assert decision.skill == "manager"
    assert "fallback" in decision.reason.lower()


def test_router_passes_skill_descriptions_to_llm(skills):
    claude = MagicMock()
    claude.create_router_choice.return_value = {"skill": "capture", "reason": "ok"}
    router = RouterService(claude=claude, fallback_skill="manager")
    router.pick("save this", recent_messages=[], skills=skills)

    args, kwargs = claude.create_router_choice.call_args
    payload = kwargs.get("skill_catalog") or (args[1] if len(args) > 1 else None)
    assert payload is not None
    names = [s["name"] for s in payload]
    assert "capture" in names
    assert "manager" in names
    assert "recall" in names
```

- [ ] **Step 2: Run tests**

```bash
python -m pytest tests/test_router_service.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `RouterService`**

Create `apps/vault-server/src/services/router_service.py`:

```python
"""RouterService — classifies a user message and picks one Skill to handle it.

The router is a small Haiku LLM call. It receives the user message + recent
conversation tail + the skill catalog (name, description, when_to_use), and
returns a single skill name. On any error or unknown response, falls back to
the configured fallback skill (typically "manager", the broadest toolbox).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.services.skill_registry import Skill

logger = logging.getLogger(__name__)


@dataclass
class RouterDecision:
    skill: str
    reason: str


class RouterService:
    def __init__(self, claude, fallback_skill: str = "manager"):
        self.claude = claude
        self.fallback_skill = fallback_skill

    def pick(
        self,
        user_msg: str,
        recent_messages: list[dict],
        skills: list[Skill],
    ) -> RouterDecision:
        catalog = [
            {
                "name": s.name,
                "description": s.description,
                "when_to_use": s.when_to_use,
            }
            for s in skills
        ]
        known = {s.name for s in skills}

        try:
            choice = self.claude.create_router_choice(
                user_msg=user_msg,
                recent_messages=recent_messages,
                skill_catalog=catalog,
            )
        except Exception as e:
            logger.warning("Router LLM call failed: %s — falling back to %s", e, self.fallback_skill)
            return RouterDecision(
                skill=self.fallback_skill,
                reason=f"fallback: router error ({e})",
            )

        picked = choice.get("skill")
        reason = choice.get("reason", "")

        if picked not in known:
            logger.warning(
                "Router picked unknown skill %r — falling back to %s",
                picked, self.fallback_skill,
            )
            return RouterDecision(
                skill=self.fallback_skill,
                reason=f"fallback: router picked unknown skill {picked!r}",
            )

        return RouterDecision(skill=picked, reason=reason)
```

- [ ] **Step 4: Add `create_router_choice` stub to `ClaudeService`**

In `apps/vault-server/src/services/claude_service.py`, add a new method that wraps a Haiku call:

```python
def create_router_choice(
    self,
    user_msg: str,
    recent_messages: list[dict],
    skill_catalog: list[dict],
) -> dict:
    """Call Haiku with a structured prompt asking for a single skill name.

    Returns {"skill": <name>, "reason": <short string>}.
    """
    catalog_lines = "\n".join(
        f"- {s['name']}: {s['description']}\n  use when: {s['when_to_use']}"
        for s in skill_catalog
    )
    system = (
        "You are a router for the Mazkir personal assistant. "
        "Pick exactly one skill to handle the user's message.\n\n"
        f"Available skills:\n{catalog_lines}\n\n"
        "Respond as a JSON object: {\"skill\": \"<name>\", \"reason\": \"<one short sentence>\"}. "
        "Pick the single best match. When uncertain, pick 'manager'."
    )
    msgs = list(recent_messages) + [{"role": "user", "content": user_msg}]
    response = self._client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=128,
        system=system,
        messages=msgs,
    )
    text = response.content[0].text.strip()
    # Tolerant JSON parse: strip code fences if present
    if text.startswith("```"):
        text = text.strip("`").lstrip("json").strip()
    import json
    return json.loads(text)
```

(Adapt `self._client` reference to the existing `ClaudeService` attribute that holds the Anthropic client.)

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_router_service.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
cd /home/marcellmc/dev/mazkir
git add apps/vault-server/src/services/router_service.py apps/vault-server/src/services/claude_service.py apps/vault-server/tests/test_router_service.py
git commit -m "feat(vault-server): add RouterService that picks a skill via Haiku LLM call"
```

---

## Task 11: Skill-aware agent loop in `AgentService.handle_message`

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py`
- Create: `apps/vault-server/tests/test_skill_loop.py`

- [ ] **Step 1: Write failing tests**

Create `apps/vault-server/tests/test_skill_loop.py`:

```python
"""Tests for the skill-aware agent loop in AgentService."""

from unittest.mock import MagicMock

import pytest

from src.services.skill_registry import Skill


def _mk_skill(name: str, tools: list[str], next_skills: list[str] | None = None) -> Skill:
    return Skill(
        name=name,
        description=f"{name} skill",
        system_prompt=f"You are the {name} skill.",
        tools=tools,
        model="claude-haiku-4-5",
        max_iterations=3,
        next_skills=next_skills or [],
    )


def test_router_picks_skill_and_loop_uses_its_tools(mock_services, monkeypatch):
    from src.services.agent_service import AgentService
    claude, vault, memory, calendar, events = mock_services

    skill_registry = MagicMock()
    skill_registry.list.return_value = [_mk_skill("manager", ["list_tasks"])]
    skill_registry.get.side_effect = lambda n: _mk_skill("manager", ["list_tasks"]) if n == "manager" else None

    router = MagicMock()
    router.pick.return_value = MagicMock(skill="manager", reason="planning intent")

    agent = AgentService(
        claude=claude, vault=vault, memory=memory, calendar=calendar, events=events,
        skill_registry=skill_registry, router=router,
    )

    # Patch the inner loop to capture the active tool schemas
    captured = {}
    def fake_run_loop(chat_id, log_text, messages, system, tool_schemas, max_iterations):
        captured["tool_schemas"] = tool_schemas
        captured["system"] = system
        captured["max_iterations"] = max_iterations
        return "ok", "end_turn"
    monkeypatch.setattr(agent, "_run_loop", fake_run_loop)

    agent.handle_message(chat_id=1, text="What's on my plate")

    schema_names = [s["name"] for s in captured["tool_schemas"]]
    assert schema_names == ["list_tasks"]
    assert "You are the manager skill" in captured["system"]
    assert captured["max_iterations"] == 3


def test_next_skill_handoff_runs_second_skill(mock_services, monkeypatch):
    from src.services.agent_service import AgentService
    claude, vault, memory, calendar, events = mock_services

    capture_skill = _mk_skill("capture", ["save_knowledge"], next_skills=["manager"])
    manager_skill = _mk_skill("manager", ["list_tasks"])

    skill_registry = MagicMock()
    skill_registry.list.return_value = [capture_skill, manager_skill]
    skill_registry.get.side_effect = lambda n: {"capture": capture_skill, "manager": manager_skill}.get(n)

    router = MagicMock()
    router.pick.return_value = MagicMock(skill="capture", reason="")

    agent = AgentService(
        claude=claude, vault=vault, memory=memory, calendar=calendar, events=events,
        skill_registry=skill_registry, router=router,
    )

    call_log = []
    def fake_run_loop(chat_id, log_text, messages, system, tool_schemas, max_iterations):
        skill_name = "capture" if "capture skill" in system else "manager"
        call_log.append(skill_name)
        if skill_name == "capture":
            return "saved. next_skill: manager", "end_turn"
        return "done", "end_turn"

    monkeypatch.setattr(agent, "_run_loop", fake_run_loop)
    agent.handle_message(chat_id=1, text="Save this and then schedule it")

    assert call_log == ["capture", "manager"]


def test_loop_caps_at_three_hops(mock_services, monkeypatch):
    from src.services.agent_service import AgentService
    claude, vault, memory, calendar, events = mock_services

    a = _mk_skill("a", [], next_skills=["b"])
    b = _mk_skill("b", [], next_skills=["c"])
    c = _mk_skill("c", [], next_skills=["a"])

    skill_registry = MagicMock()
    skill_registry.list.return_value = [a, b, c]
    skill_registry.get.side_effect = lambda n: {"a": a, "b": b, "c": c}.get(n)

    router = MagicMock()
    router.pick.return_value = MagicMock(skill="a", reason="")

    agent = AgentService(
        claude=claude, vault=vault, memory=memory, calendar=calendar, events=events,
        skill_registry=skill_registry, router=router,
    )

    call_log = []
    def fake_run_loop(chat_id, log_text, messages, system, tool_schemas, max_iterations):
        name = next(s for s in ("a", "b", "c") if f"{s} skill" in system)
        call_log.append(name)
        # Every skill tries to hand off, would loop forever without the cap
        nxt = {"a": "b", "b": "c", "c": "a"}[name]
        return f"hop next_skill: {nxt}", "end_turn"

    monkeypatch.setattr(agent, "_run_loop", fake_run_loop)
    agent.handle_message(chat_id=1, text="go")

    assert len(call_log) <= 3


def test_no_skill_registry_uses_legacy_loop(mock_services, monkeypatch):
    """When skill_registry is None, AgentService falls back to the legacy
    single-loop behavior with all tools loaded."""
    from src.services.agent_service import AgentService
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(
        claude=claude, vault=vault, memory=memory, calendar=calendar, events=events,
        skill_registry=None, router=None,
    )

    captured = {}
    def fake_run_loop(chat_id, log_text, messages, system, tool_schemas=None, max_iterations=None):
        captured["tool_count"] = len(tool_schemas) if tool_schemas is not None else len(agent._tool_schemas())
        return "ok", "end_turn"

    monkeypatch.setattr(agent, "_run_loop", fake_run_loop)
    agent.handle_message(chat_id=1, text="hi")
    assert captured["tool_count"] >= 25  # all tools available in legacy mode
```

- [ ] **Step 2: Run tests, see them fail**

```bash
python -m pytest tests/test_skill_loop.py -v
```

Expected: FAIL — `AgentService` doesn't yet accept `skill_registry`/`router` or implement the skill loop.

- [ ] **Step 3: Refactor `AgentService` to support a skill-aware loop**

In `AgentService.__init__`, accept optional `skill_registry` and `router` parameters (default `None`). Store as attributes.

Extract the existing inner loop body (the `while iter_num < max_iter` block that calls `claude.create` and processes tool calls) into a helper method `_run_loop(chat_id, log_text, messages, system, tool_schemas, max_iterations) -> (response_text, stop_reason)`. The helper should accept tool schemas + max_iterations as parameters rather than reading from `self.max_iterations` / `self._tool_schemas()`.

In `handle_message`:

```python
def handle_message(self, chat_id: int, text: str, attachments=None, ...) -> AgentResponse:
    context = self.memory.assemble_context(chat_id)
    messages = list(context.messages)
    user_msg = self._build_user_message(text, attachments=attachments, ...)
    messages.append(user_msg)

    if self.skill_registry is None or self.router is None:
        return self._handle_legacy(chat_id, text, context, messages)

    return self._handle_via_skills(chat_id, text, context, messages)

def _handle_via_skills(self, chat_id, text, context, messages) -> AgentResponse:
    skills = self.skill_registry.list()
    decision = self.router.pick(
        user_msg=text,
        recent_messages=context.messages[-10:],
        skills=skills,
    )

    MAX_HOPS = 3
    visited: list[str] = []
    response_text = ""
    active = decision.skill
    previous = None
    reason = decision.reason

    while active and len(visited) < MAX_HOPS:
        if active in visited:
            logger.warning("Skill cycle detected — stopping at %s", active)
            break
        visited.append(active)

        skill = self.skill_registry.get(active)
        if skill is None:
            logger.warning("Router/handoff requested unknown skill %r", active)
            break

        tool_schemas = self._skill_tool_schemas(skill)
        system = self._build_system_prompt_for_skill(skill, context)

        with _tracer.start_as_current_span(
            f"skill.{skill.name}",
            attributes={
                "skill.name": skill.name,
                "skill.previous": previous or "",
                "skill.routing_reason": reason,
            },
        ):
            response_text, stop_reason = self._run_loop(
                chat_id=chat_id,
                log_text=text,
                messages=messages,
                system=system,
                tool_schemas=tool_schemas,
                max_iterations=skill.max_iterations,
            )

        next_skill = self._extract_next_skill(response_text, skill.next_skills)
        if next_skill:
            previous = active
            active = next_skill
            reason = f"handoff from {previous}"
        else:
            active = None

    self.memory.save_turn(chat_id, text, response_text)
    return AgentResponse(response=response_text, iterations=len(visited))

def _skill_tool_schemas(self, skill: Skill) -> list[dict]:
    return [
        self.tools[t]["schema"]
        for t in skill.tools
        if t in self.tools
    ]

def _build_system_prompt_for_skill(self, skill: Skill, context) -> str:
    base_prompt = self._build_system_prompt(context)
    return f"{skill.system_prompt}\n\n{base_prompt}"

def _extract_next_skill(self, response_text: str, allowed: list[str]) -> str | None:
    import re
    m = re.search(r"next_skill:\s*([a-z_-]+)", response_text)
    if not m:
        return None
    name = m.group(1)
    if name not in allowed:
        logger.warning("Skill emitted next_skill=%r not in allowed=%r", name, allowed)
        return None
    return name
```

The legacy fallback (`_handle_legacy`) wraps the previous flow when `skill_registry` is `None`. Pull this out as a method that runs `_run_loop` once with all tools and the existing system prompt.

- [ ] **Step 4: Update `_run_loop`**

Pull the existing `for iter_num in range(self.max_iterations)` body out as `_run_loop`. The signature mentioned in the tests is:

```python
def _run_loop(self, chat_id, log_text, messages, system, tool_schemas, max_iterations) -> tuple[str, str]:
    # ... existing loop body, parameterized
    return response_text, stop_reason
```

Adapt the body to use the parameters instead of `self.max_iterations` / `self._tool_schemas()`.

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_skill_loop.py -v
python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: 4 new tests pass; full suite green (legacy tests continue to use the no-skill path).

- [ ] **Step 6: Commit**

```bash
cd /home/marcellmc/dev/mazkir
git add apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_skill_loop.py
git commit -m "feat(vault-server): skill-aware agent loop with router, next_skill handoff, 3-hop cap"
```

---

## Task 12: Wire `RouterService` and `SkillRegistry` into the lifespan

**Files:**
- Modify: `apps/vault-server/src/main.py`

- [ ] **Step 1: Construct `RouterService` and pass into `AgentService`**

In `main.py` lifespan, after the existing `SkillRegistry` instantiation (from T9):

```python
from src.services.router_service import RouterService

router_service = RouterService(claude=claude_service, fallback_skill="manager")
agent_service = AgentService(
    claude=claude_service,
    vault=vault_service,
    memory=memory_service,
    calendar=calendar_service,
    events=events_service,
    skill_registry=skill_registry,
    router=router_service,
)
```

The existing `AgentService(...)` instantiation should be replaced — not duplicated. Read the existing lifespan first to integrate cleanly.

- [ ] **Step 2: Smoke-test**

```bash
cd /home/marcellmc/dev/mazkir/apps/vault-server
source venv/bin/activate
python -m uvicorn src.main:app --port 8001 &
sleep 3
curl -s http://localhost:8001/health
# Optional: hit /message with a simple text and observe Phoenix trace for skill.* attrs
kill %1
wait %1 2>/dev/null
```

Expected: server starts, `/health` ok, log shows skill validation warnings (if any).

- [ ] **Step 3: Commit**

```bash
cd /home/marcellmc/dev/mazkir
git add apps/vault-server/src/main.py
git commit -m "feat(vault-server): wire RouterService into lifespan, AgentService gets router + skills"
```

---

## Task 13: Per-tool confidence thresholds with risk-class defaults

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py`
- Create: `apps/vault-server/tests/test_per_tool_thresholds.py`

- [ ] **Step 1: Write failing tests**

Create `apps/vault-server/tests/test_per_tool_thresholds.py`:

```python
"""Tests for per-tool confidence thresholds with risk-class defaults."""

import pytest
from unittest.mock import MagicMock

from src.services.agent_service import AgentService, _confidence_threshold_for


def test_default_thresholds_by_risk():
    assert _confidence_threshold_for(risk="safe") is None
    assert _confidence_threshold_for(risk="write") == 0.85
    assert _confidence_threshold_for(risk="destructive") == 0.95


def test_tool_can_override_threshold(mock_services):
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)
    # update_task is "write" with default threshold 0.85
    assert agent.tools["update_task"]["confidence_threshold"] == 0.85
    # delete_task is "destructive" with default threshold 0.95
    assert agent.tools["delete_task"]["confidence_threshold"] == 0.95


def test_gate_uses_per_tool_threshold(mock_services):
    """A 0.90 confidence destructive call fails the 0.95 gate."""
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)

    score, action = agent._check_confidence(
        name="delete_task",
        params={"task_name": "x", "_confidence": 0.90, "_reasoning": "test"},
    )
    assert action == "needs_confirmation"


def test_gate_passes_write_at_0_85(mock_services):
    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=calendar, events=events)

    score, action = agent._check_confidence(
        name="update_task",
        params={"name": "x", "_confidence": 0.86, "_reasoning": "test"},
    )
    assert action == "auto_execute"
```

- [ ] **Step 2: Run tests to see them fail**

```bash
python -m pytest tests/test_per_tool_thresholds.py -v
```

Expected: FAIL — `_confidence_threshold_for` does not exist; tool registry entries lack `confidence_threshold`.

- [ ] **Step 3: Add `_confidence_threshold_for` and stamp tool registry entries**

In `agent_service.py`:

```python
_RISK_DEFAULT_THRESHOLDS = {
    "safe": None,
    "write": 0.85,
    "destructive": 0.95,
}


def _confidence_threshold_for(risk: str) -> float | None:
    return _RISK_DEFAULT_THRESHOLDS.get(risk)
```

At the end of `_register_tools`, after building the dict, iterate and stamp default thresholds:

```python
for name, entry in tools.items():
    if "confidence_threshold" not in entry:
        entry["confidence_threshold"] = _confidence_threshold_for(entry["risk"])
return tools
```

- [ ] **Step 4: Update `_check_confidence` to use the per-tool threshold**

Find the existing confidence-gate logic (`CONFIDENCE_THRESHOLD = 0.85` constant + checker). Replace the global comparison with the per-tool one:

```python
def _check_confidence(self, name: str, params: dict) -> tuple[float, str]:
    """Return (score, action) where action is 'auto_execute' or 'needs_confirmation'."""
    threshold = self.tools[name].get("confidence_threshold")
    if threshold is None:
        return (1.0, "auto_execute")  # safe risk — no gate

    score = float(params.get("_confidence", 0.0))
    if score >= threshold:
        return (score, "auto_execute")
    return (score, "needs_confirmation")
```

Update existing callers if they used the old return shape.

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_per_tool_thresholds.py -v
python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: 4 new pass, full suite green. Existing confidence-gate tests may need their assertions updated to pass through `_check_confidence` instead of the old constant.

- [ ] **Step 6: Commit**

```bash
cd /home/marcellmc/dev/mazkir
git add apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_per_tool_thresholds.py
git commit -m "feat(vault-server): per-tool confidence thresholds with risk-class defaults"
```

---

## Task 14: Preview-before-execute for destructive tools

**Files:**
- Create: `apps/vault-server/src/services/preview.py`
- Create: `apps/vault-server/tests/test_preview.py`
- Modify: `apps/vault-server/src/services/agent_service.py`

- [ ] **Step 1: Write failing tests**

Create `apps/vault-server/tests/test_preview.py`:

```python
"""Tests for destructive-action preview rendering."""

import pytest
from unittest.mock import MagicMock

from src.services.preview import (
    PREVIEW_FUNCTIONS,
    register_preview_fn,
    render_preview,
)


@pytest.fixture(autouse=True)
def clean_registry():
    saved = PREVIEW_FUNCTIONS.copy()
    PREVIEW_FUNCTIONS.clear()
    yield
    PREVIEW_FUNCTIONS.clear()
    PREVIEW_FUNCTIONS.update(saved)


def test_register_and_render():
    register_preview_fn("delete_task", lambda params, ctx: f"Would delete: {params['task_name']}")
    out = render_preview("delete_task", {"task_name": "Walk dog"}, ctx={})
    assert out == "Would delete: Walk dog"


def test_render_returns_default_when_no_preview_fn_registered():
    out = render_preview("delete_task", {"task_name": "X"}, ctx={})
    assert "delete_task" in out
    assert "X" in out  # generic fallback includes tool name + params
```

- [ ] **Step 2: Run to see them fail**

```bash
python -m pytest tests/test_preview.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the preview registry**

Create `apps/vault-server/src/services/preview.py`:

```python
"""Preview-text registry for destructive tool calls.

Each destructive tool may register a `preview_fn(params, ctx) -> str` that
produces a human-readable description of what would change. The confirmation
flow renders this text alongside yes/no buttons before executing.

Tools without a registered preview_fn get a generic fallback ("Would call
<tool> with <params>").
"""

from __future__ import annotations

import json
from typing import Any, Callable

PreviewFn = Callable[[dict, Any], str]

PREVIEW_FUNCTIONS: dict[str, PreviewFn] = {}


def register_preview_fn(tool_name: str, fn: PreviewFn) -> None:
    PREVIEW_FUNCTIONS[tool_name] = fn


def render_preview(tool_name: str, params: dict, ctx: Any) -> str:
    fn = PREVIEW_FUNCTIONS.get(tool_name)
    if fn is None:
        return f"Would call `{tool_name}` with params: {json.dumps(params, indent=2)}"
    return fn(params, ctx)
```

- [ ] **Step 4: Register previews for destructive tools**

At the bottom of `AgentService.__init__`, after `register_hook(...)`:

```python
from src.services.preview import register_preview_fn

def _preview_delete_task(params, ctx):
    return f"Would delete task: **{params.get('task_name', '?')}**"

def _preview_archive_task(params, ctx):
    return f"Would archive task: **{params.get('task_name', '?')}**"

def _preview_delete_habit(params, ctx):
    return f"Would delete habit: **{params.get('habit_name', '?')}**"

def _preview_archive_goal(params, ctx):
    return f"Would archive goal: **{params.get('goal_name', '?')}**"

def _preview_complete_task(params, ctx):
    return f"Would mark task **{params.get('task_name', '?')}** as done"

def _preview_complete_habit(params, ctx):
    return f"Would log completion of habit **{params.get('habit_name', '?')}**"

register_preview_fn("delete_task", _preview_delete_task)
register_preview_fn("archive_task", _preview_archive_task)
register_preview_fn("delete_habit", _preview_delete_habit)
register_preview_fn("archive_goal", _preview_archive_goal)
register_preview_fn("complete_task", _preview_complete_task)
register_preview_fn("complete_habit", _preview_complete_habit)
```

Add `"preview": True` to every destructive tool entry in `_register_tools` (no extra logic — flagging only; the execution path checks the flag).

- [ ] **Step 5: Wire preview into the confirmation flow**

The existing `_execute_tool` builds a `pending_action` for low-confidence tool calls. Extend the logic: if the tool has `preview=True`, **always** stage a pending action with the rendered preview, regardless of confidence. Re-use the existing confirmation infrastructure (the `/message/confirm` endpoint, chat-state pending actions).

In `agent_service.py`, find where the gate decides to auto-execute. Add:

```python
if tool.get("preview") and action == "auto_execute":
    preview_text = render_preview(name, params, ctx={"vault": self.vault, "tool": tool})
    action = "needs_confirmation"
    # Stash preview text in the pending action so the bot can render it
    pending_meta = {"preview": preview_text}
else:
    pending_meta = {}
```

(The existing confirmation handler should accept and propagate `pending_meta` to the chat-state record. Adapt the data model as needed.)

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/test_preview.py -v
python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: 2 new pass. Existing destructive-tool tests may need to set `_confidence: 0.96` to bypass the preview gate (since destructive now always previews even at high confidence — by design). Update those tests' input params or assert the `needs_confirmation` outcome instead.

- [ ] **Step 7: Commit**

```bash
cd /home/marcellmc/dev/mazkir
git add apps/vault-server/src/services/preview.py apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_preview.py
git commit -m "feat(vault-server): destructive tools require preview-before-execute confirmation"
```

---

## Task 15: Post-hooks framework activation in `_execute_tool_inner`

The hook framework already supports `run_post_hooks` (P1 T3). Wire it into the execution path so future post-hooks (e.g., `sync_to_calendar` in P5) work without further plumbing.

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py`
- Modify: `apps/vault-server/tests/test_hooks.py`

- [ ] **Step 1: Add failing test**

Append to `apps/vault-server/tests/test_hooks.py`:

```python
def test_execute_tool_runs_post_hooks_after_handler():
    """Post-hooks run after a successful handler, receiving (params, output, ctx)."""
    from src.services.agent_service import AgentService
    from src.services.hooks import register_hook, HOOK_REGISTRY
    from unittest.mock import MagicMock

    HOOK_REGISTRY.clear()
    calls = []
    register_hook("audit", lambda p, o, c: calls.append(("audit", p, o)))

    claude, vault, memory = MagicMock(), MagicMock(), MagicMock()
    agent = AgentService(claude=claude, vault=vault, memory=memory, calendar=None, events=None)
    # Wire post-hook on an arbitrary tool for the test
    agent.tools["list_tasks"]["post_hooks"] = ["audit"]
    agent.tools["list_tasks"]["handler"] = lambda p: {"ok": True, "data": {"tasks": []}, "_items": []}
    agent.tools["list_tasks"]["pre_hooks"] = []

    result = agent._execute_tool_inner("list_tasks", {}, risk="safe")
    assert result["ok"] is True
    assert len(calls) == 1
    assert calls[0][0] == "audit"
    assert calls[0][2]["data"]["tasks"] == []
```

- [ ] **Step 2: Run to see it fail**

```bash
python -m pytest tests/test_hooks.py -k post_hooks_after_handler -v
```

Expected: FAIL — post-hooks aren't invoked yet.

- [ ] **Step 3: Wire post-hooks**

In `_execute_tool_inner`, after the handler call and response normalization:

```python
from src.services.hooks import run_post_hooks
post_hooks = tool.get("post_hooks", [])
if post_hooks:
    run_post_hooks(post_hooks, params, response, ctx)
return response
```

Add `"post_hooks": []` to every tool registry entry so the field is always present (mirrors how `pre_hooks` was rolled out in P1 T8). Mechanical edit.

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_hooks.py -v
python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
cd /home/marcellmc/dev/mazkir
git add apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_hooks.py
git commit -m "feat(vault-server): wire post_hooks into _execute_tool_inner (framework activation)"
```

---

## Task 16: Span attributes — skill, preview, confidence

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py`

- [ ] **Step 1: Add attributes incrementally**

Find these spans and add attributes per the design doc Block C/D:

- `skill.<name>` span (created in T11): add `skill.name`, `skill.previous`, `skill.routing_reason`, `skill.next_skill` (set when handoff emitted).
- `agent.tool_call` span: add `confirmation.required` (bool), `tool.confidence_threshold` (float|None), `tool.confidence_score` (float).
- When a preview is rendered: add `preview.tool` (str), `preview.text_length` (int).

No new tests required (these are observability attributes). Verify by manually inspecting a Phoenix trace via `px trace list --last-n-minutes 5 --format raw --no-progress | jq` after running through one `/message`.

- [ ] **Step 2: Run full suite to ensure no regressions**

```bash
cd apps/vault-server
source venv/bin/activate
python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: green.

- [ ] **Step 3: Commit**

```bash
cd /home/marcellmc/dev/mazkir
git add apps/vault-server/src/services/agent_service.py
git commit -m "feat(vault-server): tag skill, confidence, and preview span attributes for Phoenix"
```

---

## Task 17: Smoke-test the skill loop end-to-end

**Files:** (no new files, manual verification)

- [ ] **Step 1: Start vault-server**

```bash
cd /home/marcellmc/dev/mazkir/apps/vault-server
source venv/bin/activate
python -m uvicorn src.main:app --port 8001 --log-level info &
sleep 3
```

- [ ] **Step 2: Send three test messages**

```bash
# Capture intent
curl -s -X POST http://localhost:8001/message \
  -H "Content-Type: application/json" \
  -d '{"text": "Save this note: prompt caching cuts costs by ~10x on cache hits", "chat_id": 1}'

# Manager intent
curl -s -X POST http://localhost:8001/message \
  -H "Content-Type: application/json" \
  -d '{"text": "Show me my active tasks", "chat_id": 1}'

# Recall intent
curl -s -X POST http://localhost:8001/message \
  -H "Content-Type: application/json" \
  -d '{"text": "What notes do I have about prompt caching", "chat_id": 1}'

kill %1
wait %1 2>/dev/null
```

- [ ] **Step 3: Inspect Phoenix traces**

```bash
px trace list --last-n-minutes 5 --format raw --no-progress | \
  jq '.[] | select(.rootSpan.name | test("skill\\.|agent\\.handle_message")) | {trace_id: .traceId, span: .rootSpan.name, attrs: .rootSpan.attributes}'
```

Expected: each turn shows the skill-routed span with `skill.name`, `skill.routing_reason`. The recall and capture turns may also show `skill.next_skill` if any handoff fired.

Document any unexpected behavior in the commit body for T18 (final sweep).

- [ ] **Step 4: No commit unless you tweak something**

If you find a bug, fix it in a separate commit and rerun the smoke test.

---

## Task 18: Final sweep — full test run + CLAUDE.md refresh

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Full vault-server suite**

```bash
cd /home/marcellmc/dev/mazkir/apps/vault-server
source venv/bin/activate
python -m pytest tests/ -v 2>&1 | tail -15
```

Expected: all green. Total around 300+ tests.

- [ ] **Step 2: Full repo suite**

```bash
cd /home/marcellmc/dev/mazkir
npx turbo test 2>&1 | tail -10
```

Expected: telegram-bot and webapp pass; vault-server passes via the local pytest run above.

- [ ] **Step 3: Update CLAUDE.md**

In `CLAUDE.md`:

- Architecture section — add a new bullet describing the skill loop:
  > **Skill loop:** `AgentService.handle_message` dispatches via `RouterService` (Haiku LLM classifier) to one of three skills loaded from `memory/00-system/mazkir-skills/` (`capture`, `manager`, `recall`). Skills chain via a `next_skill` token in their reply; loop caps at 3 hops. Each skill has its own model, tool subset, and system prompt.
- Update the agent confidence section: "Per-tool thresholds (write 0.85, destructive 0.95). Destructive tools always render a preview before execution and require yes/no confirmation."
- Add to "Related Documentation" pointer line: `memory/00-system/mazkir-skills/*.md` — Mazkir sub-agent definitions.

- [ ] **Step 4: Commit**

```bash
cd /home/marcellmc/dev/mazkir
git add CLAUDE.md
git commit -m "docs(claude-md): document skill architecture and per-tool gate model after P2"
```

---

## Self-review notes

Spec coverage:

| Spec item (from D3 / D4 / P1 rollovers) | Task(s) |
| --- | --- |
| P1 rollover: expose schedule fields on create_* tool schemas | 1 |
| P1 rollover: reconcile status enum with real vault data | 2 |
| P1 rollover: complete_habit uses resolver | 3 |
| SkillRegistry (markdown loader) | 4 |
| SkillRegistry validation (tools / next_skills) | 5 |
| Skill markdown files (capture / manager / recall) | 6, 7, 8 |
| SkillRegistry instantiated at startup | 9 |
| RouterService (Haiku LLM classifier) | 10 |
| Skill-aware agent loop with next_skill handoff | 11 |
| 3-hop cap + cycle protection | 11 |
| Fallback to manager when router uncertain | 10 (`fallback_skill`) |
| RouterService wired into lifespan | 12 |
| Per-tool confidence thresholds | 13 |
| Risk-class default thresholds (write 0.85, destructive 0.95) | 13 |
| Preview-before-execute for destructive | 14 |
| Hook framework: post_hooks wired | 15 |
| Phoenix span attributes (skill.*, confidence.*, preview.*) | 16 |
| End-to-end smoke test of skill loop | 17 |
| CLAUDE.md update | 18 |

**Out of scope** (verified): daily-tier tools (P4), media migration (P4), calendar sync as post-hook (P5), streaming (P5), parallel tool execution (P5), state-drift protection on confirmed actions (deferred until first incident, per design doc D4).

**Open questions to resolve during implementation:**
- The router's `create_router_choice` method on `ClaudeService` makes a raw Haiku call. If `ClaudeService` already wraps responses in a structured format (e.g., tool use), adapt — don't duplicate.
- `_run_loop` extraction needs to preserve the existing confirmation-flow path (where a tool call pauses for `/message/confirm`). The skill loop should treat a "needs confirmation" exit the same as `end_turn` for the purposes of the hop counter — control returns to the bot, and the next `/message/confirm` call should resume the same skill, not re-route.
- The vault repo (`memory/`) is a nested git repo; commits to skill files happen there. The outer repo's `.gitignore` should already exclude `memory/`. Skill files do not get committed to the outer Mazkir repo.
- After T13, the existing global `CONFIDENCE_THRESHOLD` constant can be removed if no callers remain. Verify and clean up.
