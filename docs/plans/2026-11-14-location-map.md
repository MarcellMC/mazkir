# Location map copy: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local copy of OpenStreetMap supplies the places at a stop, so a stop question
offers real places such as [Café Barzilay] and [Dog park] as buttons.

**Architecture:** A monthly download of Geofabrik's Israel `.osm.pbf` is kept whole in
`data/map/`, and a SQLite index with an R*Tree is built from it. That index holds places,
addresses, area names and transit stops. At a STOPPED event, the pipeline looks up nearby
map places (a local file read) and:
- gives the model their labels and distances;
- lets a guess cite them through `map_id`;
- fills any empty buttons with them;
- records the place's `osm` id when the user answers.

**Tech stack:** Python 3.13, pyosmium (`osmium` 4.3.2, installed with `uv pip`), sqlite3
with R*Tree (SQLite 3.50.4), httpx, pytest.

**Spec:** `docs/specs/2026-11-14-location-map-design.md`

## Global Constraints

- **No position leaves the machine.** The only network call is downloading
  `LOCATION_MAP_URL` and its `.md5`.
- **No coordinate reaches a model, span, log line, the vault or `data/logs/`.**
  - The model sees labels, kinds, distances and area names only. It never sees OSM ids or
    house numbers; addresses appear as the street only.
  - Exceptions are logged with `model.safe_error`.
- **Settings:**
  - `LOCATION_MAP` defaults to `on` (user, 2026-11-14). With `off`, nothing in this plan
    runs and stops behave exactly as they do now.
  - `LOCATION_MAP_URL` defaults to `https://download.geofabrik.de/asia/israel-and-palestine-latest.osm.pbf`.
  - `LOCATION_MAP_MAX_AGE_DAYS` defaults to `30`.
- **The user's places come first.** A user place (`data/places.json`) at the stop names it
  silently, with no map lookup. A map entry never renames or moves a user place.
- **Map places are buttons only.** A stop is never named from the map without asking.
- **The 2026-11-14 stop rules stand:**
  - a stop guess needs a destination and must not equal the trip's purpose;
  - an unanswered stop stays unnamed, with no block;
  - `Later` stays.
- **No map, no change.** With no index (missing, corrupt or being built), lookups return
  `[]` and stops are asked about as they are today.
- **Callback data carries indexes, never names,** so a long or Hebrew label cannot push a
  button past Telegram's 64 bytes.
- **Docs:** `docs/specs/`, `docs/plans/`. Commits end with the session attribution lines.
  `master` takes PRs only.

## Review Focus

1. **A lookup while an update swaps the index.** The reader opens SQLite read-only
   (`mode=ro`) per lookup; the swap is `os.replace`. A reader sees the old file or the new
   one, never a partial one. Test: `test_lookup_during_swap_sees_old_or_new`.
2. **Ranking for nested and large areas.**
   - A dog park inside a park: the dog park first.
   - A café node 10 m away inside a 5 ha park: the café first.

   Tests: `test_small_containing_area_ranks_first`, `test_big_containing_area_counts_as_20m`.
3. **An interrupted download or a full disk.** The `.part` files are removed and the old
   copy keeps answering. Tests: `test_failed_build_keeps_old_copy`, `test_md5_mismatch_keeps_old_copy`.
4. **A user place next to a map place.** The user place names the stop, and `map_near` is
   not called. Test: `test_user_place_wins_and_skips_the_map`.
5. **A Hebrew-only name, or a label over 32 characters.** The button label is cut with "…"
   and callback data is unchanged. Test: `test_hebrew_and_long_map_labels`.

---

### Task 1: Settings and the dependency

**Files:**
- Modify: `apps/vault-server/src/config.py` (beside `location_awareness`)
- Modify: `apps/vault-server/pyproject.toml` (`dependencies`)
- Modify: `.gitignore` only if `data/map/` is not already covered by `data/` (check first)
- Test: `apps/vault-server/tests/test_config.py`

**Interfaces:**
- Produces: `settings.location_map: str = "on"`, `settings.location_map_url: str`,
  `settings.location_map_max_age_days: int = 30`, and `settings.location_map_path: Path`
  (default `{location_data_path.parent}/map`, from the env var `LOCATION_MAP_PATH`).

