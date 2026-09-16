"""Unified events API — auto-merges from sources on read, persists enriched data."""

import logging
from datetime import date as date_type, datetime, time
from typing import Literal

import pytz
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from src.config import settings
from src.services.approval import resolve_state, source_systems
from src.services.day_assembly import merge_from_sources as _merge_from_sources
from src.services.events_service import USER_SETTABLE_FIELDS, apply_user_set
from src.services.habit_completion import complete_habit

router = APIRouter(prefix="/events", tags=["events"])

logger = logging.getLogger(__name__)


def _rfc3339(timestamp: str | None) -> str | None:
    """Google's `dateTime` needs seconds; the bot's edit view sends `…THH:MM`."""
    if timestamp and len(timestamp) == 16:
        return f"{timestamp}:00"
    return timestamp


async def _push_edit_to_google(event: dict) -> dict:
    """Send a name/time edit to the Google entry this block mirrors.

    Without this, ✎ changed only Mazkir's copy, and Google kept the old times.
    Same guards as the agent's `update_event`: only Mazkir's own calendar is
    ours to change, and Google stores a cross-midnight span as one event where
    Mazkir keeps two fragments.
    """
    from src.main import get_calendar
    from src.services.events_service import is_complete
    from src.services.interval import crosses_midnight

    calendar_id = (event.get("source_ids") or {}).get("calendar_id")
    calendar = get_calendar()
    if not calendar_id:
        return {"ok": False, "attempted": False, "reason": "not_in_calendar"}
    if event.get("calendar") not in (None, "Mazkir"):
        return {"ok": False, "attempted": False, "reason": "not_in_mazkir_calendar"}
    if is_complete(event) and crosses_midnight(event["start_time"], event["end_time"]):
        return {"ok": False, "attempted": False, "reason": "crosses_midnight"}
    if not calendar or not getattr(calendar, "is_initialized", False):
        return {"ok": False, "attempted": False, "reason": "calendar_not_configured"}

    try:
        pushed = await calendar.update_event(
            event_id=calendar_id,
            name=event.get("name"),
            start_time=_rfc3339(event.get("start_time")),
            end_time=_rfc3339(event.get("end_time")),
        )
    except Exception as exc:
        logger.warning("Failed to push event edit to Google Calendar: %s", exc)
        pushed = False
    sync = {"ok": bool(pushed), "attempted": True, "event_id": calendar_id}
    if not pushed:
        sync["reason"] = "update_failed"
    return sync


async def _settle_proposal(event: dict, date_str: str) -> dict:
    """Give an approved proposal what `create_event` withheld from it.

    A proposal skips Google Calendar and `## Schedule` so a dismissed
    suggestion leaves nothing behind. Approval is the moment it becomes real,
    so both happen here — with the block's current times, which already carry
    any ✎ adjustment, since the edit view saves before it approves. A failed
    sync never blocks the approval; it is reported, as `create_event` does.
    """
    from src.main import get_calendar, get_vault
    from src.services.daily_schedule import append_schedule_entry
    from src.services.events_service import is_complete
    from src.services.interval import crosses_midnight

    start, end = event.get("start_time"), event.get("end_time")
    calendar = get_calendar()

    if not start:
        sync = {"ok": False, "attempted": False, "reason": "no_start_time"}
    elif is_complete(event) and crosses_midnight(start, end):
        sync = {"ok": False, "attempted": False, "reason": "crosses_midnight"}
    elif not calendar or not getattr(calendar, "is_initialized", False):
        sync = {"ok": False, "attempted": False, "reason": "calendar_not_configured"}
    else:
        sync = {"ok": False, "attempted": True, "reason": "no_event_created"}
        try:
            gcal_id = await calendar.create_event(
                name=event.get("name") or "",
                date=date_str,
                start_time=start[11:16],
                end_time=(end or "")[11:16] or None,
            )
            if gcal_id:
                event["source_ids"] = {**(event.get("source_ids") or {}), "calendar_id": gcal_id}
                sync = {"ok": True, "attempted": True, "event_id": gcal_id}
        except Exception as exc:
            logger.warning("Failed to sync approved proposal to Google Calendar: %s", exc)
            sync = {"ok": False, "attempted": True, "reason": str(exc)}

    if start and end:
        try:
            vault = get_vault()
            daily = vault.read_daily_note(date_str)
            vault.write_daily_note(date_str, append_schedule_entry(
                daily["content"], start[11:16], end[11:16], event.get("name") or "",
            ))
        except Exception as exc:
            logger.warning("Failed to write approved proposal to ## Schedule: %s", exc)

    return sync


