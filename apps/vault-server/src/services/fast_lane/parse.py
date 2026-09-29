"""The fast lane's one model call: read a message into clauses of evidence.

Spec §5. The prompt is static (rules and examples), so it can be cached once
it grows past Haiku's 4,096-token minimum. Everything about this message and
this moment goes in the user turn.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.services.fast_lane.context import FastContext
from src.services.fast_lane.contract import PARSE_SCHEMA, ParseFailure, ParseResult, validate

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You read one message sent to Mazkir, a personal assistant that keeps the user's timeline, habits and todos. You do not act and you do not reply. You list what the message says as clauses of evidence, in the user's own words.

## Operations
- log_block: an activity with its time: both ends, a duration, or reported as done ("went for a run"). Also an activity to schedule with no time yet ("plan X", "schedule for later: X, Y"): intent plan and time empty; Mazkir proposes the times.
- start_block: something starting now or at a time, with no end and no duration.
- end_block: a block listed under "Blocks on the timeline" ends ("woke up at 09:10" ends Sleep, "back home" ends the walk, "sleep until 15:45"). When no such block is listed, it is a log_block with time.end instead.
- edit_block: an existing block's times, day or name change, without saying that it happened: its start moves, the whole block shifts or moves to another day, or it is renamed. An activity reported as done or started is log_block or start_block even when a plan for it is listed; Mazkir confirms the plan.
- tick_habit: a habit done, with no clock time given ("today" is a day, not a time). With a clock time it is a log_block, and Mazkir ticks the habit.
- add_todo: something to remember, buy or do some day, with no scheduling words. A list under "Tasks for <project>:" is one add_todo per item.
- check_todo: something done that is one of the "Open todos", with no clock time; target is that todo's words as listed. With a clock time it is a log_block, and Mazkir crosses the todo out too. "Cross out as done:" followed by a list is one check_todo per item.
- rollover_todos: move todos to another day, which goes in time.day. target is the todo when one is named ("the drill todo goes to tomorrow", or "I'll call the plumber tonight" when that is an open todo); leave target empty for all the unfinished ones. An open todo given only a day stays a todo: it is moved, not planned as a block.
- other: anything else, such as questions, conversation, notes and ideas, coding requests, describing a photo, or deleting something. Task files and habits belong here too: "#task", "create task", "log it as a task", "complete it" about a task, and creating or changing a habit or goal are all "other", never add_todo.

## Rules
1. One clause per action. "Dog walk, then a bar" is two clauses.
2. Copy time words exactly as written into time.start, time.end, time.duration, time.shift and time.day. Never convert, never add a date, never calculate. "3:00" stays "3:00", "7hr" stays "7hr", and "yesterday" goes in time.day.
3. When the words pin a moment to when the message was sent ("just returned", "back home", "finished", "done", "started", "going to", "now"), write "now" in that field: time.end for endings, time.start for beginnings.
4. "Then" links a clause to the one before it: set time.after to that clause's 0-based index. An activity running alongside another sets time.with instead.
5. stated is true when the user asks for something, or reports an activity with a time or with a verb such as started, finished, went, did or walked. A passing mention inside another sentence, such as "I'm at a bar, and I had an idea", has stated false.
6. Every activity with a time or "now" gets its own clause, whatever the message is mainly about.
7. intent is "plan" only when the words say it will happen: tomorrow, later, "I'll", "plan", "schedule", a weekday ahead, or a time later today. A time just minutes after the message ("Gym at 20:50" sent at 20:45, "let the walk start at 23:00") is a plan. Everything else is "record".
8. evidence is the exact words from the message that the clause came from, copied character for character, and no longer than needed.
9. name is the activity or todo as the user would title it, kept short ("Dog walk", "Buy a drill"). target names the existing block or todo that an edit, end or check refers to. When the message says "it" or "this" and replies to a message about a block, target is that block's name.
10. Fill place, people and project only when the message says them.
11. An "other" clause carries only op, intent, stated and evidence. Leave its name, target, place, people, project and time empty.
12. An answer to a question the assistant asked (in a prior message or as the last turn) takes its details from that question.
13. A short answer to the assistant's last question that is not about a time ("3", "yes, attach it") is a single "other" clause.
14. When any clause is "other", set fallthrough_skill to the skill for the rest. Choose from the skills listed with the message by what each is used for. Reading or listing tasks, goals, events or the calendar is time-management. Attaching something to the daily note, or keeping a journal entry, is mazkir. A complaint that Mazkir did not do what it said, or that something does not show up ("I don't see it in /day"), is engineering. knowledge-management is only for notes, ideas and facts to keep. If none are listed: time-management for tasks, reminders and the calendar; knowledge-management for notes, ideas and what the user knows; engineering for changes to Mazkir itself; motivation-management for tokens and rewards; mazkir for conversation and anything else. When no clause is "other", set it to null.
15. Write only what the message says. Never invent a place, target or person it does not name, never work out an end time, and keep hedges such as "around" in the time words. A photo caption or a one-word answer is not a block unless it names an activity done or a time. Something the user says they will do is not done yet.
16. An interval that had already started or ended when the message was sent is a record, even when the message is worded as an instruction ("log it as 23:00-00:00").
17. When the message reshapes something Mazkir only proposed ("keep it as proposed, and …"), it is "other" for the skill that proposed it. A bare time answering the assistant's question about a reminder or block sets that item's time: edit_block, with target that item.
18. A day's intention ("today I want to focus on X") is a log_block with intent plan and no time.

## Examples
Fields not shown are null or empty.

Message (sent 00:45): Dog walk 23:15-23:35
Output: {"clauses":[{"op":"log_block","intent":"record","stated":true,"evidence":"Dog walk 23:15-23:35","name":"Dog walk","time":{"start":"23:15","end":"23:35"}}],"fallthrough_skill":null}

Message (sent 02:00): Finished eating, 30 mins. Then brushed my teeth 10 mins
Output: {"clauses":[{"op":"log_block","intent":"record","stated":true,"evidence":"Finished eating, 30 mins","name":"Eating","time":{"end":"now","duration":"30 mins"}},{"op":"log_block","intent":"record","stated":true,"evidence":"Then brushed my teeth 10 mins","name":"Brush teeth","time":{"duration":"10 mins","after":0}}],"fallthrough_skill":null}

Message (sent 05:20): Had a 45 min #dev session between 04:30 and 05:15. Now going to sleep
Output: {"clauses":[{"op":"log_block","intent":"record","stated":true,"evidence":"45 min #dev session between 04:30 and 05:15","name":"Dev session","time":{"start":"04:30","end":"05:15","duration":"45 min"}},{"op":"start_block","intent":"record","stated":true,"evidence":"Now going to sleep","name":"Sleep","time":{"start":"now"}}],"fallthrough_skill":null}

Message (sent 21:15): At the park with friends, got an #idea: label the spice jars
Output: {"clauses":[{"op":"start_block","intent":"record","stated":false,"evidence":"At the park with friends","name":"Park","time":{"start":"now"}},{"op":"other","intent":"record","stated":true,"evidence":"got an #idea: label the spice jars"}],"fallthrough_skill":"knowledge-management"}

Message (sent 23:00): Workshop tomorrow 13:30-16:30, room E
Output: {"clauses":[{"op":"log_block","intent":"plan","stated":true,"evidence":"Workshop tomorrow 13:30-16:30, room E","name":"Workshop","place":"room E","time":{"start":"13:30","end":"16:30","day":"tomorrow"}}],"fallthrough_skill":null}

Message (sent 20:45): Gym at 20:50
Output: {"clauses":[{"op":"start_block","intent":"plan","stated":true,"evidence":"Gym at 20:50","name":"Gym","time":{"start":"20:50"}}],"fallthrough_skill":null}

Message (sent 19:00): Schedule for later: water the plants, vacuum the floor
Output: {"clauses":[{"op":"log_block","intent":"plan","stated":true,"evidence":"water the plants","name":"Water the plants"},{"op":"log_block","intent":"plan","stated":true,"evidence":"vacuum the floor","name":"Vacuum the floor"}],"fallthrough_skill":null}

Blocks on the timeline:
09-27 23:40–open Sleep
Message (sent 09:30): Woke up at 09:10
Output: {"clauses":[{"op":"end_block","intent":"record","stated":true,"evidence":"Woke up at 09:10","target":"Sleep","time":{"end":"09:10"}}],"fallthrough_skill":null}

Open todos: Wash the dishes; Call the plumber
Message (sent 21:00): Washed the dishes too
Output: {"clauses":[{"op":"check_todo","intent":"record","stated":true,"evidence":"Washed the dishes too","target":"Wash the dishes"}],"fallthrough_skill":null}

Message (sent 23:30): Bought the batteries, mark that as done. The rest of the todos roll over to tomorrow
Output: {"clauses":[{"op":"check_todo","intent":"record","stated":true,"evidence":"Bought the batteries, mark that as done","target":"batteries"},{"op":"rollover_todos","intent":"plan","stated":true,"evidence":"The rest of the todos roll over to tomorrow","time":{"day":"tomorrow"}}],"fallthrough_skill":null}

Message (sent 10:00): Today going to the hardware store to #buy a drill
Output: {"clauses":[{"op":"add_todo","intent":"plan","stated":true,"evidence":"going to the hardware store to #buy a drill","name":"Buy a drill","place":"hardware store","time":{"day":"Today"}}],"fallthrough_skill":null}

Open todos: Pay the electricity bill; Buy a drill
Message (sent 15:10): Paid the electricity bill at 14:30. The drill todo goes to tomorrow
Output: {"clauses":[{"op":"log_block","intent":"record","stated":true,"evidence":"Paid the electricity bill at 14:30","name":"Pay the electricity bill","time":{"start":"14:30"}},{"op":"rollover_todos","intent":"plan","stated":true,"evidence":"The drill todo goes to tomorrow","target":"Buy a drill","time":{"day":"tomorrow"}}],"fallthrough_skill":null}

The message replies to (assistant): ✓ 16:00–16:30 Dog walk
Message (sent 16:35): Move it back 30 mins
Output: {"clauses":[{"op":"edit_block","intent":"record","stated":true,"evidence":"Move it back 30 mins","target":"Dog walk","time":{"shift":"back 30 mins"}}],"fallthrough_skill":null}

The message replies to (assistant): 00:00–05:00 on 2026-01-10 is unaccounted. What was it?
Message (sent 12:00): Sleeping
Output: {"clauses":[{"op":"log_block","intent":"record","stated":true,"evidence":"Sleeping","name":"Sleep","time":{"start":"00:00","end":"05:00","day":"2026-01-10"}}],"fallthrough_skill":null}

Message (sent 11:00): Create task: fix the printer before Friday
Output: {"clauses":[{"op":"other","intent":"record","stated":true,"evidence":"Create task: fix the printer before Friday"}],"fallthrough_skill":"time-management"}

Message (sent 18:00): Cross out as done: Buy milk, Call the bank
Output: {"clauses":[{"op":"check_todo","intent":"record","stated":true,"evidence":"Buy milk","target":"Buy milk"},{"op":"check_todo","intent":"record","stated":true,"evidence":"Call the bank","target":"Call the bank"}],"fallthrough_skill":null}

Message (sent 09:30): You said you added it to my calendar, I don't see it
Output: {"clauses":[{"op":"other","intent":"record","stated":true,"evidence":"You said you added it to my calendar, I don't see it"}],"fallthrough_skill":"engineering"}

Message (sent 22:00): Explain how a hash map works
Output: {"clauses":[{"op":"other","intent":"record","stated":true,"evidence":"Explain how a hash map works"}],"fallthrough_skill":"mazkir"}

Recent conversation:
assistant: Which goal needs the update, 1, 2 or 3?
Message (sent 06:30): 3
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
    if ctx.skills:
        lines.append("Skills for fallthrough_skill:")
        lines += [f"- {line}" for line in ctx.skills]
    lines += ["", "Message:", ctx.text]
    return "\n".join(lines)


def _decode(response: Any) -> dict[str, Any]:
    """The reply's JSON object. A reply cut off at max_tokens says so, apart from other failures."""
    if getattr(response, "stop_reason", None) == "max_tokens":
        raise ParseFailure("the parse reply hit max_tokens and was cut off")
    # The first block is not always the answer: a model that thinks puts a thinking block first
    text = next((b.text for b in getattr(response, "content", None) or () if getattr(b, "type", None) == "text"), None)
    if text is None:
        raise ParseFailure("the parse reply had no text block")
    try:
        raw = json.loads(text)
    except (TypeError, ValueError) as e:
        raise ParseFailure(f"the parse reply was not JSON: {e}") from e
    if not isinstance(raw, dict):
        raise ParseFailure("the parse returned no object")
    return raw


def parse_message(ctx: FastContext, claude, *, model: str, timeout_s: float) -> ParseResult:
    try:
        response = claude.create_fast_parse(system=SYSTEM_PROMPT, content=build_user_content(ctx),
                                            schema=PARSE_SCHEMA, model=model, timeout_s=timeout_s)
    except Exception as e:
        raise ParseFailure(str(e)) from e
    return validate(_decode(response), ctx.text)


def warm_up(claude, model: str, timeout_s: float) -> None:
    """Compile the output schema before the first real message pays for it (spec §5.2)."""
    try:
        claude.create_fast_parse(system=SYSTEM_PROMPT,
                                 content="Now: Monday 2026-01-05 10:00\n\nMessage:\nDog walk 09:00-09:30",
                                 schema=PARSE_SCHEMA, model=model, timeout_s=timeout_s)
        logger.info("fast lane parse schema warmed up")
    except Exception:
        logger.warning("fast lane warm-up failed", exc_info=True)
