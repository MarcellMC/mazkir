# Jev fits Mazkir's router, not its planner

Jev is TypeSafe AI's "System One" decision model, released in limited early access on 15 September 2026. It is a proprietary, US-hosted API that never generates text. Instead it returns a choice, a score or a yes/no probability over options the caller defines, in roughly 130–650 ms, at $0.042 per million input tokens. Mazkir could put it behind today's router with little code: the five-skill decision is exactly one Jev Choice question, and `RouterService` already calls a duck-typed `create_router_choice` seam. Independent tests put Jev 1.4–5.4x faster than Claude Haiku 4.5, at accuracy that is comparable overall but varies by task. At Mazkir's volume that buys only latency, about 1.3–1.7 s off a 9.2 s median turn. The router already costs under a cent a day, and structured output removed its format failures on 13 September. Jev cannot serve as the front of the pipeline that Ships 7 and 4b share. It returns no arguments, its Choice question is single-select, and its parallel questions cannot see one another. So it can tell *that* a message carries several intents, but it cannot pull out the targets, times and anchors an action list needs. That extraction stays an LLM job, and an LLM extraction step would probably absorb single-skill dispatch as its N=1 case. Several things argue against adopting Jev now:

- launch-week overloads and paused signups;
- a single model version;
- open-ended default retention of every transcript sent;
- English-primary quality;
- documented weaknesses with dates and with irrelevant context.

The follow-up brainstorm should first settle the shape of the pipeline's front end. It should then define a provider-neutral "typed decision" interface that Haiku, Jev or a local classifier could sit behind, and build a labelled eval set from Mazkir's own traces. No candidate has been scored against Mazkir traffic yet.

## Jev answers in probabilities and cannot write a sentence

