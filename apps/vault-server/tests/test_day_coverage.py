"""Coverage and gap arithmetic for a day's blocks."""

import pytest

from src.services.day_coverage import (
    Coverage,
    Gap,
    day_coverage,
    minutes_into_day,
)

DAY = 24 * 60


class TestMinutesIntoDay:
    def test_iso_timestamp_on_the_day(self):
        assert minutes_into_day("2026-08-29T09:05", "2026-08-29") == 545

    def test_bare_time_is_read_as_that_day(self):
        assert minutes_into_day("09:05", "2026-08-29") == 545

    def test_timestamp_on_another_day_returns_none(self):
        assert minutes_into_day("2026-08-28T09:05", "2026-08-29") is None

    def test_unparseable_returns_none(self):
        assert minutes_into_day("", "2026-08-29") is None
        assert minutes_into_day("garbage", "2026-08-29") is None


class TestMinutesIntoDayTimezones:
    def test_an_offset_timestamp_is_read_as_local_wall_clock(self):
        """Google Calendar returns RFC3339 with the calendar's offset, whose
        wall-clock reading is already local. 09:05+03:00 is 09:05 here."""
        assert minutes_into_day("2026-08-29T09:05:30+03:00", "2026-08-29") == 545

    @pytest.mark.parametrize("ts", [
        "2026-08-29T09:05Z",
        "2026-08-29T09:05:30Z",
    ])
    def test_a_utc_timestamp_is_rejected_rather_than_misplaced(self, ts):
        """09:05 UTC is 12:05 in this vault's timezone. Reading the wall clock
        off it would shift the block three hours earlier with no error. This
        module has no timezone knowledge, so it declines instead of guessing."""
        assert minutes_into_day(ts, "2026-08-29") is None


class TestDayCoverage:
    def test_the_worked_example_from_the_spec(self):
        """Friday, clock at 15:00, three blocks.
        covered 2.6h; unaccounted 12.4h across four gaps."""
        intervals = [(420, 460), (545, 600), (720, 780)]
        gaps, coverage = day_coverage(intervals, elapsed_minutes=900)
        assert coverage == Coverage(covered_minutes=155, unaccounted_minutes=745)
        assert gaps == [
            Gap("00:00", "07:00", 420),
            Gap("07:40", "09:05", 85),
            Gap("10:00", "12:00", 120),
            Gap("13:00", "15:00", 120),
        ]

    def test_a_fully_covered_day_has_no_gaps(self):
        gaps, coverage = day_coverage([(0, DAY)], elapsed_minutes=DAY)
        assert gaps == []
        assert coverage == Coverage(covered_minutes=DAY, unaccounted_minutes=0)

    def test_an_empty_day_is_one_gap(self):
        gaps, coverage = day_coverage([], elapsed_minutes=900)
        assert gaps == [Gap("00:00", "15:00", 900)]
        assert coverage == Coverage(covered_minutes=0, unaccounted_minutes=900)

    def test_a_future_day_has_no_gaps_and_no_coverage(self):
        """Nothing has elapsed, so nothing is unaccounted for."""
        gaps, coverage = day_coverage([(600, 660)], elapsed_minutes=0)
        assert gaps == []
        assert coverage == Coverage(covered_minutes=0, unaccounted_minutes=0)

    def test_overlapping_blocks_are_counted_once(self):
        """Eating while watching a video is one hour of the day, not two."""
        gaps, coverage = day_coverage([(600, 660), (630, 690)], elapsed_minutes=DAY)
        assert coverage.covered_minutes == 90

    def test_a_block_in_the_future_does_not_count_as_covered(self):
        """It has not happened. Counting it would let unaccounted go negative."""
        gaps, coverage = day_coverage([(600, 660), (1200, 1260)], elapsed_minutes=900)
        assert coverage.covered_minutes == 60
        assert coverage.unaccounted_minutes == 840

    def test_a_block_straddling_now_counts_only_its_elapsed_part(self):
        gaps, coverage = day_coverage([(840, 960)], elapsed_minutes=900)
        assert coverage.covered_minutes == 60
        assert gaps == [Gap("00:00", "14:00", 840)]

    def test_adjacent_blocks_produce_no_zero_length_gap(self):
        gaps, _ = day_coverage([(0, 600), (600, 900)], elapsed_minutes=900)
        assert gaps == []

    def test_blocks_arrive_in_any_order(self):
        gaps, coverage = day_coverage([(720, 780), (420, 460)], elapsed_minutes=900)
        assert coverage.covered_minutes == 100
        assert gaps[0] == Gap("00:00", "07:00", 420)

    def test_midnight_end_renders_as_24_00(self):
        """A gap running to the end of a past day ends at 24:00, not 00:00,
        which would read as a zero-length span."""
        gaps, _ = day_coverage([(0, 60)], elapsed_minutes=DAY)
        assert gaps == [Gap("01:00", "24:00", 1380)]

    def test_a_fully_contained_block_does_not_shrink_its_container(self):
        """A block nested inside another — the `max()` in the union is what
        prevents this from undercounting coverage and inventing a gap where the
        outer block continues."""
        gaps, coverage = day_coverage([(420, 480), (440, 460)], elapsed_minutes=900)
        assert coverage.covered_minutes == 60
        assert not any(g.start == "07:40" for g in gaps)
