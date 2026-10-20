"""Spec §7: which tool calls each clause becomes."""

import datetime as dt
from zoneinfo import ZoneInfo

from src.services.fast_lane.actions import PlanInputs, plan_turn
from src.services.fast_lane.contract import Clause, ParseResult, TimeWords
from src.services.fast_lane.places import Place
from src.services.fast_lane.time_resolver import ClauseResolution, Placement, logical_date

TZ = ZoneInfo("Asia/Jerusalem")
NOW = dt.datetime(2026, 9, 28, 0, 48, tzinfo=TZ)


def at(h, m, day=28):
    return dt.datetime(2026, 9, day, h, m, tzinfo=TZ)


def clause(op, **kw):
    return Clause(op=op, intent=kw.pop("intent", "record"), stated=kw.pop("stated", True),
                  evidence=kw.pop("evidence", "words"), **kw)


def placed(outcome, start, end, sp="exact", ep="exact", **kw):
    return ClauseResolution(outcome, Placement(start, end, sp, ep, logical_date(start or end, 5)), **kw)


def plan(clauses, resolutions, **kw):
    return plan_turn(ParseResult(tuple(clauses), None), resolutions, PlanInputs(now=NOW, message_id=7, **kw))


def block(id, name, start, end, **kw):
    return {"id": id, "name": name, "start_time": start, "end_time": end, "source": "manual",
            "date": (start or end)[:10], **kw}


def test_a_new_record_becomes_one_create_event_with_its_fields():
    c = clause("log_block", name="Dog walk", evidence="Dog walk 23:15-23:35", place="the park",
               project="Mazkir", tags=("dev",))
    [line] = plan([c], [placed("fact", at(23, 15, 27), at(23, 35, 27))],
                  places=[Place("park", "Park", ("the park",))])
    [step] = line.steps
    assert (line.kind, line.outcome, step.tool) == ("block", "fact", "create_event")
    assert step.params["date"] == "2026-09-27" and step.params["start_time"] == "2026-09-27T23:15:00"
    assert step.params["activity"] == "dev" and step.params["wikilinks"] == ["Mazkir"]
    assert step.params["location"] == {"name": "Park"}
    fast = step.params["_fast"]
    assert fast["defer_calendar_sync"] is True
    assert fast["fields"]["intent"] == "record" and fast["fields"]["logical_date"] == "2026-09-27"
    assert fast["fields"]["place_id"] == "park" and fast["fields"]["place_text"] is None
    assert fast["fields"]["evidence"] == {"text": "Dog walk 23:15-23:35", "message_id": 7}
    assert fast["fields"]["tags"] == ["dev"]


def test_an_unknown_place_is_kept_as_text_and_offered():
    [line] = plan([clause("log_block", name="Coffee", place="a new cafe")],
                  [placed("fact", at(0, 10), at(0, 40))])
    assert line.place_text == "a new cafe"
    assert line.steps[0].params["_fast"]["fields"]["place_text"] == "a new cafe"


def test_a_record_closes_the_open_block_of_its_activity():
    open_walk = block("w", "Dog walk", "2026-09-27T23:15:00", None)
    [line] = plan([clause("log_block", name="Dog walk")], [placed("fact", at(23, 15, 27), at(23, 35, 27))],
                  candidates=[open_walk])
    [step] = line.steps
    assert (line.kind, step.tool) == ("edit", "update_event")
    assert step.params["event_id"] == "w" and step.params["end_time"] == "2026-09-27T23:35:00"
    assert "start_time" not in step.params


def test_a_record_confirms_its_plan():
    gym = block("g", "Gym", "2026-09-27T18:00:00", "2026-09-27T19:00:00", intent="plan")
    [line] = plan([clause("log_block", name="Gym")], [placed("fact", at(18, 15, 27), at(19, 20, 27))],
                  candidates=[gym])
    params = line.steps[0].params
    assert params["_fast"]["state"] == "approved" and params["_fast"]["fields"]["intent"] == "record"
    assert params["start_time"] == "2026-09-27T18:15:00" and params["end_time"] == "2026-09-27T19:20:00"