class PatchEventBody(BaseModel):
    # `forbid`: the /day edit view sent start_time/end_time for months while
    # this model had no such fields, so pydantic dropped them, the route saved
    # the event unchanged, and the bot reported "✓ Saved". An unknown field is
    # now a 422 the bot's error toast can show.
    model_config = ConfigDict(extra="forbid")

    photos: list[dict] | None = None
    assets: dict[str, str] | None = None
    name: str | None = None
    location: dict | None = None
    start_time: str | None = None
    end_time: str | None = None
    activity: str | None = None


class SetStateBody(BaseModel):
    # `Literal`, so "suggested" is a 422 at the boundary rather than a stored
    # value nothing would ever read (spec §2.2).
    state: Literal["approved", "dismissed"]


def _events_payload(date: date_type, result: list[dict]) -> dict:
    return {
        "date": date.isoformat(),
        "events": result,
        "summary": {
            "total_events": len(result),
            "total_tokens": sum(e.get("tokens_earned", 0) for e in result),
        },
    }


@router.get("/{date}")
async def get_events(date: date_type):
    """Get events for a date — auto-merges from sources and persists."""
    from src.main import get_events as get_events_svc
    events_svc = get_events_svc()
    if not events_svc:
        raise HTTPException(503, "Events service not initialized")

    fresh, available_sources = await _merge_from_sources(date)
    result = events_svc.auto_refresh(date.isoformat(), fresh, available_sources)
    return _events_payload(date, result)


async def get_events_preview(date: date_type) -> dict:
    """Merge from sources and reconcile against persisted data, without
    persisting the result.

    `/daily` uses this instead of `get_events` so that browsing a date can
    never itself write `data/events/{date}.json` for it — a persisted event
    for a past date must not be silently rewritten just because someone
    looked at it.

    Ship 4 moved the agent's event tools onto the shared merge in
    `services/day_assembly.py`, so the old justification for `GET
    /events/{date}`'s persist — that `list_events` and `update_event` could
    only ever see the raw persisted file — no longer holds. What is true now:

    - Reads still never persist. This function, and everything reached
      through it, is `reconcile` (pure) and not `refresh_events`.
    - An *edit* does persist, deliberately and at one place:
      `AgentService._resolve_reference` calls `refresh_events` when
      materialising an inferred block so the reference the user just named
      has a row to update. Navigation must not write; an explicit edit must.
    - `GET /events/{date}` still persists by design. It is the explicit
      "bring this day up to date" call — the webapp and `POST
      .../refresh` both rely on it — and it is what gives a
      calendar/timeline/habit-derived event a stable ID for anything that
      addresses one by ID rather than by description.
    """
    from src.main import get_events as get_events_svc
    events_svc = get_events_svc()
    if not events_svc:
        raise HTTPException(503, "Events service not initialized")

    fresh, available_sources = await _merge_from_sources(date)
    result = events_svc.reconcile(date.isoformat(), fresh, available_sources)
    return _events_payload(date, result)


@router.post("/{date}/refresh")
async def refresh_events(date: date_type):
    """Force-refresh events from sources (same as GET, explicit intent)."""
    result = await get_events(date)
    result["refreshed"] = True
    return result


