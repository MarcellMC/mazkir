# Memory System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the stateless intent-parse-then-route pattern with a Claude tool-use agent loop backed by a three-tier memory system, all stored in the Obsidian vault.

**Architecture:** New `MemoryService` (conversation management, knowledge CRUD, graph index) and `AgentService` (tool-use loop, confidence gate) added to vault-server. Claude tool-use replaces intent parsing. Telegram client gets minor changes for chat_id and confirmation routing.

**Tech Stack:** Python 3.12, FastAPI, Anthropic SDK (tool-use API), python-frontmatter, pytest, pytest-asyncio

**Design Doc:** `docs/plans/2026-03-02-memory-system-design.md`

---

## Task 1: Vault Structure — New Folders and Templates

**Files:**
- Create: `memory/00-system/conversations/.gitkeep`
- Create: `memory/00-system/preferences/.gitkeep`
- Create: `memory/60-knowledge/notes/.gitkeep`
- Create: `memory/60-knowledge/insights/.gitkeep`
- Create: `memory/00-system/templates/_conversation_.md`
- Create: `memory/00-system/templates/_knowledge_.md`
- Modify: `memory/AGENTS.md` (append new schemas)

**Step 1: Create new vault directories**

```bash
mkdir -p memory/00-system/conversations
mkdir -p memory/00-system/preferences
mkdir -p memory/60-knowledge/notes
mkdir -p memory/60-knowledge/insights
touch memory/00-system/conversations/.gitkeep
touch memory/00-system/preferences/.gitkeep
touch memory/60-knowledge/notes/.gitkeep
touch memory/60-knowledge/insights/.gitkeep
```

**Step 2: Create conversation template**

Create `memory/00-system/templates/_conversation_.md`:

```markdown
---
type: conversation
chat_id: "{{chat_id}}"
date: "{{date}}"
started: "{{timestamp}}"
last_active: "{{timestamp}}"
message_count: 0
summary: ""
tags: []
items_referenced: []
---
```

**Step 3: Create knowledge template**

Create `memory/00-system/templates/_knowledge_.md`:

```markdown
---
type: knowledge
name: "{{title}}"
created: "{{date}}"
updated: "{{date}}"
tags: []
links: []
source: "{{source}}"
source_ref: ""
---

{{content}}
```

**Step 4: Update AGENTS.md with new schemas**

Append to `memory/AGENTS.md` after the existing schemas section:

```markdown
## Conversation Log (`00-system/conversations/`)

Stores conversation history per chat per day. Used by MemoryService for short-term context.

**Location:** `00-system/conversations/YYYY-MM-DD/{chat_id}.md`

| Field | Type | Description |
|-------|------|-------------|
| type | string | Always "conversation" |
| chat_id | integer | Telegram chat ID |
| date | date | Conversation date (YYYY-MM-DD) |
| started | datetime | First message timestamp |
| last_active | datetime | Most recent message timestamp |
| message_count | integer | Total messages in conversation |
| summary | string | AI-generated summary of decayed messages |
| tags | list | Auto-extracted topic tags |
| items_referenced | list | Vault paths touched during conversation |

Messages stored as markdown sections below frontmatter:
`### HH:MM [user|assistant]`

## Preference (`00-system/preferences/`)

System-inferred user patterns. Internal operational data.

**Location:** `00-system/preferences/{preference-name}.md`

| Field | Type | Description |
|-------|------|-------------|
| type | string | Always "knowledge" |
| name | string | Preference name |
| tags | list | Category tags |
| links | list | Related vault items |
| source | string | Always "inferred" |
| confidence | float | 0-1 confidence score |
| observations | integer | Number of supporting observations |

## Knowledge Note (`60-knowledge/notes/`)

User-captured ideas, facts, and references. Browsable in Obsidian.

**Location:** `60-knowledge/notes/{note-name}.md`

| Field | Type | Description |
|-------|------|-------------|
| type | string | Always "knowledge" |
| name | string | Note title |
| tags | list | Category tags |
| links | list | Wikilinks to related vault items |
| source | string | "conversation" or "user" |
| source_ref | string | Path to source conversation |

## Knowledge Insight (`60-knowledge/insights/`)

AI-generated connections and observations.

**Location:** `60-knowledge/insights/{insight-name}.md`

| Field | Type | Description |
|-------|------|-------------|
| type | string | Always "knowledge" |
| name | string | Insight title |
| tags | list | Category tags |
| links | list | Wikilinks to related items |
| source | string | Always "inferred" |
| confidence | float | 0-1 confidence score |
```

**Step 5: Commit**

```bash
git add memory/00-system/conversations/.gitkeep memory/00-system/preferences/.gitkeep \
  memory/60-knowledge/notes/.gitkeep memory/60-knowledge/insights/.gitkeep \
  memory/00-system/templates/_conversation_.md memory/00-system/templates/_knowledge_.md \
  memory/AGENTS.md
git commit -m "feat: add vault structure for memory system (conversations, knowledge, preferences)"
```

---

## Task 2: MemoryService — Conversation Management

The core new service. This task covers conversation loading, saving, and summarization. Knowledge and graph come in later tasks.

**Files:**
- Create: `apps/vault-server/src/services/memory_service.py`
- Create: `apps/vault-server/tests/test_memory_service.py`

**Step 1: Write tests for conversation management**

Create `apps/vault-server/tests/test_memory_service.py`:

```python
"""Tests for MemoryService conversation management."""

import datetime
from pathlib import Path

import pytest

from src.services.memory_service import MemoryService
from src.services.vault_service import VaultService


@pytest.fixture
def memory_service(vault_service, vault_path):
    """Create MemoryService with test vault."""
    # Create required directories
    (vault_path / "00-system" / "conversations").mkdir(parents=True, exist_ok=True)
    (vault_path / "00-system" / "preferences").mkdir(parents=True, exist_ok=True)
    (vault_path / "60-knowledge" / "notes").mkdir(parents=True, exist_ok=True)
    (vault_path / "60-knowledge" / "insights").mkdir(parents=True, exist_ok=True)

    service = MemoryService(
        vault=vault_service,
        vault_path=vault_path,
        timezone="Asia/Jerusalem",
    )
    return service


class TestConversationManagement:
    def test_load_conversation_returns_empty_for_new_chat(self, memory_service):
        result = memory_service.load_conversation(chat_id=123456)
        assert result["messages"] == []
        assert result["summary"] == ""

    def test_save_turn_creates_conversation_file(self, memory_service, vault_path):
        memory_service.save_turn(
            chat_id=123456,
            user_msg="hello",
            assistant_msg="hi there",
            items_referenced=[],
        )
        today = datetime.date.today().isoformat()
        conv_dir = vault_path / "00-system" / "conversations" / today
        conv_file = conv_dir / "123456.md"
        assert conv_file.exists()

    def test_save_turn_appends_messages(self, memory_service):
        memory_service.save_turn(123456, "first message", "first reply", [])
        memory_service.save_turn(123456, "second message", "second reply", [])

        result = memory_service.load_conversation(123456)
        assert len(result["messages"]) == 4  # 2 user + 2 assistant

    def test_save_turn_updates_frontmatter(self, memory_service):
        memory_service.save_turn(123456, "hello", "hi", [])
        memory_service.save_turn(123456, "create task", "done", ["40-tasks/active/test.md"])

        result = memory_service.load_conversation(123456)
        assert result["message_count"] == 4
        assert "40-tasks/active/test.md" in result["items_referenced"]

    def test_load_conversation_respects_window_size(self, memory_service):
        memory_service.window_size = 4  # 2 turns = 4 messages
        # Save 4 turns (8 messages)
        for i in range(4):
            memory_service.save_turn(123456, f"msg {i}", f"reply {i}", [])

        result = memory_service.load_conversation(123456)
        # Should return only last window_size messages
        assert len(result["messages"]) == 4
        # Oldest messages should be accessible via raw file
        assert result["message_count"] == 8

    def test_save_turn_tracks_items_referenced(self, memory_service):
        memory_service.save_turn(
            123456, "done with gym", "completed!",
            items_referenced=["20-habits/gym.md"],
        )
        memory_service.save_turn(
            123456, "create task buy milk", "created!",
            items_referenced=["40-tasks/active/buy-milk.md"],
        )

        result = memory_service.load_conversation(123456)
        assert "20-habits/gym.md" in result["items_referenced"]
        assert "40-tasks/active/buy-milk.md" in result["items_referenced"]


class TestConversationContext:
    def test_get_conversation_file_path(self, memory_service):
        today = datetime.date.today().isoformat()
        path = memory_service._get_conversation_path(123456)
        assert str(path).endswith(f"{today}/123456.md")

    def test_parse_conversation_messages(self, memory_service):
        memory_service.save_turn(123456, "hello", "hi there", [])
        result = memory_service.load_conversation(123456)

        assert result["messages"][0]["role"] == "user"
        assert result["messages"][0]["content"] == "hello"
        assert result["messages"][1]["role"] == "assistant"
        assert result["messages"][1]["content"] == "hi there"
```

**Step 2: Run tests to verify they fail**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_memory_service.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'src.services.memory_service'`

**Step 3: Implement MemoryService conversation management**

Create `apps/vault-server/src/services/memory_service.py`:

```python
"""Service for managing conversation history, knowledge, and graph index."""

import datetime
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import frontmatter
import pytz

from src.services.vault_service import VaultService


@dataclass
class ConversationContext:
    """Assembled context for the agent loop."""
    messages: list[dict[str, str]]
    summary: str
    vault_snapshot: str
    knowledge: str


class MemoryService:
    """Manages three-tier memory: conversations, vault state, and knowledge."""

    def __init__(
        self,
        vault: VaultService,
        vault_path: Path,
        timezone: str = "Asia/Jerusalem",
    ):
        self.vault = vault
        self.vault_path = Path(vault_path)
        self.tz = pytz.timezone(timezone)
        self.window_size = 20  # messages before decay
        self.graph: dict[str, dict] = {}

    def initialize(self) -> None:
        """Called at startup. Builds graph index."""
        self._rebuild_graph()

    # ── Conversation Management ──────────────────────────────────

    def _get_conversation_path(self, chat_id: int) -> Path:
        """Get path to today's conversation file for a chat."""
        today = datetime.date.today().isoformat()
        return self.vault_path / "00-system" / "conversations" / today / f"{chat_id}.md"

    def load_conversation(self, chat_id: int) -> dict[str, Any]:
        """Load conversation history for a chat.

        Returns dict with: messages (list), summary (str),
        message_count (int), items_referenced (list).
        """
        path = self._get_conversation_path(chat_id)

        if not path.exists():
            return {
                "messages": [],
                "summary": "",
                "message_count": 0,
                "items_referenced": [],
            }

        post = frontmatter.load(str(path))
        metadata = dict(post.metadata)
        content = post.content

        messages = self._parse_messages(content)
        message_count = metadata.get("message_count", len(messages))
        summary = metadata.get("summary", "")
        items_referenced = metadata.get("items_referenced", [])

        # Apply sliding window — return only last N messages
        windowed = messages[-self.window_size:] if len(messages) > self.window_size else messages

        return {
            "messages": windowed,
            "summary": summary,
            "message_count": message_count,
            "items_referenced": items_referenced,
        }

    def save_turn(
        self,
        chat_id: int,
        user_msg: str,
        assistant_msg: str,
        items_referenced: list[str],
    ) -> None:
        """Append a user/assistant exchange to the conversation file."""
        path = self._get_conversation_path(chat_id)
        now = datetime.datetime.now(self.tz)
        time_str = now.strftime("%H:%M")

        if path.exists():
            post = frontmatter.load(str(path))
            metadata = dict(post.metadata)
            existing_content = post.content
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            metadata = {
                "type": "conversation",
                "chat_id": chat_id,
                "date": now.strftime("%Y-%m-%d"),
                "started": now.isoformat(),
                "last_active": now.isoformat(),
                "message_count": 0,
                "summary": "",
                "tags": [],
                "items_referenced": [],
            }
            existing_content = ""

        # Append messages
        new_content = existing_content
        if new_content and not new_content.endswith("\n"):
            new_content += "\n"
        new_content += f"\n### {time_str} [user]\n{user_msg}\n"
        new_content += f"\n### {time_str} [assistant]\n{assistant_msg}\n"

        # Update metadata
        metadata["last_active"] = now.isoformat()
        metadata["message_count"] = metadata.get("message_count", 0) + 2

        # Merge items_referenced (deduplicate)
        existing_refs = set(metadata.get("items_referenced", []))
        existing_refs.update(items_referenced)
        metadata["items_referenced"] = sorted(existing_refs)

        # Write file
        post = frontmatter.Post(new_content, **metadata)
        path.write_text(frontmatter.dumps(post), encoding="utf-8")

    def _parse_messages(self, content: str) -> list[dict[str, str]]:
        """Parse conversation markdown into message dicts."""
        messages = []
        # Match: ### HH:MM [role]\ncontent
        pattern = r"### \d{2}:\d{2} \[(user|assistant)\]\n(.*?)(?=\n### \d{2}:\d{2} \[|$)"
        for match in re.finditer(pattern, content, re.DOTALL):
            role = match.group(1)
            text = match.group(2).strip()
            if text:
                messages.append({"role": role, "content": text})
        return messages

    # ── Knowledge CRUD ───────────────────────────────────────────
    # (Implemented in Task 3)

    # ── Graph Index ──────────────────────────────────────────────
    # (Implemented in Task 4)

    def _rebuild_graph(self) -> None:
        """Scan vault and build in-memory adjacency map. Stub for now."""
        self.graph = {}
```

**Step 4: Run tests to verify they pass**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_memory_service.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add apps/vault-server/src/services/memory_service.py apps/vault-server/tests/test_memory_service.py
git commit -m "feat: add MemoryService with conversation management"
```

---

## Task 3: MemoryService — Knowledge CRUD

Add knowledge note creation, search, and preference management to MemoryService.

**Files:**
- Modify: `apps/vault-server/src/services/memory_service.py`
- Modify: `apps/vault-server/tests/test_memory_service.py`

**Step 1: Write tests for knowledge operations**

Append to `apps/vault-server/tests/test_memory_service.py`:

```python
class TestKnowledgeCRUD:
    def test_save_knowledge_creates_note(self, memory_service, vault_path):
        result = memory_service.save_knowledge(
            name="Dentist location",
            content="Dentist is on Av. Roma 1234, Dr. Garcia.",
            tags=["health", "locations"],
            links=[],
            source="conversation",
        )
        assert result["path"].startswith("60-knowledge/notes/")
        assert (vault_path / result["path"]).exists()

    def test_save_knowledge_stores_metadata(self, memory_service):
        result = memory_service.save_knowledge(
            name="Test note",
            content="Some content.",
            tags=["test"],
            links=["[[gym]]"],
            source="conversation",
        )
        note = memory_service.vault.read_file(result["path"])
        assert note["metadata"]["name"] == "Test note"
        assert note["metadata"]["type"] == "knowledge"
        assert note["metadata"]["tags"] == ["test"]
        assert "[[gym]]" in note["metadata"]["links"]
        assert note["metadata"]["source"] == "conversation"

    def test_save_knowledge_insight(self, memory_service, vault_path):
        result = memory_service.save_knowledge(
            name="Health routine gap",
            content="User creates meal tasks after gym.",
            tags=["health"],
            links=["[[gym]]"],
            source="inferred",
        )
        assert result["path"].startswith("60-knowledge/insights/")

    def test_search_knowledge_finds_by_tag(self, memory_service):
        memory_service.save_knowledge(
            name="Gym schedule",
            content="Morning sessions work best.",
            tags=["health", "gym"],
            links=[],
            source="conversation",
        )
        memory_service.save_knowledge(
            name="Python tips",
            content="Use dataclasses.",
            tags=["programming"],
            links=[],
            source="conversation",
        )

        results = memory_service.search_knowledge("health gym")
        assert len(results) >= 1
        assert any("gym-schedule" in r["path"] for r in results)

    def test_search_knowledge_finds_by_name(self, memory_service):
        memory_service.save_knowledge(
            name="Dentist location",
            content="Av. Roma 1234",
            tags=["health"],
            links=[],
            source="conversation",
        )

        results = memory_service.search_knowledge("dentist")
        assert len(results) >= 1

    def test_search_knowledge_returns_empty_for_no_match(self, memory_service):
        results = memory_service.search_knowledge("quantum physics")
        assert results == []


class TestPreferences:
    def test_update_preference_creates_new(self, memory_service, vault_path):
        memory_service.update_preference(
            name="Task defaults",
            observation="User set priority to 1 for grocery task",
        )
        pref_path = vault_path / "00-system" / "preferences" / "task-defaults.md"
        assert pref_path.exists()

    def test_update_preference_increments_observations(self, memory_service):
        memory_service.update_preference("Task defaults", "First observation")
        memory_service.update_preference("Task defaults", "Second observation")

        pref_path = "00-system/preferences/task-defaults.md"
        data = memory_service.vault.read_file(pref_path)
        assert data["metadata"]["observations"] == 2

    def test_update_preference_appends_content(self, memory_service):
        memory_service.update_preference("Task defaults", "User prefers priority 1")
        memory_service.update_preference("Task defaults", "User prefers due dates")

        pref_path = "00-system/preferences/task-defaults.md"
        data = memory_service.vault.read_file(pref_path)
        assert "User prefers priority 1" in data["content"]
        assert "User prefers due dates" in data["content"]
```

**Step 2: Run tests to verify new tests fail**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_memory_service.py -v -k "Knowledge or Preferences"
```

Expected: FAIL — `AttributeError: 'MemoryService' object has no attribute 'save_knowledge'`

**Step 3: Implement knowledge CRUD methods**

Add to `MemoryService` in `apps/vault-server/src/services/memory_service.py`, replacing the stub comment:

```python
    # ── Knowledge CRUD ───────────────────────────────────────────

    def save_knowledge(
        self,
        name: str,
        content: str,
        tags: list[str],
        links: list[str],
        source: str,
        source_ref: str = "",
    ) -> dict:
        """Create a knowledge note in the vault.

        Args:
            name: Note title.
            content: Note body text.
            tags: Category tags.
            links: Wikilinks to related items.
            source: "conversation", "user", or "inferred".
            source_ref: Path to source conversation if applicable.

        Returns:
            Dict with path and metadata of created note.
        """
        today = datetime.date.today().isoformat()
        filename = self.vault._sanitize_filename(name) + ".md"

        # Inferred notes go to insights/, everything else to notes/
        if source == "inferred":
            rel_path = f"60-knowledge/insights/{filename}"
        else:
            rel_path = f"60-knowledge/notes/{filename}"

        metadata = {
            "type": "knowledge",
            "name": name,
            "created": today,
            "updated": today,
            "tags": tags,
            "links": links,
            "source": source,
            "source_ref": source_ref,
        }

        self.vault.write_file(rel_path, metadata, f"# {name}\n\n{content}")
        self._update_graph_for_file(rel_path, metadata, content)

        return {"path": rel_path, "metadata": metadata}

    def search_knowledge(self, query: str, limit: int = 5) -> list[dict]:
        """Search knowledge notes by keyword matching on name and tags.

        Phase 1: keyword overlap on titles and tags.
        Phase 2 (future): embedding-based semantic search.
        """
        query_terms = set(query.lower().split())
        candidates = []

        # Scan notes and insights directories
        for subdir in ["60-knowledge/notes", "60-knowledge/insights"]:
            dir_path = self.vault_path / subdir
            if not dir_path.exists():
                continue
            for md_file in dir_path.glob("*.md"):
                rel_path = str(md_file.relative_to(self.vault_path))
                try:
                    data = self.vault.read_file(rel_path)
                except Exception:
                    continue

                # Score: count query term matches in name, tags, and filename
                name = data["metadata"].get("name", "").lower()
                tags = [t.lower() for t in data["metadata"].get("tags", [])]
                stem = md_file.stem.replace("-", " ").lower()

                searchable = f"{name} {stem} {' '.join(tags)}"
                score = sum(1 for term in query_terms if term in searchable)

                if score > 0:
                    candidates.append({
                        "path": rel_path,
                        "name": data["metadata"].get("name", stem),
                        "tags": data["metadata"].get("tags", []),
                        "score": score,
                    })

        candidates.sort(key=lambda c: c["score"], reverse=True)
        return candidates[:limit]

    def update_preference(self, name: str, observation: str) -> dict:
        """Update or create a preference file with a new observation.

        Args:
            name: Preference name (e.g., "Task defaults").
            observation: New observation to append.

        Returns:
            Dict with path and updated metadata.
        """
        filename = self.vault._sanitize_filename(name) + ".md"
        rel_path = f"00-system/preferences/{filename}"
        full_path = self.vault_path / rel_path

        today = datetime.date.today().isoformat()

        if full_path.exists():
            data = self.vault.read_file(rel_path)
            metadata = data["metadata"]
            content = data["content"]

            metadata["observations"] = metadata.get("observations", 0) + 1
            metadata["updated"] = today

            content = content.rstrip() + f"\n- {observation}\n"
            self.vault.write_file(rel_path, metadata, content)
        else:
            metadata = {
                "type": "knowledge",
                "name": name,
                "created": today,
                "updated": today,
                "tags": ["preferences"],
                "links": [],
                "source": "inferred",
                "confidence": 0.5,
                "observations": 1,
            }
            content = f"# {name}\n\n- {observation}\n"
            self.vault.write_file(rel_path, metadata, content)

        return {"path": rel_path, "metadata": metadata}

    def _update_graph_for_file(self, rel_path: str, metadata: dict, content: str) -> None:
        """Update graph index for a single file. Stub until Task 4."""
        pass
```