- [ ] **Step 1: Write the failing test** `test_location_map_defaults`:
  - import `Settings` *before* `monkeypatch.delenv` for each of `LOCATION_MAP`,
    `LOCATION_MAP_URL` and `LOCATION_MAP_MAX_AGE_DAYS` (the existing load-order lesson);
  - assert `Settings(_env_file=None).location_map == "on"`;
  - assert the URL equals the Geofabrik URL above;
  - assert `location_map_max_age_days == 30`;
  - assert `location_map_path.name == "map"`.
- [ ] **Step 2: Run** `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_config.py -q`.
  Expected: FAIL (no attribute `location_map`).
- [ ] **Step 3: Implement** the four settings. Add `"osmium>=4.3.2"` to `pyproject.toml`,
  then run `uv pip install --python venv/bin/python "osmium>=4.3.2"`.
- [ ] **Step 4: Run** the same test, then `python -c "import osmium; print(osmium.__version__)"`.
  Expected: PASS, and `4.3.2`.
- [ ] **Step 5: Commit** `feat(location): map settings and pyosmium`.

### Task 2: Build the index from a map file

**Files:**
- Create: `apps/vault-server/src/services/location/map_index.py`
- Create: `apps/vault-server/tests/fixtures/map_small.osm` (OSM XML; pyosmium reads it)
- Test: `apps/vault-server/tests/test_location_map_index.py`

**Interfaces:**
- Produces:
  - `INDEX_VERSION = 1`.
  - `classify(tags: dict[str, str]) -> tuple[str, str] | None`, returning `(group, kind)`.
  - `build_index(src: Path, dest: Path) -> dict[str, int]`, returning counts per group.
  - Table `features` with columns `id INTEGER PRIMARY KEY, osm TEXT, grp TEXT, kind TEXT,
    name TEXT, name_en TEXT, street TEXT, housenumber TEXT, city TEXT, lat REAL, lng REAL,
    area_m2 REAL, rings TEXT`.
  - `rings` is JSON `[[[lat, lng], …], …]`: outer rings, then inner rings, each tagged
    `{"outer": bool}`. The builder chooses the exact shape and documents it in the module
    docstring.
  - R*Tree `features_rtree(id, min_lat, max_lat, min_lng, max_lng)`.

**Classification rule** (spec §4.4):
- **`place`:** has any key in `PLACE_KEYS = ("amenity", "shop", "leisure", "tourism",
  "healthcare", "office", "craft", "sport")`. `kind` is the first such key's value, in that
  order.
- **`address`:** has `addr:housenumber` and is not a place.
- **`area`:** `place` is in `("suburb", "quarter", "neighbourhood", "city")`.
- **`transit_stop`:**
  - `highway=bus_stop` gives `bus_stop`;
  - `public_transport` in `(platform, station)` gives that value;
  - `railway` in `(station, halt, tram_stop)` gives that value.
- **Precedence:** place, then transit_stop, then address, then area.
- **Nothing else** is classified, and `None` is returned.

**Reading:** use `osmium.FileProcessor(src).with_locations().with_areas()`.
- **Nodes** become points.
- **Areas** (closed ways and multipolygon relations) get:
  - a representative point (the centroid of the largest outer ring);
  - a bounding box;
  - `area_m2`, computed in local equirectangular metres;
  - `osm` set to `w<id>` for an area from a way, `r<id>` for one from a relation.
- **Open ways** are skipped (POIs on open ways are rare).
- **Batches:** rows are written in transactions of 10,000.

- [ ] **Step 1: Write the fixture.** It must contain:
  - a café node named "קפה ברזילי" with `addr:street`;
  - a dog park closed way (about 30×30 m) inside a park closed way (about 120×120 m);
  - a 5 ha park closed way with a café node inside, 10 m from a test point;
  - an address-only node;
  - a bus stop;
  - a `place=neighbourhood` node "נווה שאנן" with `name:en=Neve Sha'anan`;
  - a road way (`highway=residential`) and a node tagged only `building=yes`.
