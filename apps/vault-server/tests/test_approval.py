"""resolve_state — spec §2.1, §2.3."""

from src.services.approval import is_approved, resolve_state


def ev(**kw):
    """An event with the keys resolve_state reads, all defaulted."""
    base = {"source": "merged", "source_ids": {}, "completed": False}
    base.update(kw)
    return base


class TestStoredWins:
    def test_stored_approved(self):
        assert resolve_state(ev(state="approved")) == "approved"

    def test_stored_dismissed(self):
        assert resolve_state(ev(state="dismissed")) == "dismissed"

    def test_stored_dismissed_beats_a_completed_habit(self):
        """An explicit dismissal is the user's word and outranks derivation."""
        e = ev(state="dismissed", source_ids={"habit_slug": "dog-walk"}, completed=True)
        assert resolve_state(e) == "dismissed"

    def test_a_bare_suggested_is_not_stored_state(self):
        """"suggested" is never written any more (§2.2). If an old row still
        carries it, it must be treated as absent and derived, not returned."""
        e = ev(state="suggested", source_ids={"habit_slug": "dog-walk"}, completed=True)
        assert resolve_state(e) == "approved"


class TestDerivedApproved:
    def test_manual_source(self):
        assert resolve_state(ev(source="manual")) == "approved"

    def test_photo_source(self):
        assert resolve_state(ev(source="photo")) == "approved"

    def test_ticked_habit(self):
        e = ev(source_ids={"habit_slug": "dog-walk"}, completed=True)
        assert resolve_state(e) == "approved"

    def test_checked_checkbox(self):
        e = ev(source_ids={"note_line": "abc123"}, completed=True)
        assert resolve_state(e) == "approved"


class TestDerivedPending:
    def test_unfired_habit(self):
        e = ev(source_ids={"habit_slug": "dog-walk"}, completed=False)
        assert resolve_state(e) == "pending"

    def test_unchecked_checkbox(self):
        e = ev(source_ids={"note_line": "abc123"}, completed=False)
        assert resolve_state(e) == "pending"

    def test_calendar_event(self):
        e = ev(source="calendar", source_ids={"calendar_id": "g1"})
        assert resolve_state(e) == "pending"

    def test_completed_calendar_event_is_still_pending(self):
        """THE case to get right. Google's green colour and a ✅ prefix both
        set `completed` (merger_service.py:279,297), but a calendar entry is
        machine-inferred intent — the source system decides, not `completed`."""
        e = ev(source="calendar", source_ids={"calendar_id": "g1"}, completed=True)
        assert resolve_state(e) == "pending"

    def test_timeline_visit(self):
        e = ev(source="timeline", source_ids={"visit_id": "v1"})
        assert resolve_state(e) == "pending"

    def test_completed_timeline_visit_is_still_pending(self):
        e = ev(source="timeline", source_ids={"visit_id": "v1"}, completed=True)
        assert resolve_state(e) == "pending"

    def test_transit(self):
        e = ev(source="timeline", source_ids={"transit_id": "t1"})
        assert resolve_state(e) == "pending"


class TestTolerance:
    def test_missing_keys_entirely(self):
        """A persisted row from before any of these fields existed."""
        assert resolve_state({}) == "pending"

    def test_source_ids_explicitly_none(self):
        """`.get` returns None for an explicit null, not the default."""
        assert resolve_state({"source_ids": None}) == "pending"

    def test_unknown_source_ids_key(self):
        assert resolve_state(ev(source_ids={"martian_id": "x"}, completed=True)) == "pending"

    def test_multi_key_event_with_one_human_source(self):
        """Ship 2 guarantees MergerService emits one key, but a persisted row
        can have accumulated more. Any human source is enough."""
        e = ev(source_ids={"calendar_id": "g1", "habit_slug": "dog-walk"}, completed=True)
        assert resolve_state(e) == "approved"


class TestIsApproved:
    def test_true_for_approved(self):
        assert is_approved(ev(state="approved")) is True

    def test_false_for_pending(self):
        assert is_approved(ev(source="calendar", source_ids={"calendar_id": "g1"})) is False

    def test_false_for_dismissed(self):
        assert is_approved(ev(state="dismissed")) is False
