# Vault Editing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Give the agent full vault editing capabilities — read/edit daily note sections, delete/archive tasks and habits, archive goals.

**Architecture:** VaultService gets new methods for section read/replace, file deletion, task archiving, and fuzzy find for habits/goals. AgentService gets 6 new tools (1 safe, 1 write, 4 destructive).

**Tech Stack:** Python (FastAPI, frontmatter, pytest)

---

### Task 1: VaultService — read and replace daily sections

**Files:**
- Modify: `apps/vault-server/src/services/vault_service.py`
- Test: `apps/vault-server/tests/test_vault_service.py`

**Step 1: Write the failing tests**

Add to `tests/test_vault_service.py`:

```python
class TestDailySections:
    def test_read_daily_section_returns_content(self, vault_service, vault_path):
        vault_service.create_daily_note()
        vault_service.append_to_daily_section("Notes", "Hello world")
        result = vault_service.read_daily_section("Notes")
        assert "Hello world" in result

    def test_read_daily_section_empty(self, vault_service, vault_path):
        vault_service.create_daily_note()
        result = vault_service.read_daily_section("Notes")
        assert result.strip() == ""

    def test_read_daily_section_missing(self, vault_service, vault_path):
        vault_service.create_daily_note()
        result = vault_service.read_daily_section("Nonexistent")
        assert result == ""

    def test_read_daily_section_no_daily_note(self, vault_service):
        result = vault_service.read_daily_section("Notes")
        assert result == ""

    def test_replace_daily_section(self, vault_service, vault_path):
        vault_service.create_daily_note()
        vault_service.append_to_daily_section("Notes", "Old content")
        vault_service.replace_daily_section("Notes", "New content")
        result = vault_service.read_daily_section("Notes")
        assert "New content" in result
        assert "Old content" not in result

    def test_replace_daily_section_preserves_other_sections(self, vault_service, vault_path):
        vault_service.create_daily_note()
        vault_service.replace_daily_section("Notes", "New notes content")
        daily = vault_service.read_daily_note()
        assert "## Daily Habits" in daily["content"]
        assert "## Tasks" in daily["content"]
        assert "New notes content" in daily["content"]
```

**Step 2: Run tests to verify they fail**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_vault_service.py::TestDailySections -v`
Expected: FAIL — `read_daily_section` and `replace_daily_section` not defined

**Step 3: Implement VaultService methods**

Add to `apps/vault-server/src/services/vault_service.py` after `get_daily_notes_section`:

```python
def read_daily_section(self, section: str, date: Optional[datetime] = None) -> str:
    """Read content of a daily note section as raw text.

    Returns text between `## {section}` and the next `## ` heading.
    Returns empty string if section or daily note doesn't exist.
    """
    try:
        daily = self.read_daily_note(date)
    except FileNotFoundError:
        return ""

    content = daily.get("content", "")
    header = f"## {section}"
    if header not in content:
        return ""

    idx = content.index(header) + len(header)
    next_section = content.find("\n## ", idx)
    if next_section == -1:
        return content[idx:]
    return content[idx:next_section]

def replace_daily_section(
    self,
    section: str,
    new_content: str,
    date: Optional[datetime] = None,
) -> Dict:
    """Replace the content of a daily note section.

    Finds `## {section}` and replaces everything between it and
    the next `## ` heading (or end of file) with new_content.
    Creates the daily note if it doesn't exist.
    """
    try:
        daily = self.read_daily_note(date)
    except FileNotFoundError:
        daily = self.create_daily_note(date)

    content = daily["content"]
    header = f"## {section}"

    if header in content:
        idx = content.index(header) + len(header)
        next_section = content.find("\n## ", idx)
        if next_section == -1:
            updated = content[:idx] + "\n\n" + new_content + "\n"
        else:
            updated = content[:idx] + "\n\n" + new_content + "\n" + content[next_section:]
    else:
        updated = content.rstrip() + f"\n\n{header}\n\n{new_content}\n"

    path = self.get_daily_note_path(date)
    self.write_file(path, daily["metadata"], updated)
    return {"path": path, "section": section}
