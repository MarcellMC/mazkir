# Location Trips: Mazkir notices where you went, works out why, and fills in the day (Design)

**Status:** Draft, written 2026-11-10 to 2026-11-12 from conversation, after the L0 spike's first week of data.

**Replaces:** §5 (L1) of `docs/specs/2026-11-05-location-check-in-design.md`, and brings forward the part of §6 (L2) it needs: your places get coordinates. L2's points-of-interest lookup, L3 (reminders by kind of place) and L4 are unchanged and still later.

**Related:**
- `docs/specs/2026-09-10-ship5-inferred-capture-design.md`: proposals, ✓ ✕ ✎, approval ticks a habit.
- `docs/specs/2026-09-27-fast-lane-design.md`: receipts and taps, `run_tool`, the principle.
- `docs/specs/2026-08-29-ship2-navigable-day-design.md`: source availability.

---

## 1. What this is for

You share your live location with the bot all the time, and you log very little by hand. This design answers one question: **when you went somewhere, what were you doing?**

Mazkir works it out from your own history and from what you've told it. It asks only when it can't tell, and only once it knows where you stopped. Every trip ends up as a proposed block in `/day`, and a message when you are back makes it one tap to confirm and one tap or one sentence to fix.

Your words, from the conversation:
- On guessing: "Don't simply assume a dog walk, but infer from the existing data: habits, tasks, current schedule, user reports/conversations. Dog walks are usually twice a day ~12 hrs apart, so they are the easiest to infer, but it could be anything." It must also cover office visits, gym visits and other recurring outings, so fixed per-activity rules won't do.
- On choices: "If there are several good guesses (high confidence), Mazkir could propose a few options to choose from with inline keyboard, or type in something else."
- On when to ask: "'Where to' is a good question to ask after the arrival so there's more data for Mazkir to infer from… rather 3 mins after arriving to a stop."
- On unanswered trips: "If I didn't answer, but got home eventually, update suggested block with end time."
- On correcting: "There should always be options to quickly approve suggested block or edit it: nudge timestamps with buttons and/or correct Mazkir with NL prompt." And: "When I both nudge times and reply with text, it means I want to edit both timestamps and the activity itself."
- On merging: "If that could be inferred from location data, why would I bother typing the time in by hand? … never create duplicates — always merge existing data from different sources, where my direct instructions always take precedence over inferred values."
- A dog walk inferred without asking still gets a message when you're back.
- On stops: "Dog walk is just a type of walk. It's not much different from a bicycle ride around the city, or a walk with a friend. Ask about stops, and if I don't specify, leave unnamed and don't create a separate block for it." No activity gets rules of its own.
- Short trips count: Mazkir should "spot a short visit to a convenience store right next to my house… probably around 50 m away", without being triggered by GPS lag.
- Plans you mentioned are looked for in the last 24 hours of conversation.
- No shadow phase: "I want to start testing it live right away."
- Approving a block ticks its habit, for every habit, not only Dog Walk.

### 1.1 Goals

1. **Notice every trip, short ones included.** That means a 48 m trip to the shop, while GPS drift at home is never taken for a trip.
2. **Work out each trip's purpose** from your confirmed history, and from today's schedule, open todos and the last 24 hours of conversation. It should learn any recurring outing without new code.
3. **Ask well.** Ask once, after you've stopped somewhere it can't name, with its good guesses as buttons and room to type anything else.
4. **One rule for every trip, whatever the activity.** Each stop Mazkir can't name gets one question. A stop you name becomes its own block; a stop you don't name stays unnamed inside the trip's block and never gets one of its own. A dog walk follows the same rule as a bike ride or a walk with a friend.
5. **Fill the day without duplicates.** A trip completes a block you started yourself. What you said is never overwritten, and location fills what you left out.
6. **Make correcting cheap.**
   - ✓ approves.
   - The nudge pad shifts the times.
   - A reply corrects the block.
   - A nudge plus a reply edits both the times and the activity at once.
7. **Learn your places** from your answers.

### 1.2 Non-goals (here)

