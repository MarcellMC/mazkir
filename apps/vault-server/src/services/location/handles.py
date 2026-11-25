"""Per-chat handles for map places and anchors (spec §7).

The agent refers to a map place as ``m<n>`` and to a photo or a location message by its
anchor key (``photo:<file>`` / ``location:<message_id>``). Coordinates and OSM ids stay
here, server-side, so neither reaches a tool result or a prompt.

Numbering is per chat and only counts up: an expired entry's number is never reused while
the file lives, so an old ``m3`` cannot resolve to a new place.
"""

from __future__ import annotations

import datetime as dt
import threading
from pathlib import Path
from typing import Any, Callable

from src.services.location.runtime import _atomic_write, _read


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Handles:
    def __init__(
        self,
        path: Path,
        ttl: dt.timedelta = dt.timedelta(hours=24),
        now: Callable[[], dt.datetime] = _utc_now,
    ) -> None:
        self._path = path
        self._ttl = ttl
        self._now = now
        self._lock = threading.Lock()

    # --- public API -----------------------------------------------------------

    def place(
        self, chat_id: int, *, osm: str, label: str, kind: str, lat: float, lng: float
    ) -> str:
        """Register a map place for the chat and return its ``m<n>`` handle.

        The same ``osm`` in the same chat returns the same handle while it lives; registering
        again refreshes its lifetime.
        """
        with self._lock:
            data, now = self._load()
            chat = self._chat(data, chat_id)
            for handle, entry in chat["entries"].items():
                if entry.get("kind") == "map" and entry.get("osm") == osm:
                    entry.update(label=label, kind_of_place=kind, lat=lat, lng=lng, at=now.isoformat())
                    self._save(data)
                    return handle
            number = chat["next"] + 1
            chat["next"] = number
            handle = f"m{number}"
            chat["entries"][handle] = {
                "kind": "map",
                "osm": osm,
                "label": label,
                "kind_of_place": kind,
                "lat": lat,
                "lng": lng,
                "at": now.isoformat(),
            }
            self._save(data)
            return handle

    def anchor(
        self,
        chat_id: int,
        key: str,
        lat: float,
        lng: float,
        accuracy_m: float | None = None,
    ) -> str:
        """Register a photo or location anchor under ``key`` and return the key itself."""
        with self._lock:
            data, now = self._load()
            chat = self._chat(data, chat_id)
            entry: dict[str, Any] = {"kind": "anchor", "lat": lat, "lng": lng, "at": now.isoformat()}
            if accuracy_m is not None:
                entry["accuracy_m"] = accuracy_m
            chat["entries"][key] = entry
            self._save(data)
            return key

    def resolve(self, chat_id: int, handle: str) -> dict[str, Any] | None:
        """Return what a handle stands for, or ``None`` when unknown or expired."""
        with self._lock:
            data, now = self._load()
            entry = data.get("chats", {}).get(str(chat_id), {}).get("entries", {}).get(handle)
        if entry is None:
            return None
        if self._expired(entry, now):
            return None
        if entry.get("kind") == "map":
            return {
                "kind": "map",
                "osm": entry["osm"],
                "label": entry["label"],
                "lat": entry["lat"],
                "lng": entry["lng"],
            }
        out: dict[str, Any] = {"kind": "anchor", "lat": entry["lat"], "lng": entry["lng"]}
        if "accuracy_m" in entry:
            out["accuracy_m"] = entry["accuracy_m"]
        return out

    # --- storage --------------------------------------------------------------

    def _load(self) -> tuple[dict[str, Any], dt.datetime]:
        """Read the file and drop what has expired. Corrupt or missing reads as empty."""
        now = self._now()
        raw = _read(self._path, {})
        data: dict[str, Any] = raw if isinstance(raw, dict) else {}
        chats = data.get("chats")
        if not isinstance(chats, dict):
            chats = {}
        data["chats"] = chats
        for chat in chats.values():
            entries = chat.get("entries", {})
            chat["entries"] = {h: e for h, e in entries.items() if not self._expired(e, now)}
        return data, now

    def _save(self, data: dict[str, Any]) -> None:
        _atomic_write(self._path, data)

    @staticmethod
    def _chat(data: dict[str, Any], chat_id: int) -> dict[str, Any]:
        chat = data["chats"].setdefault(str(chat_id), {})
        chat.setdefault("next", 0)
        chat.setdefault("entries", {})
        return chat

    def _expired(self, entry: dict[str, Any], now: dt.datetime) -> bool:
        try:
            at = dt.datetime.fromisoformat(entry["at"])
        except (KeyError, TypeError, ValueError):
            return True
        return now - at > self._ttl
