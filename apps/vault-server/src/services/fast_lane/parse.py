"""The fast lane's one model call: read a message into clauses of evidence.

Spec §5. The prompt is static (rules and examples), so it can be cached once
it grows past Haiku's 4,096-token minimum. Everything about this message and
this moment goes in the user turn.
"""

from __future__ import annotations

import logging

from src.services.fast_lane.context import FastContext
from src.services.fast_lane.contract import PARSE_SCHEMA, ParseResult, validate

logger = logging.getLogger(__name__)


class ParseFailure(Exception):
    """The parse failed or answered with something unusable; the router takes the message."""


SYSTEM_PROMPT = """You read one message sent to Mazkir, a personal assistant that keeps the user's timeline, habits and todos. You do not act and you do not reply. You list what the message says as clauses of evidence, in the user's own words.

## Operations
- log_block: an activity that happened or is happening, with its time words.
- start_block: something starting now or at a time, with no end yet.
- end_block: an open or planned block ends.
- edit_block: change an existing block's times or name.
- tick_habit: a habit done, with no time given.
- add_todo: something to do, with no fixed time needed.
- check_todo: a todo is done.
- rollover_todos: move unfinished todos to another day.
- other: anything else, such as questions, conversation, notes and ideas, tasks with priorities, coding requests, describing a photo, or deleting something.

## Rules
1. One clause per action. "Dog walk, then a bar" is two clauses.
2. Copy time words exactly as written into time.start, time.end, time.duration, time.shift and time.day. Never convert, never add a date, never calculate. "3:00" stays "3:00", "7hr" stays "7hr", and "yesterday" goes in time.day.
3. When the words pin a moment to when the message was sent ("just returned", "back home", "finished", "done", "started", "going to", "now"), write "now" in that field: time.end for endings, time.start for beginnings.
4. "Then" links a clause to the one before it: set time.after to that clause's 0-based index. An activity running alongside another sets time.with instead.
5. stated is true when the user asks for something, or reports an activity with a time or with a verb such as started, finished, went, did or walked. A passing mention inside another sentence, such as "I'm at a bar, and I had an idea", has stated false.
6. Every activity with a time or "now" gets its own clause, whatever the message is mainly about.
7. intent is "plan" only when the words say it will happen: tomorrow, later, "I'll", "plan", a weekday ahead, or a time later today. Everything else is "record".
8. evidence is the exact words from the message that the clause came from, copied character for character.
9. name is the activity or todo as the user would title it, kept short ("Dog walk", "Buy a drill"). target names the existing block or todo that an edit, end or check refers to. When the message says "it" or "this" and replies to a message about a block, target is that block's name.
10. Fill place, people and project only when the message says them.
11. tags are the hashtags belonging to this clause, without the "#".
12. An answer to a question the assistant just asked takes its details from that question.
13. A short answer to the assistant's last question that is not about a time ("3", "yes, attach it") is a single "other" clause.
14. When any clause is "other", set fallthrough_skill to the skill for the rest:
    - time-management: tasks, priorities, calendar questions;
    - knowledge-management: notes, ideas, what the user knows;
    - engineering: changes to Mazkir itself;
    - motivation-management: tokens and rewards;
    - mazkir: conversation, questions, anything else.
    Otherwise set it to null.

## Examples
Fields not shown are null or empty.

Message (sent 00:48): Dog walk 23:15-23:35
Output: {"clauses":[{"op":"log_block","intent":"record","stated":true,"evidence":"Dog walk 23:15-23:35","name":"Dog walk","time":{"start":"23:15","end":"23:35"}}],"fallthrough_skill":null}

Message (sent 01:56): Finished eating, 30 mins. Then brushed my teeth 10 mins
Output: {"clauses":[{"op":"log_block","intent":"record","stated":true,"evidence":"Finished eating, 30 mins","name":"Eating","time":{"end":"now","duration":"30 mins"}},{"op":"log_block","intent":"record","stated":true,"evidence":"Then brushed my teeth 10 mins","name":"Brush teeth","time":{"duration":"10 mins","after":0}}],"fallthrough_skill":null}

Message (sent 05:16): Had a 45 min #dev session between 04:30 and 05:15. Now going to sleep
Output: {"clauses":[{"op":"log_block","intent":"record","stated":true,"evidence":"45 min #dev session between 04:30 and 05:15","name":"Dev session","tags":["dev"],"time":{"start":"04:30","end":"05:15","duration":"45 min"}},{"op":"start_block","intent":"record","stated":true,"evidence":"Now going to sleep","name":"Sleep","time":{"start":"now"}}],"fallthrough_skill":null}

Message (sent 01:14): At a bar with friends, got an #idea: play a concert for my family
Output: {"clauses":[{"op":"start_block","intent":"record","stated":false,"evidence":"At a bar with friends","name":"Bar","time":{"start":"now"}},{"op":"other","intent":"record","stated":true,"evidence":"got an #idea: play a concert for my family","name":"Play a concert for my family","tags":["idea"]}],"fallthrough_skill":"knowledge-management"}

Message (sent 23:06): Band practice tomorrow 13:30-16:30, room E
Output: {"clauses":[{"op":"log_block","intent":"plan","stated":true,"evidence":"Band practice tomorrow 13:30-16:30, room E","name":"Band practice","place":"room E","time":{"start":"13:30","end":"16:30","day":"tomorrow"}}],"fallthrough_skill":null}

Message (sent 23:32): Bought the cough syrup, mark that as done. The rest of the todos roll over to tomorrow
Output: {"clauses":[{"op":"check_todo","intent":"record","stated":true,"evidence":"Bought the cough syrup, mark that as done","target":"cough syrup"},{"op":"rollover_todos","intent":"plan","stated":true,"evidence":"The rest of the todos roll over to tomorrow","time":{"day":"tomorrow"}}],"fallthrough_skill":null}

Message (sent 01:14): Today going to the hardware store to #buy a drill
Output: {"clauses":[{"op":"add_todo","intent":"plan","stated":true,"evidence":"going to the hardware store to #buy a drill","name":"Buy a drill","place":"hardware store","tags":["buy"],"time":{"day":"Today"}}],"fallthrough_skill":null}

The message replies to (assistant): ✓ 15:59–16:29 Dog walk
Message (sent 16:30): Move it back 30 mins
Output: {"clauses":[{"op":"edit_block","intent":"record","stated":true,"evidence":"Move it back 30 mins","target":"Dog walk","time":{"shift":"back 30 mins"}}],"fallthrough_skill":null}

The assistant just asked: 00:00–05:00 on 2026-09-12 is unaccounted. What was it?
Message (sent 20:41): Bar hopping
Output: {"clauses":[{"op":"log_block","intent":"record","stated":true,"evidence":"Bar hopping","name":"Bar hopping","time":{"start":"00:00","end":"05:00","day":"2026-09-12"}}],"fallthrough_skill":null}

Message (sent 22:22): Explain multi-head attention vs grouped query attention
Output: {"clauses":[{"op":"other","intent":"record","stated":true,"evidence":"Explain multi-head attention vs grouped query attention"}],"fallthrough_skill":"mazkir"}

The assistant just asked: Which goal needs the update, 1, 2 or 3?
Message (sent 06:36): 3
Output: {"clauses":[{"op":"other","intent":"record","stated":true,"evidence":"3"}],"fallthrough_skill":"time-management"}
"""


