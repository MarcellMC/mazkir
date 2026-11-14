# Location awareness: a local map copy

**Status:** design, for approval · **Date:** 2026-11-14 · **Builds on:**
`docs/specs/2026-11-10-location-trips-design.md` (and its 2026-11-14 addendum)

## 1. Why

The first live walk (2026-11-14) had two stops: the local dog park and Café Barzilay.
Mazkir knew neither. It has no map, so all it can do is ask "what's this?", or guess
from context, and that guess named both stops after the walk. The user wants Mazkir
to know what is at a spot the first time they stop there.

OpenStreetMap already knows. Checked on 2026-11-14:
- **Café Barzilay** is a café named "קפה ברזילי", 10 m from the stop.
- **The dog park** is mapped as a dog park (`leisure=dog_park`) 1 m from the stop. It
  has no name: "Electra" is the user's own name for it.

So map data answers "what kind of place is this", often "what is it called", and the
user's own answer fills in the rest.

## 2. Goals, non-goals, anti-goals

**Goals**
- **Map places as buttons.** A stop question offers the places that are actually there
  ("Café Barzilay", "Dog park"), so a first visit takes one tap.
- **A local copy, kept current.** The map is stored on this machine and refreshed
  automatically, monthly.
- **The full download is kept**, so later features (bus rides, addresses,
  "you're passing a pharmacy") need no new download and no new design for the data.
- **An index for lookups by position.** It holds places, addresses, area names and
  transit stops.

**Non-goals (this part)**
- Bus and train rides: which line, boarding and alighting stops. This is part 2, on the
  backlog (§9), and waits until the user rides buses more often.
- Location reminders ("buy at a pharmacy" when passing one). The index makes these
  possible, but they are a separate feature.
- Naming stops silently from the map. The 2026-11-14 rule stands: only a place the user
  named is named without asking. The map makes the question one tap; it does not skip it.
- Maps for other countries. The download is Israel (§4.1). Another region is one
  setting, but it is not built or tested.

**Anti-goals: these would make it a failure even if it works**
- **A coordinate leaving the machine.** Lookups never go to an online map service. The
  only network traffic is downloading the country file, which is the same for everyone.
- **A coordinate reaching a model, span, log line or the vault.** The existing rule
  applies to everything here. The model sees place names, kinds and distances only.
- **A map entry overriding the user.** The user's own places (`data/places.json`) always
  win, and a map entry never renames or moves one.
- **Mazkir breaking without a map.** With no copy, or while one is being built, stops are
  asked about exactly as they are today.

## 3. What the user sees

A new spot with map data:

```
📍 You've been here since 16:23 — 690 m from home, a new place. What's this?
[Café Barzilay] [Just a pause] [✎ Something else] [Later]
```

The usual dog park, before the user has named it:

```
📍 You've been here since 16:05 — 180 m from home, your usual stop (6 earlier trips). What's this?
[Dog park] [Just a pause] [✎ Something else] [Later]
```

Tapping **[Café Barzilay]** names the stop "Café Barzilay" and saves it as the user's
place, linked to the map entry. Every later visit is then named without a question. To
call the dog park "Dog park Electra", the user taps ✎ and types it; this is what they did
on 2026-11-14.

Between buttons, the model chooses (§5.3). "On a dog walk" points to the dog park, not
the kiosk next to it. It can also phrase a button as an activity at that place: "Coffee
at Café Barzilay".

## 4. The map copy

### 4.1 Source

Geofabrik's daily extract of OpenStreetMap for Israel and Palestine:
`https://download.geofabrik.de/asia/israel-and-palestine-latest.osm.pbf`. On 2026-11-14
it was 121 MB, modified the night before. Geofabrik publishes an `.md5` file next to it,
and the download is checked against it. The URL is a setting (`LOCATION_MAP_URL`), so
another region is a change of settings only.

### 4.2 Files (`data/map/`, gitignored with the rest of `data/`)

