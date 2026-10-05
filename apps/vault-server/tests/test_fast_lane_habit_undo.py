"""Spec §9.3: a backdated tick credits its own day, and undo takes a tick back."""

import datetime as dt
from zoneinfo import ZoneInfo

from src.services.habit_completion import complete_habit, retract_completion

TZ = ZoneInfo("Asia/Jerusalem")
WORKOUT = "20-habits/workout.md"   # conftest: 15 tokens, streak 5, longest 8, last 2026-02-27


def test_a_backdated_completion_credits_the_note_of_its_own_day(vault_service):
    vault_service.write_daily_note("2026-09-27", "# 27\n")
    vault_service.write_daily_note("2026-09-28", "# 28\n")
    complete_habit(vault_service, WORKOUT, now=dt.datetime(2026, 9, 27, 23, 35, tzinfo=TZ))
    assert vault_service.read_daily_note("2026-09-27")["metadata"]["tokens_earned"] == 15
    assert "tokens_earned" not in vault_service.read_daily_note("2026-09-28")["metadata"]


def test_complete_habit_reports_what_undo_needs(vault_service):
    done = complete_habit(vault_service, WORKOUT, now=dt.datetime(2026, 9, 27, 23, 35, 12, 999, tzinfo=TZ))
    assert done["completed_at"] == "2026-09-27T23:35:12+03:00"
    assert done["prior"] == {"streak": 5, "longest_streak": 8, "last_completed": "2026-02-27"}
    assert done["completed_at"] in vault_service.read_file(WORKOUT)["content"]


def test_retracting_a_completion_restores_the_habit_and_the_tokens(vault_service):
    vault_service.write_daily_note("2026-09-27", "# 27\n")
    done = complete_habit(vault_service, WORKOUT, now=dt.datetime(2026, 9, 27, 23, 35, tzinfo=TZ))
    assert done["new_streak"] == 6
    assert retract_completion(vault_service, WORKOUT, done["completed_at"], done["prior"]) == {
        "ok": True, "tokens_retracted": 15}
    habit = vault_service.read_file(WORKOUT)
    assert habit["metadata"]["streak"] == 5 and habit["metadata"]["longest_streak"] == 8
    assert str(habit["metadata"]["last_completed"]) == "2026-02-27"
    assert done["completed_at"] not in habit["content"]
    assert vault_service.read_token_ledger()["metadata"]["total_tokens"] == 50
    assert vault_service.read_daily_note("2026-09-27")["metadata"]["tokens_earned"] == 0


def test_a_later_completion_blocks_the_retraction(vault_service):
    first = complete_habit(vault_service, WORKOUT, now=dt.datetime(2026, 9, 27, 8, 0, tzinfo=TZ))
    complete_habit(vault_service, WORKOUT, now=dt.datetime(2026, 9, 28, 8, 0, tzinfo=TZ))
    assert retract_completion(vault_service, WORKOUT, first["completed_at"], first["prior"]) == {
        "ok": False, "reason": "a later completion exists"}


def test_retracting_a_completion_that_is_not_there(vault_service):
    assert retract_completion(vault_service, WORKOUT, "2026-09-27T08:00:00+03:00",
                              {"streak": 5, "longest_streak": 8, "last_completed": "2026-02-27"}) == {
        "ok": False, "reason": "completion not found"}
