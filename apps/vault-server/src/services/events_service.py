"""Merged event persistence — read/write/refresh data/events/{date}.json."""

import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.tracing_setup import fs_span

logger = logging.getLogger(__name__)

# Which upstream system produced an event, keyed by its source_ids entry.
# The `source` field cannot answer this: a calendar event fuzzy-matched to a
# timeline visit is stored as "merged", and create_event writes "manual".
_SOURCE_SYSTEM_BY_ID_KEY = {
    "calendar_id": "calendar",
    "visit_id": "timeline",
    "transit_id": "timeline",
    "note_line": "daily-note",
    "habit_slug": "habit",
}

# The only source systems whose absence from a fresh merge is real evidence
# that an event was deleted upstream — and therefore the only ones whose
# persisted events reconciliation may drop.
#
# Their ids come from the upstream system itself (Google's event id; a
# visit's start time and place_id), so the same event yields the same id on
# every merge, and a merge that does not emit it means it is genuinely gone.
#
# The excluded sources — `daily-note` and `habit` — derive their ids from
# user-editable text, so an unmatched persisted event is far more likely to
# mean "the text changed" or "something shadowed it" than "the user deleted
# it":
#   * `note_line` hashes the checkbox's date, section, text and time.
#     Correcting a typo re-hashes it, the old id matches nothing, and the
#     block (with any photo attached to it) was deleted.
#   * `habit_slug` blocks are suppressed by `MergerService`'s
#     calendar-attachment match: when a calendar event claims a habit, the
#     habit emits no standalone block at all. Its absence from the merge is
#     shadowing, not deletion — and `available_sources` cannot see the
#     difference, because the habit source *did* answer.
#
# Stale rows for these two linger until Ship 5 gives them stable identity.
# That is visible clutter; the alternative is silent loss.
_DELETABLE_SOURCE_SYSTEMS = frozenset({"calendar", "timeline"})

# The only fields a user can pin against re-inference.
#
# `completed` and `habit` are deliberately absent: `reconcile` re-derives
# both from checkbox and habit-log state on every merge, so a pinned value
# would be stale the instant the vault changed. `id`, `source_ids`, `state`,
# `photos` and `assets` are absent because they are already preserved by
# other means, and letting `user_set` reach them would turn a stray key into
# a way to rewrite reconciliation's own bookkeeping.
USER_SETTABLE_FIELDS = frozenset({
    "name", "start_time", "end_time", "location", "activity",
})


def is_complete(event: dict[str, Any]) -> bool:
    """Whether the event has enough to be drawn as a block.

    Derived, never stored: a status field that restates what the timestamps
    already say is a status field that goes stale, and the timestamps are
    right here.
    """
    return bool(event.get("start_time")) and bool(event.get("end_time"))


def apply_user_set(event: dict[str, Any]) -> None:
    """Re-apply the user's pinned fields over freshly merged values.

    Called at the end of `reconcile`'s matched branch, so the user gets the
    last word on the fields they set while every other field keeps tracking
    its source. Mutates in place.
    """
    pinned = event.get("user_set") or {}
    if not isinstance(pinned, dict):
        return

    moved_an_end = False
    for field, value in pinned.items():
        if field not in USER_SETTABLE_FIELDS:
            continue
        event[field] = value
        if field in ("start_time", "end_time"):
            moved_an_end = True

    if moved_an_end:
        start, end = event.get("start_time"), event.get("end_time")
        if start and end:
            try:
                from datetime import datetime as _dt
                delta = (_dt.fromisoformat(end) - _dt.fromisoformat(start)).total_seconds()
                event["duration_minutes"] = max(0, int(delta / 60))
            except (ValueError, TypeError):
                pass


def _date_part(timestamp: str | None) -> str | None:
    """The YYYY-MM-DD prefix of an ISO timestamp, or None if there isn't one.

    Returns None for a bare `HH:MM` and for anything that doesn't parse as a
    real date, so callers can fall back rather than inventing a file name out
    of a malformed string.
    """
    from datetime import date as _date

    if not isinstance(timestamp, str) or len(timestamp) < 10:
        return None
    head = timestamp[:10]
    try:
        _date.fromisoformat(head)
    except ValueError:
        return None
    return head


