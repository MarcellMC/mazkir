# Location Trips: Mazkir notices you are moving, guesses why, and fills in the day (Design)

**Status:** Draft, written 2026-11-10 from conversation, after the L0 spike's first five days of data.
**Replaces:** §5 (L1) of `docs/specs/2026-11-05-location-check-in-design.md`, and pulls forward the part of §6 (L2) it needs, which is your places getting coordinates. L2's points-of-interest lookup, L3 (reminders by kind of place) and L4 are unchanged and still later.
**Related:**
- `docs/specs/2026-09-10-ship5-inferred-capture-design.md`: proposals, ✓ ✕ ✎, and approval ticking a habit.
- `docs/specs/2026-09-27-fast-lane-design.md`: receipts and taps, `run_tool`, the principle.
- `docs/specs/2026-08-29-ship2-navigable-day-design.md`: source availability.

---

## 1. What this is for

You share your live location with the bot all the time, and you log very little by hand. This design answers one question: **when you move, what were you doing?**

When it can't tell, Mazkir asks the question once, as soon as it is confident you are on the move. When it can tell, it doesn't ask. Either way, every trip ends up as a proposed block in `/day`, and Mazkir sends you a message when you arrive, so it takes one tap to confirm the block and one tap or one sentence to fix it.

Your own words, from the conversation:
- Mazkir should "recognize that I'm on the move and ask me where I'm going. As soon as it's confident that I'm changing location."
- It shouldn't simply assume a dog walk. Infer it "from the existing data: habits, tasks, current schedule, user reports/conversations. Dog walks are usually twice a day ~12 hrs apart, so they are the easiest to infer, but it could be anything."
- "If there are several good guesses (high confidence), Mazkir could propose a few options to choose from with inline keyboard, or type in something else."
- "If I didn't answer, but got home eventually, update suggested block with end time."
- "There should always be options to quickly approve suggested block or edit it: nudge timestamps with buttons and/or correct Mazkir with NL prompt."
- "When I both nudge times and reply with text, it means I want to edit both timestamps and the activity itself."
- A dog walk that Mazkir inferred without asking still gets a message when you're back.

### 1.1 Goals

1. **Notice a departure quickly.** The target is within about 3 minutes of leaving, including a short walk around the block.
2. **Guess the trip's purpose from what Mazkir already knows.** That means your habits, today's schedule, your open tasks and todos, what you said recently, and where you usually go from this place at this time. Ask only when no single guess is strong.
3. **Ask well.** Ask once per trip. Offer the strong guesses as buttons and let you type anything else.
4. **Log commutes.** A trip from one place to another becomes travel blocks and stop blocks. A loop from home and back that is one activity, such as a dog walk, stays one block, stops included.
5. **Fill the day.** Every trip becomes a proposed block, and its end is set when you arrive, whether or not you answered.
6. **Make correction cheap.**
   - ✓ approves the block.
   - The nudge pad shifts its times.
   - A plain reply corrects it.
   - A nudge plus a reply is one edit of both the times and the activity.
7. **Learn your places.** When you answer "Alex's" and then arrive somewhere, that spot becomes Alex's place. Next time Mazkir names it without asking.

### 1.2 Non-goals (here)

- **Asking what you're doing while you stay at home.** You want this ("I'm usually doing something, but rarely logging my activity"). It is deferred to the time-awareness work, because Mazkir needs a sense of time to ask at a good moment. It will share this design's question budget and message format.
- Naming places from OpenStreetMap or Google (L2 §6.2) and reminders by kind of place (L3). For now, a place with no name stays unnamed until you answer.
- A map view.

### 1.3 Anti-goals: things that would make this a failure even if it works

- **A question on a routine dog walk.** If Mazkir asks "where are you going?" twice a day for a walk it could have guessed, you will start ignoring it.
- **More than one question per trip, or a question nobody needed.** That includes a question caused by GPS jitter while you sit still, and a re-ask when you didn't answer.
- **A duplicate block.** When you have already logged "Dog walk 10:24" yourself, the trip completes that block rather than adding a second one.
- **Anything written to Google before you approve it.** A proposal stays local until ✓, as Ship 5 already does.
- **Coordinates in a model call, a span or a log line.** This rule carries over from L0. The model sees place names, distances in metres, durations, speeds and times, never latitude or longitude.

