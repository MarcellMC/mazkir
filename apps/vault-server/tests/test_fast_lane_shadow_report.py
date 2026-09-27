from src.services.fast_lane.shadow_report import findings, pair_runs, render_report


def run(text, clauses, route="fast", now="2026-09-08T00:48:00+03:00", **kw):
    return {"event": "fast_shadow", "chat_id": 1, "text": text, "now": now, "route": route,
            "clauses": clauses, "parse_ms": 1800, **kw}


def turn(text, tools=(), skill="time-management", ts="2026-09-08T00:48:20+0300"):
    return {"chat_id": 1, "ts": ts, "user_text": text, "skill": skill, "tools": list(tools)}


BLOCK = {"op": "log_block", "intent": "record", "outcome": "fact", "name": "Dog walk",
         "evidence": "Dog walk 23:15-23:35", "start": "2026-09-07T23:15:00+03:00",
         "end": "2026-09-07T23:35:00+03:00"}


def test_runs_pair_with_the_turn_that_handled_the_same_message():
    pairs = pair_runs([run("Dog walk 23:15-23:35", [BLOCK])],
                      [turn("Dog walk 23:15-23:35"), turn("other", ts="2026-09-08T09:00:00+0300")])
    assert len(pairs) == 1 and len(pairs[0][1]) == 1


def test_a_block_the_old_path_never_wrote_is_reported():
    notes = findings(run("Dog walk 23:15-23:35", [BLOCK]), [turn("Dog walk 23:15-23:35")], set())
    assert any("wrote no block" in n for n in notes)


def test_different_times_are_reported():
    old = turn("Dog walk 23:15-23:35", tools=[{"name": "create_event", "params": {
        "name": "Dog walk", "start_time": "2026-09-08T23:15", "end_time": "2026-09-08T23:35"}}])
    notes = findings(run("Dog walk 23:15-23:35", [BLOCK]), [old], set())
    assert any("times differ" in n for n in notes)


def test_an_unticked_habit_is_reported():
    old = turn("Dog walk 23:15-23:35", tools=[{"name": "create_event", "params": {
        "name": "Dog walk", "start_time": "2026-09-07T23:15", "end_time": "2026-09-07T23:35"}}])
    notes = findings(run("Dog walk 23:15-23:35", [BLOCK]), [old], {"dog walk"})
    assert notes == ["habit not ticked by the old path: Dog walk"]


def test_questions_and_failures_are_reported():
    question = dict(BLOCK, outcome="question", reason="two readings of these times fit")
    assert any("would ask" in n for n in findings(run("x", [question]), [], set()))
    assert findings(run("x", [], route="router_fallback", error="timeout"), [], set()) == ["parse failed: timeout"]


def test_the_report_opens_with_totals():
    text = render_report([(run("Dog walk 23:15-23:35", [BLOCK]), [turn("Dog walk 23:15-23:35")])], set())
    assert text.splitlines()[0].startswith("1 message")
