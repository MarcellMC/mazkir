# Ship 3 — The agent can't deny its own work (Design)

**Status:** Implemented. All seven plan tasks landed on `feat/ship3-agent-action-memory`, reviewed and merge-ready.
**Plan:** `docs/superpowers/plans/2026-09-05-ship3-agent-action-memory.md`
**Parent:** `docs/plans/2026-08-21-time-management-phase2-capture-design.md` §2 ship 3, §9. That doc owns the interaction model across all nine ships; this one owns Ship 3.
**Ship 1 shipped:** PR #9 (`3eb8b2c`), vault commit `fb824da`.
**Ship 2 shipped:** PR #11 (`934c003`).

## 1. What this ship is

The agent reasons about its own past using the current turn's capabilities. Ship 3 makes the past factual: what it actually did arrives in the prompt unasked, and a prompt invariant forbids denying an action without checking.

No new user-facing surface. No new tools. The whole ship is a reader for data that is already being written, plus three lines of prompt.

It is sequenced before Ship 4 (NL logging) deliberately. Every write path inherits this failure mode, and Ships 4 and 5 add several. An assistant that logs your sleep and then denies logging it is worse than one that never logged it, because you will log it twice — which is exactly what happened to the two todos on 2026-08-20.

## 2. The failure, precisely

Turn 1 routed to `time-management`, which holds `daily_add_task`. Both writes succeeded.

Turn 2 — *"where did you add those?"* — is a question, so the router sent it to `mazkir`, whose tool list has no task-creation tool. The agent inspected its **current** tools, found none, and reasoned backwards to *"I actually didn't add them."* Then it added them again, producing duplicates.

**One iteration. Zero tool calls.** It held `read_daily_section` and `get_daily` in that very skill and used neither.

Two conclusions follow, and both shape the design.

**This is not a capability gap.** The agent had two ways to check and checked with neither. Any fix that adds a *third* way to check — a tool it must first decide to call — leaves the failing decision untouched. The fix has to be push, not pull.

**Conversation memory stores what the agent said, never what it did.** `save_turn` (`memory_service.py:86`) takes `user_msg` and `assistant_msg`; `_parse_messages` (`:134`) matches only `### HH:MM [user|assistant]`. So a skill hop silently rewrites the agent's sense of its own past, because nothing in context contradicts the inference.

## 3. Where the trace comes from

### 3.1 `agent-turns.jsonl` is the store

`agent_service.py:1498` already builds a rich `tools_audit` per call — name, sanitized params, confidence, reasoning, `result_summary`, `confirmed`, and `pending` for gate-blocked calls. It reaches `data/logs/agent-turns.jsonl` and the OTel span, and nothing reads it. **Ship 3 is largely giving it a reader.**

An earlier draft proposed a second store at `data/turns/{date}/{chat_id}.jsonl`, on the theory that a rotating log is unfit for memory. The measurement killed it:

```
698 turns · 493 KB · 2026-05-02 → 2026-09-02     (~700 B/turn, ~175 turns/month)
```

The 10 MB rotation threshold is roughly **14,000 turns — about seven years** at this rate, with five backups behind it. A second store would have been a duplicate of a file that already holds exactly this.

Two consequences, both accepted:

- **A log is not a database.** The reader tolerates a torn final line, a missing file, and unparseable rows: per-line `try`/`except`, skip what won't parse. Losing one turn's trace is the failure mode, not a crash.
- **Deleting `data/logs/` now costs the agent its memory of its own actions.** This is a real new coupling and is named rather than hidden. Degradation is graceful — no trace means no trace, and §5's invariant holds independently. The prompt rule is the safety net; the trace is what makes it cheap.

### 3.2 Rejected: Phoenix MCP as a tool

Considered and declined for this ship. Traces already carry `skill.name`, tool I/O and timings, and exposing them as an agent tool is genuinely attractive — but it is pull-based, and §2 established that the failing decision was *whether to check at all*. Adding a third way to check does not fix not checking. It also makes a dev observability stack load-bearing for correctness rather than debugging.