"Jev" refers to one product. TypeSafe AI is a San Francisco startup founded in 2024 by Diogo Almeida (formerly OpenAI, on RLHF, InstructGPT and ChatGPT), Erik Gafni and Sasha Sheng. It released Jev in limited early access on **15 September 2026**, alongside a **$40M seed round led by DCVC** ([Wikipedia](https://en.wikipedia.org/wiki/Jev_%28AI_model%29)). Sites such as jevai.org, jev.pro and jevwiki.ai are unofficial SEO or fan pages about the same model and should never be used as an endpoint. TypeSafe calls Jev the first System One model, "built to make fast, structured decisions that software can use directly" ([TypeSafe launch blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev)). Unlike an LLM, it "does not generate natural-language text" and returns "typed values together with probability estimates and confidence scores" ([Wikipedia](https://en.wikipedia.org/wiki/Jev_%28AI_model%29)).

A request carries a `state` (text or JSON) and a set of questions of three kinds, all "evaluated in parallel and in isolation against the same state in one go" ([TypeSafe docs: Introduction](https://docs.typesafe.ai/introduction)):

- **Choice:** an option from a supplied list, with per-option probabilities and a confidence.
- **Score:** a level on a scale of 2 to 10.
- **Noul:** a single yes/no probability.

Choice options can be described with objects carrying `what`, `not_for` and `examples`. The vendor recommends adding an `other` option and treating confidence "below 0.3-0.5" as a cue to escalate rather than route ([TypeSafe docs: Choice](https://docs.typesafe.ai/primitives/choice.md)). Jev is never fine-tuned per customer; behaviour is shaped only through the state, instructions and criteria ([TypeSafe docs: Models](https://docs.typesafe.ai/models)). TypeSafe lists "routing requests", "deciding whether an action needs review" and "selecting the next model in an agent workflow" among its target uses, and positions Jev as a complement to an LLM rather than a replacement ([Wikipedia](https://en.wikipedia.org/wiki/Jev_%28AI_model%29)).

| Property | Jev 1.13.0 | What it means for Mazkir |
|---|---|---|
| Access | `POST https://api.typesafe.ai/v1/systemone`, with Bearer auth and Python (sync and async) and JS SDKs ([API reference](https://docs.typesafe.ai/api.md)). Also on OpenRouter and Vercel AI Gateway ([OpenRouter](https://openrouter.ai/typesafe/jev-1.13); [Vercel](https://vercel.com/changelog/typesafe-ai-jev-now-available-on-ai-gateway)) | One small async client in FastAPI. An aggregator would add a second data processor. |
| Versions | Only `jev-1.13.0`; `jev-latest` and `jev-preview` both alias it ([Models](https://docs.typesafe.ai/models)) | Pin the version. There is no deprecation policy. |
| Context and input | 64k tokens per request, of which state plus the longest question may use 32k. Text only ([Models](https://docs.typesafe.ai/models)) | The router's ~1.3k tokens fit easily. Photos must arrive as text. |
| Choice limits | Up to 255 options, single-select ([API reference](https://docs.typesafe.ai/api.md)) | Five skills fit. Detecting several intents needs one yes/no question per intent. |
| Price | $0.042/MTok input; output is free ([launch blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev)) | About $0.00008 per router call. |
| Languages | English is primary; others are "handled but not equally well" ([Models](https://docs.typesafe.ai/models)) | Hebrew and Russian are never mentioned or tested. |
| Data | No training on inputs; retention "as long as reasonably necessary … or otherwise in support of our business"; hosted in the US ([Privacy Policy](https://typesafe.ai/legal/privacy-policy)). Zero data retention (ZDR) is for enterprise only ([Legal](https://docs.typesafe.ai/legal.md)) | Every routed transcript is kept on open-ended terms. |
| Weights | Proprietary, with no paper and no self-hosting ([Wikipedia](https://en.wikipedia.org/wiki/Jev_%28AI_model%29)) | No local fallback of the same model. |

The claim that Jev "can't hallucinate" ([launch blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev)) describes the output type, not whether the answer is correct. The vendor's own known-limitations page for jev-1.13 is candid ([TypeSafe docs: jev-1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md)). It says Jev:

- reads instructions literally;
- "reads dates as text, not as ordered quantities";
- loses accuracy "as the state grows with content unrelated to the decision";
- can be steered by injected instructions;
- struggles with multi-step "System Two" reasoning.

The product is also about eleven days old. One tester hit "five system_overloaded errors in six calls" mid-run on 21 September ([jock.pl](https://thoughts.jock.pl/p/jev-typesafe-system-one-model-benchmark-2026)). TypeSafe paused new signups on 22 September, though existing accounts kept working ([Flavio Copes](https://flaviocopes.com/jev/)). The headline claims of "70ms-500ms" end to end and "40x-200x faster" than frontier LLMs come from vendor-built workflows ([launch blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev)). TypeSafe itself says those workflows likely represent the "high end of real-world results" ([Wikipedia](https://en.wikipedia.org/wiki/Jev_%28AI_model%29)).

## Independent tests find Jev up to 5x faster than Haiku, not more accurate

Every independent measurement dates from launch week and uses `jev-1.13.0`. Speed is where the evidence is consistent:

- LiteLLM's 240-call routing benchmark: **Jev p50 127 ms against Haiku 4.5's 688 ms** ([LiteLLM](https://docs.litellm.ai/blog/jev-auto-router-benchmark)).
- wotai-dev's 16-model comparison: 455 ms against 631 ms ([wotai-dev](https://github.com/wotai-dev/typesafe-jev-tools)).
- A phishing benchmark run from France: about 239 ms against 687 ms ([beri.net](https://www.beri.net/article/typesafe-jev-typed-decision-model-calibration-decomposition-shadow-eval)).
- JevBench, measured from Germany on shared infrastructure: 0.65 s ([JevBench](https://benchmarkheaven.com/jev-models)).

The spread follows client location more than prompt size. A 20K-token prompt still returned in 429 ms ([Lightfield](https://lightfield.app/blog/testing-typesafe-jev-on-text-understanding)), and the service runs only on the US West Coast ([Flavio Copes](https://flaviocopes.com/jev/)). Nobody has measured from Israel, where Mazkir runs. Extrapolating from the European figures, **300–700 ms p50** is a reasonable expectation, not a measurement. Trained small classifiers are faster still: a 22M-parameter encoder ran in 8 ms on CPU, in a benchmark whose authorship is unidentified ([MindStudio](https://www.mindstudio.ai/blog/jev-vs-classic-classifiers-benchmark)).

Accuracy splits both ways:

| Study | Task | Jev | Haiku 4.5 |
|---|---|---|---|
| [LiteLLM](https://docs.litellm.ai/blog/jev-auto-router-benchmark) (labels and prompts by the same author) | 4-tier complexity routing, 240 calls | **95.0%** | 73.75% |
| [primeline](https://primeline.cc/blog/typesafe-jev-pre-registered-test) (pre-registered) | Commit type (800) / KB category (450) | 65.8% / 90.7% | 54.6% / **97.8%** |
| [wotai-dev](https://github.com/wotai-dev/typesafe-jev-tools) | Passages / business category / commit type | 66.0% / 79.9% / 50.0% | 66.0% / 83.2% / 42.0% |
| [beri.net](https://www.beri.net/article/typesafe-jev-typed-decision-model-calibration-decomposition-shadow-eval) | Phishing, one question / five narrow questions plus a fitted regression | 62.6% / 95.0% | **81.3%** / 93.2% |

The routing-specific results favour Jev, but they are weak evidence for two reasons. LiteLLM's labels came from one author "without independent annotation or blind adjudication" ([LiteLLM](https://docs.litellm.ai/blog/jev-auto-router-benchmark)). And no Haiku run is documented as using enum-constrained structured output, so part of Haiku's deficit may be format failures that Mazkir's router can no longer suffer.

The consistent pattern is that **Jev fails when one question has to carry a compound judgment**, and recovers when the judgment is split into narrow questions. On JevBench, accuracy falls to 74% on the Hard tier and 37% on Sealed. Jev's chance-corrected Intelligence score of 53.1 sits far below a reasoning LLM's 95.8, and no Claude model appears on the board ([JevBench](https://benchmarkheaven.com/jev-models)).

The vendor's skill-suggestion cookbook is the closest analogue to Mazkir. It used Haiku 4.5 as the agent and Jev to suggest one of 182 skills, cutting Haiku's wrong skill loads from **16.8% to 7.3%**. But the requests were single-turn, with an empty `recent_context` ([TypeSafe cookbook](https://docs.typesafe.ai/cookbooks/skill_suggestion.md)). No study tests routing that depends on earlier turns. The only non-English result is a Croatian binary task, where zero-shot Jev scored 97.1% against a fine-tuned BERT's 97.6% ([Senko Rašić](https://blog.senko.net/analyzing-jev-a-new-ai-model)).

What Haiku's structured output cannot give Mazkir is a probability distribution, and that is Jev's distinctive asset. The distribution is informative, but it is miscalibrated in a known direction:

- Jev's expected calibration error matched Haiku's (0.121 against 0.122). Jev said "unsure" on 34.7% of items, against Haiku's 2.7% ([wotai-dev](https://github.com/wotai-dev/typesafe-jev-tools)).
- It is **overconfident on Choice and Score**. On questions whose answers could not be inferred from the text, it was right 44.7% of the time while reporting an average probability of 0.74 ([beri.net](https://www.beri.net/article/typesafe-jev-typed-decision-model-calibration-decomposition-shadow-eval)).
- On Banking77 its mean confidence was 88% against about 80% accuracy, and temperature scaling cut the calibration error by about two-thirds ([MindStudio](https://www.mindstudio.ai/blog/jev-vs-classic-classifiers-benchmark)).
- At a 0.9 threshold it was right about 92% of the time, and 73% of items cleared the threshold ([primeline](https://primeline.cc/blog/typesafe-jev-pre-registered-test)).

A confidence gate is therefore workable, but only with a threshold tuned on Mazkir's own traffic rather than the vendor's 0.3–0.5. There is **no independent evaluation of Jev on multi-intent extraction**. Choice is single-select, and "one answer never becomes context for another" ([Flavio Copes](https://flaviocopes.com/jev/)). Batching questions is nearly free, though: adding questions "barely impacts response time" ([TypeSafe docs: Choice](https://docs.typesafe.ai/primitives/choice.md)).

## Swapping the router saves about 1.5 seconds of a 9-second turn

Every message except a confirmation reply triggers exactly one serial call to `claude-haiku-4-5-20251001`, with `max_tokens` 128. Its `output_config` schema constrains a `skill` field to an enum of the five skill names, plus a free-text `reason` ([claude_service.py](file:///home/marcellmc/dev/mazkir/apps/vault-server/src/services/claude_service.py)). The chosen skill then runs its own Sonnet 4.6 tool loop. A second skill is reachable only through a `next_skill:` token, capped at three hops ([skill_executor.py](file:///home/marcellmc/dev/mazkir/apps/vault-server/src/services/skill_executor.py)). The router sees less than the skill it picks: photos arrive only as a filename, reply context is cut to 50 characters, and `forwarded_from` and `selected_date` never reach it at all ([agent_service.py](file:///home/marcellmc/dev/mazkir/apps/vault-server/src/services/agent_service.py)).

Latency is the router's only real cost. Since the structured-output fix, the call has taken **p50 1.95 s and p95 2.75 s**, on p50 1,310 input tokens and 56 output tokens. That is **p50 20% and p95 43% of the turn's wall-clock time**, against a turn p50 of 9.2 s ([local Phoenix traces](http://localhost:6006)). In money it costs about **$0.0016 per turn**, 3.5% of the turn's LLM spend at [Anthropic list prices](https://platform.claude.com/docs/en/about-claude/pricing). At roughly three routed turns a day, that is under a cent a day, so Jev's input price, about 24 times lower than Haiku's ([primeline](https://primeline.cc/blog/typesafe-jev-pre-registered-test)), saves nothing that matters here.

The Sonnet skill calls take p50 2.85 s each, at two per turn, so they, not the router, dominate median turn time. The router still hurts perceived speed, because streaming forwards only the final iteration and the router's full ~2 s therefore delays the first visible token. **Replacing Haiku with Jev at 300–700 ms would save roughly 1.3–1.7 s per turn, about 15–18% of a median turn.** The gain is real but bounded, because the other ~80% of a turn is Sonnet.

The reliability problem that made the router notorious is already solved. Before 13 September, Haiku was asked for JSON while sitting mid-conversation, and it sometimes continued the chat instead. Each miss fell back silently to `mazkir`, which has no write tools. Commit `50d9971` moved the router to structured output, and **zero fallbacks** have occurred in the 28 routed turns since ([local Phoenix traces](http://localhost:6006)). Jev's guarantee that it only ever returns a valid option is therefore parity, not an advantage.

The magnitude CLAUDE.md records for that failure is wrong. The "up to 42 times a day" figure matches 2026-08-09, and **all 42 of that day's router-failure lines were pytest fixtures** ("LLM down", "nonsense"). Real fallbacks peaked at 9 a day, on 10 distinct days, 29 turns in total, concentrated at about 38% of turns from 10 to 13 September ([vault-server.jsonl](file:///home/marcellmc/dev/mazkir/data/logs/vault-server.jsonl)). That line in CLAUDE.md should be corrected.

What nobody knows is whether the router picks the *right* valid skill. Since the fix:

- 24 of 28 turns went to time-management and 4 to knowledge-management;
- `mazkir`, `engineering` and `motivation-management` were never exercised;
- the only Phoenix dataset is a 10-example priority-phrasing set, and no router labels exist ([local Phoenix traces](http://localhost:6006)).

Neither Jev's independent accuracy results nor Haiku's clean post-fix record can be checked against Mazkir's harder boundaries: journal versus event, knowledge versus event, statement versus request.

The code change itself is small, but it has four side effects:

1. **Tests and wiring.** `RouterService` accepts any object with `create_router_choice`, so a Jev client drops in. However, `main.py` builds the router only when an Anthropic key exists, and `test_claude_service.py` pins the Anthropic `output_config` shape.
2. **Tracing.** The router has no span of its own. It appears in Phoenix only as an auto-instrumented Anthropic `messages.create` span, identified by model and `max_tokens`, so a non-Anthropic client would silently vanish from traces.
3. **State.** 22 of the 28 post-fix router inputs contained Ship 3 turn-trace records ("Record of your previous reply — tools that actually ran…") ([local Phoenix traces](http://localhost:6006)). That is exactly the "content unrelated to the decision" Jev's documentation says degrades accuracy, so its state would need trimming.
4. **Cheaper levers first.** Two options need no new vendor. Dropping `reason`, which is p50 174 characters and nearly all of the router's output, is one; its effect is unmeasured, since post-fix latency rose even as output tokens fell. Letting the main model route itself, with skill descriptions in the prompt as in Anthropic's own [Agent Skills design](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills), removes the serial call entirely.

## Ships 7 and 4b need an action list that Jev cannot write

The capture design's §13 (2026-09-26) records that Ships 7 and 4b are one four-step pipeline ([capture design §13](file:///home/marcellmc/dev/mazkir/docs/specs/2026-08-21-time-management-phase2-capture-design.md)):

1. One message becomes **N intents**.
2. Each intent is **resolved to a concrete target**.
3. All N appear in **one preview** of what would change.
4. **One tap commits all N.**

Ship 7 comes first. Its intents are given, since they are imperatives, and they modify blocks already on screen. Ship 4b adds what §13 calls "the hard part": deciding whether an intent exists at all, as when *"I'm at the dentist"* asked for nothing. Section 12 names 4b's obstacles, all in the routing layer:

- one message reaches one destination;
- habit matching fails on prose ("went for a run" scores 38 against the `workout` habit, under a floor of 60);
- no policy decides that a volunteered fact deserves an action;
- past and planned events are mechanically identical.

Step 1's output therefore has to be a side-effect-free action list. For each intent it needs an operation, a target *description* for the deterministic `block_resolver`, time anchors with the anchored end marked, a past-or-planned mode and a confidence. At the message level it needs a request-versus-volunteered-fact judgment. It must also respect Ship 4's rules: `create_event` takes any two of start, end and duration and never invents the third, and `selected_date` steers resolution but never the write.

Jev cannot produce that list. It emits no strings or numbers of its own, its Choice is single-select, and its questions are isolated from one another. Ship 7's edits are interval edits ("move it 15 minutes later", "I got back at 4"), which fall squarely in the documented weakness that Jev "reads dates as text, not as ordered quantities" ([jev-1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md)). Extraction therefore stays an LLM job.

With Claude's structured outputs, arrays support only `minItems` of 0 or 1, so the intent count needs a check in code ([Claude structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)). The literature points the same way. Divide-solve-combine prompting and JSON plans of tool calls are the working patterns for multi-intent input, and Anthropic reserves separate routing for inputs whose categories are distinct and whose "classification can be handled accurately" ([Anthropic: Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)). Once an extractor labels each intent with its domain, today's single-skill router becomes the N=1 case, and dispatch folds into extraction.

Jev's plausible role is a set of smaller, faster decisions *around* that extractor. None of them has been evaluated:

- **A cascade gate.** One Jev call can combine the five-skill Choice with several yes/no questions ("more than one request?", "a statement rather than a request?", "refers to blocks on screen?") at the latency of a single question. Simple single-intent messages would go straight to a skill, and only compound or ambient ones would pay for extraction. The payoff depends on how many messages carry a single request, a share nobody has measured. 86% of post-fix turns went to time-management, which suggests the simple path is the common one.
- **Ship 4b's "does this statement deserve an action?" judgment.** This is exactly the compound judgment where Jev performs worst. The best published proactive-assistance model reached only **66.47% F1** at deciding when to offer help ([Proactive Agent, arXiv 2410.12361](https://arxiv.org/abs/2410.12361)). Whatever makes this call, its output must land as a `proposed: true` suggestion, never as a write.
- **Habit matching.** A Choice over habits whose options carry `what`, `not_for` and `examples` is literally the fix §12 asks for: "a description the matcher can see", not a lower threshold.
- **Ship 6's classification queue.** Its candidates are "ranked by the classifier's best guesses" over the activity matrix ([capture design §5](file:///home/marcellmc/dev/mazkir/docs/specs/2026-08-21-time-management-phase2-capture-design.md)). That is a batch of per-block Choice questions with probabilities, the shape Jev handles cheapest.

The batch preview also has a security payoff. Committing to a plan before touching untrusted content is one of the recognised defences against prompt injection ([Beurer-Kellner et al., arXiv 2506.08837](https://arxiv.org/abs/2506.08837)). That matters because Jev, like Haiku, can be steered by instructions inside forwarded text.

## The brainstorm should fix the pipeline's shape before its vendor

The decision that affects most future ships is not Haiku versus Jev. It is what sits at the front of the pipeline, and whether "decide" is a stable internal interface that any backend can serve. Because TypeSafe's terms, availability and model version are all in flux, the durable investments are that interface and an eval set. With both in place, a vendor choice becomes a reversible experiment rather than an architectural commitment.

| Question for the brainstorm | Live options | What settles it |
|---|---|---|
| Front-end shape | (a) keep dispatch and add an extractor only for compound messages; (b) one LLM extraction call that also dispatches; (c) a fast typed gate that sends each message to either dispatch or extraction; (d) the main model routes itself | The share of real messages that are multi-intent or ambient, which is unknown today, and each option's latency on the eval set |
| Decision interface | Vendor SDK calls scattered through the services, or one `decide(state, questions) → {answer, probabilities}` contract that Haiku structured output, Jev or a local classifier can back | Whether Ships 6, 7 and 4b each need their own classifier (they do) |
| Eval set | Seed from the 225 Phoenix router spans and `agent-turns.jsonl`, with a compound and ambient split labelled with expected action lists | Built once; Ship 7's spec needs the same labelled messages anyway |
| Fallback on timeout or low confidence | Fall back to the Haiku router, with a circuit breaker (LiteLLM uses a 30 s cooldown, per [its benchmark write-up](https://docs.litellm.ai/blog/jev-auto-router-benchmark)); **never fall back to `mazkir`**, which caused the fabricated-write replies | Replay tests with injected faults |
| State design | The full 10-message transcript, or the last 2–4 turns plus the open question with turn-trace records stripped | Accuracy by state variant on the eval set |
| Data exposure | TypeSafe on default terms, an aggregator with ZDR routing, or a local model | Whether health, location and schedule transcripts may be kept on open-ended US terms |
| Use of confidence | Ignore it, use it as a routing threshold, or feed it into the write-confidence gate | Calibration measured on Mazkir traffic |

A few points behind the table need spelling out.

- **Privacy is the hardest constraint, not a formality.** Router state carries the recent conversation. TypeSafe's default terms allow open-ended retention in the US, with ZDR reserved for enterprise customers ([Privacy Policy](https://typesafe.ai/legal/privacy-policy); [Legal](https://docs.typesafe.ai/legal.md)). Anthropic's structured outputs, by contrast, are ZDR-eligible ([Claude structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)).
- **Routing through OpenRouter does not solve the privacy problem by itself.** OpenRouter's `zdr: true` restricts requests to ZDR endpoints ([OpenRouter ZDR](https://openrouter.ai/docs/guides/features/zdr)), but nothing found shows Jev has one.
- **Local options avoid the question entirely.** Open-weight routers such as Arch-Router 1.5B report 93.17% routing scores without retraining for new routes ([arXiv 2506.16655](https://arxiv.org/abs/2506.16655)). A trained encoder could learn from Mazkir's own logged decisions. The trade-off runs the other way here: LLMs beat fine-tuned classifiers on out-of-scope input (85.6% against 58.1%) and on schemas that change without retraining ([Rodrigues & Vas, arXiv 2608.20371](https://arxiv.org/abs/2608.20371)). Mazkir's [skill set](file:///home/marcellmc/dev/mazkir/memory/00-system/skills/) was redesigned in June and extended in July.
- **Phoenix covers most of the eval tooling.** It supplies versioned datasets and code evaluators for exact-match experiments ([Phoenix datasets](https://arizeai-433a7140.mintlify.app/docs/phoenix/datasets-and-experiments/concepts-datasets); [Phoenix experiments](https://arizeai-433a7140.mintlify.app/docs/phoenix/datasets-and-experiments/how-to-experiments/running-experiments)). A confusion matrix is a `pd.crosstab` over the runs.
- **An owned `router.pick` span is worth adding whatever is chosen**, carrying model, tokens and probabilities. Without it, the router cannot even be queried by name today.

## Conclusion

Asking "should Jev replace Haiku as the router?" frames the problem around a component that Ship 7 is about to demote. Once one message can produce N intents, the single-label router is either absorbed into extraction or becomes a fast pre-filter in front of it. Jev's speed matters only in the second design, and only for the ~1.5 s it shaves from the simple, single-intent majority of messages. What makes Jev genuinely new for Mazkir is not speed but a cheap, batchable primitive that answers yes/no or a choice with a calibrated-ish probability. That primitive matches a family of small decisions Mazkir's roadmap is about to accumulate: which activity a block belongs to, which habit a sentence describes, whether a statement warrants a proposal. Today each of those would be either a full LLM call or a fuzzy string threshold that fails on prose.

The practical consequence is an ordering. First, define the typed-decision contract and label a few dozen real messages, including compound and ambient ones, with the action lists Ship 7 would need to produce. Then run Haiku as it stands, Haiku without `reason`, main-model self-routing and Jev against that set. That work pays off whichever backend wins, and Ship 7 needs it regardless. Adopting Jev before that eval set exists would trade a solved reliability problem and a known privacy posture for an eleven-day-old vendor's latency claims, on traffic that no one has yet shown it handles.