- [ ] **Step 2: Write the failing tests:**
  - `test_classify_by_key_not_by_value`: a made-up `shop=pottery_studio` gives
    `("place", "pottery_studio")`; `{"highway": "residential"}` gives `None`;
    `{"amenity": "cafe", "addr:housenumber": "5"}` gives `("place", "cafe")`;
    `{"addr:housenumber": "5"}` gives `("address", "address")`.
  - `test_build_counts_and_skips_roads`: building the fixture gives counts with `place ≥ 4`,
    `address == 1`, `area == 1` and `transit_stop == 1`. No row has kind `residential`, and
    none is a bare building.
  - `test_areas_have_outlines_and_size`: the dog park row has `rings`, an `area_m2` between
    700 and 1200, and an `osm` starting with `w`.
  - `test_names_are_kept_as_written`: the café's `name` is `"קפה ברזילי"` and its `name_en`
    is NULL.
- [ ] **Step 3: Run** `python -m pytest tests/test_location_map_index.py -q`. Expected: FAIL
  (module missing).
- [ ] **Step 4: Implement** `classify` and `build_index`.
- [ ] **Step 5: Run** the same command. Expected: PASS.
- [ ] **Step 6: Commit** `feat(location): build a map index from OSM data`.

### Task 3: Look places up

**Files:**
- Create: `apps/vault-server/src/services/location/map_lookup.py`
- Test: `apps/vault-server/tests/test_location_map_lookup.py`

**Interfaces:**
- Consumes: the Task 2 index (build it from the fixture in a test fixture).
- Produces:
  - `MapPlace(osm: str, group: str, kind: str, label: str, name: str | None, street: str | None, distance_m: float)`,
    a frozen dataclass with `to_dict()`. `to_dict` has no lat/lng.
  - `map_near(index: Path | None, lat: float, lng: float, spread_m: float) -> list[MapPlace]`
  - `map_area(index: Path | None, lat: float, lng: float) -> str | None`
  - `kind_words(kind: str) -> str`
  - `RADIUS_EXTRA_M = 30`, `RADIUS_CAP_M = 80`, `SMALL_AREA_M2 = 10_000`,
    `BIG_AREA_DISTANCE_M = 20`, `MAX_RESULTS = 8`, `AREA_NAME_RADIUS_M = 1500`.

**Rules** (spec §4.5, with the ranking amendment):
- **Radius** is `min(spread_m + 30, 80)`.
- **What counts:** only `place` rows (and `address` rows when no place qualifies). A row
  counts when its point or outline is within the radius, or its outline contains the point.
- **Rank:**
  1. containing areas of ≤ 1 ha, smallest first, at distance 0;
  2. then by distance. A containing area > 1 ha counts as 20 m.
- **`label`:**
  - `name_en`, else `name`, else `kind_words(kind)`;
  - for an address, `street` (without the number), else "an address".
- **`kind_words`:** a dict of common values (`cafe` "Café", `dog_park` "Dog park",
  `pharmacy` "Pharmacy", `convenience` "Convenience store", `park` "Park", `playground`
  "Playground", `supermarket` "Supermarket", `restaurant` "Restaurant", `bar` "Bar",
  `pub` "Pub", `bakery` "Bakery", `fitness_centre` "Gym", `sauna` "Sauna",
  `bus_stop` "Bus stop"; the builder may add more). The fallback is
  `kind.replace("_", " ").capitalize()`.
- **Unavailable index:** `index is None`, a missing file, or a sqlite error returns `[]`
  (or `None` from `map_area`) and logs once per process at WARNING with `safe_error`.
- **Opening:** `sqlite3.connect(f"file:{index}?mode=ro", uri=True)`, one connection per
  call.
- **`map_area`:** the nearest `area` row within 1.5 km, as `name_en or name`.

