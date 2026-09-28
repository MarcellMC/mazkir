# Routing and Multi-Intent Action Planning Patterns for LLM Personal Assistants (2025–2026)

Scope note: this covers architecture options, not the "Jev" model itself. One section includes a **local measurement** taken from Mazkir's own Phoenix traces (project `mazkir`, `http://localhost:6006`, queried 2026-09-26, spans since 2026-07-01). It is primary evidence for this system only, and the sample is small. The script that produced it was a scratchpad pull of `/v1/projects/mazkir/spans`. Router spans were identified as `messages.create` + `claude-haiku-4-5-20251001` + `max_tokens: 128`, and turns as the `agent.handle_message` span.

## 1. Which routing patterns are in use, and what are their latency, cost and accuracy trade-offs?

### Takeaway
There are six families of router. They are (a) a single-label LLM classifier, which is what Mazkir has now; (b) embedding/semantic routers, at millisecond latency but weak on out-of-scope and compound input; (c) fine-tuned small classifiers or small generative routers, which are the most accurate on a stable label set and cheapest per call but need labelled data; (d) cascades, where a cheap classifier runs first and escalates on low confidence; (e) model-routers such as RouteLLM, Not Diamond or OpenRouter, which answer "which model" rather than "which skill"; and (f) orchestrator/manager or hand-off patterns, where the main model routes itself through tools. For a five-skill, single-user bot, the evidence favours keeping an LLM router, or removing the router call entirely and letting the main model pick. The accuracy advantage of fine-tuned encoders appears only with abundant in-domain labels. LLMs win on out-of-scope input, noisy input and changing schemas.

