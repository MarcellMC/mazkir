# Fast Lane: a message becomes evidence on your timeline (Design)

**Status:** Design, approved section by section in conversation 2026-09-26/27. A1 merged; A2 planned.
**Revised 2026-10-03** after A1's labelled replay: the owner's rules on 24-hour clocks, untimed plans, windows, waking up, shared intervals, todos and routing; the operations both models split the same way; and the resolver fixes the replay found (§5.1–§5.6, §6, §7.1–§7.3, §11.2).
**Piece A** of the message-pipeline redesign (pieces A–D, §3). B, C and D get their own brainstorm and spec.
**Parent:** `docs/specs/2026-08-21-time-management-phase2-capture-design.md`. This design supersedes its ship order from Ship 6 on (§3.2), and absorbs Ship 7 and Ship 4b into pieces C and D.
**Research behind it:**
- `reports/Jev for message routing.md` and `research_notes/Jev for message routing/`: router baseline, routing patterns, the Jev evaluation.
- Private artifacts: *Mazkir Message Routing* (primer), *Your Reconstructed Timeline* (history reconstruction), *Mazkir Readout Lab* (readout prototype).
- The analysis of all 304 real agent turns in `data/logs/agent-turns.jsonl` (§2).

---

## 1. What this is for

### 1.1 What Mazkir is for

> Mazkir is a very capable personal assistant. Its main purpose is to organize time and knowledge, act as a second brain, assist thinking and better decision making, and track and build habits. It makes managing life feel easy and fun, like playing a game.

This is the owner's wording, and it goes into CLAUDE.md in the same PR (§14).

### 1.2 The goals this design serves

1. **Mazkir uses the information you give it to reconstruct your real-life timeline.** Every message is evidence about your day, not only a command to carry out.
2. **Simple, common tracking is quick.** Logging a block, ticking a habit, adding a todo.
3. **Complex, multistep requests feel like Claude Code:** it understands intent and follows through. That is piece B's job; A must not stand in its way.

### 1.3 The principle

**The model decides what a message says. Code decides what happens.** Every write, and every "✓" line that reports one, comes from code. The model never computes a timestamp, never picks a record id, and never writes anything on the fast path.

---

## 2. Evidence: what the history shows

Analysed: 304 real agent turns (your chat) from 2026-05-02 to 2026-09-23, which is 282 distinct messages once a message that passed through two skills is counted once. Test chat ids are excluded.

**What you use Mazkir for:**

| Kind | Messages |
|---|---|
| Time blocks: log, plan, edit | 78 |
| Tasks and todos | 51 |
| No tool used: answers ("Yes", "3", "10:00"), questions, chat, failures | 47 |
| Photos | 36 |
| Coding / meta (inflated by one request repeated 9 times) | 31 |
| Knowledge | 24 |
| Daily note | 11 |
| Habits | 4 |

**Where the current design failed:**

| # | Failure | Evidence |
|---|---|---|
| 1 | Claimed a write that never happened | 11 turns, e.g. "Schedule for later: hang laundry…" → "Added 3 chores!" with no tool call; "Undo, delete the note" → "Done", though no delete tool exists |
| 2 | Habit blocks never counted | Conversation log: 26 habit-like blocks logged, 1 ticked. Ledger: 12 of 16 dog walks and all 7 gym blocks never ticked, 165 tokens unpaid; 4 walk ticks have no walk |
| 3 | The model does time arithmetic | "3:00-3:20" sent at 04:17 → 15:00 in the future; "ended at 00:30" → a 25-hour walk; "just returned" used as a start; the 7 Sep night filed a day late (still wrong in the ledger) |
| 4 | Yes/no for trivial writes | 25 stops, e.g. "Meal prep 20:00–20:30 — Should I proceed?" |
| 5 | Skill silos and hand-offs | 11 hand-offs, every one after a fallback; "Explain MHA vs GQA" refused twice; "I don't have a tool" while holding one |
| 6 | Slow simple logs | 28 single "X HH:MM–HH:MM" logs: p50 9.0 s, p90 11 s |
| 7 | Parts of mixed messages lost | 16 of 82 time-bearing messages wrote nothing; "Watched UFC" never logged; an `#idea` became a task due decades in the past |
| 8 | List numbers and priority scale | "min priority for task 1, highest for task 3" reversed; four turns to fix |

