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


# Fix (a): anchor old times on the tool's own date
def test_old_times_anchor_on_tool_date():
    old = turn("Dog walk", tools=[{"name": "create_event", "params": {
        "name": "Dog walk", "date": "2026-09-07", "start_time": "23:15", "end_time": "23:35"}}])
    notes = findings(run("Dog walk", [BLOCK]), [old], set())
    assert not any("times differ" in n for n in notes)


def test_old_times_wrap_end_to_next_day():
    old = turn("Dog walk", tools=[{"name": "create_event", "params": {
        "name": "Dog walk", "date": "2026-09-07", "start_time": "23:15", "end_time": "00:05"}}])
    clause = {"op": "log_block", "intent": "record", "outcome": "fact", "name": "Dog walk",
              "evidence": "Dog walk 23:15-00:05", "start": "2026-09-07T23:15:00+03:00",
              "end": "2026-09-08T00:05:00+03:00"}
    notes = findings(run("Dog walk", [clause], now="2026-09-08T00:48:00+03:00"), [old], set())
    assert not any("times differ" in n for n in notes)


# Fix (b): compare only the times both sides have
def test_end_only_old_write_matches_end():
    old = turn("Dog walk", tools=[{"name": "create_event", "params": {
        "name": "Dog walk", "date": "2026-09-07", "end_time": "23:35"}}])
    notes = findings(run("Dog walk", [BLOCK]), [old], set())
    assert not any("times differ" in n for n in notes)


def test_end_only_old_write_with_different_end():
    old = turn("Dog walk", tools=[{"name": "create_event", "params": {
        "name": "Dog walk", "date": "2026-09-07", "end_time": "23:50"}}])
    notes = findings(run("Dog walk", [BLOCK]), [old], set())
    assert any("times differ" in n for n in notes)


# Fix (c): check tick_habit clauses
def test_unticked_habit_without_complete_habit():
    clause = {"op": "tick_habit", "name": "Stretching", "outcome": None, "evidence": "did my stretching"}
    notes = findings(run("stretching", [clause]), [turn("stretching")], set())
    assert notes == ["habit not ticked by the old path: Stretching"]


def test_ticked_habit_with_complete_habit():
    clause = {"op": "tick_habit", "name": "Stretching", "outcome": None, "evidence": "did my stretching"}
    old = turn("stretching", tools=[{"name": "complete_habit", "params": {"name": "Stretching"}}])
    notes = findings(run("stretching", [clause]), [old], set())
    assert not any("not ticked" in n for n in notes)
