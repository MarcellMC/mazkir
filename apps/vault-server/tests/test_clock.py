"""The agent and the day view must read the same clock.

Every date the agent writes is compared, sooner or later, against a date
`/day` computed — and `/day` has always resolved "today" in
`VAULT_TIMEZONE` while the agent used `datetime.now()` / `date.today()`,
which read the *process* timezone. On a server running as UTC that is a
three-hour offset all day (a block anchored on "now" lands three hours from
the day being lived) and a wrong date from 21:00 local until midnight (the
event is written to yesterday's file, and today's `/day` cannot show it).
"""

import datetime as dt

import pytest

from src.config import settings
from src.services.clock import vault_now, vault_today, vault_today_iso


# Two zones 25 hours apart, so their local dates *always* differ, whatever
# the process timezone is and whenever the suite happens to run.
FAR_EAST = "Pacific/Kiritimati"   # +14
FAR_WEST = "Pacific/Midway"       # -11


@pytest.fixture
def vault_timezone(monkeypatch):
    def _set(name: str) -> None:
        monkeypatch.setattr(settings, "vault_timezone", name)
    return _set


def test_today_follows_the_configured_zone(vault_timezone):
    vault_timezone(FAR_EAST)
    east = vault_today()
    vault_timezone(FAR_WEST)
    west = vault_today()

    assert east != west
    assert east - west == dt.timedelta(days=1)


def test_today_iso_is_the_date_argument_form(vault_timezone):
    vault_timezone("Asia/Jerusalem")
    assert vault_today_iso() == vault_today().isoformat()
    assert len(vault_today_iso()) == 10


def test_now_is_aware_and_reads_the_zone_per_call(vault_timezone):
    """Resolved per call, not captured at import — otherwise overriding the
    setting (a test, a reload) would be silently ignored."""
    vault_timezone("UTC")
    utc = vault_now()
    vault_timezone("Asia/Jerusalem")
    local = vault_now()

    assert utc.tzinfo is not None and local.tzinfo is not None
    # Same instant, different wall clocks: Jerusalem is 2 or 3 hours ahead of
    # UTC depending on the season, and never 0.
    assert local.utcoffset() != utc.utcoffset()
