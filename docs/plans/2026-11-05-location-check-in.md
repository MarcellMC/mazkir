# Location Check-in L0 (Spike) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Log every Telegram location point to disk, write nothing else, and report what came in, so L1's thresholds are tuned on real data.

**Architecture:** A bot Composer sends live-location edits, live starts and one-off check-ins to a new `POST /locations/points`. The bot still passes check-ins on to the agent. The server appends each point to `data/locations/raw/{date}.jsonl` under one lock. A pure report module, with a script, reads those files and prints share sessions, sampling, silences, accuracy, coverage, ingest health and a naïve stay-point pass. It can also write a labelling template.

**Tech Stack:** FastAPI + pydantic v2 (vault-server, Python 3.14), grammY + vitest (telegram-bot, TypeScript), pytest.

**Spec:** `docs/specs/2026-11-05-location-check-in-design.md`. This plan implements §4 (L0) only.

## Global Constraints

- **Branch.** Work on `feat/location-l0`; `master` takes PRs only. The first commit also carries the spec and this plan.
- **One switch, one name, both sides.** `LOCATION_INGEST=off|log`, default `off`. `off` keeps today's behaviour exactly, on the bot as well as the server.
  - The spec names the switch only for the server (§4.3), but "`off` keeps today's behaviour exactly" (§4.1) forces the bot to have it too. Otherwise a live start would stop reaching the agent even with ingest off.
- **The spike writes nothing but raw point files** (and, on request, a label template). No visits, no blocks, no model calls, no external network calls.
- **Coordinates go only to `data/locations/`.** They never go to spans (`input.value` included), log lines, Loki or a model. The bot's failure log carries `kind`, `status` and `err`, never `lat` or `lng`.
- **The file date comes from a parsed `ts` converted to `VAULT_TIMEZONE`, by calendar day** (not the 05:00 logical day). It is never taken from a request string.
- **No location update ever reaches `/message`**, except a one-off check-in, which is forwarded exactly as today.
- **Report defaults, from the spec:**
  - moving = implied speed > 1 km/h;
  - a silence is a gap > 15 minutes;
  - waking hours are 07:00–23:00;
  - the naïve stay-point pass uses 150 m, 8 minutes, and drops points with accuracy above 200 m.
- **Commits** are `feat(location): …` / `test(location): …` / `docs(location): …`, ending with the session's attribution lines.

## Review Focus

1. **A `ts` with no offset** (`"2026-11-06T08:14:03"`) is a 422, not a point filed under the server's local guess. Pinned in Task 1.
2. **The same update stored twice**, from a redelivery after a bot crash (same `source`, `message_id`, `ts`, `lat`, `lng`), counts once in every report number. Pinned in Task 3.
3. **A torn last line** in a raw file, from a crash mid-append, is skipped, and the report still runs and says how many lines it skipped. Pinned in Tasks 1 and 3.
4. **A check-in whose POST fails** (server down, or a 404 because ingest is off on the server) still reaches the agent, and the bot does not throw. Pinned in Task 2.
5. **With the bot's `LOCATION_INGEST=off`**, a live start and a one-off location both reach `messageHandler` exactly as today, and nothing is posted. Pinned in Task 2.

---

### Task 1: Server ingest

**Files:**
- Create: `apps/vault-server/src/services/location_store.py`
- Create: `apps/vault-server/src/api/routes/locations.py`
- Modify: `apps/vault-server/src/config.py`: add two settings beside the fast-lane block
- Modify: `apps/vault-server/src/main.py`: import and include `locations_router` (with the other routers, around lines 259–287)
- Modify: `CLAUDE.md`: add the endpoint to "vault-server API Endpoints", `data/locations/` to the repository tree, and a short "Location ingest (L0)" architecture bullet pointing at the spec
- Test: `apps/vault-server/tests/test_location_store.py`, `apps/vault-server/tests/test_locations_route.py`