**Step 4: Run tests to verify they pass**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_memory_service.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add apps/vault-server/src/services/memory_service.py apps/vault-server/tests/test_memory_service.py
git commit -m "feat: add knowledge CRUD and preference management to MemoryService"
```

---

## Task 4: MemoryService — Graph Index

Build in-memory adjacency map from vault `[[wikilinks]]`, tags, and frontmatter links.

**Files:**
- Modify: `apps/vault-server/src/services/memory_service.py`
- Modify: `apps/vault-server/tests/test_memory_service.py`

**Step 1: Write tests for graph operations**

Append to `apps/vault-server/tests/test_memory_service.py`:

```python
class TestGraphIndex:
    def test_rebuild_graph_indexes_existing_files(self, memory_service, vault_path):
        """The conftest vault_path fixture creates sample habits/tasks/goals."""
        memory_service._rebuild_graph()
        # Should have nodes for files in the test vault
        assert len(memory_service.graph) > 0

    def test_graph_node_has_tags(self, memory_service, vault_path):
        memory_service._rebuild_graph()
        # buy-groceries task from conftest
        if "buy-groceries" in memory_service.graph:
            node = memory_service.graph["buy-groceries"]
            assert "tags" in node

    def test_graph_extracts_wikilinks(self, memory_service, vault_path):
        """Create a note with wikilinks and verify graph picks them up."""
        memory_service.save_knowledge(
            name="Morning routine",
            content="Start with [[gym]] then [[meditation]].",
            tags=["health"],
            links=["[[gym]]", "[[meditation]]"],
            source="conversation",
        )
        memory_service._rebuild_graph()

        assert "morning-routine" in memory_service.graph
        node = memory_service.graph["morning-routine"]
        assert "gym" in node["links_to"]

    def test_get_related_returns_neighbors(self, memory_service, vault_path):
        memory_service.save_knowledge(
            name="Node A",
            content="Links to [[node-b]].",
            tags=["test"],
            links=["[[node-b]]"],
            source="conversation",
        )
        memory_service.save_knowledge(
            name="Node B",
            content="Links to [[node-c]].",
            tags=["test"],
            links=["[[node-c]]"],
            source="conversation",
        )
        memory_service.save_knowledge(
            name="Node C",
            content="End node.",
            tags=["test"],
            links=[],
            source="conversation",
        )
        memory_service._rebuild_graph()

        related = memory_service.get_related("node-a", depth=2)
        node_ids = [r["id"] for r in related]
        assert "node-a" in node_ids
        assert "node-b" in node_ids
        assert "node-c" in node_ids  # 2 hops away

    def test_get_related_respects_depth(self, memory_service, vault_path):
        memory_service.save_knowledge("A", "[[b]]", ["test"], ["[[b]]"], "conversation")
        memory_service.save_knowledge("B", "[[c]]", ["test"], ["[[c]]"], "conversation")
        memory_service.save_knowledge("C", "end", ["test"], [], "conversation")
        memory_service._rebuild_graph()

        related = memory_service.get_related("a", depth=1)
        node_ids = [r["id"] for r in related]
        assert "a" in node_ids
        assert "b" in node_ids
        assert "c" not in node_ids  # 2 hops, beyond depth=1

    def test_get_related_returns_empty_for_unknown(self, memory_service):
        memory_service._rebuild_graph()
        related = memory_service.get_related("nonexistent-node", depth=1)
        assert related == []

    def test_get_most_connected(self, memory_service, vault_path):
        # Create a hub node that multiple notes link to
        memory_service.save_knowledge("Hub", "Central topic.", ["test"], [], "conversation")
        memory_service.save_knowledge("Spoke 1", "About [[hub]].", ["test"], ["[[hub]]"], "conversation")
        memory_service.save_knowledge("Spoke 2", "Also [[hub]].", ["test"], ["[[hub]]"], "conversation")
        memory_service.save_knowledge("Spoke 3", "And [[hub]].", ["test"], ["[[hub]]"], "conversation")
        memory_service._rebuild_graph()

        top = memory_service.get_most_connected(limit=1)
        assert top[0]["id"] == "hub"

    def test_get_most_connected_filters_by_tag(self, memory_service, vault_path):
        memory_service.save_knowledge("Health hub", "Main.", ["health"], [], "conversation")
        memory_service.save_knowledge("H1", "[[health-hub]]", ["health"], ["[[health-hub]]"], "conversation")
        memory_service.save_knowledge("H2", "[[health-hub]]", ["health"], ["[[health-hub]]"], "conversation")
        memory_service.save_knowledge("Code hub", "Main.", ["code"], [], "conversation")
        memory_service.save_knowledge("C1", "[[code-hub]]", ["code"], ["[[code-hub]]"], "conversation")
        memory_service._rebuild_graph()

        top_health = memory_service.get_most_connected(tag="health", limit=1)
        assert top_health[0]["id"] == "health-hub"
```

**Step 2: Run tests to verify new tests fail**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_memory_service.py -v -k "Graph"
```

Expected: FAIL — `AttributeError: 'MemoryService' object has no attribute 'get_related'`

**Step 3: Implement graph index**

Replace the `_rebuild_graph` stub and add graph methods in `memory_service.py`:

```python
    # ── Graph Index ──────────────────────────────────────────────

    def _rebuild_graph(self) -> None:
        """Scan all vault markdown files and build in-memory adjacency map."""
        self.graph = {}

        for md_file in self.vault_path.rglob("*.md"):
            # Skip non-content directories
            rel = md_file.relative_to(self.vault_path)
            if str(rel).startswith("."):
                continue

            try:
                post = frontmatter.load(str(md_file))
            except Exception:
                continue

            metadata = dict(post.metadata)
            content = post.content
            node_id = md_file.stem

            # Extract wikilinks from content
            wiki_links = set(re.findall(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', content))

            # Extract links from frontmatter
            fm_links = set()
            for link in metadata.get("links", []):
                match = re.match(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', str(link))
                if match:
                    fm_links.add(match.group(1))

            # Extract items_referenced
            for ref in metadata.get("items_referenced", []):
                ref_stem = Path(ref).stem
                fm_links.add(ref_stem)

            all_links = wiki_links | fm_links

            self.graph[node_id] = {
                "path": str(rel),
                "type": metadata.get("type", "unknown"),
                "tags": metadata.get("tags", []),
                "links_to": all_links,
                "linked_from": set(),
            }

        # Second pass: populate backlinks
        for node_id, node in self.graph.items():
            for target in node["links_to"]:
                if target in self.graph:
                    self.graph[target]["linked_from"].add(node_id)

    def _update_graph_for_file(self, rel_path: str, metadata: dict, content: str) -> None:
        """Update graph index for a single file without full rebuild."""
        node_id = Path(rel_path).stem

        # Extract links
        wiki_links = set(re.findall(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', content))
        fm_links = set()
        for link in metadata.get("links", []):
            match = re.match(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', str(link))
            if match:
                fm_links.add(match.group(1))

        all_links = wiki_links | fm_links

        # Remove old backlinks from this node
        if node_id in self.graph:
            for old_target in self.graph[node_id]["links_to"]:
                if old_target in self.graph:
                    self.graph[old_target]["linked_from"].discard(node_id)

        # Update node
        self.graph[node_id] = {
            "path": rel_path,
            "type": metadata.get("type", "unknown"),
            "tags": metadata.get("tags", []),
            "links_to": all_links,
            "linked_from": self.graph.get(node_id, {}).get("linked_from", set()),
        }

        # Add new backlinks
        for target in all_links:
            if target in self.graph:
                self.graph[target]["linked_from"].add(node_id)

    def get_related(self, topic: str, depth: int = 2) -> list[dict]:
        """Get nodes within N hops of topic via BFS."""
        if topic not in self.graph:
            # Try fuzzy match on node IDs
            topic = self._fuzzy_find_node(topic)
            if not topic:
                return []

        visited: set[str] = set()
        queue: list[tuple[str, int]] = [(topic, 0)]
        results: list[dict] = []

        while queue:
            node_id, d = queue.pop(0)
            if node_id in visited or d > depth:
                continue
            visited.add(node_id)

            if node_id not in self.graph:
                continue

            node = self.graph[node_id]
            results.append({
                "id": node_id,
                "path": node["path"],
                "type": node["type"],
                "tags": node["tags"],
                "depth": d,
            })

            for neighbor in node["links_to"] | node["linked_from"]:
                if neighbor not in visited:
                    queue.append((neighbor, d + 1))

        return results

    def get_most_connected(
        self, tag: str | None = None, limit: int = 5
    ) -> list[dict]:
        """Get nodes with the most connections, optionally filtered by tag."""
        candidates = []
        for node_id, node in self.graph.items():
            if tag and tag not in node.get("tags", []):
                continue
            degree = len(node["links_to"]) + len(node["linked_from"])
            candidates.append({
                "id": node_id,
                "path": node["path"],
                "type": node["type"],
                "tags": node["tags"],
                "degree": degree,
            })

        candidates.sort(key=lambda c: c["degree"], reverse=True)
        return candidates[:limit]

    def _fuzzy_find_node(self, topic: str) -> str | None:
        """Find a graph node by fuzzy matching on ID."""
        topic_lower = topic.lower().replace(" ", "-")
        # Exact match
        if topic_lower in self.graph:
            return topic_lower
        # Substring match
        for node_id in self.graph:
            if topic_lower in node_id or node_id in topic_lower:
                return node_id
        return None
```

**Step 4: Run tests to verify they pass**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_memory_service.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add apps/vault-server/src/services/memory_service.py apps/vault-server/tests/test_memory_service.py
git commit -m "feat: add graph index with BFS traversal and most-connected queries"
```

---

## Task 5: MemoryService — Context Assembly

The `assemble_context()` method that builds the full context for each agent loop call.

**Files:**
- Modify: `apps/vault-server/src/services/memory_service.py`
- Modify: `apps/vault-server/tests/test_memory_service.py`

**Step 1: Write tests for context assembly**

Append to `apps/vault-server/tests/test_memory_service.py`:

```python
class TestContextAssembly:
    def test_assemble_context_returns_dataclass(self, memory_service):
        ctx = memory_service.assemble_context(chat_id=123456)
        assert isinstance(ctx, ConversationContext)
        assert isinstance(ctx.messages, list)
        assert isinstance(ctx.summary, str)
        assert isinstance(ctx.vault_snapshot, str)
        assert isinstance(ctx.knowledge, str)

    def test_assemble_context_includes_conversation(self, memory_service):
        memory_service.save_turn(123456, "hello", "hi there", [])
        ctx = memory_service.assemble_context(123456)
        assert len(ctx.messages) == 2
        assert ctx.messages[0]["content"] == "hello"

    def test_assemble_context_includes_vault_snapshot(self, memory_service):
        ctx = memory_service.assemble_context(123456)
        # The test vault fixture has tasks and habits
        assert "task" in ctx.vault_snapshot.lower() or "habit" in ctx.vault_snapshot.lower()

    def test_assemble_context_includes_preferences(self, memory_service):
        memory_service.update_preference("Test pref", "Some observation")
        ctx = memory_service.assemble_context(123456)
        assert "Test pref" in ctx.knowledge or "test pref" in ctx.knowledge.lower()
