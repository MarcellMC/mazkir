"""Unified events API — auto-merges from sources on read, persists enriched data."""

from datetime import date as date_type, datetime, time
from typing import Literal

import pytz
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.config import settings
from src.services.approval import resolve_state
from src.services.day_assembly import merge_from_sources as _merge_from_sources
from src.services.events_service import _SOURCE_SYSTEM_BY_ID_KEY
from src.services.habit_completion import complete_habit

router = APIRouter(prefix="/events", tags=["events"])


class PatchEventBody(BaseModel):
    photos: list[dict] | None = None
    assets: dict[str, str] | None = None
    name: str | None = None
    location: dict | None = None


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
async def patch_event(date: str, event_id: str, body: PatchEventBody):
    """Update a single persisted event."""
    from src.main import get_events as get_events_svc
    events_svc = get_events_svc()
    if not events_svc:
        raise HTTPException(503, "Events service not initialized")

    events = events_svc.get_events(date)
    for event in events:
        if event["id"] == event_id:
            updates = body.model_dump(exclude_none=True)
            event.update(updates)
            events_svc.save_events(date, events)
            return {"updated": event_id, "event": event}

    raise HTTPException(404, f"Event {event_id} not found")


def _source_systems(event: dict) -> set[str]:
    return {
        _SOURCE_SYSTEM_BY_ID_KEY.get(key)
        for key in (event.get("source_ids") or {})
    }


def _habit_path(vault, name: str) -> str | None:
    """The vault path of the active habit called `name`, case-insensitively."""
    wanted = name.strip().casefold()
    for habit in vault.list_active_habits():
        if (habit.get("metadata", {}).get("name") or "").strip().casefold() == wanted:
            return habit.get("path")
    return None


@router.post("/{date}/{event_id}/state")
async def set_event_state(date: str, event_id: str, body: SetStateBody):
    """Approve or dismiss one block (spec §2.3).

    Dispatches on the block's source system. Two branches write no `state` at
    all: ticking a habit or checking a checkbox makes `completed` true, and
    `resolve_state` then derives "approved" from the source on every later
    merge. Storing a state row as well would key an approval to an unstable
    `habit_slug`/`note_line` id — the stale-row trap §2.1 exists to avoid.
    """
    from src.main import get_events as get_events_svc, get_vault
    events_svc = get_events_svc()
    if not events_svc:
        raise HTTPException(503, "Events service not initialized")

    # The reconciled view, not the raw file: a habit- or note-derived block
    # often has no persisted row at all, because /daily reconciles without
    # saving. Resolving from the raw store would 404 on exactly the blocks
    # this route most needs to act on.
    fresh, available = await _merge_from_sources(date_type.fromisoformat(date))
    merged = events_svc.reconcile(date, fresh, available)

    event = next((e for e in merged if e.get("id") == event_id), None)
    if event is None:
        raise HTTPException(404, f"No event {event_id} on {date}")

    systems = _source_systems(event)
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
        stamp = datetime.combine(
            date_type.fromisoformat(date), time(12, 0),
            tzinfo=pytz.timezone(settings.vault_timezone),
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
    if body.state == "approved" and "daily-note" in systems and not event.get("completed"):
        from src.services.tool_handlers.daily import daily_set_task_state
        text = event.get("name") or ""
        result = daily_set_task_state(
            get_vault(), {"text": text, "state": "checked", "date": date}
        )
        if not result.get("ok"):
            error = result.get("error", {})
            raise HTTPException(
                404, error.get("message", f"Could not check task {text!r}")
            )
        return {
            "ok": True, "state": "approved", "event_id": event_id,
            "habit": None, "checkbox": {"text": text},
        }

    # --- already approved, nothing to write ------------------------------
    if body.state == "approved" and current == "approved":
        return {"ok": True, "state": "approved", "event_id": event_id,
                "habit": None, "checkbox": None}

    # --- store the state -------------------------------------------------
    # Persist the reconciled day so the row exists to carry the state. This
    # is the deliberate exception to "reads never persist": an explicit user
    # action may write, and Ship 4 drew the same line for _resolve_reference.
    for candidate in merged:
        if candidate.get("id") == event_id:
            candidate["state"] = body.state
    events_svc.save_events(date, merged)

    return {"ok": True, "state": body.state, "event_id": event_id,
            "habit": None, "checkbox": None}