**Interfaces:**
- Produces (`location_store.py`):
  - `raw_path(root: Path, day: date) -> Path` returns `root / "raw" / f"{day.isoformat()}.jsonl"`
  - `file_date(ts: datetime, tz: str) -> date`
  - `append_point(root: Path, point: dict, tz: str) -> float | None` appends one JSON line to the file for `file_date(point["ts"])`. It returns the seconds since the previous point appended by this process for the same `source`, or `None` for the first one.
  - `load_points(root: Path, day: date) -> tuple[list[dict], int]` returns the parsed lines in file order, plus the count of lines skipped as unparseable. A missing file gives `([], 0)`.
- Produces (route): `POST /locations/points` with body `LocationPoint`, answering `{"ok": true}`.
- Produces (settings): `settings.location_ingest: str = "off"`, and `settings.location_data_path: Path = Path(os.getenv("LOCATION_DATA_PATH", str(Path.home() / "dev" / "mazkir" / "data" / "locations")))`.

- [ ] **Step 1: Create the branch and commit the docs**

```bash
git checkout -b feat/location-l0
git add docs/specs/2026-11-05-location-check-in-design.md docs/plans/2026-11-05-location-check-in.md
git commit -m "docs(location): check-in design and L0 spike plan"
```

- [ ] **Step 2: Write the failing store tests** in `tests/test_location_store.py`

```python
def test_a_point_after_local_midnight_goes_to_the_next_days_file(tmp_path):
    # 22:30Z on 5 Nov is 00:30 on 6 Nov in Asia/Jerusalem (+02:00)
    append_point(tmp_path, point(ts="2026-11-05T22:30:00Z"), "Asia/Jerusalem")
    assert raw_path(tmp_path, date(2026, 11, 6)).exists()
    assert not raw_path(tmp_path, date(2026, 11, 5)).exists()

def test_a_late_point_goes_to_its_own_days_file_not_todays(tmp_path): ...
    # ts two days ago → that day's file

def test_append_returns_the_gap_since_the_previous_point_of_the_same_source(tmp_path):
    assert append_point(tmp_path, point(ts="2026-11-06T08:00:00+02:00"), TZ) is None
    assert append_point(tmp_path, point(ts="2026-11-06T08:02:30+02:00"), TZ) == 150.0

def test_concurrent_appends_produce_whole_lines(tmp_path):
    # 8 threads × 50 appends → load_points returns 400 points and 0 skipped

def test_a_torn_last_line_is_skipped_and_counted(tmp_path):
    # write two good lines then '{"lat": 32.0' with no newline
    points, skipped = load_points(tmp_path, day)
    assert len(points) == 2 and skipped == 1

def test_a_missing_file_is_empty(tmp_path):
    assert load_points(tmp_path, date(2026, 1, 1)) == ([], 0)
```

`point(**over)` is a local helper returning a valid dict: `source="telegram"`, `kind="live"`, `message_id=7`, `lat=32.0853`, `lng=34.7818`, `accuracy_m=12.0`, and `ts` as a `datetime`. The store receives `ts` as a `datetime`, which is what the route hands it, and writes it as ISO 8601.

The module keeps its gap memory process-wide, so add an autouse fixture that clears it (expose `_reset_for_tests()`).

- [ ] **Step 3: Run them; expect import failures**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_location_store.py -v`
Expected: FAIL, `ModuleNotFoundError: src.services.location_store`

- [ ] **Step 4: Implement `location_store.py`**

- One module-level `threading.Lock` guards both the append and the per-source last-`ts` dict.
- Open in `"a"` mode, write `json.dumps(point, default=str, ensure_ascii=False) + "\n"`, and create `raw/` on demand.
- `ts` is serialised with `.isoformat()`.
- `load_points` tolerates lines that fail `json.loads`.

- [ ] **Step 5: Run the store tests; expect PASS**

- [ ] **Step 6: Write the failing route tests** in `tests/test_locations_route.py`

Build the app as `test_fast_lane_receipt_routes.py` does: a bare `FastAPI()` with `include_router`. Patch `settings.location_ingest` and `settings.location_data_path` with `monkeypatch.setattr(settings, …)`.

```python
def test_a_valid_point_is_stored_with_received_at(client, tmp_path):
    r = client.post("/locations/points", json=BODY)          # ts "2026-11-06T06:14:03Z"
    assert r.status_code == 200 and r.json() == {"ok": True}
    [line], _ = load_points(tmp_path, date(2026, 11, 6))
    assert line["kind"] == "live" and line["lat"] == 32.0853 and "received_at" in line

