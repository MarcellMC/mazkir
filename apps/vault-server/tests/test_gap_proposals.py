"""Gap proposals — spec §4.1."""

from src.services.gap_proposals import (
    HISTORY_DAYS, MIN_DAYS_SEEN, OVERLAP_FRACTION, SLEEP_CORE, propose_for_gap,
)


def blk(name, start, end, *, approved=True):
    """An event spanning `start`-`end` as "HH:MM" strings on an arbitrary day.
    `propose_for_gap` compares clock windows, so the date is irrelevant."""
    return {
        "name": name,
        "start_time": f"2026-09-01T{start}",
        "end_time": f"2026-09-01T{end}",
        "source": "manual" if approved else "calendar",
        "source_ids": {} if approved else {"calendar_id": "g1"},
    }


def day(*blocks):
    return list(blocks)


class TestHistory:
    def test_proposes_a_name_seen_on_three_days(self):
        history = [day(blk("Sleep", "00:20", "06:40")) for _ in range(3)]

        assert propose_for_gap(20, 400, history) == {"name": "Sleep", "days_seen": 3}

    def test_two_days_is_below_the_floor(self):
        """A midday gap deliberately: an overnight gap also satisfies the
        overnight rule, so it cannot isolate the history floor."""
        history = [day(blk("Lunch", "12:00", "13:00")) for _ in range(2)]

        assert propose_for_gap(720, 780, history) is None

    def test_counts_distinct_days_not_blocks(self):
        """Three blocks on one day is one day's evidence, not three.

        Each block clears the 30-minute overlap floor on its own, so all three
        reach the counting step: a regression that counted blocks instead of
        distinct days would wrongly hit MIN_DAYS_SEEN and propose "Lunch".
        The correct set-based count sees one day and returns None.
        """
        history = [day(
            blk("Lunch", "12:00", "12:45"),   # 45 min of the gap
            blk("Lunch", "12:15", "13:00"),   # 45 min
            blk("Lunch", "12:10", "12:50"),   # 40 min
        )]

        assert propose_for_gap(720, 780, history) is None

    def test_most_frequent_name_wins(self):
        history = [
            day(blk("Lunch", "12:00", "13:00")),
            day(blk("Lunch", "12:00", "13:00")),
            day(blk("Lunch", "12:00", "13:00")),
            day(blk("Errand", "12:00", "13:00")),
        ]

        assert propose_for_gap(720, 780, history) == {"name": "Lunch", "days_seen": 3}

    def test_overlap_below_half_the_gap_does_not_count(self):
        """A 20-minute coffee inside a two-hour hole is not evidence for what
        filled the hole."""
        history = [day(blk("Coffee", "12:00", "12:20")) for _ in range(5)]

        assert propose_for_gap(720, 840, history) is None

    def test_overlap_of_exactly_half_counts(self):
        """The threshold is "at least half", so the boundary is inclusive."""
        history = [day(blk("Nap", "12:00", "13:00")) for _ in range(3)]

        assert propose_for_gap(720, 840, history) == {"name": "Nap", "days_seen": 3}

    def test_pending_blocks_are_not_evidence(self):
        """Only approved blocks are history. An unconfirmed calendar entry is
        exactly the guess we are trying not to compound."""
        history = [day(blk("Standup", "12:00", "13:00", approved=False))
                   for _ in range(5)]

        assert propose_for_gap(720, 780, history) is None

    def test_dismissed_blocks_are_not_evidence(self):
        history = []
        for _ in range(5):
            b = blk("Standup", "12:00", "13:00")
            b["state"] = "dismissed"
            history.append(day(b))

        assert propose_for_gap(720, 780, history) is None

    def test_history_beats_the_overnight_rule(self):
        """An overnight gap where history says something else must follow
        history — the sleep rule is a cold-start seed, not an override."""
        history = [day(blk("Night shift", "00:00", "07:00")) for _ in range(4)]

        assert propose_for_gap(0, 420, history) == {"name": "Night shift", "days_seen": 4}

    def test_ignores_blocks_with_unusable_times(self):
        """Ten days, deliberately: at two the test sits below MIN_DAYS_SEEN and
        would pass whether or not the bad times were skipped, asserting nothing
        about the behaviour it names."""
        history = []
        for _ in range(5):
            history.append(day({"name": "Broken", "source": "manual",
                                "source_ids": {}}))
            history.append(day({"name": "Broken", "start_time": "nonsense",
                                "end_time": "also nonsense",
                                "source": "manual", "source_ids": {}}))

        assert propose_for_gap(720, 780, history) is None

    def test_only_the_first_HISTORY_DAYS_days_are_read(self):
        """A caller passing more than 14 must not get a proposal from day 20."""
        history = [day() for _ in range(HISTORY_DAYS)]
        history += [day(blk("Ancient", "12:00", "13:00")) for _ in range(5)]

        assert propose_for_gap(720, 780, history) is None

    def test_history_below_the_floor_falls_through_to_the_overnight_seed(self):
        """Two days of Sleep is not enough for the history step, but an
        overnight gap still gets the seed. Suppressing the proposal *because*
        there is a little evidence for it would be backwards."""
        history = [day(blk("Sleep", "00:20", "06:40")) for _ in range(2)]

        assert propose_for_gap(20, 400, history) == {"name": "Sleep", "days_seen": 0}

    def test_the_overnight_seed_survives_the_shape_the_route_passes(self):
        """`_load_history` always returns exactly HISTORY_DAYS lists, with []
        for a date that has no file — so a cold start arrives as fourteen
        empty lists, not as []. A truthiness check on `history` would make
        this rule unreachable in production while still passing
        test_fires_on_an_empty_store."""
        history = [[] for _ in range(HISTORY_DAYS)]

        assert propose_for_gap(20, 400, history) == {"name": "Sleep", "days_seen": 0}


class TestOvernightRule:
    def test_fires_on_an_empty_store(self):
        assert propose_for_gap(20, 400, []) == {"name": "Sleep", "days_seen": 0}

    def test_needs_the_whole_core_window(self):
        """A gap must fully contain 02:00-05:00. An evening hole is not sleep
        however long it is."""
        assert propose_for_gap(1080, 1380, []) is None      # 18:00-23:00
        assert propose_for_gap(120, 240, []) is None        # 02:00-04:00, partial
        assert propose_for_gap(180, 360, []) is None        # 03:00-06:00, partial

    def test_fires_on_exactly_the_core_window(self):
        assert propose_for_gap(120, 300, []) == {"name": "Sleep", "days_seen": 0}


class TestDegenerateInput:
    def test_a_zero_length_gap_proposes_nothing(self):
        assert propose_for_gap(720, 720, []) is None

    def test_an_inverted_gap_proposes_nothing(self):
        assert propose_for_gap(800, 700, []) is None


class TestConstants:
    def test_thresholds_are_the_spec_values(self):
        """These are stated constraints, not tuning knobs. If a test needs one
        changed, the test data is wrong — see Ship 4's R8, where an
        implementer lowered a fuzzy-match floor to make a bad test pass."""
        assert HISTORY_DAYS == 14
        assert MIN_DAYS_SEEN == 3
        assert OVERLAP_FRACTION == 0.5
        assert SLEEP_CORE == (120, 300)
