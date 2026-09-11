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

from typing import Any

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


def resolve_state(event: dict[str, Any]) -> str:
    """"approved", "pending" or "dismissed".

    A stored value wins; anything else is derived from the source. Note that
    only "approved" and "dismissed" count as stored — a legacy `"suggested"`
    is treated as absent, because it was written by a `setdefault` that no
    longer exists and never expressed a decision (§2.2).
    """
    stored = event.get("state")
    if stored in _STORABLE:
        return stored

    if event.get("source") in _HUMAN_SOURCES:
        return "approved"

    # `or {}` rather than a `.get` default: a persisted row can carry an
    # explicit null here, and `.get`'s default only applies when the key is
    # absent entirely.
    source_ids = event.get("source_ids") or {}
    systems = {_SOURCE_SYSTEM_BY_ID_KEY.get(key) for key in source_ids}

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