```

**Step 4: Run tests to verify they pass**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_vault_service.py::TestDailySections -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add apps/vault-server/src/services/vault_service.py apps/vault-server/tests/test_vault_service.py
git commit -m "feat(vault-service): add read_daily_section and replace_daily_section"
```

---

### Task 2: VaultService — delete file, archive task, fuzzy find helpers

**Files:**
- Modify: `apps/vault-server/src/services/vault_service.py`
- Test: `apps/vault-server/tests/test_vault_service.py`

**Step 1: Write the failing tests**

Add to `tests/test_vault_service.py`:

```python
class TestDeleteAndArchive:
    def test_delete_file(self, vault_service, vault_path):
        assert (vault_path / "40-tasks/active/buy-groceries.md").exists()
        vault_service.delete_file("40-tasks/active/buy-groceries.md")
        assert not (vault_path / "40-tasks/active/buy-groceries.md").exists()

    def test_delete_file_not_found(self, vault_service):
        with pytest.raises(FileNotFoundError):
            vault_service.delete_file("40-tasks/active/nonexistent.md")

    def test_archive_task_no_tokens(self, vault_service, vault_path):
        old_ledger = vault_service.read_token_ledger()
        old_total = old_ledger["metadata"]["total_tokens"]

        result = vault_service.archive_task("40-tasks/active/buy-groceries.md")

        assert result["archive_path"] == "40-tasks/archive/buy-groceries.md"
        assert not (vault_path / "40-tasks/active/buy-groceries.md").exists()
        assert (vault_path / "40-tasks/archive/buy-groceries.md").exists()

        new_ledger = vault_service.read_token_ledger()
        assert new_ledger["metadata"]["total_tokens"] == old_total

        archived = vault_service.read_file("40-tasks/archive/buy-groceries.md")
        assert archived["metadata"]["status"] == "archived"

    def test_find_habit_by_name(self, vault_service):
        habit = vault_service.find_habit_by_name("workout")
        assert habit is not None
        assert habit["metadata"]["name"] == "Workout"

    def test_find_habit_by_name_not_found(self, vault_service):
        assert vault_service.find_habit_by_name("nonexistent") is None

    def test_find_goal_by_name(self, vault_service):
        goal = vault_service.find_goal_by_name("get fit")
        assert goal is not None
        assert goal["metadata"]["name"] == "Get fit"

    def test_find_goal_by_name_not_found(self, vault_service):
        assert vault_service.find_goal_by_name("nonexistent") is None
```

**Step 2: Run tests to verify they fail**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_vault_service.py::TestDeleteAndArchive -v`
Expected: FAIL

**Step 3: Implement methods**

Add to `apps/vault-server/src/services/vault_service.py`:

```python
def delete_file(self, relative_path: str):
    """Delete a vault file."""
    file_path = self.vault_path / relative_path
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {relative_path}")
    file_path.unlink()

def archive_task(self, task_path: str) -> Dict:
    """Move a task to archive without awarding tokens."""
    task = self.read_file(task_path)
    metadata = task["metadata"]
    task_name = metadata.get("name", "Task")

    today = datetime.now(self.tz).strftime('%Y-%m-%d')
    metadata["status"] = "archived"
    metadata["updated"] = today

    filename = Path(task_path).name
    archive_path = f"40-tasks/archive/{filename}"
    self.write_file(archive_path, metadata, task["content"])

    active_file = self.vault_path / task_path
    if active_file.exists():
        active_file.unlink()

    return {"task_name": task_name, "archive_path": archive_path}

def find_habit_by_name(self, name: str) -> Optional[Dict]:
    """Find a habit by name (fuzzy match)."""
    habits = self.list_active_habits()
    name_lower = name.lower()
    for habit in habits:
        habit_name = habit["metadata"].get("name", "").lower()
        if name_lower in habit_name or habit_name in name_lower:
            return habit
    return None