### Cited Findings
**Semantic/embedding routing**
- Aurelio's semantic-router describes itself as a "superfast decision-making layer" that routes on meaning in vector space rather than "waiting for slow LLM generations". Routes are defined by example utterances. Local encoders are supported (`HuggingFaceEncoder`, FastEmbed), with a fully-local mode via `HuggingFaceEncoder` + `LlamaCppLLM`. A notebook covers training per-route thresholds, and "dynamic routes" can generate function parameters — [aurelio-labs/semantic-router GitHub](https://github.com/aurelio-labs/semantic-router)
- Secondary sources describe the design as 5–15 example utterances per route with cosine nearest-neighbour matching. They claim it runs "in 5-20ms" and cuts latency "from 5000ms to just 100ms". These are vendor or glossary claims, not independent benchmarks — [Deepchecks glossary](https://deepchecks.com/glossary/semantic-router/); [Aurelio product page](https://www.aurelio.ai/semantic-router)

**Fine-tuned small classifiers versus LLM prompting (2026 papers)**
- Rodrigues & Vas (arXiv 2608.20371, June 2026) conclude "it depends on the intent space":
  - **ATIS:** fine-tuned RoBERTa 95.9 vs zero-shot Claude Haiku 84.1 (p<0.001).
  - **CLINC150:** RoBERTa 89.1 vs Claude 88.5, statistically tied.
  - **Out-of-scope detection:** Claude 85.6 vs RoBERTa 58.1.
  - **ASR noise at 0 dB:** Claude 92.5 vs RoBERTa 80.0.
  - **Dynamic schemas:** Claude ~94% with no retraining vs RoBERTa 0%.

  Source: [arXiv 2608.20371](https://arxiv.org/abs/2608.20371)
- Valdes Gonzalez (arXiv 2602.06370, Feb 2026) found fine-tuned BERT-family encoders "competitive, and often superior" to GPT-4o and Claude Sonnet 4.5 prompting, at "one to two orders of magnitude lower cost and latency". The paper recommends LLMs as "complementary elements within hybrid architectures" — [arXiv 2602.06370](https://arxiv.org/abs/2602.06370)
- Chen, Yang & Hayou (arXiv 2608.02415, Aug 2026; COLM 2026) find that training-free and training-based intent classifiers "saturate easy benchmarks" and that training-based ones win on harder tasks, but that "training-free methods are generally more robust to mixed-intent and adversarial prompts" — [arXiv 2608.02415](https://arxiv.org/abs/2608.02415)

**Small generative router models**
- Arch-Router (Katanemo, arXiv 2506.16655, June 2025) is a 1.5B model fine-tuned from Qwen 2.5 on 43k examples. It maps queries to user-defined domain/action "route policies" and reports a 93.17% overall routing score, 7.71 points above proprietary models on average. New routes or models can be added without retraining — [arXiv 2506.16655](https://arxiv.org/abs/2506.16655); [HF model card](https://huggingface.co/katanemo/Arch-Router-1.5B); [VentureBeat](https://venturebeat.com/ai/new-1-5b-router-model-achieves-93-accuracy-without-costly-retraining)

**Model-routers (which model, not which skill)**
- **RouteLLM** (LMSYS/Berkeley, June 2024 — older material). Its matrix-factorisation router achieved 85% cost reduction on MT-Bench at 95% of GPT-4 quality, sending only 14% of queries to the strong model. Savings are much lower on MMLU (45%) and GSM8K (35%). Router overhead is small: $3.32 per million requests, 155 req/s on a $0.8/h VM — [RouteLLM paper](https://arxiv.org/pdf/2406.18665); [RouteLLM GitHub](https://github.com/lm-sys/routellm)
- The **TMLR 2026 survey** by Moslem & Kelleher frames routing and cascading along *when* a decision occurs, *what* information informs it and *how* computation proceeds. It covers difficulty-based, preference-aligned, clustering, uncertainty, RL and cascade approaches, and notes that optimal choice "depends entirely on operational constraints" — [arXiv 2603.04445](https://arxiv.org/abs/2603.04445)
- **Commercial routers:**
  - OpenRouter's auto router "classifies prompts into roughly 30 task types". The older Not Diamond-powered `openrouter/auto` slug is reportedly deprecated.
  - Not Diamond is said to add "50 to 120 milliseconds" per request as an external classification call.
  - Both claims come from aggregator blogs, not primary docs. Treat them as unverified — [dev.to roundup](https://dev.to/kuldeep_paul/7-best-llm-routing-tools-for-latency-and-cost-2026-4mm1); [Morph](https://www.morphllm.com/notdiamond-alternative)

**Orchestration patterns (the router is the main model)**
- OpenAI's *A practical guide to building agents* (2025) distinguishes two patterns:
  - **Manager pattern:** a central LLM calls specialist agents *as tools* and keeps control of the user.
  - **Decentralised hand-off pattern:** agents "hand off control of the workflow" to one another. OpenAI recommends it when no single agent needs central control or synthesis.

  Source: [OpenAI guide (PDF)](https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf); [OpenAI page](https://openai.com/business/guides-and-resources/a-practical-guide-to-building-ai-agents/)
- Google Cloud's pattern catalogue (updated 2026-05-28) lists 12 patterns: single, sequential, parallel, loop, review/critique, iterative refinement, coordinator, hierarchical decomposition, swarm, ReAct, human-in-the-loop and custom logic.
  - On the coordinator pattern: it "results in more model calls than a single-agent system... increases token throughput, operational costs, and overall latency".
  - On the parallel pattern: it "can reduce overall latency compared to a sequential approach" at higher token cost.

  Source: [Google Cloud Architecture Center](https://docs.cloud.google.com/architecture/choose-design-pattern-agentic-ai-system)
- LangChain's benchmark (June 2025) ran τ-bench retail against 6 distractor domains of 19 tools each.
  - A single agent "falls off sharply when there are two or more distractor domains".
  - Swarm (peer hand-off) "slightly outperforms" supervisor, and supervisor costs more tokens.
  - Three supervisor fixes gave a ~50% improvement: removing hand-off messages from sub-agent context, a "forward message" tool so the supervisor does not regenerate sub-agent answers, and better hand-off tool naming.

  Source: [LangChain blog](https://www.langchain.com/blog/benchmarking-multi-agent-architectures)

### Inferences
- Mazkir's `next_skill` hop chain is the decentralised hand-off pattern. Its Haiku router is a separate single-label classifier placed in front of it. LangChain's finding, that swarm-style hand-off is competitive once hand-off chatter is kept out of sub-agent context, supports keeping the hand-off shape. It also suggests auditing how much hand-off text each hop carries.
- With five skills and few labelled examples, a fine-tuned encoder is unlikely to beat Haiku by much (the CLINC150 result is a tie). It would lose out-of-scope robustness, and it would need retraining whenever a skill is added (the dynamic-schema result). A semantic router is a plausible **pre-filter** for high-frequency, unambiguous phrasings, with the LLM kept as fallback. It is weak as the sole router for compound messages.
- Model-routers (RouteLLM, Not Diamond, OpenRouter auto) solve a different problem: picking a model per query to save cost. They are relevant only if the brainstorm considers sending easy turns to a cheaper main-loop model.

### Gaps
- There is no independent, primary-source latency benchmark comparing semantic-router, a fine-tuned encoder and a Haiku-class LLM router on the same task. Latency numbers above are vendor claims or aggregator claims.
- Pydantic AI, DSPy and LlamaIndex routing docs were not researched within the call budget.

## 2. What is Anthropic's own guidance (routing, orchestrator-workers, parallelisation, structured outputs, tool use, subagents)?

### Takeaway
Anthropic's guidance has four strands:
- Start with the simplest workflow.
- Use **routing** only when categories are distinct and "classification can be handled accurately".
- Prefer **orchestrator-workers** when subtasks cannot be predicted in advance.
- Use **parallelisation** for independent subtasks.

Newer platform features give alternatives to a separate router call. Skills are loaded through *progressive disclosure*, where the model picks a skill from its description. Tool search defers large tool sets. Strict tool use and structured outputs guarantee schema-valid choices. Forced `tool_choice` is being withdrawn on the newest models.

### Cited Findings
- **"Building effective agents"** (published 2024-12-19, older material, but the live page now cites Haiku 4.5 and Sonnet 4.5):
  - Routing "classifies an input and directs it to a specialized followup task". It fits "complex tasks where there are distinct categories that are better handled separately, and where classification can be handled accurately". One example routes easy questions to Haiku 4.5 and hard ones to Sonnet 4.5.
  - Orchestrator-workers means "a central LLM dynamically breaks down tasks, delegates them to worker LLMs, and synthesizes their results", for tasks "where you can't predict the subtasks needed".
  - Parallelisation covers "sectioning" (independent subtasks) and "voting".
  - The article advises: "start with simple prompts... add multi-step agentic systems only when simpler solutions fall short", and "explicitly showing the agent's planning steps" for transparency.

  Source: [Anthropic Engineering](https://www.anthropic.com/engineering/building-effective-agents)
- **Multi-agent research system** (2025-06-13):
  - Agents use "about 4× more tokens than chat", and multi-agent systems "about 15×".
  - Parallel subagents plus parallel tool calls "cut research time by up to 90% for complex queries".
  - Multi-agent systems suit "heavy parallelization"; "most coding tasks involve fewer truly parallelizable tasks".
  - The lead agent runs subagents synchronously.
  - Evaluation started with ~20 real queries and a single LLM-judge call scoring 0.0–1.0.

  Source: [Anthropic Engineering](https://www.anthropic.com/engineering/multi-agent-research-system)
- **Agent Skills** (2025-10-16): skill metadata (name and description) sits in the system prompt, and "if Claude thinks the skill is relevant to the current task, it will load the skill by reading its full SKILL.md into context". Further linked files load only as needed, giving three or more disclosure levels. The *model* selects the skill; there is no separate router call — [Anthropic Engineering](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- **Advanced tool use** (2025-11-24):
  - **Tool Search Tool** cuts tool-definition context from ~77K to ~8.7K tokens (85% less) and improves MCP-eval accuracy: Opus 4 from 49%→74%, Opus 4.5 from 79.5%→88.1%.
  - **Programmatic Tool Calling** avoids "19+ inference passes" when orchestrating 20+ calls in code, and cuts tokens 37%.
  - **Tool Use Examples** raise complex-parameter accuracy from 72%→90%.

  Source: [Anthropic Engineering](https://www.anthropic.com/engineering/advanced-tool-use)
- **Structured outputs:**
  - Uses `output_config.format`, GA on the Claude API. Haiku 4.5 (`claude-haiku-4-5-20251001`) is supported. The old `output_format` field and beta header are deprecated.
  - `enum` is supported for strings, numbers, bools and nulls only. Array `minItems` supports only 0 and 1.
  - Numeric and string-length constraints and recursive schemas are unsupported. `additionalProperties` must be `false`.
  - "The first time you use a specific schema, there is additional latency while the grammar compiles". Grammars are "cached for 24 hours from last use".
  - The cache is invalidated when the schema structure or the tool set changes, but not by name or description edits.

  Source: [Claude structured outputs docs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- **`tool_choice`:** it can be `auto`, `any`, `tool` or `none`.
  - Claude Opus 5.5, Fable 5.1 and Mythos 5.1 reject `any`/`tool` with a 400 error. The docs advise "`auto` with strict tool use... or structured outputs when you need a response in a fixed JSON shape".
  - `any`/`tool` prefill the assistant turn, so no explanatory text precedes the tool call.
  - Changing `tool_choice` invalidates cached message blocks.
  - The tool docs also advise to "consolidate related operations into fewer tools" and to namespace tool names to reduce selection ambiguity.

  Source: [Claude docs: Define tools](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)
- **Parallel tool use:** it is on by default ("Claude may call multiple tools in a single response"), and execution order is the caller's choice.
  - All `tool_result`s go back in one user message. A call that was not executed must still get `is_error: true`.
  - `disable_parallel_tool_use` goes inside `tool_choice`.
  - The recommended prompt line is: "For maximum efficiency, whenever you need to perform multiple independent operations, invoke all relevant tools simultaneously". Adding "Only batch tool calls that are independent of each other" reduces dependent calls appearing together.

  Source: [Claude docs: Parallel tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/parallel-tool-use)
- **Latency guidance:** "first engineer a prompt that works well... then try latency reduction strategies". The levers are the model (Haiku 4.5 "offers the fastest response times"), fewer input and output tokens, a tight `max_tokens`, and streaming, with TTFT as the metric for perceived speed — [Claude docs: Reducing latency](https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-latency)

### Inferences
- Structured outputs cannot cap a multi-label router's array length (only `minItems` 0 or 1 is supported). A multi-label or action-list output therefore needs a count check in code.
- Mazkir's enum is built from the skill catalogue, so it is stable. If the enum became dynamic per turn (for example, a filtered skill subset), each new schema would pay first-use grammar compilation.
- The Skills / progressive-disclosure design suggests a zero-extra-call alternative. Put the five skill descriptions into the main model's system prompt, and give it `load_skill` or `handoff` tools, so routing happens inside the first main-loop call.
- If the main model is ever moved to Opus 5.5-class models, any design that relies on forced `tool_choice` must switch to `auto` + strict tools or structured outputs. Mazkir's current router already uses structured outputs.

### Gaps
- No Anthropic document addresses *multi-intent splitting* specifically.
- The Claude Agent SDK subagent docs were not fetched.
- Anthropic publishes no router-latency benchmark for Haiku 4.5 with structured outputs.

## 3. How do production assistants and research systems split one utterance into several actions, and handle intents the user did not state explicitly?

### Takeaway
There are three families of approach:
1. **Classic multi-intent spoken-language understanding (SLU).** This is multi-label classification plus slot filling, benchmarked on MixATIS/MixSNIPS.
2. **LLM decomposition prompting.** The model divides the message into sub-utterances, solves each, then combines the results.
3. **Agentic planners.** These emit a JSON *plan of tool calls*, or rely on native parallel tool calls, and dispatch each item to a typed executor.

Unstated intents ("I'm at the dentist") are a separate problem, *proactive* assistance. Research treats it as "predict whether help is needed", with accept/reject labels, and reported accuracy is still modest.

### Cited Findings
- MixATIS and MixSNIPS, the standard multi-intent benchmarks, are built by **concatenating single-intent utterances with "and"**. MixATIS has 13,162 training, 759 validation and 828 test samples; MixSNIPS has 39,776 training and 2,198 validation — [MIDLM, COLING 2025](https://aclanthology.org/2025.coling-main.179.pdf); [multi-intent SLU survey, arXiv 2512.11258 (Dec 2025)](https://arxiv.org/pdf/2512.11258)
- **DSCP** ("Divide-Solve-Combine Prompting", AAAI 2025) decomposes zero-shot multi-intent detection into three prompts: single-intent *division* into sub-sentences, intent-by-intent *solution*, and multi-intent *combination*. It reports substantial gains over baselines on MixATIS and MixSNIPS, with better interpretability — [AAAI 2025 paper](https://ojs.aaai.org/index.php/AAAI/article/view/34688/36843); [ML Anthology](https://mlanthology.org/aaai/2025/qin2025aaai-divide/)
- BlendX (2024, older) argues that concatenation-based benchmarks under-represent real "blended" multi-intent patterns — [arXiv 2403.18277](https://arxiv.org/pdf/2403.18277)
- AnovaX (arXiv 2607.15367, July 2026) is a local multi-agent voice assistant. It uses "an LLM planner (Gemini) that emits a JSON plan of tool calls, a whitelist-and-denylist safety layer, a multi-agent orchestrator that translates each plan into typed child agents on a bounded thread pool". Each executor class has its own timeout, retry policy and locks. A recursive MetaAgent can delegate sub-goals back to the planner, capped at 2 levels. Planner latency is hidden "behind speculative execution of read-only tools" — [arXiv 2607.15367](https://arxiv.org/abs/2607.15367)
- The hybrid-router "super agent" vision (arXiv 2504.10519, 2025) "first detects the intent of the user, then routes the request to specialized task agents" or auto-generates workflows. It chooses between local and cloud models by task complexity — [arXiv 2504.10519](https://arxiv.org/abs/2504.10519)
- Alexa+ (Feb 2025) organises capabilities into "experts": "groups of systems, capabilities, APIs, and instructions that accomplish specific types of tasks". It orchestrates across "tens of thousands of services and devices" on Bedrock-hosted LLMs. No public detail on multi-intent splitting was found — [About Amazon](https://www.aboutamazon.com/news/devices/new-alexa-generative-artificial-intelligence); [SiliconANGLE](https://siliconangle.com/2025/02/26/amazon-debuts-llm-powered-alexa-expanded-automation-features/)
- Native parallel tool calls are the simplest "action list". Claude can emit several `tool_use` blocks in one turn, and the caller chooses concurrent or sequential execution — [Claude docs: Parallel tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/parallel-tool-use)
- **Unstated or implicit intents:**
  - *Proactive Agent* (Lu et al., Oct 2024, older; ICLR 2025) built ProactiveBench with 6,790 events. Human annotators labelled proactive offers as accepted or rejected, and a reward model trained on those labels acts as judge. The best fine-tuned model reached only **66.47% F1** at proactively offering help — [arXiv 2410.12361](https://arxiv.org/abs/2410.12361)
  - *ContextAgent* (NeurIPS 2025) combines sensory context with persona or history context. It first predicts *whether* proactive service is needed, then calls tools. ContextAgentBench has 1,000 samples across 9 scenarios and 20 tools; the system is up to 8.5% better on proactive prediction and 6.0% on tool calling than baselines — [arXiv 2505.14668](https://arxiv.org/abs/2505.14668)

### Inferences
- For Mazkir, "I'm at the dentist" is a *declared state*. It could lead to a log entry, a time block, a task tick or a follow-up reminder.
- The research framing suggests treating unstated intents as **proposals with explicit accept/reject**, never auto-executed. Proactive-prediction accuracy is only about 66% F1 in the best published system. Mazkir's existing `proposed: true` / pending-approval mechanism for events already fits this.
- An **action-list structured output** has the same shape as DSCP's divide step and AnovaX's JSON plan: `[{skill, action, args, explicit: bool, confidence}]`. It maps cleanly onto the current skill executors, which play the role of typed executors. Whether a Haiku-class model can produce it reliably is an empirical question for the eval set.
- Benchmarks built by "and"-concatenation will overstate accuracy on real chat, where intents are blended ("done with the dentist, remind me to book the follow-up"). A Mazkir eval set should come from its own traces.

### Gaps
- Numeric results for LLMs on MixATIS/MixSNIPS were not retrieved; the full papers were not fetched.
- I found no primary source describing how Alexa+, Gemini or ChatGPT segment multi-intent utterances internally.
- I found no published evaluation of implicit-intent handling in text-chat personal assistants specifically.

## 4. What propose-then-confirm / preview-then-commit patterns exist for batched agent actions, including chat UI patterns?

### Takeaway
Two mainstream designs are converging. Both suit a Telegram inline keyboard, provided the pending plan is stored server-side:
- **Per-tool approval gates.** The agent run pauses on flagged tool calls, stores a checkpoint, and resumes with approve, edit or reject for each call. Partial approval of a batch is supported.
- **Co-planning.** The user sees and edits the whole plan before any action runs.

### Cited Findings
- LangChain / LangGraph `HumanInTheLoopMiddleware`:
  - Configured per tool via `interrupt_on`. Each entry is either `false` (auto-approve) or a policy listing `allowedDecisions` (`approve` / `edit` / `reject`) with a description.
  - Built on LangGraph `interrupt`; it requires a checkpointer and `thread_id`.
  - "Tool calls are processed in the order they appear in the AI message, with auto-approved tools executing immediately."

  Source: [LangChain HITL docs](https://docs.langchain.com/oss/python/langchain/human-in-the-loop); [LangChain JS reference](https://reference.langchain.com/javascript/langchain/index/humanInTheLoopMiddleware)
- OpenAI Agents SDK:
  - `needs_approval` is set per tool, as a boolean or an async predicate.
  - An unapproved call does not execute, and the run returns `interruptions`. The caller approves or rejects each one and resumes with the serialised state.
  - Partial approval is supported: "Approve two out of five pending items, resume, and the agent continues executing the approved calls while the remaining three stay paused". The partial-approval phrasing is from a secondary summary.

  Source: [OpenAI Agents SDK HITL guide](https://openai.github.io/openai-agents-js/guides/human-in-the-loop/); [OpenAI API: guardrails and approvals](https://developers.openai.com/api/docs/guides/agents/guardrails-approvals)
- Magentic-UI (Microsoft Research, July 2025) has several relevant mechanisms:
  - **Co-planning:** the user edits the plan in a plan editor or via text *before* any action.
  - **Action guards:** "seeks user approval before executing potentially irreversible actions, and the user can specify how often" approvals are needed.
  - **Co-tasking, multi-tasking and long-term memory**, which covers plan learning.

  Source: [Microsoft Research blog](https://www.microsoft.com/en-us/research/blog/magentic-ui-an-experimental-human-centered-web-agent/); [arXiv 2507.22358](https://arxiv.org/abs/2507.22358)
- The security-pattern paper by Beurer-Kellner et al. (June 2025; authors from IBM, Invariant Labs, ETH Zürich, Google and Microsoft) lists **Plan-Then-Execute** and **Action-Selector** among six patterns against prompt injection. Committing to a plan *before* reading untrusted data (such as calendar or web content) limits what injected text can change — [arXiv 2506.08837](https://arxiv.org/abs/2506.08837)
- Anthropic recommends "transparency by explicitly showing the agent's planning steps" — [Anthropic Engineering](https://www.anthropic.com/engineering/building-effective-agents)
- Mazkir already has several of these building blocks:
  - per-tool risk classes with thresholds (≥0.85 write, ≥0.95 destructive);
  - always-confirm previews for destructive tools;
  - `AgentResponse.confirmation_choices` rendered as an inline keyboard;
  - `proposed: true` events that stay pending until approved;
  - an "Approve all" endpoint.

  Telegram `callback_data` is limited to 64 bytes, and rich-message button rows hold 1–8 buttons — [Mazkir CLAUDE.md, local](file:///home/marcellmc/dev/mazkir/CLAUDE.md)

### Inferences
- A practical "one-tap" batch design for Mazkir:
  1. The router or planner emits an action list.
  2. The server stores it as a pending plan with a short id, keeping the 64-byte callback payload small.
  3. The bot renders one row per action: a ✓/✕ toggle plus a single "Approve all (n)" button.
  4. Safe and high-confidence explicit actions can auto-execute. Inferred actions (`explicit: false`) always wait.

  This mirrors the LangChain `interrupt_on` split between auto-approved and gated calls, and the OpenAI partial-approval model.
- The ordering rule matters. LangChain executes auto-approved calls immediately while gated ones wait. If a gated action depends on an auto-executed one, or the reverse, the plan needs explicit dependencies. Otherwise the batch should be all-or-nothing.

### Gaps
- No quantitative study was found on approval fatigue, or on the best batch size for confirm-all UIs in chat.
- The Magentic-UI user-study numbers were not retrieved; only the abstract was fetched.

## 5. How should a router be evaluated (labelled dataset from traces, offline evals, confusion matrices, fallback rates), and what does Phoenix provide?

### Takeaway
Build a small, versioned golden dataset from real Mazkir spans; roughly 20–100 turns is enough to start, per Anthropic's experience. Label the expected skill, or the expected action list, per turn. Run candidate routers as Phoenix experiments with deterministic exact-match evaluators, and compute the confusion matrix and fallback rate with pandas. Phoenix covers the dataset, versioning, splits, experiment comparison and span annotations. A confusion-matrix view is not documented and should be assumed DIY.

### Cited Findings
- Phoenix datasets hold `input`, optional reference `output` and `metadata`. They are **versioned**: "every insert, update, and delete is versioned, so you can pin experiments... to a specific version" — [Phoenix: Datasets concepts](https://arizeai-433a7140.mintlify.app/docs/phoenix/datasets-and-experiments/concepts-datasets)
- Spans can be added to a dataset one at a time from the trace view ("add to dataset"). Several can be added at once by filtering the spans table and multi-selecting — [Phoenix: Creating datasets from spans](https://arizeai-433a7140.mintlify.app/docs/phoenix/datasets-and-experiments/how-to-datasets/creating-datasets)
- `run_experiment(dataset, task, evaluators)` runs a candidate over every example. Code evaluators (exact match) are recommended when "you already know the exact correctness rule" and "you do not want to call another model during evaluation" — [Phoenix: Running experiments](https://arizeai-433a7140.mintlify.app/docs/phoenix/datasets-and-experiments/how-to-experiments/running-experiments); [Phoenix TS experiments](https://arizeai-433a7140.mintlify.app/docs/phoenix/sdk-api-reference/typescript/packages/phoenix-client/experiments)
- A Phoenix tutorial evaluates an LLM ticket classifier as an experiment task with a code evaluator. The agents cookbook binds a `routing_eval` ClassificationEvaluator alongside function-selection and parameter-extraction evals — [Phoenix tutorial](https://arizeai-433a7140.mintlify.app/docs/phoenix/datasets-and-experiments/tutorial/run-experiments-with-code-evals); [Phoenix agent cookbook](https://arizeai-433a7140.mintlify.app/docs/phoenix/cookbook/datasets-and-experiments/experiment-with-a-customer-support-agent)
- **Splits** let you compare experiments on a fixed subset, and each experiment snapshots its example ids so comparisons stay stable — [Phoenix: Splits](https://arizeai-433a7140.mintlify.app/docs/phoenix/datasets-and-experiments/how-to-experiments/splits)
- Human labels can be attached as span annotations (`annotator_kind="HUMAN"`) and pulled back with `SpanQuery().where("annotations['…'].label == …")` for analysis — [Phoenix: Exporting annotated spans](https://arizeai-433a7140.mintlify.app/docs/phoenix/tracing/how-to-tracing/importing-and-exporting-traces/exporting-annotated-spans); [Phoenix: Annotating spans](https://arizeai-433a7140.mintlify.app/docs/phoenix/tracing/how-to-tracing/feedback-and-annotations/annotating-auto-instrumented-spans)
- Anthropic's research team began with "about 20 queries representing real usage patterns" and an LLM judge — [Anthropic Engineering](https://www.anthropic.com/engineering/multi-agent-research-system)
- **Fallback rate is already observable.** Mazkir's `skill.<name>` spans carry `skill.routing_reason`, and router failures are prefixed `fallback:`.
  - In the local Phoenix sample (2026-07-01 → 2026-09-23), 28 of 132 unstructured router calls fell back with "Expecting value: line 1 column 1", which is 21%.
  - The last fallback was on 2026-09-13, the day structured output was introduced. There were 0 fallbacks in the 28 structured calls since.
  - Source: local Phoenix query, project `mazkir`.
  - CLAUDE.md separately records up to 42 fallbacks a day before the fix — [Mazkir CLAUDE.md, local](file:///home/marcellmc/dev/mazkir/CLAUDE.md)

### Inferences
- Suggested eval protocol:
  1. Export `agent.handle_message` spans to a dataset. The input is the user text plus a recent transcript; the reference is the skill label (or action list) corrected by hand.
  2. Add labelled compound and implicit-intent examples as a separate split.
  3. Run the current Haiku router and each candidate (Jev, a semantic router, the main-model-picks design) as experiments.
  4. Score with exact match. For action lists, use set-level precision/recall on skill+action pairs.
  5. Record router latency per run.
  6. Build the confusion matrix with `pd.crosstab` on the experiment runs.
- The trace data shows the Phoenix sample is much smaller than real traffic: only 160 routed turns in about 12 weeks, against "up to 42 fallbacks a day" in CLAUDE.md. Before relying on Phoenix as the dataset source, check retention and sampling. `data/logs/agent-turns.jsonl` may be the more complete source of raw inputs.

### Gaps
- I could not confirm whether Phoenix has a built-in confusion-matrix or multiclass view for experiment results.
- No published guidance was found on the minimum eval-set size for 5-way routing.

## 6. Where does a very fast model help, and where is latency dominated by downstream steps? Is router latency as a share of turn latency published?

### Takeaway
No published measurement of router latency as a share of agent-turn latency was found. Mazkir's own traces answer it for this system:
- The Haiku router takes **~1.7 s median** (p90 ~2.5 s), about **16% of a median 10.1 s turn** (p90 share 33%).
- The Sonnet 4.6 main loop takes **~80%**. Tools take only ~2.5%.

A router that was instant would therefore cut the median turn from ~10.1 s to ~8.4 s. It would move time-to-first-token by the same ~1.7 s, since the router runs serially before the streamed reply. Bigger wins are in the main loop: fewer iterations, fewer hops, or folding routing into the first main-loop call.

### Cited Findings
- **Local measurement** (Phoenix project `mazkir`, spans 2026-07-01 → 2026-09-23; 159 turns with both a router span and `agent.handle_message`):
  - **Router latency:** p50 1,718 ms, p90 2,477 ms, p99 3,023 ms.
    - After the switch to structured output (n=28, from 2026-09-13): p50 1,961 ms, p90 2,583 ms, prompt p50 1,340 tokens, completion p50 56.
    - Before the switch (n=132): p50 1,624 ms, prompt p50 858 tokens, completion p50 85.
    - The prompt also changed on 2026-09-13 (the transcript is now quoted), so the latency difference cannot be attributed to grammar-constrained decoding alone.
  - **Turn latency:** `agent.handle_message` p50 10,100 ms, p90 18,308 ms.
  - **Router share of the turn:** p50 16.3%, p90 32.9%, mean 19.2%.
  - **Main loop:** the non-router LLM share of the turn is p50 79.9% (mostly `claude-sonnet-4-6`: 396 calls vs 10 Haiku). There are 2 main-loop LLM calls per turn at p50 and 4 at p90. A Sonnet call takes p50 3,174 ms and p90 6,422 ms.
  - **Tool execution share:** p50 2.5%.
  - **Hops:** 140 turns used 1 skill and 19 used 2. Two-hop turns have p50 13.4 s vs 10.1 s overall.
  - **Router schema:** the router returns `{skill, reason}`. The `reason` string accounts for most of the 56–85 completion tokens (`services/claude_service.py`, local).
- Anthropic lists the latency levers: a faster model (Haiku 4.5), fewer input and output tokens, a tight `max_tokens`, and streaming. It says to optimise TTFT for perceived speed — [Claude docs: Reducing latency](https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-latency)
- Structured-output grammars add latency on the first use of a schema and are cached for 24 h — [Claude structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- Other structural latency levers:
  - Parallelisation cut research time "by up to 90%" in Anthropic's system — [Anthropic Engineering](https://www.anthropic.com/engineering/multi-agent-research-system)
  - Programmatic tool calling removes "19+ inference passes" — [Anthropic Engineering](https://www.anthropic.com/engineering/advanced-tool-use)
  - AnovaX hides planner latency with speculative execution of read-only tools — [arXiv 2607.15367](https://arxiv.org/abs/2607.15367)
- Embedding routers claim 5–20 ms (vendor claim) — [Deepchecks](https://deepchecks.com/glossary/semantic-router/). Encoders run at "one to two orders of magnitude lower... latency" than LLM prompting — [arXiv 2602.06370](https://arxiv.org/abs/2602.06370)

### Inferences
- **A faster router model helps most for:**
  - TTFT on streamed replies, since the router is strictly serial.
  - Short, read-only turns, where the main loop is a single call.
  - Any design that adds a planning or action-list step. Such a step emits more output tokens than a single label, so output speed starts to matter.
- **It helps little for:**
  - Median end-to-end turn time, where 80% is the Sonnet main loop.
  - Multi-hop turns, where each hop adds a full main-loop call of ~3 s. Removing hops would help more.
- **Cheap experiments to run before adopting a new provider:**
  1. Drop or shorten `reason` in the router schema, fewer output tokens being the Anthropic-recommended lever. Log `reason` only on a sampled or debug basis.
  2. Run the router **concurrently** with context assembly, or speculatively start the most-likely skill.
  3. Let the main model route itself, via skills in the system prompt plus a hand-off tool, removing one serial call.
  4. Add a semantic pre-router for the top-N frequent phrasings, with the LLM as fallback.
- Caveat: n=159 turns (n=28 on the current structured prompt). Percentiles, especially p90/p99, are noisy.

### Gaps
- No external, published measurement of router share of turn latency in production agents was found.
- TTFT was not measured separately. Phoenix spans give total call duration, not first-token time.
- Whether the router call benefits from prompt caching was not verified. No `cache_control` was seen in `create_router_choice`, and Haiku's minimum cacheable length was not checked.

## 7. What are the risks of adding a second model provider to the loop (privacy, failure modes, tracing, consistency)?

### Takeaway
The risks are:
- a second data processor, which needs its own retention and training policy review;
- a second failure domain, whose timeouts and outages must fall back safely without causing silent mis-routing;
- instrumentation that may not match OpenInference or Phoenix conventions out of the box;
- behavioural drift between the two models' interpretations of the same skill catalogue.

Mazkir's own history shows that silent router fallbacks produce *fabricated-action* failures, so a new provider's error path must be explicit.

### Cited Findings
- **Privacy:**
  - Anthropic structured outputs are eligible for zero data retention (ZDR), excluding "Covered Models" — [Claude structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
  - Aggregators add their own policy layer. OpenRouter's `zdr: true` restricts routing to ZDR endpoints, and `data_collection: "deny"` blocks providers that store or train on inputs. "ZDR enforcement only applies to provider routing for inference requests. It does not apply to plugins and tools" — [OpenRouter ZDR docs](https://openrouter.ai/docs/guides/features/zdr); [OpenRouter data residency](https://openrouter.ai/blog/insights/ai-data-residency/)
- **Local-first routers** keep routing data on the device:
  - Arch-Router 1.5B is open-weight and runs locally — [HF](https://huggingface.co/katanemo/Arch-Router-1.5B)
  - semantic-router supports fully local encoders — [GitHub](https://github.com/aurelio-labs/semantic-router)
  - The hybrid-router vision keeps "most computations... locally, with cloud collaboration only as needed" — [arXiv 2504.10519](https://arxiv.org/abs/2504.10519)
- **Failure modes:**
  - Mazkir's router, before 2026-09-13, silently fell back to `mazkir`, a skill with no write tools. The result was replies claiming work that never ran. Fallback is now logged at ERROR — [Mazkir CLAUDE.md, local](file:///home/marcellmc/dev/mazkir/CLAUDE.md); `services/router_service.py` (local)
  - External router APIs add a network hop, reportedly 50–120 ms for Not Diamond (aggregator claim, unverified) — [dev.to](https://dev.to/kuldeep_paul/7-best-llm-routing-tools-for-latency-and-cost-2026-4mm1)
- **Tracing:** Phoenix relies on per-SDK OpenInference instrumentors, as its examples register `OpenAIInstrumentor` explicitly. A second provider needs its own instrumentor, or manual spans with `openinference.span.kind = LLM`, to appear with token counts and model name — [Phoenix: Running experiments](https://arizeai-433a7140.mintlify.app/docs/phoenix/datasets-and-experiments/how-to-experiments/running-experiments); [Phoenix: Span kinds](https://arizeai-433a7140.mintlify.app/docs/phoenix/tracing/how-to-tracing/setup-tracing/instrument)
- **Consistency:**
  - Schema guarantees differ by provider. Anthropic's structured outputs constrain decoding ("constraining the model's token sampling to schema-valid output") — [Claude strict tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use)
  - A second provider without equivalent constrained decoding brings back the JSON-parse fallback class of error. That class was 21% of router calls in Mazkir's pre-fix sample (local Phoenix).

### Inferences
- A second provider on the router path should meet four conditions:
  1. It is behind a hard timeout, with the Haiku router as fallback, not a default skill.
  2. It emits the same span attributes (model, tokens, `skill.routing_reason`) so experiments compare like with like.
  3. It is checked for constrained-decoding support.
  4. It is reviewed for retention and training terms, because router inputs carry the recent conversation transcript.
- If the goal is only speed, local options (semantic pre-router, Arch-Router-class model) avoid the privacy question entirely, though they add a model to host.

### Gaps
- No published incident data or reliability comparison for multi-provider router setups was found.
- OpenInference instrumentor coverage for any specific new provider ("Jev") was not checked; other researchers cover that model.
