# Location trips: trips you can fix

**Status:** built · **Date:** 2026-11-24 · **Builds on:**
`docs/specs/2026-11-10-location-trips-design.md`, `docs/specs/2026-11-14-location-map-design.md` ·
**Evidence:** `docs/research/cross-midnight/report.md` (the 16–23 Nov review)

## 1. Why

In the first ten days of live trips (16–23 Nov) Mazkir got trips wrong in ways the user could
not fix by talking to it. Twelve separate problems were found. The cross-midnight practices in the
research report fix three of them and help with two. The rest come down to three things:

1. **It names trips it should ask about.** Back home, one strong guess from history names the
   trip with no question. Four trips were named "Dog walk" that were not: a trip with a café the
   user had just named, a work trip, an outing with a friend, and a 7-hour night.
2. **It stops asking.** At most 6 questions a logical day. A work trip that went on to a walk in
   another city and a night out used up the six, and about 30 stops were never asked about.
3. **The agent can't see a trip, so it can't fix one.** It has `set_trip_purpose` and
   `list_events`, nothing else. Asked about a trip, it asked the user for times the location data
   had, ended a block at the time of the user's message, stretched the wrong stop, and said it had
   no access to maps or location history. It could not add a stop the tracker missed, split a stop
   that merged three places, or bring back a block that was dismissed by mistake.

The review also found problems in how a trip is shaped:

- **Unnamed stops vanish into legs.** On a trip with a destination, the legs run from named stop to
  named stop, so "Ride home" covered 11:44–18:45 and twelve stops.
- **A trip can't be split or joined.** Everything from leaving home to coming back is one trip:
  work and then a walk in another city, or a night out and the next morning's walk.
- **Trips start hours early.** When sharing resumes away from home, the trip starts at the last
  point at home (17:41 for a trip that left at 19:01; 09:42 for one that left at 22:48).
- **✕ Not right undid a ✓.** It dismisses every block of the trip, including one approved seconds
  before.
- **A street became a place of the user's.** An answer through the agent saved a street name as
  the lunch place.
- **A photo went to the daily note, not to the block it was taken in.**
- **The router's `next_skill: …` token reached the user** in a reply.

## 2. Goals, non-goals, anti-goals

**Goals**
- **Every trip asks.** Mazkir never names a trip from its own guess; the guess is a button (§4).
- **Every stop gets asked**, live or once home, with no limit on questions (§5).
- **Blocks match what happened:** legs only while moving, and the trip starts when it left (§6).
- **The agent can see a trip and fix it by talking:** find a place by name, find when the user was
  there, add, merge or split stops, change times, split a trip in two or join two, restore a
  block (§7).
- **Every location and photo the user sends is looked up on the map**, and the model gets words,
  not coordinates (§8).
- **Small fixes** to the problems in §1 that need no design (§9).

**Non-goals**
- **Splitting trips automatically.** The user (2026-11-24): there is no general rule yet. "One
  purpose, one trip" fails for a trip with several purposes; "ends when I'm home" fails for a night
  at a friend's, camping, or a week in hotels that are home for a while. So for now a trip still
  runs from leaving home to coming back, and the agent splits or joins trips when asked (§7.4).
  A rule may come from more use.