def test_unknown_fields_are_rejected(client):           # {"speed": 3} added → 422
def test_a_ts_without_offset_is_rejected(client):       # "2026-11-06T08:14:03" → 422   (Review Focus 1)
def test_latitude_out_of_range_is_rejected(client):     # lat 91 → 422
def test_off_answers_404_and_writes_nothing(client_off, tmp_path):
    assert client_off.post("/locations/points", json=BODY).status_code == 404
    assert not (tmp_path / "raw").exists()
def test_a_check_in_keeps_its_venue_title(client, tmp_path):   # kind "check_in", venue_title "Superpharm"
```

- [ ] **Step 7: Run them; expect FAIL** (no route module)

- [ ] **Step 8: Implement the route and settings**

`LocationPoint(BaseModel)`, with `model_config = ConfigDict(extra="forbid")`:

| Field | Type |
|---|---|
| `source` | `str = Field(pattern=r"^[a-z_]{1,32}$")` |
| `kind` | `Literal["live", "live_start", "check_in"]` |
| `message_id` | `int \| None = None` |
| `ts` | `AwareDatetime` |
| `lat` | `float = Field(ge=-90, le=90)` |
| `lng` | `float = Field(ge=-180, le=180)` |
| `accuracy_m` | `float \| None = Field(None, ge=0)` |
| `heading` | `int \| None = None` |
| `live_period` | `int \| None = None` |
| `venue_title` | `str \| None = Field(None, max_length=200)` |

`router = APIRouter(prefix="/locations", tags=["locations"], dependencies=[Depends(verify_api_key)])`.

`def ingest_point(point: LocationPoint) -> dict` is a **plain `def`**, so it runs in the threadpool, off the event loop, while it holds the lock:
1. If `settings.location_ingest != "log"`, raise `HTTPException(404, "Location ingest is off")`.
2. Build `point.model_dump()` plus `received_at` (now, in `VAULT_TIMEZONE`, isoformat).
3. Call `append_point(settings.location_data_path, …, settings.vault_timezone)`.
4. Inside `get_tracer().start_as_current_span("location.ingest")` with `with_span_status`, set exactly three attributes: `location.kind`, `location.accuracy_m` (`-1` when absent) and `location.gap_s` (`-1` when `None`). No `input.value`, no coordinates.

Register in `main.py` next to the other routers.

- [ ] **Step 9: Run both test files, then the whole server suite**

Run: `python -m pytest tests/test_location_store.py tests/test_locations_route.py -v && python -m pytest tests/ -q`
Expected: all PASS, with no new failures elsewhere.

- [ ] **Step 10: Update CLAUDE.md** as listed under Files.

- [ ] **Step 11: Commit**

```bash
git add apps/vault-server/src/services/location_store.py apps/vault-server/src/api/routes/locations.py \
  apps/vault-server/src/config.py apps/vault-server/src/main.py apps/vault-server/tests/test_location_store.py \
  apps/vault-server/tests/test_locations_route.py CLAUDE.md
