"""Merged event persistence — read/write/refresh data/events/{date}.json."""

import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


class PhotoRef:
    """Photo reference attached to an event."""

    def __init__(self, path: str, caption: str | None = None, wikilinks: list[str] | None = None):
        self.path = path
        self.caption = caption
        self.wikilinks = wikilinks or []

    def to_dict(self) -> dict:
        return {"path": self.path, "caption": self.caption, "wikilinks": self.wikilinks}


class EventsService:
    """Manages persisted merged events in JSON files."""

    def __init__(self, events_path: Path):
        self.events_path = Path(events_path)
        self.events_path.mkdir(parents=True, exist_ok=True)

    def _file_path(self, date: str) -> Path:
        return self.events_path / f"{date}.json"

    def get_events(self, date: str) -> list[dict[str, Any]]:
        """Read persisted events for a date. Returns [] if no file exists."""
        path = self._file_path(date)
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text())
        except Exception as e:
            logger.error(f"Failed to read events for {date}: {e}")
            return []

    def save_events(self, date: str, events: list[dict[str, Any]]) -> None:
        """Write events to disk. Assigns IDs to events that lack them."""
        for event in events:
            if "id" not in event:
                event["id"] = f"evt_{uuid4().hex[:8]}"
            event.setdefault("photos", [])
            event.setdefault("assets", None)
            event.setdefault("source_ids", {})
        self._file_path(date).write_text(json.dumps(events, indent=2))

    def create_event(
        self,
        date: str,
        name: str,
        start_time: str,
        end_time: str | None = None,
        location: dict | None = None,
        category: str | None = None,
        photo_path: str | None = None,
        caption: str | None = None,
        wikilinks: list[str] | None = None,
        event_type: str | None = None,
        source_ids: dict | None = None,
    ) -> dict:
        """Create a new event and persist it."""
        from datetime import datetime as _dt

        events = self.get_events(date)

        # Calculate duration from start/end times
        duration = 0
        if end_time and end_time != start_time:
            try:
                st = _dt.fromisoformat(start_time)
                et = _dt.fromisoformat(end_time)
                duration = max(0, int((et - st).total_seconds() / 60))
            except (ValueError, TypeError):
                duration = 0

        # Determine event type: explicit > photo-based > calendar
        if event_type:
            resolved_type = event_type
        elif photo_path:
            resolved_type = "unplanned_stop"
        else:
            resolved_type = "calendar"

        event: dict[str, Any] = {
            "id": f"evt_{uuid4().hex[:8]}",
            "name": name,
            "type": resolved_type,
            "start_time": start_time,
            "end_time": end_time or start_time,
            "duration_minutes": duration,
            "location": location,
            "activity_category": category,
            "source": "photo" if photo_path else "manual",
            "source_ids": source_ids or {},
            "confidence": "medium",
            "photos": [],
            "assets": None,
            "tokens_earned": 0,
        }

        if photo_path:
            event["photos"].append(
                PhotoRef(path=photo_path, caption=caption, wikilinks=wikilinks or []).to_dict()
            )

        events.append(event)
        self.save_events(date, events)
        return {"id": event["id"], "path": str(self._file_path(date))}

    def update_event(
        self,
        date: str,
        event_id: str,
        updates: dict,
    ) -> dict:
        """Update fields on an existing event."""
        events = self.get_events(date)
        for event in events:
            if event["id"] == event_id:
                # Recalculate duration if times changed
                start = updates.get("start_time", event.get("start_time"))
                end = updates.get("end_time", event.get("end_time"))
                if "start_time" in updates or "end_time" in updates:
                    if start and end and start != end:
                        from datetime import datetime as _dt
                        try:
                            st = _dt.fromisoformat(start)
                            et = _dt.fromisoformat(end)
                            updates["duration_minutes"] = max(0, int((et - st).total_seconds() / 60))
                        except (ValueError, TypeError):
                            pass

                event.update(updates)
                self.save_events(date, events)
                return {"updated": True, "event_id": event_id}

        return {"error": f"Event {event_id} not found"}

    def attach_photo(
        self,
        date: str,
        event_id: str,
        photo_path: str,
        caption: str | None = None,
        wikilinks: list[str] | None = None,
    ) -> dict:
        """Attach a photo to an existing event."""
        events = self.get_events(date)
        for event in events:
            if event["id"] == event_id:
                event.setdefault("photos", [])
                event["photos"].append(
                    PhotoRef(path=photo_path, caption=caption, wikilinks=wikilinks or []).to_dict()
                )
                self.save_events(date, events)
                return {"attached": True, "event_id": event_id}

        return {"error": f"Event {event_id} not found"}

    def auto_refresh(self, date: str, fresh_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Merge fresh events with persisted data and save.

        Alias for refresh_events — used by the unified GET /events endpoint.
        """
        return self.refresh_events(date, fresh_events)

    def refresh_events(self, date: str, fresh_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Re-merge from sources while preserving manually-added data.

        Algorithm:
        1. Match fresh events to existing events by source_ids
        2. Matched: update name/time/location from fresh, keep photos/assets/id
        3. Unmatched fresh: add as new events
        4. Unmatched existing with source in ('manual', 'photo'): preserve as-is
        """
        existing = self.get_events(date)
        existing_by_source: dict[str, dict] = {}
        manual_events: list[dict] = []

        for evt in existing:
            source_ids = evt.get("source_ids", {})
            matched = False
            for key, val in source_ids.items():
                if val:
                    existing_by_source[f"{key}:{val}"] = evt
                    matched = True
            if not matched and evt.get("source") in ("manual", "photo"):
                manual_events.append(evt)

        result: list[dict] = []
        for fresh in fresh_events:
            fresh_source_ids = fresh.get("source_ids", {})
            matched_existing = None

            for key, val in fresh_source_ids.items():
                lookup = f"{key}:{val}"
                if lookup in existing_by_source:
                    matched_existing = existing_by_source.pop(lookup)
                    break

            if matched_existing:
                # Update from fresh source, keep persisted data
                matched_existing["name"] = fresh["name"]
                matched_existing["start_time"] = fresh["start_time"]
                matched_existing["end_time"] = fresh.get("end_time", matched_existing.get("end_time"))
                matched_existing["location"] = fresh.get("location", matched_existing.get("location"))
                matched_existing["source"] = fresh.get("source", matched_existing.get("source"))
                matched_existing["source_ids"] = fresh_source_ids
                result.append(matched_existing)
            else:
                result.append(fresh)

        # Preserve manual/photo events that weren't matched
        result.extend(manual_events)

        self.save_events(date, result)
        return result
