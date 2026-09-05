"""Per-turn tool traces for the agent prompt.

AgentService already writes a rich audit record for every turn to
``data/logs/agent-turns.jsonl``.  Nothing read it, so the agent had no
factual record of its own past actions and reasoned about them from its
*current* tool list instead -- which is how it came to deny writes it had
made (Ship 3, spec section 2).

This module is the reader.  It is deliberately pure: it takes paths and
dicts, returns strings and lists, and depends on no service.  It also never
raises -- ``assemble_context`` calls it on every single turn, so a malformed
log line must cost one trace, not the whole conversation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_LOG_FILENAME = "agent-turns.jsonl"


def read_turn_records(
    logs_dir: Path | str, chat_id: int, date: str,
) -> list[dict[str, Any]]:
    """Return this chat's turn records for ``date``, in chronological order.

    Args:
        logs_dir: Directory holding ``agent-turns.jsonl``.
        chat_id: Telegram chat id to filter on.
        date: ``YYYY-MM-DD``; matched against the record's ``ts`` prefix.

    Returns:
        Matching records in file order.  Empty when the file is absent.
        Rows that are blank, unparseable or not JSON objects are skipped.
    """
    path = Path(logs_dir) / _LOG_FILENAME
    if not path.exists():
        return []

    records: list[dict[str, Any]] = []
    # errors="replace" so a partially-flushed multibyte character cannot
    # raise out of the iterator itself, before json.loads ever sees it.
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue  # torn or corrupt line -- skip it, never raise
            if not isinstance(record, dict):
                continue
            if record.get("chat_id") != chat_id:
                continue
            if not str(record.get("ts", "")).startswith(date):
                continue
            records.append(record)
    return records