git commit -m "feat(location): POST /locations/points appends raw points behind LOCATION_INGEST"
```

---

### Task 2: Bot ingest

**Files:**
- Create: `apps/telegram-bot/src/conversations/location.ts`
- Create: `apps/telegram-bot/src/bot-utils/update-kind.ts`
- Modify: `apps/telegram-bot/src/config.ts`: add `locationIngest: boolean` (`process.env.LOCATION_INGEST === "log"`)
- Modify: `apps/telegram-bot/src/api/client.ts`: add the `LocationPoint` type and `postLocationPoint`
- Modify: `apps/telegram-bot/src/bot.ts`:
  - replace the inline `kind` ternary (lines ~76–86) with `updateKind(ctx)`;
  - register `locationHandler` after `callbackHandlers` and before `messageHandler`.
- Modify: `CLAUDE.md`: one sentence under "Telegram Bot Commands" on live location and check-ins
- Test: `apps/telegram-bot/tests/conversations/location.test.ts`, `apps/telegram-bot/tests/bot-utils/update-kind.test.ts`

**Interfaces:**
- Consumes: `POST /locations/points` and its body fields (Task 1).
- Produces:
  - `export interface LocationPoint { source: "telegram"; kind: "live" | "live_start" | "check_in"; message_id: number; ts: string; lat: number; lng: number; accuracy_m?: number; heading?: number; live_period?: number; venue_title?: string }`
  - `api.postLocationPoint(point: LocationPoint): Promise<{ ok: boolean }>`
  - `export function toLocationPoint(msg: Message, kind: LocationPoint["kind"]): LocationPoint`
  - `export const locationHandler: Composer<Context>`
  - `export function updateKind(ctx: Pick<Context, "message" | "editedMessage" | "callbackQuery">): string`

- [ ] **Step 1: Write the failing tests**

`location.test.ts`:
- Mock `config.js` with `locationIngest: true` by default, toggled per test through a hoisted object. Mock `api.postLocationPoint`, and spy on `logger.warn`.
- Drive `locationHandler.middleware()(ctx, next)` the way `tests/callbacks/receipt.test.ts` does. A ctx stub needs `update` (`{edited_message}` or `{message}`), `message` / `editedMessage`, `chat` and `from` for grammY's filter to match. If the stub proves brittle, build the ctx with grammY's `new Context(update, api, me)`.

```ts
it("an edited live location posts one point stamped with edit_date and never reaches next")
  // editedMessage: { message_id: 7, date: 1762409000, edit_date: 1762409643,
  //                  location: { latitude: 32.0853, longitude: 34.7818, horizontal_accuracy: 12, heading: 270, live_period: 28800 } }
  // → postLocationPoint called with kind "live", ts new Date(1762409643 * 1000).toISOString(),
  //   accuracy_m 12, heading 270, live_period 28800; next not called
it("a live share starting posts live_start and does not reach the agent")   // message.location.live_period set → next not called
it("a one-off location posts a check_in and still reaches the agent")      // no live_period → posted, then next called once
it("a venue is a check_in carrying its title")                             // message.venue.title "Superpharm"
it("a check-in whose post fails still reaches the agent and logs no coordinates")   // Review Focus 4
  // postLocationPoint rejects with ApiError(404) → next called; logger.warn called with event_type "location_ingest_failed",
  // kind "check_in", status 404; JSON.stringify of the logged object contains neither "32.08" nor "34.78"
