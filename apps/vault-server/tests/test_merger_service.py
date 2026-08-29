from datetime import date

import pytest

from src.services.merger_service import MergerService, MergedEvent


@pytest.fixture
def calendar_events():
    """Sample calendar events as returned by /calendar/events."""
    return [
        {
            "id": "cal-1",
            "summary": "Gym — Holmes Place",
            "start": "2026-02-27T16:00:00+02:00",
            "end": "2026-02-27T17:30:00+02:00",
            "completed": False,
            "calendar": "Mazkir",
        },
        {
            "id": "cal-2",
            "summary": "Team standup",
            "start": "2026-02-27T10:00:00+02:00",
            "end": "2026-02-27T10:30:00+02:00",
            "completed": False,
            "calendar": "Work",
        },
    ]


@pytest.fixture
def timeline_data():
    """Sample timeline data as returned by TimelineService.get_day()."""
    return {
        "visits": [
            {
                "name": "Holmes Place Dizengoff",
                "address": "Dizengoff St 123, Tel Aviv",
                "lat": 32.1079,
                "lng": 34.6818,
                "place_id": "ChIJtest123",
                "start_time": "2026-02-27T16:05:00+02:00",
                "end_time": "2026-02-27T17:25:00+02:00",
                "duration_minutes": 80,
                "confidence": "high",
            },
            {
                "name": "Carmel Market",
                "lat": 32.0660,
                "lng": 34.7678,
                "place_id": "ChIJmarket",
                "start_time": "2026-02-27T18:30:00+02:00",
                "end_time": "2026-02-27T19:00:00+02:00",
                "duration_minutes": 30,
                "confidence": "medium",
            },
        ],
        "activities": [
            {
                "mode": "transit",
                "distance_meters": 2400,
                "duration_minutes": 12,
                "start_time": "2026-02-27T15:48:00+02:00",
                "end_time": "2026-02-27T16:00:00+02:00",
                "start_lat": 32.0800,
                "start_lng": 34.7800,
                "end_lat": 32.1079,
                "end_lng": 34.6818,
                "polyline": [[32.0800, 34.7800], [32.1079, 34.6818]],
                "confidence": "high",
            },
        ],
    }


@pytest.fixture
def habits_data():
    """Sample habits data as returned by /habits."""
    return [
        {
            "name": "gym",
            "completed_today": True,
            "streak": 15,
            "tokens_per_completion": 10,
        },
    ]


@pytest.fixture
def daily_data():
    """Sample daily data as returned by /daily."""
    return {
        "date": "2026-02-27",
        "tokens_earned": 10,
        "tokens_total": 250,
    }


