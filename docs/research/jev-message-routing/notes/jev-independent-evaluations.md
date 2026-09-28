# Jev (TypeSafe AI): independent evaluations for LLM-style message routing, as of late September 2026

Labels used throughout:
- **[IND]**: an independent third-party measurement with a stated method.
- **[IND-weak]**: third-party, but with a tiny sample, the same author writing labels and prompts, or a partner or commercial interest.
- **[VENDOR]**: a claim by TypeSafe or relayed from TypeSafe docs.
- **[PARTNER]**: a claim by a distribution partner (Vercel etc.).
- **[ANECDOTE]**: forum or social posts.

Every data point below falls between 2026-09-15 (launch) and 2026-09-24. No earlier model versions exist. Nearly every test names the model as `jev-1.13.0`.

## Which product is "Jev"?

### Takeaway
"Jev" is TypeSafe AI's "System One" or "decision" model, launched in limited early access on 2026-09-15. It is not an LLM: it takes text or JSON state plus typed questions and returns only typed values with probabilities (Choice / Score / yes-no "Noul"). It clearly matches "a new fast model/API". No competing product called "Jev" turned up. The only near-hits were unrelated (JMEV, an EV maker; Jeep).

### Cited Findings
- Jev is a proprietary model from TypeSafe AI, a San Francisco company founded in 2024 by Diogo Almeida (formerly OpenAI RLHF, InstructGPT, ChatGPT and GPT-4), Erik Gafni and Sasha Sheng. It was released in limited early access on 2026-09-15 alongside a $40M seed round led by DCVC. — [Wikipedia: Jev (AI model)](https://en.wikipedia.org/wiki/Jev_(AI_model))
- It does not generate natural-language text. It returns typed values with probability estimates and confidence scores, meant for software to consume. — [Wikipedia](https://en.wikipedia.org/wiki/Jev_(AI_model))
- There are three question types: Noul (a yes/no probability from 0 to 1), Choice (a distribution over the options you supply) and Score (a position on a scale of 2–10 levels). Multiple questions on one document are processed in parallel and take roughly the same time as one. — [Simon Willison, 2026-09-21](https://simonwillison.net/2026/Sep/21/jev/); [Flavio Copes, 2026-09-24](https://flaviocopes.com/jev/)
- The API endpoint is `POST https://api.typesafe.ai/v1/systemone`. — [search result citing jevai.org / Tom's Hardware coverage](https://www.jevai.org/jev-api); also referenced in [git-loopy issue #620](https://github.com/bradcstevens/git-loopy/issues/620)
- [VENDOR] "40–200x faster and 40–400x cheaper than frontier LLMs", with a peak of 193.6x faster and 444.6x cheaper on TypeSafe's own workflows. — [Wikipedia](https://en.wikipedia.org/wiki/Jev_(AI_model)); [Tom's Hardware](https://www.tomshardware.com/tech-industry/artificial-intelligence/typesafe-ais-jev-offers-an-alternative-to-llms-that-claims-to-be-193x-faster-and-445x-cheaper-system-one-type-model-is-bespoke-for-probabilistic-decision-making)
- [VENDOR] Pricing is $0.042 per million input tokens, and output is free. Willison notes this undercuts GPT-5 Nano at $0.05/M. — [Simon Willison](https://simonwillison.net/2026/Sep/21/jev/)
- Jev is available through Vercel AI Gateway, OpenRouter and Cloudflare Workers AI within a week of launch. — [Vercel changelog](https://vercel.com/changelog/typesafe-ai-jev-now-available-on-ai-gateway); [eesel review, 2026-09-21](https://www.eesel.ai/blog/typesafe-jev-review) (Cloudflare Workers AI); [Flavio Copes](https://flaviocopes.com/jev/) (Vercel, same pricing)
- [ANECDOTE] An HN commenter (hbrn) speculated that Jev might be a fine-tuned, rebranded Qwen, since it "performs on-par with SemIf which was built in a couple days". This is unverified speculation. — [HN: Show HN JevBench](https://news.ycombinator.com/item?id=49800574)

### Inferences
- The router workload fits a Choice question over about 5 skill names almost exactly. The recent conversation goes in as the "state" (text or JSON), and the output is a probability distribution over the enum rather than generated text.
- Because it is not an LLM, the usual LLM leaderboards (Artificial Analysis, LMArena, BFCL) are the wrong instruments, and I found none that lists it. The relevant third-party evidence is small practitioner benchmarks plus one community leaderboard (JevBench).

### Gaps
- There is no model card or technical report with architecture details from an independent source. The only architecture speculation found is the HN "fine-tuned Qwen" comment.

## Independent latency measurements (TTFT, end-to-end, p50/p95)

### Takeaway
Independent measurements put Jev at about **130–450 ms p50** end-to-end, depending on where the client is and the task. Haiku 4.5 measured about **630–1,200 ms** in the same harnesses. That makes Jev **1.4x–5.4x faster than Haiku 4.5** in head-to-heads, which is far below the vendor's "40–200x" framing against *frontier* LLMs. The service runs only on the US West Coast, so latency measured from Europe is noticeably higher. "Time to first token" does not apply, because there is no token stream.

### Cited Findings
- [IND-weak] **LiteLLM auto-router benchmark (2026-09-20).** 4-tier complexity routing, 80 cases × 3 repeats = 240 calls per classifier. **Jev p50 126.81 ms / p95 231.16 ms. Haiku 4.5 p50 688.40 ms / p95 896.94 ms.** That is 5.43x faster at p50 and 3.88x at p95. — [LiteLLM blog](https://docs.litellm.ai/blog/jev-auto-router-benchmark)
- [IND] **wotai-dev comparison of 16 models on 150 identical passages (2026-09-18).** Jev 455 ms p50 against Haiku 4.5 631 ms p50, about 1.4x. The author calls Jev "the fastest model in the whole field". — [wotai-dev/typesafe-jev-tools](https://github.com/wotai-dev/typesafe-jev-tools)
- [IND] **jev-phishing-bench (2026-09-17)**, measured from France. Jev about 239 ms against Haiku 4.5 about 687 ms. — [beri.net write-up](https://www.beri.net/article/typesafe-jev-typed-decision-model-calibration-decomposition-shadow-eval)
- [IND] **Open-Jev benchmarks**, hosted providers over fresh HTTPS connections. Customer-service suite of 8 questions: **Jev 1.13.0 p50 295.26 ms / p95 330.37 ms**. GPT-5.6 Luna 918.13 / 1443.13 ms. GPT-6 Astra 1938.39 / 2375.71 ms. A self-hosted Open-Jev-2B on a local H100 managed 85.03 / 133.91 ms. The page warns these "are client-observed deployment times, not matched-hardware model speedups". — [Open-Jev benchmarks](https://zefan-cai.github.io/open-jev/benchmarks/)
- [IND] **JevBench v1.4.2** (scored 2026-09-24, measured from Germany only). **Jev 1.13.0 latency 0.65 s**, against **Gemini 3.1 Flash-Lite 0.76 s**. The public endpoints run on shared infrastructure and reflect that day's performance. — [JevBench leaderboard](https://benchmarkheaven.com/jev-models); [JevBench GitHub](https://github.com/fstandhartinger/jevbench)
- [IND-weak] **jock.pl (2026-09-21), 40 support tickets.** Jev "370 milliseconds" per call against Haiku 4.5 "1.2 seconds". The author says 370 ms is "the real number when the service is up". — [thoughts.jock.pl](https://thoughts.jock.pl/p/jev-typesafe-system-one-model-benchmark-2026)
- [IND-weak] **LangChain agent-evaluator test (2026-09-20).** Jev averaged 0.44 s per call. — [LangChain blog](https://www.langchain.com/blog/jev-agent-evals-langsmith)
- [IND] **Lightfield (2026-09-20), long-context questions over a roughly 20K-token article.** Jev 429 ms against Claude Opus 5 at 2,252 ms. — [Lightfield](https://lightfield.app/blog/testing-typesafe-jev-on-text-understanding)
- [IND-weak] MindStudio reports about 150 ms for a single question, with 30 questions batched in a similar time. A trained 22M-parameter encoder took **8 ms on CPU**, and a trained BERT router 26 ms. The benchmark's author and methodology are not identified. — [MindStudio](https://www.mindstudio.ai/blog/jev-vs-classic-classifiers-benchmark)
- [IND] Senko Rašić ran 3,000 texts in about a minute for about 20 cents. His local fine-tuned BERT on an RTX 3060 ran "at about the same speed" (2026-09-22). — [Senko Rašić](https://blog.senko.net/analyzing-jev-a-new-ai-model)
- [VENDOR] Latency is 70–500 ms end to end, mostly about 100 ms, measured from the US West Coast where the service runs. Callers elsewhere add network time on top. — [Flavio Copes, relaying TypeSafe docs](https://flaviocopes.com/jev/)
- [PARTNER] Vercel CEO Guillermo Rauch: "Jev is up to 18x faster (p95) and more accurate". — relayed by [eesel review](https://www.eesel.ai/blog/typesafe-jev-review)

### Inferences
- For a short-message router, a realistic expectation is about **130–300 ms p50** from North America and **about 250–650 ms** from Europe. That is still 2–5x under Haiku 4.5's roughly 690 ms p50 in the same harnesses.
- The spread across studies (127 ms to 650 ms) seems to come mainly from client location and launch-week load, not from prompt length. Lightfield's 20K-token prompt still returned in 429 ms.
- A trained embedding or encoder classifier (8–26 ms) is an order of magnitude faster than Jev, if labeled data exists.

### Gaps
- There is no Artificial Analysis or OpenRouter throughput or latency page for Jev; the searches returned none.
- No study reports a p99 or a latency distribution under sustained load. None measured specifically at about 500-token prompts with 5 labels.
- Location-matched Jev-vs-Haiku numbers exist only as pairs *within* each study, and no two studies share a location.

## Accuracy on intent classification, routing and multi-label tasks

### Takeaway
Results are mixed and task-dependent. On routing and intent-style tasks Jev ranges from "roughly equal to Haiku 4.5" to "clearly better", and on some single-question judgment tasks it is clearly worse. Zero-shot, it beats classic NLI classifiers but loses to a *trained* small encoder when labeled data exists. On the harder JevBench decisions its chance-corrected "intelligence" is far below reasoning LLMs.

### Cited Findings
- [IND-weak] **LiteLLM router (2026-09-20)**, 4-label complexity tiering (SIMPLE / MEDIUM / COMPLEX / REASONING). The cases were 40 short, 16 long, 8 follow-ups, 8 tool-context and 8 boundary. **Jev 228/240 = 95.00% against Haiku 4.5 177/240 = 73.75%.** The two classifiers agreed on 78.75% of cases. Caveat: "Labels and prompts came from the same author, without independent annotation or blind adjudication", and downstream answer quality was not measured. — [LiteLLM](https://docs.litellm.ai/blog/jev-auto-router-benchmark)
- [IND] **MindStudio-reported Banking77** (77-way intent, zero-shot). **Jev 80.1%**, about 22 cents in total. A classic zero-shot NLI scored 48.8% and an updated NLI 66.7%. A **trained 22M encoder with logistic regression scored 93.2%**. The trained classifiers also beat Jev on the emotion and phishing datasets. Yelp star rating: Jev 67.2%. The provenance of this "recent independent benchmark" is not identified. — [MindStudio](https://www.mindstudio.ai/blog/jev-vs-classic-classifiers-benchmark)
- [IND-weak] **jock.pl (2026-09-21)**, routing 40 support tickets to 3 teams. Jev got 39/40, and the one error came with confidence 0.33, the lowest in the run. The write-up also calls this "perfect routing", which is internally inconsistent. It compared Haiku 4.5, Claude Fable 5.1, GPT-6 Astra and Gemini Flash, but the fetched summary gave no per-model accuracy for routing. — [thoughts.jock.pl](https://thoughts.jock.pl/p/jev-typesafe-system-one-model-benchmark-2026)
- [IND] **Pre-registered test on primeline.cc (2026-09-18).** On commit-message classification (800 items): **Jev 65.8%**, Opus 5 63.5%, GPT-5.6 59.5%, **Haiku 4.5 54.6%**. On knowledge-base category classification (450 items): **Haiku 4.5 97.8%**, GPT-5.6 92.7%, **Jev 90.7%**, Opus 5 86.9%. — [primeline.cc](https://primeline.cc/blog/typesafe-jev-pre-registered-test)
- [IND] **wotai-dev (2026-09-18).** Primary task, 150 passages: Jev 66.0% and Haiku 4.5 66.0%. Business category (149 rows): **Jev 79.9% against Haiku 83.2%**. Commit type (100 rows): **Jev 50.0% against Haiku 42.0%**. — [wotai-dev/typesafe-jev-tools](https://github.com/wotai-dev/typesafe-jev-tools)
- [IND] **Phishing, 2,000 emails (2026-09-17).** Asked as a single question, **Jev scored 62.6% against Haiku 4.5's 81.3%** (McNemar p < 0.0001). Split into 5 narrow questions with logistic-regression weights fitted on 1,000 labeled examples, Jev reached 95.0% against Haiku 93.2% and a two-line regex 91.8%. That gap is not significant (p = 0.063). — [beri.net](https://www.beri.net/article/typesafe-jev-typed-decision-model-calibration-decomposition-shadow-eval)
- [IND] **Senko Rašić (2026-09-22)**, 3,000 **Croatian** texts, binary classification. Jev zero-shot scored 97.1% against his fine-tuned BERT at 97.6%. Where the two disagreed, Jev often followed the stated definition more literally than the mislabeled data did. — [Senko Rašić](https://blog.senko.net/analyzing-jev-a-new-ai-model)
- [IND] **Lightfield (2026-09-20)**, n=100 each. Jev scored 91% on CommonsenseQA, 80% on MMLU-CF and 95% on RACE-H, against Opus 5 at 90 / 79 / 95. On a custom 20K-token passage task it scored 90%, matching Opus 5. — [Lightfield](https://lightfield.app/blog/testing-typesafe-jev-on-text-understanding)
- [IND] **JevBench v1.4.2 (2026-09-24).** The families are routing, adequacy judging, policy checks, intent classification, ordinal scoring and enum extraction, across 534 decisions. Jev 1.13.0 scores **Intelligence 53.1** (chance-corrected), Calibration 76.3, Speed 83.3, Cost $0.040 per 1k decisions, **overall 63.3, ranked #2** of 89. #1 is decider-4b v2 at 64.1. Jev's accuracy by tier: **Easy 100%, Standard 99%, Judge 95%, Hard 74%, Sealed 37%**. For comparison, GPT-6 Luna (low reasoning) scores Intelligence 95.8, and Gemini 3.1 Flash-Lite scores Intelligence 54.5. **No Claude model is on the board.** — [JevBench leaderboard](https://benchmarkheaven.com/jev-models); [JevBench GitHub](https://github.com/fstandhartinger/jevbench)
- [IND] **Open-Jev, JevBench public set.** Jev 1.13.0 scored 200/231 (86.58%) against GPT-6 Astra 231/231 (100%). — [Open-Jev](https://zefan-cai.github.io/open-jev/benchmarks/)
- [IND] **Eesel's own trial (2026-09-21)**, support triage over 284 chats plus a 100-ticket validation. Triage accuracy was 93%, and spam detection caught 100% with no false positives. — [eesel](https://www.eesel.ai/blog/typesafe-jev-review)
- [VENDOR, relayed] TypeSafe's own 4-workflow benchmark puts Jev at about 68% accuracy, "close to mid-tier LLMs like GPT-5.6 Terra". — search summary of [DataCamp](https://www.datacamp.com/blog/system-one-models-jev) / vendor materials; not verified on the page.

### Inferences
- The routing-specific evidence (LiteLLM's 95% against Haiku's 73.75%; jock.pl's 39/40) favours Jev. Both studies are small and self-labeled, and LiteLLM's task (complexity tiering) is subjective. They show Jev is *competitive* as a router, but they do not establish that it is more accurate than Haiku 4.5 in general.
- In the balanced head-to-heads Jev wins some tasks and Haiku wins others, sometimes by 3–7 points either way. Treat the two as roughly comparable on clean categorical routing. **Expect Jev to lose badly when one question has to carry a compound judgment** (phishing: 62.6% against 81.3%).
- Decomposing into narrow questions is the documented way to recover accuracy, which argues for designing router questions as "Is this a request to log or schedule something with a time?" rather than a vague "which skill?"
- The Croatian result is the only non-English evidence. JevBench is English-only.

### Gaps
- No independent test of **multi-label** intent (several labels at once).
- No test of routing with **conversation context** (follow-ups that only make sense given prior turns), except LiteLLM's 8 follow-up cases, which were not broken out separately.
- No Gemini Flash / Flash-Lite, GPT-5 mini/nano or semantic-router results on a *routing* task alongside Jev. JevBench lists Flash-Lite, but not per family.
- The number of labels (5 skills) versus accuracy was not studied, although the API allows up to 255 Choice options.

## Structured-output reliability (schema/enum adherence, function calling, off-format failures)

### Takeaway
By construction Jev can only return a value from the options you supply, so the classic LLM failure modes cannot happen: prose instead of JSON, continuing the conversation, truncation mid-reasoning. The reliability questions shift to **calibration** (moderately good, but overconfident on Choice and Score) and **service availability** (launch-week overload errors). It does not do function calling, so BFCL-style numbers do not exist.

### Cited Findings
- Choice answers are constrained: "every answer is constrained to the options I supplied", and multiple selections are not allowed. — [Flavio Copes](https://flaviocopes.com/jev/)
- [IND] Smaller Claude models sometimes "begin working the problem in visible output and get truncated" when constrained to single-letter answers, and Jev "has no such issue". — [Lightfield](https://lightfield.app/blog/testing-typesafe-jev-on-text-understanding)
- [IND] JevBench's "Easy" tier is a function-calling baseline. Jev scores 100% on it, as does decider-4b v2. — [JevBench leaderboard](https://benchmarkheaven.com/jev-models)
- [IND] Open-Jev's TREC-DL retrieval suite recorded that "Jev had 108 mass-validation failures affecting 66 queries". Jev was also weak on that retrieval-ranking task (nDCG@10 0.276 / 0.191 against GPT-5.6 Luna's 0.730 / 0.702). The page notes "Response validity does not establish equal task quality". — [Open-Jev](https://zefan-cai.github.io/open-jev/benchmarks/)
- [IND] **Calibration (wotai-dev):** Jev's ECE is 0.121 against Haiku 4.5's 0.122. Jev said "unsure" on **34.7%** of items against Haiku's 2.7%, and produced 56 distinct confidence values against Haiku's 11. "If your code does not branch on the confidence value, none of this matters." — [wotai-dev](https://github.com/wotai-dev/typesafe-jev-tools)
- [IND] **Calibration (phishing):** ECE 0.154 on single verdicts. A separate study found an ECE of 0.107, 4.4x the 0.024 noise floor, on synthetic support tickets, with **overconfidence on Choice and Score and underconfidence on yes/no**. On questions whose answers could not be inferred from the text, Jev was right 44.7% of the time while giving an average probability of 0.74. — [beri.net](https://www.beri.net/article/typesafe-jev-typed-decision-model-calibration-decomposition-shadow-eval)
- [IND] **Calibration (Banking77):** mean reported confidence 88% against about 80% actual accuracy, i.e. mild overconfidence. Temperature scaling cut calibration error by about two-thirds. — [MindStudio](https://www.mindstudio.ai/blog/jev-vs-classic-classifiers-benchmark)
- [IND] At a 0.9 confidence threshold Jev was correct about 92% of the time, and 73% of the pooled test set cleared that threshold. — [primeline.cc](https://primeline.cc/blog/typesafe-jev-pre-registered-test)
- [IND-weak] Jev matched the oracle on all 500 repeated binary decisions (5 scenarios × 100). GPT-5.6 Terra matched 99.8%, Luna 96.4% and Claude Sonnet 4.6 80.0%. Its variance was far lower (for example, Sonnet's was 92x Jev's). This is a very small scenario set, and LangChain co-hosted a livestream with TypeSafe. — [LangChain](https://www.langchain.com/blog/jev-agent-evals-langsmith)
- [ANECDOTE] HN user 542458 reports that the "AI slop detector" demo gave keyboard-mash input "86% confidence that the text was AI written". — [HN](https://news.ycombinator.com/item?id=49800574)
- [ANECDOTE / reviewer opinion] Eesel's reviewer agrees with HN critics that "calibrated confidence" is not the same as "can't hallucinate", and that the vendor's no-hallucination framing is oversold. — [eesel](https://www.eesel.ai/blog/typesafe-jev-review)

### Inferences
- The failure Mazkir hit (a router continuing the chat instead of emitting its choice) cannot occur with Jev. With Claude it is already addressed by enum-constrained structured output (`output_config.format`), so this is parity on format, not an advantage on it.
- Jev's distinctive asset is a probability per option, usable as a fallback threshold (for example, below 0.6 goes to the conversational default or triggers a clarifying question). The independent evidence says the probability is informative but overconfident on Choice, so the threshold should be tuned on logged traffic.

### Gaps
- No independent measurement of API-level error rates over time: HTTP errors, timeouts, malformed responses.
- The meaning of Open-Jev's "mass-validation failures" is not explained on the page.

## Multi-intent: several intents or actions from one message

### Takeaway
There is **no independent evaluation of multi-intent extraction** with Jev. Structurally, Choice is single-select. The documented pattern is to ask several independent Noul (yes/no) questions in parallel, one per candidate intent or skill, at roughly the latency of one question. Questions cannot see each other's answers.

### Cited Findings
- Choice does not support multi-select. Each question is evaluated independently against the same state in parallel: "one answer never becomes context for another". — [Flavio Copes](https://flaviocopes.com/jev/)
- Multiple questions on one document take about the same time as one. — [Simon Willison](https://simonwillison.net/2026/Sep/21/jev/)
- [IND-weak] About 150 ms for a single question, with 30 questions batched in a similar timeframe. — [MindStudio](https://www.mindstudio.ai/blog/jev-vs-classic-classifiers-benchmark)
- [IND] Five narrow parallel questions, combined by a fitted logistic regression, raised phishing accuracy from 62.6% to 95.0%. This is evidence that parallel narrow questions work well, though it is not multi-intent per se. — [beri.net](https://www.beri.net/article/typesafe-jev-typed-decision-model-calibration-decomposition-shadow-eval)
- [VENDOR, relayed] Documented weaknesses: math and counting, date comparisons and relative references, indirection and double negatives, large irrelevant context, and contradictions between instructions and criteria. — [Flavio Copes](https://flaviocopes.com/jev/); [Simon Willison](https://simonwillison.net/2026/Sep/21/jev/) (numbers, dates, adversarial content)

### Inferences
- For "several skills at once", the Jev-native design is 5 parallel Noul questions ("Does this message ask to log or schedule a timed activity?" and so on), each thresholded. Ordering or dependencies between intents would have to be resolved in code, and extracting the *arguments* of each action (times, names) is out of scope for Jev.
- Router messages that hinge on relative dates ("tomorrow", "last Tuesday") fall inside a documented weak area. That matters only if the routing decision depends on the date, not merely on the presence of one.

### Gaps
- No accuracy data for multi-label or multi-intent tasks, and no comparison against Haiku 4.5 returning an array of skills.

## Head-to-head: Jev vs Claude Haiku 4.5 and other fast options (cost, latency, accuracy)

### Takeaway
Against Haiku 4.5, Jev is consistently **1.4–5.4x faster** and **about 12–26x cheaper per decision** (up to 96% cheaper), with accuracy that is **task-dependent and roughly comparable**. Neither is uniformly better. Against Gemini 3.1 Flash-Lite on JevBench, Jev has similar raw intelligence, better calibration, slightly lower latency and about 6.6x lower cost. Reasoning LLMs (GPT-6 Luna) are far more accurate on hard decisions but slower and costlier. Trained small encoders beat Jev's zero-shot accuracy and speed when labeled data exists.

### Cited Findings

| Study (date) | Task | Jev | Haiku 4.5 | Other | Label |
|---|---|---|---|---|---|
| [LiteLLM](https://docs.litellm.ai/blog/jev-auto-router-benchmark) (09-20) | 4-tier router, 240 calls | 95.00% · p50 127 ms · $0.0077 for 240 calls | 73.75% · p50 688 ms · $0.199 for 240 calls | — | IND-weak |
| [wotai-dev](https://github.com/wotai-dev/typesafe-jev-tools) (09-18) | 150 passages / business category / commit type | 66.0% / 79.9% / 50.0% · 455 ms | 66.0% / 83.2% / 42.0% · 631 ms | 16 models in total | IND |
| [primeline](https://primeline.cc/blog/typesafe-jev-pre-registered-test) (09-18) | commits (800) / KB category (450) | 65.8% / 90.7% | 54.6% / 97.8% | Opus 5 63.5/86.9; GPT-5.6 59.5/92.7 | IND (pre-registered) |
| [beri / phishing](https://www.beri.net/article/typesafe-jev-typed-decision-model-calibration-decomposition-shadow-eval) (09-17) | 2,000 emails, single question / 5-question decomposition | 62.6% / 95.0% · ~239 ms · $0.038 per 1k | 81.3% / 93.2% · ~687 ms · $0.462 per 1k (single), $1.02 (five-signal) | regex 91.8% | IND |
| [jock.pl](https://thoughts.jock.pl/p/jev-typesafe-system-one-model-benchmark-2026) (09-21) | 3-team routing, 40 tickets | 39/40 · 370 ms · $0.0000172 per call | 1.2 s · ~$0.0005 per call | Fable 5.1, GPT-6 Astra, Gemini Flash (accuracy not given in summary) | IND-weak |

- [IND] **JevBench v1.4.2 (09-24).** Jev: Intelligence 53.1, Calibration 76.3, 0.65 s, $0.040 per 1k decisions, overall score 63.3. **Gemini 3.1 Flash-Lite**: Intelligence 54.5, Calibration 59.3, 0.76 s, $0.264 per 1k, overall score 14.3. **GPT-6 Luna (low)**: Intelligence 95.8, Calibration 92.0, $0.127 per 1k, overall score 35.1. GPT-5.6 Luna: Intelligence 93.1, $0.242 per 1k. The score formula weights cost and speed at 50%, which penalises LLMs heavily. The rerankers bge-reranker-v2-m3 and mxbai-rerank-base-v2, used as "neutral adapters", scored Intelligence 5.0–6.8. Small open "Jev-class" models such as decider-4b v2 (Intelligence 49.4, about $0.020 per 1k) sit right next to Jev. — [JevBench](https://benchmarkheaven.com/jev-models)
- [IND] Primeline estimates Jev's input price at "about 24 times cheaper than Haiku 4.5's input price on paper". Its full suite of 9,750 Jev calls cost about $0.38. — [primeline.cc](https://primeline.cc/blog/typesafe-jev-pre-registered-test)
- [IND-weak] The trained 22M encoder with logistic regression scored 93.2% on Banking77 at 8 ms on CPU, against Jev's 80.1% zero-shot. — [MindStudio](https://www.mindstudio.ai/blog/jev-vs-classic-classifiers-benchmark). Senko's fine-tuned BERT scored 97.6% against Jev's 97.1%. — [Senko Rašić](https://blog.senko.net/analyzing-jev-a-new-ai-model)
- [IND] Open small models: a self-hosted Open-Jev-9B scored 77.49% and Open-Jev 27B 85.28% on the JevBench public set, against Jev's 86.58%. Open-Jev-2B ran at p50 85 ms on a local H100. — [Open-Jev](https://zefan-cai.github.io/open-jev/benchmarks/)
- [IND-weak] LangChain's judge test included Sonnet 4.6 (80.0% oracle match) but neither Haiku nor Gemini. Jev cost $0.34 in total against Claude's $28.17. — [LangChain](https://www.langchain.com/blog/jev-agent-evals-langsmith)
- Conflict: eesel's 2026-09-21 review states there were "no published comparisons with Claude Haiku 4.5 or Gemini Flash". Several were already published on 09-17 and 09-18, so that statement was stale when written. — [eesel](https://www.eesel.ai/blog/typesafe-jev-review)
- Conflict in JevBench scores: the Show HN post (about 09-23) listed Jev at **74.4**, ranked #1. The v1.4.2 board (09-24) shows **63.3, ranked #2**. This is probably a change in scoring version or protocol, since the GitHub page notes a formula change in v1.2+. Cite the version with any JevBench number. — [HN](https://news.ycombinator.com/item?id=49800574); [JevBench](https://benchmarkheaven.com/jev-models)

### Inferences
- For a Mazkir-style router already on Haiku 4.5 with enum structured output, switching to Jev would save about 0.4–0.6 s per turn and nearly all the router's cost, which is already small. The accuracy change is unpredictable without testing on Mazkir's own logged messages. The independent results point both ways by 3–20 points depending on the task.
- The cheapest and most accurate option, *if labeled routing data exists* (for example, from Mazkir's logged router decisions), is a trained small encoder or embedding classifier. The evidence shows these beating zero-shot Jev at 10–50x lower latency.
- No study includes GPT-5 mini/nano or Gemini Flash (non-Lite) with published per-task accuracy next to Jev on routing.

### Gaps
- No Artificial Analysis, OpenRouter-stats or LMArena data for Jev.
- No GPT-5 nano/mini head-to-head. Willison compares only price.
- No study measures Haiku 4.5 *with* enum structured output against Jev. Most Haiku runs presumably used plain prompting, so Haiku's format failures may be inflated relative to a structured-output setup.

## Known problems, outages, rate limits and regressions

### Takeaway
Launch-week capacity problems are documented: `system_overloaded` errors and a signup pause on 2026-09-22 "due to demand". Access is still early-access and waitlist-gated, and there are published but "dynamically adjusted" rate limits. Other concerns: black-box outputs with no justification, observed bias, overconfidence, and skepticism about the benchmarks and the funding hype. No quality regressions between versions have been reported, since there has been only about 10 days of public life and version 1.13.0 throughout.

### Cited Findings
- [IND-weak] Mid-test, the author hit "five system_overloaded errors in six calls" before the service stabilised (2026-09-21). — [thoughts.jock.pl](https://thoughts.jock.pl/p/jev-typesafe-system-one-model-benchmark-2026)
- TypeSafe paused new signups on 2026-09-22 due to demand, while existing accounts kept working. Access is also available through Vercel AI Gateway at the same price. — [Flavio Copes, 2026-09-24](https://flaviocopes.com/jev/)
- [search-snippet only, not verified on page] Access began as a waitlist, and Reddit users reported approval arriving within hours for some and a day or more for others. TypeSafe opened signups to everyone on 2026-09-20 with $5 of free credit, then paused them on 09-22. — surfaced in search results alongside [Flavio Copes](https://flaviocopes.com/jev/) / [Firecrawl](https://www.firecrawl.dev/blog/what-is-jev)
- [VENDOR, relayed] Early-access rate limits are 250,000 tokens/s and 1,200 requests/min, "adjusting dynamically during early access". — [Flavio Copes](https://flaviocopes.com/jev/). Conflict: eesel (09-21) found "no pricing page (every `/pricing` URL 404s today), no published plan tiers or rate limits". — [eesel](https://www.eesel.ai/blog/typesafe-jev-review)
- Some developers could not confirm whether their API key was even activated. For example, a git-loopy planning issue exists solely to "verify live Jev access" before integrating. — [git-loopy #620](https://github.com/bradcstevens/git-loopy/issues/620)
- [IND-weak] LiteLLM's integration wraps Jev in a circuit breaker with a 30 s cooldown and falls back to the default model on timeout or malfunction. This is a design precaution, not a reported incident. — [LiteLLM](https://docs.litellm.ai/blog/jev-auto-router-benchmark)
- Limits: about 32K tokens for the longest single question and about 64K shared across state and questions. Input is text or JSON only, with no images. — [Flavio Copes](https://flaviocopes.com/jev/)
- Willison warns that Jev gives no justification for its decisions. His city-scoring experiment showed apparent bias (Cupertino rated high, East Palo Alto lowest), and he warns against uses such as hiring. — [Simon Willison](https://simonwillison.net/2026/Sep/21/jev/)
- [ANECDOTE] HN: the CEO has reportedly opposed public benchmarking before. Commenters question $40M and two years in stealth for performance on par with quickly built community models, and raise contamination risk from held-out prompts sent to external APIs. — [HN](https://news.ycombinator.com/item?id=49800574). JevBench itself warns "not public is not the same as not seen". — [JevBench GitHub](https://github.com/fstandhartinger/jevbench)
- [PARTNER] Vercel says Jev is "the fastest-adopted model in AI Gateway history". — [Vercel blog](https://vercel.com/blog/ai-gateway-jev-model-launch)

### Inferences
- For a production router, Jev should sit behind a timeout and fallback (for example, about 1 s, then fall back to the current Haiku router or the `mazkir` default). Launch-week overloads and paused signups mean availability is not yet established.
- Relying on direct TypeSafe access is currently gated. Vercel AI Gateway and OpenRouter are the practical paths if direct signup stays paused.

### Gaps
- No status page, SLA or uptime history found.
- No reports of quality regressions. There is no version history beyond 1.13.0 in the evidence.
- The terms of service and data-retention policy for sending chat context to TypeSafe were not covered by any third-party source found.
