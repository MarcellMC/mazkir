"""Tests for /habits routes — daily_target-aware completion reporting."""
import datetime as dt
from unittest.mock import MagicMock, patch

import pytest
import pytz
from fastapi.testclient import TestClient

from src.config import settings

tz = pytz.timezone(settings.vault_timezone)


def _today() -> dt.date:
    """The route's idea of today — the vault timezone, not the server's."""
    return dt.datetime.now(tz).date()


def _habit(name="Dog Walk", *, target=2, log_times=(), last_completed=None, **meta):
    today = _today().isoformat()
    log = "".join(f"- {today}T{t}\n" for t in log_times)
    return {
        "path": f"20-habits/{name.lower().replace(' ', '-')}.md",
        "metadata": {
            "type": "habit",
            "name": name,
            "status": "active",
            "frequency": "daily",
            "streak": 3,
            "longest_streak": 5,
            "daily_target": target,
            "last_completed": last_completed,
            "tokens_per_completion": 5,
            **meta,
        },
        "content": f"# {name}\n\n## Completion Log\n{log}",
    }


@pytest.fixture
def client():
    # Lazy import: importing src.main at module level would initialize tracing
    # during pytest collection and leak a global TracerProvider into other tests.
    from src.main import app
    return TestClient(app)


def _get_habits(client, habits):
    vault = MagicMock()
    vault.list_active_habits.return_value = habits
    with patch("src.api.routes.habits.get_vault", return_value=vault):
        resp = client.get("/habits")
    assert resp.status_code == 200
    return resp.json()


class TestListHabitsCompletion:
    def test_partial_completion_is_not_completed(self, client):
        """Regression: `last_completed == today` read as done, but Task 7 sets
        it on partial completions too — one of two walks looked like two."""
        body = _get_habits(client, [_habit(
            target=2,
            log_times=["07:12:00"],
            last_completed=_today().isoformat(),
        )])[0]

        assert body["completions_today"] == 1
        assert body["daily_target"] == 2
        assert body["completed_today"] is False

    def test_meeting_the_target_is_completed(self, client):
        body = _get_habits(
            client, [_habit(target=2, log_times=["07:12:00", "19:40:00"])]
        )[0]

        assert body["completions_today"] == 2
        assert body["completed_today"] is True

    def test_untouched_habit_is_not_completed(self, client):
        body = _get_habits(client, [_habit(target=1)])[0]

        assert body["completions_today"] == 0
        assert body["completed_today"] is False

    def test_single_target_habit_completed_once_is_done(self, client):
        body = _get_habits(client, [_habit(target=1, log_times=["07:12:00"])])[0]

        assert body["completed_today"] is True

    def test_pre_log_habit_completed_today_is_done(self, client):
        """Transition day: the log is empty, only `last_completed` is set."""
        body = _get_habits(
            client, [_habit(target=2, last_completed=_today().isoformat())]
        )[0]

        assert body["completions_today"] == 2
        assert body["completed_today"] is True

    def test_a_broken_daily_target_defaults_to_one(self, client):
        body = _get_habits(client, [_habit(target=-1, log_times=["07:12:00"])])[0]

        assert body["daily_target"] == 1
        assert body["completed_today"] is True
