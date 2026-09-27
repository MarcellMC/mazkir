from src.services.fast_lane.contract import (
    MAX_CLAUSES, PARSE_SCHEMA, ParseResult, extract_hashtags, validate,
)


def clause(op, evidence, **kw):
    return {"op": op, "intent": "record", "stated": True, "evidence": evidence, **kw}


def _objects(schema):
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            yield schema
        for value in schema.values():
            yield from _objects(value)
    elif isinstance(schema, list):
        for value in schema:
            yield from _objects(value)


def test_every_object_in_the_schema_is_closed_and_fully_required():
    for obj in _objects(PARSE_SCHEMA):
        assert obj["additionalProperties"] is False
        assert set(obj["required"]) == set(obj["properties"])


def test_a_clause_whose_words_are_not_in_the_message_is_dropped():
    raw = {"clauses": [clause("log_block", "Dog walk 23:15-23:35", name="Dog walk"),
                       clause("log_block", "gym at noon", name="Gym")],
           "fallthrough_skill": None}
    result = validate(raw, "Dog walk 23:15-23:35")
    assert [c.name for c in result.clauses] == ["Dog walk"]
    assert result.dropped == ("gym at noon",)
    assert result.route == "mixed"   # the unread text still needs someone


def test_links_follow_the_clauses_that_survived():
    raw = {"clauses": [
        clause("log_block", "not in message", name="X"),
        clause("log_block", "Finished eating", name="Eating", time={"end": "now"}),
        clause("log_block", "then teeth", name="Teeth", time={"duration": "10 mins", "after": 1}),
    ], "fallthrough_skill": None}
    result = validate(raw, "Finished eating, then teeth")
    assert result.clauses[1].time.after == 0


def test_a_clause_missing_what_its_op_needs_is_dropped():
    raw = {"clauses": [clause("edit_block", "move it", shift="back")], "fallthrough_skill": None}
    assert validate(raw, "move it").clauses == ()


def test_too_many_clauses_send_the_whole_message_on():
    raw = {"clauses": [clause("log_block", "a", name="a")] * (MAX_CLAUSES + 1), "fallthrough_skill": None}
    result = validate(raw, "a")
    assert result.clauses == () and result.route == "fallthrough"


def test_hashtags_are_rules_not_hints():
    raw = {"clauses": [
        clause("add_todo", "got an #idea: a concert", name="A concert"),
        clause("other", "#buy a drill"),
        clause("log_block", "#dev session 21:30-23:00", name="Dev session"),
    ], "fallthrough_skill": "mazkir"}
    result = validate(raw, "got an #idea: a concert, #buy a drill, #dev session 21:30-23:00")
    idea, drill, dev = result.clauses
    assert idea.op == "other" and result.fallthrough_skill == "knowledge-management"
    assert drill.op == "add_todo" and drill.name == "#buy a drill"
    assert "dev" in dev.tags


def test_extract_hashtags_keeps_the_first_segment_of_a_path():
    assert extract_hashtags("#explore/watch and #Dev") == ("explore/watch", "explore", "dev")


def test_route():
    assert ParseResult((), None).route == "fallthrough"


def test_a_clause_with_an_out_of_range_link_is_dropped():
    raw = {"clauses": [clause("log_block", "something", name="Task", time={"after": 99})],
           "fallthrough_skill": None}
    result = validate(raw, "something")
    assert result.clauses == ()
    assert result.dropped == ("something",)


def test_a_clause_with_a_self_referential_link_is_dropped():
    raw = {"clauses": [clause("log_block", "task", name="Task", time={"after": 0})],
           "fallthrough_skill": None}
    result = validate(raw, "task")
    assert result.clauses == ()
    assert result.dropped == ("task",)


def test_a_clause_with_a_link_to_a_dropped_clause_is_dropped():
    raw = {"clauses": [
        clause("log_block", "not in message", name="First"),
        clause("log_block", "second task", name="Second", time={"with": 0}),
    ], "fallthrough_skill": None}
    result = validate(raw, "second task")
    assert result.clauses == ()
    assert result.dropped == ("not in message", "second task")


def test_extract_hashtags_handles_punctuation_around_tags():
    assert extract_hashtags('(#idea) and "#buy", #dev-session') == ("idea", "buy", "dev-session", "dev")


def test_hashtag_override_works_with_enclosing_punctuation():
    raw = {"clauses": [
        clause("other", "(#buy) a drill"),
    ], "fallthrough_skill": None}
    result = validate(raw, "(#buy) a drill")
    drill = result.clauses[0]
    assert drill.op == "add_todo"


def test_a_clause_with_a_bool_link_is_dropped():
    raw = {"clauses": [
        clause("log_block", "first task", name="First", time={"after": True}),
        clause("log_block", "second task", name="Second"),
    ], "fallthrough_skill": None}
    result = validate(raw, "first task, second task")
    assert [c.name for c in result.clauses] == ["Second"]
    assert result.dropped == ("first task",)


def test_a_clause_with_a_float_link_is_dropped():
    raw = {"clauses": [
        clause("log_block", "first task", name="First"),
        clause("log_block", "second task", name="Second", time={"with": 1.0}),
    ], "fallthrough_skill": None}
    result = validate(raw, "first task, second task")
    assert [c.name for c in result.clauses] == ["First"]
    assert result.dropped == ("second task",)
