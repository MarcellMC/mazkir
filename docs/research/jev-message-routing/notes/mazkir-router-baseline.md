# Mazkir message router: baseline as of 2026-09-26, and what Ships 7 and 4b require of it

Scope: how an incoming Telegram message is routed today (model, prompt, output, latency, cost, failure modes), measured from local logs and Phoenix traces, plus what the planned Ships 7 and 4b need from "quick classification and deciding the next action". All measurements are read-only extractions. Logs end at 2026-09-23 23:32 +03:00 and the newest Phoenix `agent.handle_message` span is from the same minute, so no traffic from 2026-09-24 to 2026-09-26 appears in either source.

Source key used below:
- Code: `apps/vault-server/src/services/{router_service,claude_service,skill_executor,skill_registry,agent_service}.py`, `apps/vault-server/src/{main,config,tracing_setup}.py`, tests in `apps/vault-server/tests/`.
- Skills: `memory/00-system/skills/*.md` (vault repo).
- Logs: `data/logs/vault-server.jsonl` (22,845 lines, 2026-04-30 → 2026-09-23), `data/logs/agent-turns.jsonl` (828 records, 2026-05-02 → 2026-09-23).
- Phoenix: local project `mazkir`, pulled with `px span list` (LLM spans, and spans named `agent.handle_message`) on 2026-09-26. "Last 2 weeks" = spans since 2026-09-12T00:00Z: 226 LLM spans, 96 `agent.handle_message` spans. Historical pull since 2026-05-01: 249 Haiku spans, 451 `agent.handle_message` spans.
- "Real" traffic = chat_id <your-chat-id>. The same log file also holds pytest output (fake chat_ids 99999999/999999/88888888, and fixture messages like "LLM down" or "nonsense"), and I filtered that out. In Phoenix, 30 zero-duration `agent.handle_message` spans on 2026-09-13 with no router child are test runs and are excluded.
- "Post-fix" = after the structured-output router fix, commit `50d9971` (2026-09-13 22:01 +03:00), deployed by the 22:11 restart. That leaves n=28 real routed turns, which is small.

---

## 1. How routing works end to end today

### Takeaway
Every non-confirmation message makes exactly one serial Claude Haiku 4.5 call (`claude-haiku-4-5-20251001`, max_tokens 128). The call uses structured output (`output_config.format` json_schema) whose `skill` field is an enum of the 5 skill names, plus a free-text `reason`. The chosen skill then runs its own Sonnet 4.6 tool loop. The only way to reach a second skill is for that skill to write a `next_skill: <name>` token in its reply, sequentially and capped at 3 skills per turn. Any router exception falls back to `mazkir`, which has no write tools except the daily-journal ones.