class TestMergerService:
    def test_merge_calendar_with_timeline_match(
        self, calendar_events, timeline_data, habits_data, daily_data
    ):
        """Calendar gym event + timeline gym visit → single merged event."""
        merger = MergerService(timezone="Asia/Jerusalem")
        events = merger.merge(
            calendar_events=calendar_events,
            timeline_data=timeline_data,
            habits=habits_data,
            daily=daily_data,
        )

        # Find the gym event
        gym = next(e for e in events if "gym" in e.name.lower() or "holmes" in e.name.lower())
        assert gym.source == "merged"
        assert gym.location is not None
        assert gym.location["name"] == "Holmes Place Dizengoff"
        assert gym.location["lat"] == pytest.approx(32.1079, abs=0.001)

    def test_unmatched_calendar_event_preserved(
        self, calendar_events, timeline_data, habits_data, daily_data
    ):
        """Calendar event with no timeline match → kept as calendar-only."""
        merger = MergerService(timezone="Asia/Jerusalem")
        events = merger.merge(
            calendar_events=calendar_events,
            timeline_data=timeline_data,
            habits=habits_data,
            daily=daily_data,
        )

        standup = next(e for e in events if "standup" in e.name.lower())
        assert standup.source == "calendar"
        assert standup.location is None

    def test_unmatched_timeline_visit_becomes_unplanned_stop(
        self, calendar_events, timeline_data, habits_data, daily_data
    ):
        """Timeline visit with no calendar match → unplanned_stop."""
        merger = MergerService(timezone="Asia/Jerusalem")
        events = merger.merge(
            calendar_events=calendar_events,
            timeline_data=timeline_data,
            habits=habits_data,
            daily=daily_data,
        )

        market = next(e for e in events if "carmel" in e.name.lower())
        assert market.type == "unplanned_stop"
        assert market.source == "timeline"

    def test_transit_activity_becomes_route(
        self, calendar_events, timeline_data, habits_data, daily_data
    ):
        """Activity segments → transit events with route data."""
        merger = MergerService(timezone="Asia/Jerusalem")
        events = merger.merge(
            calendar_events=calendar_events,
            timeline_data=timeline_data,
            habits=habits_data,
            daily=daily_data,
        )

        transit = [e for e in events if e.type == "transit"]
        assert len(transit) >= 1
        assert transit[0].route_from is not None
        assert transit[0].route_from["mode"] == "transit"

    def test_habit_attached_to_matching_event(
        self, calendar_events, timeline_data, habits_data, daily_data
    ):
        """Gym habit → attached to gym calendar event."""
        merger = MergerService(timezone="Asia/Jerusalem")
        events = merger.merge(
            calendar_events=calendar_events,
            timeline_data=timeline_data,
            habits=habits_data,
            daily=daily_data,
        )

        gym = next(e for e in events if "gym" in e.name.lower() or "holmes" in e.name.lower())
        assert gym.habit is not None
        assert gym.habit["completed"] is True
        assert gym.habit["streak"] == 15

    def test_events_sorted_chronologically(
        self, calendar_events, timeline_data, habits_data, daily_data
    ):
        """All events sorted by start_time."""
        merger = MergerService(timezone="Asia/Jerusalem")
        events = merger.merge(
            calendar_events=calendar_events,
            timeline_data=timeline_data,
            habits=habits_data,
            daily=daily_data,
        )

        times = [e.start_time for e in events]
        assert times == sorted(times)

    def test_merged_event_serializes_to_dict(
        self, calendar_events, timeline_data, habits_data, daily_data
    ):
        """MergedEvent can be serialized to dict for JSON response."""
        merger = MergerService(timezone="Asia/Jerusalem")
        events = merger.merge(
            calendar_events=calendar_events,
            timeline_data=timeline_data,
            habits=habits_data,
            daily=daily_data,
        )

        for event in events:
            d = event.model_dump()
            assert "id" in d
            assert "name" in d
            assert "type" in d
            assert "start_time" in d


from src.services.events_service import EventsService


def _cal(id_="cal1", summary="Standup", start="2026-08-29T09:05", end="2026-08-29T10:00"):
    return {"id": id_, "summary": summary, "start": start, "end": end,
            "completed": False, "calendar": "Mazkir"}


def test_calendar_event_carries_its_calendar_id():
    m = MergerService()
    events = m.merge(calendar_events=[_cal()], timeline_data={"visits": [], "activities": []})
    assert events[0].source_ids == {"calendar_id": "cal1"}


def test_unplanned_stop_source_id_is_stable_for_the_same_visit():
    visit = {"name": "Xoho", "start_time": "2026-08-29T11:00", "end_time": "2026-08-29T12:00",
             "duration_minutes": 60, "lat": 32.07, "lng": 34.78, "place_id": "p123"}
    m = MergerService()
    a = m.merge(calendar_events=[], timeline_data={"visits": [visit], "activities": []})
    b = m.merge(calendar_events=[], timeline_data={"visits": [dict(visit)], "activities": []})
    assert a[0].source_ids == b[0].source_ids
    assert a[0].source_ids != {}


def test_merger_no_longer_guesses_an_activity():
    """CATEGORY_KEYWORDS targeted the single-facet model Phase 1 replaced.
    Blocks must arrive unclassified; Ship 6 fills `activity`."""
    m = MergerService()
    events = m.merge(
        calendar_events=[_cal(summary="Gym session")],
        timeline_data={"visits": [], "activities": []},
    )
    assert events[0].activity is None


