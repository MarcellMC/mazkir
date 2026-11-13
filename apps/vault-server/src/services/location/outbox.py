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


class Outbox:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._items: list[dict[str, Any]] = []
        if self.path.exists():
            try:
                self._items = json.loads(self.path.read_text(encoding="utf-8")).get("items", [])
            except (OSError, ValueError):
                logger.exception("location outbox unreadable; starting empty")

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"items": self._items}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def add(self, kind: str, receipt: dict[str, Any], trip_id: str | None) -> str:
        item_id = uuid4().hex[:8]
        with self._lock:
            self._items.append({"id": item_id, "kind": kind, "receipt": receipt, "trip_id": trip_id, "served": 0})
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
