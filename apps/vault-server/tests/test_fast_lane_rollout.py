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
