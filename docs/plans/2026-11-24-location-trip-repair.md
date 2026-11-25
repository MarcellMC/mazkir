# Location trips: trips you can fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every trip and stop is asked about, trip blocks match what happened, photos and locations are looked up on the local map, and the agent can read and repair any trip by talking.

**Architecture:** The tracker's trip stays the raw record (`rec["trip"]`); the agent's edits are an overlay (`rec["edits"]`) that one function, `trip_of(rec)`, applies, and every reader that plans blocks or draws messages goes through it. Positions never leave the server: map places and photo/location anchors are reached by short handles kept in a per-chat table. New agent tools return trip receipts on the side, which the reply carries for the bot to draw under the answer.

**Tech Stack:** Python 3.14, FastAPI, SQLite (local map index), pytest; TypeScript + grammY (bot), vitest.

**Spec:** `docs/specs/2026-11-24-location-trip-repair-design.md`

## Global Constraints

- No coordinate in a tool result, a model prompt, a span, a log line or the vault (spec §2). No OSM id in a tool result or prompt (spec §7).
- Map place handles are `m<n>`, places of the user's are `place:<id>`; the handle table lives per chat for 24 h; an unknown handle is `PATH_NOT_FOUND` with message "search again" (spec §7).
- Distances shown to the model are rounded to 10 m (`guess._metres`).
- No proposal reaches Google before ✓. Blocks an edit creates are `proposed: true`.
- Every trip asks: `decide` never returns `"name"` for a trip (spec §4).
- No limit on questions: `QUESTION_CAP` and `_questions_today` go (spec §5).
- A stop of 10 min or more ends a leg: `LEG_BREAK_STOP_S = 600` (spec §6).
- `find_place`: within 3 km of `near`, at most 8 results (spec §7.2).
- `find_visit`: points within `max(40 m, accuracy)`, at least 3 min, silences up to 10 min inside (spec §7.3).
- Photo/location lookup: up to 5 places within `max(40 m, GPS accuracy)` (spec §8).
- Tests must not write to `data/logs/tool-calls.jsonl`; set `MAZKIR_AUDIT_LOG_PATH` to a tmp path where an agent runs tools.
- Commit per task on a feature branch; `master` takes PRs only. Never print or commit anything from `data/`.

## Review Focus