def build_user_content(ctx: FastContext) -> str:
    lines = [f"Now: {ctx.now.strftime('%A %Y-%m-%d %H:%M')}"]
    if ctx.recent_turns:
        lines.append("Recent conversation:")
        lines += [f"{role}: {text}" for role, text in ctx.recent_turns]
    if ctx.reply_to:
        lines.append(f"The message replies to ({ctx.reply_from or 'assistant'}): {ctx.reply_to}")
    if ctx.blocks:
        lines.append("Blocks on the timeline:")
        lines += [block.line() for block in ctx.blocks]
    if ctx.todos:
        lines.append("Open todos: " + "; ".join(ctx.todos))
    if ctx.habits:
        lines.append("Habits: " + "; ".join(h.line() for h in ctx.habits))
    if ctx.places:
        lines.append("Known places: " + ", ".join(ctx.places))
    if ctx.hashtags:
        lines.append("Hashtags in the message: " + " ".join("#" + t for t in ctx.hashtags))
    if ctx.selected_date:
        lines.append(f"Day open in /day: {ctx.selected_date}")
    if ctx.has_photo:
        lines.append("The message carries a photo.")
    lines += ["", "Message:", ctx.text]
    return "\n".join(lines)


def parse_message(ctx: FastContext, claude, *, model: str, timeout_s: float) -> ParseResult:
    try:
        raw = claude.create_fast_parse(system=SYSTEM_PROMPT, content=build_user_content(ctx),
                                       schema=PARSE_SCHEMA, model=model, timeout_s=timeout_s)
    except Exception as e:
        raise ParseFailure(str(e)) from e
    if not isinstance(raw, dict):
        raise ParseFailure("the parse returned no object")
    return validate(raw, ctx.text)


def warm_up(claude, model: str, timeout_s: float) -> None:
    """Compile the output schema before the first real message pays for it (spec §5.2)."""
    try:
        claude.create_fast_parse(system=SYSTEM_PROMPT,
                                 content="Now: Monday 2026-01-05 10:00\n\nMessage:\nDog walk 09:00-09:30",
                                 schema=PARSE_SCHEMA, model=model, timeout_s=timeout_s)
        logger.info("fast lane parse schema warmed up")
    except Exception:
        logger.warning("fast lane warm-up failed", exc_info=True)
