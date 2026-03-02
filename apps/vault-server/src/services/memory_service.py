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
    # Stub -- implemented in Task 3

    # -- Graph Index (Task 4) --------------------------------------------------

    def _rebuild_graph(self) -> None:
        """Scan vault and build in-memory adjacency map. Stub for now."""
        self.graph = {}

    def _update_graph_for_file(
        self, rel_path: str, metadata: dict, content: str
    ) -> None:
        """Update graph index for a single file. Stub until Task 4."""
        pass