**From the timeline reconstruction:**
- Only 3% of hours since 2 Mar carry a block. 2–15 Sep averaged 30%, and 12 Sep reached 98% with gap prompts: capture works when used.
- 29% of your activity is between 00:00 and 06:00. Median sleep onset is 03:15, median wake 10:47.
- The ledger holds 18 zero-length blocks and 2 blocks never closed.
- 19 blocks were created before they happened and count as approved with no confirmation.
- 36% of blocks created from messages have an assumed or missing end.
- Telegram photo timestamps (UTC) were read as local time twice. 35 of 44 photos lost their EXIF on the way through Telegram.
- 12 of 77 matched daily-note and ledger blocks disagree.

Routing speed was never the complaint. Truthfulness, time arithmetic and unpaid habits were.

---

## 3. The pipeline and its four pieces

### 3.1 Shape

```
Telegram ─► bot shows a stage draft at once
             │
             ▼  POST /message (SSE)
 1 Context   code   the message you replied to, the bot's open question, recent turns,
                    today's blocks, habits and aliases, places, hashtags, the /day date
 2 Continue? code   a pending yes/no confirmation ──► today's /message/confirm path (unchanged)
 3 Parse     Haiku  one structured call → clauses, as evidence (§5)
 4 Resolve   code   time resolver (§6), matching to the ledger, habits, places (§7)
 5 Act       code   facts and plans written now · proposals written pending · questions asked
 6 Reply            receipt built from what ran (§8) · fallthrough work ──► skill / agent
```

Latency budget for a tracking message (estimate): context about 0.1 s, parse 1.5–2.5 s, resolve and write about 0.3 s. About 3 s against today's 9 s. Google sync finishes after the receipt is shown.

### 3.2 Four pieces, each its own spec, plan and PR

| | Piece | Delivers | Replaces |
|---|---|---|---|
| **A** | **Fast lane** (this spec) | Parse, time resolver, evidence outcomes, receipts with undo, habit hook, live stages; handles time blocks, habits and todos | the slow path for about 45% of messages, and the separate router call |
| **B** | **One agent** | One Sonnet agent with every tool; skills become instructions; a to-do list for multistep work; short answers return to whoever asked | the router's skill silos and `next_skill` hand-offs |
| **C** | **Preview** | A stored pending plan with one preview for batches of edits, ✓ ✕ per line, Approve all; list numbers | Ship 7's core |
| **D** | **Judgment** | Volunteered statements beyond the timeline: reminders, follow-ups, new habits from prose, past vs planned beyond explicit words | Ship 4b |

**Order: A, then B, then C and D in either order.** Ship 6 (classification) is independent. Ships 8 (timers) and 9 (weekly readout) are unchanged. §14 lists the phase-doc update.

---

## 4. Piece A in brief

Every message is read once by a fast model and turned into **clauses of evidence**. Code places each clause on the timeline and gives it exactly one outcome:

| Evidence | Outcome |
|---|---|
| Stated record, placed exactly | **Fact.** Written, counted in `confirmed_minutes`, receipt with undo |
| Stated plan | **Scheduled.** Written, synced to Google, counted as a plan until confirmed |
| Mentioned in passing, or the resolver had to guess | **Proposal.** Pending on `/day`, ✓ ✕ ✎ on the receipt, not synced, not counted |
| Can't be placed | **Question.** One tap, or one reply; the answer comes back as evidence |

Clauses outside A's operations fall through to a skill; parse failures fall through to today's router.

---

## 5. The parse contract

### 5.1 Input (assembled by code, about 1–1.5k tokens)

- Now: local time with weekday, Asia/Jerusalem, DST-aware. This is the only clock the resolver trusts.
- The message text or caption; the replied-to message in full (`repliedToText`, 2026-09-15); the bot's open question if any.
- The last 4 turns, with Ship 3's tool-record lines stripped.
- Today's blocks as `HH:MM–HH:MM name` with open ones marked. Before 05:00, also last evening's.
- Today's untimed todos; habit names with aliases; known place names.
- Hashtags extracted by code; the day open in `/day`.
- The router's skill catalog, one line per skill (name, description, when to use), for `fallthrough_skill`. With one-line hints instead, the parse chose the right skill 55 % of the time against the router's 82 % (2026-09-29).

### 5.2 Output (structured output via `output_config.format`)

```ts
ParseResult {
  clauses: Clause[]            // count capped in code (≤ 12); the schema can't cap it
  fallthrough_skill: "time-management" | "knowledge-management" | "mazkir"
                   | "engineering" | "motivation-management" | null
}
Clause {
  op: "log_block" | "start_block" | "end_block" | "edit_block" | "tick_habit"
    | "add_todo" | "check_todo" | "rollover_todos" | "other"
  intent: "record" | "plan"
  stated: boolean
  evidence: string             // exact words from the message
  name: string | null
  target: string | null        // edits, checks and moved todos: "the dog walk", "Dev Session", "it"
  place: string | null         // as written
  people: string[]             // as written
  project: string | null       // as written
  time: { start, end, duration, shift, day: string | null,   // copied as written
          after, with: integer | null } | null
}
```