```

Add import at the top of the test file:

```python
from src.services.memory_service import MemoryService, ConversationContext
```

**Step 2: Run tests to verify new tests fail**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_memory_service.py -v -k "ContextAssembly"
```

Expected: FAIL — `AttributeError: 'MemoryService' object has no attribute 'assemble_context'`

**Step 3: Implement context assembly**

Add to `MemoryService` in `memory_service.py`:

```python
    # ── Context Assembly ─────────────────────────────────────────

    def assemble_context(self, chat_id: int) -> ConversationContext:
        """Build the full context for an agent loop call.

        Combines: conversation history (short-term), vault state snapshot
        (mid-term), and relevant knowledge + preferences (long-term).
        """
        # 1. Conversation (short-term)
        conversation = self.load_conversation(chat_id)

        # 2. Vault snapshot (mid-term)
        vault_snapshot = self._build_vault_snapshot(conversation)

        # 3. Knowledge (long-term)
        knowledge = self._gather_relevant_knowledge(conversation)

        return ConversationContext(
            messages=conversation["messages"],
            summary=conversation["summary"],
            vault_snapshot=vault_snapshot,
            knowledge=knowledge,
        )

    def _build_vault_snapshot(self, conversation: dict) -> str:
        """Build a compact vault state summary for the system prompt."""
        parts = []

        # Active tasks
        try:
            tasks = self.vault.list_active_tasks()
            if tasks:
                referenced = set(conversation.get("items_referenced", []))
                task_lines = []
                for t in tasks:
                    name = t["metadata"].get("name", Path(t["path"]).stem)
                    priority = t["metadata"].get("priority", 3)
                    due = t["metadata"].get("due_date", "no due date")
                    ref_marker = " [referenced]" if t["path"] in referenced else ""
                    task_lines.append(f"  - {name} (P{priority}, due: {due}){ref_marker}")
                parts.append(f"Active tasks ({len(tasks)}):\n" + "\n".join(task_lines))
        except Exception:
            pass

        # Active habits
        try:
            habits = self.vault.list_active_habits()
            if habits:
                habit_items = []
                for h in habits:
                    name = h["metadata"].get("name", Path(h["path"]).stem)
                    streak = h["metadata"].get("streak", 0)
                    habit_items.append(f"{name} (streak {streak})")
                parts.append("Habits: " + ", ".join(habit_items))
        except Exception:
            pass

        # Active goals
        try:
            goals = self.vault.list_active_goals()
            if goals:
                goal_items = []
                for g in goals:
                    name = g["metadata"].get("name", Path(g["path"]).stem)
                    progress = g["metadata"].get("progress", 0)
                    goal_items.append(f"{name} ({progress}%)")
                parts.append("Goals: " + ", ".join(goal_items))
        except Exception:
            pass

        # Token balance
        try:
            ledger = self.vault.read_token_ledger()
            total = ledger["metadata"].get("total_tokens", 0)
            today = ledger["metadata"].get("tokens_today", 0)
            parts.append(f"Tokens: {today} earned today, {total} total")
        except Exception:
            pass

        return "\n\n".join(parts) if parts else "No vault data available."

    def _gather_relevant_knowledge(self, conversation: dict) -> str:
        """Gather preferences and knowledge relevant to the conversation."""
        parts = []

        # Always load preferences (they're small)
        pref_dir = self.vault_path / "00-system" / "preferences"
        if pref_dir.exists():
            for pref_file in pref_dir.glob("*.md"):
                try:
                    rel_path = str(pref_file.relative_to(self.vault_path))
                    data = self.vault.read_file(rel_path)
                    name = data["metadata"].get("name", pref_file.stem)
                    content = data["content"].strip()
                    if content:
                        parts.append(f"[Preference: {name}]\n{content}")
                except Exception:
                    continue

        # If conversation has referenced items, look for related knowledge
        items = conversation.get("items_referenced", [])
        if items:
            # Get tags from referenced items to search knowledge
            search_terms = set()
            for ref in items:
                stem = Path(ref).stem.replace("-", " ")
                search_terms.add(stem)

            for term in search_terms:
                for result in self.search_knowledge(term, limit=2):
                    try:
                        data = self.vault.read_file(result["path"])
                        name = data["metadata"].get("name", "")
                        content = data["content"].strip()
                        if content:
                            parts.append(f"[Knowledge: {name}]\n{content}")
                    except Exception:
                        continue

        return "\n\n".join(parts) if parts else ""
```

**Step 4: Run tests to verify they pass**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_memory_service.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add apps/vault-server/src/services/memory_service.py apps/vault-server/tests/test_memory_service.py
git commit -m "feat: add context assembly to MemoryService (vault snapshot + knowledge gathering)"
```

---

## Task 6: Simplify ClaudeService

Remove `parse_intent()`, add `create()` for tool-use API calls.

**Files:**
- Modify: `apps/vault-server/src/services/claude_service.py`
- Create: `apps/vault-server/tests/test_claude_service.py`

**Step 1: Write tests for new ClaudeService interface**

Create `apps/vault-server/tests/test_claude_service.py`:

```python
"""Tests for simplified ClaudeService."""

from unittest.mock import MagicMock, patch

from src.services.claude_service import ClaudeService


class TestClaudeServiceInit:
    def test_init_stores_api_key(self):
        with patch("src.services.claude_service.anthropic") as mock_anthropic:
            service = ClaudeService(api_key="test-key")
            mock_anthropic.Anthropic.assert_called_once_with(api_key="test-key")

    def test_has_create_method(self):
        with patch("src.services.claude_service.anthropic"):
            service = ClaudeService(api_key="test-key")
            assert hasattr(service, "create")

    def test_has_complete_method(self):
        with patch("src.services.claude_service.anthropic"):
            service = ClaudeService(api_key="test-key")
            assert hasattr(service, "complete")

    def test_no_parse_intent_method(self):
        with patch("src.services.claude_service.anthropic"):
            service = ClaudeService(api_key="test-key")
            assert not hasattr(service, "parse_intent")


