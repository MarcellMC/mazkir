# tests/test_fast_lane_habits.py
"""Spec §7.2: which habit a block is, ticking it once at the block's own time."""

import asyncio
import datetime as dt
from unittest.mock import MagicMock

from src.services.events_service import EventsService
from src.services.fast_lane.habits import (
    decline_suggestion, match_habit, suggest_habit, tick_if_habit,
)


def with_dog_walk(vault):
    vault.write_file("20-habits/dog-walk.md", {
        "type": "habit", "name": "Dog Walk", "status": "active", "streak": 2, "longest_streak": 4,
        "tokens_per_completion": 5, "daily_target": 2, "aliases": ["walked the dog"],
    }, "# Dog Walk\n")
    return vault.list_active_habits()


def test_match_habit_by_name_alias_and_fuzzy(vault_service):
    habits = with_dog_walk(vault_service)
    assert match_habit("dog walk", (), habits).kind == "exact"
    assert match_habit("Walked the dog", (), habits).kind == "alias"
    fuzzy = match_habit("walk", (), habits)
    assert fuzzy.kind == "fuzzy" and fuzzy.name == "Dog Walk"
    assert match_habit("Dentist", (), habits) is None


def test_a_fact_block_ticks_its_habit_once_at_the_blocks_own_time(vault_service, tmp_path):
    with_dog_walk(vault_service)
    events = EventsService(tmp_path / "events")
    e = events.create_event("2026-09-27", "Dog walk", "2026-09-27T23:15:00", "2026-09-27T23:35:00")
    now = dt.datetime(2026, 9, 28, 0, 30)
    done = tick_if_habit(vault_service, events, "2026-09-27", e["id"], now=now)
    assert done["name"] == "Dog Walk" and done["completed_at"] == "2026-09-27T23:35:00+03:00"
    assert (done["completions_today"], done["daily_target"], done["tokens_earned"]) == (1, 2, 5)
    assert tick_if_habit(vault_service, events, "2026-09-27", e["id"], now=now) is None
    assert events.get_events("2026-09-27")[0]["habit_completion"]["path"] == "20-habits/dog-walk.md"


def test_plans_proposals_the_future_and_the_habits_own_blocks_do_not_tick(vault_service, tmp_path):
    with_dog_walk(vault_service)
    events = EventsService(tmp_path / "events")
    now = dt.datetime(2026, 9, 28, 12, 0)
    blocks = [
        events.create_event("2026-09-28", "Dog walk", "2026-09-28T09:00:00", "2026-09-28T09:20:00",
                            fields={"intent": "plan"}),
        events.create_event("2026-09-28", "Dog walk", "2026-09-28T10:00:00", "2026-09-28T10:20:00",
                            proposed=True),
        events.create_event("2026-09-28", "Dog walk", "2026-09-28T18:00:00", "2026-09-28T18:20:00"),
        events.create_event("2026-09-28", "Dog walk", "2026-09-28T07:00:00", "2026-09-28T07:20:00",
                            source_ids={"habit_slug": "dog-walk"}),
    ]
    for b in blocks:
        assert tick_if_habit(vault_service, events, "2026-09-28", b["id"], now=now) is None


def test_a_fuzzy_match_is_left_for_a_tap(vault_service, tmp_path):
    with_dog_walk(vault_service)
    events = EventsService(tmp_path / "events")
    e = events.create_event("2026-09-27", "Walk", "2026-09-27T10:00:00", "2026-09-27T10:20:00")
    assert tick_if_habit(vault_service, events, "2026-09-27", e["id"], now=dt.datetime(2026, 9, 28)) is None


def test_the_post_hook_ticks_when_the_agent_creates_a_block(vault_service, tmp_path):
    from src.services.agent_service import AgentService
    with_dog_walk(vault_service)
    events = EventsService(tmp_path / "events")
    agent = AgentService(claude=MagicMock(), vault=vault_service, memory=MagicMock(),
                         media_path=tmp_path / "media", events=events)
    result = agent.run_tool("create_event", {"name": "Dog walk", "date": "2026-01-10",
                                             "start_time": "2026-01-10T08:00:00",
                                             "end_time": "2026-01-10T08:20:00"})
    assert result["ok"]
    assert events.get_events("2026-01-10")[0]["habit_completion"]["name"] == "Dog Walk"


def test_approving_a_plan_in_day_ticks_its_habit(vault_service, tmp_path, monkeypatch):
    import src.main as main
    from src.api.routes import events as events_route
    with_dog_walk(vault_service)
    events = EventsService(tmp_path / "events")
    e = events.create_event("2026-01-10", "Dog walk", "2026-01-10T08:00:00", "2026-01-10T08:20:00",
                            fields={"intent": "plan"})
    monkeypatch.setattr(main, "get_events", lambda: events)
    monkeypatch.setattr(main, "get_vault", lambda: vault_service)

    async def no_sources(date):
        return [], set()

    monkeypatch.setattr(events_route, "_merge_from_sources", no_sources)
    result = asyncio.run(events_route.set_event_state(
        dt.date(2026, 1, 10), e["id"], events_route.SetStateBody(state="approved")))
    assert result["habit"]["name"] == "Dog Walk"


def test_suggest_a_habit_after_three_days_then_stay_quiet(vault_service, tmp_path):
    habits = with_dog_walk(vault_service)
    events = EventsService(tmp_path / "events")
    for day in ("2026-09-20", "2026-09-24", "2026-09-28"):
        events.create_event(day, "Stretching", f"{day}T08:00:00", f"{day}T08:15:00")
    store = tmp_path / "suggestions.json"
    today = dt.date(2026, 9, 28)
    assert suggest_habit("Stretching", events, habits, today, store) == "Stretching"
    assert suggest_habit("Stretching", events, habits, today, store) is None       # shown this month
    assert suggest_habit("Dog walk", events, habits, today, store) is None         # already a habit
    # "not now" alone keeps it quiet, on a store where it was never shown
    fresh_store = tmp_path / "declined.json"
    decline_suggestion("Stretching", today, fresh_store)
    assert suggest_habit("Stretching", events, habits, today, fresh_store) is None