- [ ] **Step 1: Write the failing tests:**
  - `test_dog_park_inside_park_comes_first`.
  - `test_small_containing_area_ranks_first`.
  - `test_big_containing_area_counts_as_20m`: the café 10 m away ranks before the 5 ha park.
  - `test_radius_is_spread_plus_30_capped_at_80`: a place 70 m away is found with spread 45
    and not with spread 20; one 90 m away is never found.
  - `test_addresses_only_when_no_place`.
  - `test_transit_and_areas_are_not_buttons`: no `transit_stop` or `area` rows appear in
    `map_near`.
  - `test_labels`: an unnamed dog park is labelled "Dog park"; the café "קפה ברזילי"; an
    address shows its street only; `kind_words("pottery_studio") == "Pottery studio"`.
  - `test_map_area_names_the_neighbourhood`: gives "Neve Sha'anan".
  - `test_missing_or_corrupt_index_returns_nothing`: covers `None`, a missing path, and a
    file of garbage bytes.
  - `test_lookup_during_swap_sees_old_or_new`: build A, look up, `os.replace` B over it,
    look up; each lookup returns a complete result from A or B.
  - `test_to_dict_has_no_coordinates`.
- [ ] **Step 2: Run** `python -m pytest tests/test_location_map_lookup.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** Distances use `src.services.geo.haversine_m` for points. For
  outlines, measure point-to-segment in local metres; containment is ray casting on the
  outer rings minus the inner ones.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(location): look up map places near a stop`.

### Task 4: Download, check, build, swap, monthly

**Files:**
- Create: `apps/vault-server/src/services/location/map_update.py`
- Create: `apps/vault-server/scripts/location_map_update.py`
- Modify: `apps/vault-server/src/main.py` (`_location_clock_loop` and its start in `lifespan`)
- Test: `apps/vault-server/tests/test_location_map_update.py`

**Interfaces:**
- Consumes: `build_index`, `INDEX_VERSION` (Task 2), and the Task 1 settings.
- Produces:
  - `read_meta(map_dir: Path) -> dict | None`
  - `needs_update(meta: dict | None, now: dt.datetime, max_age_days: int) -> str | None`.
    It returns `"download"` when there is no meta, no index, or the index is too old;
    `"rebuild"` when `meta["index_version"] < INDEX_VERSION` and the pbf exists; otherwise
    `None`.
  - `update_map(map_dir: Path, url: str, *, now: dt.datetime, force: bool = False, fetch=None) -> dict`.
    It returns `{"action", "counts"}`. `fetch(url, dest: Path) -> str | None` streams to
    `dest` and returns Last-Modified; the default is httpx streaming. The md5 is read from
    `url + ".md5"`, from its first token.
  - `index_path(map_dir: Path) -> Path` (`map_dir / "index.sqlite"`).
  - `class MapUpdater(map_dir, url, max_age_days)` with `maybe_start(now) -> bool`. It checks
    at most once per local day, runs `update_map` in one daemon thread at a time, and never
    raises.

**Steps of `update_map`** (spec §4.3):
1. Download to `<name>.osm.pbf.part`. This is skipped for `"rebuild"`.
2. Check the md5 against the `.md5` file.
3. Build `index.sqlite.part`.
4. `os.replace` the pbf, then the index.
5. Write `meta.json` holding `url`, `last_modified`, `md5`, `built_at`, `index_version` and
   `counts`.

Any exception removes the `.part` files, leaves the previous files untouched and re-raises.
`MapUpdater` logs it with `safe_error`. The pbf name is the last path segment of the URL.

**Spans:** `location.map.update` carries `action`, `duration_s` and `counts.*`.

**Clock:** `_location_clock_loop(runtime, notifier, interval_seconds=60.0, map_updater=None)`
calls `map_updater.maybe_start(now)` inside its try. `lifespan` passes a `MapUpdater` when
`settings.location_map == "on"`.

**Script:** `scripts/location_map_update.py [--force]` runs `update_map` in the foreground
and prints the action and counts.

