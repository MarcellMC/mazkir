"""What time it is *where the user lives*.

Every date the agent writes and every date `/day` reads has to be the same
date, and the only way that holds is if both ask the same clock. The views
already did — `routes/daily.py`, `memory_service`, `vault_service` and
`merger_service` all resolve "now" against `VAULT_TIMEZONE`. The agent did
not: `datetime.now()` / `date.today()` read the *process* timezone, which in
a container is UTC unless someone remembered to set TZ.

Two failures come out of that split, and both were reported as "the event I
just made is not in /day":

  * A three-hour offset all day long. The system prompt said "Current
    date/time: 06:34" while the user's clock said 09:34, so `create_event`
    anchored on a "now" three hours in the past and the block landed three
    hours from where the user was living. It is drawn, but nowhere near the
    part of the timeline they are looking at.
  * A wrong *date* between 21:00 and midnight local, which is invisibility
    rather than misplacement: `dt.date.today()` still says yesterday, the
    event is written to yesterday's file, and `/day` — which resolves today
    in the vault timezone — renders a day that does not contain it.

Takes the timezone from `settings` rather than from a passed-in vault
service so that a handler with no vault to hand (and a test with a mocked
one) still gets the real answer.
"""

from __future__ import annotations

import datetime as _dt

import pytz

from src.config import settings


def vault_tz():
    """The configured vault timezone. Resolved per call, not at import, so a
    test that overrides `settings.vault_timezone` is actually honoured."""
    return pytz.timezone(settings.vault_timezone)


def vault_now() -> _dt.datetime:
    """Timezone-aware "now" on the user's wall clock."""
    return _dt.datetime.now(vault_tz())


def vault_today() -> _dt.date:
    """The date it is for the user, which is the date `/day` will open on."""
    return vault_now().date()


def vault_today_iso() -> str:
    """`vault_today()` as `YYYY-MM-DD` — the form every date argument takes."""
    return vault_today().isoformat()