1. **A live trip is edited while points still arrive.** The tracker rewrites `rec["trip"]` on every event; an edit must survive the next `STOPPED`/`LEFT_STOP` — pinned in Task 9.
2. **A tap on an old message after an edit.** An arrival message drawn before a `split_stop`/`merge_stops` still carries old stop ids; the tap must answer "That stop changed — see the latest message", not crash or name the wrong stop — pinned in Task 9.
3. **Handles after a restart or 24 h.** The agent reuses `m3` from yesterday's turn; it must get `PATH_NOT_FOUND`, never another place — pinned in Task 6.
4. **A photo with GPS but no map copy and no place of the user's nearby.** The prompt must say "no map here", never fall back to numbers — pinned in Task 8.
5. **Splitting the open trip and then coming home.** `BACK_HOME` must close the second trip, not reopen the first — pinned in Task 10.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/services/skill_executor.py` | strip `next_skill:` lines (Task 1) |
| `src/services/location/runtime.py` | ✕ All skips approved (Task 2); new methods the tools call (Task 12) |
| `src/services/location/decide.py`, `pipeline.py`, `records.py` | every trip asks, no cap, unanswered → later (Task 3) |
| `src/services/location/tracker.py` | trip start after a silence (Task 4) |
| `src/services/location/writer.py` | legs only while moving, leg keys, photos kept on re-plan (Task 5) |
| `src/services/location/handles.py` (new) | per-chat handle table (Task 6) |
| `src/services/location/map_lookup.py` | `map_search`, `map_address`, `street_named` (Task 7) |
| `src/services/location/where.py` (new) | a position in words, for photos and locations (Task 8) |
| `src/services/exif_service.py`, `src/services/agent_service.py` | GPS accuracy; prompt lines; photo to covering block in every mode (Task 8) |
| `src/services/location/edits.py` (new) | `trip_of`, stop ops (Task 9), trip split/join (Task 10) |
| `src/services/location/view.py` (new) | `get_trip`, `find_place`, `find_visit` (Task 11) |
| `src/services/location/places_edit.py` (new) | no street as a place, `edit_place` (Task 11) |
| `src/services/agent_service.py`, `src/services/location/turn_receipts.py` (new), `src/api/routes/message.py` | five tools; trip receipts on the reply (Task 12) |
| `apps/telegram-bot/src/conversations/message.ts`, `packages/shared-types` | draw trip receipts under the reply (Task 13) |
| `src/api/routes/events.py` | dismissed proposal's photos go to the note (Task 5) |
| vault `memory/00-system/skills/*.md`, `CLAUDE.md`, `docs/README.md` | skill text, docs (Task 14) |

All Python paths are under `apps/vault-server/`. Tests go in `apps/vault-server/tests/`; use `tests/location_pipeline_fixtures.make_deps` and `tests/location_fixtures` (`Track`, `t`, `at`) for trips.

---

### Task 1: `next_skill:` never reaches the user

**Files:**
- Modify: `src/services/skill_executor.py` (the loop end, ~line 190–205; `_extract_next_skill` at ~216)
- Test: `tests/test_skill_executor.py`

**Interfaces:**
- Produces: `SkillExecutor._strip_next_skill(text: str) -> str` (static).

- [ ] **Step 1: Write the failing tests**

```python
def test_strip_next_skill_removes_token_lines():
    text = "Done, logged it.\nnext_skill: time-management\n"
    assert SkillExecutor._strip_next_skill(text) == "Done, logged it."

def test_unknown_next_skill_does_not_leak():
    # a skill replies with a next_skill name not in its allowed list
    result = run_executor_with_reply("Sure.\nnext_skill: nonsense")   # build like test_next_skill_handoff_runs_second_skill
    assert "next_skill" not in result.response_text
```

- [ ] **Step 2: Run** `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_skill_executor.py -v` — expect the two new tests to FAIL.
- [ ] **Step 3: Implement.** `_strip_next_skill` removes every line matching `^\s*next_skill:\s*[a-z_-]+\s*$` (multiline) and trailing whitespace. Apply it to `response_text` in `SkillExecutorResult` on every exit (hop cap, cycle, unknown name, no hop).
- [ ] **Step 4: Run** the file again — PASS.
- [ ] **Step 5: Commit** `fix(agent): never send the next_skill token to the user`

---

### Task 2: ✕ Not right keeps what you ✓'d

**Files:**
- Modify: `src/services/location/runtime.py:279-307` (`_approve`)
- Test: `tests/test_location_runtime.py`

- [ ] **Step 1: Write the failing test** `test_not_right_all_skips_approved_blocks`: a closed trip with two blocks (`trip`, `stop:s1`); `stop:s1` stored `state: "approved"`. `rt.tap(trip_id, "all", "no")` returns `approvals == [(date, trip_event_id, "dismissed")]` only, and `toast == "Dismissed the rest — kept what you ✓'d."`. A second test: with nothing approved, toast stays `"Dismissed"`.
- [ ] **Step 2: Run** `python -m pytest tests/test_location_runtime.py -v` — FAIL.
- [ ] **Step 3: Implement.** In `_approve`, when `line == "all"` and `action == "no"`, skip a part whose fragments all resolve (`approval.resolve_state` on the stored event) to `"approved"`; set the toast above when any were skipped.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `fix(location): ✕ Not right keeps blocks you approved`

---

### Task 3: Every trip asks, every stop is asked

**Files:**
- Modify: `src/services/location/decide.py` (drop `QUESTION_CAP`, `questions_today`, the trip `"name"` branch)
- Modify: `src/services/location/pipeline.py` (`_questions_today`, `_on_stopped`, `_on_left_stop`, `_on_back_home`)
- Modify: `src/services/location/records.py` (`questions_on` — delete if unused after this task)
- Test: `tests/test_location_decide.py`, `tests/test_location_pipeline.py`

**Interfaces:**
- Produces: `decide(guesses, history, *, known_place, may_ask, at_stop=False, map_options=()) -> Decision` — no `questions_today` parameter. `Decision.action` is `"name"` only when `at_stop` and `known_place` is a non-pause place.

- [ ] **Step 1: Write the failing tests**
  - `test_trip_with_one_strong_guess_asks`: `decide([guess("Dog walk")], history, known_place=None, may_ask=True)` → `action == "ask"`, `options[0].name == "Dog walk"`.
  - `test_no_daily_cap`: in the pipeline, 10 trips' worth of stops in one day each get a `question` outbox item (use `make_deps`, feed 10 `STOPPED` events on distinct stops).
  - `test_unanswered_stop_becomes_later_on_leaving`: `STOPPED` (asked) then `LEFT_STOP` with no answer → `rec["stops"]["s1"]["status"] == "later"`, and the arrival receipt after `BACK_HOME` has a `?` line for s1.
  - `test_open_stop_at_back_home_becomes_later`: asked stop still open at `BACK_HOME` → `"later"`.
  - `test_trip_named_by_mid_trip_answer_is_not_asked_again`: `apply_answer(trip_id, None, "Dog walk", None, deps)` before `BACK_HOME` → no `trip_question`.
  - Update existing tests that asserted silent naming or the cap; delete cap tests.
- [ ] **Step 2: Run** `python -m pytest tests/test_location_decide.py tests/test_location_pipeline.py -v` — new tests FAIL.
- [ ] **Step 3: Implement.** Remove the `not at_stop and len(strong) == 1` branch and the cap. In `_on_left_stop` and `_on_back_home`, set `status = "later"` for every stop whose status is `"asked"` and not `answered` (the outbox withdrawal stays). `_name_from_your_block` is unchanged. Remove `_questions_today` and its call.
- [ ] **Step 4: Run** the whole location suite `python -m pytest tests/ -k location -q` — PASS.
- [ ] **Step 5: Commit** `feat(location): every trip asks, no question cap, unanswered stops asked at home`

---

### Task 4: A trip starts when it left

**Files:**
- Modify: `src/services/location/tracker.py:306-332` (`_leave`)
- Modify: `src/services/location/guess.py:137` (`describe_trip` wording)
- Test: `tests/test_location_tracker.py`

- [ ] **Step 1: Write the failing test** `test_trip_after_silence_starts_at_first_point_away`: points at home until 17:41, nothing, then from 19:01 points 500 m away for 2 min. The trip's `left_at == t(…, 19, 1)` (the first point outside), `start_precision == "before"`, and `legs[0].start == left_at`. A second test: no silence → `left_at` is the last point inside, `"location"` (unchanged).
- [ ] **Step 2: Run** `python -m pytest tests/test_location_tracker.py -v` — FAIL.
- [ ] **Step 3: Implement.** In `_leave`, when `precision == "before"` the departure is `self._outside[0].ts`. Applies to the trip start and to the new leg after a stop; a stop's `end` stays `stay.last_inside_ts`. `describe_trip` keeps "Left home before HH:MM", which is now correct.
- [ ] **Step 4: Run** the tracker and replay tests — PASS.
- [ ] **Step 5: Commit** `fix(location): a trip after a silence starts at the first point away`

---

### Task 5: Blocks that match what happened

**Files:**
- Modify: `src/services/location/writer.py` (`_travel`, `apply_blocks`, `_delete_if_pending`, `_create`)
- Modify: `src/api/routes/events.py:385` (`set_event_state`)
- Test: `tests/test_location_writer.py`, `tests/test_events_routes.py` (or the existing `set_event_state` test file)

**Interfaces:**
- Produces: leg part keys `leg:<from>-<to>` where each end is a stop id, `"start"` or `"home"`; `writer.LEG_BREAK_STOP_S = 600`.
- Produces: `writer._rekey_legs(rec: dict, specs: list[BlockSpec], events, zone) -> None` — renames old `leg:<n>` keys in `rec["blocks"]` to the planned key whose spec starts within 60 s of the stored block's start.

- [ ] **Step 1: Write the failing tests**
  - `test_long_unnamed_stop_ends_a_leg`: travel purpose, named s1 and s3, unnamed s2 lasting 20 min between them → specs include `leg:s1-s2` ending at s2.start and `leg:s2-s3` starting at s2.end; no block covers s2.
  - `test_short_unnamed_stop_stays_in_leg`: s2 lasting 5 min → one leg `leg:s1-s3`.
  - `test_activity_trip_keeps_unnamed_stops_inside`: no destination → one `trip` block covering everything (unchanged).
  - `test_old_leg_keys_are_rekeyed`: a record with an approved `leg:2` block whose start matches the new `leg:s1-s3` → after `apply_blocks`, `rec["blocks"]` has `leg:s1-s3` with the same `event_id`, and no new block was created.
  - `test_photos_survive_recreate`: a pending trip block with `photos: ["a.jpg"]` whose shape changes (now crosses midnight) → the recreated block(s) carry `a.jpg` (the first fragment).
  - `test_dismissing_a_proposal_moves_its_photos_to_the_note`: `set_event_state` with `dismissed` on a `proposed` block holding a photo → the daily note's `## Notes` gains `![[a.jpg]]` (via `vault.append_to_daily_section`), and the block's `photos` is emptied.
- [ ] **Step 2: Run** `python -m pytest tests/test_location_writer.py -v` — FAIL.
- [ ] **Step 3: Implement.**
  - `_travel`: the stops that break legs are named stops plus unnamed stops of `LEG_BREAK_STOP_S` or more; legs run between consecutive breakers; only named stops get blocks. Key each leg by its two ends.
  - `apply_blocks`: call `_rekey_legs` before matching. `_delete_if_pending` returns the deleted blocks' `photos`; `apply_blocks` passes them to the `_create` of the same part, which attaches them with `events.attach_photo` after creating.
  - `set_event_state`: on `dismissed` for an event with `proposed` and `photos`, append one `![[<filename>]]` line per photo to the event's date note `## Notes` and clear `photos` on the event.
- [ ] **Step 4: Run** `python -m pytest tests/ -k "location or events" -q` — PASS.
- [ ] **Step 5: Commit** `feat(location): legs only while moving, legs keyed by their stops, photos kept on re-plan`

---

### Task 6: Handles instead of ids

**Files:**
- Create: `src/services/location/handles.py`
- Test: `tests/test_location_handles.py`

**Interfaces:**
- Produces:
  - `class Handles: __init__(self, path: Path, ttl: dt.timedelta = dt.timedelta(hours=24), now: Callable[[], dt.datetime] = …)`
  - `Handles.place(chat_id: int, *, osm: str, label: str, kind: str, lat: float, lng: float) -> str` — returns `m<n>`; the same `osm` in the same chat returns the same handle while it lives.
  - `Handles.anchor(chat_id: int, key: str, lat: float, lng: float, accuracy_m: float | None = None) -> str` — for `photo:<file>` / `location:<message_id>`; returns `key`.
  - `Handles.resolve(chat_id: int, handle: str) -> dict | None` — `{kind: "map"|"anchor", osm?, label?, lat, lng, accuracy_m?}`; `None` when unknown or expired.
  - Persisted with an atomic write to `data/locations/handles.json`; entries older than `ttl` are dropped on load and on write.

- [ ] **Step 1: Write the failing tests**: same osm → same handle; a different chat gets its own numbering; `resolve` after 25 h → `None`; survives a new `Handles` on the same path; a corrupt file reads as empty.
- [ ] **Step 2: Run** `python -m pytest tests/test_location_handles.py -v` — FAIL.
- [ ] **Step 3: Implement** `handles.py` (a lock around read-modify-write; reuse `runtime._atomic_write`).
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(location): per-chat handles for map places and anchors`

---

### Task 7: Searching the map copy

**Files:**
- Modify: `src/services/location/map_lookup.py`
- Test: `tests/test_location_map_lookup.py` (build a small index with the existing test helper used there)

**Interfaces:**
- Produces:
  - `map_search(index: Path | None, query: str, lat: float, lng: float, radius_m: float = 3000, limit: int = 8) -> list[MapPlace]` — matches `name`, `name_en`, `street` (for addresses) by normalised exact, prefix, then substring, then distance; groups `place` and `address` only.
  - `map_address(index: Path | None, lat: float, lng: float, radius_m: float = 60) -> str | None` — `"<street> <housenumber>"` of the nearest address, or `"<street>"` when only the street is known.
  - `street_named(index: Path | None, name: str, lat: float, lng: float, radius_m: float = 300) -> bool` — True when an address within `radius_m` has that street (normalised) and no `place` within `radius_m` has that name.
  - Normalisation `_fold(text) -> str`: casefold, strip punctuation and Hebrew niqqud, map Hebrew final letters (ך→כ, ם→מ, ן→נ, ף→פ, ץ→צ).

- [ ] **Step 1: Write the failing tests**: Hebrew query with a final letter finds the place; English `name_en` match; exact beats substring beats nearer; nothing beyond 3 km; `map_address` gives street + number; `street_named("יסוד המעלה", …)` True for an index holding only addresses on that street, False when a café of that name is near; all return `[]`/`None` without an index.
- [ ] **Step 2: Run** `python -m pytest tests/test_location_map_lookup.py -v` — FAIL.
- [ ] **Step 3: Implement** with `_query` over the R-tree box and Python-side matching (no new index table).
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(location): search the map copy by name, nearest address`

---

### Task 8: Photos and locations in words

**Files:**
- Create: `src/services/location/where.py`
- Modify: `src/services/exif_service.py` (GPS accuracy), `src/services/agent_service.py:2063-2141` (`_place_photo`, `_build_user_content`)
- Test: `tests/test_location_where.py`, `tests/test_agent_service.py`, `tests/test_exif_service.py`

**Interfaces:**
- Consumes: `Handles` (Task 6), `map_near`, `map_address`, `map_area` (Task 7), `fast_lane.places.nearest`, `TripRecords`.
- Produces:
  - `describe_where(lat, lng, *, accuracy_m: float | None, at: dt.datetime | None, chat_id: int, places: list[Place], map_index: Path | None, handles: Handles, records=None, anchor_key: str) -> str` — the text after `where:` (or `at home` / `at <place>`), e.g. `m1 Café X (café, 10 m), m2 … ; on Street N 12; in <area> | GPS ±15 m`; registers `anchor_key` in `handles`.
  - When `at` falls inside a stop of a trip in `records`, the text is `at stop s3 of trip <id> (<name or "unnamed">)` followed by that stop's map places.
  - Without a map and no place of the user's: `no map here`.
  - `extract_exif_metadata(...)["gps"]["accuracy_m"]` from `GPSHPositioningError`, when present.
  - `LocationRuntime.handles: Handles`, created in `build_runtime` at `<locations root>/handles.json`; later tasks reach it as `rt.handles`.

- [ ] **Step 1: Write the failing tests**
  - `test_at_home`: inside home's radius → `"at home"`, no `m` handles.
  - `test_near_places_and_address`: index with a café 10 m and a restaurant 25 m → both with handles, the address, the area; never a number with ≥4 decimals (regex `\d+\.\d{4,}`).
  - `test_accuracy_widens_radius`: accuracy 60 m finds a place at 55 m; accuracy None does not.
  - `test_photo_during_stop`: a trip record with stop s3 covering `at` → `"at stop s3 of trip …"`.
  - `test_no_map`: `map_index=None`, no place → `"no map here"`.
  - In `test_agent_service.py`: a photo attachment with EXIF GPS → user content contains `where:` and no `EXIF GPS:`; a location attachment → `[Location: where: …]` / `[Location — "<title>": where: …]` and no coordinate; a forwarded location is described but `places.json` is unchanged.
  - `test_photo_attaches_to_covering_block_when_shadow`: `FAST_LANE_MODE=shadow`, a trip proposal covering the photo's moment → `events.attach_photo` called on it; with no persisted block covering, the reconciled day (`get_events_preview`) is tried before "no block covers that moment".
- [ ] **Step 2: Run** `python -m pytest tests/test_location_where.py tests/test_agent_service.py tests/test_exif_service.py -v` — FAIL.
- [ ] **Step 3: Implement.** `_build_user_content` calls `describe_where` with `anchor_key = f"photo:{filename}"` or `f"location:{message_id}"` (message id from the attachment; fall back to a uuid). `_place_photo` drops the `fast_lane_mode == "on"` gate and falls back to the reconciled day on a miss. `AgentService` gets the handles/map/places/records through the location runtime (`location_runtime.get_runtime()`), and when the runtime is off it uses places only.
- [ ] **Step 4: Run** — PASS, then `python -m pytest tests/ -q` for regressions.
- [ ] **Step 5: Commit** `feat(location): photos and locations are looked up on the map, never sent as numbers`

---

### Task 9: The edit overlay and stop edits

**Files:**
- Create: `src/services/location/edits.py`
- Modify: every `Trip.from_dict(rec["trip"])` used for planning or drawing → `trip_of(rec)`: `writer.plan_blocks`, `messages.arrival_receipt`, `messages.question_receipt`, `pipeline._answer`, `pipeline.defer_stop`, `pipeline._on_back_home`, `runtime._tap`, `history.load_confirmed`, `records.on_day`
- Test: `tests/test_location_edits.py`

**Interfaces:**
- Produces:
  - `trip_of(rec: dict) -> Trip` — `Trip.from_dict(rec["trip"])` with `rec["edits"]` applied in order, `id` set to `rec["id"]`.
  - `apply_edit(trip_id: str, op: str, args: dict, deps: TripDeps) -> dict` — under `deps.records.lock_for(trip_id)`; validates, appends to `rec["edits"]`, re-plans (`_apply`), refreshes the arrival message (`_refresh_arrival`), saves, logs decision `EDIT` with `{op, stop_ids}` only; returns `{"record": rec, "receipt": arrival_receipt(...)}`. Raises `KeyError` for an unknown trip/stop, `ValueError(message)` for a refused edit.
  - Stop ops and their edit dicts:
    - `add_stop {start, end, ref?, name?}` → `{op, id: "x<n>", start, end, lat, lng, spread_m}`; position from the resolved handle, else the centre of raw fixes in the window (`raw.load_fixes`, root = `deps.raw_dir`); refused outside the trip's time.
    - `name_stop {stop_id, name, ref?, place?}` → goes through `pipeline.apply_answer` (with `osm` from the handle); no edit entry.
    - `split_stop {stop_id, at}` → `{op, stop_id, at, ids: ["<sid>a", "<sid>b"], centres}`; each half's centre from its own raw fixes, else the original.
    - `merge_stops {stop_ids}` → adjacent only; `{op, stop_ids, id: first}`; the first's `rec["stops"]` info is kept.
    - `set_stop_times {stop_id, start?, end?}` → pinned in the overlay, so a later tracker update of that stop does not override it.
    - `remove_stop {stop_id}`.
    - `restore_block {part}` → `events.update_event(state=None)` on each fragment (back to pending proposal); no edit entry.
  - `TripDeps.raw_dir: Path | None = None` (set by `build_runtime` to `data/locations/raw`).
  - Edited stops carry `source: "agent_edit"` in `rec["stops"][id]`.

- [ ] **Step 1: Write the failing tests**
  - one test per op on a closed trip, asserting `trip_of(rec).stops` and the planned blocks;
  - `test_edit_survives_tracker_event` (Review Focus 1): open trip, `set_stop_times` on s1, then a `STOPPED` for s2 through `handle_event` → `trip_of(rec).stop("s1")` keeps the edited times and s2 exists;
  - `test_tap_on_changed_stop` (Review Focus 2): after `split_stop` on s1, `rt.tap(trip_id, "s1", "a0")` → toast `"That stop changed — see the latest message."`, no answer applied;
  - `test_add_stop_outside_trip_refused` → `ValueError`;
  - `test_edit_result_has_no_coordinates`: `json.dumps` of everything `apply_edit` returns except `record` contains no `lat`/`lng` key and no `\d+\.\d{4,}`.
- [ ] **Step 2: Run** `python -m pytest tests/test_location_edits.py -v` — FAIL.
- [ ] **Step 3: Implement** `edits.py`, then switch the readers listed above to `trip_of`. In `runtime._tap`, a stop id the overlay removed answers the toast above (today it raises `KeyError`).
- [ ] **Step 4: Run** `python -m pytest tests/ -k location -q` — PASS.
- [ ] **Step 5: Commit** `feat(location): trip edits as an overlay over the tracker's trip`

---

### Task 10: Splitting and joining trips

**Files:**
- Modify: `src/services/location/edits.py`, `src/services/location/pipeline.py` (`_handle`)
- Test: `tests/test_location_edits.py`

**Interfaces:**
- Consumes: `trip_of`, `apply_edit` (Task 9).
- Produces:
  - `split_trip {at, stop_side?: "first"|"second", purpose_to?: "first"|"second"}` — `at` is a stop id (cut at its end, the stop stays in the first unless `stop_side == "second"`), or a time. The first record gets `{op: "window", end: at}`, `split_into: <new id>`, `closed: True`; a new record (`new_record`, id `uuid4().hex[:8]`) gets the same `trip` dict, `{op: "window", start: at}`, `split_from`; `rec["stops"]` infos move with their stops; the purpose stays with the first unless `purpose_to == "second"`. Both are re-planned; the second asks on its own (trip question when closed).
  - `join_trips {other_trip_id}` — refused (`ValueError("a trip is still open")`) when either is open, or when they are not consecutive on the same day or the next. The first gets `{op: "join", trip: trip_of(other).to_dict()}` with the joined stop ids prefixed `j`; the other gets `joined_into`, its pending blocks deleted; an approved block of the other is re-keyed into the first's `rec["blocks"]` when its part exists there, else its `trip` field is removed so the writer's merge rules treat it as the user's.
  - `pipeline._handle`: an event for a record with `split_into` and `ev.ts >= window end` is handled on the record it was split into (follow the chain); `rec["trip"]` of every record in the chain is updated to `ev.trip`.
  - `history.load_confirmed` skips `joined_into` records.

- [ ] **Step 1: Write the failing tests**: split a closed trip at a stop (both sides, purpose stays first); split by time; `test_split_open_trip_then_home` (Review Focus 5): split the open trip, then `BACK_HOME` → the second record is `closed`, the first unchanged; join two closed trips (stop ids `js1`…, one arrival message); join refused while open; an approved block of the joined trip survives.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `python -m pytest tests/ -k location -q` — PASS.
- [ ] **Step 5: Commit** `feat(location): split a trip in two, join two into one`

---

### Task 11: Reading trips, finding places and visits, fixing places

**Files:**
- Create: `src/services/location/view.py`, `src/services/location/places_edit.py`
- Modify: `src/services/location/pipeline.py` (`_answer`: street check before `learn_place`)
- Test: `tests/test_location_view.py`, `tests/test_location_places_edit.py`

**Interfaces:**
- Consumes: `Handles`, `map_search`, `street_named`, `trip_of`, `raw.load_fixes`.
- Produces:
  - `get_trip(deps, handles, chat_id, *, trip_id: str | None = None, date: str | None = None) -> dict` — `{"trips": [...]}` per spec §7.1; map places as `{ref, label, kind, distance_m}` (handles registered); blocks with `part, event_id, date, name, start, end, state` including dismissed; `split_from`/`split_into`/`joined_into`. A date means the logical day (`records._logical_day`, boundary `deps.boundary_hour`).
  - `find_place(deps, handles, chat_id, query: str, near: str | None = None) -> dict` — `{"places": [{ref, label, kind, group, area, distance_m}], "near": <what it searched around>}`; `near` is `trip:<id>` (its farthest stop), `stop:<trip>:<stop>`, `home`, `photo:<file>`, `location:<id>`; default the latest trip. User places first when they match (`match_place`), then `map_search`.
  - `find_visit(deps, handles, chat_id, ref: str, *, trip_id=None, date=None) -> dict` — `{"visits": [{start, end, closest_m, stop_id, quality: "good"|"poor"}], "closest": {distance_m, at} | None}`.
  - `edit_place(deps, handles, chat_id, ref: str, op: "forget"|"move_to"|"rename"|"add_alias", value: str | None) -> dict` — `move_to` takes `"<trip>:<stop>"`.
  - `pipeline._answer`: when `place` is given and `street_named(deps.map_index, place, stop.lat, stop.lng)`, do not call `learn_place`; set `info["place"] = place`, `info["street"] = True`, and return `{"record": rec, "conflict": None, "street": True}`.

- [ ] **Step 1: Write the failing tests**: `get_trip` by id and by logical date (a trip at 01:30 belongs to the previous day); dismissed blocks listed; `find_place` near a trip returns handles not ids; a user place outranks a map place of the same name; `find_visit` on synthetic fixes (a 6-min visit with a 4-min silence inside is one visit; 2 min is none; poor quality when accuracy > 30 m); `edit_place` each op; the street answer is not learned; the coordinate check over every returned dict.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(location): read a trip, find places and visits, fix places`

---

### Task 12: The agent's tools and trip receipts on the reply

**Files:**
- Create: `src/services/location/turn_receipts.py`
- Modify: `src/services/agent_service.py` (`_register_tools`, handlers, `AgentResponse`, `handle_message`), `src/services/location/runtime.py` (thin methods), `src/api/routes/message.py` (`_on_reply`, both final payloads)
- Test: `tests/test_agent_service.py`, `tests/test_location_runtime.py`, `tests/test_message_route.py` (the existing route test file)

**Interfaces:**
- Consumes: Tasks 9–11.
- Produces:
  - `turn_receipts.collecting() -> ContextManager[list[dict]]` and `turn_receipts.add(receipt: dict) -> None` (a `ContextVar` holding a list; `add` outside a turn does nothing).
  - Tools (schema + handler + risk):
    - `get_trip` (safe): `{trip_id?, date?}`
    - `find_place` (safe): `{query, near?}`
    - `find_visit` (safe): `{ref, trip_id?, date?}`
    - `edit_trip` (write): `{trip_id, op: enum[name_trip, name_stop, add_stop, split_stop, merge_stops, set_stop_times, remove_stop, split_trip, join_trips, restore_block], ...op args, _confidence, _reasoning}`
    - `edit_place` (write): `{ref, op: enum[forget, move_to, rename, add_alias], value?, _confidence, _reasoning}`
  - `edit_trip`'s handler calls `turn_receipts.add(result["receipt"])` and returns `ok({"trip": get_trip(...)["trips"][0], "shown_to_user": True})` — the receipt itself is not in the tool result.
  - `set_trip_purpose` becomes a call to `edit_trip` with `name_trip`/`name_stop` (schema unchanged).
  - `AgentResponse.trip_receipts: list[dict] = field(default_factory=list)`; `handle_message` wraps the turn in `collecting()`.
  - `_on_reply(...)` adds `"trip_receipts": result.trip_receipts if result else []`; the streamed `done` payload carries it too.
  - `list_events`' description: "for a trip's stops and times, call get_trip".
  - Errors: `KeyError` → `PATH_NOT_FOUND`; `ValueError` → `STATE_CONFLICT` with its message; unknown handle → `PATH_NOT_FOUND` "search again"; runtime off → `STATE_CONFLICT` "Location trips are off".

- [ ] **Step 1: Write the failing tests**: registration of the five tools with their risks; each handler with a fake runtime; `edit_trip` puts its receipt on `AgentResponse.trip_receipts` and not in the tool result; the route returns `trip_receipts` in both JSON and the SSE `done` frame; tool count assertion updated (36 → 41).
- [ ] **Step 2: Run** `python -m pytest tests/test_agent_service.py tests/test_message_route.py -v` — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `python -m pytest tests/ -q` — PASS.
- [ ] **Step 5: Commit** `feat(agent): get_trip, find_place, find_visit, edit_trip, edit_place`

---

### Task 13: The bot draws trip receipts under the reply

**Files:**
- Modify: `packages/shared-types/src/` (the `MessageResponse` type: `trip_receipts?: Receipt[]`), `apps/telegram-bot/src/conversations/message.ts` (`sendFinal`), `apps/telegram-bot/src/api/client.ts` (the `done` frame parse, if it whitelists fields)
- Test: `apps/telegram-bot/tests/conversations/message.test.ts`

- [ ] **Step 1: Write the failing test** `sendFinal sends trip receipts after the reply`: a response with `response: "Added the café stop."` and one trip receipt → `sendRich` called with the markdown first, then `buildReceiptRich(receipt)`; an `open_question` on a trip receipt is armed after the sends.
- [ ] **Step 2: Run** `cd apps/telegram-bot && npx vitest run tests/conversations/message.test.ts` — FAIL.
- [ ] **Step 3: Implement** in `sendFinal`, after the reply. Taps already route through `callbacks/trip.ts`.
- [ ] **Step 4: Run** `npx vitest run` and `npx tsc --noEmit` — PASS.
- [ ] **Step 5: Commit** `feat(bot): draw trip receipts under the agent's reply`

---

### Task 14: Skill text, docs, and the replay check

**Files:**
- Modify (vault repo, `memory/`): `00-system/skills/time-management.md` (add the five tools to `tools:`; trip rules per spec §7.6, replacing lines 48–49), `00-system/skills/mazkir.md` (add `get_trip`, `find_place`; one line: "Location trips exist; read them with get_trip")
- Modify: `CLAUDE.md` (tool count 41 and names; a "Trips you can fix (2026-11-24)" bullet under the location architecture), `docs/README.md` (key docs line for the spec and plan), the spec's status line → `built`
- Modify: `scripts/location_replay.py` — measures `trips_named_without_question` and `stops_never_asked`

- [ ] **Step 1: Write the failing test** in `tests/test_location_replay.py`: the two new measures on a synthetic day (one trip, two stops, one answered).
- [ ] **Step 2: Run** — FAIL; **implement**; run — PASS.
- [ ] **Step 3: Rebuild and replay** `python scripts/location_rebuild.py --from 2026-11-16 --to 2026-11-23` (writes only `derived/`), then `python scripts/location_replay.py --from 2026-11-16 --to 2026-11-23`, and record in the PR description: `trips_named_without_question == 0`, `stops_never_asked == 0`, and the two early starts (16–17 Nov, 19–20 Nov) now start at their first point away. Report counts and times only.
- [ ] **Step 4: Edit the skills and docs**; commit the vault separately in `memory/` (`docs(skills): trip tools`).
- [ ] **Step 5: Commit** `docs: trips you can fix` and open the PR against `master`.