Schema notes, checked against the structured-outputs docs:
- Optional fields are `anyOf: [{type: …}, {type: "null"}]`, and every property is listed in `required`.
- Every object sets `additionalProperties: false`.
- Enums and arrays of objects are supported. Array length and string length can't be constrained, so both are checked in code.
- A new schema compiles once and is cached for 24 h. The server makes one throwaway parse call at startup so the first real message doesn't pay for compilation.
- **Tags are not in the schema.** Code reads them from each clause's evidence (§5.4). Asked for tags, Haiku invented them without end ("query", "request", …) until it hit the token cap, on messages as short as "3": 22 of 276 parses failed that way in the first replay. The reply is capped at 1,500 tokens.
- **Thinking is off explicitly**, not by omission: Sonnet 5 thinks unless told not to, and a thinking block arrives before the text, so the reply is read from its text block.

### 5.3 Rules in the prompt

The prompt defines each operation, gives numbered rules, and carries 19 examples in generic words. *Revised 2026-10-03 from the labelled history and the owner's answers.*

**Operations**
- `log_block`: an activity with its time, or reported as done. Also a plan with no time yet ("plan X", "schedule for later: X, Y", "today I want to focus on X"): intent plan, time empty, and code proposes the times (§6.2 rule 12).
- `start_block`: something starting now or at a time. It writes what a `log_block` with only a start writes.
- `end_block`: a block listed on the timeline ends. With none listed, it is a `log_block` with only an end.
- `edit_block`: an existing block's times, day or name change **without saying it happened**. An activity reported as done or started is logged even when its plan is listed; the matcher confirms the plan (§7.1).
- `tick_habit`, `check_todo`: a habit or open todo done **with no clock time** ("today" is a day, not a time). With a clock time it is a `log_block`, and the habit and todo hooks tick it or cross it out (§7.2, §7.3). "Cross out as done:" followed by a list is one `check_todo` per item.
- `add_todo`: something to remember, buy or do some day. A list under "Tasks for <project>:" is one per item.
- `rollover_todos`: move todos to another day, in `time.day`. `target` names one todo ("the drill todo goes to tomorrow", or "I'll call the plumber tonight" when that is an open todo); empty means all unfinished ones. An open todo given only a day is moved, not planned as a block.
- `other`: anything else. Task files and habits belong here: "#task", "create task", "complete it" about a task, and creating or changing a habit or goal.

