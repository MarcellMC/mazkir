"""Messages waiting for the bot (trips spec §6.1).

They ride back on the next point's response. An item stays until the bot
acknowledges it, so a retried POST never sends a message twice; one served
3 times without an ack is dropped and logged, since the blocks are in `/day`
regardless.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

MAX_SERVES = 3
DONE_KEYS = 500


class Outbox:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._items: list[dict[str, Any]] = []
        self._done: list[str] = []         # keys already sent: never queued again
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                self._items, self._done = raw.get("items", []), raw.get("done_keys", [])
            except (OSError, ValueError):
                logger.exception("location outbox unreadable; starting empty")

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"items": self._items, "done_keys": self._done[-DONE_KEYS:]},
                                  ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def add(self, kind: str, receipt: dict[str, Any], trip_id: str | None, key: str | None = None) -> str | None:
        """Queue a message. With a `key`, one already queued or sent is not queued again (returns its id or None)."""
        item_id = uuid4().hex[:8]
        with self._lock:
            if key is not None:
                if key in self._done:
                    return None
                queued = next((i for i in self._items if i.get("key") == key), None)
                if queued is not None:
                    return queued["id"]
            self._items.append({"id": item_id, "kind": kind, "receipt": receipt, "trip_id": trip_id,
                                "served": 0, "key": key})
            self._persist()
        return item_id

    def serve(self) -> list[dict[str, Any]]:
        with self._lock:
            out, keep = [], []
            for item in self._items:
                if item["served"] >= MAX_SERVES:
                    # No content in the line: a receipt can name where you were.
                    logger.warning("location outbox dropped an unacknowledged %s item", item["kind"])
                    continue
                item["served"] += 1
                keep.append(item)
                out.append({"id": item["id"], "kind": item["kind"], "receipt": item["receipt"]})
            changed = len(keep) != len(self._items) or out
            self._items = keep
            if changed:
                self._persist()
            return out

    def ack(self, item_id: str) -> bool:
        with self._lock:
            acked = next((i for i in self._items if i["id"] == item_id), None)
            if acked is None:
                return False
            self._items = [i for i in self._items if i["id"] != item_id]
            if acked.get("key"):
                self._done.append(acked["key"])
            self._persist()
            return True

    def withdraw(self, key: str) -> bool:
        """Take back an unsent message that no longer applies (a question about a stop already left)."""
        with self._lock:
            before = len(self._items)
            self._items = [i for i in self._items if i.get("key") != key]
            if len(self._items) == before:
                return False
            self._done.append(key)
            self._persist()
            return True

    def remove(self, item_id: str | None) -> bool:
        """Take back an unsent message by id (a trip joined into another: its arrival is the other's now)."""
        with self._lock:
            before = len(self._items)
            self._items = [i for i in self._items if i["id"] != item_id]
            if len(self._items) == before:
                return False
            self._persist()
            return True

    def find(self, trip_id: str, kind: str) -> dict[str, Any] | None:
        with self._lock:
            return next((dict(i) for i in self._items if i["trip_id"] == trip_id and i["kind"] == kind), None)

    def update(self, item_id: str, receipt: dict[str, Any]) -> bool:
        with self._lock:
            for item in self._items:
                if item["id"] == item_id:
                    item["receipt"] = receipt
                    self._persist()
                    return True
            return False
