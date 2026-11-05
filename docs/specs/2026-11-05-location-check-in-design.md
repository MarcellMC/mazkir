# Location Check-in: where you were becomes evidence on your timeline (Design)

**Status:** Draft, written 2026-11-05 from conversation. Not yet reviewed section by section. **L0 (the spike, §4) is the only piece ready to plan.** L1–L3 are designed to the depth needed to estimate them and to know what the spike must measure, and each is revisited after the spike reports (§4.6).
**Related:** `docs/specs/2026-09-27-fast-lane-design.md` §7.3 (places, "names only in A: coordinates and arrival triggers come later" — this design is that later), `docs/specs/2026-09-10-ship5-inferred-capture-design.md` (approval of machine-inferred blocks, gap proposals), `docs/specs/2026-08-29-ship2-navigable-day-design.md` (source availability, coverage).

---

## 1. What this is for

### 1.1 Goals

1. **Restore the day from where you were.** Like Google Timeline: visits ("Gym, 18:05–19:10") and travel between them arrive in `/day` as pending blocks you confirm, correct or dismiss. That closes the largest gaps in the ledger, the ones you never logged by message.
2. **Reminders that know where you are, by kind of place.** Like Google Keep's location reminders, but smarter. "Buy ibuprofen" needs *a* pharmacy, not one particular pharmacy. When you are near any open pharmacy and the todo is still open, Mazkir tells you.

### 1.2 The principle

The fast lane's principle holds here: **the model decides what something says, code decides what happens.** The only model call in this design is classifying what kind of place a todo needs, once, when it is captured (§7.2). Segmenting points into visits, naming places, matching todos and deciding to notify are all deterministic code, so they can be replayed, tested and tuned against labelled days.

### 1.3 Sources

The first source is **Telegram live location**, because it needs nothing new: the bot already long-polls, so no endpoint has to be exposed to the internet, and the phone already runs Telegram. But Telegram is a messaging app, not a location logger, and how densely it samples is the main unknown (§2.2). **Ingest is therefore independent of the source:** every point arrives at `POST /locations/points` in one shape. If the spike shows Telegram's sampling is too thin, a dedicated logger (OwnTracks, Overland on iOS) feeds the same endpoint, and nothing downstream changes.

---

## 2. What we know and what we do not

### 2.1 Telegram, as documented (Bot API, read 2026-11-05)

- A live location arrives first as a `message` whose `location` carries `live_period` ("Time relative to the message sending date, during which the location can be updated; in seconds. For active live locations only.").
- Each position change arrives as an **`edited_message`** for the same `message_id`, with `edit_date` ("Date the message was last edited in Unix time").
- `Location` also carries `horizontal_accuracy` ("The radius of uncertainty for the location, measured in meters; 0-1500") and `heading` ("1-360. For active live locations only."). `proximity_alert_radius` is for alerts between chat members and is no use to a bot.
- `getUpdates` keeps undelivered updates for at most **24 hours**. The default `allowed_updates` excludes only `chat_member`, `message_reaction` and `message_reaction_count`, so `edited_message` is already delivered: `index.ts` calls `bot.start()` with no `allowed_updates`.
- The bot's auth middleware checks `ctx.from?.id`, which is set on an `edited_message` too, so edits pass the existing authorization. Its `kind` label currently calls them `"other"`.

### 2.2 Not documented, so the spike measures it

1. **How often an update comes**, while moving and while still. The Telegram app decides; it is not in the API.
2. **Whether anything comes while you are still.** If the app sends nothing while you sit for an hour, "still" and "phone off / Telegram killed by the OS" look the same. This drives the silence policy in L1 (§5.3).
3. **What the bot receives when sharing stops**, by expiry or by tapping "stop": a final edit without `live_period`, nothing, or something else.
4. **The "until I turn it off" option**: what `live_period` value it sends, and whether it really runs for days or quietly expires.
5. **Background behaviour on your phone**: whether updates keep coming with the screen locked for hours, and the battery cost.
6. **Accuracy indoors and in the city**: the `horizontal_accuracy` distribution, and how far still-standing points scatter.

### 2.3 What already exists