**Rules**
1. One clause per action. Several activities given one interval together ("23:00–00:00 as meal prep, eating and a film") are one clause each, each with that interval's words; Mazkir asks how it was split. One running alongside another ("eating while watching") sets `with` instead.
2. Copy time words exactly; never convert, add a date or calculate. Window words stay in `time.start` ("somewhere between 20:30").
3. Words that pin a moment to the send time ("just returned", "started", "going to", "now") are written as "now".
4. "Then" sets `after`; an activity alongside another sets `with`.
5. `stated` is true for an explicit request, an activity reported with a time, or a log verb ("started", "finished", "went"). A passing mention is `stated: false`.
6. Every activity with a time or "now" gets its own clause, whatever the message is mainly about.
7. `intent: plan` only when the words say it will happen: "tomorrow", "later", "I'll", "plan", "schedule", a weekday ahead, or a time later today, including one minutes after the message ("Gym at 20:50" sent at 20:45). An interval that had already started or ended when the message was sent is a record, even when worded as an instruction.
8. `evidence` is the exact words, no longer than needed.
9. Write only what the message says: no invented place, target or person, no computed end, and hedges kept. A photo caption or a one-word answer is not a block unless it names an activity done or a time.
10. An answer to a question the assistant asked takes its details from that question (a gap prompt's interval). A bare time answering a question about a reminder or block sets that item's time (`edit_block`).
11. Reshaping something Mazkir only proposed ("keep it as proposed, and …") is `other`, for the skill that proposed it.
12. A short answer to the assistant's last question that is not about a time ("3", "yes, attach it") is a single `other`.
13. `fallthrough_skill` comes from the skill catalog (§5.1). Reading tasks, goals, events or the calendar is time-management; attaching to the daily note or keeping a journal entry is mazkir; a complaint that Mazkir did not do what it said, or that something does not show up, is engineering; knowledge-management is only for notes, ideas and facts.

With the catalog, the request is about 5k tokens on Haiku 4.5, above its 4,096-token cache minimum. Whether caching cuts latency is measured in A2 (§13).

### 5.4 Checks in code after the parse

- **Hashtags override the model.** Code reads each clause's tags from its own evidence. `#idea` and `#green` force a knowledge clause; `#buy` forces `add_todo`; `#dev`, `#work` and `#explore` become activity tags. The map lives in code.
- Evidence not found in the message: that clause is dropped and its text falls through.
- Out-of-range `after` / `with`, or fields an op requires missing: the same.
- More than 12 clauses: the whole message falls through.

### 5.5 Routing after the parse

- Every clause is an A op: fast lane only.
- Every clause is `other`: dispatch straight to `fallthrough_skill`, with no router call.
- Mixed: the fast clauses run first; the skill then gets the message plus a list of what already ran, with an instruction not to redo it.
- A lone `other` clause right after a skill turn (a short answer such as "3" or "yes, attach it") goes to **that same skill**, read from the previous turn's `skill` in `agent-turns.jsonl`, not to `fallthrough_skill`.
- The parse fails or takes over 5 s: today's router path, logged at ERROR. Never the `mazkir` fallback.

### 5.6 Photos

Before the parse, code places each photo on the timeline:
- At its **EXIF capture time** when the image was sent as a file (`exact`).
- Otherwise at **Telegram's send time**, converted from UTC (`approx`). This conversion fixes the 3-hour bug.

The photo is attached to the block covering that moment, if one exists. The message then goes to the fallthrough skill for its content.

A caption that names an activity done with no time ("logged it on the dog walk") also proposes a block of that activity around the photo's moment, at your usual length (owner, 2026-09-29). Telegram's send time is the right moment when the image carries no camera time.

---

## 6. The time resolver

`services/time_resolver.py` is pure functions with no I/O. It extends `services/interval.py` (`derive_interval`, `split_at_midnight`).

### 6.1 Inputs

- Each clause's raw time words, intent, and `after` / `with` links.
- **The message's send time**, local.
- Blocks still open, and each activity's typical duration from the ledger (median; 30 min fallback).
- Your usual bedtime: the median Sleep start over 30 days, read across midnight; none with fewer than three nights.
- The day boundary: 05:00 by default, configurable, taken from your sleep data.

### 6.2 Rules

*Revised 2026-10-03.* Rules 3, 4, 6, 7 and 9 changed; 11–14 are new.

1. **A record can't have happened after its message.** One that started before and ends after is ongoing, with an `expected` end. A record starting within an hour after its message is that clause's slip: it is proposed as it stands, and the rest of the message keeps its day.
2. **A plan can't start in the past**, unless an explicit past date is given. A plan within an hour before its message is proposed as it stands, not moved to tomorrow.
3. **Hours are 24-hour unless am/pm is written** (owner, 2026-09-29). An hour has one reading. What remains is its day: today or the day before for a record, today or tomorrow for a plan. The most recent record or the soonest plan wins, with no question. One exception: after a night word, a bare hour 1–12 may be the evening one ("tonight at 11" is 23:00).
4. **Day words are relative to the day the message was sent**, not the day open in `/day`: "yesterday", "the previous day", "Friday", "September 7th", "14.10", plus a small Russian and Hebrew table. "Tonight" and "last night" use the 05:00 boundary. **A date names the day a range starts**: "23:00–00:30 on the 31st" ends on the 1st. A range of dates ("30.08 – 06.09") runs from the first day to the last, as whole days when no clock is given. An end word "next day" puts the end on the day after the start.
5. **"Just returned", "back home", "finished", "done" and "ended" pin the end** to the message time or the stated time. "Started", "going to" and "now" pin the start.
6. **A chain with no clock times ends at the message time and runs backwards.** If one clause has a clock time, the chain works outward from it. A later clause's clock takes the reading just after the clause before it when that is within 12 hours, otherwise the nearest before it within 12 hours, so "…before that, 00:33–02:35" lands earlier the same night. A clause with only an end clock that follows another starts where that one ended.
7. **`with` clauses share the referenced clause's interval.** Records of different activities given one written interval without `with` ask how it was split (owner, 2026-09-29).
8. **Start, end and duration, when all three are given, must agree within 5 minutes.**
9. **Edits.** A shift moves both ends. A new start alone moves only the start, unless it lands at or after the block's end; then the whole block moves and keeps its length. A shower planned for 13:15–13:45 and moved "to 15:20" becomes 15:20–15:50, while "sleep start at 04:00" inside 01:13–08:00 moves only the start. A new end alone takes its nearest occurrence after the start. An `end_block` whose block is not on the timeline is that block, ending then.
10. **A record longer than 16 hours is implausible**, unless an explicit date range was written.
11. **A record with only a start** ends after your usual length once that has passed (`assumed`). One still within it stays open.
12. **Plans with no time** ("plan meal prep, eating and a walk after that", "schedule for later: …", a day's intention) are proposed back to back from now, at your usual lengths, in message order (owner, 2026-09-29). Only stated plans with no day word but today: a passing mention, or a day the vocabulary can't read ("after 1 month"), asks instead.
13. **A window** ("somewhere between 20:30 and 22:30") proposes your usual length at its start, never past its end (owner).
14. **Waking with no Sleep open** ("woke up at 11:00") proposes a Sleep ending then, starting at your usual bedtime, or eight hours before when no bedtime is known (owner).

### 6.3 Precision and logical date

Each end carries one of:
- `exact` — a clock time was written;
- `approx` — hedged: "around", "about", "~";
- `inferred` — derived from the message time, a chain or a duration;
- `assumed` — a typical duration filled in;
- `expected` — the end lies in the future.

Each block also gets `logical_date`: the start's calendar date, minus one day when the start is before the boundary. Ledger files stay calendar-dated.

### 6.4 Outcomes

| Situation | Outcome |
|---|---|
| A reading survives | Fact; soft ends marked by precision, ✎ on the receipt |
| Part of the time unknown ("just back from the dog walk") | Fact, with the unknown end `assumed` from your typical duration |
| Mazkir chose the time: an untimed plan, a window, a Sleep from your bedtime | Proposal, with the reason shown |
| A slip within an hour of the message, or a sanity rule fails (implausible length, contradiction, overlaps a stated fact, a Sleep overlap) | Proposal, with the reason shown |
| Several activities given one interval | Question: how was it split? |
| A record with no time at all, an edit whose block isn't found, or no reading fits | Question |

`stated: false` also yields a proposal, but that is §5's question of whether something happened, not when.

*Revised 2026-10-03:* the rows for two surviving readings, and the dominance rule that chose between them, are gone. Under rule 3 an hour has one reading, and the remaining candidates differ only by a day, where the most recent record or soonest plan is the one meant.

### 6.5 Example: #177

"Walked the dog around 3:00 - 3:20, visited two friends at 3:30 - 5:00", sent at 04:17. Hours are 24-hour, so this is tonight: 03:00–03:20 with an approximate start, then a visit from 03:30 still running, expected to end at 05:00. The old agent wrote 15:00 *today*, in the future. Sent at 10:00, the same message is the same night, now over.

*History:* this section first said #177 always asks, then (2026-09-27) that it asks only when neither reading dominates. Both came from reading hours ≤ 12 as 12-hour. The owner writes 24-hour or says am/pm (2026-09-29), which removed the question.

### 6.6 Tests

Table-driven cases from real messages with a frozen "now":
- #177, #180, #194;
- #198 ("ended at 00:30");
- #201 (the 7 Sep night);
- #292 (the eating-then-teeth chain);
- #142 ("back 30 mins");
- 24-hour, typo ("06:35:07:35"), duration ("7hr") and multilingual ("вчера") forms.

Each case asserts intervals, precision per end, logical date and outcome. `tests/test_fast_lane_resolver_owner_rules.py` adds one test per kind of message the labelled replay showed the resolver getting wrong, in generic words.

---

## 7. Resolve and act

### 7.1 Matching evidence to the ledger

For a record R with a placed interval:

| The ledger has | R |
|---|---|
| An open block of the same activity | closes or extends it |
| A planned block of the same activity within ±2 h | confirms it: its times become R's; plan → fact |
| A fact of the same activity overlapping ≥ 50 % | updates it, taking only the ends R states: an `assumed` or `inferred` end never overwrites a known one (later statement wins; pinned via `user_set`) |
| An open block of another activity started earlier | is created, plus a **proposal** to close the open one at R's start |
| An overlapping Sleep block | becomes a proposal with the overlap as reason |
| None of these | is created |

A **plan** P with a plan or proposal of the same activity within ±2 h moves that one to P's times rather than adding a second. An `end_block` with no open or listed block of its activity is created, placed by its end (§6.2 rule 9).

"Same activity" means the `block_resolver` ladder applied to name and activity tag. Edit targets resolve the same way. The candidates are tried in this order:
1. the replied-to message;
2. the day open in `/day`;
3. today.

### 7.2 The habit hook

Registered as a post-hook on every block write: fast lane, agent, `/day` approval, confirmed plan.
- Habit files gain `aliases:` (Workout: "gym"; Tooth brushing: "brush teeth", "teeth"; Dog Walk: "walked the dog").
- **Exact or alias match:** `complete_habit(vault, path, now=<block end>)`. The tick is stamped at the block's time and respects `daily_target`. The completion is recorded on the block, so a block ticks at most once.
- **Fuzzy match:** one-tap confirmation.
- A habit done with no clock time is `tick_habit` and ticks directly; with a clock time it is a block, and this hook ticks it.
- Plans and proposals tick only when confirmed.
- **New-habit suggestion:** an activity on 3 or more distinct days in 14, matching no habit, adds one receipt line. It is shown at most once a month per activity; "not now" is remembered.

### 7.3 Places, people, projects, todos

- **Places:** a list in `data/places.json` (gitignored), holding id, name, aliases in English, Russian and Hebrew, and kind. It is bootstrapped from location names already in the ledger. A known place stores `place_id` on the block. An unknown one is kept as `place_text` and the receipt offers "Add … as a place?". Names only in A; coordinates and arrival triggers come later.
- **People and project** become wikilinks as written; `project` is also stored as its own field.
- **Todos:** `add_todo` → `daily_add_task`, with tags and place. `check_todo` → `set_todo_checked` (section-agnostic, matched by text). `rollover_todos` → `daily_rollover`; with a `target`, only that todo moves, to `time.day`. With no source day written, the source is today when the destination is after today, and yesterday otherwise.
- **The todo hook:** a record block whose activity matches an open todo crosses it out, as the habit hook ticks a habit. The history has the owner asking why a logged "sent the invoice" left its todo open.
- **Task files are not todos:** "#task", "create task" and "complete it" about a task fall through to time-management (owner, 2026-09-29).
- List numbers ("task 1") belong to piece C.

### 7.4 What gets written

| Outcome | Write | Google | `## Schedule` line | Counted |
|---|---|---|---|---|
| Fact | now | synced | yes | yes |
| Scheduled plan | now | synced | yes | as a plan; pending once elapsed, until confirmed |
| Proposal | now, `proposed: true` | no | no | no, until ✓ |
| Question | nothing for that clause | | | |

A question's choices are held server-side under a short id for 30 minutes, because of Telegram's 64-byte callback limit, so a tap writes directly.

### 7.5 Execution

- Every write goes through the existing tool executor and handlers (`create_event`, `update_event`, `daily_add_task`, `set_todo_checked`, `daily_rollover`, `complete_habit`), so the audit log, pinning and cross-date moves behave as today.
- Actions run serially, in message order.
- A failing line shows ✗ with the reason; the others still run.
- Google sync is deferred past the receipt and reported through `receipt_update` (§8).

### 7.6 The action log and undo

- Each fast-lane turn is appended to `agent-turns.jsonl` as skill `fast-lane`, with the actions that ran. Ship 3's turn-trace memory then shows the agent the truth.
- **Undo** reverses a whole turn from snapshots taken at write time. It is refused per line if the item has changed since, and is available for 24 h:
  - created block → deleted, together with its Google entry (via the 2026-09-15 delete route);
  - edited block → prior fields restored;
  - added todo → removed; checked todo → unchecked;
  - habit tick → removed (§9.3).

---

## 8. What you see in Telegram

### 8.1 Stages over SSE

`/message?stream=true` currently sends `{text}` chunks and one `{done, response}`. It gains:

| Payload | The bot |
|---|---|
| `{stage: "Reading…" \| "Placing 3 blocks…" \| "Writing…" \| "Checking your calendar…"}` | updates the rich draft (ephemeral) |
| `{receipt: {...}}` | sends the receipt as a persistent rich message |
| `{receipt_update: {line_id, ...}}` | edits that line in place |
| `{text}` (existing) | streams the skill or agent reply below, as today |

The stream stays open until background syncs settle (15 s cap). Fallthrough turns emit a stage per tool call, in plain words, replacing a silent "typing…".

### 8.2 Receipt layout

These symbols are shared with `/day`: `✓` fact · `◌` scheduled plan · `●` proposal waiting on you · `?` needs one tap.

```
✓ yest 23:15–23:35  Dog walk                          [✎]
  🐕 Dog Walk 2/2 · +5 🪙 · streak 6
  ⏳ calendar        → edited to ✓ in calendar
                                              [ Undo ]
```

- Buttons sit inside table cells, where Telegram draws them compactly (confirmed on device in Ship 5), with plain-text labels.
- `~` marks an approximate or assumed end; `→` with no end marks a block still running. A date other than today is spelled out ("yest", "Fri", "7 Sep").
- Anything unplaced says so ("Watched UFC · no time. Reply with one.") and arms the existing open-question hint.
- The game layer is the habit line: count against target, tokens, streak, and a "longest ever" note, all computed by code.
- Callback data is `rcpt:<turn>:<line>:<action>`: approve, dismiss, edit (the existing block edit view), choice, add place, confirm habit, suggest habit, undo.
- Undo edits the receipt so each line reads "↶ undone"; a line that can't be undone says why.

The server sends structured receipt data; a new `formatters/receipt-rich.ts` draws it without knowing the rules.

---

## 9. Data model changes

### 9.1 Events (`data/events/{date}.json`)

New optional fields; absent on old rows, which keep their meaning:
- `intent: "record" | "plan"`
- `start_precision`, `end_precision`: `exact | approx | inferred | assumed | expected`
- `logical_date`
- `place_id`, `place_text`
- `project`
- `habit_completion`: habit path plus completion timestamp; one per block
- `evidence`: the quoted words and the source message id

### 9.2 Approval (`services/approval.py`)

`resolve_state` gains one rule, placed before the human-source rule: **`intent: "plan"` is `pending` once elapsed, until confirmed**. It is treated like a calendar entry, as intent rather than evidence. A plan still in the future renders `◌` as today. Confirmation, whether by a matching record (§7.1) or a `/day` ✓, sets it approved. Unlike `proposed`, a plan is synced to Google and writes its Schedule line.

The 19 existing blocks written ahead of time are left as they are. Rewriting history is out of scope (§12).

### 9.3 Undoing a habit tick (new capability)

Today tokens only ever go up. `vault.update_tokens` adds to the totals in `00-system/motivation-tokens.md` and to *today's* daily note.

Undo needs `retract_completion(habit_path, completion_ts)`, which:
- removes that completion-log entry;
- restores `streak`, `longest_streak` and `last_completed` from the snapshot taken at tick time, refusing if a newer completion exists;
- deducts `tokens_per_completion` from the totals and from **the daily note of the completion's date**.

Related bug to fix alongside it: when `complete_habit` is called with a past `now`, the token line is still written to today's note, not the completion's date.

### 9.4 Other stores

- `data/places.json` (§7.3).
- Question choices: in memory, 30-minute TTL.
- Undo snapshots: `data/actions/{turn_id}.json`, pruned after 24 h.
- Habit files: `aliases:` in frontmatter.

---

## 10. Failure handling

| Failure | What happens |
|---|---|
| Parse fails or takes over 5 s | Today's router path; logged at ERROR; never the `mazkir` fallback |
| An invalid clause | That clause falls through |
| No reading survives | One question |
| A write fails | ✗ on its line with the reason; the others proceed; nothing is claimed |
| Google sync fails | ⚠ on its line; the block stays in Mazkir |
| Server restart before a choice is tapped | "Expired, send it again" |
| Duplicate Telegram delivery | The turn is keyed by message id; a repeat within 10 min is ignored |
| Rich message rejected | `sendRich` falls back to plain text; lines survive, buttons are lost |
| Anything else | `FAST_LANE=off \| shadow \| on` |

---

## 11. Observability, evaluation, rollout

### 11.1 Spans and logs

- `fast.parse`: model, tokens, input and output.
- `fast.resolve`: readings considered, the winner and why, outcome per clause.
- `fast.act.<kind>`: one per write.
- `fast.receipt`.
- Turn attributes: clause count, outcomes by type, and the fallthrough skill.
- A `fast_turn` log line with the trace id.
- The router ceases to be an unnamed `messages.create` span.

### 11.2 Evaluation: the labelled history is the test set

*Revised 2026-10-03 to describe what A1 built.*

- `data/eval/fast-lane-golden.jsonl` (gitignored; the repo is public) holds about 350 labelled messages: the turn log plus the older conversation files. Each row has the expected route, the fallthrough skill, and clauses with op, intent, stated, name, time words, and the expected outcome and interval. The owner answered the ambiguous rows (2026-09-29). A blind A/B audit of the disputes between label and parse found the label right 50 times to the parse's 2 on actions, and 57 to 4 on the skill.
- `scripts/fast_lane_replay.py` replays each message at its send time:
  - `--resolver-only` puts the labels in place of the parse, for free;
  - `--confirm-cost` runs the real parse, at about $0.007 a message on Haiku 4.5 and $0.017 on Sonnet 5;
  - `--from-results` scores an earlier run's saved parses again, through the current resolver and scorer, for free.
- **Ops that write the same thing count as a match:** `log_block` and `start_block`; `end_block` and an edit that only sets the end; an end with no start, and a block logged by its end.
- The resolver is tested in `pytest`.

**Where it stands (2026-10-03).** Haiku 4.5 over 351 messages. The parse figures predate the last two prompt changes, which no paid run has measured yet.

| Measure | Now |
|---|---|
| Resolver with the labels as the parse: placement / outcome | 82.5 % / 94.9 % |
| Parse recall on tracking clauses | 78.7 % |
| Fallthrough skill / today's router on the same messages | 70.4 % / 83.8 % |
| Wrong-day blocks from the real parse | 11 |
| Parse latency p50 / p95 | 1.7 s / 3.1 s |

On the same 100 tracking messages, Sonnet 5 with thinking off found slightly fewer actions than Haiku (77.0 % against 79.7 %) but placed them better (85.5 % against 76.0 %, no wrong days against 8), at 2.4× the price and 1.7× the latency.

**Gates before `on`:**

| Measure | Target |
|---|---|
| Resolver fixed table | 100 % |
| Parse recall on tracking messages (op, intent, stated) | ≥ 95 % |
| Fallthrough skill vs today's router on the same messages | agrees or better |
| Replay: habit blocks that tick their habit | 26 / 26 |
| Records ending after their message; wrong-date blocks | 0 |
| Shadow: fast-lane turn time, median | ≤ 4 s |

### 11.3 Rollout

1. **Shadow, 3–5 days of real use.** Parse and resolve run concurrently beside today's path and write nothing. They log the receipt they would have sent. A daily diff is reviewed.
2. **On.** Time, habit and todo ops take the fast lane; the rest falls through via the parse's skill choice. The router remains only as the parse-failure fallback.
3. **Retire the router** from the normal path once fallthrough accuracy is measured to be at least equal.

### 11.4 Delivery in two PRs

- **A1: read-only.** Context assembly, the parse, the time resolver, the replay eval, and shadow logging. It writes nothing, so it can run against real traffic from the day it merges.
- **A2: writes.** Matching and acting, the habit hook, places, receipts and stages, undo with habit retraction, the plan intent in `approval.py`, then `on`.

A1's shadow logs are the evidence A2's gates are checked against.

---

## 12. Out of scope for A

- Photo content, task files, priorities, list numbers, knowledge notes and deletes. They fall through (photos are placed by EXIF only).
- Place coordinates, arrival triggers, live location, the place view.
- Sleep proposals from silence windows; the morning and weekly readouts.
- Rendering the daily note from the ledger (the 12/77 mismatches). A separate fix.
- Repairing past data: the 6–7 Sep night still filed on 8 Sep, the 19 plans counted as facts, the 165 unpaid tokens. Each is a one-off job to offer separately.
- Pieces B, C and D.

---

## 13. Verify during planning

- The token ledger's exact write paths for `retract_completion` (§9.3), including the transaction line in the daily note.
- Whether caching measurably cuts latency. The prompt with the skill catalog is about 5k tokens, above Haiku 4.5's 4,096-token cache minimum.
- That `messages.parse()` (the SDK's validating helper) or the existing `output_config` plus `json.loads` pattern in `claude_service.py` handles the `anyOf`-null schema. Match the router's current style.
- The logical-day boundary: 05:00 by default; confirm it against the reconstructed sleep data.
- Idempotency key: confirm the bot can pass Telegram's `message_id` on `POST /message`.

---

## 14. Docs updated in the implementation PR

- `docs/specs/2026-08-21-time-management-phase2-capture-design.md`: the ship list is rebuilt around pieces A–D. §13 already records the 4b/7 overlap that led here.
- `CLAUDE.md`:
  - the §1.1 wording as the project overview;
  - correct "up to 42 times a day" (the 42 were pytest fixtures; the real peak was 9, on 2026-09-12);
  - remove the stale "`capture` skill" line;
  - describe the fast lane, receipts, precision fields, plan intent and the habit hook.
- `memory/00-system/skills/time-management.md`: the time rules now live in code for the fast lane; the skill prompt keeps them for fallthrough and agent turns. This is a vault edit, made only with your go-ahead.

---

## Appendix: pieces B, C and D in one paragraph each

**B — One agent.** The router and five tool-limited skills become one Sonnet agent with every tool. Tool search defers the definitions until needed. Skills become instructions it loads on demand, and it gets a plan/to-do tool so multistep work is visible as it runs (the Claude Code feel). Short answers to its own questions return to it. It receives the fast lane's action log and never redoes it. Deep work (web search, bash, MCPs, its own source) is this agent in a longer mode.

**C — Preview.** A stored pending plan, with one Telegram preview for batches of edits ("move gym −30m, and 2 was dev"): ✓ ✕ per line, Approve all, and dependencies between lines. List numbers resolve in code against the list the bot last drew.

**D — Judgment.** Statements you volunteer beyond the timeline:
- whether a fact deserves an action (a reminder, a follow-up);
- habits recognised from prose beyond aliases;
- past vs planned where the words don't say.

Everything D infers lands as a proposal, never a write. The best published system decides when to help at 66 % F1.