it("a failed live post is logged and swallowed")                           // rejects with Error → handler resolves
it("with ingest off nothing is posted and every location reaches next")    // Review Focus 5: live start, one-off and edit all call next
```

`update-kind.test.ts`:

```ts
expect(updateKind({ message: { text: "hi" } })).toBe("text")
expect(updateKind({ message: { photo: [{}] } })).toBe("photo")
expect(updateKind({ editedMessage: { location: {...} } })).toBe("live_location")
expect(updateKind({ message: { location: { ..., live_period: 900 } } })).toBe("live_location")
expect(updateKind({ message: { location: {...} } })).toBe("location")
expect(updateKind({ callbackQuery: { data: "x" } })).toBe("callback")
expect(updateKind({})).toBe("other")
```

- [ ] **Step 2: Run them; expect FAIL**

Run: `cd apps/telegram-bot && npx vitest run tests/conversations/location.test.ts tests/bot-utils/update-kind.test.ts`
Expected: FAIL, modules not found.

- [ ] **Step 3: Implement**

- `toLocationPoint`:
  - `ts` comes from `msg.edit_date ?? msg.date` for `"live"`, and from `msg.date` otherwise, converted with `new Date(s * 1000).toISOString()`;
  - the location is `msg.location ?? msg.venue?.location`;
  - optional fields are omitted when Telegram did not send them.
- `locationHandler`:
  - `on("edited_message:location")` → if `!config.locationIngest`, `return next()`; else post `"live"`.
  - `on("message:location")` → if off, `return next()`. With `location.live_period`, post `"live_start"` and stop. Otherwise post `"check_in"`, then `await next()`.
  - A private `ingest(point)` awaits the post in `try/catch`. On failure it logs `logger.warn({ event_type: "location_ingest_failed", kind, status: err instanceof ApiError ? err.status : "error", err: String(err) }, "location_ingest_failed")` and returns normally.
- `updateKind`: keep the existing order (text, photo, location, callback, other), with `live_location` checked before `location`.

- [ ] **Step 4: Run the two files; expect PASS. Then the whole bot suite and the typecheck**

Run: `npx vitest run && npx tsc --noEmit`
Expected: all PASS, exit 0. `tests/conversations/message.test.ts` must still pass unchanged: one-off locations still reach `messageHandler`.

- [ ] **Step 5: Update CLAUDE.md** as listed under Files.

- [ ] **Step 6: Commit**

```bash
git add apps/telegram-bot/src apps/telegram-bot/tests CLAUDE.md
git commit -m "feat(location): bot sends live location and check-ins to /locations/points"
```

---

### Task 3: The report: sessions, sampling, silences, accuracy, coverage, ingest health

**Files:**
- Create: `apps/vault-server/src/services/geo.py`
- Create: `apps/vault-server/src/services/location_report.py`
- Create: `apps/vault-server/scripts/location_spike_report.py`
- Test: `apps/vault-server/tests/test_location_report.py`

**Interfaces:**
- Consumes: `load_points(root, day)` and `raw_path` (Task 1).
- Produces (`geo.py`): `haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float`
- Produces (`location_report.py`), every function pure:
  - `Point` is a frozen dataclass: `source, kind, message_id, ts: datetime, received_at: datetime | None, lat, lng, accuracy_m, live_period, raw: dict`
  - `normalise(lines: list[dict]) -> list[Point]` parses, **dedupes on `(source, message_id, ts, lat, lng)`**, and sorts by `ts`
  - `Session` is a dataclass: `message_id, started: datetime, live_period: int | None, expires_at: datetime | None, last_point: datetime, n_points: int, last_fields: list[str]`
  - `share_sessions(points) -> list[Session]` covers `live` / `live_start` points, grouped by `(source, message_id)`. `last_fields` is the sorted keys of the last point's raw line.
  - `intervals(points) -> list[tuple[float, bool]]` gives `(seconds, moving)` between consecutive points of the **same session**; moving means implied speed > 1 km/h
  - `summary(values: list[float]) -> dict` → `{"n", "p50", "p90", "max"}` (nearest-rank; `None`s on empty)
  - `silences(points, min_gap_s=900) -> list[tuple[datetime, datetime, float]]` gives `(start, end, distance_m)` within a session
  - `still_scatter_m(points) -> list[float]`: for each run of ≥ 3 consecutive points joined by still intervals, the p90 distance from the run's centroid
  - `coverage(sessions, day: date, tz: str, waking=(7, 23)) -> float` is the share of that day's waking minutes inside `[started, last_point]` of any session, from 0.0 to 1.0. It is a lower bound, and the rendered line says so.
  - `ingest_health(points, bot_log: list[dict], day: date, tz: str) -> dict` → `{"points", "failures", "lag": summary(...)}`. It counts `event_type == "location_ingest_failed"` lines whose `ts` falls on `day`.
  - `render_report(days: dict[date, list[Point]], skipped: dict[date, int], bot_log: list[dict], tz: str) -> str`

- [ ] **Step 1: Write the failing tests**

Build fixtures with a helper `pt(minute, lat, lng, msg=7, kind="live", **raw)` on one fixed day.

```python
def test_a_redelivered_update_counts_once():                       # Review Focus 2
    assert len(normalise([line(0), line(0), line(5)])) == 2