- **A temporary home** (a hotel, a friend's place overnight). Same reason.
- The one trip card that updates itself and the map image (ideas 1 and 2 from the 23 Nov
  discussion). They come after this, in their own spec. This spec must not make them harder (§10).
- The cross-midnight practices from the research report. Their own spec comes next.
- Tuning the tracker's stay detection (stops 150 m apart merging). The agent can split a stop
  instead (§7.4); tuning waits for more labelled data.
- Online map search. Local index only.

**Anti-goals**
- **No coordinate leaves the machine**, now that the agent asks about places and visits: no
  coordinate in a tool result, a model prompt, a span, a log line or the vault. The agent sees
  names, kinds, times and distances. Place references are short handles (§7).
- **No proposal reaches Google before ✓.** An edit through the agent changes proposals, and they
  stay proposals.
- **Nothing new is sent mid-trip** beyond one question per stop.
- **No tool that writes a block on a guess.** The agent's trip edits act on what the user said; a
  time it does not know comes from the location data or is asked, never invented.

## 3. What the user sees

- A dog walk: one question at a stop with no place of the user's, as now. Back home, the arrival
  message asks what the trip was, with "Dog walk" as the first button when history suggests it.
  One tap names it; ✓ All then confirms the blocks.
- A long day out: a question at every stop while out. Stops left unanswered are asked again in the
  arrival message.
- Correcting by talking works:
  - "There was a coffee stop at <café> between the shop and the pet store." The agent finds the
    café on the map, finds when the user was near it, adds the stop and shows the new arrival
    message.
  - "The pool and the café were separate." It splits the stop where the points moved.
  - "Work was one thing, the walk after it another." It splits the trip in two at the end of the
    work stop, and each half is asked about on its own.
  - "Bring back the café, I tapped ✕ by mistake." It restores the block as a proposal.
- ✕ Not right dismisses only what is still pending.

## 4. Naming a trip back home

Today (`decide.py`): back home, if the model returns exactly one strong guess and no other live
one, the trip is named with no question. With history the model leans to "Dog walk", and four
trips were mis-named that way.

**New rule (the user's, 2026-11-24): every trip asks.** `decide` never returns `name` for a trip.
The guesses, strong ones first, become the buttons of the trip question in the arrival message.

The one exception is the user's own words: a block of the user's that the trip merged with still
names it (`_name_from_your_block`, unchanged), and so does an answer the user gave mid-trip
("dog walking" while out). Neither is Mazkir's guess. The arrival message shows the name with
✓ ✎ as usual.

Stops are unchanged: a place of the user's names a stop silently, since the user named that
place.

## 5. Asking about stops

Today: a stop with no place of the user's is asked about once while the user is there, at most 6
times a logical day. A stop over the cap is quiet and never asked again.

**New rule.**
- **No limit** (the user's, 2026-11-24). `QUESTION_CAP` and `_questions_today` go; every stop
  without a place of the user's is asked about while the user is there.
- A stop left unanswered when the user leaves it takes status `later`, which the arrival message
  already shows as a `?` line with its options. Today it stays unnamed and gets no second chance.
  "Never a second guess" still holds: it is the same question, asked once more at home, not a new
  guess.
- Unchanged: never ask about a stop already left (the live question is withdrawn, the `later`
  line replaces it); a place of the user's names a stop silently; a pause spot is quiet.

## 6. Blocks that match what happened

**Legs only while moving** (`writer.py` `_travel`). A leg ends at any stop of 10 min or more,
named or not, and the next leg starts when that stop ends. The stop's time is left with no block
of its own until it is named, so `/day` shows it as a gap and the arrival message asks about it.
In a trip with no destination (one activity block, a dog walk) unnamed stops stay inside the block,
as now: a pause on a walk is part of the walk.

**The trip starts when it left.** In `tracker._leave`, when the first point outside the stay comes
more than `silence_s` after the last point inside, the trip and its first leg start at **the first
point outside**, with `start_precision: "before"` (it left at some time before then). Today they
start at the last point inside. `describe_trip` says "Left home before 19:01" either way, and is
now right. A stop's end after a silence stays at its last point inside, as now.

**A rebuild fixes past trips.** `location_rebuild.py` re-derives the trips of 16–23 Nov into
`derived/`. Live records are not rewritten automatically; the agent's tools (§7) and a one-off
script per trip do that, with the user's OK.

## 7. The agent can see and fix a trip

New tools, in the time-management skill. `get_trip` and `find_place` are read-only (`safe`) and
also go to the `mazkir` skill, so it stops saying it has no location data. The rest are `write`
tools. Every result follows the usual `{ok, data|error, _items}` shape.

**No tool takes or returns a coordinate, or an OSM id.** An OSM id is public and an address's id
points at one house, so it is as revealing as a coordinate (the map spec already keeps them from
the model). A place is a short handle: `place:<id>` for a place of the user's (its `places.json`
id, a slug of the user's own name for it), `m<n>` for a map feature. The server keeps the `m<n>` →
OSM id table per chat, for 24 h, and a handle it no longer knows is `PATH_NOT_FOUND` ("search
again"). Distances are rounded to 10 m.

**Showing the result.** Every `edit_trip` op returns the redrawn arrival message as a receipt,
and the agent's reply carries it the way a fast-lane reply carries its receipt today: the bot
draws it as a new message under the reply. The old arrival message stays where it is; its buttons
address stops by id, so a tap on it still lands on the right stop, or answers "already answered".
An unsent arrival item is updated in place, as now.

### 7.1 `get_trip(trip_id? | date?)`

One trip, or the trips of a logical day. For each trip:
- left and back times with precision; mode; distance; purpose and whether it is confirmed;
- stops: id, start and end, duration, distance from home, status (named, asked, later, pause,
  unnamed), name and place, the map places seen there (label, kind, distance) and the area;
- legs: start and end, mode, distance;
- blocks: part, `event_id`, date, name, times, state (pending, approved, dismissed), including
  dismissed ones, so the agent can restore one;
- the trips it was split from or joined with (§7.4).

`list_events` already shows a trip block's `trip: {id, part}`; its description points to
`get_trip` for anything more.

### 7.2 `find_place(query, near?)`

Search the local map index and `places.json` by name.
- `query` matches `name`, `name_en`, `street` and the user's places and aliases, in Hebrew or
  English, after the normalising `names.name_key` already does (case, punctuation, final letters).
  Prefix and substring matches count; ranking is exact, then prefix, then substring, then distance.
- `near` is `trip:<id>`, `stop:<trip>:<stop>` or `home`, default the most recent trip. Results are
  within 3 km of it, nearest first, at most 8.
- Each result: `ref`, label, kind (`kind_words`), group (place or address), area, distance from
  `near`.
- Nothing found says so. The agent then asks the user to name the place at the stop instead
  (`name_stop` with a new place), which learns it from the stop's position. Small places are often
  missing from the map; this is the expected way to add them.

### 7.3 `find_visit(ref, trip_id? | date?)`

When was the user near this place? Code matches the raw points of that trip or logical day against
the place's position, server-side.
- A visit is a run of points within `max(40 m, accuracy)` of the place lasting 3 min or more,
  allowing silences of up to 10 min inside it.
- Each visit: start, end, closest distance, the stop it falls in if any (`s3`), and whether the
  points there were good (accuracy ≤ 30 m) or poor.
- No visit says so, with the closest the user came and when. It never writes.

### 7.4 Trip edits

One tool, `edit_trip(trip_id, op, …)`. Each op rewrites the trip record under its lock, re-plans
the blocks (`plan_blocks` + `apply_blocks`), refreshes the arrival message if it is unsent, and
returns the trip as `get_trip` shows it. The ops:

| op | arguments | what it does |
|---|---|---|
| `name_trip` | `name`, `destination?` | the trip's purpose (`set_trip_purpose` with no stop) |
| `name_stop` | `stop_id`, `name`, `ref?` or `place?` | `set_trip_purpose` for a stop, plus a map `ref`; a new `place` text is learned at the stop's position |
| `add_stop` | `start`, `end`, `ref?`, `name?` | a stop the tracker missed, from a `find_visit` result or the user's times; inside the trip's time only |
| `split_stop` | `stop_id`, `at` | one stop becomes two at a time; each half keeps the points on its side |
| `merge_stops` | `stop_ids` | adjacent stops become one |
| `set_stop_times` | `stop_id`, `start?`, `end?` | a time the user stated; pinned so a rebuild keeps it |
| `remove_stop` | `stop_id` | a stop that was not one (a traffic light) |
| `split_trip` | `at` (a stop id, its start or end, or a time) | the trip becomes two trips |
| `join_trips` | `other_trip_id` | two adjacent trips become one |
| `restore_block` | `part` | a dismissed block comes back as a pending proposal |

**Splitting and joining trips** is the only way a trip changes shape for now (§2, non-goals):
- `split_trip` cuts the trip at a moment. The first trip keeps its id and ends there; the second
  gets a new id and starts there. A stop at the cut goes to the side the user said ("after work"
  means the work stop stays in the first). Each trip then has its own purpose, question and blocks;
  the purpose and stop answers already given stay with the stops they belong to, and the trip's
  purpose stays with the first trip unless the user says otherwise. Both records note the split
  (`split_from`, `split_into`), and `history.py` learns each one as a trip of its own.
- `join_trips` makes one trip of two that touch or follow each other (a night at a friend's and
  the walk home the next morning, if the user calls that one thing). The second record is kept,
  marked `joined_into`, and its blocks are re-planned into the first.
- A trip still open (the user is out) can be split: the second trip is the open one, and the
  tracker carries on with it. `join_trips` refuses while either is open.

Rules for every op:
- **An approved block changes too.** The user asked for the edit, so a block they already ✓'d is
  updated in place and pushed to Google, as `update_event` does today; it stays approved. A new
  block an edit creates (an added stop, the second half of a split) is a proposal.
- **Legs are keyed by what they join**, `leg:<from>-<to>` (stop ids, `home` or `start`), not by
  position, so adding a stop never turns an approved leg into a different one. The old
  `leg:{n}` keys are read once and re-keyed.
- A stop the agent adds or splits gets a new id (`s7`, `s3b`), never reusing one, so a button on
  an old message cannot point at the wrong stop.
- Edits are stored as the user's (`source: "agent_edit"` on the stop), and the trip worker never
  undoes one. A live trip still receives points: a later `STOPPED` adds its own stop as usual.
- `set_trip_purpose` stays, as a thin alias of `name_trip` / `name_stop`.
- Every edit is logged to `location-trips.jsonl` as decision `EDIT`, with the op and ids, no
  positions.

### 7.5 Places of the user's

- **No address or street as a place.** Before `learn_place`, a name is checked against the index
  near the stop. If it matches a street or address and no place, it is kept as the stop's
  `place_text`, never learned, and the tool result says so ("saved as the street, not as a place of
  yours"). Same rule as the map buttons today.
- **Fixing a place.** `edit_place(ref, op)`: `forget` (removes a place of the user's), `move_to`
  (`stop_id`: re-learn its position from a stop), `rename`, `add_alias`. A `clash` from
  `learn_place` ("is this a different X?") now tells the agent it can `move_to`.

### 7.6 What the skill text says

`memory/00-system/skills/time-management.md` (a vault edit, done with this ship):
- read the trip with `get_trip` before answering anything about it; never ask the user for a time
  the trip has;
- a place named in passing: `find_place`, then `find_visit`, then `add_stop` or `name_stop`;
- an end time is the trip's or the stop's, never the time of the user's message;
- "these were two things" or "this was one thing": `split_trip` or `join_trips`;
- ✕ by mistake: `restore_block`.

## 8. Locations and photos you send

The user (2026-11-24): whenever they send a location, or a photo that carries one, Mazkir should
look it up on the map. Sometimes to name the place the photo was taken (the café or restaurant of
a photo of food, or home), sometimes to pin down where on the street a street photo was taken.

Today the model gets the raw numbers: `EXIF GPS: lat, lng` for a photo
(`agent_service._build_user_content`) and `[Location: lat, lng — title]` for a location or venue.
From numbers a model can tell the city at best, and guesses the rest.

**New rule.** Code looks the position up and the model gets words, never the numbers:

```
[Photo saved to: … | taken 13:05 | at home]
[Photo saved to: … | taken 13:05 | where: m1 Café X (café, 10 m), m2 Restaurant Y (restaurant, 25 m),
 m3 Bakery Z (bakery, 40 m); on Street N, by number 12; in <area> | GPS ±15 m]
[Location: where: place:gym The gym (yours, 5 m); on Street N; in <area>]
[Location — "Venue title": where: m1 … ]
```

- **Places of the user's first.** Inside a place of the user's radius (home included), the line
  says so ("at home", "at <place>") and the map is not shown, as at a stop today.
- **Otherwise the map**: up to 5 places nearest first, within `max(40 m, the photo's GPS
  accuracy)`, using `map_near`'s ranking (an area that contains the point first); then the nearest
  address ("on <street>, by number N") and the area (`map_area`). The address is what pinpoints a
  street photo.
- **The photo's own accuracy** is shown when the EXIF has it (`GPSHPositioningError`), because a
  photo indoors can be 30 m off and the model should not pick the nearest café on faith.
- **A trip stop at that moment** wins over a fresh lookup: a photo taken during stop `s3` says
  "at stop s3 of trip <id> (<its name, or unnamed>)", with that stop's map places, so a photo of
  food at a café the user has not named yet helps name the stop (`edit_trip name_stop`).
- **Handles, not ids.** Each place comes with its handle (`m<n>`, `place:<id>`), from the same
  per-chat table as `find_place` (§7), so the agent can name a stop, set a block's place, or save
  a new place of the user's from it ("this is my friend's place" → `edit_place` / `learn_place`
  at the photo's position, server-side). The position itself stays on the server, keyed to the
  photo or the message.
- **`find_place` takes the photo or message as `near`** (`photo:<file>`, `location:<message_id>`),
  so "it's the burger place across the road" can search around it.
- **A forwarded location** is somebody else's place: it gets the lookup, but nothing from it is
  learned as a place of the user's without the user saying so.
- **No map copy** (`LOCATION_MAP=off` or no index): only places of the user's, and "no map
  here" otherwise. Never the numbers.
- **The venue's title** from Telegram is kept as it is: the user (or the sender) chose it.

**What stays.** The daily note's map link (`attach_to_daily` writes a Google Maps link with the
coordinates) is for the user, not the model, and is unchanged: tapping it opens the map. The
vault is the user's own private repo. *(Claude's call; the user can say otherwise.)*

## 9. Small fixes

- **✕ Not right skips approved blocks.** `runtime._approve` with `line == "all"` and `no`
  dismisses only blocks still pending. The toast says "Dismissed the rest — kept what you ✓'d."
- **A photo goes to the block it was taken in**, in every fast-lane mode, not only `on`: the
  photo path uses `fast_lane/photos.py`'s covering-block rule on the reconciled day, trip
  proposals included. Only a photo no block covers goes to the daily note. The agent is told where
  it went. The `photos/…` path in `attach_to_daily` is fixed to the vault media path.
  A photo on a proposal must not be lost when the writer re-plans: `apply_blocks` carries `photos`
  over when it deletes and recreates a pending block (a split, a stop crossing midnight), and a
  dismissed proposal's photos go to the daily note.
- **`next_skill:` never reaches the user.** `SkillExecutor` strips every `next_skill: <name>` line
  from the final response, whether or not the hop happened (an unknown name, the hop cap, a cycle).

## 10. Leaving room for the trip card

The next spec turns a trip's messages into one card that updates itself, possibly as a map image.
With no question limit, a long day out sends many questions; the card is what will gather them. To
keep that easy:
- every line the arrival message draws comes from one function over the record (`arrival_receipt`
  already does this); `later` stops go through it too;
- buttons address stops by id, never by position in a message;
- live questions go through one function, so the card can replace them with edits to itself.

## 11. How we know it works

- **Replay of 16–23 Nov** (`location_replay.py`, plus labels from the user's answers):
  - no trip is named without a question, except from the user's own block or words;
  - every stop is asked about, live or at home (from about 30 never asked to 0);
  - trip start times: the two early starts start at the first point away.
- **Tests** for each `edit_trip` op (split and join a trip both ways, split an open trip),
  `find_place` ranking in Hebrew and English, `find_visit` on synthetic points, ✕ All after a ✓, a
  street refused as a place, the `next_skill` strip, a photo and a location turned into map words
  (at home, at a stop, near places, with no map).
- **No coordinate in any new tool result or in what a photo or location adds to the prompt**: a
  test runs every new tool and the two prompt paths, and checks for no `lat`/`lng` key, no OSM id
  and no number with 4 or more decimals.
- **A live check**: the user's next long day out, and correcting one trip by talking, including a
  split.

## 12. Left to the builder

- How `find_place` matches Hebrew against English names beyond `name_en` (transliteration is not
  required).
- Where `edit_trip` lives (`pipeline.py` next to `apply_answer`, or a new `edits.py`).
- How a split trip's raw points are assigned to each half for `find_visit` and a rebuild.
- Exact wording of the new messages and toasts.

## 13. Decisions

**The user's (2026-11-24):** every trip asks (§4); no limit on questions (§5); no automatic
splitting of trips, and no temporary home, until more use shows a rule; the agent splits and joins
trips when asked (§7.4); every location and photo sent is looked up on the map (§8).

**Claude's, for the user to check:**
- A mid-trip answer and the user's own block still name a trip without a question (§4).
- A stop left unanswered is asked again in the arrival message (§5).
- 10 min as the stop length that ends a leg (§6).
- One `edit_trip` tool with ops rather than ten tools, to keep the skill's tool list short.
- `split_trip` keeps the first trip's id and purpose; `join_trips` keeps the first trip (§7.4).
- `find_place` searches within 3 km and returns at most 8.
- Visit matching radius `max(40 m, accuracy)` and 10-min silences (§7.3).
- Past trips are re-derived into `derived/` only; live records change only through edits.
- Map handles `m<n>` per chat for 24 h instead of OSM ids (§7).
- An edit's result is drawn as a new message under the agent's reply; the old one is left (§7).
- An edit to an approved block updates it and Google; legs keyed by the stops they join (§7.4).
- Photos carried over on re-plan, back to the note on dismissal (§9).
- The model gets map words instead of coordinates for photos and locations, with up to 5 places,
  the nearest address and the area; a trip stop at that moment wins (§8).
- The daily note's map link stays (§8).
