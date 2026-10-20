"""Spec §3.1: one message through the fast lane, end to end, with a fake parse."""

import datetime as dt
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import src.services.fast_lane.turn as turn_module
from src.services.events_service import EventsService
from src.services.fast_lane.context import FastContext
from src.services.fast_lane.contract import Clause, ParseResult, TimeWords
from src.services.fast_lane.parse import ParseFailure
from src.services.fast_lane.shadow import ShadowSettings
from src.services.fast_lane.turn import FastDeps, run_fast_turn

TZ = ZoneInfo("Asia/Jerusalem")
SETTINGS = ShadowSettings(model="m", timeout_s=1)


def setup(tmp_path, vault):
    from src.services.agent_service import AgentService
    events = EventsService(tmp_path / "events")
    memory = MagicMock()
    agent = AgentService(claude=MagicMock(), vault=vault, memory=memory, media_path=tmp_path / "media", events=events)
    deps = FastDeps(claude=None, run_tool=agent.run_tool, events=events, vault=vault, memory=memory,
                    actions_dir=tmp_path / "actions", places_path=tmp_path / "places.json",
                    suggestions_path=tmp_path / "suggestions.json")
    return deps, events, memory


def ctx(text, h=20, m=0, day=10):
    return FastContext(now=dt.datetime(2026, 1, day, h, m, tzinfo=TZ), chat_id=1, text=text)


def parse_to(*clauses, skill=None):
    return lambda ctx, claude, **kw: ParseResult(tuple(clauses), skill)


GYM = Clause("log_block", "record", True, "Gym 18:00-19:00", "Gym", time=TimeWords(start="18:00", end="19:00"))


def test_a_tracking_message_is_written_and_receipted(tmp_path, vault_service, monkeypatch):
    deps, events, memory = setup(tmp_path, vault_service)
    logged = []
    monkeypatch.setattr(turn_module, "emit_agent_turn", logged.append)
    fast = run_fast_turn(ctx("Gym 18:00-19:00"), deps, SETTINGS, message_id=5, parse=parse_to(GYM))
    assert fast.route == "fast" and not fast.repeat
    [line] = fast.receipt["lines"]
    assert (line["glyph"], line["when"], line["text"]) == ("✓", "18:00–19:00", "Gym")
    assert [e["name"] for e in events.get_events("2026-01-10")] == ["Gym"]
    assert (tmp_path / "actions" / f"{fast.turn['turn_id']}.json").exists()
    assert logged[0]["skill"] == "fast-lane" and logged[0]["tools"][0]["name"] == "create_event"
    memory.save_turn.assert_called_once_with(1, "Gym 18:00-19:00", fast.receipt["text"], [])
    assert fast.ran == ["✓ 18:00–19:00 Gym (block)"]


def test_a_repeat_returns_the_first_turn_and_writes_nothing(tmp_path, vault_service):
    deps, events, _ = setup(tmp_path, vault_service)
    first = run_fast_turn(ctx("Gym 18:00-19:00"), deps, SETTINGS, message_id=5, parse=parse_to(GYM))
    second = run_fast_turn(ctx("Gym 18:00-19:00"), deps, SETTINGS, message_id=5,
                           parse=lambda *a, **k: (_ for _ in ()).throw(AssertionError("parsed twice")))
    assert second.repeat and second.turn["turn_id"] == first.turn["turn_id"]
    assert len(events.get_events("2026-01-10")) == 1


def test_a_parse_failure_goes_to_the_router(tmp_path, vault_service):
    deps, events, _ = setup(tmp_path, vault_service)

    def failing(ctx, claude, **kw):
        raise ParseFailure("timeout")

    fast = run_fast_turn(ctx("Gym 18:00-19:00"), deps, SETTINGS, parse=failing)
    assert fast.route == "router_fallback" and fast.turn is None and events.get_events("2026-01-10") == []


