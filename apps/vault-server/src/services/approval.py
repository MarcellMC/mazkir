"""Whether a block counts — derived from its source, stored only when tapped.

Spec §2.1. Writing `state` on every confirmed block would persist rows keyed
by `note_line` and `habit_slug` ids, which are hashes of user-editable text.
`events_service.py`'s own comment says what happens then: the row matches
nothing on the next merge and lingers *beside* the freshly-inferred block, so
the same block renders twice.

The auto-approval rule makes that unnecessary rather than solving it. The
sources with unstable ids are exactly the human-created ones, and those
auto-approve — which needs no row at all, because a checked checkbox *is* the
approval. So the only rows we ever persist are calendar and timeline, whose
ids come from upstream and are stable across merges.

This module must never be imported by `events_service`: it imports from it.
"""

from __future__ import annotations

import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo

from src.config import settings
from src.services.events_service import _SOURCE_SYSTEM_BY_ID_KEY

# Source systems whose blocks a human action created, and which therefore
# need no tap. `daily-note` is a checkbox the user wrote; `habit` is one they
# ticked. Both are also the two whose ids are unstable — which is the whole
# reason this set and the persisted-state set are complements.
_HUMAN_SOURCE_SYSTEMS = frozenset({"habit", "daily-note"})

# `source` values that mean the user made this block directly, with no
# upstream to infer from: `create_event` writes "manual", photo attachment
# writes "photo".
_HUMAN_SOURCES = frozenset({"manual", "photo"})

_STORABLE = frozenset({"approved", "dismissed"})


def source_systems(event: dict[str, Any]) -> set[str]:
    """The source systems (`calendar`, `timeline`, `habit`, `daily-note`, …)
    an event's `source_ids` keys map to. Shared by `resolve_state` and by
    `api/routes/events.py`'s dispatch on `set_event_state`, which needs the
    same set to decide which branch owns an approve/dismiss.

    `or {}` rather than a `.get` default: a persisted row can carry an
    explicit null here, and `.get`'s default only applies when the key is
    absent entirely.
    """
    return {
        _SOURCE_SYSTEM_BY_ID_KEY.get(key)
        for key in (event.get("source_ids") or {})
    }


def has_begun(event: dict[str, Any], now: dt.datetime) -> bool:
    """Whether the block's start — or its end, when it has no start — is at or before `now`.

    Local wall clock on both sides, the ledger's convention: an offset on
    either value is dropped, not converted.
    """
    value = event.get("start_time") or event.get("end_time")
    if not value:
        return False
    try:
        moment = dt.datetime.fromisoformat(str(value))
    except ValueError:
        return False
    return moment.replace(tzinfo=None) <= now.replace(tzinfo=None)


def _local_now() -> dt.datetime:
    return dt.datetime.now(ZoneInfo(settings.vault_timezone)).replace(tzinfo=None)


def resolve_state(event: dict[str, Any], now: dt.datetime | None = None) -> str:
    """"approved", "pending" or "dismissed".

    A stored value wins; anything else is derived from the source. Note that
    only "approved" and "dismissed" count as stored — a legacy `"suggested"`
    is treated as absent, because it was written by a `setdefault` that no
    longer exists and never expressed a decision (§2.2).
    """
    stored = event.get("state")
    if stored in _STORABLE:
        return stored

    # A proposal is authored by Mazkir, not the user: asked to schedule things
    # "for later", it picked the times. `source` is still "manual", so without
    # this it would auto-approve and count as something the user said.
    if event.get("proposed"):
        return "pending"

    # Fast-lane spec §9.2: a plan is intent, as a calendar entry is. Once its
    # time has come it waits for you to say it happened; until then it is
    # simply ahead — `/day` draws it ◌, and coverage never reaches the future.
    # Confirmation (a matching record, or ✓) stores "approved", which wins above.
    if event.get("intent") == "plan":
        return "pending" if has_begun(event, now or _local_now()) else "approved"

    if event.get("source") in _HUMAN_SOURCES:
        return "approved"

    systems = source_systems(event)

    # `completed` is not sufficient on its own. A calendar entry carries it
    # too — merger_service.py:279,297 set it from Google's green colour or a
    # `✅` summary prefix — and a calendar entry is machine-inferred intent.
    # The source system decides; `completed` only qualifies a human one.
    if systems & _HUMAN_SOURCE_SYSTEMS and event.get("completed"):
        return "approved"

    return "pending"


def is_approved(event: dict[str, Any]) -> bool:
    """Whether this block counts toward `confirmed_minutes` (§3)."""
    return resolve_state(event) == "approved"