| Piece | Where | What it gives this design |
|---|---|---|
| Visit / transit dict shape | `timeline_service.py:178` (`_parse_visit`), `_parse_activity` | A new source that emits the same `{visits, activities}` plugs into `MergerService.merge` unchanged: calendar matching, unplanned stops, transit blocks |
| Source fan-out and availability | `services/day_assembly.py` | Where a new source is added, and the rule that an unavailable source never deletes its events |
| Pending approval of inferred blocks | `services/approval.py` `resolve_state` | Inferred visits arrive with ✓ ✕ ✎ in `/day` and count toward `confirmed_minutes` only once approved |
| Gap proposals from history | `services/gap_proposals.py` | Extended with place → usual activity (§6.4) |
| Places by name | `services/fast_lane/places.py`, `data/places.json` | Gains coordinates (§6.1) |
| One-off location messages | `conversations/message.ts:70` | Already sent to the agent as an attachment; becomes a check-in (§5.6) |
| Google Takeout history | `data/timeline/` | Historical only: Google no longer exports new history this way. Kept for past days (§5.5) |

---

## 3. The pieces

| Piece | What | Estimate | Ready to plan? |
|---|---|---|---|
| **L0** | Spike: log raw points, report on them, label two days | 1–2 days of code, then ~5 days of sharing | Yes (§4) |
| **L1** | Points → visits and transit in `/day` | 3–4 days | After L0 |
| **L2** | Naming places: your places, nearby points of interest, learning new ones | 2–3 days | After L1 |
| **L3** | Location reminders by kind of place | 4–6 days | After L2 |
| **L4** | Smarter: on-route suggestions, urgency, errand grouping | Not estimated | Later |

About 2–3 weeks for L0–L3. Most of the risk is in L0's answers and in L3's noise control (§7.5), not in the amount of code.

L1 and L3 depend on L2 only loosely: L1's visits can render as "Unknown place" before L2 exists, and L3 needs L2's point-of-interest lookup but not its learning loop.

---

## 4. L0 — the spike

### 4.1 Scope

**Log every point, write nothing else, and report what came in.** No visits, no blocks, no reminders, no model calls. The spike's only purpose is to answer §2.2 on your own phone and your own days, so that L1's thresholds are tuned on real data rather than guessed.

Behind `LOCATION_INGEST=off|log` (default `off`), read by **both** the bot and the server. `off` keeps today's behaviour exactly. The bot needs the switch too: without it, a live share's first message would stop reaching the agent even with the server's ingest off.

### 4.2 Bot

A new Composer, `src/conversations/location.ts`, registered **before** `messageHandler`:

- **`edited_message:location`** → `POST /locations/points` with one point. Never goes near `/message`: a model call per point would cost money and minutes for nothing.
- **`message:location` with `live_period`** (a live share starting) → the same, and **not** to the agent. Today this message falls through to `messageHandler` and starts an agent turn about a bare location, which helps nobody.
- **`message:location` without `live_period`** (a one-off share, or a venue) → logged as a point with `kind: "check_in"`, **and** still passed on to `messageHandler` as today (`next()`), so the agent's existing location handling is unchanged.
- The auth middleware's `kind` gains `"live_location"` for edits and live starts, and reads `ctx.editedMessage` as well as `ctx.message`, so these updates are labelled in logs and spans rather than `"other"`.
- A failed POST is logged (`event_type: "location_ingest_failed"`) and dropped. grammY confirms the update either way, so a vault-server outage loses those points; the spike counts how often that happens (§4.5) and L1 decides whether the bot needs a retry buffer.

Sent per point:

```json
{
  "source": "telegram",
  "kind": "live" | "live_start" | "check_in",
  "message_id": 123,
  "ts": "2026-11-06T08:14:03+02:00",
  "lat": 32.0853, "lng": 34.7818,
  "accuracy_m": 12.0,
  "heading": 270,
  "live_period": 28800,
  "venue_title": null
}
```