def test_merged_event_survives_a_reopen_with_its_id_and_state(tmp_path):
    """Regression: without source_ids, refresh_events appends every fresh
    event as new and drops the persisted copy, so approval could never
    survive an open. Ship 5 depends on this holding."""
    m = MergerService()
    svc = EventsService(tmp_path)

    def fresh():
        return [e.model_dump() for e in m.merge(
            calendar_events=[_cal()], timeline_data={"visits": [], "activities": []},
        )]

    first = svc.refresh_events("2026-08-29", fresh())
    original_id = first[0]["id"]
    first[0]["state"] = "approved"
    first[0]["activity"] = "meetings"
    svc.save_events("2026-08-29", first)

    second = svc.refresh_events("2026-08-29", fresh())
    assert len(second) == 1
    assert second[0]["id"] == original_id
    assert second[0]["state"] == "approved"
    assert second[0]["activity"] == "meetings"


NOTE_WITH_TIMED = """\
## Tasks
- [ ] 14:00 — Visit dentist (60m)
- [ ] Order dog food (30m)

## Notes
- [x] 09:00 — Take meds (5m)
"""


def test_timed_checkboxes_become_blocks_from_any_section():
    m = MergerService()
    events = m.merge(
        calendar_events=[], timeline_data={"visits": [], "activities": []},
        daily_body=NOTE_WITH_TIMED, date="2026-08-29",
    )
    by_name = {e.name: e for e in events}
    assert set(by_name) == {"Visit dentist", "Take meds"}
    assert by_name["Visit dentist"].start_time == "2026-08-29T14:00"
    assert by_name["Visit dentist"].end_time == "2026-08-29T15:00"
    assert by_name["Visit dentist"].duration_minutes == 60
    assert by_name["Visit dentist"].source == "daily-note"


def test_untimed_checkbox_is_not_a_block():
    """An untimed todo has no interval. It stays a todo; Ship 5 places it."""
    m = MergerService()
    events = m.merge(
        calendar_events=[], timeline_data={"visits": [], "activities": []},
        daily_body="## Tasks\n- [ ] Order dog food (30m)\n", date="2026-08-29",
    )
    assert events == []


def test_timed_checkbox_without_a_duration_is_zero_length():
    m = MergerService()
    events = m.merge(
        calendar_events=[], timeline_data={"visits": [], "activities": []},
        daily_body="## Tasks\n- [ ] 14:00 — Standup\n", date="2026-08-29",
    )
    assert events[0].start_time == events[0].end_time == "2026-08-29T14:00"
    assert events[0].duration_minutes == 0


def test_note_block_source_id_is_stable_across_merges():
    m = MergerService()
    kw = dict(calendar_events=[], timeline_data={"visits": [], "activities": []},
              daily_body=NOTE_WITH_TIMED, date="2026-08-29")
    a = m.merge(**kw)
    b = m.merge(**kw)
    assert [e.source_ids for e in a] == [e.source_ids for e in b]
    assert all("note_line" in e.source_ids for e in a)


def test_note_block_records_completion():
    m = MergerService()
    events = m.merge(
        calendar_events=[], timeline_data={"visits": [], "activities": []},
        daily_body=NOTE_WITH_TIMED, date="2026-08-29",
    )
    by_name = {e.name: e for e in events}
    assert by_name["Take meds"].tokens_earned == 0
    assert by_name["Take meds"].habit is None


def test_a_block_crossing_midnight_is_clamped_to_the_day():
    """Storage splits at midnight. Wrapping the end time instead would put
    the end before the start, and the coverage builder would drop the block
    entirely."""
    m = MergerService()
    events = m.merge(
        calendar_events=[], timeline_data={"visits": [], "activities": []},
        daily_body="## Tasks\n- [ ] 23:30 — Sleep (60m)\n", date="2026-08-29",
    )
    assert events[0].start_time == "2026-08-29T23:30"
    assert events[0].end_time == "2026-08-29T23:59"
    assert events[0].end_time > events[0].start_time


def test_duplicate_checkboxes_get_distinct_ids():
    """The agent has produced duplicate todos in this vault before. Two
    identical lines must reconcile as two blocks, not silently collapse into
    one — the second would overwrite the first's persisted state."""
    m = MergerService()
    events = m.merge(
        calendar_events=[], timeline_data={"visits": [], "activities": []},
        daily_body="## Tasks\n- [ ] 14:00 — Standup\n- [ ] 14:00 — Standup\n",
        date="2026-08-29",
    )
    assert len(events) == 2
    ids = [e.source_ids["note_line"] for e in events]
    assert ids[0] != ids[1]