- **Asking what you're doing while you stay at home.** You want this, but it waits for the time-awareness work. It will share this design's message format and have its own budget of at most 4 questions a day.
- Naming places from OpenStreetMap or Google (L2 §6.2), and reminders by kind of place (L3).
- A map view.

### 1.3 Anti-goals

These would make it a failure even if it technically works:
- **A question about a trip Mazkir could have worked out,** above all a routine dog walk.
- **More than one question about the same stop, or a re-ask after no answer.**
- **Rules for one activity.** A dog walk is a walk; nothing in the tracker or the asking knows about dogs.
- **A false trip from GPS drift** while you sit at home.
- **A duplicate block, or an inferred value overwriting something you said.**
- **Anything in Google Calendar before you approve it.** Proposals stay local until ✓, as in Ship 5.
- **Coordinates in a model call, a span or a log line.** This is the L0 rule, carried over. The model sees place names, distances in metres, durations, speeds and times.

### 1.4 The principle

The fast lane's rule holds: **the model reads meaning, code decides what happens.**

- **Code** turns points into stays and trips, scores your history, gathers the context, decides whether to ask, and writes the blocks.
- **Exactly one model call per trip-decision** reads the context and says what the trip probably was. Anything it proposes that is not from your history must cite the line it came from, and code checks that the line exists (§5.3).

A wrong guess is therefore visible in the decision log as "the model said X because of Y", and the thresholds for asking can be tuned without touching the prompt.

---

## 2. What the spike showed (5 – 11 Nov)

Run with `python scripts/location_spike_report.py --from 2026-11-05 --to 2026-11-11`.

- **One share has run for a week.** It is the "until I turn it off" option, `live_period = 2147483647`. About 8,000 points, no failed posts, delay 1 s at p50 and p90.
- **Sampling is dense.** Since 6 Nov 10:24, a point every 32 s (p50) while moving and every 36 s (p50) while still, nights included. Before that it was sparse; why is not known.
- **Two holes:**
  - the evening of 5 Nov, when a ~20-minute dog walk got one point;
  - 8 Nov 18:35–20:28, 112 minutes with no points, ending 615 m away.

  Silence has to be treated as missing data (§4.4).
- **Accuracy:**
  - `horizontal_accuracy` is 15 m at p50, 33 m at p90 and 496 m at most;
  - points taken while still sit within 5 m of their centre at p50 and 9 m at p90;
  - bad points come in bursts of 250–400 m accuracy, and single points can be a few hundred metres off.
- **A 40 m departure rule is safe at home.** At home, the departure rule from §4.1 was tested at 40, 50, 60 and 75 m: at least 3 points with accuracy ≤ 30 m, outside the radius for at least 1 minute. Over six days GPS drift produced **no** false departures at any of these radii; every departure found was a real trip. Only 40 m found one more: 9 Nov 20:29–20:32, about 48 m from home for 3 minutes, just after the evening walk. You don't remember it; we assume it was the convenience store, so it is the test case for short trips, and home's radius is 40 m.
- **Short walks stay close to home:** the 7 Nov evening walk went no further than 144–163 m.
- **The naïve stay-point pass:**
  - turned slow dog-walk loops into visits;
  - split one stay in two at a 1-minute gap;
  - split one night in two at a single 385 m point;
  - cut a visit at midnight.

  §4 fixes each of these.
- **Dog walks are twice a day, about 11–12 h apart:** 7 Nov 10:07 / 21:00, 8 Nov 07:20 / ~18:35, 9 Nov 08:29 / 20:00. They range from 8 minutes within 160 m to almost 3 hours with three stops up to 1.7 km away.

### 2.1 The labelled days

From your description, Mazkir writes the labels itself into `data/eval/location/{date}.json`; you don't label anything by hand. Your description: the unlabelled trips are mostly dog walks, some of them long, plus commutes home, such as the walk from Sam's birthday at their place with a stop at the café in Elm Park. The labels, together with your later answers:

| Day | Trip (from the points) | Label | Evidence |
|---|---|---|---|
| 5 Nov | ~20:01–20:21, 1 point at 131 m | Dog walk | you said so |
| 6 Nov | 10:24–10:38, up to 340 m | Dog walk | logged 10:24–10:38 |
| 6 Nov | 11:25 → stay 11:28–17:34 at 205 m → home 17:37 | Walk to pottery class · Pottery class · Walk home | logged 11:20–17:50 |
| 6 Nov | 17:37–19:13, 10 m from home | Dinner at Jo's (at or next to home) | logged, ends 19:13 |
| 6 Nov | 19:20–19:28, up to 268 m | Dog walk | logged 19:17 |
| 6 Nov | 19:36 → 20:10 to 2.4 km, stay until 7 Nov 07:54 | Bus to Sam's · Sam's birthday | logged 19:40–20:00 and from 20:00 |
| 7 Nov | 07:54 → café 08:04–09:14 at 1.75 km → home 09:50 | Walk to Elm Park · Café at Elm Park · Walk home | logged café until 09:13; you described it |
| 7 Nov | 10:07–10:46, up to 727 m, stop 10:20–10:28 | Dog walk | logged 10:02 |
| 7 Nov | 21:00–21:20, up to 163 m | Dog walk | pattern |
| 8 Nov | 07:20–10:10, up to 1.7 km, three stops | Dog walk (long) | you said so |
| 8 Nov | ~18:35–20:41, silent 112 min, 655 m at the end | Dog walk (long) | you confirmed it |
| 9 Nov | 08:29–08:49, up to 201 m | Dog walk | logged 08:37 |
| 9 Nov | 20:00–20:13, up to 272 m | Dog walk | pattern |
| 9 Nov | 20:29–20:32, ~48 m | Convenience store | assumed; you don't remember it |
| 9 Nov | 21:08 → board-game café at up to 920 m → home 00:31 | Walk to board-game night · Board-game night · Walk home | you said so |
| 10 Nov | 09:17–09:41, up to 245 m | Dog walk | pattern |
| 10 Nov | from 10:16, to ~700 m | Walk to café · Coffee, then the library | you said so |

The 10 Nov late morning is the case §5 exists for. The morning walk had just happened, nothing was on the schedule, and the place was new, so Mazkir has no good guess and asks once you've sat down.

---

## 3. Where it runs

There is no separate job. The work is driven by the stream of points the bot already posts, plus one worker thread, plus a timer like the coding-session poller in `main.py`.

```
 Phone (Telegram live location)
        │  a point every ~30 s
        ▼
┌─ telegram-bot ─────────────────────────────────────────────────────────────┐
│ conversations/location.ts                                                  │
│   POST /locations/points ──────────────────────────┐                       │
│   ◄── {ok, notify:[…]}  ── messages to send ◄────┐ │                       │
│   sends them as rich messages with buttons       │ │                       │
│   callbacks/trip.ts    ✓ ✕ ✎ and answer buttons                            │
│   state/nudge-draft.ts the unsaved nudge, sent along with your next text   │
└──────────────────────────────────────────────────┼─┼───────────────────────┘
                                                   │ │
┌─ vault-server ───────────────────────────────────┼─┼───────────────────────┐
│  routes/locations.py  (inside the request, a few milliseconds)  │          │
│    1. append the raw point            data/locations/raw/{date}.jsonl     │
│    2. tracker.feed(point)             state: data/locations/state.json    │
│         stay / moving state machine, pure code                            │
│         emits: LEFT · STOPPED (3 min) · LEFT_STOP · BACK_HOME · GAP        │
│    3. return what the outbox holds ─────────────┘                         │
│              │ events                                                      │
│              ▼                                                             │
│  trip worker  (one background thread, one event at a time)                │
│    candidates.py  code: scores your confirmed history; gathers context    │
│                   as quoted text (24 h of conversation, open todos,       │
│                   today's schedule) without interpreting it               │
│    guess.py       the one Haiku call: what was this trip?                 │
│    decide.py      code: name it silently, or ask? which blocks?           │
│    writer.py      blocks via run_tool(create_event / update_event):       │
│                   completes YOUR block if there is one, never duplicates, │
│                   never overwrites what you said                          │
│    outbox.py      queued messages        data/locations/outbox.json       │
│                                                                            │
│  trip clock  (async loop from lifespan, every 60 s)                        │
│    no points for 30 min while sharing → "Location sharing stopped",       │
│    sent directly through telegram_notifier, since no point will carry it  │
│                                                                            │
│  answers coming back                                                       │
│    button tap    → POST /locations/trips/{id}/answer → writer, places      │
│    typed answer  → agent → new tool set_trip_purpose(trip, purpose, place) │
│    ✓ on a block  → existing approval → Google Calendar + habit tick        │
└────────────────────────────────────────────────────────────────────────────┘
```

