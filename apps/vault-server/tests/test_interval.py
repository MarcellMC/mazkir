"""Interval arithmetic — the sums the model used to do and got wrong."""

from src.services.interval import (
    crosses_midnight,
    derive_interval,
    normalize_time,
    split_at_midnight,
)

DATE = "2026-09-08"


class TestNormalizeTime:
    def test_bare_hhmm_gets_the_date(self):
        assert normalize_time("18:00", DATE) == "2026-09-08T18:00:00"

    def test_iso_timestamp_is_left_alone(self):
        assert normalize_time("2026-09-07T18:00:00", DATE) == "2026-09-07T18:00:00"

    def test_none_stays_none(self):
        assert normalize_time(None, DATE) is None


class TestDeriveInterval:
    def test_start_and_end_give_duration(self):
        r = derive_interval("18:00", "19:00", None, DATE)
        assert r["ok"] is True
        assert r["start_time"] == "2026-09-08T18:00:00"
        assert r["end_time"] == "2026-09-08T19:00:00"
        assert r["duration_minutes"] == 60

    def test_start_and_duration_give_end(self):
        r = derive_interval("18:00", None, 40, DATE)
        assert r["end_time"] == "2026-09-08T18:40:00"
        assert r["duration_minutes"] == 40

    def test_end_and_duration_give_start(self):
        """'Just got back from the 40-minute dog walk' — the utterance
        anchors the END, and the start is arithmetic the model should
        never be asked to do."""
        r = derive_interval(None, "16:40", 40, DATE)
        assert r["start_time"] == "2026-09-08T16:00:00"
        assert r["end_time"] == "2026-09-08T16:40:00"

    def test_all_three_consistent_is_accepted(self):
        r = derive_interval("18:00", "19:00", 60, DATE)
        assert r["ok"] is True
        assert r["duration_minutes"] == 60

    def test_all_three_inconsistent_is_rejected(self):
        """Never silently pick one. Two of the three are wrong and we do
        not know which."""
        r = derive_interval("18:00", "19:00", 90, DATE)
        assert r["ok"] is False
        assert "90" in r["error"] and "60" in r["error"]

    def test_only_start_is_incomplete_not_an_error(self):
        r = derive_interval("18:00", None, None, DATE)
        assert r["ok"] is True
        assert r["start_time"] == "2026-09-08T18:00:00"
        assert r["end_time"] is None
        assert r["duration_minutes"] is None

    def test_only_end_is_incomplete_not_an_error(self):
        r = derive_interval(None, "16:40", None, DATE)
        assert r["ok"] is True
        assert r["start_time"] is None
        assert r["end_time"] == "2026-09-08T16:40:00"

    def test_nothing_given_is_allowed(self):
        r = derive_interval(None, None, None, DATE)
        assert r["ok"] is True
        assert r["start_time"] is None and r["end_time"] is None

    def test_duration_alone_cannot_place_anything(self):
        r = derive_interval(None, None, 40, DATE)
        assert r["ok"] is True
        assert r["start_time"] is None and r["end_time"] is None
        assert r["duration_minutes"] == 40

    def test_zero_length_is_legal(self):
        r = derive_interval("18:00", "18:00", None, DATE)
        assert r["ok"] is True
        assert r["duration_minutes"] == 0

    def test_end_before_start_on_explicit_dates_is_rejected(self):
        """Two full timestamps in the wrong order is a contradiction, not
        a midnight crossing — the dates say so."""
        r = derive_interval("2026-09-08T19:00:00", "2026-09-08T18:00:00", None, DATE)
        assert r["ok"] is False

    def test_negative_duration_with_start_is_rejected(self):
        """A hallucinated negative duration is exactly the input this module
        exists to catch, not to launder into a reversed block."""
        r = derive_interval("18:00", None, -30, DATE)
        assert r["ok"] is False

    def test_negative_duration_with_end_is_rejected(self):
        """A hallucinated negative duration is exactly the input this module
        exists to catch, not to launder into a reversed block."""
        r = derive_interval(None, "18:00", -30, DATE)
        assert r["ok"] is False


class TestMidnight:
    def test_bare_times_in_reverse_order_cross_midnight(self):
        r = derive_interval("23:30", "07:15", None, DATE)
        assert r["ok"] is True
        assert r["start_time"] == "2026-09-08T23:30:00"
        assert r["end_time"] == "2026-09-09T07:15:00"
        assert r["duration_minutes"] == 465

    def test_crosses_midnight_detects_a_date_change(self):
        assert crosses_midnight("2026-09-08T23:30:00", "2026-09-09T07:15:00") is True
        assert crosses_midnight("2026-09-08T18:00:00", "2026-09-08T19:00:00") is False

    def test_split_produces_one_fragment_per_day(self):
        parts = split_at_midnight("2026-09-08T23:30:00", "2026-09-09T07:15:00")
        assert parts == [
            ("2026-09-08T23:30:00", "2026-09-08T23:59:59"),
            ("2026-09-09T00:00:00", "2026-09-09T07:15:00"),
        ]

    def test_split_handles_more_than_one_boundary(self):
        parts = split_at_midnight("2026-09-08T22:00:00", "2026-09-10T06:00:00")
        assert len(parts) == 3
        assert parts[0][0] == "2026-09-08T22:00:00"
        assert parts[1] == ("2026-09-09T00:00:00", "2026-09-09T23:59:59")
        assert parts[2][1] == "2026-09-10T06:00:00"

    def test_split_of_a_same_day_interval_is_one_fragment(self):
        parts = split_at_midnight("2026-09-08T18:00:00", "2026-09-08T19:00:00")
        assert parts == [("2026-09-08T18:00:00", "2026-09-08T19:00:00")]

    def test_split_ending_exactly_at_midnight_drops_phantom_fragment(self):
        """'Worked until midnight' is a plausible real input. The interval
        ends exactly at the next day's 00:00:00, which would naively produce
        a zero-length fragment on that day. A genuinely stated zero-length
        interval (18:00 → 18:00) does not cross midnight, so it never reaches
        this function — the drop is safe and cannot swallow a legitimate event."""
        parts = split_at_midnight("2026-09-08T22:00:00", "2026-09-09T00:00:00")
        assert parts == [("2026-09-08T22:00:00", "2026-09-08T23:59:59")]
