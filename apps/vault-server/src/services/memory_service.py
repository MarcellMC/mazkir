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

    # -- Graph Index (Task 4) --------------------------------------------------

    def _rebuild_graph(self) -> None:
        """Scan vault and build in-memory adjacency map. Stub for now."""
        self.graph = {}

    def _update_graph_for_file(
        self, rel_path: str, metadata: dict, content: str
    ) -> None:
        """Update graph index for a single file. Stub until Task 4."""
        pass