def _with_date(timestamp: str | None, new_date: str) -> str | None:
    """Re-date an ISO timestamp, keeping its time-of-day."""
    if not isinstance(timestamp, str):
        return timestamp
    if "T" in timestamp:
        return f"{new_date}T{timestamp.split('T', 1)[1]}"
    if _date_part(timestamp):
        return new_date
    # A bare time carries no date to replace; the caller normalizes those
    # against the target date before we ever see them.
    return timestamp


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

    @staticmethod
    def _normalize(event: dict[str, Any]) -> dict[str, Any]:
        """Migrate legacy keys on read. Files stay untouched until next save."""
        if "activity_category" in event and "activity" not in event:
            event["activity"] = event.pop("activity_category")
        event.setdefault("activity", None)
        event.setdefault("category", None)
        event.setdefault("tags", [])
        event.setdefault("state", "suggested")
        return event

    def get_events(self, date: str) -> list[dict[str, Any]]:
        """Read persisted events for a date. Returns [] if no file exists."""
        path = self._file_path(date)
        if not path.exists():
            return []
        try:
            return [self._normalize(e) for e in json.loads(path.read_text())]
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
            event.setdefault("activity", None)
            event.setdefault("category", None)
            event.setdefault("tags", [])
            event.setdefault("state", "suggested")
            event.setdefault("user_set", {})
        path = self._file_path(date)
        payload = json.dumps(events, indent=2)
        with fs_span("write", path, "events") as span:
            span.set_attribute("fs.bytes", len(payload.encode("utf-8")))
            path.write_text(payload)

    def create_event(
        self,
        date: str,
        name: str,
        start_time: str | None,
        end_time: str | None = None,
        location: dict | None = None,
        activity: str | None = None,
        photo_path: str | None = None,
        caption: str | None = None,
        wikilinks: list[str] | None = None,
        event_type: str | None = None,
        source_ids: dict | None = None,
        category: str | None = None,
        logical_id: str | None = None,
    ) -> dict:
        """Create a new event and persist it.

        `activity` is what the time was spent doing (walk, work, commute).
        `category` is a deprecated alias for it, kept for one release: it used
        to be the only name for this field, but an event now carries `activity`
        and `category` as two separate axes of the time matrix. `activity`
        wins when both are given. Populating the `category` facet is a
        separate job — this kwarg does not do it.
        """
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
            "activity": activity if activity is not None else category,
            "source": "photo" if photo_path else "manual",
            "source_ids": source_ids or {},
            "confidence": "medium",
            "photos": [],
            "assets": None,
            "tokens_earned": 0,
            "logical_id": logical_id,
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
        date: str | None,
        event_id: str,
        updates: dict,
        new_date: str | None = None,
        user_set_fields: list[str] | None = None,
        revert_fields: list[str] | None = None,
    ) -> dict:
        """Update fields on an existing event, relocating it when its day changes.

        `date` is a hint, exactly as in `attach_photo`: if it's omitted or the
        event isn't in that date's file, every event file is scanned for the ID
        (IDs are unique). Callers routinely know an event only by the ID
        `list_events` handed them, and defaulting the hint to today made every
        update to an event on any other day fail with "not found".

        `new_date` moves the event to another day, re-dating its start and end
        while keeping their times of day. It is also what a bare `HH:MM`
        update should already have been normalized against.

        The file an event lives in *is* the day it belongs to — `/day` and
        `list_events` both read `data/events/{date}.json` and nothing re-checks
        the timestamps inside. So an update that lands the event on another
        date moves its row to that date's file; leaving it behind would give
        the old day an event it no longer has and the new day nothing at all.
        """
        source_date = self.resolve_event_date(event_id, date)
        if source_date is None:
            return {"error": f"Event {event_id} not found"}
        # Copy: this function re-dates timestamps and writes duration into
        # the mapping, and doing that to the caller's dict is a side effect
        # on an argument.
        updates = dict(updates)
        events = self.get_events(source_date)

        for index, event in enumerate(events):
            if event["id"] != event_id:
                continue

            if new_date:
                # Re-date whichever timestamps this update leaves in place.
                # An explicit start_time/end_time in `updates` wins — the
                # caller normalized those against new_date already.
                for field in ("start_time", "end_time"):
                    if field not in updates:
                        moved = _with_date(event.get(field), new_date)
                        if moved is not None:
                            updates[field] = moved

            # Reject an interval that ends before it starts. This used to
            # persist silently: `day_coverage` drops such a span so the
            # numbers stayed right, but `/day` rendered `21:00–19:00` and
            # the block counted for nothing.
            start = updates.get("start_time", event.get("start_time"))
            end = updates.get("end_time", event.get("end_time"))
            if start and end:
                from datetime import datetime as _dt
                try:
                    if _dt.fromisoformat(end) < _dt.fromisoformat(start):
                        return {
                            "error": (
                                f"End {end} is before start {start} — refusing to "
                                "write an inverted interval"
                            )
                        }
                except (ValueError, TypeError):
                    pass

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

            # Provenance. Revert first, then pin: naming a field in both
            # reverts it and pins the new value, which is the only reading
            # under which a single call cannot contradict itself.
            pinned = dict(event.get("user_set") or {})
            for field in revert_fields or []:
                pinned.pop(field, None)
            for field in user_set_fields or []:
                if field in USER_SETTABLE_FIELDS and field in updates:
                    pinned[field] = updates[field]
            event["user_set"] = pinned

            target_date = _date_part(event.get("start_time")) or new_date or source_date
            if target_date == source_date:
                self.save_events(source_date, events)
                return {"updated": True, "event": event, "date": source_date}

            # Moved. Detach the upstream ids first: the event now sits on a
            # day its source never claimed it for, so `reconcile` at the
            # target date would find no fresh event matching those ids and —
            # for a calendar or timeline event, whose source answers and has
            # stable ids — delete it on the next read, silently undoing the
            # move. Keeping them under `moved_from_source_ids` preserves the
            # provenance without letting reconciliation act on it. What the
            # upstream system still holds is untouched; a caller that cares
            # (the agent's update_event tool) reports that separately.
            if event.get("source_ids"):
                event["moved_from_source_ids"] = event["source_ids"]
                event["source_ids"] = {}
            if event.get("source") not in ("manual", "photo"):
                event["source"] = "manual"

            events.pop(index)
            self.save_events(source_date, events)
            target_events = self.get_events(target_date)
            target_events.append(event)
            self.save_events(target_date, target_events)
            return {
                "updated": True,
                "event": event,
                "date": target_date,
                "moved_from": source_date,
            }

        return {"error": f"Event {event_id} not found"}

    def delete_event(self, date: str | None, event_id: str) -> dict:
        """Delete an event from the store. `date` is a hint, as in `update_event`.

        Returns the deleted event so the caller can report what actually went
        away — and can see, from its `source_ids`, whether the next merge will
        simply put it back.
        """
        source_date = self.resolve_event_date(event_id, date)
        if source_date is None:
            return {"error": f"Event {event_id} not found"}

        events = self.get_events(source_date)
        for index, event in enumerate(events):
            if event["id"] == event_id:
                events.pop(index)
                self.save_events(source_date, events)
                return {"deleted": True, "event": event, "date": source_date}

        return {"error": f"Event {event_id} not found"}

    def resolve_event_date(self, event_id: str, date: str | None = None) -> str | None:
        """The date file holding `event_id`, trusting `date` only if it's right.

        The hint is checked first (one file read for the common case), then
        every file is scanned. Returns None when no file holds the ID.
        """
        if date:
            if any(e.get("id") == event_id for e in self.get_events(date)):
                return date
        return self.find_event_date(event_id)

    def find_event_date(self, event_id: str) -> str | None:
        """Scan all persisted event files for an event ID; return its date (file stem).

        Event IDs are globally unique, so this lets callers locate an event
        without knowing which date's file it lives in.
        """
        for path in sorted(self.events_path.glob("*.json")):
            try:
                events = json.loads(path.read_text())
            except Exception:
                continue
            if any(e.get("id") == event_id for e in events):
                return path.stem
        return None

    def attach_photo(
        self,
        date: str | None,
        event_id: str,
        photo_path: str,
        caption: str | None = None,
        wikilinks: list[str] | None = None,
    ) -> dict:
        """Attach a photo to an existing event.

        `date` is a hint: if it's omitted or the event isn't in that date's
        file, all event files are scanned for the ID (IDs are unique). This
        keeps attachment robust when the caller doesn't know the event's date.
        """
        target_date = self.resolve_event_date(event_id, date)
        if target_date is None:
            return {"error": f"Event {event_id} not found"}
        events = self.get_events(target_date)

        for event in events:
            if event["id"] == event_id:
                event.setdefault("photos", [])
                event["photos"].append(
                    PhotoRef(path=photo_path, caption=caption, wikilinks=wikilinks or []).to_dict()
                )
                self.save_events(target_date, events)
                return {"attached": True, "event_id": event_id, "date": target_date}

        return {"error": f"Event {event_id} not found"}

    def auto_refresh(
        self,
        date: str,
        fresh_events: list[dict[str, Any]],
        available_sources: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Merge fresh events with persisted data and save.

        Alias for refresh_events — used by the unified GET /events endpoint.
        """
        return self.refresh_events(date, fresh_events, available_sources)

    def refresh_events(
        self,
        date: str,
        fresh_events: list[dict[str, Any]],
        available_sources: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """`reconcile`, then persist. See `reconcile` for the merge algorithm."""
        result = self.reconcile(date, fresh_events, available_sources)
        self.save_events(date, result)
        return result

    def reconcile(
        self,
        date: str,
        fresh_events: list[dict[str, Any]],
        available_sources: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Re-merge from sources while preserving manually-added data.

        Pure: reads persisted state but never writes it. `refresh_events`
        is this plus `save_events` — callers that only need the merged view
        for one moment (rendering `/daily` for a browsed date, say) use this
        directly so that navigating the calendar can never itself alter the
        store. A persisted event for a past date must not be silently
        rewritten just because someone looked at it.

        Algorithm:
        1. Match fresh events to existing events by source_ids
        2. Matched: update name/time/location/completed/habit from fresh
           (all re-derived from the vault every merge), keep
           photos/assets/id/state (user-set enrichment nothing upstream
           can regenerate)
        3. Unmatched fresh: add as new events
        4. Unmatched existing with source in ('manual', 'photo'): preserve as-is
        5. Unmatched existing from any other source: preserve unless its
           source system is in `available_sources` — an unmatched event
           should only be treated as "deleted upstream" when the source that
           would have produced it actually answered this call. A source that
           failed or was never configured looks identical to "returned
           nothing" unless the caller says otherwise, so `available_sources`
           being `None` (caller didn't say) preserves everything unmatched —
           the safe default. Losing an expired-token calendar refresh used to
           silently delete every persisted calendar event for the day.
           A source system must additionally be in
           `_DELETABLE_SOURCE_SYSTEMS`: answering is not enough when the
           source's ids come from user-editable text, because then an
           unmatched event usually means the text changed or another block
           shadowed it, and `available_sources` cannot see either.
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
                # Update from fresh source, keep persisted data. These
                # fields are re-derived from the vault on every merge —
                # `completed` and `habit` (streak/tokens_earned/etc.) are
                # never user-set on the persisted event, they're computed
                # from checkbox/habit-log state each time, so the fresh
                # value is always the current truth and the persisted one
                # is always stale the instant the vault changes. That is
                # the opposite of `photos`/`assets`/`state`, which are
                # enrichment nothing upstream can regenerate — those must
                # keep coming from `matched_existing`, never from `fresh`.
                matched_existing["name"] = fresh["name"]
                matched_existing["start_time"] = fresh["start_time"]
                matched_existing["end_time"] = fresh.get("end_time", matched_existing.get("end_time"))
                matched_existing["location"] = fresh.get("location", matched_existing.get("location"))
                matched_existing["source"] = fresh.get("source", matched_existing.get("source"))
                matched_existing["source_ids"] = fresh_source_ids
                matched_existing["completed"] = fresh.get("completed", False)
                matched_existing["habit"] = fresh.get("habit")
                # The user gets the last word. Everything above re-derives
                # from the source; this puts back the fields the user
                # explicitly set, and only those.
                apply_user_set(matched_existing)
                result.append(matched_existing)
            else:
                result.append(fresh)

        # Preserve manual/photo events that weren't matched
        result.extend(manual_events)

        # Whatever is left in existing_by_source had real source_ids but no
        # fresh event claimed it this round. That only means "deleted
        # upstream" if the source system that would have produced it actually
        # answered — otherwise it means the source failed or was never
        # configured, and dropping the event here would be indistinguishable
        # from the calendar genuinely emptying out. Dedup by id first: an
        # event with two source_ids keys (e.g. a merged calendar+timeline
        # entry) appears twice in existing_by_source's values.
        leftover_by_id: dict[str, dict] = {}
        for evt in existing_by_source.values():
            leftover_by_id[evt.get("id", id(evt))] = evt

        for evt in leftover_by_id.values():
            source_ids = evt.get("source_ids", {})
            its_systems = {
                _SOURCE_SYSTEM_BY_ID_KEY[key]
                for key, val in source_ids.items()
                if val and key in _SOURCE_SYSTEM_BY_ID_KEY
            }
            # Subset, not intersection: unreachable today (every event
            # carries exactly one source_ids key) but stays correct if an
            # event ever carries two — it should only be dropped once every
            # system that could have produced it has actually answered.
            # `its_systems` must also be non-empty: a source_ids key that
            # isn't in _SOURCE_SYSTEM_BY_ID_KEY (a future source type added
            # without a matching entry) leaves its_systems empty, and
            # `set() <= anything` is True — that would delete the event
            # unconditionally, including when available_sources is empty
            # because nothing answered. An unmapped key means we cannot
            # tell which source owns this event, so we keep it — the same
            # fail-safe direction as available_sources=None.
            #
            # `_DELETABLE_SOURCE_SYSTEMS` is the third gate: even a source
            # that answered may not have *stable* ids, and for those an
            # unmatched event means the text changed or something shadowed
            # it, not that it was deleted. Subset again, for the same
            # reason as above — an event carrying two keys is only
            # deletable when every system behind it is.
            if (
                available_sources is not None
                and its_systems
                and its_systems <= available_sources
                and its_systems <= _DELETABLE_SOURCE_SYSTEMS
            ):
                # The source that would have produced this answered this
                # round and didn't return it — genuinely gone upstream.
                continue
            result.append(evt)

        return result