### 1.4 The principle, restated

The fast lane's rule holds: **the model decides what something says, code decides what happens.** Code finds trips, builds the candidate list, applies the thresholds and writes the blocks. One model call per trip, at most, ranks candidates that code already built, and it can only name one of them or "unknown" (§5.3). A trip with no model call at all, because one candidate clears the bar by rule, is the normal case for dog walks.

---

## 2. What the spike showed (5 Nov – 10 Nov)

Run with `python scripts/location_spike_report.py --from 2026-11-05 --to 2026-11-10`.

- **One share has run for five days without stopping.** It is the "until I turn it off" option, `live_period = 2147483647`. That's about 5,700 points, no failed posts, and a delay of 1 s at p50 and p90.
- **Sampling is dense.** Since 6 Nov 10:24, a point arrives every 32 s (p50) while moving and every 36 s (p50) while still, nights included. Before that moment it was sparse, apparently until Telegram was next opened. The cause is not known yet.
- **Two holes so far:**
  - the evening of 5 Nov, from 16:20, when sampling was sparse and a ~20-minute dog walk got a single point;
  - 8 Nov 18:35–20:28, 112 minutes with no points, ending 615 m from where they started.

  The design has to treat silence as missing data, not as "nothing happened" (§4.4).
- **Accuracy:**
  - `horizontal_accuracy` is 15 m at p50 and 33 m at p90, with a maximum of 496 m;
  - points taken while you're still sit within 5 m of their centre at p50 and 9 m at p90;
  - bad points come in bursts of 250–400 m accuracy, and isolated points can be a few hundred metres off.