class TestClaudeServiceCreate:
    def test_create_passes_tools(self):
        with patch("src.services.claude_service.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client

            service = ClaudeService(api_key="test-key")
            tools = [{"name": "test_tool", "description": "test", "input_schema": {}}]

            service.create(
                system="test system",
                messages=[{"role": "user", "content": "hello"}],
                tools=tools,
            )

            call_kwargs = mock_client.messages.create.call_args[1]
            assert call_kwargs["tools"] == tools
            assert call_kwargs["system"] == "test system"

    def test_create_without_tools(self):
        with patch("src.services.claude_service.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client

            service = ClaudeService(api_key="test-key")

            service.create(
                system="test",
                messages=[{"role": "user", "content": "hello"}],
            )

            call_kwargs = mock_client.messages.create.call_args[1]
            assert "tools" not in call_kwargs


class TestClaudeServiceComplete:
    def test_complete_returns_text(self):
        with patch("src.services.claude_service.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="summary text")]
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.Anthropic.return_value = mock_client

            service = ClaudeService(api_key="test-key")
            result = service.complete("summarize this")

            assert result == "summary text"

    def test_complete_uses_haiku_by_default(self):
        with patch("src.services.claude_service.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="ok")]
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.Anthropic.return_value = mock_client

            service = ClaudeService(api_key="test-key")
            service.complete("test")

            call_kwargs = mock_client.messages.create.call_args[1]
            assert "haiku" in call_kwargs["model"]
```

**Step 2: Run tests to verify they fail**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_claude_service.py -v
```

Expected: FAIL — tests that check for removal of `parse_intent` will fail, `create()` method doesn't exist yet.

**Step 3: Rewrite ClaudeService**

Replace contents of `apps/vault-server/src/services/claude_service.py`:

```python
"""Thin wrapper around the Anthropic Claude API."""

import anthropic


class ClaudeService:
    """Claude API client for tool-use and simple completions."""

    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)

    def create(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 4096,
    ) -> anthropic.types.Message:
        """Claude API call with tool-use support.

        Args:
            system: System prompt.
            messages: Conversation messages.
            tools: Tool definitions (optional).
            model: Model to use.
            max_tokens: Max tokens in response.

        Returns:
            Raw Anthropic Message response.
        """
        kwargs: dict = {
            "model": model,
            "system": system,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
        return self.client.messages.create(**kwargs)

    def complete(
        self,
        prompt: str,
        system: str = "",
        model: str = "claude-haiku-4-5-20251001",
        max_tokens: int = 1024,
    ) -> str:
        """Simple single-turn completion. Used for summarization, etc.

        Args:
            prompt: User prompt.
            system: System prompt (optional).
            model: Model to use (defaults to Haiku for cost).
            max_tokens: Max tokens.

        Returns:
            Claude's response as plain text.
        """
        response = self.client.messages.create(
            model=model,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
        return response.content[0].text
```

**Step 4: Run tests to verify they pass**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_claude_service.py -v
```

Expected: All tests PASS.

**Step 5: Run all existing tests to check for breakage**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/ -v
```

Expected: Vault service tests PASS. Any tests that relied on the old ClaudeService interface will need updates in Task 8 (route changes).

**Step 6: Commit**

```bash
git add apps/vault-server/src/services/claude_service.py apps/vault-server/tests/test_claude_service.py
git commit -m "refactor: simplify ClaudeService to thin API wrapper with tool-use support"
```

---

## Task 7: AgentService — Core Loop and Tool Registry

The agent loop, tool definitions, confidence gate, and confirmation flow.

**Files:**
- Create: `apps/vault-server/src/services/agent_service.py`
- Create: `apps/vault-server/tests/test_agent_service.py`

**Step 1: Write tests for agent service**

Create `apps/vault-server/tests/test_agent_service.py`:

```python
"""Tests for AgentService — tool registry, confidence gate, loop control."""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.agent_service import AgentService, AgentResponse, CONFIDENCE_THRESHOLD


@pytest.fixture
def mock_services():
    """Create mock service dependencies."""
    claude = MagicMock()
    vault = MagicMock()
    memory = MagicMock()
    calendar = MagicMock()

    # Default memory.assemble_context return
    from src.services.memory_service import ConversationContext
    memory.assemble_context.return_value = ConversationContext(
        messages=[],
        summary="",
        vault_snapshot="No data.",
        knowledge="",
    )
    memory.save_turn = MagicMock()
    memory.summarize_and_decay = MagicMock()

    return claude, vault, memory, calendar


@pytest.fixture
def agent(mock_services):
    claude, vault, memory, calendar = mock_services
    return AgentService(
        claude=claude, vault=vault, memory=memory, calendar=calendar,
    )


class TestToolRegistry:
    def test_tools_are_registered(self, agent):
        assert len(agent.tools) > 0

    def test_all_tools_have_required_fields(self, agent):
        for name, tool in agent.tools.items():
            assert "schema" in tool
            assert "handler" in tool
            assert "risk" in tool
            assert tool["risk"] in ("safe", "write", "destructive")

    def test_safe_tools_exist(self, agent):
        safe = [n for n, t in agent.tools.items() if t["risk"] == "safe"]
        assert "list_tasks" in safe
        assert "list_habits" in safe
        assert "search_knowledge" in safe

    def test_destructive_tools_exist(self, agent):
        destructive = [n for n, t in agent.tools.items() if t["risk"] == "destructive"]
        assert "complete_task" in destructive
        assert "complete_habit" in destructive


class TestConfidenceGate:
    def test_safe_tools_always_pass(self, agent):
        assert agent._check_confidence("list_tasks", {}) is True

    def test_write_tool_passes_with_high_confidence(self, agent):
        params = {"name": "test", "_confidence": 0.95, "_reasoning": "clear intent"}
        assert agent._check_confidence("create_task", params) is True
        # _confidence and _reasoning should be popped
        assert "_confidence" not in params
        assert "_reasoning" not in params

    def test_write_tool_fails_with_low_confidence(self, agent):
        params = {"name": "test", "_confidence": 0.5, "_reasoning": "unsure"}
        assert agent._check_confidence("create_task", params) is False

    def test_destructive_tool_fails_with_low_confidence(self, agent):
        params = {"task_name": "buy milk", "_confidence": 0.6, "_reasoning": "maybe"}
        assert agent._check_confidence("complete_task", params) is False

    def test_missing_confidence_defaults_low(self, agent):
        params = {"task_name": "test"}
        assert agent._check_confidence("complete_task", params) is False

    def test_confidence_at_threshold_passes(self, agent):
        params = {"name": "test", "_confidence": CONFIDENCE_THRESHOLD}
        assert agent._check_confidence("create_task", params) is True


class TestAgentResponse:
    def test_response_dataclass(self):
        r = AgentResponse(response="hello")
        assert r.response == "hello"
        assert r.awaiting_confirmation is False
        assert r.pending_action_id is None

    def test_confirmation_response(self):
        r = AgentResponse(
            response="Confirm?",
            awaiting_confirmation=True,
            pending_action_id="abc123",
        )
        assert r.awaiting_confirmation is True
        assert r.pending_action_id == "abc123"


class TestHandleMessage:
    def test_simple_text_response(self, agent, mock_services):
        """Claude returns end_turn with text — simplest case."""
        claude = mock_services[0]
        memory = mock_services[2]

        # Mock Claude response: just text, no tool calls
        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Hello! How can I help?"
        mock_response.content = [text_block]
        claude.create.return_value = mock_response

        result = agent.handle_message("hello", chat_id=123)

        assert result.response == "Hello! How can I help?"
        assert result.awaiting_confirmation is False
        memory.save_turn.assert_called_once()

    def test_tool_call_then_response(self, agent, mock_services):
        """Claude calls a tool, gets result, then responds with text."""
        claude = mock_services[0]
        vault = mock_services[1]
        memory = mock_services[2]

        # First response: tool call
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "list_tasks"
        tool_block.id = "tool_123"
        tool_block.input = {}
        mock_tool_response = MagicMock()
        mock_tool_response.stop_reason = "tool_use"
        mock_tool_response.content = [tool_block]

        # Second response: text
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "You have 2 tasks."
        mock_text_response = MagicMock()
        mock_text_response.stop_reason = "end_turn"
        mock_text_response.content = [text_block]

        claude.create.side_effect = [mock_tool_response, mock_text_response]

        vault.list_active_tasks.return_value = [
            {"path": "40-tasks/active/buy-milk.md", "metadata": {"name": "Buy milk"}},
        ]

        result = agent.handle_message("what tasks do I have?", chat_id=123)

        assert result.response == "You have 2 tasks."
        assert claude.create.call_count == 2

    def test_low_confidence_triggers_confirmation(self, agent, mock_services):
        """Claude calls a destructive tool with low confidence → confirmation."""
        claude = mock_services[0]

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "complete_task"
        tool_block.id = "tool_456"
        tool_block.input = {"task_name": "something", "_confidence": 0.4, "_reasoning": "vague"}
        mock_response = MagicMock()
        mock_response.stop_reason = "tool_use"
        mock_response.content = [tool_block]

        claude.create.return_value = mock_response

        result = agent.handle_message("maybe finish that thing", chat_id=123)

        assert result.awaiting_confirmation is True
        assert result.pending_action_id is not None

    def test_max_iterations_safety(self, agent, mock_services):
        """Loop stops after max_iterations even if Claude keeps calling tools."""
        claude = mock_services[0]
        vault = mock_services[1]
        agent.max_iterations = 2

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "list_tasks"
        tool_block.id = "tool_loop"
        tool_block.input = {}
        mock_response = MagicMock()
        mock_response.stop_reason = "tool_use"
        mock_response.content = [tool_block]

        vault.list_active_tasks.return_value = []
        claude.create.return_value = mock_response

        result = agent.handle_message("loop forever", chat_id=123)

        assert claude.create.call_count == 2
        # Should still return something
        assert result.response is not None
```

**Step 2: Run tests to verify they fail**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_agent_service.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'src.services.agent_service'`

**Step 3: Implement AgentService**

Create `apps/vault-server/src/services/agent_service.py`:

```python
"""Agent loop with tool-use, confidence gate, and confirmation flow."""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import uuid4

from src.services.claude_service import ClaudeService
from src.services.memory_service import MemoryService
from src.services.vault_service import VaultService

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.85


@dataclass
class AgentResponse:
    """Response from the agent loop."""
    response: str
    awaiting_confirmation: bool = False
    pending_action_id: str | None = None


@dataclass
class PendingAction:
    """Stored state when loop is paused for confirmation."""
    chat_id: int
    messages: list[dict]
    assistant_response: Any
    executed_results: list[dict]
    pending_calls: list[dict]


class AgentService:
    """Runs the Claude tool-use agent loop with confidence gating."""

    def __init__(
        self,
        claude: ClaudeService,
        vault: VaultService,
        memory: MemoryService,
        calendar: Any = None,
    ):
        self.claude = claude
        self.vault = vault
        self.memory = memory
        self.calendar = calendar
        self.max_iterations = 10
        self.pending_confirmations: dict[str, PendingAction] = {}
        self.tools = self._register_tools()

    # ── Tool Registry ────────────────────────────────────────────

    def _register_tools(self) -> dict[str, dict]:
        """Register all available tools with schemas and handlers."""
        return {
            # Read-only tools (safe)
            "list_tasks": {
                "schema": {
                    "name": "list_tasks",
                    "description": "List all active tasks sorted by priority and due date.",
                    "input_schema": {"type": "object", "properties": {}, "required": []},
                },
                "handler": self._tool_list_tasks,
                "risk": "safe",
            },
            "list_habits": {
                "schema": {
                    "name": "list_habits",
                    "description": "List all active habits with streaks and stats.",
                    "input_schema": {"type": "object", "properties": {}, "required": []},
                },
                "handler": self._tool_list_habits,
                "risk": "safe",
            },
            "list_goals": {
                "schema": {
                    "name": "list_goals",
                    "description": "List all active goals with progress.",
                    "input_schema": {"type": "object", "properties": {}, "required": []},
                },
                "handler": self._tool_list_goals,
                "risk": "safe",
            },
            "get_daily": {
                "schema": {
                    "name": "get_daily",
                    "description": "Get today's daily note with habits, tokens, and calendar.",
                    "input_schema": {"type": "object", "properties": {}, "required": []},
                },
                "handler": self._tool_get_daily,
                "risk": "safe",
            },
            "get_tokens": {
                "schema": {
                    "name": "get_tokens",
                    "description": "Get current motivation token balance and stats.",
                    "input_schema": {"type": "object", "properties": {}, "required": []},
                },
                "handler": self._tool_get_tokens,
                "risk": "safe",
            },
            "search_knowledge": {
                "schema": {
                    "name": "search_knowledge",
                    "description": "Search knowledge notes by topic or keyword.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query"},
                            "limit": {"type": "integer", "description": "Max results (default 5)"},
                        },
                        "required": ["query"],
                    },
                },
                "handler": self._tool_search_knowledge,
                "risk": "safe",
            },
            "get_related": {
                "schema": {
                    "name": "get_related",
                    "description": "Get vault items related to a topic via graph traversal.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "topic": {"type": "string", "description": "Topic or item name to explore"},
                            "depth": {"type": "integer", "description": "Hops to traverse (default 2)"},
                        },
                        "required": ["topic"],
                    },
                },
                "handler": self._tool_get_related,
                "risk": "safe",
            },
            # Write tools
            "create_task": {
                "schema": {
                    "name": "create_task",
                    "description": "Create a new task in the vault.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Task name"},
                            "priority": {"type": "integer", "description": "Priority 1-5 (1=highest). Default 3."},
                            "due_date": {"type": "string", "description": "Due date YYYY-MM-DD (optional)"},
                            "category": {"type": "string", "description": "Category (default 'personal')"},
                            "_confidence": {"type": "number"},
                            "_reasoning": {"type": "string"},
                        },
                        "required": ["name"],
                    },
                },
                "handler": self._tool_create_task,
                "risk": "write",
            },
            "create_habit": {
                "schema": {
                    "name": "create_habit",
                    "description": "Create a new habit to track.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Habit name"},
                            "frequency": {"type": "string", "description": "daily, weekly, 2x/week, 3x/week"},
                            "category": {"type": "string", "description": "Category (default 'personal')"},
                            "_confidence": {"type": "number"},
                            "_reasoning": {"type": "string"},
                        },
                        "required": ["name"],
                    },
                },
                "handler": self._tool_create_habit,
                "risk": "write",
            },
            "create_goal": {
                "schema": {
                    "name": "create_goal",
                    "description": "Create a new goal.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Goal name"},
                            "priority": {"type": "string", "description": "low, medium, high"},
                            "target_date": {"type": "string", "description": "Target date YYYY-MM-DD (optional)"},
                            "_confidence": {"type": "number"},
                            "_reasoning": {"type": "string"},
                        },
                        "required": ["name"],
                    },
                },
                "handler": self._tool_create_goal,
                "risk": "write",
            },
            "update_item": {
                "schema": {
                    "name": "update_item",
                    "description": "Update metadata of a vault item (task, habit, or goal).",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Relative vault path to the item"},
                            "updates": {"type": "object", "description": "Metadata fields to update"},
                            "_confidence": {"type": "number"},
                            "_reasoning": {"type": "string"},
                        },
                        "required": ["path", "updates"],
                    },
                },
                "handler": self._tool_update_item,
                "risk": "write",
            },
            "save_knowledge": {
                "schema": {
                    "name": "save_knowledge",
                    "description": "Save a knowledge note (idea, fact, or reference).",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Note title"},
                            "content": {"type": "string", "description": "Note content"},
                            "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags"},
                            "links": {"type": "array", "items": {"type": "string"}, "description": "[[wikilinks]]"},
                            "_confidence": {"type": "number"},
                            "_reasoning": {"type": "string"},
                        },
                        "required": ["name", "content"],
                    },
                },
                "handler": self._tool_save_knowledge,
                "risk": "write",
            },
            # Destructive tools
            "complete_task": {
                "schema": {
                    "name": "complete_task",
                    "description": "Mark a task as completed. Awards tokens and archives it.",
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
                "handler": self._tool_complete_task,
                "risk": "destructive",
            },
            "complete_habit": {
                "schema": {
                    "name": "complete_habit",
                    "description": "Mark a habit as completed for today. Updates streak and awards tokens.",
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
                "handler": self._tool_complete_habit,
                "risk": "destructive",
            },
        }

    def _tool_schemas(self) -> list[dict]:
        """Get tool schemas for Claude API call."""
        return [t["schema"] for t in self.tools.values()]

    # ── Confidence Gate ──────────────────────────────────────────

    def _check_confidence(self, name: str, params: dict) -> bool:
        """Check if a tool call passes the confidence gate."""
        risk = self.tools[name]["risk"]
        if risk == "safe":
            return True
        confidence = params.pop("_confidence", 0.0)
        params.pop("_reasoning", None)
        return confidence >= CONFIDENCE_THRESHOLD

    # ── Agent Loop ───────────────────────────────────────────────

    def handle_message(self, text: str, chat_id: int) -> AgentResponse:
        """Main entry point: process a user message through the agent loop."""
        # 1. Assemble context
        context = self.memory.assemble_context(chat_id)

        # 2. Build messages array
        messages = []
        if context.summary:
            messages.append({"role": "user", "content": f"[Previous conversation summary: {context.summary}]"})
            messages.append({"role": "assistant", "content": "Understood, I have the prior context."})
        for msg in context.messages:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": text})

        # 3. System prompt
        system = self._build_system_prompt(context)

        # 4. Run the loop
        return self._run_loop(chat_id, text, messages, system)

    def handle_confirmation(
        self, chat_id: int, action_id: str, user_response: str,
    ) -> AgentResponse:
        """Resume a paused loop after user confirms or denies."""
        pending = self.pending_confirmations.pop(action_id, None)
        if not pending:
            return AgentResponse(response="No pending action found.")

        if user_response.lower() in ("yes", "y", "ok", "sure", "do it"):
            # Execute pending tools
            tool_results = list(pending.executed_results)
            for call in pending.pending_calls:
                result = self._execute_tool(call["name"], call["input"])
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": call["id"],
                    "content": json.dumps(result),
                })

            messages = pending.messages
            messages.append({"role": "assistant", "content": pending.assistant_response.content})
            messages.append({"role": "user", "content": tool_results})

            system = self._build_system_prompt(
                self.memory.assemble_context(chat_id)
            )
            return self._run_loop(chat_id, user_response, messages, system)
        else:
            # User denied or modified — feed response to Claude
            messages = pending.messages
            messages.append({
                "role": "user",
                "content": f"User responded to confirmation: {user_response}",
            })
            system = self._build_system_prompt(
                self.memory.assemble_context(chat_id)
            )
            return self._run_loop(chat_id, user_response, messages, system)

    def _run_loop(
        self,
        chat_id: int,
        original_text: str,
        messages: list[dict],
        system: str,
    ) -> AgentResponse:
        """Core agent loop: Claude ↔ tools until end_turn or max iterations."""
        items_referenced: list[str] = []
        assistant_text = ""

        for _ in range(self.max_iterations):
            response = self.claude.create(
                system=system,
                messages=messages,
                tools=self._tool_schemas(),
            )

            # End turn — Claude has final text
            if response.stop_reason == "end_turn":
                assistant_text = self._extract_text(response)
                break

            # Tool use — execute and feed back
            if response.stop_reason == "tool_use":
                tool_calls = self._extract_tool_calls(response)

                needs_confirmation = []
                auto_execute = []
                for call in tool_calls:
                    if self._check_confidence(call["name"], call["input"]):
                        auto_execute.append(call)
                    else:
                        needs_confirmation.append(call)

                # If anything needs confirmation, pause
                if needs_confirmation:
                    # Execute safe tools first
                    executed = []
                    for call in auto_execute:
                        result = self._execute_tool(call["name"], call["input"])
                        items_referenced.extend(result.get("_items", []))
                        executed.append({
                            "type": "tool_result",
                            "tool_use_id": call["id"],
                            "content": json.dumps(result),
                        })

                    action_id = str(uuid4())
                    self.pending_confirmations[action_id] = PendingAction(
                        chat_id=chat_id,
                        messages=messages,
                        assistant_response=response,
                        executed_results=executed,
                        pending_calls=needs_confirmation,
                    )

                    description = self._describe_pending_calls(needs_confirmation)
                    self.memory.save_turn(chat_id, original_text, description, items_referenced)
                    return AgentResponse(
                        response=description,
                        awaiting_confirmation=True,
                        pending_action_id=action_id,
                    )

                # All tools auto-execute
                tool_results = []
                for call in auto_execute:
                    result = self._execute_tool(call["name"], call["input"])
                    items_referenced.extend(result.get("_items", []))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": call["id"],
                        "content": json.dumps(result),
                    })

                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
        else:
            # Max iterations reached
            assistant_text = self._extract_text(response) if response else "I hit my processing limit. Please try again with a simpler request."

        # Save conversation turn
        self.memory.save_turn(chat_id, original_text, assistant_text, items_referenced)
        self.memory.summarize_and_decay(chat_id)

        return AgentResponse(response=assistant_text)

    # ── Helpers ───────────────────────────────────────────────────

    def _build_system_prompt(self, context) -> str:
        """Build the system prompt with vault snapshot and knowledge."""
        import datetime
        now = datetime.datetime.now()

        parts = [
            "You are Mazkir, a personal AI assistant for managing tasks, habits, goals, and knowledge.",
            "",
            f"Current date/time: {now.strftime('%Y-%m-%d %H:%M')}",
            "",
            "## Tools",
            "You have tools to manage tasks, habits, goals, calendar, and knowledge.",
            "Call tools as needed. You can call multiple tools in sequence.",
            "For every write or destructive tool call, include _confidence (0.0-1.0) and _reasoning fields.",
            "_confidence reflects how sure you are this is the right action. Be honest.",
            "",
            "## Current vault state",
            context.vault_snapshot,
        ]

        if context.knowledge:
            parts.extend(["", "## Relevant knowledge", context.knowledge])

        parts.extend([
            "",
            "## Guidelines",
            "- Be concise and friendly",
            "- Use Telegram markdown: *bold*, _italic_, `monospace`",
            "- When completing items, report tokens earned and streak updates",
            "- When unsure which item the user means, ask — don't guess with low confidence",
            "- Save important facts the user shares using save_knowledge",
            "- Reference specific item names when discussing tasks/habits/goals",
        ])

        return "\n".join(parts)

    def _extract_text(self, response) -> str:
        """Extract text content from a Claude response."""
        for block in response.content:
            if hasattr(block, "text"):
                return block.text
        return ""

    def _extract_tool_calls(self, response) -> list[dict]:
        """Extract tool calls from a Claude response."""
        calls = []
        for block in response.content:
            if hasattr(block, "type") and block.type == "tool_use":
                calls.append({
                    "name": block.name,
                    "id": block.id,
                    "input": dict(block.input),
                })
        return calls

    def _execute_tool(self, name: str, params: dict) -> dict:
        """Execute a registered tool and return its result."""
        if name not in self.tools:
            return {"error": f"Unknown tool: {name}"}
        try:
            handler = self.tools[name]["handler"]
            return handler(params)
        except Exception as e:
            logger.error(f"Tool {name} failed: {e}", exc_info=True)
            return {"error": str(e)}

    def _describe_pending_calls(self, calls: list[dict]) -> str:
        """Build a human-readable description of pending tool calls."""
        lines = ["I'd like to perform the following actions:\n"]
        for call in calls:
            name = call["name"].replace("_", " ")
            params = {k: v for k, v in call["input"].items() if not k.startswith("_")}
            param_str = ", ".join(f"{k}={v}" for k, v in params.items())
            lines.append(f"  - {name}: {param_str}")
        lines.append("\nShould I proceed? (yes/no)")
        return "\n".join(lines)

    # ── Tool Handlers ────────────────────────────────────────────

    def _tool_list_tasks(self, params: dict) -> dict:
        tasks = self.vault.list_active_tasks()
        return {
            "tasks": [
                {"name": t["metadata"].get("name", ""), "path": t["path"],
                 "priority": t["metadata"].get("priority"), "due_date": t["metadata"].get("due_date")}
                for t in tasks
            ],
            "_items": [t["path"] for t in tasks],
        }

    def _tool_list_habits(self, params: dict) -> dict:
        habits = self.vault.list_active_habits()
        return {
            "habits": [
                {"name": h["metadata"].get("name", ""), "path": h["path"],
                 "streak": h["metadata"].get("streak", 0),
                 "frequency": h["metadata"].get("frequency", "daily")}
                for h in habits
            ],
            "_items": [h["path"] for h in habits],
        }

    def _tool_list_goals(self, params: dict) -> dict:
        goals = self.vault.list_active_goals()
        return {
            "goals": [
                {"name": g["metadata"].get("name", ""), "path": g["path"],
                 "progress": g["metadata"].get("progress", 0),
                 "priority": g["metadata"].get("priority")}
                for g in goals
            ],
            "_items": [g["path"] for g in goals],
        }

    def _tool_get_daily(self, params: dict) -> dict:
        try:
            daily = self.vault.read_daily_note()
            return {"daily": daily["metadata"], "content": daily["content"], "_items": [daily["path"]]}
        except Exception:
            return {"error": "No daily note found for today."}

    def _tool_get_tokens(self, params: dict) -> dict:
        try:
            ledger = self.vault.read_token_ledger()
            return {
                "total": ledger["metadata"].get("total_tokens", 0),
                "today": ledger["metadata"].get("tokens_today", 0),
                "all_time": ledger["metadata"].get("all_time_tokens", 0),
            }
        except Exception:
            return {"error": "Token ledger not found."}

    def _tool_search_knowledge(self, params: dict) -> dict:
        results = self.memory.search_knowledge(
            query=params["query"],
            limit=params.get("limit", 5),
        )
        return {"results": results}

    def _tool_get_related(self, params: dict) -> dict:
        results = self.memory.get_related(
            topic=params["topic"],
            depth=params.get("depth", 2),
        )
        return {"related": results}

    def _tool_create_task(self, params: dict) -> dict:
        result = self.vault.create_task(
            name=params["name"],
            priority=params.get("priority", 3),
            due_date=params.get("due_date"),
            category=params.get("category", "personal"),
        )
        return {
            "created": result["metadata"]["name"],
            "path": result["path"],
            "priority": result["metadata"].get("priority"),
            "due_date": result["metadata"].get("due_date"),
            "_items": [result["path"]],
        }

    def _tool_create_habit(self, params: dict) -> dict:
        result = self.vault.create_habit(
            name=params["name"],
            frequency=params.get("frequency", "daily"),
            category=params.get("category", "personal"),
        )
        return {
            "created": result["metadata"]["name"],
            "path": result["path"],
            "frequency": result["metadata"].get("frequency"),
            "_items": [result["path"]],
        }

    def _tool_create_goal(self, params: dict) -> dict:
        result = self.vault.create_goal(
            name=params["name"],
            priority=params.get("priority", "medium"),
            target_date=params.get("target_date"),
        )
        return {
            "created": result["metadata"]["name"],
            "path": result["path"],
            "_items": [result["path"]],
        }

    def _tool_update_item(self, params: dict) -> dict:
        self.vault.update_file(params["path"], params["updates"])
        return {"updated": params["path"], "_items": [params["path"]]}

    def _tool_save_knowledge(self, params: dict) -> dict:
        result = self.memory.save_knowledge(
            name=params["name"],
            content=params["content"],
            tags=params.get("tags", []),
            links=params.get("links", []),
            source="conversation",
        )
        return {"saved": result["path"], "_items": [result["path"]]}

    def _tool_complete_task(self, params: dict) -> dict:
        task = self.vault.find_task_by_name(params["task_name"])
        if not task:
            return {"error": f"No task found matching '{params['task_name']}'"}

        name, tokens, archive_path = self.vault.complete_task(task["path"])

        # Mark calendar event if synced
        if self.calendar and task["metadata"].get("google_event_id"):
            try:
                self.calendar.mark_event_complete(task["metadata"]["google_event_id"])
            except Exception as e:
                logger.warning(f"Calendar update failed: {e}")

        return {
            "task": name,
            "tokens_earned": tokens,
            "archived_to": archive_path,
            "_items": [archive_path],
        }

    def _tool_complete_habit(self, params: dict) -> dict:
        import datetime as dt

        habits = self.vault.list_active_habits()
        target = params["habit_name"].lower()

        # Fuzzy match
        habit = None
        for h in habits:
            name = h["metadata"].get("name", "").lower()
            if target in name or name in target:
                habit = h
                break

        if not habit:
            return {"error": f"No habit found matching '{params['habit_name']}'"}

        # Update streak
        meta = habit["metadata"]
        old_streak = meta.get("streak", 0)
        new_streak = old_streak + 1
        longest = max(meta.get("longest_streak", 0), new_streak)
        today = dt.date.today().isoformat()

        self.vault.update_file(habit["path"], {
            "streak": new_streak,
            "longest_streak": longest,
            "last_completed": today,
        })

        # Award tokens
        tokens = meta.get("tokens_per_completion", 5)
        self.vault.update_tokens(tokens, meta.get("name", "habit"))

        # Mark calendar if synced
        if self.calendar and meta.get("google_event_id"):
            try:
                self.calendar.mark_event_complete(meta["google_event_id"])
            except Exception as e:
                logger.warning(f"Calendar update failed: {e}")

        return {
            "habit": meta.get("name", ""),
            "old_streak": old_streak,
            "new_streak": new_streak,
            "longest_streak": longest,
            "tokens_earned": tokens,
            "_items": [habit["path"]],
        }