def find_goal_by_name(self, name: str) -> Optional[Dict]:
    """Find a goal by name (fuzzy match)."""
    goals = self.list_active_goals()
    name_lower = name.lower()
    for goal in goals:
        goal_name = goal["metadata"].get("name", "").lower()
        if name_lower in goal_name or goal_name in name_lower:
            return goal
    return None
```

**Step 4: Run tests to verify they pass**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_vault_service.py::TestDeleteAndArchive -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add apps/vault-server/src/services/vault_service.py apps/vault-server/tests/test_vault_service.py
git commit -m "feat(vault-service): add delete_file, archive_task, find_habit/goal_by_name"
```

---

### Task 3: AgentService — daily section tools

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py`
- Test: `apps/vault-server/tests/test_agent_service.py`

**Step 1: Write the failing tests**

Add to `tests/test_agent_service.py`:

```python
class TestDailySectionTools:
    def test_read_daily_section_tool_registered(self, agent):
        assert "read_daily_section" in agent.tools
        assert agent.tools["read_daily_section"]["risk"] == "safe"

    def test_edit_daily_section_tool_registered(self, agent):
        assert "edit_daily_section" in agent.tools
        assert agent.tools["edit_daily_section"]["risk"] == "write"

    def test_read_daily_section_calls_vault(self, agent, mock_services):
        vault = mock_services[1]
        vault.read_daily_section.return_value = "Some notes here"
        result = agent._tool_read_daily_section({"section": "Notes"})
        assert result["content"] == "Some notes here"
        vault.read_daily_section.assert_called_once()

    def test_edit_daily_section_calls_vault(self, agent, mock_services):
        vault = mock_services[1]
        vault.replace_daily_section.return_value = {"path": "10-daily/2026-03-06.md", "section": "Notes"}
        result = agent._tool_edit_daily_section({"section": "Notes", "content": "Updated notes"})
        assert "path" in result
        vault.replace_daily_section.assert_called_once()
```

**Step 2: Run tests to verify they fail**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_agent_service.py::TestDailySectionTools -v`
Expected: FAIL

**Step 3: Register tools and implement handlers**

In `apps/vault-server/src/services/agent_service.py`, add to `_register_tools()` dict (after `get_daily`):

```python
"read_daily_section": {
    "schema": {
        "name": "read_daily_section",
        "description": "Read the content of a daily note section (e.g., Notes, Tasks, Daily Habits).",
        "input_schema": {
            "type": "object",
            "properties": {
                "section": {"type": "string", "description": "Section name (e.g., 'Notes', 'Tasks', 'Daily Habits')"},
                "date": {"type": "string", "description": "Date YYYY-MM-DD (default: today)"},
            },
            "required": ["section"],
        },
    },
    "handler": self._tool_read_daily_section,
    "risk": "safe",
},
"edit_daily_section": {
    "schema": {
        "name": "edit_daily_section",
        "description": "Replace the content of a daily note section. Use read_daily_section first to see current content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "section": {"type": "string", "description": "Section name (e.g., 'Notes', 'Tasks')"},
                "content": {"type": "string", "description": "New section content (replaces existing)"},
                "date": {"type": "string", "description": "Date YYYY-MM-DD (default: today)"},
                "_confidence": {"type": "number"},
                "_reasoning": {"type": "string"},
            },
            "required": ["section", "content"],
        },
    },
    "handler": self._tool_edit_daily_section,
    "risk": "write",
},
```

Add a `_parse_date` helper near the other helpers:

```python
def _parse_date(self, date_str: str | None):
    """Parse YYYY-MM-DD string to datetime or None for today."""
    if not date_str:
        return None
    import datetime as dt
    return dt.datetime.fromisoformat(date_str)
```

Add handler methods:

```python
def _tool_read_daily_section(self, params: dict) -> dict:
    date = self._parse_date(params.get("date"))
    content = self.vault.read_daily_section(params["section"], date)
    return {"section": params["section"], "content": content}

def _tool_edit_daily_section(self, params: dict) -> dict:
    date = self._parse_date(params.get("date"))
    result = self.vault.replace_daily_section(
        section=params["section"],
        new_content=params["content"],
        date=date,
    )
    return {"path": result["path"], "section": result["section"], "_items": [result["path"]]}
```

**Step 4: Run tests to verify they pass**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_agent_service.py::TestDailySectionTools -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_agent_service.py
git commit -m "feat(agent): add read_daily_section and edit_daily_section tools"
```

---

### Task 4: AgentService — delete/archive tools

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py`
- Test: `apps/vault-server/tests/test_agent_service.py`

**Step 1: Write the failing tests**

Add to `tests/test_agent_service.py`:

```python
class TestDeleteArchiveTools:
    def test_delete_task_tool_registered(self, agent):
        assert "delete_task" in agent.tools
        assert agent.tools["delete_task"]["risk"] == "destructive"

    def test_archive_task_tool_registered(self, agent):
        assert "archive_task" in agent.tools
        assert agent.tools["archive_task"]["risk"] == "destructive"

    def test_delete_habit_tool_registered(self, agent):
        assert "delete_habit" in agent.tools
        assert agent.tools["delete_habit"]["risk"] == "destructive"

    def test_archive_goal_tool_registered(self, agent):
        assert "archive_goal" in agent.tools
        assert agent.tools["archive_goal"]["risk"] == "destructive"

    def test_delete_task_calls_vault(self, agent, mock_services):
        vault = mock_services[1]
        vault.find_task_by_name.return_value = {
            "path": "40-tasks/active/buy-milk.md",
            "metadata": {"name": "Buy milk"},
        }
        result = agent._tool_delete_task({"task_name": "buy milk"})
        assert result["deleted"] == "Buy milk"
        vault.delete_file.assert_called_once_with("40-tasks/active/buy-milk.md")

    def test_delete_task_not_found(self, agent, mock_services):
        vault = mock_services[1]
        vault.find_task_by_name.return_value = None
        result = agent._tool_delete_task({"task_name": "nonexistent"})
        assert "error" in result

    def test_archive_task_calls_vault(self, agent, mock_services):
        vault = mock_services[1]
        vault.find_task_by_name.return_value = {
            "path": "40-tasks/active/buy-milk.md",
            "metadata": {"name": "Buy milk"},
        }
        vault.archive_task.return_value = {
            "task_name": "Buy milk",
            "archive_path": "40-tasks/archive/buy-milk.md",
        }
        result = agent._tool_archive_task({"task_name": "buy milk"})
        assert result["archived_to"] == "40-tasks/archive/buy-milk.md"
        vault.archive_task.assert_called_once_with("40-tasks/active/buy-milk.md")

    def test_delete_habit_calls_vault(self, agent, mock_services):
        vault = mock_services[1]
        vault.find_habit_by_name.return_value = {
            "path": "20-habits/workout.md",
            "metadata": {"name": "Workout"},
        }
        result = agent._tool_delete_habit({"habit_name": "workout"})
        assert result["deleted"] == "Workout"
        vault.delete_file.assert_called_once_with("20-habits/workout.md")

    def test_archive_goal_calls_vault(self, agent, mock_services):
        vault = mock_services[1]
        vault.find_goal_by_name.return_value = {
            "path": "30-goals/2026/get-fit.md",
            "metadata": {"name": "Get fit"},
        }
        result = agent._tool_archive_goal({"goal_name": "get fit"})
        assert result["archived"] == "Get fit"
        vault.update_file.assert_called_once_with(
            "30-goals/2026/get-fit.md", {"status": "archived"}
        )
```