- **Short walks stay close to home.** The evening walks on 7 Nov went no further than 144 m and 163 m. With L1's placeholder 150 m visit radius, they would not have counted as leaving home. Leaving is therefore detected with a tighter rule than staying (§4.1).
- **The naïve stay-point pass:**
  - turned slow dog-walk loops into "visits";
  - split one stay in two at a 1-minute gap (band practice);
  - split one night at home at a single 385 m point;
  - cut a visit at midnight (Alex's birthday).

  §4 fixes each of these.
- **Dog walks are twice a day, about 11–12 hours apart:** 7 Nov at 10:07 and 21:00, 8 Nov at 07:20 and ~18:35, 9 Nov at 08:29 and 20:00. They range from 8 minutes within 160 m to almost 3 hours with three stops up to 1.7 km away. `memory/20-habits/dog-walk.md` has `daily_target: 2`.

### 2.1 The labelled days

You described the unlabelled trips: mostly dog walks, some of them long, plus commutes home, such as the walk from Alex's birthday at his home with a stop at the café in Gan Meir. So Mazkir writes the labels itself, from that description and your logged blocks, into `data/eval/location/{date}.json`, and you don't label anything by hand. The labels are:

| Day | Trip (from the points) | Label | Evidence |
|---|---|---|---|
| 5 Nov | ~20:01–20:21, 1 point at 131 m | Dog walk | you said so |
| 6 Nov | 10:24–10:38, up to 340 m | Dog walk | logged 10:24–10:38 |
| 6 Nov | 11:25 → stay 11:28–17:34 at 205 m → home 17:37 | Walk to band practice · Band practice · Walk home | logged 11:20–17:50 |
| 6 Nov | 19:20–19:28, up to 268 m | Dog walk | logged 19:17 |
| 6 Nov | 19:36 → 20:10 to 2.4 km, stay until 7 Nov 07:54 | Bus to Alex's · Alex's birthday | logged "Bus to …" 19:40–20:00 and the party from 20:00 |
| 7 Nov | 07:54 → café 08:04–09:14 at 1.75 km → home 09:50 | Walk to Gan Meir · Café at Gan Meir · Walk home | logged café until 09:13, home ~10:02; you described it |
| 7 Nov | 10:07–10:46, up to 727 m, stop 10:20–10:28 | Dog walk | logged 10:02 |
| 7 Nov | 21:00–21:20, up to 163 m | Dog walk | pattern |
| 8 Nov | 07:20–10:10, up to 1.7 km, three stops | Dog walk (long) | you said the unlogged trips are mostly long dog walks |
| 8 Nov | ~18:35–20:41, silent 112 min, 655 m at the end | Dog walk (long) | you confirmed it |
| 9 Nov | 08:29–08:49, up to 201 m | Dog walk | logged 08:37 |
| 9 Nov | 20:00–20:13, up to 272 m | Dog walk | pattern |
| 9 Nov | 23:08 → bar at up to 920 m → home 04:31 | Walk to the bar · Bar · Walk home | you said so |
| 10 Nov | 09:17–09:41, up to 245 m | Dog walk | pattern |
| 10 Nov | from 10:16, to ~700 m | Walk to café · Coffee (still there at 10:55), then sauna | you said so |

The 10 Nov morning is the case §5 exists for. The dog walk at 09:17 had just happened, so the second trip, an hour later, cannot be the morning walk. With no coffee or sauna on the schedule and no habit due, Mazkir has no strong guess and asks "Where to?".

`Dinner at Leyman's` (logged, ending 19:13 on 6 Nov) shows in the points as a stay 10 m from home. So it was either at home or next door, and it is labelled as a stay at home with that name.

---

## 3. How it fits what exists

| Piece | Where | Used for |
|---|---|---|
| Raw points, ingest | `services/location_store.py`, `POST /locations/points` (L0) | Unchanged; trips are derived from them |
| Proposals | `create_event(proposed: true)`, `approval.resolve_state`, `_settle_proposal` | Every trip block is a proposal. Approval creates the Google entry and the `## Schedule` line, as it already does |
| Habit tick on approval | `tick_if_habit` (Ship 5) | ✓ on a "Dog walk" block ticks Dog Walk |
| ✓ ✕ ✎ and the nudge pad | `formatters/block-edit-rich.ts`, `callbacks/day-actions.ts` (`adj:` / `adjsave:`) | The ✎ on a trip message opens the same pad |
| Receipts with per-line taps | `formatters/receipt-rich.ts`, `callbacks/receipt.ts` | The shape of the arrival message (§6.3) |
| The bot remembering its question | `state/open-question.ts` | A typed answer to "where to?" is understood as one (§6.2) |
| Replies to rich messages | `bot-utils/rich-text.ts` `repliedToText` | A reply to an arrival message reaches the agent with its text |
| Places by name | `services/fast_lane/places.py`, `data/places.json` | Gain coordinates (§7) |
| Sending without being asked | the ingest response (L0 spec §7.4), not `telegram_notifier.py` | §6.1 |

---

## 4. From points to trips

An **online** detector runs on each ingested point, after the raw append, which never changes. It keeps its state in `data/locations/state.json` and its output in `data/locations/derived/{date}.json`. `scripts/location_rebuild.py` replays raw files through the same code, so changing a threshold means a rebuild, not a migration. The thresholds below are starting values, to be tuned on the labelled days (§9).

### 4.1 A stay, and leaving it

- **Point filter:** a point with `accuracy_m` over 100 m is not used for detection. A point whose implied speed from both its neighbours is above 150 km/h and which jumps out and straight back is an outlier and dropped. That is the single 385 m point on 9 Nov.
- **Stay:** points within 100 m of their running centre for at least 8 minutes. The stay's **spread** is the p90 distance of its points from the centre, typically under 10 m.
- **Leaving a stay is a separate, tighter rule.** It fires when 3 points in a row with accuracy ≤ 50 m lie farther from the stay's centre than `max(60 m, 3 × spread + their accuracy)`, and keep getting farther or stay out for at least 2 minutes. The 7 Nov evening walks reached 144–163 m within 2–4 minutes, so they are caught. Jitter of a few metres around a 9 m spread is not.
- **Departure time** is the last point inside the stay, not the moment the rule fires. So a block starts when you actually left, and a question sent at 3 minutes still carries the true start.
- **Merging:** two stays less than 100 m apart with less than 10 minutes between them are one stay. That fixes band practice.
- **Midnight doesn't split anything.** Stays and trips span days. Blocks are split at 00:00 only when written, the way `create_event` already splits them.

### 4.2 A trip

A **trip** runs from leaving a stay to arriving at the next stay that matters. It is made of **legs** (moving) and **stops**.

- **The mode of a leg** is guessed from its median speed: up to 7 km/h is walking, up to 25 km/h cycling or a bus in traffic, above that a vehicle. Cycling and bus aren't separated by speed alone, so a leg in that range is "ride". The answer or the guess names it.
- **A stop** is a stay during a trip. Whether it is a place you went to, such as the café, or a pause within an activity, such as the dog park, is decided by the trip's purpose (§5), not by its length:
  - a dog walk's stops stay inside the one Dog walk block;
  - a commute's stops of 10 minutes or more become their own blocks;
  - shorter stops on a commute are part of the leg they interrupt.
- **Arrival** is the first stay of at least 8 minutes that isn't a stop of an ongoing loop activity. Arriving home always ends a trip. "Home" is the place where most nights are spent (§7).

### 4.3 What a trip turns into

| Purpose | Blocks |
|---|---|
| A loop activity (dog walk, run, …) that left home and came back | One block, departure → arrival home, stops included |
| A commute (A → B, possibly with stops) | One travel block per leg ("Walk to Gan Meir", "Bus to Alex's"), one block per stop of 10 minutes or more ("Café at Gan Meir"), and an open stay block at the destination ("Alex's birthday"), closed when you next leave |
| Unknown, never answered | "Trip" (a loop) or "Trip to ‹place or distance›" (a commute), with the same structure |

### 4.4 Silence

A gap of more than 10 minutes between points inside a share is **missing data**, never evidence of staying.

- If the points on both sides of the gap are at the same stay, the stay continues, with lower confidence.
- If they are apart, a trip happened inside the gap. It starts at the last point before the gap and ends at the first point after it, and its block is marked `start_precision: "before"` so the message can say "left before 18:35". That is 8 Nov's evening.
- A share that ends closes everything at its last point, and the bot says once, "Location sharing stopped — share again to keep your day filling in" (L0 spec §5.3).

---

## 5. Guessing the purpose

### 5.1 When it runs

1. **At departure**, as soon as §4.1 fires. This decides whether to ask (§5.4).
2. **When the trip stops looking like its guess**, at most once:
   - a "dog walk" that turns into a vehicle leg;
   - one that goes more than about 1.5× farther from home than any approved dog walk;
   - one with a stop of more than 45 minutes at a place that is not one of its usual stops.

   If the purpose was guessed silently, Mazkir may ask now. That is the one late question.
3. **At arrival**, to name a destination that is a known place.

### 5.2 Candidates (code)

Code builds the candidate list from facts, each carrying the evidence behind it:

| Source | Candidate | Evidence it carries |
|---|---|---|
| Habits | Each active habit not yet at today's `daily_target` | Time since its last completion; whether that gap matches your usual spacing, from approved history (e.g. dog walk: ~11–12 h, and 0 or 1 done today); its usual departure hours |
| Today's ledger | Blocks and calendar events starting within the next hour or in progress, especially ones with a location or place | Name, start, place |
| Open todos and tasks | Ones whose text names a place you have or an errand | Text, due date |
| Recent conversation | What you said today about going somewhere ("going to Alex's tonight") | The quoted line |
| Trip history | Approved trips leaving this place at a similar hour on similar days | How many, what they were |
| The trip so far | Mode, distance from home, direction toward a known place | Numbers only, no coordinates |

### 5.3 Ranking (code first, then at most one model call)

- **A rule settles it when it can.** A habit candidate whose spacing, time window and mode all match its own approved history, with nothing in the ledger competing, is **strong** with no model call. That is the twice-a-day dog walk.
- **History on day one.** "Approved history" includes the labelled trips in `data/eval/location/` (§2.1), so dog walks can be settled by rule from the first day instead of after weeks of approvals. My call.
- **Otherwise, one Haiku call** with structured output receives:
  - the candidates and their evidence, as text;
  - the time;
  - the trip so far, as numbers.

  It returns each candidate's likelihood as `strong`, `plausible` or `unlikely`, and may add "something else". Its enum is the candidate ids plus `unknown`, so it cannot invent a purpose, exactly like the router's structured output. About $0.007 a call, and only on trips the rule did not settle.
- A failed or timed-out call counts as "no strong guess", so Mazkir asks. Asking is the safe direction.

### 5.4 Ask or not

| Result | At departure | At arrival |
|---|---|---|
| Exactly one strong candidate | No question | Message with the block (§6.3) |
| Two or three strong or plausible ones | "Where to?" with them as buttons, plus ✎ Something else | Message with the block, named by your answer or the top guess |
| None | "Where to?" with no buttons, or with your usual destinations from here as buttons | Message with "Trip …" |

- **A question is never repeated** for a trip, and an unanswered one is never re-sent.
- **A daily cap of 6 trip questions** catches a bug or a strange day; it does not ration normal ones. My call: you asked to be asked as soon as Mazkir is confident you are moving, and the cap should never bind on an ordinary day.
- **Questions are allowed at any hour.** My call: if you are moving, you are awake. The deferred stay questions will have their own budget of 4 a day.

---

## 6. Talking to you

### 6.1 How a message gets sent

The bot POSTs every point. The ingest response gains `notify: [...]` (L0 spec §7.4), and the bot sends what it lists. That avoids a second channel, and departure is only ever detected on a point arriving anyway. Each item has an id, so a retried POST never sends the same message twice. The server records an item as sent only once the bot acknowledges it.

### 6.2 "Where to?"

> 🚶 You're on the move, left home 18:02. Where to?
> [Dog walk] [Band practice] [Café at Gan Meir] [✎ Something else]

- **A button** names the trip's purpose. If it is a place, it also names the destination.
- **✎ Something else**, or typing without tapping, is read as the answer. The bot keeps the question as an open question (`open-question.ts`). The answer goes through the normal message path with the trip's id in the reply context, and is written onto the trip's blocks: "to Dana's for dinner" names the destination and the stay.
- **An answer after you've already arrived** still applies. It renames the blocks and re-sends nothing.
- **An answer is written to the trip, not just to its blocks:** the purpose, and the destination if one was named. Renaming the blocks alone would leave nothing for §7 to learn the place from, or for the next trip's history (§5.2) to use. A typed answer still goes through the agent, since only a model can read "to Dana's for dinner". The agent then records it on the trip with one new tool, e.g. `set_trip_purpose(trip_id, purpose, destination?)`, rather than with `update_event` alone. The tool's exact shape is the builder's call.

### 6.3 Arriving

One message per trip, when it ends, shaped like a fast-lane receipt, one line per block:

> 🐕 Dog walk 07:20–10:10 · 2 h 50 min, 3.4 km  [✓] [✎]
>
> or
>
> 🚶 Walk to Gan Meir 07:54–08:04  [✓] [✎]
> ☕ Café at Gan Meir 08:04–09:14  [✓] [✎]
> 🚶 Walk home 09:14–09:50  [✓] [✎]
> [✓ All] [✕ Not right]

- ✓ approves the block through the existing approval path. For a dog walk that ticks the habit and creates the Google entry.
- ✎ opens the block-edit view with the nudge pad, already used in `/day`.
- ✕ dismisses the trip's blocks.
- A block whose start is uncertain (§4.4) shows "left before 18:35".
- The blocks are in `/day` from the moment of departure (an open trip renders as ongoing), so the message is a shortcut, not the only way to act on them.

### 6.4 Corrections in words, and words with nudges

- **A reply to the arrival message** ("no, I took the bus", "that was a run") reaches the agent with the message's text through `repliedToText`, plus the trip's block ids, so it can edit the right blocks without asking which.
- **Nudging, then typing.** Today a nudge draft lives only in the callback data, so a typed message after nudging knows nothing of it. The bot now also remembers the **latest unsaved nudge draft** per chat: the block, its date and its two offsets. It is one-shot, expires after 10 minutes, and is held in memory like `open-question.ts`.
  - When a text message arrives while a draft is held, the draft travels with it. The block's times are changed to the draft's and its activity to what the text says, in **one** edit.
  - The reply says both, for example "Run, 07:25–08:10".
  - Saving the draft with the pad's own button clears it, as does any other action on that block.

### 6.5 When you logged it yourself

Before writing a trip's first block, Mazkir looks for a block you made that overlaps the trip or starts within 15 minutes of it, such as "Dog walk 10:24" with no end:

- if its name matches the trip's purpose, or no purpose was guessed, the trip completes **that** block (fills in its end) instead of proposing a new one, and the arrival message shows it as "Dog walk 10:24–10:38 (end from location)";
- if it doesn't match, both stay, and the message asks which one is right.

The end it fills in is still a proposal, so ✓ confirms it. 6, 7 and 9 Nov each had such an open block.

---

## 7. Places

- `data/places.json` entries gain optional `lat`, `lng` and `radius_m`, defaulting to 100 m (L2 spec §6.1, pulled forward). `places.py` keeps resolving by name and gains `nearest(lat, lng)`.
- **Home** is the stay where most nights between 01:00 and 05:00 were spent over the last 14 days. It is written as a place with id `home`, and the bot tells you once that it has found home.
- **Learning:** you answer "Alex's" and the trip ends at a stay that is not a known place. That stay's centre becomes the place "Alex's" (with alias "Alex"), unless a place with that name already has coordinates more than its radius away. In that case Mazkir asks: "Is this a different Alex's?"
- **A stay at a known place** is named after it ("Alex's"). A stay at an unknown place is "Somewhere 2.4 km from home" until you answer.
- Coordinates live only in `places.json` and `data/locations/`, never in the vault, which is a git repo.

---

## 8. Rollout

`LOCATION_TRIPS=off|shadow|on`, read by the server only, with `LOCATION_INGEST=log` as before. Default `off`.

- **shadow:**
  - derives stays and trips;
  - runs the guessing, including model calls;
  - writes `data/logs/location-trips.jsonl`, one line per decision: departure detected, candidates, the question it would ask, the blocks it would propose;
  - writes no blocks and sends no messages.

  `scripts/location_trips_report.py [date]` prints the day as a list of trips with what would have happened.
- **on:** the same, plus blocks and messages.

Shadow first for a few days, read against the labels and your own memory of the day. Then on.

---

## 9. Evaluation

`scripts/location_replay.py` runs the detector and the rule-based part of the guessing over `data/eval/location/`. It is free and offline; `--with-model --confirm-cost` adds the Haiku calls. It scores:

| Measure | Target, first pass |
|---|---|
| Trips found / missed / invented | No dog walk missed, including the 7 Nov evening ones within 163 m; no trips invented from the jitter bursts |
| Departure delay (true departure → rule fires) | p50 ≤ 3 min |
| Start / end error of blocks | p50 ≤ 3 min, p90 ≤ 10 min |
| Purpose right on labelled trips | Dog walks settled by rule, with no question, from the third day of history on |
| Questions per day | ≤ 2 on the labelled days |

The labels grow as you approve or correct trips: an approved trip block is a label. A short `scripts/location_labels_from_ledger.py` writes them back to `data/eval/location/`, so the evaluation improves without you labelling anything.

---

## 10. Failure handling

- **A crash in detection or guessing** is caught and logged at ERROR, and ingest still returns 200. The raw point is already appended, so a rebuild recovers everything.
- **A server restart** reloads `state.json`. A trip in progress continues; a question already sent is not sent again.
- **The model call fails:** no strong guess, so ask (§5.3).
- **A message fails to send:** the bot retries on the next point's response, up to 3 times, then drops it. The blocks are in `/day` regardless.
- **A share stops:** §4.4.
- **The sparse sampling of 5 Nov returns:** trips inside silences get uncertain starts (§4.4). If it becomes common, that is evidence for swapping to a dedicated logger app (L0 spec §1.3), which feeds the same endpoint.

---

## 11. Left to the builder

- File and module layout, within the existing patterns (`services/location_*`, routes, bot `conversations/` and `callbacks/`).
- How trip blocks are made idempotent per trip id: through `run_tool("create_event", …)` with a hidden trip id, as the fast lane does with `_fast`, or a `location_trip` key in `source_ids`. These constraints hold either way:
  - a trip writes each block at most once;
  - its end can be updated on arrival;
  - `reconcile` never drops a trip block because some source was unavailable;
  - approval goes through `_settle_proposal`.
- The exact text of messages, within the shapes in §6.
- The thresholds' final values, set by the replay.

---

## 12. Docs updated in the PR

- `CLAUDE.md`: `LOCATION_TRIPS`, `data/locations/derived/` and `state.json`, the `notify` field on the ingest response, and an architecture note.
- `docs/specs/2026-11-05-location-check-in-design.md`: a line under §5 pointing here.
