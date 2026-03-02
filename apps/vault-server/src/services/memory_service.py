"""Service for managing conversation history, knowledge, and graph index."""

import datetime
import re
from dataclasses import dataclass
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
        self._claude: Any = None  # Set after init for summarization

    def initialize(self) -> None:
        """Called at startup. Builds graph index."""
        self._rebuild_graph()

    # -- Conversation Management -----------------------------------------------

    def _get_conversation_path(self, chat_id: int) -> Path:
        """Get path to today's conversation file for a chat."""
        today = datetime.datetime.now(self.tz).strftime("%Y-%m-%d")
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

        # Apply sliding window -- return only last N messages
        if len(messages) > self.window_size:
            windowed = messages[-self.window_size:]
        else:
            windowed = messages

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
        pattern = r"### \d{2}:\d{2} \[(user|assistant)\]\n(.*?)(?=\n### \d{2}:\d{2} \[|$)"
        for match in re.finditer(pattern, content, re.DOTALL):
            role = match.group(1)
            text = match.group(2).strip()
            if text:
                messages.append({"role": role, "content": text})
        return messages

    # -- Conversation Decay (Task 10) ------------------------------------------

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
            time_str = now.strftime("%H:%M")
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
        prompt = (
            "Summarize this conversation concisely in 2-3 sentences. "
            "Preserve key facts: what items were discussed, created, completed, or modified.\n\n"
            f"Previous summary: {existing_summary or 'None'}\n\n"
            f"Messages to summarize:\n{msg_text}"
        )

        return self._claude.complete(prompt)

    # -- Knowledge CRUD (Task 3) -----------------------------------------------

    def save_knowledge(
        self,
        name: str,
        content: str,
        tags: list[str],
        links: list[str],
        source: str,
        source_ref: str = "",
    ) -> dict[str, Any]:
        """Create a knowledge note in the vault.

        Args:
            name: Title for the knowledge note.
            content: Body content of the note.
            tags: List of tags for categorisation.
            links: List of Obsidian wiki-links (e.g. ``[[gym]]``).
            source: Origin of the knowledge — ``"conversation"`` or ``"inferred"``.
            source_ref: Optional reference back to source (e.g. conversation path).

        Returns:
            Dict with ``path`` and ``metadata``.
        """
        now = datetime.datetime.now(self.tz)
        today = now.strftime("%Y-%m-%d")

        # Choose sub-directory based on source
        subdir = "insights" if source == "inferred" else "notes"
        filename = self.vault._sanitize_filename(name)
        rel_path = f"60-knowledge/{subdir}/{filename}.md"

        metadata: dict[str, Any] = {
            "type": "knowledge",
            "name": name,
            "tags": tags,
            "links": links,
            "source": source,
            "source_ref": source_ref,
            "created": today,
            "updated": today,
        }

        self.vault.write_file(rel_path, metadata, content)

        # Keep graph index up to date (no-op until Task 4)
        self._update_graph_for_file(rel_path, metadata, content)

        return {"path": rel_path, "metadata": metadata}

    def search_knowledge(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Phase-1 keyword search over knowledge notes and insights.

        Splits *query* into lowercase terms and scores each file by how many
        terms appear in the file's name, tags, or filename.

        Args:
            query: Space-separated search terms.
            limit: Maximum number of results to return.

        Returns:
            Sorted list of dicts ``{path, name, tags, score}`` (highest first).
        """
        terms = query.lower().split()
        if not terms:
            return []

        scored: list[dict[str, Any]] = []

        for subdir in ("60-knowledge/notes", "60-knowledge/insights"):
            files = self.vault.list_files(subdir)
            for file_path in files:
                rel_path = str(file_path)
                try:
                    data = self.vault.read_file(rel_path)
                except FileNotFoundError:
                    continue

                meta = data["metadata"]
                name_lower = meta.get("name", "").lower()
                tags_lower = " ".join(t.lower() for t in meta.get("tags", []))
                filename_lower = file_path.stem.lower() if hasattr(file_path, "stem") else rel_path.lower()

                searchable = f"{name_lower} {tags_lower} {filename_lower}"

                score = sum(1 for t in terms if t in searchable)
                if score > 0:
                    scored.append({
                        "path": rel_path,
                        "name": meta.get("name", ""),
                        "tags": meta.get("tags", []),
                        "score": score,
                    })

        scored.sort(key=lambda r: r["score"], reverse=True)
        return scored[:limit]

    def update_preference(self, name: str, observation: str) -> None:
        """Create or update a user-preference file.

        On first call for a given *name*, creates the file with
        ``observations=1`` and ``confidence=0.5``.  On subsequent calls,
        increments *observations* and appends the new observation text
        to the note body.

        Args:
            name: Human-readable preference name (e.g. ``"Task defaults"``).
            observation: A single observation sentence to record.
        """
        now = datetime.datetime.now(self.tz)
        today = now.strftime("%Y-%m-%d")
        filename = self.vault._sanitize_filename(name)
        rel_path = f"00-system/preferences/{filename}.md"

        abs_path = self.vault_path / rel_path

        if abs_path.exists():
            # Update existing preference
            data = self.vault.read_file(rel_path)
            metadata = data["metadata"]
            metadata["observations"] = metadata.get("observations", 1) + 1
            metadata["updated"] = today

            content = data["content"]
            if content and not content.endswith("\n"):
                content += "\n"
            content += f"- {observation}\n"

            self.vault.write_file(rel_path, metadata, content)
        else:
            # Create new preference
            metadata: dict[str, Any] = {
                "type": "preference",
                "name": name,
                "observations": 1,
                "confidence": 0.5,
                "created": today,
                "updated": today,
            }
            content = f"# {name}\n\n- {observation}\n"
            self.vault.write_file(rel_path, metadata, content)

    # -- Context Assembly (Task 5) ------------------------------------------------

    def assemble_context(self, chat_id: int) -> ConversationContext:
        """Build the full context for an agent loop call.

        Combines: conversation history (short-term), vault state snapshot
        (mid-term), and relevant knowledge + preferences (long-term).
        """
        conversation = self.load_conversation(chat_id)
        vault_snapshot = self._build_vault_snapshot(conversation)
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

        items = conversation.get("items_referenced", [])
        if items:
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

    # -- Graph Index (Task 4) --------------------------------------------------

    def _rebuild_graph(self) -> None:
        """Scan all vault markdown files and build in-memory adjacency map."""
        self.graph = {}

        for md_file in self.vault_path.rglob("*.md"):
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

            wiki_links = set(re.findall(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', content))

            fm_links = set()
            for link in metadata.get("links", []):
                match = re.match(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', str(link))
                if match:
                    fm_links.add(match.group(1))

            for ref in metadata.get("items_referenced", []):
                fm_links.add(Path(ref).stem)

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

        wiki_links = set(re.findall(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', content))
        fm_links = set()
        for link in metadata.get("links", []):
            match = re.match(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', str(link))
            if match:
                fm_links.add(match.group(1))

        all_links = wiki_links | fm_links

        if node_id in self.graph:
            for old_target in self.graph[node_id]["links_to"]:
                if old_target in self.graph:
                    self.graph[old_target]["linked_from"].discard(node_id)

        self.graph[node_id] = {
            "path": rel_path,
            "type": metadata.get("type", "unknown"),
            "tags": metadata.get("tags", []),
            "links_to": all_links,
            "linked_from": self.graph.get(node_id, {}).get("linked_from", set()),
        }

        for target in all_links:
            if target in self.graph:
                self.graph[target]["linked_from"].add(node_id)

    def get_related(self, topic: str, depth: int = 2) -> list[dict]:
        """Get nodes within N hops of topic via BFS."""
        if topic not in self.graph:
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

    def get_most_connected(self, tag: str | None = None, limit: int = 5) -> list[dict]:
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
        if topic_lower in self.graph:
            return topic_lower
        for node_id in self.graph:
            if topic_lower in node_id or node_id in topic_lower:
                return node_id
        return None