**Step 2: Run tests to verify they fail**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_agent_service.py::TestDeleteArchiveTools -v`
Expected: FAIL

**Step 3: Register tools and implement handlers**

Add to `_register_tools()` dict in `agent_service.py` (after `complete_habit`):

```python
"delete_task": {
    "schema": {
        "name": "delete_task",
        "description": "Permanently delete a task. Use archive_task if you want to keep it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_name": {"type": "string", "description": "Task name or partial match"},
                "_confidence": {"type": "number"},
                "_reasoning": {"type": "string"},
            },
            "required": ["task_name"],
        },
    },
    "handler": self._tool_delete_task,
    "risk": "destructive",
},
"archive_task": {
    "schema": {
        "name": "archive_task",
        "description": "Archive a task without completing it. No tokens awarded. Use for abandoned or deferred tasks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_name": {"type": "string", "description": "Task name or partial match"},
                "_confidence": {"type": "number"},
                "_reasoning": {"type": "string"},
            },
            "required": ["task_name"],
        },
    },
    "handler": self._tool_archive_task,
    "risk": "destructive",
},
"delete_habit": {
    "schema": {
        "name": "delete_habit",
        "description": "Permanently delete a habit.",
        "input_schema": {
            "type": "object",
            "properties": {
                "habit_name": {"type": "string", "description": "Habit name or partial match"},
                "_confidence": {"type": "number"},
                "_reasoning": {"type": "string"},
            },
            "required": ["habit_name"],
        },
    },
    "handler": self._tool_delete_habit,
    "risk": "destructive",
},
"archive_goal": {
    "schema": {
        "name": "archive_goal",
        "description": "Archive a goal (set status to archived).",
        "input_schema": {
            "type": "object",
            "properties": {
                "goal_name": {"type": "string", "description": "Goal name or partial match"},
                "_confidence": {"type": "number"},
                "_reasoning": {"type": "string"},
            },
            "required": ["goal_name"],
        },
    },
    "handler": self._tool_archive_goal,
    "risk": "destructive",
},
```

Add handler methods:

```python
def _tool_delete_task(self, params: dict) -> dict:
    task = self.vault.find_task_by_name(params["task_name"])
    if not task:
        return {"error": f"No task found matching '{params['task_name']}'"}
    self.vault.delete_file(task["path"])
    return {"deleted": task["metadata"].get("name", ""), "_items": [task["path"]]}

def _tool_archive_task(self, params: dict) -> dict:
    task = self.vault.find_task_by_name(params["task_name"])
    if not task:
        return {"error": f"No task found matching '{params['task_name']}'"}
    result = self.vault.archive_task(task["path"])
    return {
        "task": result["task_name"],
        "archived_to": result["archive_path"],
        "_items": [result["archive_path"]],
    }

def _tool_delete_habit(self, params: dict) -> dict:
    habit = self.vault.find_habit_by_name(params["habit_name"])
    if not habit:
        return {"error": f"No habit found matching '{params['habit_name']}'"}
    self.vault.delete_file(habit["path"])
    return {"deleted": habit["metadata"].get("name", ""), "_items": [habit["path"]]}

def _tool_archive_goal(self, params: dict) -> dict:
    goal = self.vault.find_goal_by_name(params["goal_name"])
    if not goal:
        return {"error": f"No goal found matching '{params['goal_name']}'"}
    self.vault.update_file(goal["path"], {"status": "archived"})
    return {"archived": goal["metadata"].get("name", ""), "_items": [goal["path"]]}
```

**Step 4: Run tests to verify they pass**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_agent_service.py::TestDeleteArchiveTools -v`
Expected: All PASS

**Step 5: Run full test suite**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/ -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_agent_service.py
git commit -m "feat(agent): add delete_task, archive_task, delete_habit, archive_goal tools"
```

---

### Task 5: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update tool count and docs**

- Change agent tool count from 19 to 25
- Add new tools to the agent tools description: `read_daily_section`, `edit_daily_section`, `delete_task`, `archive_task`, `delete_habit`, `archive_goal`
- Update VaultService method descriptions

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for new agent vault editing tools"
```