- [ ] **Step 1: Write the failing tests.** Each uses a fake `fetch` that copies the Task 2
  fixture (or writes bad bytes) and a fake `.md5`.
  - `test_first_run_downloads_builds_and_writes_meta`.
  - `test_md5_mismatch_keeps_old_copy`: an earlier good copy stays, no `.part` is left, and
    the call raises.
  - `test_failed_build_keeps_old_copy`: `build_index` is monkeypatched to raise; the old
    index still answers `map_near`.
  - `test_needs_update`: covers no meta, 29 days ("None"), 31 days ("download"), and an old
    `index_version` with the pbf present ("rebuild").
  - `test_rebuild_uses_the_kept_download`: `fetch` is not called.
  - `test_updater_checks_once_a_day_and_one_at_a_time`: two `maybe_start` calls on the same
    day give one run; while a run is in flight, a second does not start.
  - `test_clock_loop_starts_the_map_update`: one iteration of the loop with a fake runtime
    and updater calls `maybe_start`.
- [ ] **Step 2: Run** `python -m pytest tests/test_location_map_update.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the module, the script and the clock hook.
- [ ] **Step 4: Run** the same command, then `python -m pytest tests/test_location_clock.py -q`.
  Expected: PASS.
- [ ] **Step 5: Commit** `feat(location): monthly map download, checked and swapped`.

### Task 5: Use the map at a stop

**Files:**
- Modify: `apps/vault-server/src/services/fast_lane/places.py` (`Place.osm: str | None = None`;
  `_entry` writes it when set; `load_places` reads it; `learn_place(..., osm=None)`)
- Modify: `apps/vault-server/src/services/location/decide.py`
  (`Option.osm: str | None = None`, in `to_dict`/`from_dict`; `decide(..., map_options=())`)
- Modify: `apps/vault-server/src/services/location/guess.py` (MAP section, `map_id`)
- Modify: `apps/vault-server/src/services/location/messages.py` (`question_receipt(..., map_label=None, area=None)`)
- Modify: `apps/vault-server/src/services/location/pipeline.py` (`TripDeps.map_index: Path | None = None`;
  `_on_stopped`, `_answer`, `_log`)
- Modify: `apps/vault-server/src/services/location/runtime.py` (pass `chosen.osm`; set
  `map_index` in `build_runtime` when `location_map == "on"`)
- Test: `apps/vault-server/tests/test_location_map_stops.py`, plus updates to
  `test_location_guess.py` and `test_location_decide.py`

**Interfaces:**
- Consumes: `map_near`, `map_area`, `MapPlace` (Task 3), `index_path` (Task 4).
- Produces:
  - `Guess.map_id: str | None = None`.
  - `build_content(subject, trip_text, history, lines, map_places=())`, which adds a
    `MAP:` section with lines `m1 <label> (<kind words>, <n> m)` or `(none)`.
  - `guess(..., map_places=())`. The schema gains a required, nullable `map_id`. An unknown
    `map_id` is dropped as `"unknown map id"`. A guess citing a map id with no destination
    gets the map label as its destination. A guess with a `map_id` needs no `cites`.
  - `apply_answer(..., osm: str | None = None)`.
- **The prompt** (`SYSTEM_PROMPT`) adds that MAP lists what the map shows within a few
  metres of the stop. A stop guess should usually be one of them, citing its `map_id`. It
  may be an activity at that place ("Coffee at Café Barzilay").

**Pipeline at STOPPED** (spec §5.1–§5.5):
- **No user place found:**
  - call `map_near(deps.map_index, stop.lat, stop.lng, stop.spread_m)` and `map_area(...)`;
  - store `info["map"] = [m.to_dict() for m in mapped]` and `info["area"]`;
  - pass `mapped` to `_guess`, then into `guess`.
- **`decide`** takes `map_options = [Option(m.label, m.label, m.osm) for m in mapped]`.
  Options are composed in order — live guesses, then map options, then history — deduped by
  `names.name_key` and capped at 3.
- **`question_receipt`** gets `map_label` when `mapped[0].distance_m <= 15`, and `area`.
  - With `map_label`, "a new place" becomes `by <label>`. A usual stop keeps its wording.
  - `area` appends `, in <area>` after the distance.
- **`_answer`:**
  - `learn_place(..., osm=osm)`. When `osm` is None and the place's or purpose's
    `name_key` equals a label in `info["map"]`, use that entry's `osm`.
- **`_log`** adds `"map": info.get("map")` for stop events. Its entries have no
  coordinates.
- **Span:** `location.map.lookup` carries `count` and `top_distance_m`.

- [ ] **Step 1: Write the failing tests** (`test_location_map_stops.py`: the pipeline
  fixtures plus an index built from the fixture, with the stop placed at the fixture's café
  or dog park):
  - `test_map_places_become_buttons`: a model returning no guesses gives an asked stop whose
    options start with the map labels.
  - `test_a_guess_citing_the_map_keeps_the_place`: the model returns `map_id: "m1"` with no
    cites, giving the option "Coffee at קפה ברזילי" with destination "קפה ברזילי".
  - `test_unknown_map_id_is_dropped`.
  - `test_question_says_what_is_there`: "by Dog park" appears, and ", in Neve Sha'anan"
    appears when the area is known.
  - `test_tapping_a_map_option_saves_the_place_with_its_osm_id`: `places.json` gets the
    entry with `osm`, and the next STOPPED there is named silently.
  - `test_user_place_wins_and_skips_the_map`: `map_near` is monkeypatched to raise; the stop
    is named from the user place.
  - `test_no_index_means_todays_behaviour`: `map_index=None` gives the same options and text
    as before.
  - `test_trip_purpose_still_never_names_a_stop`: a map-cited guess equal to the trip's
    purpose is dropped.
  - `test_hebrew_and_long_map_labels`: a 40-character Hebrew label is cut to 32 with "…",
    and the data is `trip:<id>:s1:a0`.
  - `test_model_and_log_never_see_coordinates_or_osm_ids`: the stop's lat (4 decimals) is
    absent from `model.calls[*]["content"]` and from the decision log; `osm` ids are absent
    from the model content.
- [ ] **Step 2: Run** `python -m pytest tests/test_location_map_stops.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the changes listed under Files.
- [ ] **Step 4: Run** `python -m pytest tests/ -q`. Expected: all pass. Existing tests that
  pin the guess schema's required fields, or the `Option` dict, are updated to the new
  fields. List each update in the commit message.