### Cited Findings
**Call path**
- `handle_message` opens the `agent.handle_message` AGENT span and runs `_handle_message_inner`. That calls `memory.assemble_context(chat_id)`, builds the messages, then goes to `_handle_via_skills` → `SkillExecutor.run` whenever both a skill registry and a router are configured. Otherwise it uses a legacy single-loop path with all tools loaded. — [agent_service.py:1227-1380](file:///home/marcellmc/dev/mazkir/apps/vault-server/src/services/agent_service.py)
- The router only exists when an Anthropic key is configured: `if settings.anthropic_api_key: claude = ClaudeService(...)`, then `RouterService(claude=claude, fallback_skill="mazkir")`. — [main.py:70-138](file:///home/marcellmc/dev/mazkir/apps/vault-server/src/main.py)
- `SkillExecutor.run` calls `router.pick(user_msg=user_msg, recent_messages=context_messages[-10:], skills=registry.list())` once per turn, before any skill runs. — [skill_executor.py:~90-97](file:///home/marcellmc/dev/mazkir/apps/vault-server/src/services/skill_executor.py)
- Confirmation replies (`POST /message/confirm` → `handle_confirmation`) resume the paused loop and never call the router. — [agent_service.py handle_confirmation](file:///home/marcellmc/dev/mazkir/apps/vault-server/src/services/agent_service.py)

**Model and request shape (`ClaudeService.create_router_choice`)**
- Model: hard-coded `"claude-haiku-4-5-20251001"`, `max_tokens=128`, and no `cache_control`. It is not configurable. `config.claude_model` exists but the router does not read it. — [claude_service.py:113-177](file:///home/marcellmc/dev/mazkir/apps/vault-server/src/services/claude_service.py), [config.py:27](file:///home/marcellmc/dev/mazkir/apps/vault-server/src/config.py)
- System prompt: "You are a router for the Mazkir personal assistant. Pick exactly one skill to handle the user's new message." It is followed by a catalog built from each skill's frontmatter (`- name: description\n  use when: when_to_use`) and ends "Pick the single best match. When uncertain, pick 'mazkir'." Measured at about 1,876 characters in Phoenix. — [claude_service.py](file:///home/marcellmc/dev/mazkir/apps/vault-server/src/services/claude_service.py); Phoenix router spans post-fix
- Context: a single `user` message reading `"Recent conversation:\n{role}: {content}\n...\n\nNew message to route:\n{user_msg}"`. It covers the last 10 messages of the sliding window, keeps only string contents (image blocks are dropped), and quotes them rather than replaying them as turns. — [claude_service.py](file:///home/marcellmc/dev/mazkir/apps/vault-server/src/services/claude_service.py)
- Output schema (verified from `llm.invocation_parameters` on post-fix spans): `{"type":"object","properties":{"skill":{"type":"string","enum":["engineering","knowledge-management","mazkir","motivation-management","time-management"]},"reason":{"type":"string"}},"required":["skill","reason"],"additionalProperties":false}`. The reply is read with `json.loads(response.content[0].text)`. — Phoenix span `messages.create`, 2026-09-23; [claude_service.py](file:///home/marcellmc/dev/mazkir/apps/vault-server/src/services/claude_service.py)

**What the router sees and does not see**
- `user_msg` is `log_text`, not the enriched content the skill receives. Photos arrive only as `(photo: <filename>)`, and a location only as coordinates. Reply context is cut to the first 50 characters: `(replying to {from}: "{reply_to['text'][:50]}")`. The router gets no `forwarded_from`, no `selected_date` and no image. The skill receives all of these through `_build_user_content`. — [agent_service.py:1318-1335, 1989-1991](file:///home/marcellmc/dev/mazkir/apps/vault-server/src/services/agent_service.py)
- The router transcript does include Ship 3 turn-trace records (`[Record of your previous reply — tools that actually ran …]`), because `assemble_context` attaches them to user messages in `context.messages`. 22 of 28 post-fix router inputs contained one. The newest reply's trace (`trailing_trace`) goes only to the skill. — Phoenix post-fix router spans; [memory_service.py assemble_context](file:///home/marcellmc/dev/mazkir/apps/vault-server/src/services/memory_service.py)

**Validation and fallback (`RouterService.pick`)**
- A failed call or an exception (including a `json.loads` failure) returns `RouterDecision(skill="mazkir", reason="fallback: router error (...)")`. A skill missing from the registry returns the fallback with "router picked unknown skill". Both log at ERROR, a level raised from WARNING in `50d9971`. The code comments that "the fallback skill may lack the tools this message needs, and a skill without the tool is where a reply claiming work that never ran comes from". A success logs `router_pick` at INFO with the `skill` and `reason` fields. — [router_service.py](file:///home/marcellmc/dev/mazkir/apps/vault-server/src/services/router_service.py)

**Skill loop and hops**
- `MAX_HOPS = 3`. `visited` is a list: if the active skill is already in it, a cycle is logged at WARNING and the loop stops. An unknown skill stops it too. Each hop opens a `skill.<name>` span carrying the attributes `skill.previous`, `skill.routing_reason` and `skill.next_skill`. — [skill_executor.py](file:///home/marcellmc/dev/mazkir/apps/vault-server/src/services/skill_executor.py)
- A handoff is parsed with `re.search(r"next_skill:\s*([a-z_-]+)", response_text)` and accepted only when the name is in that skill's `next_skills` allow-list. A turn paused for confirmation (`stop_reason == "needs_confirmation"`) never hands off. A hop overwrites `response_text`, so the user sees only the last skill's reply. — [skill_executor.py](file:///home/marcellmc/dev/mazkir/apps/vault-server/src/services/skill_executor.py)

**Skills (vault `memory/00-system/skills/`, last changed 2026-09-13)**

| skill | model | max_iter | tools | next_skills |
|---|---|---|---|---|
| mazkir (fallback) | claude-sonnet-4-6 | 8 | 12: read tools plus `attach_to_daily` and `edit_daily_section` | time-management, knowledge-management, motivation-management |
| time-management | claude-sonnet-4-6 | 10 | 26: all task/habit/goal/event/daily-tier tools | mazkir, knowledge-management |
| knowledge-management | claude-sonnet-4-6 | 5 | search/read/get_related/save_knowledge | mazkir, time-management |
| engineering | claude-sonnet-4-6 | 5 | list_* and propose_coding_session | mazkir |
| motivation-management | claude-haiku-4-5 | 3 | get_tokens | mazkir |

— [mazkir.md](file:///home/marcellmc/dev/mazkir/memory/00-system/skills/mazkir.md), [time-management.md](file:///home/marcellmc/dev/mazkir/memory/00-system/skills/time-management.md), [knowledge-management.md](file:///home/marcellmc/dev/mazkir/memory/00-system/skills/knowledge-management.md), [engineering.md](file:///home/marcellmc/dev/mazkir/memory/00-system/skills/engineering.md), [motivation-management.md](file:///home/marcellmc/dev/mazkir/memory/00-system/skills/motivation-management.md)

- The `mazkir` prompt tells it to hand off writes it does not own with an explicit token: task/habit/goal/event writes go to `next_skill: time-management`, and durable notes go to `next_skill: knowledge-management`. — [mazkir.md](file:///home/marcellmc/dev/mazkir/memory/00-system/skills/mazkir.md)
- History: the router was added 2026-06-03 (`98c1a8a`, `72738f5`) with the fallback `manager`. The skills were redesigned 2026-06-20 (`5386375` in the vault), replacing capture/manager/recall with domain skills, and the fallback became `mazkir` (`88e3b0f`). Engineering was added 2026-07-27. — `git log` of the monorepo and vault
- Stale doc: root CLAUDE.md still says "The `capture` skill now includes `create_event`", but no `capture.md` exists. It was removed on 2026-06-20. — [CLAUDE.md](file:///home/marcellmc/dev/mazkir/CLAUDE.md); directory listing of `memory/00-system/skills/`

### Inferences
- The router is a pure single-label, 5-way classifier over whole messages, and routing never looks at the content of what gets decided downstream. The `reason` string is logged and put on the skill span, but no code consumes it.
- Because the router sees less than the skill (50-character reply excerpt, no image, no forwarded content, no selected date), a reply-driven or photo-driven message can be routed on thinner evidence than the skill will later have.
- `RouterService` depends on a duck-typed `claude.create_router_choice(user_msg, recent_messages, skill_catalog) -> {"skill","reason"}`. That is the natural seam for a drop-in replacement.

### Gaps
- Whether `next_skill:` tokens ever leak into user-visible text: they are only overwritten when a hop happens. I found no stripping code, but I did not check the bot's rendering.

---

## 2. What CLAUDE.md says about the router, and whether the "42 a day" figure holds

### Takeaway
CLAUDE.md (2026-09-13) says that before structured output the router "sometimes continued the chat instead — on most days since June, up to 42 times a day". The failure mode is real and structured output fixed it: 0 fallbacks in 28 post-fix turns. But the "42 a day" and "most days" figures do not survive checking. The 42 matches 2026-08-09's count of router-failure log lines, and all of those were pytest fixtures. Real production fallbacks peaked at 9 in a day, on 10 distinct days.

### Cited Findings
- CLAUDE.md text: the router's answer is structured output; before, it "was only asked for JSON while sitting mid-chat in the assistant's seat, and it sometimes continued the chat instead — on most days since June, up to 42 times a day — each miss silently routed to `mazkir`, which has no write tools. That is how 'log reading 06:35–07:35' reached a skill that could only claim to have logged it." — [CLAUDE.md](file:///home/marcellmc/dev/mazkir/CLAUDE.md)
- The fix commit `50d9971` (2026-09-13) says the router "was asked for JSON but not held to it, and it received the chat as alternating turns". On 09-13 at 08:05 and 12:30 it "wrote a full 'Logged! ... [Tools I called this turn ...]' reply, json.loads failed, and both turns were silently routed to mazkir". Replaying those inputs through the new code "returns time-management for both". — `git show 50d9971`
- Before the fix, router calls were plain `messages.create` with only `{"max_tokens":128}`. After it, the calls carry `output_config`. Phoenix, 2026-09-12 onward: 39 pre-fix router spans, 28 post-fix. — Phoenix `llm.invocation_parameters`
- **Checking "42 a day":** on 2026-08-09 `vault-server.jsonl` has exactly 42 router-failure lines. All of them are test fixtures: 21 × "Router picked unknown skill 'nonsense'" and 21 × "Router LLM call failed: LLM down". Only 4 real messages arrived that day. — [vault-server.jsonl](file:///home/marcellmc/dev/mazkir/data/logs/vault-server.jsonl)
- Real JSON-parse fallbacks per day (log, chat <your-chat-id>): 06-03: 1, 06-20: 1, 08-11: 2, 08-12: 1, 08-20: 1, 09-02: 2, 09-08: 5, 09-10: 2, 09-12: 9, 09-13: 6. That is 30 lines in total, 29 of them inside real message traces. — [vault-server.jsonl](file:///home/marcellmc/dev/mazkir/data/logs/vault-server.jsonl)
- Phoenix agrees in shape. Of 225 router spans since 2026-06-03, 24 real outputs were prose with no JSON (chat continuation), on 7 of 43 days with router calls, peaking at 8 on 2026-09-12. Another 154 were ```` ```json ```` fenced, which the old "robust JSON extraction" (`fae6e59`, 2026-06-03) could parse, and 30 were bare JSON. — Phoenix Haiku spans since 2026-05-01
- Pre-fix output shape, 2026-09-12/13 (n=39): 25 fenced JSON (8 of them hit the 128-token cap), and 14 prose chat continuations (4 hit the cap). The prose share was therefore about 36% in the two days before the fix. — Phoenix
- The failure became more frequent in September. In 2026-09-10..13 before the fix, 17 of 45 routed turns (38%) fell back, against about 13% (29/216) of all pre-fix routed real turns since June. — vault-server.jsonl

### Inferences
- The failure was real, clustered in September, and plausibly got worse as turn-trace text in history taught the model that replies end with a tool record (the forged-record behaviour CLAUDE.md describes). "Up to 42 a day" and "most days since June" should be read as about 9/day max and about 10 days. CLAUDE.md overstates the magnitude by roughly 4–5×.
- Structured output removed the parse-failure class completely in the observed window. Any replacement model therefore has to guarantee valid, enum-constrained output (grammar-constrained decoding or equivalent) to avoid bringing this class back.

### Gaps
- Whether the September rise was caused by the turn-trace records in history is plausible but was not tested.

---

## 3. Measured router latency, tokens, cost, and share of a turn

### Takeaway
Post-fix, the router call takes **p50 1.95 s / p90 2.57 s / p95 2.75 s** (Phoenix, n=28). It uses **p50 1,310 input and 56 output tokens** and costs about **$0.0015 per turn**. It starts about 8 ms after the turn begins and blocks everything else, so it accounts for **p50 20% / p90 38% / p95 43% of `agent.handle_message` wall-clock** (turn p50 9.2 s, p95 16.5 s). In money it is only about 3.5% (p50) of a turn's LLM cost. Latency, not cost, is the router's price.

### Cited Findings
Phoenix router spans (`messages.create`, Haiku, max_tokens 128), with durations matched to the parent `agent.handle_message` trace:

| window | n | router p50 / p90 / p95 (s) | turn p50 / p90 / p95 (s) | router share of turn p50 / p90 / p95 | input tok p50 / p95 | output tok p50 / p95 |
|---|---|---|---|---|---|---|
| since 09-12, all | 67 router / 66 matched | 1.72 / 2.52 / 2.65 | 8.77 / 15.86 / 17.96 | 20.5% / 38.8% / 42.6% | 1,141 / 1,569 | 68 / 128 |
| post-fix (≥09-13 22:11 +03) | 28 | **1.95 / 2.57 / 2.75** (min 1.29, max 3.02) | **9.20 / 15.78 / 16.47** | **20.2% / 37.9% / 42.5%** (mean 22.9%) | 1,310 / 1,617 (max 1,656) | 56 / 70 (max 87) |
| pre-fix (09-12..13) | 39 | 1.62 / 2.22 / 2.54 | 7.91 / 16.19 / 18.87 | 20.7% / 38.5% / 41.8% | 1,114 / 1,429 | 95 / 128 |

— Phoenix project `mazkir`, `px span list` (LLM spans since 2026-09-12)

- Where the router sits in the turn: its span starts 6–17 ms (p50 8 ms) after `agent.handle_message` starts. — Phoenix
- The log-based cross-check agrees. For the log interval `message_received` → `router_pick` (context assembly plus the router), the last 14 days give p50 1.84 s, p95 2.72 s (n=56), and post-fix gives p50 1.96 s, p95 2.76 s (n=28). The whole-history log interval is p50 1.75 s, p95 3.03 s, max 10.26 s (n=187). HTTP-level turn time (`message_received` → `message_responded`), post-fix: p50 9.20 s, p95 16.47 s. — [vault-server.jsonl](file:///home/marcellmc/dev/mazkir/data/logs/vault-server.jsonl)
- Post-fix skill phase: each skill LLM call (Sonnet 4.6) takes p50 2.85 s, p95 6.34 s. Skill LLM calls per turn: p50 2, p95 4. Skill prompt tokens per call: p50 9,089, p95 11,766, with p50 3,143 served from cache. Summed skill LLM wall time per turn is p50 7.3 s. Non-LLM time (tools, context, I/O) is p50 about 0.4 s. — Phoenix (skill-call stats cover all turns since 09-12, n=159 calls)
- The `reason` output field is p50 174 characters (post-fix `router_pick` logs), and completion tokens are p50 56. So `reason` is nearly all of the router's output, since the skill name itself is only a few tokens. — vault-server.jsonl; Phoenix
- Pricing: Haiku 4.5 costs $1/MTok input and $5/MTok output ($0.10 cache hit). Sonnet 4.6 costs $3/$15 ($0.30 cache hit, $3.75 5-minute cache write). — [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- Cost per post-fix turn (tokens from Phoenix × the list prices above): router p50 $0.0016, skills p50 $0.041 (max $0.080). The router is p50 3.5% / p95 16.5% / mean 5.5% of a turn's LLM spend. — Phoenix + [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- Volume is low. Post-fix there were 28 routed turns in about 10 days. The busiest day on record was 29 agent-turn records (2026-09-12). Since June 3 there were 225 router calls in total (Phoenix). — [agent-turns.jsonl](file:///home/marcellmc/dev/mazkir/data/logs/agent-turns.jsonl); Phoenix
- Streaming forwards only the final iteration's text (P5), so the router's ~2 s adds directly to time-to-first-visible-token on every turn. — [CLAUDE.md](file:///home/marcellmc/dev/mazkir/CLAUDE.md) streaming section; [skill_executor.py](file:///home/marcellmc/dev/mazkir/apps/vault-server/src/services/skill_executor.py)

### Inferences
- At this volume, about 3 turns/day at ~$0.0016 each, the router costs under $0.01/day. A cheaper router saves nothing that matters. A faster one could save up to ~2 s (about 20% of a median turn, and up to ~40% of short turns) on every message.
- Much of the router's generation time goes to the free-text `reason`. Shrinking it (an enum only, or a short reason) is a no-provider-change latency lever worth benchmarking against any "Jev" number, so that a comparison is like for like.
- Post-fix latency is about 0.3 s higher at p50 than pre-fix despite fewer output tokens. Candidate causes are the larger inputs (1,310 vs 1,114 tokens) and structured-output overhead. With n=28 against 39, this is not established.
- An apples-to-apples baseline for a Jev comparison: **~1.3 k input tokens (a ~1.9 k-character system catalog plus a ~1.75 k-character quoted transcript), a 5-value enum output, p50 ~1.95 s / p95 ~2.75 s end-to-end from Israel to the Anthropic API.**

### Gaps
- Phoenix does not record time-to-first-token for the router, only total span duration, and the router call is not streamed.
- The sample is small (n=28 post-fix) and covers only 2026-09-13 → 09-23. Percentiles above p90 are fragile.
- Network location and API region affect latency. Only end-to-end duration was measured, not queueing versus generation.

---

## 4. Routing accuracy signals: fallbacks, hops, wrong picks

### Takeaway
Post-fix: 0 fallbacks, 0 `next_skill` hops and 0 `mazkir` picks in 28 routed turns (24 time-management, 4 knowledge-management), and no evident misroutes. Pre-fix, fallbacks were the dominant routing error: 29 real turns. Every one of the 11 hops observable in `agent-turns.jsonl` was the `mazkir` fallback recovering by handing off. `next_skill` has in practice been a recovery path, not a feature. No labelled accuracy dataset exists.

### Cited Findings
- Real routed turns in the log, all history: time-management 96, capture 23 (a pre-June-20 name), engineering 21, knowledge-management 20, manager 15 (pre-June-20), mazkir 10, recall 3; FAIL 29; 32 turns had no router log line (confirmations or pre-router turns). Motivation-management was never picked. — [vault-server.jsonl](file:///home/marcellmc/dev/mazkir/data/logs/vault-server.jsonl)
- Last 14 days (≥09-10, 73 real turns): time-management 46, FAIL 17, knowledge-management 6, engineering 4. Post-fix (28): time-management 24, knowledge-management 4. — vault-server.jsonl; the Phoenix post-fix outputs match (24 time-management / 4 knowledge-management, all valid JSON)
- `agent-turns.jsonl` began recording `skill` in Ship 3. Consecutive records with the same `user_text` and different skills show 11 hops: mazkir→time-management 10, mazkir→knowledge-management 1. `next_skill:` appears in assistant text 20 times, including in pre-Ship-3 records. — [agent-turns.jsonl](file:///home/marcellmc/dev/mazkir/data/logs/agent-turns.jsonl)
- Joining the 29 fallback turns to agent-turn records gives these outcomes:

  | outcome | turns |
  |---|---|
  | handed off and then wrote | 9 |
  | handed off with no write | 2 |
  | stayed in mazkir or a pre-Ship-3 unknown skill with no write | 15 |
  | wrote while staying in the fallback (pre-Ship-3 records, where toolsets differed) | 3 |

  Every hop observed coincides with a fallback, and there were no hops after a successful pick. — vault-server.jsonl × agent-turns.jsonl (time-window join)
- CLAUDE.md documents the harm of the fallback path: five turns between 09-10 and 09-13 "wrote a forged record instead of calling a tool — habits 'created', blocks 'logged', chores 'added', none of it real", and "PRs #24/#25 were opened against bugs that did not exist". — [CLAUDE.md](file:///home/marcellmc/dev/mazkir/CLAUDE.md) (Observability / agent-turns bullet)
- Post-fix turns where the picked skill called no tool: 2 time-management turns on 09-14/15 were follow-ups to a reply whose context never arrived, the rich-message `reply_to` bug that CLAUDE.md records as fixed 2026-09-15. That was a context loss, not a misroute. One knowledge-management turn on a photo message called no tool; the router saw only `(photo: <filename>)` plus the text. — vault-server.jsonl; [CLAUDE.md](file:///home/marcellmc/dev/mazkir/CLAUDE.md) "A reply to a rich message has no `.text`"
- The only Phoenix dataset is `priority-phrasing` (10 examples). There is no router dataset, no router prompt in Phoenix, and no annotations. — `px dataset list`, `px prompt list`

### Inferences
- The post-fix router appears effectively correct on this traffic, but the traffic is narrow: 86% time-management, and `mazkir`, `engineering` and `motivation-management` were not exercised at all post-fix. The measured post-fix accuracy therefore says little about the harder boundaries: journal-vs-event, knowledge-vs-event, statement-vs-request.
- Structured failure (fallback) has been removed. Semantic failure (the wrong valid skill) cannot be measured without labels. The 225 Phoenix router spans since June, with inputs, outputs and the downstream tool calls, are the raw material for a labelled eval set to score any replacement against.
- A single-label router plus sequential hops is the "one message, one destination" limitation that §12 of the design doc names. The logs show the hop mechanism almost never fires except as fallback recovery.

### Gaps
- There is no ground-truth labelling, so semantic misroute rates are unknown.
- Turns before Ship 3 (`skill: null`) cannot be attributed to a skill from `agent-turns.jsonl`.

---

## 5. What Ships 7 and 4b require of "classification and next action"

### Takeaway
Both ships need the front of the pipeline to turn **one message into N intents, each resolved to a concrete target, shown as one set-level preview and committed by one tap**. A single skill label cannot carry that. The requirement is a **structured, side-effect-free action list**: per intent, an operation, the target described for a deterministic resolver, the time anchors, a past/planned mode and a confidence, plus a message-level "does this statement warrant any action?" judgment for 4b. Ship 7 (explicit imperatives, modifying blocks on screen) comes first. 4b adds the judgment layer later.

### Cited Findings
- Ship order: "Next: Ship 6 (classification…). Then 7 before 4b." 7 "Batch edit → preview → accept all", size ~5. 4b "Ambient capture", size ~4, "Now after 7, and shrunk by it". — [capture design §2](file:///home/marcellmc/dev/mazkir/docs/plans/2026-08-21-time-management-phase2-capture-design.md)
- §13 (2026-09-26), Ships 4b and 7 are one pipeline: "1. one message → **N intents** … 2. each intent → **resolved to a concrete target** … 3. all N → **one preview** of what would change 4. one tap → **all N commit**". "Steps 1, 3 and 4 are the same code." Step 2's habit matching and block addressing "are both 'turn a description into a record'", and half of it already exists as `block_reference` → `_resolve_reference`. — [design §13](file:///home/marcellmc/dev/mazkir/docs/plans/2026-08-21-time-management-phase2-capture-design.md)
- "Step 3 does not exist. `services/preview.py` is 29 lines: one registered function per tool, returning a string, wired only to destructive tools, one call at a time." (Verified: 29 lines.) — design §13; [preview.py](file:///home/marcellmc/dev/mazkir/apps/vault-server/src/services/preview.py)
- The real differences between the ships: for 4b, whether an intent exists at all is "the hard part — *'I'm at the dentist'* asked for nothing", it creates records, and it resolves fuzzily against habits and prose. For 7 the intent is "Given: it is an imperative", it modifies records, and it resolves "exact-ish, against blocks on screen". `proposed: true` should fold in as "a proposal *set*". — design §13
- §12, 4b obstacles "all in the routing and prompt layer":
  - **(a)** "One message, one destination. `RouterService` classifies the whole message and dispatches to a single skill … whatever does not fit that skill's tool list is dropped without comment … 4b needs fan-out: one message producing several actions across skills, not a chain that depends on each skill volunteering the next."
  - **(b)** Habit matching uses `rapidfuzz.token_set_ratio` on the habit `name` with a floor of 60. 'went for a run' → workout scores 38 and 'cleared my inbox' → review email scores 36, so neither matches. "The fix is habits carrying aliases or a description the matcher can see, not a lower threshold."
  - **(c)** "Nothing decides that a volunteered fact deserves an action … This needs an explicit policy."
  - **(d)** "Past and planned are mechanically identical."

  — [design §12](file:///home/marcellmc/dev/mazkir/docs/plans/2026-08-21-time-management-phase2-capture-design.md)
- §6: "Batch edit → preview → accept … several edits in one message, one preview showing the resolved intervals, one approval. Nothing is written until the tap." Logging quality depends on "which end of the interval the utterance anchors". — design §6
- §7: ordinals are never stored, and one deterministic sort is used per type (blocks by start timestamp, tasks by priority then alphabetical, goals alphabetical). An ordinal only means something relative to the selected date. — design §7
- Ship 4 constraints that any intent extractor must preserve:
  - `selected_date` steers resolution only, "never the write". Resolution searches the hinted day **and** today.
  - Writes to a day that is not today must name that day.
  - Addressing is descriptive through `block_resolver` (exact id or name → case-insensitive substring 95 → `token_set_ratio`, floor 60, ambiguity delta 10 → `AMBIGUOUS_MATCH`).
  - `shift_minutes` is used for moves.
  - `create_event` takes "any two of three" of start, end and duration and never invents a missing one.
  - Ship 4 explicitly defers "Multi-intent extraction, habit matching against prose … and a policy for volunteered facts" to 4b.

  — [Ship 4 spec §4.2, §4.4, §5, §8](file:///home/marcellmc/dev/mazkir/docs/superpowers/specs/2026-09-08-ship4-nl-logging-design.md)
- Ship 5 §1.3: "Once tapping is the primary path and talking the exception, those failures become both rarer and *visible* — a missed block sits in the draft instead of never being learned about." Its approval model (a derived pending state, `proposed: true` waiting for approval) is the existing single-intent preview-that-waits. — [Ship 5 spec §1.3](file:///home/marcellmc/dev/mazkir/docs/superpowers/specs/2026-09-10-ship5-inferred-capture-design.md); [CLAUDE.md](file:///home/marcellmc/dev/mazkir/CLAUDE.md) "A proposal is Mazkir's guess, so it waits"
- The skill prompts already encode rules an extractor would need to reproduce or pass through:
  - "Just got back from X" anchors the END.
  - An overnight span reported in the morning belongs to the previous date.
  - Logging something past gives an incomplete block if only one time is known.
  - Scheduling gives start plus a chosen duration.
  - No time given gives `proposed: true`.

  — [time-management.md](file:///home/marcellmc/dev/mazkir/memory/00-system/skills/time-management.md)

### Inferences
Given the §13 pipeline, "the router" splits into two different jobs:

1. **Dispatch (today's job):** choose which skill or toolset handles a message. Single-label and enum-constrained. The measured cost is ~2 s. A fast model can replace this directly behind `create_router_choice`.
2. **Intent extraction (the new job for 7 and 4b):** one message → an ordered list of intents. A plausible minimal schema per intent, derived from the constraints above (a design sketch, not in any spec):
   - `op`: create_event, update_event (shift/rename/retime), delete/dismiss, complete_habit, daily_add_task or check, save_knowledge, journal_line, or none.
   - `domain`: which skill or tool family.
   - `target_ref`: a free-text description for the deterministic resolver, never an id the model invents; ordinals resolved against the selected date's sort.
   - `mode`: past (log), planned (schedule) or present.
   - `time`: start/end/duration as stated, which end is anchored, and a date hint.
   - `evidence_span`: which clause of the message it came from.
   - `confidence`.
   - A message-level `is_request | volunteered_fact` flag, plus a policy decision for 4b.

   The output must be side-effect-free so that one set-level preview can render it and a single tap can commit it. That points to the action list being data the server executes deterministically, like the Ship 5 `adj:` callback drafts, rather than a model re-running tools after the tap.
- Resolution (step 2) should stay deterministic: resolver ladders and habit aliases, per §12's "not a lower threshold". A model's job is to produce good `target_ref` strings and anchors, not to pick records.
- For Ship 7 the extractor only needs imperatives against on-screen blocks, which is a narrow and testable problem. Ship 4b additionally needs the statement → action judgment, which is the part §13 says is "genuinely new" and unsolved.
- Latency budget: extraction would sit on the critical path before the preview. The current dispatch is already ~2 s, a fifth of a median turn, so an extra LLM stage would be felt unless the dispatch and extraction calls are merged or much faster.

### Gaps
- Neither the Ship 7 nor the 4b spec exists yet. §13 says "Still needs a brainstorm before either is specced". The schema above is my inference, not a documented decision.
- Whether Ship 6 (classification) will add another LLM call on the per-block path is not specified in a way that affects message routing.

---

## 6. How the router is traced and tested, and what swapping providers would touch

### Takeaway
The router has **no owned span**. Its only trace is the OpenInference-Anthropic auto-instrumented `messages.create` LLM span, plus the chosen skill's `skill.routing_reason` attribute and a `router_pick` log line. Its tests mock the Anthropic client and assert the exact `output_config` shape. Swapping in a non-Anthropic provider would silently remove the router's LLM span, and would touch `claude_service.py`, `main.py` wiring, `config.py`, the tests, and any Phoenix queries that identify router calls by model and `max_tokens`.

### Cited Findings
- Tracing setup: `setup_tracing` installs an OTLP/HTTP exporter and `_install_anthropic_instrumentor()` (`openinference.instrumentation.anthropic.AnthropicInstrumentor().instrument()`), plus FastAPI auto-instrumentation. — [tracing_setup.py](file:///home/marcellmc/dev/mazkir/apps/vault-server/src/tracing_setup.py)
- Dependencies: `anthropic>=0.18.0`, `openinference-instrumentation-anthropic>=0.1.14`, and opentelemetry sdk, exporter and fastapi instrumentation. — [pyproject.toml](file:///home/marcellmc/dev/mazkir/apps/vault-server/pyproject.toml)
- Spans owned by the router path: none. `SkillExecutor` opens `skill.<name>` spans with `skill.routing_reason`, `skill.previous` and `skill.next_skill`. `agent.handle_message` is the root AGENT span. In Phoenix all LLM spans are named `messages.create`. I identified router spans by `llm.model_name = claude-haiku-4-5-20251001` together with `max_tokens=128`. — [skill_executor.py](file:///home/marcellmc/dev/mazkir/apps/vault-server/src/services/skill_executor.py); Phoenix
- Logs: `router_pick` (INFO, with `skill` and `reason`). Router failures log at ERROR since `50d9971`; all 30 real failures in the log predate that change and are WARNING. — [router_service.py](file:///home/marcellmc/dev/mazkir/apps/vault-server/src/services/router_service.py); vault-server.jsonl
- Tests:
  - `tests/test_router_service.py`: picks, fallback on unknown skill, fallback on error, failure logged as ERROR, default fallback is mazkir, descriptions passed to the LLM.
  - `tests/test_claude_service.py::TestClaudeServiceCreateRouterChoice`: `test_parses_plain_json`, `test_forces_a_known_skill_through_structured_output` (asserts `kwargs["output_config"] == {...}`), and `test_history_reaches_the_router_as_a_transcript_not_as_turns` (asserts a single `user` role).
  - `tests/test_skill_executor.py` (8 tests: handoff, max hops, unknown next_skill ignored, confirmation stops handoff, legacy 2-tuple) and `tests/test_skill_loop.py` (6 tests).
  - All mock the LLM. There is no live or golden-set routing eval.

  — [tests/](file:///home/marcellmc/dev/mazkir/apps/vault-server/tests)
- Config: `anthropic_api_key` and `claude_model` (default `claude-sonnet-4-6`, not used by the router). `skills_dir` comes from `MAZKIR_SKILLS_DIR`. The OTel endpoint and service name come from env. There is no router model or provider setting. — [config.py](file:///home/marcellmc/dev/mazkir/apps/vault-server/src/config.py)

### Inferences
What a Jev swap touches:
1. **Seam:** implement `create_router_choice(user_msg, recent_messages, skill_catalog) -> {"skill","reason"}` on a new client and inject it into `RouterService(claude=...)`. `RouterService` is duck-typed. `main.py` currently builds the router only when an Anthropic key exists, so the wiring changes.
2. **Config:** a new API key and endpoint setting in `config.py` and `.env`, and ideally a router-provider or model setting, since the model is hard-coded today.
3. **Output guarantee:** the enum constraint must be reproduced (Jev's structured-output or grammar feature). Otherwise the pre-09-13 failure class returns, and it failed silently into a skill without write tools.
4. **Tracing:** without an OpenInference instrumentor for the new SDK, the router disappears from Phoenix. The fix is a manual `router.pick` LLM/CHAIN span (with `llm.model_name`, token counts, `input.value`/`output.value`), and it is worth adding regardless, because today the router cannot be queried by name.
5. **Tests:** `test_claude_service.py` pins the Anthropic `output_config` shape, and a new client needs equivalent tests. `test_router_service.py` works unchanged against any object with `create_router_choice`.
6. **Evaluation:** there is no eval dataset. The 225 Phoenix router spans (with downstream tool calls as weak labels) are the obvious seed for a head-to-head comparison.
7. **Prompt inputs:** if Jev is also meant to do intent extraction for 7/4b, it would need what the router lacks today: the full reply text, image or photo metadata, `forwarded_from`, and `selected_date`.

### Gaps
- Whether a "Jev" SDK has an OpenInference instrumentor or JSON-schema/enum-constrained output is outside this repo. Other researchers need to establish it.
