"""Tests for the shared habit-completion semantics."""

import datetime as dt

from src.services.habit_completion import completions_today, daily_target_of


class TestDailyTargetOf:
    def test_reads_the_configured_target(self):
        assert daily_target_of({"daily_target": 3}) == 3

    def test_defaults_to_one_when_absent(self):
        assert daily_target_of({}) == 1

    def test_defaults_to_one_when_null(self):
        assert daily_target_of({"daily_target": None}) == 1

    def test_a_negative_target_does_not_make_the_habit_uncompletable(self):
        """`0 >= -1` is true, so a hand-edited -1 refused every completion."""
        assert daily_target_of({"daily_target": -1}) == 1

    def test_a_zero_target_does_not_make_the_habit_uncompletable(self):
        assert daily_target_of({"daily_target": 0}) == 1

    def test_a_typo_does_not_raise(self):
        """`daily_target: two` is hand-edited YAML in a live vault."""
        assert daily_target_of({"daily_target": "two"}) == 1

    def test_a_numeric_string_still_counts(self):
        assert daily_target_of({"daily_target": "2"}) == 2

    def test_a_list_does_not_raise(self):
        assert daily_target_of({"daily_target": [2]}) == 1


class TestCompletionsToday:
    def test_counts_todays_log_entries(self):
        today = dt.date(2026, 8, 17)
        habit = {
            "metadata": {"daily_target": 2},
            "content": (
                "## Completion Log\n"
                "- 2026-08-16T07:00:00\n"
                "- 2026-08-17T07:00:00\n"
                "- 2026-08-17T19:00:00\n"
            ),
        }
        assert completions_today(habit, today) == 2

    def test_empty_log_is_zero(self):
        habit = {"metadata": {}, "content": "# Dog Walk\n"}
        assert completions_today(habit, dt.date(2026, 8, 17)) == 0

    def test_last_completed_today_backfills_a_full_day(self):
        """Pre-log habits carry only `last_completed`; treating that as zero
        would let them be completed a second time on the transition day."""
        habit = {
            "metadata": {"daily_target": 2, "last_completed": "2026-08-17"},
            "content": "# Dog Walk\n",
        }
        assert completions_today(habit, dt.date(2026, 8, 17)) == 2

    def test_backfill_retires_once_the_log_has_entries(self):
        habit = {
            "metadata": {"daily_target": 2, "last_completed": "2026-08-17"},
            "content": "## Completion Log\n- 2026-08-17T07:00:00\n",
        }
        assert completions_today(habit, dt.date(2026, 8, 17)) == 1

    def test_last_completed_on_another_day_does_not_backfill(self):
        habit = {
            "metadata": {"daily_target": 2, "last_completed": "2026-08-16"},
            "content": "# Dog Walk\n",
        }
        assert completions_today(habit, dt.date(2026, 8, 17)) == 0


class FakeVault:
    """Enough vault to exercise a real read-modify-write cycle."""

    def __init__(self, habit):
        self.files = {habit["path"]: habit}
        self.total_tokens = 0
        self.token_calls = []

    def read_file(self, path):
        import copy
        return copy.deepcopy(self.files[path])

    def write_file(self, path, metadata, content):
        self.files[path] = {"path": path, "metadata": metadata, "content": content}

    def update_tokens(self, tokens, activity):
        self.total_tokens += tokens
        self.token_calls.append((tokens, activity))
        return {"new_total": self.total_tokens}

    def list_active_habits(self):
        import copy
        return [copy.deepcopy(f) for f in self.files.values()]


def _habit(target=2, streak=3, log="", last_completed=None):
    return {
        "path": "20-habits/dog-walk.md",
        "metadata": {
            "type": "habit",
            "name": "Dog Walk",
            "status": "active",
            "daily_target": target,
            "streak": streak,
            "longest_streak": 5,
            "last_completed": last_completed,
            "tokens_per_completion": 5,
            "google_event_id": "gcal_1",
        },
        "content": f"# Dog Walk\n\n## Completion Log\n{log}",
    }


class TestCompleteHabit:
    def _run(self, vault, n=1):
        from src.services.habit_completion import complete_habit
        out = None
        for _ in range(n):
            out = complete_habit(vault, "20-habits/dog-walk.md")
        return out

    def test_first_of_two_does_not_advance_the_streak(self):
        vault = FakeVault(_habit(target=2))
        out = self._run(vault)

        assert out["already_completed"] is False
        assert out["completions_today"] == 1
        assert out["target_met"] is False
        assert out["new_streak"] == 3

    def test_second_of_two_advances_the_streak(self):
        vault = FakeVault(_habit(target=2))
        out = self._run(vault, n=2)

        assert out["completions_today"] == 2
        assert out["target_met"] is True
        assert out["new_streak"] == 4

    def test_tokens_are_awarded_on_every_completion(self):
        vault = FakeVault(_habit(target=2))
        self._run(vault, n=2)

        assert vault.total_tokens == 10
        assert len(vault.token_calls) == 2

    def test_completion_beyond_the_target_is_refused_and_writes_nothing(self):
        vault = FakeVault(_habit(target=2))
        self._run(vault, n=2)
        before = vault.files["20-habits/dog-walk.md"]["content"]

        out = self._run(vault)

        assert out["already_completed"] is True
        assert out["tokens_earned"] == 0
        assert vault.total_tokens == 10
        assert vault.files["20-habits/dog-walk.md"]["content"] == before

    def test_each_completion_appends_a_log_entry(self):
        vault = FakeVault(_habit(target=2))
        self._run(vault, n=2)

        content = vault.files["20-habits/dog-walk.md"]["content"]
        assert content.count("\n- ") == 2

    def test_last_completed_is_stamped_on_a_partial_completion(self):
        """This is why `last_completed == today` cannot mean "done"."""
        import datetime as dt
        vault = FakeVault(_habit(target=2))
        self._run(vault)

        meta = vault.files["20-habits/dog-walk.md"]["metadata"]
        assert meta["last_completed"] == dt.date.today().isoformat()

    def test_pre_log_habit_completed_today_is_refused(self):
        import datetime as dt
        vault = FakeVault(
            _habit(target=2, last_completed=dt.date.today().isoformat())
        )

        out = self._run(vault)

        assert out["already_completed"] is True

    def test_untouched_metadata_survives_the_write(self):
        vault = FakeVault(_habit(target=2))
        self._run(vault)

        meta = vault.files["20-habits/dog-walk.md"]["metadata"]
        assert meta["tokens_per_completion"] == 5
        assert meta["google_event_id"] == "gcal_1"
        assert meta["type"] == "habit"

    def test_reports_the_google_event_id_for_the_caller_to_sync(self):
        vault = FakeVault(_habit(target=2))
        assert self._run(vault)["google_event_id"] == "gcal_1"
