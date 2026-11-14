# Location Trips Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the live-location stream into trips. For each trip, work out what it was from your history and context, ask only when Mazkir can't tell, and write it to `/day` as proposed blocks. Those blocks merge with what you logged yourself, and a message when you're back makes confirming or fixing them one tap.

**Architecture:**
- **Tracker.** A pure state machine runs inside `POST /locations/points`. It turns points into stays, stops and trips, and emits events.
- **Worker.** One background thread handles each event: history scoring and context gathering (code), one Haiku call, the ask-or-name decision (code), then writing blocks through `AgentService.run_tool`.
- **Messages.** These ride back to the bot in the ingest response's `notify[]`, shaped as fast-lane `Receipt`s so the bot's existing receipt renderer draws them.
- **Trip clock.** A lifespan loop that sends "sharing stopped" when no point will carry it.

**Tech Stack:** FastAPI + pydantic (Python 3.14, pytest), Anthropic SDK structured output (Haiku), grammY + vitest (TypeScript), `@mazkir/shared-types`.

**Spec:** `docs/specs/2026-11-10-location-trips-design.md`. Read it fully before Task 1: the plan argues from it, and section numbers below (§4.1 etc.) are the spec's.

## Global Constraints

- **Coordinates never reach a model call, a span, a log line, the vault, or `data/logs/`.**
  - The model sees place names, distances in metres, durations, speeds and times.
  - Coordinates live only in `data/locations/` (raw, state, trips, derived) and in `data/places.json`.
  - Every task that writes a log, a span or a prompt gets a test asserting no coordinate appears.
- **`LOCATION_AWARENESS=off` (the default) changes nothing.** The ingest route behaves exactly as L0. No tracker or worker is created, and no clock runs.
- **Thresholds are copied from spec §4.1, verbatim:**
  - accuracy cutoff 30 m;
  - outlier above 150 km/h both into and out of a point;
  - a stay is ≥ 3 min;
  - home radius **40 m**; elsewhere 75 m;
  - leaving needs 3 good points in a row, for ≥ 1 min. At home the threshold is the radius itself; elsewhere it is `max(radius, 3 × spread + accuracy)`;
  - silence over 10 min is missing data; 30 min with no points means the share stopped;
  - leg modes: walk ≤ 7 km/h, ride ≤ 25 km/h, vehicle above;
  - home is learned from 01:00–05:00 over 14 days.
- **Every trip block is a proposal** (`proposed: true`). It reaches Google Calendar and `## Schedule` only on ✓, through `_settle_proposal`.
- **What the user said is never overwritten by location** (§6.5). A time counts as stated when its precision is `exact` or `approx` (fast lane `STATED`), or when there is no precision at all on a block the user made.
- **Questions:** at most once per stop, never re-sent, and a cap of 6 per logical day. Never ask about a stop already left. Questions are allowed at any hour.
- **No rule anywhere names an activity.** No string "dog" or "walk" in tracker, decide or writer logic. Leg names come from mode words, and nothing else.
- **Commits** end with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01XBHMJx179hGQ9cBNK8KByd
  ```
- **Branch** `feat/location-trips` (already exists, holds the spec). `master` takes PRs only.
- **Server tests:** `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/<file> -q`. Full suite: `python -m pytest tests/ -q`.
- **Bot tests:** `cd apps/telegram-bot && npx vitest run <file>`. Full: `npx vitest run && npx tsc --noEmit`.
- **New server code** goes in `apps/vault-server/src/services/location/` (a package; `location_store.py` stays where it is).

## Review Focus

1. **A share that ends and is restarted mid-trip.** You get a new `live_start` with a new `message_id`, and the same trip continues. There is no second LEFT and no second trip. Test in Task 3.
2. **Redelivered or out-of-order points** (grammY re-fetching after a crash). A point at or before the last processed `ts` changes nothing and emits nothing. Test in Task 3.
3. **A server restart between an event and its handling.**
   - The event is in the trip record's `inbox` and is handled after the restart.
   - A question already queued in the outbox is not queued again.

   Test in Task 12.
4. **A trip block you edited with ✎** (PATCH pins `user_set`) while the trip continues. The writer must not touch the pinned fields when the trip updates the block. Test in Task 10.
5. **A coordinate leaking** into the decision log, a span attribute, or the model's content. Tests in Tasks 8, 12.

---

## File Structure

**Server, new (`apps/vault-server/src/services/location/`):**

| File | Responsibility |
|---|---|
| `__init__.py` | empty |
| `model.py` | Dataclasses: `Fix`, `Stop`, `Leg`, `Trip`, `TrackerEvent`, and their `to_dict` / `from_dict` |
| `tracker.py` | `Params`, `Tracker`: points → stays, stops and trips; emits events (§4) |
| `home.py` | `find_home(fixes_by_night)` (§4.2) |
| `records.py` | `TripRecords`: one JSON record per trip in `data/locations/trips/{id}.json` |
| `outbox.py` | `Outbox`: queued messages with ack, in `data/locations/outbox.json` (§6.1) |
| `history.py` | `ConfirmedTrip`, `load_confirmed`, `score_history` (§5.2 item 1) |
| `context.py` | `ContextLine`, `gather_context` (§5.2 item 2) |
| `guess.py` | `GUESS_SCHEMA`, `Guess`, `guess` (§5.3) |
| `decide.py` | `Option`, `Decision`, `decide` (§5.4) |
| `writer.py` | `BlockSpec`, `plan_blocks`, `apply_blocks` (§4.3, §6.5) |
| `messages.py` | `question_receipt`, `arrival_receipt`, `notice_receipt` (§6.2, §6.3) |
| `pipeline.py` | `TripDeps`, `handle_event`, `apply_answer` (glues the parts per event) |
| `runtime.py` | `LocationRuntime` (tracker + state.json + worker thread + clock), `get_runtime` / `set_runtime` |

**Server, modified:**
- `src/config.py`
- `src/services/events_service.py`
- `src/api/routes/events.py`
- `src/services/agent_service.py`
- `src/services/fast_lane/places.py`
- `src/api/routes/locations.py`
- `src/main.py`
- `src/logging_setup.py`

**Server scripts, new:**
- `scripts/location_rebuild.py`
- `scripts/location_seed_labels.py`
- `scripts/location_replay.py`
- `scripts/location_labels_from_ledger.py`
- `scripts/location_trips_report.py`

**Bot:**
- New: `src/callbacks/trip.ts`, `src/state/nudge-draft.ts`.
- Modified: `src/conversations/location.ts`, `src/api/client.ts`, `src/callbacks/index.ts`, `src/callbacks/day-actions.ts`, `src/conversations/message.ts`, `src/tracing-utils.ts`.

**Shared types:** new `packages/shared-types/src/location.ts`, re-exported from `index.ts`.

**Vault (nested repo `memory/`):** `00-system/skills/time-management.md` gains the `set_trip_purpose` tool and one rule line.

**Ruling recorded here: no separate trip formatter.** The spec lists `formatters/trip-rich.ts`. The trip messages are `Receipt`s, so `buildReceiptRich` draws them unchanged, and one renderer means one place for button rules.

---

### Task 1: Settings, the events lock, and unpinned inferred edits

**Files:**
- Modify: `apps/vault-server/src/config.py` (next to `location_ingest`, line ~90)
- Modify: `apps/vault-server/src/services/events_service.py` (`FAST_FIELDS` line 66, `__init__` line 159, every method that ends in `save_events`)
- Modify: `apps/vault-server/src/services/agent_service.py` (`_tool_update_event`, the `user_set_fields` line ~3594)
- Modify: `apps/vault-server/src/api/routes/events.py` (the four `save_events` call sites: lines ~238, 300, 362, 486)
- Test: `tests/test_events_service.py`, `tests/test_agent_service.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `settings.location_awareness: str = "off"`, `settings.location_guess_model: str` (default the same string as `fast_parse_model`), `settings.location_guess_timeout_s: float = 8.0`.
- Produces: `EventsService.lock: threading.RLock` (one per instance; the app has one instance).
- Produces: `"trip"` in `FAST_FIELDS`. A block's `trip` field is `{"id": str, "part": str}`.
- Produces: `_fast.inferred: true` on `update_event`, meaning pin nothing.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_events_service.py
def test_events_service_has_one_reentrant_lock(tmp_path):
    svc = EventsService(events_path=tmp_path)
    with svc.lock:
        with svc.lock:          # re-entrant: service methods call each other
            svc.create_event(date="2026-11-13", name="X", start_time="2026-11-13T10:00:00")
    assert svc.get_events("2026-11-13")[0]["name"] == "X"

def test_create_event_keeps_trip_field(tmp_path):
    svc = EventsService(events_path=tmp_path)
    svc.create_event(date="2026-11-13", name="Trip", start_time="2026-11-13T10:00:00",
                     proposed=True, fields={"trip": {"id": "1a2b3c4d", "part": "trip"}})
    assert svc.get_events("2026-11-13")[0]["trip"] == {"id": "1a2b3c4d", "part": "trip"}

