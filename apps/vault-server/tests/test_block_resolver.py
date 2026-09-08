"""Descriptive addressing: "the gym block", not `evt_7a8857a4`.

Mirrors `resolver.py`'s ladder deliberately — two resolvers that disagree
about what counts as ambiguous are two behaviours the user has to learn.
"""

from src.services.block_resolver import resolve_block


def block(id_, name, date="2026-09-08", start="2026-09-08T18:00:00"):
    return {"id": id_, "name": name, "date": date, "start_time": start}


class TestResolveBlock:
    def test_exact_id_wins(self):
        r = resolve_block("evt_1", [block("evt_1", "Gym"), block("evt_2", "Dinner")])
        assert r["ok"] is True
        assert r["data"]["id"] == "evt_1"
        assert r["data"]["score"] == 100.0

    def test_exact_name_wins(self):
        r = resolve_block("Gym", [block("evt_1", "Gym"), block("evt_2", "Dinner")])
        assert r["data"]["id"] == "evt_1"

    def test_unique_substring_matches(self):
        r = resolve_block("gym", [block("evt_1", "Gym session"), block("evt_2", "Dinner")])
        assert r["ok"] is True
        assert r["data"]["id"] == "evt_1"
        assert r["data"]["score"] == 95.0

    def test_multiple_substring_hits_are_ambiguous(self):
        r = resolve_block("walk", [
            block("evt_1", "Dog walk", start="2026-09-08T08:00:00"),
            block("evt_2", "Evening walk", start="2026-09-08T19:00:00"),
        ])
        assert r["ok"] is False
        assert r["error"]["code"] == "AMBIGUOUS_MATCH"
        assert len(r["error"]["details"]["candidates"]) == 2

    def test_candidates_carry_their_date(self):
        """Two days can both have a dog walk, and the reply has to be able
        to say which one it means."""
        r = resolve_block("dog walk", [
            block("evt_1", "Dog walk", date="2026-09-07"),
            block("evt_2", "Dog walk", date="2026-09-08"),
        ])
        assert r["ok"] is False
        dates = {c["date"] for c in r["error"]["details"]["candidates"]}
        assert dates == {"2026-09-07", "2026-09-08"}

    def test_fuzzy_match_above_the_floor(self):
        # "stand up" vs "Standup" scores 80.0; the floor is 60.0.
        # This tests real user input (typing "stand up" for "Standup").
        r = resolve_block("stand up", [block("evt_1", "Standup"), block("evt_2", "Lunch")])
        assert r["ok"] is True
        assert r["data"]["id"] == "evt_1"

    def test_below_the_floor_is_not_found(self):
        r = resolve_block("dentist", [block("evt_1", "Gym"), block("evt_2", "Lunch")])
        assert r["ok"] is False
        assert r["error"]["code"] == "PATH_NOT_FOUND"

    def test_empty_candidates_is_not_found(self):
        r = resolve_block("gym", [])
        assert r["ok"] is False
        assert r["error"]["code"] == "PATH_NOT_FOUND"

    def test_near_tie_is_ambiguous(self):
        r = resolve_block("review", [
            block("evt_1", "Review email"),
            block("evt_2", "Review notes"),
        ])
        assert r["ok"] is False
        assert r["error"]["code"] == "AMBIGUOUS_MATCH"
