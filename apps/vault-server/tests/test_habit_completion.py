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
