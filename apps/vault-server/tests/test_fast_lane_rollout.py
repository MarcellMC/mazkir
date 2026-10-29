"""The shadow report compares todo days; the latency readout answers the caching question."""

from src.services.fast_lane.shadow_report import caching_verdict, findings, latency_summary

RUN = {"event": "fast_shadow", "chat_id": 1, "text": "add milk for tomorrow", "now": "2026-09-28T21:00:00+03:00",
       "route": "fast", "clauses": [{"op": "add_todo", "name": "Buy milk", "outcome": "fact",
                                     "logical_date": "2026-09-29", "evidence": "add milk for tomorrow"}]}


def turn(date=None):
    params = {"text": "Buy milk", **({"date": date} if date else {})}
    return {"chat_id": 1, "ts": "2026-09-28T21:00:05+0300", "user_text": "add milk for tomorrow",
            "tools": [{"name": "daily_add_task", "params": params}]}


def test_a_todo_on_another_day_is_a_disagreement():
    assert findings(RUN, [turn("2026-09-28")], set()) == ["todo day differs for Buy milk: fast 2026-09-29, old 2026-09-28"]


def test_the_same_day_agrees():
    assert findings(RUN, [turn("2026-09-29")], set()) == []


def test_no_date_means_the_day_the_message_was_sent():
    assert findings(RUN, [turn()], set()) == ["todo day differs for Buy milk: fast 2026-09-29, old 2026-09-28"]


def test_latency_summary():
    records = [{"parse_ms": ms} for ms in (1000, 2000, 3000, 4000, 5000)] + [{"route": "error"}]
    assert latency_summary(records) == {"n": 5, "p50": 3000, "p95": 5000}
    assert latency_summary([]) == {"n": 0, "p50": None, "p95": None}


def test_caching_verdict():
    assert "already long enough" in caching_verdict(3000, 5000)
    assert "try growing the examples" in caching_verdict(3200, 1800)
    assert "leave the prompt" in caching_verdict(1800, 1800)
    assert caching_verdict(None, 1800) == "no parses logged yet"


def _todo(name, day):
    return {"op": "add_todo", "name": name, "outcome": "fact", "logical_date": day, "evidence": name}


def _old(*calls):
    return [{"chat_id": 1, "ts": "2026-09-28T21:00:05+0300", "user_text": "milk today, bread tomorrow",
             "tools": [{"name": n, "params": p} for n, p in calls]}]


TWO = {**RUN, "text": "milk today, bread tomorrow",
       "clauses": [_todo("Buy milk", "2026-09-28"), _todo("Buy bread", "2026-09-29")]}


def test_two_todos_on_different_days_that_both_paths_agree_on():
    old = _old(("daily_add_task", {"text": "Buy milk"}), ("daily_add_task", {"text": "Buy bread", "date": "2026-09-29"}))
    assert findings(TWO, old, set()) == []


def test_only_the_todo_that_differs_is_named():
    old = _old(("daily_add_task", {"text": "Buy milk"}), ("daily_add_task", {"text": "buy bread"}))
    assert findings(TWO, old, set()) == ["todo day differs for Buy bread: fast 2026-09-29, old 2026-09-28"]


def test_a_move_is_not_compared_as_a_check():
    run = {**RUN, "clauses": [{"op": "check_todo", "target": "Buy milk", "outcome": "fact",
                               "logical_date": "2026-09-29", "evidence": "done milk"}]}
    moved = _old(("daily_set_task_state", {"text": "milk", "state": "moved", "date": "2026-09-28"}))
    assert findings(run, moved, set()) == []
    checked = _old(("daily_set_task_state", {"text": "milk", "state": "checked", "date": "2026-09-28"}))
    assert findings(run, checked, set()) == ["todo day differs for Buy milk: fast 2026-09-29, old 2026-09-28"]
    ticked = _old(("daily_check_todo", {"text": "Buy milk"}))
    assert findings(run, ticked, set()) == ["todo day differs for Buy milk: fast 2026-09-29, old 2026-09-28"]