Where it does win is the question the window cannot answer — *"what did I do last Tuesday?"*, beyond 20 messages, across sessions and skills. **Filed as a candidate ship of its own.** Push makes the recent past unforgettable; pull makes the distant past reachable.

### 3.3 Rejected: writing traces into the conversation note

The conversation note (`memory/00-system/conversations/{date}/{chat_id}.md`) is an Obsidian-readable artifact. Writing tool traces into it was rejected: the vault stays clean, and the log already holds the data. This concerns *persistence* only — §4.1 still attaches the trace to the assistant message when assembling the prompt in memory. Nothing is written to the note.

The repo split is **not** an access boundary. `vault_path` and `logs_dir` are both plain config (`config.py:22`, `:61`) in one process on one machine. What is missing is a *tool* — and injecting at `assemble_context` needs none. The server reads the file and puts the text in the prompt. The agent never asks.

## 4. Interleaved, joined by consumption order

### 4.1 Shape

Each turn's trace attaches to **that turn's assistant message**, not as a separate message:

```
Added both to today's note.

[Tools I called this turn, as time-management:
   daily_add_task(text="Order dog food") → ok
   daily_add_task(text="Bring the bicycle to repair shop") → ok]
```

Appending to the assistant turn keeps the `messages` array strictly alternating — which the existing code visibly takes care to do, pairing the summary injection at `agent_service.py:1096` with a synthetic *"Understood, I have the prior context"* ack. It is also semantically right: the assistant is reporting its own turn, not the user narrating it.

**Why interleaved over one flat block.** A flat list requires the model to bind each call to a turn by timestamp. That binding is cheap for an LLM — attention reaches any position in one step, so it is nothing like a human's linear scan — but it is not free in *reliability*: binding degrades with distance and with similarity, and two `daily_add_task` calls a minute apart with similar params are precisely the case where attribution slips. Interleaving does not help the model *find* the trace; it removes the need to decide what the trace belongs to.

Cost and caching do not separate the options: only `cache_static_prefix` carries `cache_control` (`claude_service.py:59`). The `messages` array and the dynamic system tail are both re-sent uncached every turn.

### 4.2 The join

The two sequences — message-pairs in the note, turn records in the log — must be matched without a shared id.

**They pair reliably.** Every path (normal, confirmation-pause, confirmation-resume) funnels through `_run_agent_turn`, which calls `save_turn` then `_emit_turn_audit` with the **same `original_text`** (`:1531`/`:1541`, `:1586`/`:1598`). One note pair ↔ one log record, same order, byte-identical user string.

**Match on `user_text`, consume in order.** Walk the note's pairs oldest→newest, consuming that chat and date's log records chronologically. Exact string equality — *not* timestamp. Duplicate user texts (`"yes"`, `"ok"`, `"continue"` — common at confirmation gates) are disambiguated by consumption order rather than content.

**Align from the tail.** Decay truncates the note only from the *front*; the log keeps everything. The sequences agree at the recent end and diverge at the old end, which is the end being windowed away anyway.

**A mismatch omits the trace; it never guesses.** This is the ship's one non-negotiable property. The bug is the agent asserting something false about its own past — attaching the *wrong* trace would be a worse version of the same bug, dressed as evidence.

Ordered consumption also absorbs the real desync: `save_turn` runs *before* `_emit_turn_audit`, so a crash between them leaves a note pair with no record. Consumption skips it and carries on. A strict lockstep walk would stall there and lose everything older.

### 4.3 Out of scope: the note's timestamps

`_parse_messages` matches `### \d{2}:\d{2}` but never **captures** it — no group. So `summarize_and_decay` cannot preserve the original time and re-stamps every kept message with the moment decay ran:

```python
time_str = now.strftime("%H:%M")  # Approximate — exact times lost
```

The comment is from the 2026-03-02 plan that prescribed this code; it was dropped on the way into commit `4858aa0`, which is why the line now reads as an unexplained bug rather than a stated trade-off. The fix is small — capture the group, carry it, write it back.

**It stays out of Ship 3**, because §4.2's join uses `user_text`, not timestamps. Filed separately.

## 5. What the trace renders as