def test_points_are_ordered_by_ts_not_by_file_order():
def test_a_session_reports_its_start_period_expiry_and_last_fields():
    # live_start at 08:00 with live_period 3600 then edits to 08:40, last edit has no live_period
    # → expires_at 09:00, last_point 08:40, n_points 3, "live_period" not in last_fields
def test_intervals_split_moving_from_still():
    # 0 m in 5 min → still; 500 m in 5 min (6 km/h) → moving
def test_intervals_do_not_bridge_two_sessions():
def test_check_ins_are_not_sessions():
def test_summary_uses_nearest_rank():
    assert summary([60, 120, 180, 240, 600]) == {"n": 5, "p50": 180, "p90": 600, "max": 600}
def test_a_long_silence_reports_the_distance_either_side():
    # gap 08:00→09:30 with 20 m apart → one silence (…, …, ≈20)
def test_coverage_of_a_session_from_07_to_15_is_half_the_waking_day():
    assert coverage([session(7, 15)], day, TZ) == pytest.approx(0.5)
def test_ingest_health_counts_failures_on_that_day_only_and_lag():
def test_the_report_names_every_section_and_its_skipped_lines():   # Review Focus 3
    text = render_report({day: pts}, {day: 1}, [], TZ)
    for heading in ("Share sessions", "Sampling", "Silences", "Accuracy", "Coverage", "Ingest health"):
        assert heading in text
    assert "1 unreadable line skipped" in text
```

- [ ] **Step 2: Run; expect FAIL** (`python -m pytest tests/test_location_report.py -v`)

- [ ] **Step 3: Implement `geo.py` and `location_report.py`**

- `haversine_m` uses an Earth radius of 6 371 000 m.
- Leave `MergerService._haversine` alone; L1 can move it onto `geo.py`.
- `render_report` prints one block per date (Share sessions, Silences, Coverage, Ingest health), then the range totals (Sampling, split moving/still; Accuracy, `accuracy_m` summary plus a `still_scatter_m` summary).
- The check-in count goes under Share sessions.
- Times print as `HH:MM` in `tz`.

- [ ] **Step 4: Run; expect PASS**

- [ ] **Step 5: Write the script** `scripts/location_spike_report.py [DATE | --from D --to D]`

- Build it like `scripts/fast_lane_shadow_report.py`: insert `sys.path`, import `settings`, default to today.
- Load each day with `load_points(settings.location_data_path, d)`, plus the next day's file, so a session crossing midnight is whole.
- Read `settings.logs_dir / "telegram-bot.jsonl"` tolerantly.
- Print `render_report`.
- Parse arguments with `argparse`.

- [ ] **Step 6: Smoke-run it on an empty data directory**

Run: `LOCATION_DATA_PATH=$(mktemp -d) python scripts/location_spike_report.py 2026-11-05`
Expected: exit 0, and every heading printed with "no points".

- [ ] **Step 7: Commit**

```bash
git add apps/vault-server/src/services/geo.py apps/vault-server/src/services/location_report.py \
  apps/vault-server/scripts/location_spike_report.py apps/vault-server/tests/test_location_report.py
git commit -m "feat(location): spike report — sessions, sampling, silences, accuracy, coverage, ingest health"
```

---

### Task 4: Naïve stay-point pass and the label template

**Files:**
- Modify: `apps/vault-server/src/services/location_report.py`
- Modify: `apps/vault-server/scripts/location_spike_report.py`: add `--write-labels`
- Modify: `CLAUDE.md`: add the report command to "Quick Commands" under a "Location spike (L0)" comment
- Test: `apps/vault-server/tests/test_location_report.py`

**Interfaces:**
- Consumes: `Point`, `normalise`, `haversine_m` (Task 3).
- Produces:
  - `Visit` is a dataclass: `start: datetime, end: datetime, lat: float, lng: float, n_points: int`
  - `stay_points(points, radius_m=150, min_minutes=8, max_accuracy_m=200) -> list[Visit]`
  - `labels_template(day: date, visits: list[Visit], tz: str) -> dict`
  - `render_report` gains a final "Naïve visits" section (the list from `stay_points`, as `HH:MM–HH:MM  (n points)`)

- [ ] **Step 1: Write the failing tests**

```python
def test_twenty_minutes_within_150_m_is_one_visit():
    # points every 2 min 08:00–08:20 jittering ≤ 40 m, then a point 1 km away at 08:25
    [v] = stay_points(pts)
    assert (v.start.strftime("%H:%M"), v.end.strftime("%H:%M")) == ("08:00", "08:20")