def test_a_record_after_an_open_other_block_offers_to_close_it():
    work = block("k", "Work", "2026-09-27T20:00:00", None)
    lines = plan([clause("log_block", name="Dinner")], [placed("fact", at(21, 0, 27), at(21, 30, 27))],
                 candidates=[work])
    assert [l.kind for l in lines] == ["block", "propose"]
    [pending] = lines[1].pending
    assert pending.params == {"event_id": "k", "date": "2026-09-27", "end_time": "2026-09-27T21:00:00",
                              "_fast": {"defer_calendar_sync": True, "fields": {"end_precision": "inferred"}}}


def test_proposals_are_written_as_proposed_and_sleep_overlaps_become_proposals():
    sleep = block("s", "Sleep", "2026-09-28T01:00:00", "2026-09-28T09:00:00")
    lines = plan([clause("log_block", name="Nap", stated=False), clause("log_block", name="Reading")],
                 [placed("proposal", at(0, 10), at(0, 30), reason="mentioned in passing"),
                  placed("fact", at(3, 0), at(3, 30))],
                 candidates=[sleep])
    assert [l.outcome for l in lines] == ["proposal", "proposal"]
    assert all(l.steps[0].params["proposed"] is True for l in lines)
    assert lines[1].reason == "overlaps Sleep"


def test_a_plan_is_created_with_plan_intent():
    [line] = plan([clause("log_block", name="Gym", intent="plan")], [placed("plan", at(18, 0), at(19, 0))])
    assert line.outcome == "plan" and line.steps[0].params["_fast"]["fields"]["intent"] == "plan"
    assert "proposed" not in line.steps[0].params


def test_an_edit_updates_only_what_changed_and_asks_without_a_target():
    gym = block("g", "Gym", "2026-09-27T18:00:00", "2026-09-27T19:00:00")
    moved = placed("fact", at(18, 0, 27), at(19, 30, 27), sp=None, ep="exact")
    lines = plan([clause("edit_block", target="the gym"), clause("edit_block", target="the run")],
                 [moved, ClauseResolution("question", reason="which block?")], targets={0: gym})
    assert lines[0].steps[0].params == {"event_id": "g", "date": "2026-09-27", "end_time": "2026-09-27T19:30:00",
                                        "_fast": {"defer_calendar_sync": True, "fields": {"end_precision": "exact"}}}
    assert (lines[1].kind, lines[1].reason) == ("question", "which block?")


def test_habits_and_todos():
    tomorrow = ClauseResolution("fact", Placement(None, None, None, None, dt.date(2026, 9, 29)))
    lines = plan(
        [clause("tick_habit", name="stretching"), clause("add_todo", name="Buy milk", tags=("buy",)),
         clause("check_todo", target="call the plumber"), clause("rollover_todos"),
         clause("other", evidence="and how are you")],
        [ClauseResolution("fact"), tomorrow, ClauseResolution("fact"), ClauseResolution("fact"), None],
    )
    assert [(l.kind, l.steps[0].tool) for l in lines] == [
        ("habit", "complete_habit"), ("todo", "daily_add_task"), ("todo", "daily_check_todo"),
        ("rollover", "daily_rollover")]
    assert lines[0].steps[0].params == {"habit_name": "stretching"}
    assert lines[1].steps[0].params == {"text": "Buy milk #buy", "date": "2026-09-29"}
    assert lines[2].steps[0].params == {"text": "call the plumber", "date": "2026-09-28"}


def test_a_fuzzy_habit_match_is_offered_on_the_block_line():
    habits = [{"path": "20-habits/dog-walk.md", "metadata": {"name": "Dog Walk"}}]
    [line] = plan([clause("log_block", name="walk")], [placed("fact", at(0, 10), at(0, 30))], habits=habits)
    assert line.habit_candidate == {"path": "20-habits/dog-walk.md", "name": "Dog Walk"}


def test_a_tag_and_its_first_segment_are_written_once():
    [line] = plan([clause("add_todo", name="Fix login", tags=("dev-session", "dev"))], [ClauseResolution("fact")])
    assert line.steps[0].params["text"] == "Fix login #dev-session"


# --- Revised 2026-10-03 (spec §7.1, §7.3) ---


def test_an_end_with_nothing_open_creates_its_block():
    [line] = plan([clause("end_block", target="Gym")], [placed("fact", at(15, 40, 27), at(16, 50, 27), sp="assumed")])
    [step] = line.steps
    assert (line.kind, step.tool, step.params["name"]) == ("block", "create_event", "Gym")
    assert step.params["end_time"] == "2026-09-27T16:50:00"