- `<name>.osm.pbf`: the full download, kept (user's decision). It is replaced only by a
  newer download that has been checked.
- `index.sqlite`: the lookup index (§4.4).
- `meta.json`: the source URL, the download's Last-Modified time, its md5, when the index
  was built, the index format version and the row counts per kind.

### 4.3 Updates

- **Automatic, monthly.** Once a day the server checks the copy. If there is none, or
  `meta.json` says the index was built more than 30 days ago, it updates in the background
  (one thread, at most one update at a time). The check is part of the server's existing
  60 s location clock loop and runs only when `LOCATION_MAP=on`.
- **By hand:** `python scripts/location_map_update.py [--force]` does the same thing and
  prints the counts.
- **Steps:**
  1. Download to `*.part`.
  2. Check the md5.
  3. Build `index.sqlite.part` from it.
  4. Rename both into place, the pbf first, then the index.
  5. Write `meta.json`.

  A failure at any step deletes the `.part` files and keeps the old copy working. It is
  logged once, by type only (`model.safe_error`). Up to two copies of the pbf and two
  indexes exist during an update, about 0.3 GB in all.
- **Index format version.** If the code's version is newer than the one in `meta.json`,
  the index is rebuilt from the kept pbf without downloading. This is the point of keeping
  the full download.
- **When an update happens:** the server is told only "the map was updated", with counts.
  Nothing is sent to the user.

### 4.4 What the index holds

Each row: `osm` (type and id, e.g. `n123`, `w456`), `group`, `kind`, `name`, `name_en`,
`addr` (street, house number, city, when tagged), a representative point, and for an area
its outline. A spatial index (SQLite R*Tree, available here: SQLite 3.50.4) covers each
row's bounding box.

| Group | Kept when | `kind` |
|---|---|---|
| **place** | it has any of `amenity`, `shop`, `leisure`, `tourism`, `healthcare`, `office`, `craft`, `sport`, whatever the value | the value, e.g. `cafe`, `dog_park`, `pharmacy`, `park` |
| **address** | it has `addr:housenumber`, and is not already kept as a place | `address` |
| **area** | `place` is `suburb`, `quarter`, `neighbourhood` or `city` | the value |
| **transit_stop** | `highway=bus_stop`, `public_transport=platform` or `station`, or `railway` is `station`, `halt` or `tram_stop` | `bus_stop`, `station` … |

The rule is about OpenStreetMap's keys, not about activities: whatever OpenStreetMap files
under `shop` is kept, including shop types nobody listed. Not indexed: roads, land use,
power lines, building outlines that carry no address, and bus *routes*. Routes stay in the
kept pbf for part 2.

The reader is pyosmium (`osmium` on PyPI, version 4.3.2 at the time of writing; it builds
areas from ways and multipolygons). This is a new dependency in `pyproject.toml`.

### 4.5 Lookup

`map_near(lat, lng, radius_m) -> list[MapPlace]`. It is pure, reads `index.sqlite`, and
returns at most 8 results, ranked in this order:
1. areas of up to 1 ha that **contain** the point, smallest first (the dog park before the
   park around it);
2. everything else, by distance from the point to the outline or point. A larger area that
   contains the point counts as 20 m away, so a café 10 m from the stop ranks ahead of the
   campus or big park around it.

The radius is the stop's spread plus 30 m, with a cap of 80 m. Addresses are returned only
when no place is within the radius. Transit stops are indexed but **not returned** in this part: a stop at a
bus stop is asked about as today, until part 2 (§9) knows what waiting for a bus looks like. Area names (`area` group) are returned separately as
`map_area(lat, lng)`: the nearest neighbourhood or suburb within 1.5 km.

`MapPlace` holds `osm`, `group`, `kind`, `label`, `name` and `distance_m`.

- **`label`** is what a button shows: the name when there is one, otherwise the kind in
  words.
- **Kind words** come from one table of OpenStreetMap values to English words (`dog_park`
  → "Dog park", `cafe` → "Café"). A value missing from the table falls back to the value
  with `_` turned into a space and the first letter capitalised. A missing word is
  therefore never an error.
- **Names:** `name_en` is used when present, otherwise `name`. Hebrew names stay in
  Hebrew. A Latin spelling is never invented.

## 5. How a stop uses it

### 5.1 Order of precedence at a stop

1. **The user's place** (`places.json`, as today): named silently. A pause spot stays
   quiet.
2. **Map places within the radius:** passed to the guess, and used as buttons.
3. **Neither:** asked as today: "a new place", or "your usual stop".

### 5.2 The question text

- **A map place contains or is within 15 m of the stop** (the top result): the question
  says what is there, e.g. "📍 Here since 16:23 — 690 m from home, by Café Barzilay.
  What's this?"
- **Otherwise:** the question reads as today.
- **The area name** is added when known: "690 m from home, in Neve Sha'anan".

### 5.3 The guess

`describe_trip` gains a MAP section, with lines `m1…` holding the label, kind and distance
of each place in `map_near`, and nothing else. The guess schema gains `map_id` (nullable),
handled like `history_id`:
- A guess citing a map line keeps that place as its destination. Code checks that the id
  exists.
- A guess may name an activity at that place ("Coffee at Café Barzilay") or the place
  itself.

The 2026-11-14 stop rules stand: a stop guess needs a destination and must not repeat the
trip's purpose.

### 5.4 Buttons

There are at most 3 option buttons, chosen in this order:
1. the model's kept guesses;
2. if fewer than 3, the top map places by rank (code, not the model);
3. the history purposes that have a destination.

Duplicates by name are removed. If the model call fails, the buttons are the map places
alone.

### 5.5 Answers

- **Tapping a map-based option** names the stop. It also saves the place in
  `places.json` under the button's label, with `osm: <id>` and the stop's centre (the
  existing `learn_place`).
- **A typed answer** (✎) is saved as today. If the answer names a map place within the
  radius (the same words, by `names.name_key`), that place's `osm` id is stored with it.
- **`osm` link.** A saved place's `osm` link is used only to show the map's name and
  kind in the decision log. The user's name always wins.

## 6. Settings and switches

| Setting | Default | Meaning |
|---|---|---|
| `LOCATION_MAP` | `on` (user, 2026-11-14: on from the start) | `on`: download, update and use the map. `off`: nothing in this design runs, and stops behave as now |
| `LOCATION_MAP_URL` | the Geofabrik URL above | another region |
| `LOCATION_MAP_MAX_AGE_DAYS` | `30` | how old the index may get before an update |

The automatic update runs in the location clock, so with `LOCATION_AWARENESS=off` nothing is
downloaded, whatever `LOCATION_MAP` says. The script works either way.

## 7. Privacy and logging

- **No position leaves the machine.** Lookups are local file reads; the only network
  call is the country download.
- **The model** sees labels, kinds, distances and area names. It never sees coordinates,
  OSM ids or addresses' house numbers. An address shows as street only ("on Ha'Yarkon").
- **The decision log** (`location-trips.jsonl`) gains `map: [{id, osm, kind, label,
  distance_m}]` per stop decision. It has no coordinates.
- **Spans:** `location.map.update` carries duration and counts; `location.map.lookup`
  carries the result count and the top distance.
- **The index holds public map data,** so it does not count as personal location data.
  The decision log ties an OSM id to a stop and is local, like the rest of `data/`.

## 8. How we know it works

1. **Unit tests** on a small hand-made `.osm` file (pyosmium reads XML too):
   - the filtering rule by keys;
   - addresses kept only when not a place;
   - containment ranking (dog park inside a park);
   - kind words and their fallback;
   - the ranking and radius;
   - a missing or corrupt index returning nothing.
2. **Update tests** with a fake download:
   - md5 mismatch;
   - a failure mid-build keeping the old copy;
   - an index version bump rebuilding without a download;
   - the age check.
3. **Replay on real stops** (`scripts/location_replay.py --map`, offline):
   - **Barzilay** (14 Nov): "Café Barzilay" offered.
   - **Dog park** (14 Nov): "Dog park" offered.
   - **The convenience store** (9 Nov 20:29): a shop offered.
   - **The Gan Meir coffee stop** (7 Nov): a café offered.

   Pass: the right place is among the buttons for at least 3 of the 4.
4. **Live:** the next walk with a new stop.

## 9. Backlog: part 2 and later (not built here)

- **Transit rides.**
  - A stop at a transit stop is "waiting", not a place to ask about.
  - A ride leg between two stops gives candidate lines from the route relations in the
    kept pbf ("Bus 375, Savidor → Kiryat Gat"), named silently when only one line fits.
  - Needs real bus rides in the location data to design against.
  - OpenStreetMap's Israeli bus data may lag; the Ministry of Transport's GTFS feed is the
    fallback source to measure against.
- **Location reminders:** "you're passing a pharmacy, and 'buy X' is on your list", from
  `map_near` along a leg and open todos.
- **Addresses for people's homes:** "Alex's" linked to its address, so a stop there is
  named silently.

## 10. Left to the builder

- **The index schema** beyond the fields in §4.4: column types, how outlines are stored,
  and the batch size during the build.
- **Kind words:** the exact table, as long as the fallback holds.
- **The download client:** reuse `httpx`, which is already a dependency, with streaming
  writes.
- **The test `.osm` fixture:** its contents, as long as it exercises §8.1.

## 11. Calls made by Claude, not by the user

- **Update cadence:** monthly, automatic, checked daily. The user asked "when, how and how
  often" and did not object to monthly.
- **The `LOCATION_MAP` switch,** separate from awareness; default on per the user.
- **Containment ranking** limited to areas up to 1 ha; a larger containing area counts as 20 m
  (a café beside the stop should not lose to the campus around it).
- **Map places are buttons only**, never silent names (consistent with the 2026-11-14 rule).
- **Lookup radius** of spread + 30 m, capped at 80 m; addresses only when no place is near.
- **Hebrew names are shown as they are** when there is no English name.