def test_five_minutes_still_is_not_a_visit():
def test_a_low_accuracy_point_is_ignored_for_segmentation():   # accuracy_m 800 inside the visit → same single visit
def test_a_silence_with_no_movement_stays_inside_one_visit():  # 08:00, 08:05, then 09:30 at the same spot → one visit to 09:30
def test_check_ins_take_part_like_any_point():
def test_the_label_template_lists_detected_visits_with_empty_names():
    t = labels_template(day, [visit(8, 0, 8, 20)], TZ)
    assert t == {"date": "2026-11-06", "visits": [{"start": "08:00", "end": "08:20", "name": "", "detected": True}],
                 "missed": [], "notes": ""}
def test_the_report_lists_naive_visits():
```

- [ ] **Step 2: Run; expect FAIL**

- [ ] **Step 3: Implement `stay_points`.** This is the classic anchor-based pass (Li et al., 2008), chosen because it is deterministic and easy to read. L1's online detector replaces it.

```
usable = [p for p in points if p.accuracy_m is None or p.accuracy_m <= max_accuracy_m]
i = 0
while i < len(usable):
    j = i + 1
    while j < len(usable) and haversine(usable[i], usable[j]) <= radius_m:
        j += 1
    if usable[j-1].ts - usable[i].ts >= min_minutes:
        emit Visit(usable[i].ts, usable[j-1].ts, mean lat/lng of i..j-1, j - i)
        i = j
    else:
        i += 1
```

- [ ] **Step 4: Add `--write-labels`** to the script

- It writes `labels_template(...)` as indented JSON to `settings.logs_dir.parent / "eval" / "location" / f"{date}.json"`, which is `data/eval/location/`, gitignored with `data/`.
- It **refuses to overwrite** an existing file: print the path and exit 1, since that file holds your labels.
- It accepts only a single `DATE`.

- [ ] **Step 5: Run the report tests and the whole server suite; expect PASS**

Run: `python -m pytest tests/test_location_report.py -v && python -m pytest tests/ -q`

- [ ] **Step 6: Check `--write-labels` refuses an existing file**

Run:

```bash
D=$(mktemp -d)
LOCATION_DATA_PATH=$D LOGS_DIR=$D/logs python scripts/location_spike_report.py 2026-11-05 --write-labels
LOCATION_DATA_PATH=$D LOGS_DIR=$D/logs python scripts/location_spike_report.py 2026-11-05 --write-labels
```

Expected: the first run writes `$D/eval/location/2026-11-05.json` and exits 0; the second exits 1 and names the file.

- [ ] **Step 7: Update CLAUDE.md** Quick Commands:

```bash
# Location spike (L0): LOCATION_INGEST=log on both the server and the bot
python scripts/location_spike_report.py --from 2026-11-06 --to 2026-11-10
python scripts/location_spike_report.py 2026-11-07 --write-labels   # then fill in names, fix times, add "missed"
```

- [ ] **Step 8: Commit, push, open the PR**

```bash
git add apps/vault-server CLAUDE.md
git commit -m "feat(location): naïve stay-point pass and label template for the spike"
git push -u origin feat/location-l0
gh pr create --title "Location check-in L0: log points, report on them" --body "<summary + how to run the spike, per spec §4.6>"
```

---

## After merge (not code)

1. Set `LOCATION_INGEST=log` in both `apps/vault-server/.env` and `apps/telegram-bot/.env`, and restart both.
2. Share live location with the bot, choosing "until I turn it off". Keep it going for about 5 days, covering a workday, a weekend day and an errand day.
3. Run the report over the range, write label templates for two days, and fill them in.
4. Write the answers back into spec §2.2 and §5, and decide go / swap source / stop against §4.6.