```

**Step 4: Run tests to verify they pass**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_agent_service.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_agent_service.py
git commit -m "feat: add AgentService with tool-use loop, confidence gate, and confirmation flow"
```

---

## Task 8: Wire Up — main.py, message route, and config

Initialize new services in lifespan, replace the message route, update config.

**Files:**
- Modify: `apps/vault-server/src/main.py`
- Modify: `apps/vault-server/src/api/routes/message.py`
- Modify: `apps/vault-server/src/config.py`

**Step 1: Update config.py**

Add to the `Settings` class in `apps/vault-server/src/config.py`:

```python
    # Memory system
    conversation_window_size: int = 20
```

**Step 2: Update main.py — add service initialization**

Add imports at top of `apps/vault-server/src/main.py`:

```python
from src.services.memory_service import MemoryService
from src.services.agent_service import AgentService
```

Add globals alongside existing ones:

```python
memory: MemoryService | None = None
agent: AgentService | None = None
```

Add to the lifespan function, after vault and claude initialization:

```python
    # Initialize MemoryService
    memory = MemoryService(
        vault=vault,
        vault_path=settings.vault_path,
        timezone=settings.vault_timezone,
    )
    memory.window_size = settings.conversation_window_size
    memory.initialize()

    # Initialize AgentService (requires claude)
    if claude:
        agent = AgentService(
            claude=claude,
            vault=vault,
            memory=memory,
            calendar=calendar,
        )
```