- **Tracking is fast, deterministic code inside the request.** It can be replayed over the raw files, which is how its thresholds are tuned.
- **Guessing involves a model call (1–2 s), so it runs in the worker,** never in the request.
- **Messages ride back on the next point's response,** at most ~30 s after the worker decides. That keeps one sender, the bot, which already draws rich messages and buttons. The exception is the "sharing stopped" message, which no point will carry.
- **Blocks are written through `run_tool`,** like the fast lane's. So they appear in the audit log, Google sync happens on approval, and habits tick as they already do.

New server code lives in `src/services/location/` (`tracker`, `candidates`, `guess`, `decide`, `writer`, `outbox`), next to L0's `location_store.py`. New bot code is `formatters/trip-rich.ts`, `callbacks/trip.ts` and `state/nudge-draft.ts`.

| Existing piece | Where | Used for |
|---|---|---|
| Proposals | `create_event(proposed: true)`, `approval.resolve_state`, `_settle_proposal` | Every trip block is a proposal. Approval creates the Google entry and the `## Schedule` line |
| Habit tick on approval | `tick_if_habit` (Ship 5) | ✓ on any block that matches a habit ticks it |
| Pinned fields | `user_set` (Ship 4) | What you said wins over location (§6.5) |
| Nudge pad | `block-edit-rich.ts`, `day-actions.ts` (`adj:` / `adjsave:`) | ✎ on a trip message opens it |
| Receipts with per-line taps | `receipt-rich.ts`, `callbacks/receipt.ts` | The shape of the arrival message |
| Open question | `state/open-question.ts` | A typed answer is understood as one |
| Replies to rich messages | `rich-text.ts` `repliedToText` | A reply to a trip message reaches the agent with its text |
| Places | `fast_lane/places.py`, `data/places.json` | Gain coordinates (§7) |

---

## 4. From points to trips

`tracker.py` is a state machine fed one point at a time. Its state is in `data/locations/state.json`; closed stays and trips go to `data/locations/derived/{date}.json`. `scripts/location_rebuild.py` replays raw files through it. The thresholds are starting values, to be tuned on the labelled days (§9).

### 4.1 Staying, and leaving

- **Points used:**
  - a point with `accuracy_m` over 30 m never moves the state on its own; it is kept but does not count;
  - a point whose implied speed is above 150 km/h both into it and out of it is an outlier and is dropped (the single 385 m point on 9 Nov).