def test_concurrent_creates_lose_nothing(tmp_path):
    import threading
    svc = EventsService(events_path=tmp_path)
    threads = [threading.Thread(target=svc.create_event,
               kwargs=dict(date="2026-11-13", name=f"E{i}", start_time="2026-11-13T10:00:00"))
               for i in range(20)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert len(svc.get_events("2026-11-13")) == 20
```

```python
# tests/test_agent_service.py
def test_update_event_inferred_pins_nothing(agent_with_events):
    agent, events = agent_with_events
    e = events.create_event(date="2026-11-13", name="Trip", start_time="2026-11-13T10:00:00", proposed=True)
    agent.run_tool("update_event", {"event_id": e["id"], "date": "2026-11-13",
                   "end_time": "2026-11-13T10:40:00", "_fast": {"inferred": True}})
    stored = events.get_events("2026-11-13")[0]
    assert stored["end_time"].startswith("2026-11-13T10:40")
    assert stored["user_set"] == {}

def test_update_event_without_inferred_still_pins(agent_with_events):
    # existing behaviour, pinned so the new flag cannot leak into the default
    ...same call without _fast... → assert "end_time" in stored["user_set"]
```

Use the fixture style already in `test_agent_service.py`. If no fixture wires a real `EventsService`, add `agent_with_events` there.

```python
# tests/test_config.py
def test_location_awareness_defaults_off():
    assert Settings().location_awareness == "off"
```

- [ ] **Step 2: Run them, expect failure**

Run: `python -m pytest tests/test_events_service.py tests/test_agent_service.py tests/test_config.py -q -k "lock or trip_field or concurrent or inferred or pins or location_trips"`

Expected: FAIL. You should see `AttributeError: 'EventsService' object has no attribute 'lock'`, the `trip` key missing, the 20-thread test short of 20, and `location_awareness` missing.

- [ ] **Step 3: Implement**
- **`config.py`:** add the three settings with a comment pointing to the spec.
- **`events_service.py`:**
  - `self.lock = threading.RLock()` in `__init__`;
  - wrap the body of `create_event`, `update_event`, `delete_event`, `attach_photo` and `refresh_events` in `with self.lock:`;
  - add `"trip"` to `FAST_FIELDS`.
- **`agent_service.py` `_tool_update_event`:** when `fast.get("inferred")` is true, set `user_set_fields = []`.
- **`routes/events.py`:** at each of the four sites, after the last `await`, take `with events_svc.lock:` and re-run `merged = events_svc.reconcile(date_str, fresh, available)` (or, at line ~238, `events = events_svc.get_events(date_str)`). Then re-apply the route's one change to the re-read list and `save_events`. No `await` may run inside the lock. That way the list being saved includes any write the trip worker made during the Google call.

- [ ] **Step 4: Run them, expect pass; then the events and route suites**

Run: `python -m pytest tests/test_events_service.py tests/test_agent_service.py tests/test_config.py tests/test_events_route.py tests/test_daily_route.py -q`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A apps/vault-server && git commit -m "feat(location): settings, an events-store lock, unpinned inferred edits"
```

---

### Task 2: Places with coordinates and pause spots

**Files:**
- Modify: `apps/vault-server/src/services/fast_lane/places.py`
- Test: `tests/test_fast_lane_places.py`

**Interfaces:**
- Produces: `Place` gains `lat: float | None = None`, `lng: float | None = None`, `radius_m: float | None = None` (frozen dataclass, defaults keep every existing constructor call valid).
- Produces: `PLACE_RADIUS_CAP_M = 150.0`, `PAUSE_KIND = "pause"`.
- Produces: `nearest(lat: float, lng: float, places: list[Place]) -> Place | None`. This returns the place whose radius contains the point, closest centre first, or `None`. Places without coordinates are ignored.
- Produces: `learn_place(path: Path, name: str, lat: float, lng: float, spread_m: float) -> tuple[Place, bool]`. It returns `(place, conflict)`:
  - a new name creates a place with `radius_m = min(max(60, spread_m), 150)`;
  - an existing name without coordinates gains them;
  - an existing name whose centre is farther than its radius returns `conflict=True` and changes nothing;
  - otherwise the radius grows to `min(max(radius, distance + spread_m), 150)`.
- Produces: `add_pause_spot(path: Path, lat: float, lng: float, spread_m: float) -> Place`, with id `pause-N`, name `"pause"`, kind `"pause"`.
- Produces: `set_home(path: Path, lat: float, lng: float) -> Place`, with id `home`, name `"Home"`, radius 40.
- Changes: `match_place` skips places of kind `"pause"`. `save_places` writes `lat` / `lng` / `radius_m` only when not `None`. `load_places` reads them.

- [ ] **Step 1: Write the failing tests**

```python
def test_coordinates_round_trip_and_old_entries_still_load(tmp_path):
    p = tmp_path / "places.json"
    p.write_text('{"places":[{"id":"abullafia","name":"Abullafia","aliases":[],"kind":null}]}')
    place, conflict = learn_place(p, "Alex's", 32.08, 34.78, spread_m=20)
    loaded = load_places(p)
    assert [x.id for x in loaded] == ["abullafia", "alex-s"]
    assert loaded[1].lat == 32.08 and loaded[1].radius_m == 60 and conflict is False
    assert "lat" not in json.loads(p.read_text())["places"][0]

def test_nearest_picks_the_containing_place():
    a = Place("a", "A", lat=32.0, lng=34.0, radius_m=60)
    assert nearest(32.0003, 34.0, [a]) == a          # ~33 m
    assert nearest(32.0010, 34.0, [a]) is None       # ~111 m

def test_learn_place_far_from_its_namesake_is_a_conflict(tmp_path):
    p = tmp_path / "places.json"
    learn_place(p, "Alex's", 32.08, 34.78, 20)
    place, conflict = learn_place(p, "Alex's", 32.10, 34.78, 20)   # ~2.2 km away
    assert conflict is True and load_places(p)[0].lat == 32.08

def test_radius_grows_but_is_capped(tmp_path):
    p = tmp_path / "places.json"
    learn_place(p, "Park", 32.0, 34.0, 20)
    learn_place(p, "Park", 32.0005, 34.0, 50)        # ~55 m off, inside 60
    assert load_places(p)[0].radius_m == 105
    learn_place(p, "Park", 32.0009, 34.0, 100)
    assert load_places(p)[0].radius_m == 150

def test_pause_spots_never_match_a_name(tmp_path):
    p = tmp_path / "places.json"
    add_pause_spot(p, 32.0, 34.0, 10)
    assert match_place("pause", load_places(p)) is None
    assert nearest(32.0, 34.0, load_places(p)).kind == "pause"
```

- [ ] **Step 2: Run, expect failure** (`ImportError: cannot import name 'learn_place'`)

Run: `python -m pytest tests/test_fast_lane_places.py -q`

- [ ] **Step 3: Implement**

Use `src.services.geo.haversine_m` for every distance. Keep `save_places` atomic, as today.

- [ ] **Step 4: Run, expect pass**

Run: `python -m pytest tests/test_fast_lane_places.py tests/test_fast_lane_matching.py -q`

- [ ] **Step 5: Commit**

`git commit -m "feat(location): places carry coordinates, radius and pause spots"`

---

### Task 3: The tracker

**Files:**
- Create: `apps/vault-server/src/services/location/__init__.py`, `model.py`, `tracker.py`
- Test: `tests/test_location_tracker.py`

**Interfaces:**
- Produces (`model.py`). All dataclasses have `to_dict() -> dict` and `@classmethod from_dict(d) -> Self`, with datetimes as ISO strings with offsets.

  ```python
  @dataclass(frozen=True)
  class Fix: ts: dt.datetime; lat: float; lng: float; accuracy_m: float | None

  @dataclass
  class Stop:
      id: str                     # "s1", "s2"… in order within one trip
      start: dt.datetime          # first fix of the stay
      end: dt.datetime | None     # last fix before leaving; None while there
      lat: float; lng: float      # running centre
      spread_m: float             # p90 distance of its fixes from the centre
      from_home_m: float | None
      place_id: str | None = None # from places.nearest at STOPPED

  @dataclass
  class Leg:
      start: dt.datetime; end: dt.datetime | None
      distance_m: float
      mode: str | None            # "walk" | "ride" | "vehicle"

  @dataclass
  class Trip:
      id: str                     # 8 lowercase hex
      origin: str                 # "home" | a place id | "stay"
      left_at: dt.datetime
      start_precision: str        # "location" | "before"
      stops: list[Stop]; legs: list[Leg]
      back_at: dt.datetime | None = None
      end_precision: str | None = None   # "location" | "before"
      distance_m: float = 0.0
      max_from_home_m: float = 0.0

  @dataclass(frozen=True)
  class TrackerEvent:
      kind: str                   # LEFT | STOPPED | LEFT_STOP | BACK_HOME | SHARE_ENDED
      ts: dt.datetime
      trip: Trip | None           # a deep copy taken when emitted
      stop_id: str | None = None
  ```

- Produces (`tracker.py`):
  - `Params`: a frozen dataclass with the Global Constraints values, as `accuracy_max_m=30`, `outlier_kmh=150`, `stay_min_s=180`, `home_radius_m=40`, `stay_radius_m=75`, `leave_points=3`, `leave_min_s=60`, `silence_s=600`, `share_ended_s=1800`, `walk_kmh=7`, `ride_kmh=25`.
  - `class Tracker`, with these members:
    - `__init__(self, home: tuple[float, float] | None, places: list[Place], params: Params = Params(), new_id: Callable[[], str] = lambda: uuid4().hex[:8])`
    - `feed(self, fix: Fix) -> list[TrackerEvent]`
    - `tick(self, now: dt.datetime) -> list[TrackerEvent]`
    - `set_home(self, home: tuple[float, float]) -> None`
    - `trip -> Trip | None` (a property)
    - `last_fix_ts -> dt.datetime | None` (a property)
    - `to_dict(self) -> dict` and `@classmethod from_dict(cls, d, home, places, params=Params()) -> Tracker`

**The rules feed applies (spec §4.1, §4.2, §4.4)** are below. The implementer chooses the internal state names.

1. **Points that don't count.**
   - A fix with `ts <= last processed ts` is ignored and emits nothing.
   - A fix with `accuracy_m > 30` is recorded as `last_fix_ts`, but never moves the state.
2. **One-point delay for outliers.** The newest good fix is buffered. It is processed when the next good fix arrives, unless its implied speed from the previous processed fix **and** to the new one are both above 150 km/h; then it is dropped. `tick()` processes a buffered fix that is older than 60 s.
3. **Stay.** Fixes within the radius of the running centre for ≥ 180 s.
   - The radius is `home_radius_m` when the centre is within `home_radius_m` of home, otherwise `stay_radius_m`.
   - Spread is the p90 distance of the stay's fixes from its centre.
4. **Leaving.** 3 consecutive good fixes beyond the threshold, spanning ≥ 60 s. The threshold is `home_radius_m` at home, otherwise `max(stay_radius_m, 3 × spread + accuracy)`.
   - The departure time is the last fix inside the stay.
   - When the gap between that fix and the first outside fix is > 600 s, the precision is `"before"`; otherwise `"location"`.
5. **Trip start.** With no trip open, leaving any stay emits `LEFT` with a new `Trip`. Its `origin` is `"home"`, the nearest place's id, or `"stay"`.
6. **Stop.** With a trip open, a stay reaching 180 s emits `STOPPED` with a new `Stop` (id `s{n}`, `place_id` from `places.nearest`). Leaving that stay emits `LEFT_STOP` and sets `stop.end`.
7. **Home wins.** With a trip open, 3 consecutive good fixes within `home_radius_m` of home, spanning ≥ 60 s, emit `BACK_HOME`. This applies whatever stop is open; that stop is closed at the last fix before the first home fix.
   - `back_at` is the first of the 3 home fixes.
   - `end_precision` is `"before"` when the gap before that fix is > 600 s.
   - The trip is closed and `trip` becomes `None`.
8. **Only leaving ends a stay.** A gap of any length, or an ignored fix, never ends one. After a gap, the next fix is judged by rule 4, against the stay it left.
9. **Legs.**
   - A new `Leg` starts at departure and at every `LEFT_STOP`. It ends at the next stop's start or at `back_at`.
   - `distance_m` sums the segments between consecutive good fixes that are ≥ 10 m long.
   - `mode` comes from the median segment speed: ≤ 7 km/h is `walk`, ≤ 25 is `ride`, above is `vehicle`.
   - `trip.distance_m` and `trip.max_from_home_m` are kept up to date.
10. **Share ended.** `tick(now)` emits `SHARE_ENDED` once, when `now - last_fix_ts >= 1800 s`. If a stop is open, it closes the stop at the last fix. A later fix at the same place reopens that stop (`end = None`), and it resets the once-only flag.
11. **Midnight is not special** anywhere.
12. **No home yet.** With `home is None`, rule 7 never fires and a trip stays open. The runtime closes it when home is set: `set_home` does not emit anything.

- [ ] **Step 1: Write the failing tests**

Build tracks with a helper `track(start, legs)`. It emits a fix every 30 s along straight lines, using `geo`-consistent offsets (1e-5 deg lat ≈ 1.11 m), with accuracy 10 unless given. `HOME = (32.0, 34.0)`. Each test names the rule it pins:

```python
def test_drift_at_home_is_not_a_trip():                      # rules 3, 4
    # 6 h of fixes scattered up to 35 m from home, accuracy 5–25
    assert all(e.kind != "LEFT" for e in feed_all(t, fixes))

def test_48m_shop_trip_is_found():                            # rule 4 at home, rule 7
    # home 20 min → walk to 48 m in 60 s → stay 3 min → back home 10 min
    kinds = [e.kind for e in events]
    assert kinds == ["LEFT", "STOPPED", "LEFT_STOP", "BACK_HOME"]
    assert events[-1].trip.back_at - events[0].trip.left_at <= dt.timedelta(minutes=5)

def test_departure_time_is_last_fix_inside():                 # rule 4
    assert left.trip.left_at == last_home_fix.ts and left.trip.start_precision == "location"

def test_three_bad_points_do_not_leave():                     # rule 1
    # 5 fixes at 300 m with accuracy 300, then back to home
    assert no LEFT

def test_single_far_outlier_is_dropped():                     # rule 2 (the 385 m point on 9 Nov)
    # night at home, one fix 385 m away between two home fixes 30 s apart
    assert no LEFT and t.trip is None

def test_one_minute_gap_does_not_split_a_stay():              # rule 8 (band practice)
    # trip to 205 m, stay 11:28–17:34 with a 70 s gap at 12:31
    assert [e.kind for e in events].count("STOPPED") == 1

def test_silence_then_far_means_left_before():                # rules 4, 8 (8 Nov evening)
    # at home until 18:35, silence 112 min, next fixes 615 m away
    assert left.trip.start_precision == "before" and left.trip.left_at.strftime("%H:%M") == "18:35"

def test_stop_near_home_does_not_swallow_the_walk_back():     # rule 7
    # stop 48 m from home (75 m radius would contain home), then 3 fixes at home
    assert events[-1].kind == "BACK_HOME"

def test_loop_with_three_stops_is_one_trip():                 # rules 5–7, 9
    assert [e.kind for e in events].count("LEFT") == 1
    assert [e.kind for e in events].count("STOPPED") == 3

def test_restarted_share_continues_the_trip():                # Review Focus 1
    # fixes stop for 5 min mid-trip, then resume from a new message id at a nearby position
    assert [e.kind for e in events].count("LEFT") == 1

def test_redelivered_and_older_points_change_nothing():       # Review Focus 2
    before = t.to_dict(); assert t.feed(same_fix_again) == [] and t.to_dict() == before

def test_share_ended_once_and_reopens():                      # rule 10
    assert [e.kind for e in t.tick(last + 31min)] == ["SHARE_ENDED"]
    assert t.tick(last + 40min) == []

def test_midnight_splits_nothing():                           # rule 11
    # stay 23:00–01:30 at a non-home place
    assert [e.kind for e in events].count("STOPPED") == 1

def test_leg_modes():                                         # rule 9
    # 5 km/h leg → "walk"; 18 km/h → "ride"; 50 km/h → "vehicle"

def test_state_round_trips_mid_trip():
    t2 = Tracker.from_dict(t.to_dict(), HOME, [])
    assert t2.feed(next_fix) == t.feed(next_fix)
```

- [ ] **Step 2: Run, expect failure** (`ModuleNotFoundError: src.services.location`)

Run: `python -m pytest tests/test_location_tracker.py -q`

- [ ] **Step 3: Implement `model.py`, then `tracker.py`, to the rules above**

- [ ] **Step 4: Run, expect pass**

Run: `python -m pytest tests/test_location_tracker.py -q` → all pass.

- [ ] **Step 5: Commit**

`git commit -m "feat(location): tracker — stays, stops and trips from live points"`

---

### Task 4: Home, records, outbox, and the rebuild script

**Files:**
- Create: `src/services/location/home.py`, `records.py`, `outbox.py`, `apps/vault-server/scripts/location_rebuild.py`
- Test: `tests/test_location_home.py`, `tests/test_location_records.py`, `tests/test_location_outbox.py`

**Interfaces:**
- **`home.py`:** `find_home(fixes: list[Fix], tz: str, today: dt.date, days: int = 14) -> tuple[float, float] | None`.
  - For each night in the window, take the good fixes between 01:00 and 05:00 local time. Their centroid counts as a night only if their p90 spread is ≤ 75 m.
  - Home is the night-centroid with the most other night-centroids within 75 m of it, and needs ≥ 3 such nights. The result is the mean of that cluster.
- **`records.py`:** `TripRecords(root: Path)`, where `root` is `data/locations`. Records go in `root/"trips"/f"{id}.json"`. Methods:
  - `get(id) -> dict | None`, `save(rec: dict) -> None` (atomic), `open_ids() -> list[str]`;
  - `on_day(day: dt.date, tz: str) -> list[dict]` (by `left_at`);
  - `questions_on(day: dt.date, tz: str, boundary_hour: int) -> int`. This counts `asked_at` stamps whose logical day (05:00 boundary, `settings.fast_lane_day_boundary_hour`) is `day`.

  The record shape, fixed here so later tasks share it:

  ```python
  {"id": str, "trip": Trip.to_dict(), "closed": bool, "inbox": [TrackerEvent.to_dict()],
   "purpose": None | {"name": str, "destination": str | None, "source": "guess"|"answer"|"user_block"},
   "stops": {stop_id: {"status": "named"|"asked"|"pause"|"unnamed", "name": str | None,
                       "place": str | None, "options": [Option.to_dict()], "asked_at": str | None}},
   "trip_question": None | {"options": [Option.to_dict()], "asked_at": str},
   "blocks": {part: {"date": "YYYY-MM-DD", "event_id": str}},
   "merged": {part: {"date": str, "event_id": str, "filled": {field: previous_value},
                     "disagree": None | {"field": str, "location_value": str}}},
   "arrival_item": str | None, "confirmed": bool}
  ```
- **`outbox.py`:** `Outbox(path: Path)`, thread-safe and persisted after every change. Methods:
  - `add(kind: str, receipt: dict, trip_id: str | None) -> str` (id 8 hex);
  - `serve() -> list[dict]`: returns the unacked items as `{id, kind, receipt}`, adds 1 to each one's `served`, and drops (logged at WARNING, no content) any already served 3 times;
  - `ack(id) -> bool`;
  - `find(trip_id, kind) -> dict | None`.
- **`scripts/location_rebuild.py`:** `[--from D --to D]`. It replays raw files through a fresh `Tracker` (home from `find_home` over the range) and writes `data/locations/derived/{date}.json` as `{"trips": [Trip.to_dict()], "stays": [...]}`. It writes nothing else and makes no model calls.

- [ ] **Step 1: Write the failing tests**

```python
def test_home_is_where_most_nights_are():
    # 5 nights at A, 2 at B (Alex's), 1 night of scattered fixes
    assert haversine_m(*find_home(fixes, TZ, today), *A) < 10

def test_no_home_with_fewer_than_three_nights():
    assert find_home(two_nights, TZ, today) is None

def test_questions_on_uses_the_logical_day(tmp_path):
    # asked_at 2026-11-13T02:00 counts for 2026-11-12 with boundary 5
    assert recs.questions_on(dt.date(2026, 11, 12), TZ, 5) == 1

def test_outbox_serves_until_acked_then_drops_after_three(tmp_path):
    ob = Outbox(tmp_path / "outbox.json"); i = ob.add("question", {"text": "q"}, "1a2b3c4d")
    assert [x["id"] for x in ob.serve()] == [i]
    assert ob.ack(i) is True and ob.serve() == []
    j = ob.add("notice", {"text": "n"}, None); ob.serve(); ob.serve(); ob.serve()
    assert ob.serve() == []

def test_outbox_survives_a_restart(tmp_path):
    Outbox(tmp_path / "o.json").add("notice", {"text": "n"}, None)
    assert len(Outbox(tmp_path / "o.json").serve()) == 1
```

- [ ] **Step 2: Run, expect failure (ImportError)**

Run: `python -m pytest tests/test_location_home.py tests/test_location_records.py tests/test_location_outbox.py -q`

- [ ] **Step 3: Implement the three modules and the script**

- [ ] **Step 4: Run, expect pass.** Then run the script on the real data:

```bash
python scripts/location_rebuild.py --from 2026-11-05 --to 2026-11-12
```

Expected:
- `derived/` files exist;
- 9 Nov contains a trip around 20:29 with `max_from_home_m` of about 48;
- 8 Nov evening has `start_precision: "before"`.

Compare the trip count per day against spec §2.1, and write any mismatch in the ledger.

- [ ] **Step 5: Commit**

`git commit -m "feat(location): home finder, trip records, outbox, rebuild script"`

---

### Task 5: Seed the labels

**Files:**
- Create: `apps/vault-server/scripts/location_seed_labels.py`
- Output (gitignored): `data/eval/location/{date}.json` for 2026-11-05 … 2026-11-10

**Interfaces:**
- Produces the labels format that Tasks 6 and 16 read:

  ```json
  {"date": "2026-11-07", "trips": [{
     "start": "2026-11-07T07:54:00+02:00", "end": "2026-11-07T09:50:00+02:00",
     "purpose": "Coffee at Gan Meir", "destination": "Gan Meir",
     "blocks": [{"name": "Walk to Gan Meir", "start": "…", "end": "…"},
                {"name": "Café at Gan Meir", "start": "…", "end": "…"},
                {"name": "Walk home", "start": "…", "end": "…"}],
     "features": {"origin": "home", "mode": "walk", "distance_m": 0, "max_from_home_m": 1750, "stops": 1},
     "evidence": "logged café until 09:13; you described it"}]}
  ```

- The script holds the 17 rows of spec §2.1 as a literal table, including 9 Nov 20:29–20:32 "Convenience store", destination "Convenience store".
  - The purpose is the "Label" column. A row with several labels is a trip that gets you somewhere: purpose = the destination activity, `destination` = the place, and `blocks` = each label.
  - A single "Dog walk" or "Dog walk (long)" row is purpose "Dog walk", destination null, with one block.
  - It fills `features` by matching each row to the trip in `derived/{date}.json` that overlaps it most, so Task 4's rebuild must have run.
  - A row with no matching trip is written with `features: null` and printed as `MISSED`.

- [ ] **Step 1: Write the failing test** — `tests/test_location_seed_labels.py`:

```python
def test_label_rows_cover_the_spec_table():
    from scripts.location_seed_labels import ROWS
    assert len(ROWS) == 17
    assert any(r["purpose"] == "Convenience store" and r["start"].endswith("20:29") for r in ROWS)
    assert all(not r["destination"] for r in ROWS if r["purpose"] == "Dog walk")
```

(If `scripts` isn't importable as a package in tests, follow the import pattern `tests/test_location_report.py` already uses for `location_spike_report.py`.)

- [ ] **Step 2: Run, expect failure** (`ModuleNotFoundError`)

Run: `python -m pytest tests/test_location_seed_labels.py -q`

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the test (pass), then the script**

Run: `python scripts/location_seed_labels.py`

Expected: 6 files written. Any `MISSED` row goes in the ledger as a finding for Task 3's thresholds; this is not a failure of this task.

- [ ] **Step 5: Commit** the script and test only (`data/` is gitignored).

`git commit -m "feat(location): seed labels from the spec's table"`

---

### Task 6: History scoring

**Files:**
- Create: `src/services/location/history.py`
- Test: `tests/test_location_history.py`

**Interfaces:**
- Consumes: the labels format (Task 5), `TripRecords` (Task 4), and `EventsService.get_events`.
- Produces:

  ```python
  @dataclass(frozen=True)
  class ConfirmedTrip:
      purpose: str; destination: str | None
      start: dt.datetime; duration_s: float
      origin: str; mode: str | None; distance_m: float; max_from_home_m: float
      stop_places: tuple[str, ...]

  @dataclass(frozen=True)
  class HistoryCandidate:
      id: str                 # "h1", "h2"… in rank order
      purpose: str; destination: str | None
      score: float            # 0..1
      count: int
      evidence: str           # "Dog walk: 14 confirmed, usually 07–10 and 19–21, last 11 h ago, on foot, from home"

  MIN_CONFIRMED = 3
  def load_confirmed(labels_dir: Path, records: TripRecords, events, tz: str, now: dt.datetime, days: int = 60) -> list[ConfirmedTrip]
  def score_history(trip: Trip, confirmed: list[ConfirmedTrip], now: dt.datetime, tz: str, stop: Stop | None = None) -> list[HistoryCandidate]
  ```

- **`load_confirmed`** returns labels plus the trip records that are confirmed. A record is confirmed when `rec["confirmed"]` is true, or any of its blocks or merged blocks is stored `state: "approved"`. The purpose is `rec["purpose"]["name"]`.
- **`score_history`:**
  - Only purposes with ≥ 3 confirmed trips are scored.
  - Features, each 0 or 1, averaged over those that apply:
    - origin equal;
    - start hour within ±90 min (circular) of any confirmed start's hour;
    - hours since the last occurrence within ±40 % of the median spacing (needs ≥ 2 occurrences);
    - mode equal;
    - `max_from_home_m` so far ≤ 1.5 × the purpose's max;
    - `stop.place_id` in the purpose's `stop_places`, or its destination, when `stop` is given.
  - Keep scores ≥ 0.4, best first, at most 5. The exact formula is the builder's (spec §11), and the tests pin only ordering and the cutoffs.

- [ ] **Step 1: Write the failing tests**

```python
def test_needs_three_confirmed():
    assert score_history(trip, two_dog_walks, now, TZ) == []

def test_morning_loop_ranks_the_twice_daily_purpose_first():
    # 14 "Dog walk" at 07–10 and 19–21 from home on foot; 4 "Band practice" at 11:25 to a place
    top = score_history(trip_leaving_home_0815_walk, confirmed, now_0820, TZ)[0]
    assert top.purpose == "Dog walk" and top.id == "h1" and "14 confirmed" in top.evidence

def test_spacing_counts():
    # last Dog walk 1 h ago, median spacing 11.5 h → lower score than when last was 11 h ago
    assert score(last_1h) < score(last_11h)

def test_evidence_has_no_coordinates():
    assert "32." not in c.evidence and "34." not in c.evidence

def test_approved_block_confirms_a_record(tmp_path):
    # record with blocks {"trip": {date, event_id}} whose event has state "approved"
    assert [c.purpose for c in load_confirmed(...)] == ["Run"]
```

- [ ] **Step 2: Run, expect failure (ImportError)**

Run: `python -m pytest tests/test_location_history.py -q`

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run, expect pass**

- [ ] **Step 5: Commit**

`git commit -m "feat(location): score confirmed history for a trip"`

---

### Task 7: Context lines

**Files:**
- Create: `src/services/location/context.py`
- Test: `tests/test_location_context.py`

**Interfaces:**
- Produces:

  ```python
  @dataclass(frozen=True)
  class ContextLine:
      id: str      # "c1", "c2"…
      kind: str    # "conversation" | "todo" | "task" | "block" | "habit"
      text: str    # ≤ 300 chars, quoted as found

  def gather_context(now: dt.datetime, *, vault, events, conversations_dir: Path, chat_id: int | None, tz: str) -> list[ContextLine]
  ```

- Lines are gathered by time only, and never interpreted:
  - **Conversation:** messages from `conversations_dir/{date}/{chat_id}.md` for today and yesterday whose `### HH:MM [role]` stamp is within 24 h of `now`. The text is `"[yesterday 21:40] user: going to Alex's tonight"`. Both roles are included, newest 60 kept.
  - **Todo:** today's open todos via `daily_tasks.parse_all_todos`.
  - **Task:** active tasks via `vault.list_active_tasks()` (name and due date).
  - **Block:** today's events from `events.get_events(today)`, as name, `HH:MM–HH:MM` and location name. Blocks with a `trip` field are skipped, since they are Mazkir's own guesses.
  - **Habit:** active habits not completed today (name and `daily_target`).
- `chat_id=None` means no conversation lines. Every source failure is logged and skipped.

- [ ] **Step 1: Write the failing tests**

```python
def test_conversation_window_is_24_hours(tmp_path):
    # yesterday 09:00 (excluded at now = today 10:00), yesterday 21:40 (included)
    assert [l.text for l in lines if l.kind == "conversation"] == ["[yesterday 21:40] user: going to Alex's tonight"]

def test_ids_are_sequential_and_unique():
    assert [l.id for l in lines] == [f"c{i}" for i in range(1, len(lines) + 1)]

def test_trip_blocks_are_not_context():
    # an event with "trip": {...} is not in lines; a user block is
    ...

def test_a_failing_source_is_skipped(caplog):
    vault.list_active_tasks.side_effect = OSError
    assert any(l.kind == "conversation" for l in gather_context(...))
```

- [ ] **Step 2: Run, expect failure. Step 3: implement. Step 4: run, expect pass**

Run: `python -m pytest tests/test_location_context.py -q`

- [ ] **Step 5: Commit**

`git commit -m "feat(location): gather context lines by time"`

---

### Task 8: The guess (the one model call)

**Files:**
- Create: `src/services/location/guess.py`
- Test: `tests/test_location_guess.py`

**Interfaces:**
- Consumes: `HistoryCandidate` (Task 6), `ContextLine` (Task 7), `Trip` / `Stop` (Task 3), and `ClaudeService.create_fast_parse(system=, content=, schema=, model=, timeout_s=)`.
- Produces:

  ```python
  @dataclass(frozen=True)
  class Guess:
      purpose: str; likelihood: str            # "strong" | "plausible" | "unlikely"
      history_id: str | None; cites: tuple[str, ...]
      destination: str | None

  GUESS_SCHEMA: dict   # {"guesses": [{"purpose","likelihood","history_id","cites","destination"}]}, all required, additionalProperties false; nullable via ["string","null"]
  def describe_trip(trip: Trip, stop: Stop | None, places: list[Place], now: dt.datetime, tz: str) -> str
  def build_content(subject: str, trip_text: str, history: list[HistoryCandidate], lines: list[ContextLine]) -> str
  def guess(subject: str, trip_text: str, history, lines, claude, *, model: str, timeout_s: float) -> tuple[list[Guess], list[dict]]
  ```

  `guess` returns `(kept, dropped)`, where each dropped entry is `{purpose, reason}` for the decision log.
- **`subject`** is `"stop"` ("what is this stop?") or `"trip"` ("what was the whole trip?").
- **`describe_trip`** writes only times, durations, distances from home, mode, stop count and known place names. Example: `"Left home 10:16, on foot, now 700 m from home. Stopped since 10:24 (4 min) at an unknown place 700 m from home. 1 stop so far."`
- **The system prompt** states:
  - the subject;
  - that a history purpose is cited by its id;
  - that a new purpose must list the context ids it comes from;
  - that `destination` is the place the trip went to and is null when the moving itself was the activity;
  - at most 3 guesses.
- **Validation:**
  - an unknown `history_id` is dropped (`"unknown history id"`);
  - a history guess takes its candidate's `purpose`, and its `destination` unless the model gave one;
  - with no history id, `cites` must be non-empty and every id must exist (`"cites nothing"` / `"cites a line that does not exist"`);
  - the first 3 are kept.
- **Any exception, timeout, `max_tokens` stop or non-JSON reply** gives `([], [{"purpose": None, "reason": "<error>"}])` and is logged at WARNING. It never raises.

- [ ] **Step 1: Write the failing tests** (a fake `claude` whose `create_fast_parse` returns an object with `.content=[SimpleNamespace(type="text", text=json.dumps(...))]` and `stop_reason="end_turn"`)

```python
def test_history_guess_takes_the_candidate_purpose():
    kept, _ = guess("trip", "…", [h1_dog_walk], [], fake({"guesses": [g(purpose="walk", history_id="h1")]}), **KW)
    assert kept[0].purpose == "Dog walk"

def test_new_purpose_must_cite_a_real_line():
    kept, dropped = guess("stop", "…", [], [ContextLine("c1", "conversation", "…Dana's for dinner")],
                          fake({"guesses": [g("Dinner at Dana's", cites=["c1"]), g("Gym", cites=[]), g("Bar", cites=["c9"])]}), **KW)
    assert [k.purpose for k in kept] == ["Dinner at Dana's"]
    assert {d["reason"] for d in dropped} == {"cites nothing", "cites a line that does not exist"}

def test_failure_is_no_guess():
    assert guess("trip", "…", [], [], raising_fake(TimeoutError()), **KW)[0] == []

def test_content_has_no_coordinates():
    trip = trip_with_stop_at(32.0853, 34.7818)
    content = build_content("stop", describe_trip(trip, trip.stops[0], [], now, TZ), [], [])
    assert "32.08" not in content and "34.78" not in content
```

- [ ] **Step 2: Run, expect failure. Step 3: implement. Step 4: run, expect pass**

Run: `python -m pytest tests/test_location_guess.py -q`

- [ ] **Step 5: Commit**

`git commit -m "feat(location): one structured Haiku call guesses the purpose, citations checked"`

---

### Task 9: Decide

**Files:**
- Create: `src/services/location/decide.py`
- Test: `tests/test_location_decide.py`

**Interfaces:**
- Produces:

  ```python
  @dataclass(frozen=True)
  class Option:
      name: str; destination: str | None
      def to_dict(self) -> dict: ...
      @classmethod
      def from_dict(cls, d) -> "Option": ...

  @dataclass(frozen=True)
  class Decision:
      action: str                  # "name" | "ask" | "quiet"
      name: str | None; destination: str | None
      options: tuple[Option, ...]  # ≤ 3, for "ask"
      reason: str

  QUESTION_CAP = 6
  def decide(guesses: list[Guess], history: list[HistoryCandidate], *, known_place: Place | None,
             may_ask: bool, questions_today: int) -> Decision
  ```

- **The rules, in order (§5.4):**
  1. **`known_place` of kind `"pause"`** → `quiet`, `"pause spot"`.
  2. **One `strong` guess and no other `strong` or `plausible`** → `name`.
  3. **`known_place` (not pause) and no rule-2 guess** → `name`, with `name = known_place.name` and `destination = known_place.name`. A known place is never asked about.
  4. **Not `may_ask`** (a stop already left, an already asked one, or a re-decision) → `quiet`.
  5. **`questions_today >= 6`** → `quiet`, `"daily cap"`.
  6. **2–3 `strong` or `plausible` guesses** → `ask`, with them as options in the order given.
  7. **None** → `ask`, with the top 3 history candidates as options (possibly empty).

- [ ] **Step 1: Write the failing tests** — one per rule, named `test_rule_<n>_…`, asserting `action`, `name` and `[o.name for o in options]`. Add one more test: with two strong guesses, the action is `ask`, not `name`.

- [ ] **Step 2: Run, expect failure. Step 3: implement. Step 4: run, expect pass**

Run: `python -m pytest tests/test_location_decide.py -q`

- [ ] **Step 5: Commit**

`git commit -m "feat(location): decide whether to name or ask"`

---

### Task 10: The writer

**Files:**
- Create: `src/services/location/writer.py`
- Test: `tests/test_location_writer.py`

**Interfaces:**
- Consumes: the record shape (Task 4), `AgentService.run_tool` (via `TripDeps.run_tool: Callable[[str, dict], dict]`), `EventsService` (`get_events`, `delete_event`, `update_event`, `lock`), and `fast_lane.actions.STATED`.
- Produces:

  ```python
  @dataclass(frozen=True)
  class BlockSpec:
      part: str                    # "trip" | "leg:1"… | "stop:s1"…
      name: str
      start: dt.datetime; end: dt.datetime | None
      start_precision: str; end_precision: str | None   # "location" | "before"
      place_id: str | None; place_text: str | None

  LEG_FOLD_S = 120
  MERGE_WINDOW = dt.timedelta(minutes=15)
  def plan_blocks(rec: dict, places: list[Place]) -> list[BlockSpec]
  def apply_blocks(rec: dict, specs: list[BlockSpec], *, run_tool, events, tz: str) -> dict   # returns the updated rec
  ```

- **`plan_blocks` (§4.2, §4.3):**
  - **Named stops** are stops with `status == "named"`.
  - **Activity row:** `rec["purpose"]` is None, or has `destination` None.
    - One `trip` block `[left_at, back_at]`.
    - Its name is `purpose.name`. Without a purpose it is `"Trip"` while ongoing and `"Trip {distance}"` when closed (distance formatted `"1.1 km"` / `"350 m"`).
    - Plus a `stop:sX` block per named stop, `[stop.start, stop.end]`.
  - **Travel row:** the purpose has a destination.
    - The boundaries are the named stops. Legs run between consecutive boundaries (`left_at` → first named stop's start; each named stop's end → the next named stop's start or `back_at`).
    - A leg is named `"{Mode} to {stop's place name or stop name}"`, or `"{Mode} home"` for the last leg, where Mode is `Walk` / `Ride` / `Drive`. The leg's mode is that of its longest underlying `Leg`.
    - A leg shorter than 120 s folds into the block it leads to: the stop's start moves back to the leg's start. A final leg home that short extends the last stop's end instead.
    - Unnamed stops never split a leg.
  - **Precision:** the start precision is `trip.start_precision` for a block starting at `left_at`, otherwise `"location"`. End precision likewise from `end_precision`.
  - No activity name appears in this code.
- **`apply_blocks`**, for each spec:
  1. **Find a user block to merge into.** A user block is an event in the spec's date files that:
     - has no `trip` field;
     - has `source` `manual` or `photo`;
     - is not `proposed`;
     - is not stored `dismissed`;
     - and either overlaps the spec interval (an open end counts as now) or starts within 15 min of the spec's start.

     It must not already be merged into another part. Pick the one with the most overlap.
     - **Found:** if the part has its own trip-owned block that is still pending, delete it (`events.delete_event`; a proposal has no Google entry). Then merge:
       - fill `end_time` when missing, or when its `end_precision` is set and not in `STATED`; `start_time` likewise;
       - write through `run_tool("update_event", {..., "_fast": {"inferred": True, "fields": {"trip": {...}, "end_precision": "location"}}})`;
       - record the previous values in `rec["merged"][part]["filled"]`;
       - when a stated time differs from the spec by > 15 min, write `disagree` and change nothing.

       The user's name is never touched.
  2. **Else, if `rec["blocks"][part]` exists:** `update_event` with `_fast.inferred`, for whichever of name, start and end differ. It skips any field present in that event's `user_set` (Review Focus 4).
     - If the spec now crosses midnight while the stored block does not, and the block is still pending, delete it and recreate it (step 3), so `create_event` splits it.
  3. **Else:** `run_tool("create_event", {"name", "date", "start_time", "end_time", "proposed": True, "_fast": {"fields": {"trip": {"id", "part"}, "start_precision", "end_precision", "place_id"|"place_text"}}})`. Store `{date, event_id}` in `rec["blocks"][part]`.
- **Parts no longer in the plan** (e.g. the trip block when a trip turns out to be travel) are deleted if still pending, or else left alone and kept in the record.
- **Times** are written as local naive `"%Y-%m-%dT%H:%M:%S"` in `tz`.

- [ ] **Step 1: Write the failing tests** (real `EventsService` on `tmp_path`; `run_tool` from a real `AgentService` built as in `test_agent_service.py`, or a thin fake that calls the same `EventsService` methods — prefer real)

```python
def test_unnamed_stops_get_no_block():
    rec = record(loop_with_stops(3), purpose={"name": "Dog walk", "destination": None}, stops=all_unnamed)
    assert [s.part for s in plan_blocks(rec, [])] == ["trip"]

def test_named_stop_inside_an_activity_overlaps_it():
    specs = plan_blocks(rec_walk_with_named_coffee, [])
    assert [s.part for s in specs] == ["trip", "stop:s2"] and specs[0].start < specs[1].start < specs[1].end < specs[0].end

def test_travel_trip_becomes_legs_and_stops():           # 7 Nov morning
    assert [s.name for s in plan_blocks(rec_gan_meir, places)] == ["Walk to Gan Meir", "Café at Gan Meir", "Walk home"]

def test_short_leg_folds_into_the_shop():                # 9 Nov 20:29
    assert [s.name for s in plan_blocks(rec_shop, [])] == ["Convenience store"]

def test_unknown_closed_trip_is_named_by_distance():
    assert plan_blocks(rec_unknown_1100m, [])[0].name == "Trip 1.1 km"

def test_trip_block_is_a_pending_proposal(tmp_path):
    rec = apply_blocks(rec, plan_blocks(rec, []), run_tool=rt, events=ev, tz=TZ)
    e = ev.get_events("2026-11-09")[0]
    assert e["proposed"] is True and e["trip"]["part"] == "trip" and resolve_state(e) == "pending"

def test_apply_twice_writes_once(tmp_path):
    apply(...); apply(...); assert len(ev.get_events("2026-11-09")) == 1

def test_completes_your_block_and_keeps_your_name(tmp_path):     # "Dog walk 10:24" with no end
    ev.create_event(date=D, name="Dog walk", start_time=f"{D}T10:24:00")
    apply(rec_walk_1024_1038_guessed_as("Walk"))
    [e] = ev.get_events(D)
    assert e["name"] == "Dog walk" and e["end_time"].endswith("10:38:00") and e["start_time"].endswith("10:24:00")

def test_message_time_inferred_start_is_replaced(tmp_path):
    # user block start_precision "inferred" at 10:35; trip left at 10:24 → start becomes 10:24

def test_big_disagreement_is_reported_not_written(tmp_path):
    # user said end 10:00 (no precision = stated); location says 10:38
    assert rec["merged"]["trip"]["disagree"]["field"] == "end_time" and e["end_time"].endswith("10:00:00")

def test_your_later_block_absorbs_the_trip_block(tmp_path):     # reverse direction
    apply(rec)                                 # trip block written
    ev.create_event(date=D, name="Dog walk", start_time=f"{D}T10:25:00")
    apply(rec)
    assert [e["name"] for e in ev.get_events(D)] == ["Dog walk"]

def test_pinned_fields_are_not_overwritten(tmp_path):            # Review Focus 4
    apply(rec); ev.update_event(date=D, event_id=eid, updates={"start_time": f"{D}T10:20:00"}, user_set_fields=["start_time"])
    apply(rec_with_new_end)
    e = ev.get_events(D)[0]
    assert e["start_time"].endswith("10:20:00") and e["end_time"].endswith(new_end)

def test_cross_midnight_block_is_split(tmp_path):
    # stop 20:10 → 07:54 next day (Alex's), named → two fragments sharing logical_id
```

- [ ] **Step 2: Run, expect failure. Step 3: implement. Step 4: run, expect pass**

Run: `python -m pytest tests/test_location_writer.py -q`

- [ ] **Step 5: Commit**

`git commit -m "feat(location): trips become proposed blocks, merged with yours"`

---

### Task 11: Messages

**Files:**
- Create: `src/services/location/messages.py`
- Test: `tests/test_location_messages.py`

**Interfaces:**
- Produces dicts in the shape of the shared `Receipt` type: `{turn_id, lines: [{id, glyph, when, text, detail, sync, reason, status, buttons: [{label, data}]}], undo: None, open_question, text}`.

  ```python
  TAP_PREFIX = "trip"
  def question_receipt(rec: dict, stop_id: str | None, options: list[Option], now: dt.datetime, tz: str) -> dict
  def arrival_receipt(rec: dict, events, tz: str) -> dict
  def notice_receipt(text: str) -> dict
  ```

- **Callback data**, ≤ 64 bytes: `trip:<trip_id>:<line>:<action>`.
  - `<line>` is a stop id (`s1`), `trip` for a trip question, a numeric arrival line, or `all`.
  - `<action>` is one of `a0`…`a2` (the option index), `p` (just a pause), `t` (type it), `ok`, `no`.
  - ✎ is the existing `block:edit:<date>:<event_id>`.
- **Question at a stop (§6.2):**
  - The text reads `"📍 You've been here since 10:24 — 700 m from home, a new place. What's this?"`. Use the place name instead of "a new place" when known.
  - One line carries the buttons: the options, then `Just a pause` (stop questions only), then `✎ Something else`. Labels are cut to 32 characters.
  - `open_question` is the question text plus `" [trip <id> · stop <sid>]"`, or `" [trip <id>]"` for a trip question.
- **Arrival (§6.3):**
  - One line per part in `rec["blocks"]` and `rec["merged"]`, in time order.
  - The glyph comes from the block's current `resolve_state`: `●` pending, `✓` approved, `✕` dismissed. `when` is `"07:20–10:10"`.
  - `detail` is duration, distance and stop count on the `trip` part (`"2 h 50 min, 3.4 km, 3 stops"`).
  - `reason` is `"end from location"` / `"start from location"` for a merged part, or `"location says back 10:52"` for a disagreement.
  - Buttons are `✓` (`trip:<id>:<n>:ok`) and `✎` (`block:edit:…`), on pending lines and on merged lines not yet confirmed.
  - A last line with empty text carries `✓ All` (`trip:<id>:all:ok`) and `✕ Not right` (`trip:<id>:all:no`). Its `detail` is `"trip <id>"`, so a Telegram reply to the message reaches the agent with the trip id through `repliedToText` (spec §6.4). Button data never reaches `repliedToText`, which is why the id is in the text.
  - With an open trip question, an extra first line asks `"🚶 Trip 18:02–18:40, 1.1 km — what was it?"` with option buttons, and `open_question` is set.
- **`text`** is the plain-line fallback.

- [ ] **Step 1: Write the failing tests**

```python
def test_every_callback_fits_64_bytes():
    r = question_receipt(rec, "s1", [Option("A" * 80, None)] * 3, now, TZ)
    assert all(len(b["data"].encode()) <= 64 for l in r["lines"] for b in l["buttons"])
    assert all(len(b["label"]) <= 32 for l in r["lines"] for b in l["buttons"])

def test_stop_question_offers_pause_and_type():
    labels = [b["label"] for b in question_receipt(...)["lines"][0]["buttons"]]
    assert labels[-2:] == ["Just a pause", "✎ Something else"]
    assert question_receipt(...)["open_question"].endswith("[trip 1a2b3c4d · stop s1]")

def test_arrival_lines_follow_block_state(tmp_path):
    # one approved, one pending → glyphs ["✓", "●"], only the pending line has ✓/✎

def test_receipt_text_has_no_coordinates():
    assert "32.08" not in json.dumps(arrival_receipt(rec, ev, TZ))
```

- [ ] **Step 2: Run, expect failure. Step 3: implement. Step 4: run, expect pass**

Run: `python -m pytest tests/test_location_messages.py -q`

- [ ] **Step 5: Commit**

`git commit -m "feat(location): trip questions and arrival receipts"`

---

### Task 12: Pipeline, runtime, routes and the trip clock

**Files:**
- Create: `src/services/location/pipeline.py`, `runtime.py`
- Modify:
  - `src/api/routes/locations.py`;
  - `src/main.py` (lifespan: construct the runtime when `location_awareness == "on"`, start a `_location_clock_loop` next to `_coding_tasks_poll_loop`, and cancel it on shutdown);
  - `src/logging_setup.py` (`configure_location_trips_log` / `emit_location_trips`, mirroring `configure_fast_lane_log`, file `location-trips.jsonl`).
- Test: `tests/test_location_pipeline.py`, `tests/test_location_runtime.py`, `tests/test_locations_route.py` (extend)

**Interfaces:**
- **`pipeline.py`:**

  ```python
  @dataclass
  class TripDeps:
      records: TripRecords; outbox: Outbox; places_path: Path; labels_dir: Path
      run_tool: Callable[[str, dict], dict]; events: Any; vault: Any; claude: Any
      conversations_dir: Path; tz: str; model: str; timeout_s: float; boundary_hour: int
      chat_id: Callable[[], int | None]; now: Callable[[], dt.datetime]
      log: Callable[[dict], None]
  def handle_event(ev: TrackerEvent, deps: TripDeps) -> None
  def apply_answer(trip_id: str, stop_id: str | None, purpose: str | None, place: str | None,
                   deps: TripDeps, *, pause: bool = False) -> dict      # returns the updated record
  ```

- **`handle_event`.** It loads or creates the record, stores `ev.trip` in it, and dispatches on the kind:
  - **LEFT:** set `trip`, then plan and apply blocks (an ongoing `"Trip"`).
  - **STOPPED:** call `nearest`. A pause spot sets the stop to `unnamed` with no model call. Otherwise gather candidates (subject `stop`, with the stop), guess, and `decide` with `may_ask=True` and `questions_today` from `records`.
    - `name` → the stop becomes `named` with that name and place. For a stop, a `destination` from the guess names the place.
    - `ask` → `asked`, with `options` and `asked_at`, and `outbox.add("question", question_receipt(...))`.
    - `quiet` → `unnamed`.
  - **LEFT_STOP:** for a stop still `asked` or `unnamed` and never answered, re-guess with `may_ask=False`. Only `name` changes it.
  - **BACK_HOME:**
    - If `purpose` is None, guess the trip (subject `trip`) and decide with `may_ask=True`. `name` sets `purpose`; `ask` sets `trip_question`; `quiet` leaves it unnamed.
    - Then `closed = True`, plan and apply blocks, and add the arrival receipt to the outbox, or refresh it in place if `arrival_item` is still unacked.
  - **SHARE_ENDED:** close the open stop; the record is otherwise unchanged.
  - After every event, plan and apply blocks, save the record, and log one decision line: `{event, trip_id, stop_id, history: [{id, purpose, score}], guesses, dropped, decision: {action, name, options, reason}, blocks: rec["blocks"]}`.
- **`apply_answer`:**
  - **`pause=True`** → `add_pause_spot` at the stop's centre, and the stop becomes `unnamed`.
  - **A stop answer** → `named` with name and place. When the place is given, or the chosen option has a destination, call `learn_place`. A conflict returns `{"conflict": place_name}` in the result for the reply.
  - **A trip answer** → `purpose = {name, destination, source: "answer"}`.
  - Then `confirmed = True`, re-plan and apply, re-render any unacked arrival item, and save.
  - A late answer re-sends nothing new.
- **`runtime.py`:**

  ```python
  class LocationRuntime:
      def __init__(self, root: Path, deps: TripDeps, *, synchronous: bool = False)
      def feed(self, point: dict) -> list[dict]       # tracker under a lock, persist state.json, queue events, return outbox.serve()
      def tick(self, now: dt.datetime) -> list[dict]  # tracker.tick → SHARE_ENDED notice; home finding; returns notices to push
      def ack(self, item_id: str) -> bool
      def tap(self, trip_id: str, line: str, action: str) -> dict   # answer actions; returns {receipt, toast, open_question, approvals: [(date, event_id, state)]}
      def answer(self, trip_id, stop_id, purpose, place) -> dict    # for the agent tool
      def stop(self) -> None
  def get_runtime() -> LocationRuntime | None
  def set_runtime(rt: LocationRuntime | None) -> None
  ```

- **`feed`:**
  - Only `kind` `live` / `live_start` reach the tracker; a `check_in` is stored by L0 only.
  - `point["chat_id"]`, when present, is persisted in `state.json` as the share's chat.
  - Events are appended to the record's `inbox` before they are queued. The worker removes each one after `handle_event` returns.
  - The worker is one `threading.Thread` with a `queue.Queue`; `synchronous=True` handles events inline (for tests).
  - At construction, every record's non-empty `inbox` is re-queued (Review Focus 3). `handle_event` is idempotent per event, because the record's stop statuses and outbox lookups gate every add.
- **`tick`:**
  - **Home.** If the tracker has no home, run `find_home` over the last 14 days of raw files. On success, `set_home`, `places.set_home`, and a notice: "I found home — trips from here will fill your day." The tracker gets the new home.
  - **Share ended.** On `SHARE_ENDED`, the notice reads "Location sharing stopped — share again to keep your day filling in", and the runtime returns it for the clock to push.
- **`routes/locations.py`:**
  - `LocationPoint` gains `chat_id: int | None = None`.
  - `ingest_point`: after `append_point`, if `settings.location_awareness == "on"` and the runtime exists, call `notify = runtime.feed(record)`. Any exception is logged at ERROR, without coordinates, and leaves `notify = []`. Return `{"ok": True, "notify": notify}`.
  - `POST /locations/outbox/{item_id}/ack` → `{"ok": bool}`.
  - `POST /locations/trips/{trip_id}/tap` with body `{line: str, action: str}` (extra forbid):
    - an async route; it runs `runtime.tap` in `asyncio.to_thread`;
    - then for each approval it does `await set_event_state(date_obj, event_id, SetStateBody(state=...))`, as `daily._set_state_for_approve_all` does;
    - a merged user block takes `ok` as `events.update_event(... updates={"end_precision": "exact"})` and `no` as restoring `filled`;
    - it re-renders the arrival receipt and returns `{receipt, toast, open_question}`. The toast names a habit tick when `set_event_state` returned one (`"✓ Dog Walk · +5 tokens · streak 3"`).
  - All three endpoints return 404 unless trips are on. The `trip_id` path param must match `^[0-9a-f]{8}$` (pydantic/Path pattern), because it builds a file path.
- **`main.py`:**
  - Construct `TripDeps` from the app's services: `run_tool=agent.run_tool` when the agent exists (otherwise the runtime is not started and a WARNING says so), `conversations_dir = settings.vault_path / "00-system" / "conversations"`, `labels_dir = repo/data/eval/location`.
  - Then `set_runtime(LocationRuntime(...))`.
  - `_location_clock_loop` runs `runtime.tick` every 60 s in `asyncio.to_thread`, and pushes returned notices with `TelegramNotifier.send_message(chat_id, receipt["text"])`, then acks them.
- **Spans:** `location.trip.decide`, with attributes `event`, `action` and `n_guesses` only.

- [ ] **Step 1: Write the failing tests**

```python
# test_location_pipeline.py — real records/outbox/events on tmp_path, fake claude, fake run_tool → real EventsService
def test_routine_loop_is_named_silently_and_gets_an_arrival_message():
    # history: 14 confirmed "Dog walk"; model returns one strong h1
    run(LEFT, STOPPED s1, LEFT_STOP, BACK_HOME)
    kinds = [i["kind"] for i in deps.outbox.serve()]
    assert kinds == ["arrival"] and rec["purpose"]["name"] == "Dog walk"

def test_unknown_stop_asks_once():
    run(LEFT, STOPPED s1); run(STOPPED s1)          # redelivered event
    assert [i["kind"] for i in deps.outbox.serve()] == ["question"]

def test_stop_already_left_is_not_asked():
    # STOPPED handled with cap reached → unnamed; LEFT_STOP with no strong guess → still no question

def test_daily_cap():
    # 6 asked_at stamps today → STOPPED with no guess → no question, status unnamed

def test_pause_answer_makes_a_pause_spot_and_no_block():
    apply_answer(tid, "s1", None, None, deps, pause=True)
    assert nearest(*stop_centre, load_places(deps.places_path)).kind == "pause"
    assert all(p != "stop:s1" for p in rec["blocks"])

def test_decision_log_has_no_coordinates():
    assert not re.search(r"\b3[24]\.\d{3}", json.dumps(logged))

# test_location_runtime.py
def test_inbox_survives_a_restart(tmp_path):                         # Review Focus 3
    rt = LocationRuntime(root, deps_that_crash_on_handle, synchronous=True); rt.feed(point_that_emits_LEFT)
    rt2 = LocationRuntime(root, good_deps, synchronous=True)
    assert records.get(tid)["inbox"] == [] and records.get(tid)["blocks"]

def test_check_ins_do_not_reach_the_tracker(tmp_path): ...
def test_share_stopped_notice_once(tmp_path): ...

# test_locations_route.py
def test_trips_off_keeps_the_l0_response(client):      # {"ok": True} plus "notify": [] or exactly L0's body — pick one and assert it
def test_ingest_returns_notify_when_on(client, monkeypatch): ...
def test_tracker_crash_still_returns_200(client, monkeypatch): ...
def test_tap_rejects_a_bad_trip_id(client): assert client.post("/locations/trips/../x/tap", json=...).status_code in (404, 422)
def test_ok_tap_approves_through_set_event_state(client, monkeypatch): ...
```

**Ruling, for the off-mode test:** with trips off, the route returns `{"ok": True}` exactly as L0 does, and `notify` is added only when on. That keeps "off changes nothing" literally true.

- [ ] **Step 2: Run, expect failure**

Run: `python -m pytest tests/test_location_pipeline.py tests/test_location_runtime.py tests/test_locations_route.py -q`

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run, expect pass; then the full server suite**

Run: `python -m pytest tests/ -q > "$WS/server-suite.txt" 2>&1; tail -5 "$WS/server-suite.txt"`

Expected: all pass.

- [ ] **Step 5: Commit**

`git commit -m "feat(location): trip worker, runtime, ingest notify, taps and the trip clock"`

---

### Task 13: The agent tool `set_trip_purpose`

**Files:**
- Modify: `src/services/agent_service.py` (`_register_tools`, a new `_tool_set_trip_purpose`), `memory/00-system/skills/time-management.md` (vault repo)
- Test: `tests/test_agent_service.py`

**Interfaces:**
- Consumes: `get_runtime()` and `LocationRuntime.answer` (Task 12).
- Produces: the tool `set_trip_purpose`.
  - Input schema: `trip_id` (string, pattern `^[0-9a-f]{8}$`), `stop_id` (string, optional), `purpose` (string), `place` (string, optional), `_confidence`, `_reasoning`.
  - Risk `write`, `safe_for_parallel: False`.
  - The description tells the agent:
    - a message answering `[trip … · stop …]` is answered with this tool;
    - so is a reply that corrects what a trip was ("that was a run", "no, I took the bus") to a message showing `trip <id>`;
    - times are corrected with `update_event` on the blocks `list_events` shows for that trip;
    - `place` is filled only when the answer names a place.
- Errors:
  - no runtime → `STATE_CONFLICT` "Location trips are off";
  - unknown trip or stop → `PATH_NOT_FOUND`;
  - a place conflict is returned in `data.conflict`, so the agent can ask "Is this a different Alex's?".

- [ ] **Step 1: Write the failing tests**

```python
def test_set_trip_purpose_is_registered_as_write(agent):
    assert agent.tools["set_trip_purpose"]["risk"] == "write"

def test_set_trip_purpose_answers_the_runtime(agent, monkeypatch):
    rt = MagicMock(); rt.answer.return_value = {"id": "1a2b3c4d", "blocks": {}}
    monkeypatch.setattr("src.services.location.runtime.get_runtime", lambda: rt)
    r = agent.run_tool("set_trip_purpose", {"trip_id": "1a2b3c4d", "stop_id": "s1", "purpose": "Sauna", "_confidence": 0.9})
    assert r["ok"] and rt.answer.call_args.args[:3] == ("1a2b3c4d", "s1", "Sauna")

def test_set_trip_purpose_when_off(agent, monkeypatch):
    monkeypatch.setattr("src.services.location.runtime.get_runtime", lambda: None)
    assert agent.run_tool("set_trip_purpose", {...})["error"]["code"] == "STATE_CONFLICT"
```

Also update whatever test asserts the total tool count.

- [ ] **Step 2: Run, expect failure. Step 3: implement. Step 4: run, expect pass**

Run: `python -m pytest tests/test_agent_service.py tests/test_skill_registry.py -q`

- [ ] **Step 5: The vault skill**

In `memory/00-system/skills/time-management.md`:
- add `set_trip_purpose` under `tools:`;
- add one line to the rules: "A reply to a trip question (it ends `[trip … · stop …]`) is answered with `set_trip_purpose`, not with `create_event`."

Commit in the nested repo:

```bash
cd memory && git add 00-system/skills/time-management.md && git commit -m "skills: time-management answers trip questions"
```

Push only when the PR is opened (Task 16).

- [ ] **Step 6: Commit** the server change.

`git commit -m "feat(location): set_trip_purpose agent tool"`

---

### Task 14: Bot — notify, ack and trip taps

**Files:**
- Create: `packages/shared-types/src/location.ts`, `apps/telegram-bot/src/callbacks/trip.ts`
- Modify:
  - `packages/shared-types/src/index.ts`;
  - `apps/telegram-bot/src/api/client.ts`;
  - `src/conversations/location.ts`;
  - `src/callbacks/index.ts` (register `tripHandlers`, wherever `receiptHandlers` is registered).
- Test: `tests/conversations/location.test.ts`, `tests/callbacks/trip.test.ts`, `tests/api/client.test.ts`

**Interfaces:**
- **Shared types:**

  ```ts
  export interface LocationNotify { id: string; kind: "question" | "arrival" | "notice"; receipt: Receipt }
  export interface LocationIngestResponse { ok: boolean; notify?: LocationNotify[] }
  export interface TripTapResult { receipt: Receipt | null; toast: string | null; open_question: string | null }
  ```

- **Client:**
  - `LocationPoint` gains `chat_id?: number`;
  - `postLocationPoint` returns `LocationIngestResponse`;
  - `ackLocationOutbox(id: string): Promise<{ ok: boolean }>`;
  - `tripTap(tripId: string, line: string, action: string): Promise<TripTapResult>`.
- **`location.ts`:**
  - `toLocationPoint` is unchanged. Each handler sets `point.chat_id = ctx.chat.id`.
  - After a successful post, for each `notify` item, `await sendRich(ctx, buildReceiptRich(item.receipt))`, then `api.ackLocationOutbox(item.id)`. If `item.receipt.open_question` is set, `noteOpenQuestion(chatId, item.receipt.open_question)` comes after the send.
  - A send failure is logged (`location_notify_failed`, with kind and error, no coordinates) and not acked, so the next response carries the item again. An ack failure is logged.
  - The check-in path still calls `next()`.
- **`trip.ts`:**
  - `TRIP_TAP = /^trip:([0-9a-f]{8}):([a-z0-9]{1,6}):(ok|no|p|t|a[0-2])$/`.
  - On a tap, call `api.tripTap`, then answer the callback with `toast`.
  - If `receipt` is set, redraw with `editRich(ctx, buildReceiptRich(receipt))`, taking and restoring a pending open question around the edit exactly as `callbacks/receipt.ts` does.
  - Then, if `open_question` is set, `noteOpenQuestion` after the redraw.
  - A 404 toasts "That trip is gone." Any other failure toasts "❌ That didn't work." and leaves the message alone.

- [ ] **Step 1: Write the failing tests**

```ts
// location.test.ts
it("sends each notify item as a rich message, then acks it", async () => {
  api.postLocationPoint.mockResolvedValue({ ok: true, notify: [{ id: "n1", kind: "arrival", receipt: RECEIPT }] });
  await fire(edit(LOC));
  expect(sendRich).toHaveBeenCalledOnce();
  expect(api.ackLocationOutbox).toHaveBeenCalledWith("n1");
});
it("does not ack an item whose send failed", ...);
it("arms the open question after sending a question", ...);
it("posts the chat id with the point", ...);   // expect(api.postLocationPoint.mock.calls[0][0].chat_id).toBe(123)

// trip.test.ts
it("matches only well-formed trip taps", () => {
  expect(TRIP_TAP.test("trip:1a2b3c4d:s1:a0")).toBe(true);
  expect(TRIP_TAP.test("trip:1a2b3c4d:all:ok")).toBe(true);
  expect(TRIP_TAP.test("trip:../x:s1:ok")).toBe(false);
});
it("redraws with the returned receipt and restores the pending question", ...);
it("arms the returned open question for a ✎ Something else tap", ...);
it("toasts 'That trip is gone.' on 404", ...);
```

Mock `sendRich` / `editRich` from `../../src/bot-utils/send-rich.js` the way `tests/callbacks/receipt.test.ts` does.

- [ ] **Step 2: Run, expect failure**

Run: `cd apps/telegram-bot && npx vitest run tests/conversations/location.test.ts tests/callbacks/trip.test.ts tests/api/client.test.ts`

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run, expect pass; then `npx vitest run && npx tsc --noEmit`**

- [ ] **Step 5: Commit**

`git commit -m "feat(bot): send trip messages from the ingest response, handle trip taps"`

---

### Task 15: Bot — the nudge draft travels with your text

**Files:**
- Create: `apps/telegram-bot/src/state/nudge-draft.ts`
- Modify: `src/callbacks/day-actions.ts` (`adj:`, `adjsave:`, `block:(approve|dismiss)`, `block:edit` handlers), `src/conversations/message.ts` (`buildMessagePayload`), `src/tracing-utils.ts` (`ReplyToSource`)
- Test: `tests/state/nudge-draft.test.ts`, `tests/callbacks/day-actions.test.ts`, `tests/conversations/message.test.ts`

**Interfaces:**
- **`nudge-draft.ts`** (in memory, like `open-question.ts`):

  ```ts
  export const DRAFT_TTL_MS = 10 * 60 * 1000;
  export interface NudgeDraft { date: string; eventId: string; name: string; start: string; end: string }  // start/end "HH:MM" as drafted
  export function noteNudgeDraft(chatId: number, d: NudgeDraft, now?: number): void
  export function takeNudgeDraft(chatId: number, now?: number): NudgeDraft | undefined   // one-shot
  export function clearNudgeDraft(chatId: number, eventId?: string): void            // eventId given: only if it matches
  export function resetNudgeDrafts(): void
  export function draftContext(d: NudgeDraft): string
  ```

- **`draftContext`** returns: `Unsaved time edit on block "${name}" (id ${eventId}, ${date}): ${start}–${end}. Apply these times together with whatever this message changes, in one update_event.`
- **`adj:`:** after a successful `editRich`, note the draft when either delta is non-zero, using `shiftClock` on `block.start` / `block.end`; otherwise clear it. The draft is noted *after* the edit.
- **Clearing:** `adjsave:`, `block:approve|dismiss` and `block:edit` call `clearNudgeDraft(chatId, eventId)`.
- **The draft survives other sends.** It is **not** added to `dropPerMessageHints` (`bot.ts`): the spec ties its end to an action on the block, not to any send.
- **`buildMessagePayload`:**
  - `const draft = takeNudgeDraft(chatId)`.
  - With an explicit reply, `reply_to.text = answered + "\n\n" + draftContext(draft)`, and the source stays `telegram`.
  - With a held open question, the draft text is appended to it, and the source is `open_question`.
  - With neither, `reply_to = { text: draftContext(draft), from: "assistant" }` and the source is `"nudge_draft"`.
- **`ReplyToSource`** gains `"nudge_draft"`.

- [ ] **Step 1: Write the failing tests**

```ts
// nudge-draft.test.ts
it("is one-shot and expires after 10 minutes", ...);
it("clearNudgeDraft with another event id leaves it", ...);

// day-actions.test.ts
it("adj: with non-zero deltas notes a draft after the edit", ...);  // expect(takeNudgeDraft(123)).toMatchObject({ start: "07:25", end: "08:10" })
it("adj: back to 0/0 clears the draft", ...);
it("adjsave: clears the draft", ...);

// message.test.ts — at the handler, driving the real transformer, as the open-question tests do
it("text after a nudge carries the draft as reply context", ...);   // payload.reply_to.text contains 'Unsaved time edit on block "Dog walk"' and source "nudge_draft"
it("an explicit reply keeps its text and gains the draft", ...);
it("the typing indicator does not drop the draft", ...);
```

- [ ] **Step 2: Run, expect failure**

Run: `npx vitest run tests/state/nudge-draft.test.ts tests/callbacks/day-actions.test.ts tests/conversations/message.test.ts`

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run, expect pass; then `npx vitest run && npx tsc --noEmit`**

- [ ] **Step 5: Commit**

`git commit -m "feat(bot): an unsaved nudge travels with the next message"`

---

### Task 16: Replay, reports, docs, and switching it on

**Files:**
- Create:
  - `apps/vault-server/scripts/location_replay.py`;
  - `scripts/location_labels_from_ledger.py`;
  - `scripts/location_trips_report.py`.
- Modify:
  - `CLAUDE.md`;
  - `docs/specs/2026-11-05-location-check-in-design.md` (a line under §5);
  - `docs/README.md` (index the plan);
  - the memory file `location-spike-data-collection.md` (one line: built; where the plan is).
- Test: `tests/test_location_replay.py`

**Interfaces:**
- **`location_replay.py`** `[--from D --to D] [--with-model --confirm-cost]`.
  - It replays raw points through `Tracker`, matches trips to labels by most overlap, and runs `score_history` with each day's labels held out (leave-one-day-out).
  - It prints the §9 measures:
    - trips found, missed and invented;
    - leaving delay p50 (true departure is the label start);
    - block start/end error p50/p90, from `plan_blocks` with the label's purpose applied;
    - whether the top history candidate equals the label's purpose for every "Dog walk" row;
    - questions per day, from `decide` with history-only guesses (a guess is `strong` when its candidate's score is ≥ 0.75 and the runner-up is < 0.5).
  - `--with-model` makes the real `guess` calls and needs `--confirm-cost`. Without that flag, it refuses and prints the estimated count × $0.007.
  - Pure functions `match_trips(trips, label_trips) -> list[tuple]` and `measures(matches) -> dict` are importable for the test.
- **`location_labels_from_ledger.py`** `[--from --to]`. It writes approved and corrected trip records back into `data/eval/location/{date}.json`, appended, never replacing an existing row for the same interval.
- **`location_trips_report.py`** `[date]`. It prints each trip with its stops, decisions (from `location-trips.jsonl`) and blocks, and no coordinates.

- [ ] **Step 1: Write the failing test**

```python
def test_measures_count_missed_and_invented():
    m = measures(match_trips([trip(10, 20), trip(30, 35)], [label(10, 21), label(50, 60)]))
    assert (m["found"], m["missed"], m["invented"]) == (1, 1, 1)
```

- [ ] **Step 2: Run, expect failure. Step 3: implement the three scripts. Step 4: run the test (pass), then the replay**

Run: `python scripts/location_replay.py --from 2026-11-05 --to 2026-11-10`

Compare it against the §9 targets:
- none missed (the 163 m walk on 7 Nov and the 48 m shop trip on 9 Nov included), none invented;
- leaving p50 ≤ 2 min;
- start/end p50 ≤ 3 / p90 ≤ 10 min;
- every Dog walk named;
- ≤ 2 questions a day.

Paste the output into the ledger. A target missed is reported to the user with the numbers. Do not tune the thresholds silently: a change to a Global Constraints value needs a ledgered ruling.

- [ ] **Step 5: Docs**

**`CLAUDE.md`:**
- An architecture bullet "Location trips (2026-11-13)", summarising tracker → worker → one Haiku call → writer → outbox/notify, the stop rule, the merge rule, and the lock.
- The endpoint list: `POST /locations/points` now returns `notify` when on; `POST /locations/outbox/{id}/ack`; `POST /locations/trips/{id}/tap`.
- `LOCATION_AWARENESS`.
- `data/locations/state.json`, `outbox.json`, `trips/`, `derived/`, and `data/logs/location-trips.jsonl`.
- `set_trip_purpose` in the tool lists, with the tool count bumped.
- The Quick Commands for the four scripts.
- Remove the "`EventsService` has no lock" caveats in the fast-lane bullet, replacing them with a pointer to the new lock.

**The 2026-11-05 spec:** under §5, add "Replaced by `docs/specs/2026-11-10-location-trips-design.md`."

- [ ] **Step 6: Commit, push both repos, open the PR**

```bash
git add -A && git commit -m "feat(location): replay, reports and docs for trips"
git push -u origin feat/location-trips
cd memory && git push && cd ..
gh pr create --base master --title "Location trips: notice where you went, work out why, fill the day" --body "<summary, the replay numbers, rulings, test results>

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01XBHMJx179hGQ9cBNK8KByd"
```

- [ ] **Step 7: Switching on.** This happens after merge, and is the user's call (spec §8).

The user said they want to test live straight away, so the final message tells them the exact steps:
- set `LOCATION_AWARENESS=on` in `apps/vault-server/.env`;
- run `python scripts/location_seed_labels.py` (the labels are local);
- restart the server and the bot.

Do not edit `.env` or restart services from the session.