def test_the_same_text_in_two_sections_stays_distinct():
    m = MergerService()
    events = m.merge(
        calendar_events=[], timeline_data={"visits": [], "activities": []},
        daily_body="## Tasks\n- [ ] 14:00 — Standup\n\n## Notes\n- [ ] 14:00 — Standup\n",
        date="2026-08-29",
    )
    assert events[0].source_ids != events[1].source_ids


def test_inserting_an_unrelated_checkbox_does_not_shift_other_ids():
    """Scoping the occurrence counter to (section, text, time) is what buys
    this: a global counter would orphan every block below an insertion."""
    m = MergerService()
    kw = dict(calendar_events=[], timeline_data={"visits": [], "activities": []},
              date="2026-08-29")
    before = m.merge(daily_body="## Tasks\n- [ ] 14:00 — Standup\n", **kw)
    after = m.merge(
        daily_body="## Tasks\n- [ ] 09:00 — Earlier thing\n- [ ] 14:00 — Standup\n", **kw)
    standup_before = next(e for e in before if e.name == "Standup")
    standup_after = next(e for e in after if e.name == "Standup")
    assert standup_before.source_ids == standup_after.source_ids


def _habit(name="Dog Walk", scheduled_at="07:00", completed=False, duration=40,
           done_count=0, target=1):
    return {"name": name, "completed_today": completed, "streak": 3,
            "tokens_per_completion": 5, "scheduled_at": scheduled_at,
            "duration_minutes": duration, "completions_today": done_count,
            "daily_target": target}


def test_scheduled_habit_with_no_calendar_event_becomes_a_block():
    m = MergerService()
    events = m.merge(
        calendar_events=[], timeline_data={"visits": [], "activities": []},
        habits=[_habit()], date="2026-08-29",
    )
    assert len(events) == 1
    assert events[0].name == "Dog Walk"
    assert events[0].type == "habit"
    assert events[0].start_time == "2026-08-29T07:00"
    assert events[0].end_time == "2026-08-29T07:40"
    assert events[0].source_ids == {"habit_slug": "2026-08-29:dog-walk"}


def test_unscheduled_habit_is_not_a_block():
    m = MergerService()
    events = m.merge(
        calendar_events=[], timeline_data={"visits": [], "activities": []},
        habits=[_habit(scheduled_at=None)], date="2026-08-29",
    )
    assert events == []


def test_habit_already_attached_to_a_calendar_event_is_not_duplicated():
    """The existing name-match attaches habit data to the calendar event.
    Emitting a standalone block too would show the same thing twice."""
    m = MergerService()
    events = m.merge(
        calendar_events=[_cal(summary="Dog Walk", start="2026-08-29T07:00",
                              end="2026-08-29T07:40")],
        timeline_data={"visits": [], "activities": []},
        habits=[_habit()], date="2026-08-29",
    )
    assert len(events) == 1
    assert events[0].source == "calendar"
    assert events[0].habit["name"] == "Dog Walk"


def test_habit_block_carries_todays_progress():
    """Carried forward from Phase 1: the bot could only ever render a binary
    box because completions_today never reached it."""
    m = MergerService()
    events = m.merge(
        calendar_events=[], timeline_data={"visits": [], "activities": []},
        habits=[_habit(done_count=1, target=2)], date="2026-08-29",
    )
    assert events[0].habit["completions_today"] == 1
    assert events[0].habit["daily_target"] == 2


def test_completed_habit_block_carries_its_tokens():
    m = MergerService()
    events = m.merge(
        calendar_events=[], timeline_data={"visits": [], "activities": []},
        habits=[_habit(completed=True)], date="2026-08-29",
    )
    assert events[0].habit["completed"] is True
    assert events[0].tokens_earned == 5


def test_a_habit_crossing_midnight_is_clamped_to_the_day():
    """Same rule as _create_note_block: wrapping would put the end before the
    start and the coverage builder would drop the block entirely."""
    m = MergerService()
    events = m.merge(
        calendar_events=[], timeline_data={"visits": [], "activities": []},
        habits=[_habit(scheduled_at="23:30", duration=60)], date="2026-08-29",
    )
    assert events[0].start_time == "2026-08-29T23:30"
    assert events[0].end_time == "2026-08-29T23:59"
    assert events[0].end_time > events[0].start_time


