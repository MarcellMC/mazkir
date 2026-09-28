# Jev: identity, capabilities, API, pricing and data policy (as of 2026-09-26)

## 1. What exactly is "Jev"? (identity, candidates, confidence)

### Takeaway
"Jev" is almost certainly **Jev by TypeSafe AI** (typesafe.ai), a proprietary "System One" *decision model*, not an LLM. It launched in limited early access in mid-September 2026. It takes text or JSON "state" plus typed questions and returns typed answers with probabilities rather than generated text. Confidence is **very high (~95%)**: every exact-name search ("Jev AI model API", "Jev LLM", "Jev fast model launch 2026") resolves to this product, it has vendor docs, a Wikipedia article, and coverage from Bloomberg, Tom's Hardware and Simon Willison, and it matches "a new fast model/API" exactly. It is **not** an Anthropic product.

### Cited Findings
- Jev is "TypeSafe's flagship model and the first System One model". System One models are "built to make fast, structured decisions that software can use directly" — [TypeSafe docs index](https://docs.typesafe.ai/llms.txt); [TypeSafe launch blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
- "Unlike a large language model (LLM), Jev does not generate natural-language text. It instead returns typed values together with probability estimates and confidence scores." Its output is meant to be consumed by software, not read by people — [Wikipedia: Jev (AI model)](https://en.wikipedia.org/wiki/Jev_(AI_model))
- The vendor docs frame it this way: "LLMs are designed to produce text for humans to read. When you need a model to make a judgment that your code will consume, that creates a mismatch." — [TypeSafe docs: Introduction](https://docs.typesafe.ai/introduction)
- The launch blog says Jev "gives up string generation" in exchange for claims that it "can't hallucinate" and "never makes type errors" — [TypeSafe launch blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
- Press coverage confirms it is the same product:
  - Bloomberg (2026-09-25): "Jev, an AI Model That Can't Chat, Takes On Bigger Rivals" — [Bloomberg](https://www.bloomberg.com/news/articles/2026-09-25/jev-an-ai-model-that-can-t-chat-takes-on-bigger-rivals)
  - Tom's Hardware: "TypeSafe AI's Jev offers an alternative to LLMs that claims to be 193x faster and 445x cheaper" — [Tom's Hardware](https://www.tomshardware.com/tech-industry/artificial-intelligence/typesafe-ais-jev-offers-an-alternative-to-llms-that-claims-to-be-193x-faster-and-445x-cheaper-system-one-type-model-is-bespoke-for-probabilistic-decision-making)
  - Simon Willison (2026-09-21): "Jev introduces a new shape of LLM—System One, aka Decision Models" — [simonwillison.net](https://simonwillison.net/2026/Sep/21/jev/)
- It is listed on OpenRouter as "Jev 1.13" under the `typesafe` namespace — [OpenRouter](https://openrouter.ai/typesafe/jev-1.13)
- Vendor-described use cases: "classifying support tickets, routing requests, scoring risk, deciding whether an action needs review, or selecting the next model in an agent workflow". TypeSafe positions it as a complement to an LLM rather than a replacement — [Wikipedia](https://en.wikipedia.org/wiki/Jev_(AI_model)); [Towards Data Science (search result)](https://towardsdatascience.com/jev-vs-llms-when-ai-moves-from-generation-to-decision-making/)
- Other "Jev" results are unofficial third-party or SEO sites about the same TypeSafe model, not separate products:
  - `jevai.org` ("Jev API & Hub for the Jev Model | Jev AI Community") — [jevai.org](https://www.jevai.org/jev-api)
  - `jev.pro` — [jev.pro](https://jev.pro/explainers/data-handling/)
  - `jevaiguide.com` — [jevaiguide.com](https://jevaiguide.com/faq/does-jev-train-on-your-data/)
  - `jevwiki.ai` — [jevwiki.ai](https://jevwiki.ai/wiki/entities/typesafe-ai.md)
  - a Hugging Face community blog under the user "sora-2" — [HF blog](https://huggingface.co/blog/sora-2/how-to-use-the-jev-ai-model-a-step-by-step-develop)
- A separate "JEV AI" site at `jevai.me` has its own privacy policy. I did not verify what it is — [jevai.me](https://jevai.me/privacy)

### Inferences
- The unofficial hubs (jevai.org, jev.pro, jevaiguide.com, jevwiki.ai) look like SEO or fan sites riding the launch's virality. Use none of them as a source, and never use them as an API endpoint. The only official domains are `typesafe.ai`, `docs.typesafe.ai`, `api.typesafe.ai`, `console.typesafe.ai` and `evals.typesafe.ai`.
- Name-collision caveat, from background knowledge and not verified this session: "Typesafe" was also the name of the Scala/Akka company later renamed Lightbend. TypeSafe AI (founded 2024) appears to be unrelated.
- For Mazkir, the router's job is to pick one of five skills from a short message plus recent context. That is exactly the "Choice" decision Jev is built for, so the product does match the stated use case.

### Gaps
- I did not investigate `jevai.me` ("JEV AI"), so I cannot rule out a small unrelated product sharing the name. Nothing suggests it is "a new fast model/API".

## 2. Vendor, release date, model family, variants, context window, modalities

### Takeaway
TypeSafe AI is a San Francisco startup founded in 2024. It came out of stealth with a $40M seed round led by DCVC and released Jev in limited early access on **2026-09-15** (one source says 2026-09-25, see below). The only model is **`jev-1.13.0`**; the `jev-latest` and `jev-preview` aliases both point to it. The context window is **64k tokens per request**, of which 32k covers the state plus the longest question. Input is **text only**.

### Cited Findings
- **Company and founders:** San Francisco–based TypeSafe AI, founded 2024. Founders are Diogo Almeida (CEO; about 4 years at OpenAI on RLHF, InstructGPT, ChatGPT and GPT-4), Erik Gafni and Sasha Sheng — [Wikipedia](https://en.wikipedia.org/wiki/Jev_(AI_model))
- **Funding:** $40M seed round led by DCVC, at a reported $200M valuation (per Forbes, cited by Wikipedia), after about 2 years in stealth — [Wikipedia](https://en.wikipedia.org/wiki/Jev_(AI_model)); [emergent.sh / MindStudio search results](https://www.mindstudio.ai/blog/jev-system-one-model-launch)
- **Release date:** limited early access on 15 September 2026 — [Wikipedia](https://en.wikipedia.org/wiki/Jev_(AI_model)); [Startup Fortune](https://startupfortune.com/typesafe-ais-decision-model-jev-becomes-vercels-fastest-adopted-launch/)
  - **Conflict:** my fetch of the launch blog returned a date of "September 25, 2026" — [TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
  - Bloomberg (dated 2026-09-25) says the launch video was "from just over a week ago", which fits a mid-September launch — [Bloomberg](https://www.bloomberg.com/news/articles/2026-09-25/jev-an-ai-model-that-can-t-chat-takes-on-bigger-rivals)
- **Availability:** "available today in early access", with developers "brought off the waitlist as quickly as we can" — [TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
- **Model IDs:**
  - Current model: `jev-1.13.0`
  - `jev-latest` → `jev-1.13.0`, described as "The most recent stable, official release"
  - `jev-preview` → `jev-1.13.0`, currently identical
  - — [TypeSafe docs: Models](https://docs.typesafe.ai/models)
- **Earlier version:** the vendor's skill-suggestion cookbook was run on `jev-1.12`, so pre-release versions existed — [TypeSafe cookbook: Skill Suggestion](https://docs.typesafe.ai/cookbooks/skill_suggestion.md)
- **Context limits:** "64k tokens per request", with "State + longest question" limited to 32k combined — [TypeSafe docs: Models](https://docs.typesafe.ai/models)
- **Modalities:** "Text only. String, JSON object, or array of text values. No image, audio, or video input." — [TypeSafe docs: Models](https://docs.typesafe.ai/models)
- **Architecture and training:**
  - Transformer-based; the exact architecture and weights are unpublished and there is no technical paper
  - Trained with "Reinforcement Learning for Calibrated Decisions (RLCD)", on synthetic data exclusively
  - — [Wikipedia](https://en.wikipedia.org/wiki/Jev_(AI_model)); [TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
- **How outputs are produced:** "Parallel. Generates all outputs in a single query", i.e. non-autoregressive — [TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
- **Three question types:**
  - **Choice** returns an option plus per-option probabilities plus confidence
  - **Score** returns a level plus probabilities plus confidence
  - **Noul** returns a yes/no probability between 0 and 1
  - Types can be mixed in one call and are "evaluated in parallel and in isolation against the same state in one go" — [TypeSafe docs: Introduction](https://docs.typesafe.ai/introduction)
- **Customisation:** the model is not fine-tuned per customer. Behaviour is shaped only through the `state`, `instructions` and `criteria` fields — [TypeSafe docs: Models](https://docs.typesafe.ai/models)
- **Name:** after economist William Stanley Jevons (the Jevons paradox) — [Wikipedia](https://en.wikipedia.org/wiki/Jev_(AI_model))

### Inferences
- The product is about 11 days old and there is exactly one model version. Expect fast iteration on the `jev-latest` alias and possible behaviour drift. A production router should pin `jev-1.13.0` rather than use the alias.
- Mazkir's router input (recent conversation as a quoted transcript plus the skill list) is far below the 32k state budget.

### Gaps
- No official size or parameter count, no technical report, and no published deprecation policy.
- The exact launch-day date in the vendor blog could not be reconciled (Sept 15 vs Sept 25). The weight of evidence favours Sept 15.

## 3. Advertised latency and benchmarks (especially classification, routing, tool selection)

### Takeaway
TypeSafe claims **70–500 ms end-to-end** per request and "40x–200x faster" than frontier LLMs. Its best self-reported figures are 193.6x faster and 444.6x cheaper. All benchmarks are **vendor-run on vendor-built workflows**, and I found no independent quantitative benchmark. The vendor cookbook most relevant to Mazkir (skill selection with Claude Haiku 4.5 as the agent) reports **0.09–0.31 s** latency, and Jev's suggestions roughly halved Haiku's wrong skill loads.

### Cited Findings
- **Latency:** "End-to-end response time is 70ms-500ms", claimed as "40x-200x faster" than frontier LLMs — [TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
- **Peak claims:** 193.6x faster and 444.6x cheaper "on our home page" workflow evaluations — [TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
- **Vendor caveat:** TypeSafe acknowledges the workflows were internally created and the results likely represent the "high end of real-world results" — [Wikipedia](https://en.wikipedia.org/wiki/Jev_(AI_model))
- **Press scepticism:** TechStock²/TS2 headline: "TypeSafe AI raises $40 million for Jev but its 445x cost claim is still self-tested" (cited via Wikipedia's reference list; not fetched) — [ts2.tech](https://ts2.tech/en/typesafe-ai-raises-40-million-for-jev-but-its-445x-cost-claim-is-still-self-tested/)
- **No token-level latency figures:** there is no time-to-first-token or tokens/sec figure. Outputs are produced in one parallel pass, not streamed token by token — [TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
- **Batching questions:** "questions are evaluated in parallel" and "adding questions barely impacts response time" — [TypeSafe docs: Choice](https://docs.typesafe.ai/primitives/choice.md)
  - The parallel-questions cookbook is billed as "12.2x cheaper and 10.0x faster" — [TypeSafe docs index](https://docs.typesafe.ai/llms.txt)
- **Skill-suggestion cookbook (closest analogue to Mazkir's router):**
  - Task: pick one of **182 skills** (Nous Research Hermes catalog, 33 categories) for **488 single-turn requests**; 315 are covered by exactly one skill and 173 by none
  - Agent model: `claude-haiku-4-5-20251001`; TypeSafe model: `jev-1.12`
  - Results:

    | Condition | Wrong loads | Needless loads |
    |---|---|---|
    | Haiku alone | 16.8% | 9.8% |
    | With TypeSafe suggestion | 7.3% | 4.0% |
    | Oracle | 2.5% | 1.2% |

    ("2.3x fewer wrong loads, 2.4x fewer needless ones")
  - Latency: ~0.16–0.31 s to rank all 182 skills, ~0.09–0.12 s to rerank the top 3
  - State passed as `{"request": request, "recent_context": ""}`, i.e. **no conversation context was tested**
  - Gate and fit thresholds were both 0.30
  - — [TypeSafe cookbook: Skill Suggestion](https://docs.typesafe.ai/cookbooks/skill_suggestion.md)
- **Other routing-related docs:** the vendor publishes an "Intent Routing" pattern ("Classify incoming requests and route each to optimal handler"), a "Confidence-Gated Routing" pattern and a "Function Calling" cookbook ("Natural language to function calls") — [TypeSafe docs index](https://docs.typesafe.ai/llms.txt)
- **Re-ranking cookbook:** "Raise top-1 accuracy from 5% to 18%" — [TypeSafe docs index](https://docs.typesafe.ai/llms.txt)
- **Independent hands-on (qualitative only):** Simon Willison calls it "very fast" and "really cheap", and notes that batch queries take about as long as single ones. He published no latency numbers — [Simon Willison](https://simonwillison.net/2026/Sep/21/jev/)
- **Adoption signal (Vercel's claim, reported second-hand):** within 24 hours on Vercel AI Gateway, Jev reached nearly 13% of paid teams, "the fastest-adopted model launch in AI Gateway history" — [Startup Fortune](https://startupfortune.com/typesafe-ais-decision-model-jev-becomes-vercels-fastest-adopted-launch/)

### Inferences
- The skill-suggestion cookbook tests Jev **augmenting** Haiku 4.5 (suggesting a shortlist that Haiku then acts on), not replacing it. It is single-turn only. Mazkir's router relies on recent conversation (for example "log reading 06:35–07:35" following earlier turns), so it would need its own evaluation with multi-turn context.
- Mazkir has 5 options, against the cookbook's 182, so the choice problem is much easier. Jev's likely advantage is latency, cost, and a calibrated probability usable as a fallback gate. Accuracy on 5 classes may already be high with Haiku.
- The 70–500 ms end-to-end figure is the vendor's. Network round-trip from the user's location to US-hosted endpoints is additional or included in an unspecified way.

### Gaps
- No independent, reproducible latency or accuracy benchmark exists yet (the product is about 11 days old).
- No published p50/p95 latency distributions.
- No benchmark on multi-turn or conversational intent routing, and none on non-English inputs.

## 4. API surface: REST/SDK, compatibility, structured output, tool calling, streaming, batching, caching

### Takeaway
Jev has a **proprietary single-endpoint REST API**: `POST https://api.typesafe.ai/v1/systemone` with Bearer auth. There are official **Python** (sync and async) and **JavaScript** SDKs. Output is structured by construction: a Choice question is effectively an enum-constrained classifier returning the full probability distribution. It is **not** OpenAI- or Anthropic-Messages-compatible, and it has no streaming, no text generation and no native tool calling. It is also reachable through OpenRouter and Vercel AI Gateway.

### Cited Findings
- **Endpoint and auth:** `POST https://api.typesafe.ai/v1/systemone`, with `Authorization: Bearer <API_KEY>` and `Content-Type: application/json` — [TypeSafe API reference](https://docs.typesafe.ai/api.md)
- **Request fields:**
  - `state` (required): "string | object | array"
  - `model` (required): e.g. `"jev-latest"`
  - `questions` (required): a map of user-keyed Question objects, each with `type`, `instructions` and `criteria`
  - Instructions may be "string | object | array"
  - — [TypeSafe API reference](https://docs.typesafe.ai/api.md)
- **Response fields:** `model`, `answers` (keyed like the questions) and `usage: {input_tokens, output_tokens}`. Per answer type:
  - choice: `{type, choice, probabilities, confidence}`
  - score: `{type, score, legend, probabilities, confidence}`
  - noul: `{type, noul: 0–1}`
  - — [TypeSafe API reference](https://docs.typesafe.ai/api.md)
- **Limits:** "Maximum 255 options per Choice question"; Score takes 2–10 levels; there is no stated maximum number of questions per request — [TypeSafe API reference](https://docs.typesafe.ai/api.md)
- **Choice option descriptions** can be strings, objects or arrays. Object descriptions with `what`, `not_for` and `examples` are recommended when options are easily confused — [TypeSafe docs: Choice](https://docs.typesafe.ai/primitives/choice.md)
- **Probabilities and confidence:** probabilities across options "sum to 1.0". Confidence runs from 0 to 1 and reflects the shape of the distribution ("flat shape…means low confidence. A single peak…means high confidence") — [TypeSafe docs: Choice](https://docs.typesafe.ai/primitives/choice.md)
- **Vendor routing guidance:**
  - Add an `other` / `none of the above` option
  - Treat confidence "below 0.3-0.5" as a signal for review or escalation rather than automatic routing
  - — [TypeSafe docs: Choice](https://docs.typesafe.ai/primitives/choice.md)
- **Error codes:** 401 (bad key), 422 (validation), 429 (rate limited, use exponential backoff), 529 (overloaded) — [TypeSafe API reference](https://docs.typesafe.ai/api.md)
- **Streaming, batching, caching:** none documented on the API reference page — [TypeSafe API reference](https://docs.typesafe.ai/api.md)
- **SDKs:**
  - Python: `TypeSafeClient` (sync), `AsyncTypeSafeClient` and `RetryPolicy`
  - JavaScript/TypeScript: `TypeSafeClient`, typed `ChoiceQuestion`/`ChoiceResponse` and `choice()`/`noul()`/`score()` helpers
  - Both SDKs have changelogs
  - — [TypeSafe docs index](https://docs.typesafe.ai/llms.txt)
- **Agent Skill:** a "Drop-in skill for Claude Code, Codex, and other agent environments" — [TypeSafe docs index](https://docs.typesafe.ai/llms.txt)
- **Third-party access:**
  - Simon Willison's `llm-typesafe` plugin for the `llm` CLI and Python library (released 2026-09-22), e.g. `llm -m jev 'Please refund my last payment.' -s 'Does this message explicitly request a refund?'` — [Simon Willison](https://simonwillison.net/2026/Sep/21/jev/)
  - Routed through OpenRouter — [OpenRouter](https://openrouter.ai/typesafe/jev-1.13)
  - Routed through Vercel AI Gateway — [Startup Fortune](https://startupfortune.com/typesafe-ais-decision-model-jev-becomes-vercels-fastest-adopted-launch/)
- **Text generation:** "not trained to generate text" and "performs poorly when forced to do so" — [TypeSafe docs: jev-1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md)

### Inferences
- A Mazkir integration would be one small new client in `router_service.py`:
  - one Choice question with the five skills as `criteria`, plus an `other` option
  - state = `{message, recent_transcript}`
  - `confidence` and `probabilities` returned directly
- This replaces the Haiku call with `output_config.format` enum. It also returns a real probability distribution, which Haiku's structured output does not give. That distribution could drive a "low confidence → fall back to Haiku" gate, matching TypeSafe's "Confidence-Gated Routing" pattern.
- Jev cannot replace the skill executors, which need generation and tool use. It can only replace or augment the classifier.
- The async Python SDK fits the FastAPI backend, and raw `httpx` would also work given the single endpoint.

### Gaps
- Not confirmed:
  - whether OpenRouter or Vercel expose Jev through an OpenAI-compatible schema, or how the Choice/probabilities payload maps onto it
  - timeout defaults, rate-limit response headers, regional endpoints, request batching or prompt caching (none appear in the docs I read)
  - exact Python package name and version (the SDK pages were not fetched)

## 5. Pricing, rate limits, free tier

### Takeaway
Input costs **$0.042 per million tokens** ($42 per billion), and **output tokens are free**. Default rate limits are **250,000 tokens/s and 1,200 requests/min**, "adjusting dynamically" under launch demand. Access is early access behind a waitlist. I found no documented free tier.

### Cited Findings
- "$0.042 / MTok ($42 per billion tokens)" for input; output "FREE (too cheap to meter)" — [TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
- "Charged per input token. Output tokens are free." — [TypeSafe docs: Models](https://docs.typesafe.ai/models)
- Rate limits: "250,000 tokens per second / 1,200 requests per minute". Overage returns `429 Too Many Requests`. "Rate limits are adjusting dynamically" due to demand, and custom or enterprise plans are available — [TypeSafe docs: Models](https://docs.typesafe.ai/models)
- An independent comparison: Jev's input price undercuts OpenAI's GPT-5 Nano at $0.05/M input — [Simon Willison](https://simonwillison.net/2026/Sep/21/jev/)
- **Conflict:** Wikipedia's article (as summarised by my fetch) lists "No public pricing model disclosed", which is contradicted by the vendor docs and blog above — [Wikipedia](https://en.wikipedia.org/wiki/Jev_(AI_model)) vs [TypeSafe docs: Models](https://docs.typesafe.ai/models)

### Inferences
- **Per-call cost for Mazkir:** a ~2,000-token router call would cost about $0.000084 (2,000 × $0.042 / 1,000,000). At dozens of messages a day, cost is negligible.
- The saving over Haiku 4.5 is real, but it is small in absolute dollars at personal-assistant volume. Latency and calibrated confidence are the more meaningful gains. (Haiku 4.5's own price is not verified in this note and should be taken from Anthropic's pricing page.)

### Gaps
- No free tier or trial credits confirmed.
- Pricing when routed through OpenRouter or Vercel (possible markup) not verified.
- No minimum charges or per-request fees documented.

## 6. Data policy: retention, training, ZDR, hosting region

### Takeaway
TypeSafe **commits not to train on customer inputs**. Beyond that the default terms are weak for private personal data:
- retention is open-ended ("as long as reasonably necessary … or otherwise in support of our business or commercial purposes")
- **zero data retention is offered to enterprise customers only**
- the service is **hosted in the United States**
- the privacy policy (last updated 2025-11-19) names no security certifications

### Cited Findings
- Training: "We will not train or fine tune any artificial intelligence or machine learning models on your prompts or other Input." (Privacy Policy, last updated "Nov 19, 2025") — [TypeSafe Privacy Policy](https://typesafe.ai/legal/privacy-policy)
- The docs add that Jev is not trained on customer requests, and that zero data retention is for enterprise — [TypeSafe docs: Models](https://docs.typesafe.ai/models)
- Retention: personal data is kept "as long as reasonably necessary to provide you with the Services, or otherwise in support of our business or commercial purposes". No specific retention periods are stated for API inputs or outputs — [TypeSafe Privacy Policy](https://typesafe.ai/legal/privacy-policy)
- ZDR: "Offered for enterprise customers; contact sales@typesafe.ai". A Data Processing Agreement and Master Customer Agreement also exist — [TypeSafe docs: Legal](https://docs.typesafe.ai/legal.md)
- Hosting: "The Services are hosted in the United States ("U.S.")". EEA and UK users are "transferring your personal data outside of those regions to the U.S." — [TypeSafe Privacy Policy](https://typesafe.ai/legal/privacy-policy)
- The policy refers only generically to "vendors and service providers" and Google Analytics. It names no certifications, and on security says only "We make reasonable efforts to protect your data…" — [TypeSafe Privacy Policy](https://typesafe.ai/legal/privacy-policy)
- A secondary source summarises that ZDR is limited to enterprise and that the retention section "permits retaining personal data as reasonably necessary for service/business purposes" — [GitHub: burin-labs/harn issue #8633 (search result)](https://github.com/burin-labs/harn/issues/8633)
- A third-party aggregator publishes a TypeSafe profile covering ZDR, training posture and GDPR DPA (not fetched) — [Opper AI](https://opper.ai/provider/typesafe)
- A critical opinion piece is titled "TypeSafe/Jev Won't Train on Your Data. It Can Still Learn From It." (not fetched, so its argument is unverified) — [Medium, Eduard Ruzga](https://wonderwhy-er.medium.com/typesafe-jev-wont-train-on-your-data-it-can-still-learn-from-it-563f0ad591b6)

### Inferences
- **Two kinds of personal data would reach TypeSafe:**
  - Every user message and the recent transcript (the router state), including health reminders, locations and personal notes.
  - The skill descriptions in every call.
- Under the default (non-enterprise) terms, all of this may be retained indefinitely in the US. That is a materially weaker posture than a provider with default short retention or ZDR available to individuals.
- Routing through OpenRouter or Vercel would add another processor with its own retention terms.
- The privacy policy predates the Jev launch (Nov 2025), so it may not have been written with API inputs in mind.

### Gaps
- The DPA and Master Customer Agreement were not fetched, so any API-specific retention window, logging or abuse-monitoring periods, and subprocessor list are unknown.
- No SOC 2, ISO 27001 or GDPR/CCPA details were found.
- Not confirmed whether individuals or small accounts can obtain ZDR.

## 7. Self-hosting / open weights / license

### Takeaway
**No.** Jev is proprietary and available only as a hosted API (direct, or via OpenRouter and Vercel). No weights, architecture details or technical paper have been released.

### Cited Findings
- License: proprietary. Architecture and weights are unpublished and there is no technical paper — [Wikipedia](https://en.wikipedia.org/wiki/Jev_(AI_model))
- Wikipedia notes that outside observers speculated it may be built on an open-weight LLM foundation. This is unconfirmed — [Wikipedia](https://en.wikipedia.org/wiki/Jev_(AI_model))
- The model is not fine-tuned per customer, so there is no customer-specific deployable artifact — [TypeSafe docs: Models](https://docs.typesafe.ai/models)

### Inferences
- A local, private router is not possible with Jev. If data residency matters more than latency, a local classifier would be the alternative (for example a small open-weight model or an embedding classifier).

### Gaps
- No on-prem or VPC deployment offering was found (the enterprise plans may include one, but nothing says so).

## 8. Known limitations and languages (English, Hebrew, Russian)

### Takeaway
Jev is **English-primary**. Other languages "are handled but not equally well", and Hebrew and Russian are not mentioned at all. The vendor's own known-limitations page for jev-1.13 names several weaknesses that matter to Mazkir's router:
- **literal reading** of instructions
- **unreliable date/time reasoning**
- **accuracy loss as state grows with irrelevant content**, such as long conversation history
- **susceptibility to injected instructions**

### Cited Findings
- Languages: "Primary: English". "Other languages, including CJK scripts, are handled but not equally well" — [TypeSafe docs: Models](https://docs.typesafe.ai/models)
- The known-limitations ("jaggedness") page for jev-1.13 lists:
  1. **Literal reading:** it "answers the question you wrote, not the one you meant. Scoping words, negations, and implied conditions are read at face value."
  2. **Counting:** unreliable.
  3. **Numeric formats:** weak with hex, RGB and similar representations.
  4. **Arithmetic:** "not a calculator".
  5. **Dates and times:** "reads dates as text, not as ordered quantities. Asking which of two dates comes first, how far apart they are, or whether one falls inside a window is unreliable."
  6. **Indirection:** double negatives and complex indirection are answered less reliably.
  7. **Irrelevant state:** "Accuracy falls as the state grows with content unrelated to the decision."
  8. **Adversarial content:** it can be influenced by injected instructions or misleading framing in the state.
  9. **Contradictions:** contradictory instructions and criteria cause confusion.
  10. **No structural invariants:** e.g. no guarantee that P(noul) + P(not noul) = 1.
  11. **Text generation:** poor.
  12. **Multi-step reasoning:** struggles with "System Two" tasks that need extra levels of indirection.
  - — [TypeSafe docs: jev-1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md)
- Simon Willison criticises its opacity ("the only thing you're going to get back is a floating point number"), which makes bias hard to probe. He repeats the docs' note that it "is currently not great with numbers, dates, or adversarial content" — [Simon Willison](https://simonwillison.net/2026/Sep/21/jev/)
- "Can't hallucinate" is a claim about the output type: answers are always drawn from the defined option set. The vendor still documents that the chosen answer can be wrong (see the limitations above) — [TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev); [TypeSafe docs: jev-1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md)

### Inferences
- **Conversation context:** Mazkir's router passes recent conversation, and CLAUDE.md records that a lost context turned "Bar hopping" into an unanswerable fragment. Jev's degradation with irrelevant state argues for a trimmed state, e.g. the last 2–4 turns plus the pending question, rather than the full window. The effect must be evaluated.
- **Time-anchored messages:** many Mazkir messages carry times ("log reading 06:35–07:35", "remind me in a month"). Routing them only needs "is this time-management?", not date arithmetic, so the date weakness probably does not hurt routing. It does rule out using Jev for any time-interval decisions.
- **Language:** Hebrew and Russian quality is unknown, and "not equally well" is the vendor's own hedge. Mixed-language messages need a dedicated eval before relying on Jev without a Haiku fallback.
- **Injection:** forwarded messages and replies are user-controlled text inside the state. The adversarial-content caveat means a confidence-gated fallback is prudent.

### Gaps
- No per-language accuracy figures, and no mention of Hebrew (right-to-left) or Russian.
- No published evaluation of how accuracy degrades with conversation-history length.
- No independent study of calibration quality: whether the probabilities are well calibrated on real routing data.