- [ ] **Step 5: Commit** `feat(location): map places at a stop`.

### Task 6: Replay, real data, docs

**Files:**
- Modify: `apps/vault-server/scripts/location_replay.py` (`--map`: for each stop of each
  replayed trip, print the local time, the top 3 `map_near` labels and `map_area`. No
  coordinates)
- Modify: `CLAUDE.md`:
  - the repository tree (`data/map/`);
  - the location awareness bullet (map copy, buttons, update);
  - the quick commands (`location_map_update.py`, `location_replay.py --map`).
- Modify: `docs/specs/2026-11-14-location-map-design.md`: `Status: built`.
- Test: `apps/vault-server/tests/test_location_replay.py` (`test_map_flag_prints_labels_not_coordinates`)

- [ ] **Step 1: Write the failing test** for `--map`, using the fixture index and a
  one-stop trip. The output contains the label and no 4-decimal coordinate.
- [ ] **Step 2: Run** it. Expected: FAIL. **Implement**, then run it again. Expected: PASS.
- [ ] **Step 3: Real copy.** Run `python scripts/location_map_update.py`. Expected: the
  action `download`, a counts line, and `data/map/meta.json` written. The download is
  121 MB, taking minutes.
- [ ] **Step 4: Rebuild derived and replay.** Run `python scripts/location_rebuild.py --from
  2026-11-05 --to 2026-11-14`, then `python scripts/location_replay.py --from 2026-11-05
  --to 2026-11-14 --map`. Pass: the right place is in the top 3 for at least 3 of these 4:
  - 14 Nov ~16:23: Barzilay;
  - 14 Nov ~16:05: Dog park;
  - 9 Nov ~20:29: a shop or convenience store;
  - 7 Nov ~07:54: a café at Gan Meir.

  Record the result in the ledger.
- [ ] **Step 5: Full suites.** Run the server's `python -m pytest tests/ -q`, then the
  bot's `npx vitest run` and `npx tsc --noEmit`. Expected: all pass.
- [ ] **Step 6: Commit** `feat(location): map replay, docs`.
