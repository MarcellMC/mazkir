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


class TestPatchHabitCompletion:
    """PATCH /habits/{name} — the Telegram inline keyboard's completion path.

    It used to be an independent implementation: its own streak logic, its own
    token award, and a `last_completed == today` gate that refused the second
    dog walk and never wrote a Completion Log entry. It now shares one
    implementation with the agent's complete_habit tool.
    """

    def _patch(self, vault, calendar=None):
        from src.main import app

        with patch("src.api.routes.habits.get_vault", return_value=vault), \
                patch("src.api.routes.habits.get_calendar", return_value=calendar):
            resp = TestClient(app).patch("/habits/Dog Walk", json={"completed": True})
        assert resp.status_code == 200, resp.text
        return resp.json()

    def _vault(self, **kwargs):
        from tests.test_habit_completion import FakeVault, _habit
        return FakeVault(_habit(**kwargs))

    def test_second_completion_of_the_day_is_allowed(self):
        """Regression: tapping "complete" on the second dog walk was refused."""
        vault = self._vault(target=2)
        first = self._patch(vault)
        second = self._patch(vault)

        assert first["already_completed"] is False
        assert second["already_completed"] is False
        assert second["completions_today"] == 2

    def test_completion_beyond_the_target_is_refused(self):
        vault = self._vault(target=2)
        self._patch(vault)
        self._patch(vault)

        third = self._patch(vault)

        assert third["already_completed"] is True
        assert third["completions_today"] == 2
        assert third["daily_target"] == 2

    def test_each_completion_writes_a_log_entry(self):
        """An empty log left the agent path disagreeing about the same habit."""
        vault = self._vault(target=2)
        self._patch(vault)
        self._patch(vault)

        content = vault.files["20-habits/dog-walk.md"]["content"]
        assert content.count("\n- ") == 2

    def test_tokens_are_awarded_on_every_completion(self):
        vault = self._vault(target=2)
        first = self._patch(vault)
        second = self._patch(vault)

        assert first["tokens_earned"] == 5
        assert second["tokens_earned"] == 5
        assert vault.total_tokens == 10
        assert second["new_token_total"] == 10

    def test_streak_advances_only_when_the_target_is_met(self):
        vault = self._vault(target=2, streak=3)
        first = self._patch(vault)
        second = self._patch(vault)

        assert first["new_streak"] == 3
        assert first["target_met"] is False
        assert second["new_streak"] == 4
        assert second["target_met"] is True

    def test_pre_log_habit_completed_today_is_refused(self):
        """Transition-day backfill, same rule as the agent path."""
        vault = self._vault(target=2, last_completed=_today().isoformat())

        assert self._patch(vault)["already_completed"] is True

    def test_marks_the_calendar_event_complete(self):
        from unittest.mock import AsyncMock
        calendar = MagicMock(is_initialized=True)
        calendar.mark_event_complete = AsyncMock(return_value=True)
        vault = self._vault(target=2)

        result = self._patch(vault, calendar)

        calendar.mark_event_complete.assert_awaited_once()
        assert calendar.mark_event_complete.await_args[0][0] == "gcal_1"
        assert result["already_completed"] is False

    def test_a_broken_daily_target_does_not_lock_the_habit(self):
        vault = self._vault(target="two")

        result = self._patch(vault)

        assert result["already_completed"] is False
        assert result["daily_target"] == 1


def test_both_completion_paths_share_one_implementation():
    """The route and the agent tool must not drift apart again."""
    import inspect

    import src.main  # noqa: F401 — break circular import (main imports routes)
    from src.api.routes import habits as habits_route
    from src.services.agent_service import AgentService

    route_src = inspect.getsource(habits_route.complete_habit)
    tool_src = inspect.getsource(AgentService._tool_complete_habit)

    assert "habit_completion.complete_habit(" in route_src
    assert "complete_habit(self.vault" in tool_src
    # Neither may re-derive the rules locally: no second streak calculation,
    # no second reading of `last_completed`, no second log append.
    for src in (route_src, tool_src):
        assert "last_completed" not in src
        assert "append_completion" not in src
        assert "+ 1" not in src