def test_a_plan_moves_a_nearby_plan_instead_of_adding_one():
    gym = block("g", "Gym", "2026-09-28T18:00:00", "2026-09-28T19:00:00", intent="plan")
    [line] = plan([clause("log_block", name="Gym", intent="plan")], [placed("plan", at(18, 30), at(19, 30))],
                  candidates=[gym])
    [step] = line.steps
    assert (line.kind, line.outcome, step.tool) == ("edit", "plan", "update_event")
    assert step.params["start_time"] == "2026-09-28T18:30:00" and "state" not in step.params["_fast"]


def test_a_plan_over_a_proposal_approves_it_at_the_new_times():
    walk = block("w", "Dog walk", "2026-09-28T21:00:00", "2026-09-28T21:30:00", proposed=True)
    [line] = plan([clause("log_block", name="Dog walk", intent="plan")], [placed("plan", at(21, 15), at(21, 45))],
                  candidates=[walk])
    assert line.steps[0].params["_fast"]["state"] == "approved"


def test_an_update_keeps_a_known_end_against_an_assumed_one():
    walk = block("w", "Dog walk", "2026-09-27T23:00:00", "2026-09-27T23:40:00")
    [line] = plan([clause("log_block", name="Dog walk")],
                  [placed("fact", at(23, 10, 27), at(23, 30, 27), sp="exact", ep="assumed")], candidates=[walk])
    params = line.steps[0].params
    assert params["start_time"] == "2026-09-27T23:10:00" and "end_time" not in params
    assert params["_fast"]["fields"] == {"start_precision": "exact"}


def test_a_record_crosses_out_the_open_todo_it_finishes():
    [line] = plan([clause("log_block", name="Send the invoice")], [placed("fact", at(0, 20), at(0, 30))],
                  todos=["Send the invoice", "08:00 Call the plumber"])
    assert [s.tool for s in line.steps] == ["create_event", "daily_check_todo"]
    assert line.steps[1].params == {"text": "Send the invoice", "date": "2026-09-28"}


def test_the_todo_hook_leaves_a_todo_that_only_shares_a_word():
    [line] = plan([clause("log_block", name="Gym")], [placed("fact", at(0, 10), at(0, 40))],
                  todos=["Renew the gym membership"])
    assert [s.tool for s in line.steps] == ["create_event"]


def test_a_named_rollover_moves_that_todo_to_its_day():
    tomorrow = ClauseResolution("fact", Placement(None, None, None, None, dt.date(2026, 9, 29)))
    [line] = plan([clause("rollover_todos", target="Buy a drill")], [tomorrow])
    assert line.steps[0].params == {"from_date": "2026-09-28", "to_date": "2026-09-29", "text": "Buy a drill"}


def test_a_plain_rollover_moves_yesterdays_unfinished_todos_to_today():
    [line] = plan([clause("rollover_todos")], [ClauseResolution("fact")])
    assert line.steps[0].params == {"from_date": "2026-09-27", "to_date": "2026-09-28"}


def test_resolve_clauses_uses_the_target_it_is_given():
    from src.services.fast_lane.context import FastContext
    from src.services.fast_lane.shadow import ShadowSettings, resolve_clauses
    ctx = FastContext(now=NOW, chat_id=1, text="gym ended at 19:30")
    edit = clause("end_block", target="the gym", time=TimeWords(end="19:30"))
    gym = {"id": "g", "name": "Gym", "start_time": "2026-09-27T18:00:00", "end_time": None, "date": "2026-09-27"}
    [r] = resolve_clauses(ParseResult((edit,), None), ctx, ShadowSettings(model="m", timeout_s=1), targets={0: gym})
    assert r.outcome == "fact" and r.placement.end == at(19, 30, 27)


def test_a_start_only_record_beside_an_open_block_of_its_activity_is_created():
    # `close` needs an end; the open block is left for the user (PlanInputs docstring).
    open_walk = block("w", "Dog walk", "2026-09-28T00:05:00", None)
    [line] = plan([clause("start_block", name="Dog walk")], [placed("fact", at(0, 30), None, ep=None)],
                  candidates=[open_walk])
    [step] = line.steps
    assert (line.kind, step.tool) == ("block", "create_event")
    assert step.params["start_time"] == "2026-09-28T00:30:00" and "end_time" not in step.params