Add getter functions:

```python
def get_memory() -> MemoryService | None:
    return memory

def get_agent() -> AgentService | None:
    return agent
```

**Step 3: Replace message route**

Replace contents of `apps/vault-server/src/api/routes/message.py`:

```python
"""Natural language message endpoint — agent loop."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.auth import verify_api_key
from src.main import get_agent

router = APIRouter(tags=["message"], dependencies=[Depends(verify_api_key)])


class MessageRequest(BaseModel):
    text: str
    chat_id: int = 0


class ConfirmationRequest(BaseModel):
    chat_id: int
    action_id: str
    response: str


@router.post("/message")
def handle_message(body: MessageRequest):
    agent = get_agent()
    if not agent:
        raise HTTPException(status_code=503, detail="Agent service not initialized (missing API key?)")

    result = agent.handle_message(body.text, body.chat_id)
    return {
        "response": result.response,
        "awaiting_confirmation": result.awaiting_confirmation,
        "pending_action_id": result.pending_action_id,
    }


@router.post("/message/confirm")
def handle_confirmation(body: ConfirmationRequest):
    agent = get_agent()
    if not agent:
        raise HTTPException(status_code=503, detail="Agent service not initialized")

    result = agent.handle_confirmation(body.chat_id, body.action_id, body.response)
    return {
        "response": result.response,
        "awaiting_confirmation": result.awaiting_confirmation,
        "pending_action_id": result.pending_action_id,
    }
```

**Step 4: Run all tests**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/ -v
```

Expected: All tests PASS. If any existing tests break due to ClaudeService changes, fix imports.

**Step 5: Manual smoke test**

```bash
cd apps/vault-server && source venv/bin/activate && python -m uvicorn src.main:app --reload --port 8000
```

Then in another terminal:

```bash
# Health check
curl http://localhost:8000/health

# Send a message
curl -X POST http://localhost:8000/message \
  -H "Content-Type: application/json" \
  -d '{"text": "what tasks do I have?", "chat_id": 12345}'
```

Expected: Returns JSON with `response`, `awaiting_confirmation`, `pending_action_id`.

**Step 6: Commit**

```bash
git add apps/vault-server/src/main.py apps/vault-server/src/api/routes/message.py apps/vault-server/src/config.py
git commit -m "feat: wire up AgentService and MemoryService in vault-server"
```

---

## Task 9: Telegram Client Updates

Add chat_id to messages, confirmation routing, simplify NL handler.

**Files:**
- Modify: `apps/telegram-py-client/src/api_client.py`
- Modify: `apps/telegram-py-client/src/bot/handlers.py`

**Step 1: Update API client**

In `apps/telegram-py-client/src/api_client.py`, modify `send_message` and add `send_confirmation`:

Replace the existing `send_message` method:

```python
    async def send_message(self, text: str, chat_id: int = 0) -> dict:
        """Send a natural language message to the agent loop."""
        r = await self._client.post(
            "/message", json={"text": text, "chat_id": chat_id},
        )
        r.raise_for_status()
        return r.json()

    async def send_confirmation(
        self, chat_id: int, action_id: str, response: str,
    ) -> dict:
        """Send a confirmation response for a pending action."""
        r = await self._client.post(
            "/message/confirm",
            json={"chat_id": chat_id, "action_id": action_id, "response": response},
        )
        r.raise_for_status()
        return r.json()
```

**Step 2: Update NL handler in handlers.py**

Add module-level dict for confirmation state (near top of file, after `api` init):

```python
# Pending confirmations: chat_id → pending_action_id
_pending_confirmations: dict[int, str] = {}
```

Replace the `handle_message` function:

```python
@authorized_only
async def handle_message(event):
    """Handle natural language messages through the agent loop."""
    if event.message.text.startswith("/"):
        return

    try:
        async with event.client.action(event.chat_id, "typing"):
            chat_id = event.chat_id

            if chat_id in _pending_confirmations:
                # Route as confirmation response
                action_id = _pending_confirmations.pop(chat_id)
                result = await api.send_confirmation(
                    chat_id=chat_id,
                    action_id=action_id,
                    response=event.message.text,
                )
            else:
                result = await api.send_message(event.message.text, chat_id)

            # Store pending confirmation if needed
            if result.get("awaiting_confirmation"):
                _pending_confirmations[chat_id] = result["pending_action_id"]

            await event.respond(result.get("response", "No response received."))
    except Exception as e:
        logger.error(f"Error in NL handler: {e}", exc_info=True)
        await event.respond(f"Sorry, I encountered an error: {str(e)}")

    raise events.StopPropagation
```

Remove the `_format_nl_response` function (lines 338-407 approximately). It's no longer needed — Claude formats responses directly.

**Step 3: Manual integration test**

Start both services:

```bash
# Terminal 1
cd ~/dev/mazkir/apps/vault-server && source venv/bin/activate && python -m uvicorn src.main:app --reload --port 8000