def test_two_habits_sharing_a_name_do_not_cancel_each_other():
    """One is attached to a calendar event, the other is not. Keying the
    dedup set by display name made the unattached one disappear silently —
    the exact failure this task exists to remove."""
    m = MergerService()
    events = m.merge(
        calendar_events=[_cal(summary="Walk", start="2026-08-29T07:00",
                              end="2026-08-29T07:40")],
        timeline_data={"visits": [], "activities": []},
        habits=[_habit(name="Walk", scheduled_at="07:00"),
                _habit(name="Walk", scheduled_at="18:00")],
        date="2026-08-29",
    )
    assert len(events) == 2
    starts = sorted(e.start_time for e in events)
    assert starts == ["2026-08-29T07:00", "2026-08-29T18:00"]


def test_habits_slugifying_identically_get_distinct_ids():
    m = MergerService()
    events = m.merge(
        calendar_events=[], timeline_data={"visits": [], "activities": []},
        habits=[_habit(name="Dog Walk", scheduled_at="07:00"),
                _habit(name="Dog-Walk", scheduled_at="18:00")],
        date="2026-08-29",
    )
    ids = [e.source_ids["habit_slug"] for e in events]
    assert ids[0] != ids[1]


# --- habit attachment: whole-phrase, not incidental word overlap ------------
#
# Attachment is not cosmetic. An attached habit emits no standalone block,
# and reconciliation used to read that missing block as "deleted upstream"
# and destroy the persisted event, photos included.

def test_a_calendar_event_sharing_one_word_does_not_claim_a_habit():
    """Reproduces the whole-branch review's Critical 1 against the user's
    real habit names: a 'Design review' meeting claimed 'Review Email',
    and 'Walk to office' claimed 'Dog Walk'."""
    m = MergerService()
    habits = [_habit(name="Dog Walk", scheduled_at="07:00"),
              _habit(name="Review Email", scheduled_at="09:00"),
              _habit(name="Workout", scheduled_at="18:00")]
    for summary in ("Design review", "Walk to office", "Sprint planning"):
        events = m.merge(
            calendar_events=[_cal(summary=summary, start="2026-08-29T14:00",
                                  end="2026-08-29T15:00")],
            timeline_data={"visits": [], "activities": []},
            habits=habits, date="2026-08-29",
        )
        standalone = {e.name for e in events if e.source == "habit"}
        assert standalone == {"Dog Walk", "Review Email", "Workout"}, summary
        assert all(e.habit is None for e in events if e.source == "calendar")


def test_a_habit_calendar_event_still_claims_its_habit():
    """CalendarService.sync_habit writes the summary as `🎯 {name}`, so the
    habit name is a whole-phrase substring of the event name."""
    m = MergerService()
    events = m.merge(
        calendar_events=[_cal(summary="🎯 Dog Walk", start="2026-08-29T07:00",
                              end="2026-08-29T07:40")],
        timeline_data={"visits": [], "activities": []},
        habits=[_habit(name="Dog Walk")], date="2026-08-29",
    )
    assert len(events) == 1
    assert events[0].source == "calendar"
    assert events[0].habit["name"] == "Dog Walk"


def test_habit_matching_ignores_separator_punctuation():
    """`Dog-Walk` and `Dog Walk` are the same phrase; the containment test
    must not be defeated by whichever separator the user typed."""
    m = MergerService()
    events = m.merge(
        calendar_events=[_cal(summary="Dog-Walk — morning", start="2026-08-29T07:00",
                              end="2026-08-29T07:40")],
        timeline_data={"visits": [], "activities": []},
        habits=[_habit(name="Dog Walk")], date="2026-08-29",
    )
    assert len(events) == 1
    assert events[0].habit is not None


def test_an_empty_habit_name_never_matches():
    m = MergerService()
    events = m.merge(
        calendar_events=[_cal(summary="Standup")],
        timeline_data={"visits": [], "activities": []},
        habits=[_habit(name="", scheduled_at=None)], date="2026-08-29",
    )
    assert events[0].habit is None