@router.patch("/{date}/{event_id}")
async def patch_event(date: date_type, event_id: str, body: PatchEventBody):
    """Update a single persisted event."""
    date_str = date.isoformat()
    from src.main import get_events as get_events_svc
    events_svc = get_events_svc()
    if not events_svc:
        raise HTTPException(503, "Events service not initialized")

    events = events_svc.get_events(date_str)
    for event in events:
        if event["id"] == event_id:
            updates = body.model_dump(exclude_none=True)
            event.update(updates)
            # Pin whatever the user just set, or the next reconcile overwrites
            # it from the source and the edit silently reverts. Ship 4 built
            # user_set for exactly this and wired it only into the agent's
            # update_event; this route was the recorded gap.
            #
            # Only the five USER_SETTABLE_FIELDS are pinnable: `photos` and
            # `assets` are preserved by other means, and letting a stray key
            # into user_set would turn it into a way to rewrite
            # reconciliation's own bookkeeping.
            pinned = event.setdefault("user_set", {})
            for field, value in updates.items():
                if field in USER_SETTABLE_FIELDS:
                    pinned[field] = value
            apply_user_set(event)
            events_svc.save_events(date_str, events)
            response = {"updated": event_id, "event": event}
            if updates.keys() & {"name", "start_time", "end_time"}:
                response["calendar_sync"] = await _push_edit_to_google(event)
            return response

    raise HTTPException(404, f"Event {event_id} not found")


# `source_ids` keys whose source rebuilds the block on every merge, so removing
# the row cannot make it go away.
_REGENERATING_KEYS = ("note_line", "habit_slug", "visit_id", "transit_id")


@router.delete("/{date}/{event_id}")
async def delete_event(date: date_type, event_id: str):
    """Delete one block, and its Google Calendar entry when it has one.

    Every refusal here exists so that a delete holds. A block rebuilt from a
    note checkbox, a habit or location history comes back on the next read;
    a Google-synced block removed only from the store is merged straight back
    in. Either would report success and then quietly undo itself, so they are
    refused with the reason instead, and nothing is written.
    """
    date_str = date.isoformat()
    from src.main import get_calendar, get_events as get_events_svc
    events_svc = get_events_svc()
    if not events_svc:
        raise HTTPException(503, "Events service not initialized")

    # The reconciled view, as in set_event_state: the block on screen may
    # have no persisted row yet.
    fresh, available = await _merge_from_sources(date)
    merged = events_svc.reconcile(date_str, fresh, available)

    event = next((e for e in merged if e.get("id") == event_id), None)
    if event is None:
        raise HTTPException(404, f"No event {event_id} on {date_str}")

    source_ids = event.get("source_ids") or {}
    if any(source_ids.get(key) for key in _REGENERATING_KEYS):
        raise HTTPException(
            409,
            "This block is rebuilt from a note checkbox, a habit or location "
            "history on every read, so deleting it would not hold. ✕ on the "
            "day view hides it.",
        )

    calendar_id = source_ids.get("calendar_id")
    if calendar_id and event.get("calendar") not in (None, "Mazkir"):
        raise HTTPException(
            409, f"This event lives in your {event['calendar']} calendar — delete it there.",
        )

    calendar_sync = {"ok": False, "attempted": False, "reason": "not_in_calendar"}
    if calendar_id:
        calendar = get_calendar()
        if not calendar or not getattr(calendar, "is_initialized", False):
            raise HTTPException(503, "Google Calendar is not reachable, so nothing was deleted.")
        try:
            deleted = await calendar.delete_event(calendar_id)
        except Exception as exc:
            logger.warning("Failed to delete event from Google Calendar: %s", exc)
            deleted = False
        if not deleted:
            raise HTTPException(502, "Google Calendar refused the delete, so nothing was deleted.")
        calendar_sync = {"ok": True, "attempted": True, "event_id": calendar_id}

    events_svc.save_events(date_str, [e for e in merged if e.get("id") != event_id])
    return {"ok": True, "deleted": event_id, "calendar_sync": calendar_sync}


def _habit_path(vault, name: str) -> str | None:
    """The vault path of the active habit called `name`, case-insensitively."""
    wanted = name.strip().casefold()
    for habit in vault.list_active_habits():
        if (habit.get("metadata", {}).get("name") or "").strip().casefold() == wanted:
            return habit.get("path")
    return None