**Not the log record.** Measured: `tools[]` is **p50 308 B, p90 1.2 KB, max 8.7 KB** per turn. `_summarize_result` truncates only one level deep — `data` is a dict and passes through whole, which is why full note bodies appear in the log. Injecting raw would re-bill kilobytes of note content every turn.

One rendered line per call: name, identifying params, outcome. `_sanitize_params` already strips `_`-prefixed fields and truncates strings at 200; the renderer caps further.

Four outcome forms:

| Form | Meaning |
|---|---|
| `→ ok` | executed, succeeded |
| `→ AMBIGUOUS_MATCH` | executed, failed — the error code, not prose |
| `→ proposed, awaiting confirmation — NOT executed` | gated, never ran |
| `→ failed` | executed, failed, but the result carries no `error.code` to name it — the fallback for a result that is a dict but has neither `ok: true` nor a coded `error`. Reachable in practice: `tool_executor.execute_tool` returns a bare `{"error": str(e)}` on a handler exception and `{"error": f"Unknown tool: ..."}` for an unregistered tool name, neither of which is an `{"code": ...}` dict. |

**The third form is the mirror of the mirror.** A gate-blocked `delete_task` the user never answered must not read as done. Fixing false denial by manufacturing false claims would violate the invariant Phase 1 already established.

**A turn with no calls renders `[Tools I called this turn: none]`.** It costs a few tokens and buys the distinction between *"I called nothing"* and *"no record survived the join"*. Since §4.2 makes unmatched pairs silent, absence would otherwise be ambiguous — and a model reasoning confidently from ambiguous absence is the entire bug.

## 6. The mirror invariant

§3.4 of the parent design forbids *claiming* a write the tool result does not confirm. It says nothing about *denying* an unchecked one. Three lines join `_static_guidelines` beside the existing *"Never report an action as done unless the tool result says ok: true"*:

- **Never deny a past action without checking.** The `[Tools I called this turn]` blocks record what you actually did.
- **Your current tool list is what you can do now, not what you did earlier.** Skills change between turns — a tool absent from your list now may have been available when you acted.
- **No trace block means no record, not proof of inaction.** Use a read tool before denying.

The second line states the root cause directly: the agent did not lack information, it consulted the wrong source and trusted it.

These sit in the **cached** static prefix, so they cost nothing per turn.

## 7. `skill` in the audit record

`_emit_turn_audit` is called inside `_run_agent_turn`, which never learns which skill it is running as — `skill.name` reaches only the OTel span (`skill_executor.py:133`). Its absence made the original diagnosis materially harder.

Thread the skill name through `_run_agent_turn` and record it. Once the log is memory rather than audit, this stops being a debugging nicety: it is what lets a trace say *"as time-management"*, the concrete form of §6's second rule. The agent sees it was operating under a different tool set instead of inferring, wrongly, that it never had one.

## 8. Testing

**The join** carries most of the risk and most of the tests: clean alignment; duplicate `user_text` disambiguated by order; a note pair with no log record (the `save_turn`-then-crash window); a decay-truncated note against a full log; empty log; missing file; a torn final line.

The invariant asserted throughout: **a mismatch yields a missing trace, never a wrong one.**

**The rendering:** each outcome form, `none`, and that a `save_knowledge` carrying a full note body does not blow the line budget.

**The regression test** reconstructs 2026-08-20 — a turn calling `daily_add_task` twice under `time-management`, then *"where did you add those?"* — and asserts the assembled messages carry both calls. It cannot assert the model's behaviour; it pins the context, which is the half we control.

**The prompt:** assert the three guideline strings are present in the static prefix.

## 9. Out of scope

- **Note timestamp capture and decay re-stamping** (§4.3) — real, filed separately, not needed by this join.
- **Phoenix as an agent tool** (§3.2) — a candidate ship of its own.
- **Sourcing the message window from the log instead of the note** — `agent-turns.jsonl` already holds `user_text`, `assistant_text` and `tools` in one record, so reading the window from it would make the join not exist rather than solve it. That changes the note from machine input to human artifact, and moves `summary`/decay with it. The right eventual direction, too large for this ship.
- **Issue #10** — two unreachable parser residuals in `daily_tasks._parse_task_content`, deferred.