# Terminal 2
cd ~/dev/mazkir/apps/telegram-py-client && source venv/bin/activate && python -m src.main
```

Test via Telegram:
1. Send "what tasks do I have?" — should get a natural response listing tasks
2. Send "create task buy milk, high priority" — should create and confirm
3. Send "set it to due tomorrow" — should understand "it" from context
4. Send "done with that" — should either complete or ask for confirmation

**Step 4: Commit**

```bash
git add apps/telegram-py-client/src/api_client.py apps/telegram-py-client/src/bot/handlers.py
git commit -m "feat: update telegram client for agent loop (chat_id, confirmations, simplified handler)"
```

---

## Task 10: Conversation Decay — Summarization

Add the `summarize_and_decay` implementation that uses Claude Haiku to compress old messages.

**Files:**
- Modify: `apps/vault-server/src/services/memory_service.py`
- Modify: `apps/vault-server/tests/test_memory_service.py`

**Step 1: Write tests for decay**

Append to `apps/vault-server/tests/test_memory_service.py`:

```python
from unittest.mock import MagicMock, patch


class TestConversationDecay:
    def test_summarize_and_decay_does_nothing_under_window(self, memory_service):
        memory_service.window_size = 10
        memory_service.save_turn(123456, "hello", "hi", [])
        # Should not modify the file
        before = memory_service.load_conversation(123456)
        memory_service.summarize_and_decay(123456)
        after = memory_service.load_conversation(123456)
        assert before["message_count"] == after["message_count"]

    def test_summarize_and_decay_compresses_when_over_window(self, memory_service):
        memory_service.window_size = 4

        # Mock the Claude complete call for summarization
        mock_claude = MagicMock()
        mock_claude.complete.return_value = "User greeted and discussed tasks."
        memory_service._claude = mock_claude

        # Create 4 turns (8 messages, over window of 4)
        for i in range(4):
            memory_service.save_turn(123456, f"msg {i}", f"reply {i}", [])

        memory_service.summarize_and_decay(123456)

        result = memory_service.load_conversation(123456)
        assert result["summary"] != ""
        # Message count in file should be reduced
        # But metadata message_count stays at 8 (total historical)
        assert result["message_count"] == 8
```

**Step 2: Run test to verify it fails**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_memory_service.py -v -k "Decay"
```

Expected: FAIL — `summarize_and_decay` doesn't compress yet.

**Step 3: Implement summarize_and_decay**

Add a `_claude` attribute to `MemoryService.__init__`:

```python
    self._claude: Any = None  # Set after initialization for summarization
```

Add the method to MemoryService:

```python
    def summarize_and_decay(self, chat_id: int) -> None:
        """If conversation exceeds window, summarize oldest messages."""
        path = self._get_conversation_path(chat_id)
        if not path.exists():
            return

        post = frontmatter.load(str(path))
        metadata = dict(post.metadata)
        content = post.content

        messages = self._parse_messages(content)
        if len(messages) <= self.window_size:
            return

        # Split: oldest half gets summarized, newest half stays
        cutoff = len(messages) // 2
        old_messages = messages[:cutoff]
        keep_messages = messages[cutoff:]

        # Summarize old messages
        existing_summary = metadata.get("summary", "")
        new_summary = self._summarize_messages(existing_summary, old_messages)

        # Rebuild content with only kept messages
        now = datetime.datetime.now(self.tz)
        lines = []
        for msg in keep_messages:
            time_str = now.strftime("%H:%M")  # Approximate — exact times lost
            lines.append(f"\n### {time_str} [{msg['role']}]\n{msg['content']}\n")

        metadata["summary"] = new_summary
        post = frontmatter.Post("\n".join(lines), **metadata)
        path.write_text(frontmatter.dumps(post), encoding="utf-8")

    def _summarize_messages(
        self, existing_summary: str, messages: list[dict],
    ) -> str:
        """Summarize messages into a compact summary string."""
        if not self._claude:
            # Fallback: concatenate message contents
            parts = []
            if existing_summary:
                parts.append(existing_summary)
            for msg in messages:
                parts.append(f"[{msg['role']}] {msg['content']}")
            return "; ".join(parts)[:500]

        msg_text = "\n".join(
            f"[{m['role']}]: {m['content']}" for m in messages
        )
        prompt = f"""Summarize this conversation concisely in 2-3 sentences.
Preserve key facts: what items were discussed, created, completed, or modified.

Previous summary: {existing_summary or 'None'}

Messages to summarize:
{msg_text}"""

        return self._claude.complete(prompt)
```

In `main.py` lifespan, after memory initialization, add:

```python
    # Give MemoryService access to Claude for summarization
    if claude:
        memory._claude = claude
```

**Step 4: Run tests to verify they pass**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_memory_service.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add apps/vault-server/src/services/memory_service.py apps/vault-server/tests/test_memory_service.py apps/vault-server/src/main.py
git commit -m "feat: add conversation decay with Claude-powered summarization"
```

---

## Task 11: End-to-End Integration Test

Verify the complete flow works from HTTP request through agent loop.

**Files:**
- Create: `apps/vault-server/tests/test_integration.py`

**Step 1: Write integration test**

Create `apps/vault-server/tests/test_integration.py`:

```python
"""End-to-end integration test for the agent loop."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.services.memory_service import MemoryService
from src.services.agent_service import AgentService


@pytest.fixture
def agent_with_vault(vault_service, vault_path):
    """Create a fully wired AgentService with real vault, mocked Claude."""
    # Real MemoryService with real vault
    memory = MemoryService(
        vault=vault_service,
        vault_path=vault_path,
        timezone="Asia/Jerusalem",
    )
    (vault_path / "00-system" / "conversations").mkdir(parents=True, exist_ok=True)
    (vault_path / "00-system" / "preferences").mkdir(parents=True, exist_ok=True)
    (vault_path / "60-knowledge" / "notes").mkdir(parents=True, exist_ok=True)
    (vault_path / "60-knowledge" / "insights").mkdir(parents=True, exist_ok=True)
    memory.initialize()

    # Mock Claude
    claude = MagicMock()

    agent = AgentService(
        claude=claude,
        vault=vault_service,
        memory=memory,
        calendar=None,
    )

    return agent, claude, memory


class TestEndToEnd:
    def test_simple_question_no_tools(self, agent_with_vault):
        agent, claude, _ = agent_with_vault

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "You have 1 active task: Buy groceries (P3)."
        mock_response.content = [text_block]
        claude.create.return_value = mock_response

        result = agent.handle_message("what are my tasks?", chat_id=111)

        assert "Buy groceries" in result.response
        assert not result.awaiting_confirmation

    def test_tool_call_creates_task(self, agent_with_vault):
        agent, claude, _ = agent_with_vault

        # First call: Claude calls create_task tool
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "create_task"
        tool_block.id = "call_1"
        tool_block.input = {
            "name": "Buy milk",
            "priority": 1,
            "_confidence": 0.95,
            "_reasoning": "User clearly asked to create a task",
        }
        mock_tool_response = MagicMock()
        mock_tool_response.stop_reason = "tool_use"
        mock_tool_response.content = [tool_block]

        # Second call: Claude responds with text
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Created task: Buy milk (P1)"
        mock_text_response = MagicMock()
        mock_text_response.stop_reason = "end_turn"
        mock_text_response.content = [text_block]

        claude.create.side_effect = [mock_tool_response, mock_text_response]

        result = agent.handle_message("create task buy milk, priority 1", chat_id=111)

        assert "Buy milk" in result.response

    def test_conversation_context_persists(self, agent_with_vault):
        agent, claude, memory = agent_with_vault

        # First message
        mock_r1 = MagicMock()
        mock_r1.stop_reason = "end_turn"
        tb1 = MagicMock(); tb1.type = "text"; tb1.text = "Created task!"
        mock_r1.content = [tb1]

        # Second message
        mock_r2 = MagicMock()
        mock_r2.stop_reason = "end_turn"
        tb2 = MagicMock(); tb2.type = "text"; tb2.text = "Updated!"
        mock_r2.content = [tb2]

        claude.create.side_effect = [mock_r1, mock_r2]

        agent.handle_message("create task buy milk", chat_id=222)
        agent.handle_message("set it to due tomorrow", chat_id=222)

        # Second call should have conversation history in messages
        second_call = claude.create.call_args_list[1]
        messages = second_call[1]["messages"]
        # Should include prior exchange
        assert any("create task buy milk" in str(m.get("content", "")) for m in messages)

    def test_low_confidence_triggers_confirmation(self, agent_with_vault):
        agent, claude, _ = agent_with_vault

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "complete_task"
        tool_block.id = "call_2"
        tool_block.input = {
            "task_name": "groceries",
            "_confidence": 0.4,
            "_reasoning": "not sure which task",
        }
        mock_response = MagicMock()
        mock_response.stop_reason = "tool_use"
        mock_response.content = [tool_block]
        claude.create.return_value = mock_response

        result = agent.handle_message("maybe finish that thing", chat_id=333)

        assert result.awaiting_confirmation is True
        assert result.pending_action_id is not None
```

**Step 2: Run integration tests**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_integration.py -v
```

Expected: All tests PASS.

**Step 3: Commit**

```bash
git add apps/vault-server/tests/test_integration.py
git commit -m "test: add end-to-end integration tests for agent loop"
```

---

## Task 12: Run Full Test Suite and Cleanup

Final validation — run everything, fix any remaining issues.

**Files:**
- Potentially any file that needs fixups.

**Step 1: Run full test suite**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/ -v
```

**Step 2: Run linter**

```bash
cd apps/vault-server && source venv/bin/activate && python -m ruff check src/ tests/
```

Fix any lint issues.

**Step 3: Manual smoke test of full stack**

Start vault-server, start telegram client, test these scenarios:

1. "what tasks do I have?" — should list tasks
2. "create task buy milk, high priority, due tomorrow" — should create
3. "set it to due Friday instead" — should update (context recall)
4. "done with groceries" — should complete with tokens
5. "remember that the dentist is on Av. Roma" — should save knowledge
6. "what do you know about health?" — should search knowledge

**Step 4: Final commit**

```bash
git add -A
git commit -m "chore: cleanup and fix any remaining issues from memory system implementation"
```

---

## Summary

| Task | What it does | New files | Key risk |
|------|-------------|-----------|----------|
| 1 | Vault folders + templates | 6 files + AGENTS.md update | None |
| 2 | MemoryService conversations | memory_service.py + tests | File I/O format |
| 3 | Knowledge CRUD | memory_service.py additions | Search relevance |
| 4 | Graph index | memory_service.py additions | Performance on large vaults |
| 5 | Context assembly | memory_service.py additions | Token budget |
| 6 | Simplify ClaudeService | claude_service.py rewrite | Breaking existing callers |
| 7 | AgentService | agent_service.py + tests | Core loop correctness |
| 8 | Wire up main.py + routes | main.py, message.py, config | Integration |
| 9 | Telegram client updates | api_client.py, handlers.py | UX regression |
| 10 | Conversation decay | memory_service.py additions | Summary quality |
| 11 | Integration tests | test_integration.py | Coverage gaps |
| 12 | Full suite + cleanup | Various | Missed issues |