`ts` is `edit_date` for an edit and `date` for a new message, converted by the bot from Unix seconds to an ISO instant (UTC is fine; the server stores the instant and converts to `VAULT_TIMEZONE` only when deciding the file's date). `heading`, `live_period`, `accuracy_m` and `venue_title` are optional and passed through as received, so the report can see exactly what Telegram sent.

### 4.3 Server

- **`POST /locations/points`** (`api/routes/locations.py`): validates the body (pydantic, `extra="forbid"`), appends one line to `data/locations/raw/{YYYY-MM-DD}.jsonl`, and returns `{ok: true}`. The date comes from `ts` in `VAULT_TIMEZONE` with the **calendar** day, not the 05:00 logical day: raw files are storage, and the day boundary is applied when visits are derived (L1).
- The file name is built from a parsed `date`, never from the request, for the same reason `routes/daily.py` and `routes/events.py` type their dates: a string path segment once let a request choose the file read.
- Appends go through one process-wide lock, so two concurrent edits cannot interleave a line.
- Each stored line also gets `received_at` (server time), so the report can tell Telegram's lag from the phone's.
- `LOCATION_INGEST=off` answers 404, so a bot running with the handler but against a server with ingest off logs failures rather than writing.
- Settings: `location_data_path` (default `data/locations`), `location_ingest` (`off`).
- One span per point, `location.ingest`, with `kind`, `accuracy_m` and the gap since the previous point. No `input.value`: coordinates do not go to Phoenix.

### 4.4 Privacy

Raw points are the most sensitive data Mazkir will hold. They stay in `data/locations/` (gitignored, like the rest of `data/`), are never sent to Phoenix, Loki or a model, and the spike makes no external calls at all. L2's point-of-interest lookups are the first time a coordinate leaves the machine (§6.2).

### 4.5 The report

`scripts/location_spike_report.py [date|--from D --to D]`, pure reads, no network. Prints:

1. **Share sessions:** each live share's start, its `live_period`, the last point received, and how it ended (what the final update looked like, or "no final update"). Answers §2.2 items 3 and 4.
2. **Sampling:** points per hour of the day; the interval between consecutive points, split into *moving* (> 1 km/h implied from the previous point) and *still*, as p50 / p90 / max. Answers items 1 and 2.
3. **Silences:** every gap of more than 15 minutes during an active share, with the distance between the points either side. A long silence with ~0 distance is "still, nothing sent"; a long silence with a large distance is "lost updates".
4. **Accuracy:** the `horizontal_accuracy` distribution, and the scatter (p90 distance from the centroid) of runs of still points.
5. **Coverage:** the share of waking hours (07:00–23:00 by default) inside an active share.
6. **Ingest health:** points received vs. `location_ingest_failed` lines in `telegram-bot.jsonl`, and the p50 / p90 of `received_at − ts`.
7. **A naïve stay-point pass** with default parameters (150 m, 8 min, §5.2), printed as a list of visits, so you can label them.

### 4.6 Labelling and exit criteria

Share "until I turn it off" for **about 5 days**, including at least one workday, one weekend day and one day with errands. Then label **two days** in `data/eval/location/{date}.json` (gitignored, like `data/eval/`, because the repo is public): your actual visits with rough start and end times and a name, written from memory and photos, alongside the naïve pass's output. The same labels later score L1 (§5.7), as the fast lane's replay scores the parse.

**Go to L1 with Telegram** if all of these hold:
- While moving, p90 interval ≤ 5 minutes.
- Visits of 15 minutes or longer in your labels appear in the naïve pass, or would with a different threshold, for at least 80% of them.
- Coverage of waking hours ≥ 80% on days you meant to share.
- The battery cost is one you accept.

**Swap the source** (OwnTracks or Overland → the same endpoint, `source: "owntracks"`) if moving sampling is too sparse, or if background updates stop with the screen locked. That costs about a day more and changes nothing after ingest.

**Stop** if neither source gives usable data, and record what the spike found in this spec.

The spike's answers are written back into §2.2 and §5 before L1 is planned.

### 4.7 Tests

- Bot: an edited location posts one point and does not call `/message`; a live start does not call `/message`; a one-off location posts a `check_in` **and** reaches `messageHandler`; an unauthorized edit posts nothing; `ts` comes from `edit_date` on an edit.
- Server: a valid point appends one line to the right date's file (including a point near midnight in `VAULT_TIMEZONE`); unknown fields are a 422; `off` is a 404; concurrent posts produce whole lines.
- Report: fixed fixture files give fixed numbers for sampling, silences and sessions.

---

## 5. L1 — points become visits

Designed now so the spike measures the right things. Thresholds are placeholders until §4.6.

### 5.1 Shape

`LocationService.get_day(date) -> {visits, activities}`, the same dicts `TimelineService.get_day` returns (`name`, `lat`, `lng`, `start_time`, `end_time`, `duration_minutes`, `confidence`, `place_id`, and for activities the mode and distance). `MergerService.merge` then needs no changes beyond the new `source_ids` key (§5.4).

### 5.2 Segmentation

An **online** stay-point detector, run on ingest, one point at a time:

- Drop points with `accuracy_m` above a cutoff (placeholder 200 m) for segmentation, but keep them in the raw file.
- A **visit** opens when points stay within a radius (placeholder 150 m) of their running centroid for at least a minimum time (placeholder 8 minutes). It closes when a point lands outside the radius and the next one confirms it (one stray point is not a departure).
- Between visits is **transit**, with a mode guessed from median implied speed: walking, cycling, driving or transit. The modes are the same values as `ACTIVITY_MODE_MAP` produces, so the merger renders them already.

Online, rather than recomputed from the whole day on every read, for two reasons: L3 needs to know *now* that you have arrived somewhere, and a closed visit can then be frozen (§5.4). `scripts/location_rebuild.py [date]` replays the raw file through the same detector, so a change of thresholds is a rebuild, not a migration.

State: closed visits and transit in `data/locations/derived/{date}.json`, the open visit (if any) in `data/locations/open.json`.

### 5.3 Silence

The spike decides this; the design gives the options.

- If Telegram sends nothing while still (§2.2 item 2): a silence ends a visit **only** when the next point is outside its radius, and then the visit ends at the last point inside it. A visit continued across a silence carries lower `confidence`, and a silence longer than a cap (placeholder 3 hours) ends it at the last point regardless, since you may have walked out with a dead phone.
- If it does send something while still: a silence is lost data, and the visit ends at the last point.
- A share that ends (§2.2 item 3) closes the open visit at its last point, and the bot says once, "Location sharing stopped — share again to keep your day filling in", so a share that quietly expired is not a week of missing days.

### 5.4 Stable IDs and approval

`EventsService.reconcile` keys persisted rows on `source_ids`, and approvals are stored on those rows. A visit whose identity shifted when more points arrived would drop its approval, so:

- A visit's id is `location_visit:<hash of its first point's ts>`; transit is `location_transit:<…>`. The detector is deterministic, so a rebuild with unchanged thresholds reproduces the same ids.
- Closed visits are **frozen**: later points never change them. Only the open visit at the end of the day moves, and it is not yet approvable (it renders as ongoing, like an open block).
- A rebuild with **changed** thresholds can change ids. `location_rebuild.py` carries an approval or `user_set` pin over to the new visit that overlaps it most, and reports what it could not carry.

### 5.5 Availability, and the Takeout history

Ship 2's rule — an unmatched persisted event is dropped only when its source actually answered — needs care here, because "no points" is not "went nowhere". The location source is **available for a span** only while a share was active and points were arriving. `day_assembly` adds `"location"` to `available_sources` only for dates whose whole elapsed time was covered by a share. Otherwise persisted location rows are kept, which is the safe direction.

For a date that has location data, the location source supplies visits and the Takeout history supplies none, so the two never double up. Dates without location data keep reading Takeout as today.

### 5.6 Check-ins

A one-off location share (§4.2), or a message like "at the pharmacy", is a **declared** arrival rather than an inferred one. As a point it is weighted: it opens a visit at once, with no minimum time, and the visit is approved rather than pending (it is a human action, like a ticked habit). Through the fast lane, a check-in can also open a block for the activity the message names. The fast lane's §7 matching rules apply unchanged; how a check-in point and a check-in message are joined is decided when L1 is planned.

### 5.7 Evaluation

`scripts/location_replay.py` runs the detector over the labelled days in `data/eval/location/` and scores visits found, visits missed, visits invented, and start/end error (p50 / p90 minutes). Free and offline, like the fast lane's `--resolver-only`.

---

## 6. L2 — naming places

### 6.1 Your places get coordinates

`data/places.json` entries gain optional `lat`, `lng` and `radius_m` (default 100). `places.py` keeps resolving by name for the fast lane, and gains `nearest(lat, lng)`. A visit whose centroid falls inside a known place's radius gets that `place_id` and name.

### 6.2 Nearby points of interest

Otherwise, the visit's centroid is looked up against points of interest within its radius. Two candidates, chosen during L2 planning:

- **OpenStreetMap via Overpass** — free, no account, good tags for kinds of place (`amenity=pharmacy`, `shop=supermarket`) and `opening_hours`. Variable data quality in places, rate-limited public servers, and the server sees roughly where you are.
- **Google Places** — better names and coverage, paid per call, and Google sees roughly where you are.

Recommendation: Overpass, because L3 needs the kinds-of-place tags and opening hours, and the cost of being wrong is a visit labelled with the shop next door, which ✎ fixes.

Either way, lookups are **cached per map tile** (about 1 km, `data/locations/poi/{tile}.json`, refreshed after a few weeks), so a coordinate leaves the machine once per tile, not once per visit. Repeated visits to the same tile cost nothing.

### 6.3 Learning new places

An unnamed place you keep returning to — by default 3 visits within 30 days, within 100 m of each other — gets one question in Telegram: "You've been here 4 times (Tue 18:00, …). What is it?", with the nearest points of interest as buttons and a free reply. The answer becomes a `places.json` entry with coordinates. A dismissed question is not asked again for that cluster.

### 6.4 Place → activity

`gap_proposals.py` and the visit blocks learn which activity usually happens at a place from approved history: a visit to "Gym" proposes "Workout" once three past approved blocks there carried that name. Until then the block's name is the place's name.

---

## 7. L3 — reminders by kind of place

### 7.1 What a todo can need

A **place requirement** on a todo or task, one of:

- `{kind: "category", category: "pharmacy"}` — any place of that kind. Categories are a **fixed list** mapped to OSM tags in code: pharmacy, supermarket, convenience, bakery, hardware, post office, bank / ATM, pet shop, and a handful more. Not free text, so there is nothing for the model to invent.
- `{kind: "place", place_id: "danas-place"}` — one of your places.
- None — most todos.

### 7.2 Classifying at capture

When a todo or task is created (fast lane `add_todo`, `daily_add_task`, `create_task`), one Haiku call with structured output (the category enum, plus `place` and `none`) decides the requirement. It runs after the write and never blocks it, and it is best-effort: a failure means no requirement, logged. "Buy ibuprofen" → pharmacy; "buy milk" → supermarket or convenience; "return the drill to Dana" → the place `danas-place`, if it exists. The receipt line can show it (`📍 pharmacy`) with a tap to remove or change it.

### 7.3 Where the requirement lives

**Open question for L3 planning.**

- **Task files:** a `where:` frontmatter field. Straightforward.
- **Daily-note todos:** they are lines, with no id. Options:
  - an inline decoration, `- [ ] buy ibuprofen 📍pharmacy`, visible and editable in Obsidian. It survives edits and rollover with the line, but it is one more decoration for `_parse_task_content` to peel, and the peel order there is subtle (see CLAUDE.md, "Daily-note line parsing");
  - a sidecar file keyed by todo text, which breaks when the text changes (the deferred undo already suffers from matching by text).

  The inline decoration is recommended.

### 7.4 Triggering

On each ingested point, if there are open todos with a requirement:

1. Skip if you are moving fast (driving, by speed), at home, or inside quiet hours.
2. For each such todo, find the nearest matching point of interest within a walking radius (placeholder 300 m) from the tile cache, filtered by `opening_hours` when the tag exists (open for at least the next 15 minutes). An unparseable or missing `opening_hours` counts as open.
3. Skip any todo with a cooldown in force (§7.5).
4. If something remains, **the response to the ingest POST carries it**: `{ok: true, notify: [{todo, place_name, distance_m, …}]}`. The bot sends the message.

That last point avoids a new channel: the bot is pull-only today, and it is already POSTing every point.

The message: "💊 Superpharm, 120 m — buy ibuprofen", with buttons **✓ Done** (checks the todo), **Snooze 2 h**, **Not here** (never this place for this todo) and **Stop reminding** (removes the requirement). Several todos for the same place go in one message.

### 7.5 Noise control

This is what decides whether you keep the feature on. One irrelevant ping a day and you learn to ignore it.

- A cooldown per todo (placeholder 4 hours after any reminder) and per place (1 hour).
- Never twice for the same visit.
- Never at a place you are already visiting for longer than a few minutes — you know you are there.
- A daily cap (placeholder 3 reminders).
- Every reminder and every tap is logged (`data/logs/location-reminders.jsonl`), so the ratio of ✓ Done to ignored or "not here" can be read, and the thresholds tuned on it.

### 7.6 State

Cooldowns, snoozes and "not here" rules in `data/locations/reminders.json`. Small, per-todo, and safe to delete (worst case, a reminder repeats).

---

## 8. L4 — later

Not designed here:

- **On the way:** heading and recent transit suggest where you are going; a pharmacy a two-minute detour off the route is worth mentioning before you pass it, not after.
- **Urgency:** a todo due today widens its radius and skips its cooldown.
- **Errand grouping:** "3 of your todos fit around here".
- **Arrival triggers** for your own places ("when I get to the office, remind me…"), using the same trigger path with `kind: "place"`.

---

## 9. Files and data

| Path | What | Piece |
|---|---|---|
| `data/locations/raw/{date}.jsonl` | Every point, as received, plus `received_at` | L0 |
| `data/eval/location/{date}.json` | Your labelled visits | L0 |
| `data/locations/derived/{date}.json` | Frozen visits and transit | L1 |
| `data/locations/open.json` | The open visit | L1 |
| `data/locations/poi/{tile}.json` | Point-of-interest cache | L2 |
| `data/places.json` | Gains `lat`, `lng`, `radius_m` | L2 |
| `data/locations/reminders.json` | Cooldowns, snoozes, "not here" | L3 |
| `data/logs/location-reminders.jsonl` | Reminders sent and taps | L3 |

All under `data/`, all gitignored.

---

## 10. Failure handling

- **vault-server down:** points the bot cannot post are lost (§4.2); the spike measures how many. If it matters, L1 adds a small bot-side buffer, retried on the next successful post.
- **Bot down:** Telegram holds updates for 24 hours, so a short outage loses nothing.
- **A share ends:** the bot says so once (§5.3).
- **Point-of-interest lookup fails:** the visit stays "Unknown place" and the reminder check skips that tile; the next point retries. Never blocks ingest.
- **Classifier fails:** the todo has no requirement (§7.2).
- **A crash in segmentation or triggering:** caught and logged at ERROR. Ingest still appends the raw point first, so a rebuild recovers everything.

---

## 11. Out of scope

- Importing new Google Timeline data (Google no longer exports it as Takeout did).
- Sharing or showing location to anyone else.
- Any model reading raw coordinates.
- A map view in the Mini App — the Playground already draws route sketches from timeline data, and could read L1's output later.

---

## 12. Verify during planning

- **L0:** grammY's filter for `edited_message:location`, and that a Composer registered before `messageHandler` can pass a one-off location on with `next()`.
- **L0:** how `edit_date` behaves for live-location edits (it is the last-edited time, so it should be each point's time).
- **L1:** the `MergerService` path for unplanned stops and transit (`_create_unplanned_stop`, `_create_transit_event`). Today they stamp `source="timeline"` with `source_ids` keys `visit_id` / `transit_id`, which `reconcile` maps to the `timeline` source system. The location source needs its own keys (`location_visit` / `location_transit`) mapped to `location`, or Takeout's availability would decide whether location rows can be dropped.
- **L2:** Overpass rate limits and the tile size that keeps the cache small.
- **L3:** a Python `opening_hours` parser that handles OSM's syntax well enough, or a deliberate "unparseable counts as open".

---

## 13. Docs updated in each piece's PR

- `CLAUDE.md`: the `/locations/points` endpoint, the `LOCATION_INGEST` setting, the new `data/locations/` folder in the repository tree, and an architecture note per piece.
- This spec: §2.2 and §5's placeholders replaced with the spike's numbers once L0 reports.