@router.post("/{date}/{event_id}/state")
async def set_event_state(date: date_type, event_id: str, body: SetStateBody):
    """Approve or dismiss one block (spec §2.3).

    Dispatches on the block's source system. Two branches write no `state` at
    all: ticking a habit or checking a checkbox makes `completed` true, and
    `resolve_state` then derives "approved" from the source on every later
    merge. Storing a state row as well would key an approval to an unstable
    `habit_slug`/`note_line` id — the stale-row trap §2.1 exists to avoid.
    """
    date_str = date.isoformat()
    from src.main import get_events as get_events_svc, get_vault
    events_svc = get_events_svc()
    if not events_svc:
        raise HTTPException(503, "Events service not initialized")

    # The reconciled view, not the raw file: a habit- or note-derived block
    # often has no persisted row at all, because /daily reconciles without
    # saving. Resolving from the raw store would 404 on exactly the blocks
    # this route most needs to act on.
    fresh, available = await _merge_from_sources(date)
    merged = events_svc.reconcile(date_str, fresh, available)

    event = next((e for e in merged if e.get("id") == event_id), None)
    if event is None:
        raise HTTPException(404, f"No event {event_id} on {date_str}")

    systems = source_systems(event)
    current = resolve_state(event)

    # --- nothing in this ship reverses a human action --------------------
    if body.state == "dismissed" and current == "approved" and (
        systems & {"habit", "daily-note"}
    ):
        raise HTTPException(
            409,
            "This block is approved because you ticked it. Nothing in Mazkir "
            "unticks a habit or unchecks a checkbox yet — untick it in "
            "/habits or in the note.",
        )

    # --- approve a habit block by ticking the habit ----------------------
    if body.state == "approved" and "habit" in systems and not event.get("completed"):
        habit_name = (event.get("habit") or {}).get("name") or event.get("name") or ""
        vault = get_vault()
        path = _habit_path(vault, habit_name)
        if path is None:
            raise HTTPException(404, f"No active habit named {habit_name!r}")
        # The block's date, not today. Midday so a timezone conversion can
        # never roll it into a neighbouring day; complete_habit only reads
        # `.date()` off it.
        stamp = pytz.timezone(settings.vault_timezone).localize(
            datetime.combine(date, time(12, 0))
        )
        outcome = complete_habit(vault, path, now=stamp)
        return {
            "ok": True, "state": "approved", "event_id": event_id,
            "habit": {
                "name": outcome.get("name", habit_name),
                "tokens_earned": outcome.get("tokens_earned", 0),
                "new_streak": outcome.get("new_streak", 0),
            },
            "checkbox": None,
        }

    # --- approve a checkbox block by checking it -------------------------
    # Section-agnostic, via `set_todo_checked` — not `daily_set_task_state`,
    # which can only see and only write `## Tasks`. Since Ship 1,
    # `parse_all_todos` turns *any* section's checkbox into a block, so the
    # write path has to reach every checkbox the read path can see.
    if body.state == "approved" and "daily-note" in systems and not event.get("completed"):
        from src.services.daily_tasks import set_todo_checked
        vault = get_vault()
        text = event.get("name") or ""
        daily = vault.read_daily_note(date_str)
        new_body, reason = set_todo_checked(daily["content"], text, checked=True)
        if reason == "not_found":
            raise HTTPException(404, f"No checkbox matches {text!r} on {date_str}")
        if reason == "ambiguous":
            raise HTTPException(
                409,
                f"Multiple checkboxes match {text!r} on {date_str}; cannot tell "
                "which one to check.",
            )
        vault.write_daily_note(date_str, new_body)
        return {
            "ok": True, "state": "approved", "event_id": event_id,
            "habit": None, "checkbox": {"text": text},
        }

    # --- already approved, nothing to write ------------------------------
    if body.state == "approved" and current == "approved":
        return {"ok": True, "state": "approved", "event_id": event_id,
                "habit": None, "checkbox": None}

    # --- an approved proposal becomes real -------------------------------
    calendar_sync = None
    if (
        body.state == "approved"
        and event.get("proposed")
        and not (event.get("source_ids") or {}).get("calendar_id")
    ):
        calendar_sync = await _settle_proposal(event, date_str)

    # --- store the state -------------------------------------------------
    # Persist the reconciled day so the row exists to carry the state. This
    # is the deliberate exception to "reads never persist": an explicit user
    # action may write, and Ship 4 drew the same line for _resolve_reference.
    for candidate in merged:
        if candidate.get("id") == event_id:
            candidate["state"] = body.state
    events_svc.save_events(date_str, merged)

    response = {"ok": True, "state": body.state, "event_id": event_id,
                "habit": None, "checkbox": None}
    if calendar_sync is not None:
        response["calendar_sync"] = calendar_sync
    return response