def test_only_other_clauses_fall_through_to_the_parse_skill(tmp_path, vault_service):
    deps, _, _ = setup(tmp_path, vault_service)
    other = Clause("other", "record", True, "explain attention heads")
    fast = run_fast_turn(ctx("explain attention heads"), deps, SETTINGS,
                         parse=parse_to(other, skill="knowledge-management"))
    assert (fast.route, fast.fallthrough_skill, fast.lone_other, fast.turn) == (
        "fallthrough", "knowledge-management", True, None)


def test_stages_are_reported_in_plain_words(tmp_path, vault_service):
    deps, _, _ = setup(tmp_path, vault_service)
    stages = []
    run_fast_turn(ctx("Gym 18:00-19:00"), deps, SETTINGS, parse=parse_to(GYM), on_stage=stages.append)
    assert stages == ["Reading…", "Placing 1 thing…", "Writing…"]


def test_a_question_writes_nothing_and_asks_for_a_reply(tmp_path, vault_service):
    deps, events, _ = setup(tmp_path, vault_service)
    bar = Clause("log_block", "record", True, "Bar hopping", "Bar hopping")
    fast = run_fast_turn(ctx("Bar hopping", h=10), deps, SETTINGS, parse=parse_to(bar))
    [line] = fast.receipt["lines"]
    assert line["glyph"] == "?" and line["buttons"] == []
    assert fast.receipt["open_question"] == "Bar hopping · no time given. Reply with one."
    assert events.get_events("2026-01-10") == []


def test_an_edit_finds_its_block_in_the_replied_message(tmp_path, vault_service):
    deps, events, _ = setup(tmp_path, vault_service)
    gym = events.create_event("2026-01-10", "Gym", "2026-01-10T18:00:00", "2026-01-10T19:00:00")
    edit = Clause("end_block", "record", True, "it ended at 19:30", target="it", time=TimeWords(end="19:30"))
    context = FastContext(now=dt.datetime(2026, 1, 10, 20, 0, tzinfo=TZ), chat_id=1, text="it ended at 19:30",
                          reply_to="✓ 18:00–19:00 Gym")
    fast = run_fast_turn(context, deps, SETTINGS, parse=parse_to(edit))
    assert fast.receipt["lines"][0]["glyph"] == "✓"
    assert events.get_events("2026-01-10")[0]["end_time"] == "2026-01-10T19:30:00"
    assert events.get_events("2026-01-10")[0]["id"] == gym["id"]


def test_the_skill_catalog_reaches_the_context(tmp_path, vault_service, monkeypatch):
    deps, _, _ = setup(tmp_path, vault_service)
    deps.skills_dir = tmp_path / "skills"
    seen = {}
    real = turn_module.complete_fast_context

    def spy(snapshot, **kw):
        seen.update(kw)
        return real(snapshot, **kw)

    monkeypatch.setattr(turn_module, "complete_fast_context", spy)
    run_fast_turn(ctx("Gym 18:00-19:00"), deps, SETTINGS, parse=parse_to(GYM))
    assert seen["skills_dir"] == tmp_path / "skills"


def test_a_parse_failure_is_logged_at_error(tmp_path, vault_service, caplog):
    deps, _, _ = setup(tmp_path, vault_service)

    def failing(ctx, claude, **kw):
        raise ParseFailure("timeout")

    with caplog.at_level("ERROR", logger=turn_module.logger.name):
        run_fast_turn(ctx("Gym 18:00-19:00"), deps, SETTINGS, parse=failing)
    assert any(r.levelname == "ERROR" and getattr(r, "route", None) == "router_fallback" for r in caplog.records)


def test_a_block_left_open_days_ago_is_not_closed_by_todays_record(tmp_path, vault_service):
    deps, events, _ = setup(tmp_path, vault_service)
    stale = events.create_event("2026-01-05", "Gym", "2026-01-05T18:00:00")
    fast = run_fast_turn(ctx("Gym 18:00-19:00"), deps, SETTINGS, parse=parse_to(GYM))
    assert fast.route == "fast"
    assert [e["name"] for e in events.get_events("2026-01-10")] == ["Gym"]
    assert events.get_events("2026-01-05")[0]["id"] == stale["id"]
    assert events.get_events("2026-01-05")[0].get("end_time") is None