- **Staying:** points within the stay radius of their running centre for at least **3 minutes**. The radius is **40 m at home** (§2) and 75 m elsewhere until a place has its own measured spread. The stay's spread is the p90 distance of its points from the centre.
- **Leaving:** at least **3 points in a row**, each with accuracy ≤ 30 m, farther from the stay's centre than the threshold, for at least 1 minute. At home the threshold is the 40 m radius itself, because home's spread is measured over weeks and the spike tested exactly that rule. Elsewhere it is `max(radius, 3 × spread + accuracy)`, since a new stay's spread is still a guess. On your data this finds every real trip, the 48 m shop trip included, and no drift.
- **Home wins.** 3 good points back inside home's radius end whatever stop you were at, and the trip with it. Without this, a stop 48 m from home, with its 75 m radius, would swallow the walk back.
- **Departure time** is the last point inside the stay, so blocks start when you actually left.
- **Only leaving ends a stay.** A gap in points (up to §4.4's limits) or a point the rules above don't count never ends one. This fixes the pottery-class split at a 1-minute gap. Two stays close together are not merged when a real departure separated them, since the shop is 48 m from home.
- **Midnight splits nothing.** Stays and trips span days. Blocks are split at 00:00 only when written, as `create_event` already does.

### 4.2 Trips, stops and home

Under the hood a day is a chain: stay, moving, stay, moving, and so on. A **trip** runs from leaving a stay at home, or at a place where you have arrived, to the next such arrival. The stays in between are **stops**.

The tracker cannot tell whether a stop is a place you went to (the café) or a pause (a bench, the dog sniffing around a park), so it doesn't try. **Every stop of at least 3 minutes is treated the same way, on any trip:**

- **It is named** if it is a known place or there is one good guess (§5.4), and **asked about** otherwise, once.
- **A named stop becomes its own block.**
- **An unnamed stop** (no answer, or "nothing, just a pause") **gets no block.** Its time stays inside the trip's block, and the stop is kept only as detail on it ("3 stops"). 8 Nov morning, with no answers, is one "Dog walk 07:20–10:10" block.
- **A spot you called a pause** is remembered as a pause spot (§7), so the same bench isn't asked about again. *My call: without it, a stop on your daily route would be asked about every day.*

What the trip's own block looks like depends on what the moving was for (§4.3).
- **The mode of a leg** comes from its median speed: up to 7 km/h is walking; up to 25 km/h is "ride", which could be a bike or a bus in traffic; above that is a vehicle. An answer or a guess names it more precisely.
- **Home** is the place where most nights between 01:00 and 05:00 were spent over the last 14 days (§7). Arriving home always ends a trip.

### 4.3 What a trip becomes

| What the moving was for | Blocks |
|---|---|
| **The moving is the activity:** a dog walk, a bike ride around the city, a walk with a friend, a run | One block for the whole trip, from leaving to getting back. Each named stop is its own block inside it, overlapping it ("Coffee at Elm Park 08:10–08:25" within "Walk with Robin 07:50–09:00"); coverage counts the overlap once. |
| **The moving gets you somewhere:** the café, the cinema, Sam's, the shop | A travel block per leg ("Walk to Elm Park", "Bus to Sam's"), a block per named stop, and an open block at the destination ("Sam's birthday"), closed when you leave. Unnamed stops stay inside the leg around them, so a leg is not split by a pause. A leg under 2 minutes (the 48 m to the shop) folds into the block it leads to. *My call.* |
| Unknown, never answered | "Trip ‹distance›", one block like the first row |

The guess (§5.3) says which row applies: a purpose with a destination place is the second row, one without is the first. Code reads that field; there is no list of activities.

### 4.4 Silence

A gap of over 10 minutes between points inside a share is **missing data**.

- If the points on both sides of the gap are at the same stay, the stay continues, with lower confidence.
- If they are apart, a trip happened inside the gap. It starts at the last point before it, and the block is marked `start_precision: "before"`, so the message says "left before 18:35". 8 Nov evening is this case.
- No points for 30 minutes means the share has probably ended. The trip clock closes the open stay at its last point. (It also sent "Location sharing stopped — share again to keep your day filling in", once, until 2026-11-15, when the owner asked for it to go.)

---

## 5. Working out the purpose

### 5.1 When

The worker makes a decision on these tracker events:

- **STOPPED:** 3 minutes into a stop. Can this stop be named?
- **BACK_HOME:** what was the whole trip?
- **LEFT_STOP** after a stop that was not named: the guess is refreshed with the stop's length.

Every stop gets its STOPPED decision, whatever the trip's purpose. The trip's purpose, once guessed, is part of the context for its stops ("on a walk, stopped 4 min, 400 m from home"), and is revisited if the trip stops looking like it: a vehicle leg, a distance well beyond that purpose's history, or a stop beyond its usual length.

### 5.2 Context (code: `candidates.py`)

Two kinds of input, gathered without interpretation:

1. **Your history, scored.** For each purpose with at least 3 confirmed trips (approved trip blocks, your own logged blocks, and the labels in §2.1, so dog walks work from day one), code compares this trip on:
   - the place you left;
   - the place you arrived at or are stopped at;
   - the hour and day of the week;
   - the time since that purpose last happened, compared with its usual spacing;
   - the mode;
   - the distance and duration so far.

   The result is a short ranked list, each entry with its evidence: "Dog walk: 14 confirmed, usually 07–10 and 19–21, last 11 h ago, on foot, loop from home". Any recurring outing (gym, office, band practice) learns itself this way, with no code per activity.
2. **Text, quoted as it is.** Chosen by time only:
   - the last **24 hours** of conversation (`memory/00-system/conversations/`);
   - open todos and tasks;
   - today's blocks and calendar events with their places;
   - habits due today.

   Each line gets an id, so it can be cited.

Plus the trip so far, as numbers and names: distances, durations, mode, the known place if any. No coordinates.

### 5.3 The guess (the one model call: `guess.py`)

Haiku, with structured output. It returns up to 3 purposes, each with:
- `likelihood`: `strong`, `plausible` or `unlikely`;
- either a `history` candidate id, or a new purpose with `cites`, the ids of the context lines it comes from ("going to Sam's tonight", said yesterday at 21:40);
- optionally a destination place name.

Code drops any new purpose that cites nothing or cites an id that does not exist. So the model can find "Robin's for dinner" in a message without being able to make one up. About $0.007 a call. That is a few calls per trip, at 5–8 trips a day, so roughly $1–3 a month.

A failed or timed-out call means no good guess, and Mazkir asks. Asking is the safe direction.

### 5.4 Ask or not (code: `decide.py`)

| Guess | What happens |
|---|---|
| One `strong`, and no other `strong` or `plausible` one | Named silently; it shows in the arrival message |
| Two or three `strong` / `plausible` ones | Ask, with them as buttons |
| None | Ask, with your usual destinations from here as buttons, if there are any |

- **Where Mazkir asks:** at STOPPED, for a stop it can't name, or at BACK_HOME, for a trip it can't name. The trip question goes in the arrival message.
- **A stop already behind you** (you left before 3 minutes of messages could go out, or the question was never delivered) is not asked about later; it stays unnamed.
- **At most once per stop, and never re-sent.**
- **A cap of 6 questions a day** is only a safety net, for a bug or a strange day.
- **Questions are allowed at any hour:** if you're out moving, you're awake.

---

## 6. Talking to you

### 6.1 Delivery

The ingest response gains `notify: [...]`, and the bot sends what it lists.
- Each item has an id, and the server marks it sent only when the bot acknowledges it (`POST /locations/outbox/{id}/ack`). So a retried POST never sends a message twice.
- An item unacknowledged after 3 responses is dropped and logged; the blocks are in `/day` regardless.

### 6.2 The question at a stop

> 📍 You've been here since 10:24 — 700 m from home, a new place. What's this?
> [Café] [Library] [Just a pause] [✎ Something else]

- **A button** names the stop. A place-like answer also names the place (§7).
- **Just a pause,** or no answer at all, leaves the stop unnamed and without a block (§4.2). Only the button makes it a pause spot; silence teaches nothing.
- **✎, or just typing,** is read as the answer. The bot holds it as an open question (`open-question.ts`), and the text goes through the agent with the trip and stop ids in the reply context. The agent records it with a new tool, `set_trip_purpose(trip_id, stop_id?, purpose, place?)`, so the answer reaches the trip, not only a block name: §7 learns the place from it, and §5.2's history counts it.
- **A late answer** still applies. It renames the blocks and re-sends nothing.

### 6.3 Back home

There is one message per trip, shaped like a fast-lane receipt, with one line per block:

> 🐕 Dog walk 07:20–10:10 · 2 h 50 min, 3.4 km, 3 stops  [✓] [✎]

or

> 🚶 Walk to Elm Park 07:54–08:04  [✓] [✎]
> ☕ Café at Elm Park 08:04–09:14  [✓] [✎]
> 🚶 Walk home 09:14–09:50  [✓] [✎]
> [✓ All] [✕ Not right]

- **✓** approves the block through the existing path: the Google entry, the `## Schedule` line, and a habit tick when the block matches a habit.
- **✎** opens the block-edit view with the nudge pad.
- **✕** dismisses the trip's blocks.
- **A trip nobody could name** asks here: "🚶 Trip 18:02–18:40, 1.1 km — what was it?", with buttons.
- **Blocks are in `/day` from the moment you leave** (an ongoing trip renders as ongoing), so the message is a shortcut, not the only way in.

### 6.4 Corrections in words, and words with nudges

- **A reply to a trip message** ("no, I took the bus", "that was a run") reaches the agent with the message's text, through `repliedToText`, plus the trip's block ids. So it edits the right blocks without asking which.
- **Nudge, then type.** A nudge draft lives only in callback data today, so text typed after nudging knows nothing of it. The bot now also keeps the **latest unsaved nudge draft** per chat: the block, its date and the two offsets. It is one-shot, expires after 10 minutes, and is held in memory like `open-question.ts`.
  - **When text arrives while a draft is held,** the draft travels with it, and the block's times and activity change in **one** edit. The reply says both ("Run, 07:25–08:10").
  - **Saving from the pad, or any other action on that block,** clears the draft.

### 6.5 Merging with what you logged

**One block per real activity, never a duplicate, and what you said wins.**

- **Before writing a trip block,** `writer.py` looks for a block of yours that overlaps the trip or starts within 15 minutes of it. Examples: "Dog walk" from a message with no times, "Dog walk 10:24" with no end, or a fast-lane block placed at the message time.
- **If one exists, the trip completes it** instead of adding a block:
  - fields you stated (name, a start you gave, an end you gave) are pinned in `user_set` and never touched;
  - location fills the rest;
  - a time the fast lane only inferred from when you sent the message (`start_precision` / `end_precision` not exact) counts as not stated, so location replaces it.
- **If location strongly disagrees with a time you stated** (more than 15 minutes), nothing is overwritten; the arrival message mentions it.
- **If your block's name and the trip's guess disagree,** your name wins, and the guess is dropped.
- **The reverse direction:** when you log something during or after a trip, the fast lane's matching (§7.1 there) finds the trip's open block and updates it, rather than creating a second block. The two writers meet in the same events file, and `EventsService` has no lock today (CLAUDE.md lists this as a known fast-lane risk). The trip worker is a new concurrent writer, so this design adds one process-wide lock around `EventsService`'s read-modify-write and uses it from every caller.

The location-filled fields of your block are still a proposal until ✓, shown as "Dog walk 10:24–10:38 (end from location)".

---

## 7. Places

- **Stored** in `data/places.json`, which exists today with `{id, name, aliases, kind}`. Entries gain optional `lat`, `lng` and `radius_m`:

  ```json
  {"id": "sams", "name": "Sam's", "aliases": ["Sam"], "lat": …, "lng": …, "radius_m": 60}
  ```

  The file is gitignored and stays on this machine. Coordinates never go into the vault, which is pushed to GitHub.
- **`places.py`** keeps resolving by name, for the fast lane, and gains `nearest(lat, lng)`.
- **What usually happens at a place** (gym → Workout) is never stored. §5.2 works it out from history each time, so it keeps up when habits change.
- **Home** is found as in §4.2 and written as id `home`. The bot says once that it found home.
- **Pause spots:** "Just a pause" stores the stop as a place with `kind: "pause"` and no name the vault ever sees. A stop inside one is unnamed with no question.
- **Learning:** an answer naming a place ("Sam's", "the café on Main Street") gives the stop's centre to that place, creating the place if it is new.
  - If a place by that name already has coordinates farther away than its radius, Mazkir asks "Is this a different Sam's?"
  - A place's radius grows to cover the spread actually seen there, capped at 150 m.
- **A stop at an unknown place** is "Somewhere 700 m from home" until you answer.

---

## 8. Rollout

`LOCATION_AWARENESS=off|on`, read by the server, alongside `LOCATION_INGEST=log`. Default `off`; you will switch it on straight away, with no shadow phase.

`data/logs/location-trips.jsonl` always records one line per decision:
- the event;
- the history candidates;
- the model's answer and its citations;
- ask or not, and why;
- the blocks written or completed.

It is how bad guesses get debugged. `scripts/location_trips_report.py [date]` prints a day as trips with what happened at each.

---

## 9. Evaluation

`scripts/location_replay.py` runs the tracker and the history scoring over `data/eval/location/`. That part is free and offline; `--with-model --confirm-cost` adds the model calls.

| Measure | Target, first pass |
|---|---|
| Trips found / missed / invented | None missed, including the 163 m walk on 7 Nov and the 48 m shop trip on 9 Nov; none invented from drift or jitter bursts |
| Leaving detected (true departure → event) | p50 ≤ 2 min |
| Start / end error of blocks | p50 ≤ 3 min, p90 ≤ 10 min |
| Dog walks named without a question | All, on the labelled days, from history plus labels |
| Questions per day | ≤ 2 on the labelled days |

The labels grow by themselves: an approved or corrected trip block is a label. `scripts/location_labels_from_ledger.py` writes them back to `data/eval/location/`.

---

## 10. Failure handling

- **A crash in tracking or deciding** is caught and logged at ERROR, and ingest still returns 200. The raw point is already stored, so a rebuild recovers everything.
- **A restart** reloads `state.json` and `outbox.json`. A trip in progress continues, and a question already sent is not sent again.
- **The model fails:** no good guess, so Mazkir asks.
- **A message fails to send:** §6.1.
- **Sparse sampling returns:** trips inside silences get uncertain starts (§4.4). If that becomes common, it argues for a dedicated logger app (L0 spec §1.3), which feeds the same endpoint.

---

## 11. Left to the builder

- Module boundaries inside `services/location/`, within the existing patterns.
- How trip blocks stay idempotent per trip. One option is a hidden trip id through `run_tool`, as the fast lane does with `_fast`; another is a `location_trip` key in `source_ids`. Either way, these must hold:
  - each block is written once, and its end is updated on arrival;
  - `reconcile` never drops a trip block because some source was unavailable;
  - approval goes through `_settle_proposal`.
- The exact wording of messages, within the shapes in §6.
- The history scoring's exact formula, and the final threshold values, set by the replay.

---

## 12. Docs updated in the PR

- `CLAUDE.md`:
  - `LOCATION_AWARENESS`;
  - `data/locations/derived/`, `state.json` and `outbox.json`;
  - `notify` on the ingest response;
  - the new agent tool and the tool count;
  - an architecture note.
- `docs/specs/2026-11-05-location-check-in-design.md`: a line under §5 pointing here.


## Addendum 2026-11-14: stops after the first live walk

The first live dog walk (15:56–16:46) named its stops at the local dog park and at Café Lumen
"Dog walking" and "Dog walk", gave each its own block and asked nothing. The guess came from the
user's own "Dog walking" message and the habit being due, which bypassed the history-only
destination filter, and the prompt's "a pause gets no guess" was not followed. Agreed fixes:

1. **A stop is named after the place, never after the trip.** Code drops a stop guess with no
   destination or equal to the trip's purpose. Only a place the user named names a stop silently;
   every other stop is asked about once, with the remaining guesses as buttons. A stop left
   unanswered stays unnamed and gets no block (no re-guess on LEFT_STOP).
2. **A usual stop is recognised:** stopped within 50 m on 2 or more earlier trips in 30 days. The
   question says "your usual stop (N earlier trips)" and the model is told, so it can offer a
   guess such as "Dog park". Without map data that is still a guess, which is why it is asked.
3. **`Later`** on a stop question moves it into the arrival message (`trip:<id>:<stop>:l`).
4. **One name per activity:** a guess or an answer that means the same words as a confirmed
   purpose (first) or a habit name or alias takes that name ("Dog walking" → "Dog walk").
5. **Saying what you are doing mid-trip names the trip:** `list_events` carries a trip block's
   `trip`, and the time-management skill calls `set_trip_purpose` for it without asking.

Next: map data (OpenStreetMap places stored locally) to name places such as the dog park and
Lumen on their first visit.
