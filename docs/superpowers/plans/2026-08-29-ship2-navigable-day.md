# Ship 2 — Navigable `/day` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/day` becomes a browsable day viewer backed by the events ledger — navigable by date, rendering blocks and coverage gaps read-only.

**Architecture:** `MergerService` grows two inputs it lacks (the daily-note body, and standalone scheduled habits) so that everything `schedule[]` carried arrives as a block instead. `/daily` gains `?date=`, returns `blocks[]` / `gaps[]` / `coverage{}` and drops `schedule[]`, delegating block-building to the events service rather than re-merging. The bot renders it as a rich message with in-body navigation buttons, edited in place on each tap.

**Tech Stack:** Python 3.14 / FastAPI / pytest on the server; TypeScript / grammY / vitest on the bot; `@mazkir/shared-types` between them.

**Spec:** `docs/superpowers/specs/2026-08-29-ship2-navigable-day-design.md`

## Global Constraints

- Every agent tool returns the `{ok, data|error, _items}` shape from `src/services/tool_response.py`. Never a bare dict. (No tools change here, but the constraint binds any that do.)
- `tests/conftest.py` redirects `LOGS_DIR` and `MAZKIR_AUDIT_LOG_PATH` to temp dirs. No test may write to `data/logs/`.
- `memory/` is the user's live Obsidian vault — a separate nested git repo, gitignored, and **absent from a worktree**. Never write to a path starting `memory/`.
- `data/events/` holds the user's real event store. No test may write to it; construct `EventsService(tmp_path)` instead.
- Server tests run from `apps/vault-server` with the venv active: `source venv/bin/activate && python -m pytest tests/ -q`. The venv is a symlink; never recreate it.
- **Baselines: server 785 passing, bot 85 passing (10 files), webapp 21 passing.** Plus one pre-existing `StarletteDeprecationWarning` from `fastapi/testclient.py`. No other warnings are acceptable.
- **This ship is read-only.** No approve, no classify, no edit mode. Do not add write paths.
- Commit per task, conventional prefixes. Every commit message ends with:
  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01D8PvuwXbv8umP56LMmaeG4
  ```
- Never `git add -A` a directory in this repo — `node_modules` symlinks live at the repo root and inside `apps/telegram-bot`. Stage named paths.

## Scope addition discovered during planning

The spec's §3.2 assumes note-derived blocks "reconcile by `source_ids` the same way calendar events do." **Calendar events do not currently reconcile at all.** `MergerService` emits no `source_ids`, so `EventsService.refresh_events` step 1 can never match a merged event; it is appended as fresh (new `id`) while the persisted copy is dropped for not being `manual`/`photo`. Verified:

```
open 1: id=evt_36a44de3 state=suggested
        (mark approved + activity=meetings, save)
open 2: id=evt_2908ffbd state=suggested activity=None
id stable    : False
approval kept: False
```

Harmless for read-only rendering, fatal for Ship 5. Task 2 fixes it, because Task 3 depends on the mechanism working.

## File Structure

**Created:**
- `apps/vault-server/src/services/day_coverage.py` — pure arithmetic: union block intervals, compute covered/unaccounted and the gap spans. No I/O, no date parsing beyond one helper, so it can be tested exhaustively.
- `apps/telegram-bot/src/formatters/day-rich.ts` — builds the `InputRichMessage` for `/day`. Separate from `telegram.ts` because that file is already ~260 lines of HTML `parse_mode` formatters and this is a different output type.
- `apps/telegram-bot/tests/formatters/day-rich.test.ts`

**Modified:**
- `apps/vault-server/src/services/merger_service.py` — `source_ids` on every created event; new note-body and standalone-habit inputs; `_infer_category` removed.
- `apps/vault-server/src/api/routes/events.py` — pass the note body through to the merger.
- `apps/vault-server/src/api/routes/daily.py` — `?date=`, `blocks[]`/`gaps[]`/`coverage{}`, `schedule[]` deleted.
- `packages/shared-types/src/daily.ts` — `DailyBlock`, `DailyGap`, `DayCoverage`; `schedule` removed from `DailyResponse`.
- `apps/telegram-bot/src/bot-utils/send-rich.ts` — `editRich` sibling; corrected comment.
- `apps/telegram-bot/src/commands/day.ts` — rich render, split error handling.
- `apps/telegram-bot/src/callbacks/index.ts` — `day:<date>` handler.
- `apps/telegram-bot/package.json` — grammy `^1.46.0`.
- `CLAUDE.md` — corrections.

**Tests:**
- `apps/vault-server/tests/test_merger_service.py`
- `apps/vault-server/tests/test_day_coverage.py` (new)
- `apps/vault-server/tests/test_daily_route.py`
- `apps/telegram-bot/tests/formatters/day-rich.test.ts` (new)

---

### Task 1: Upgrade grammY for rich buttons

Rich buttons (`<tg-button-row>`) need Bot API 10.3 types. `grammy@1.46.0` pins `@grammyjs/types@5.0.0` exactly. Landing this alone means a dependency problem cannot be mistaken for a Ship 2 bug.

**Files:**
- Modify: `apps/telegram-bot/package.json`
- Modify: `apps/telegram-bot/src/bot-utils/send-rich.ts`

**Interfaces:**
- Produces, used by Tasks 7 and 8: `@grammyjs/types@5.0.0` exports `InputRichMessage<F>` (now generic), `RichMessageButton`, `RichBlockButtons`.

- [ ] **Step 1: Bump the dependency**

In `apps/telegram-bot/package.json`, change the `grammy` dependency:

```json
"grammy": "^1.46.0"
```

Then from the repo root:

```bash
npm install
```

- [ ] **Step 2: Confirm the versions resolved**

```bash
node -e "const l=require('./node_modules/.package-lock.json'); for (const [k,v] of Object.entries(l.packages||{})) if (/grammy/.test(k)) console.log(k, v.version)"
```

Expected: `node_modules/grammy 1.46.0` and `node_modules/@grammyjs/types 5.0.0`.

- [ ] **Step 3: Run the typecheck to see what breaks**

```bash
cd apps/telegram-bot && npx tsc --noEmit -p tsconfig.json
```

Expected: FAIL. `InputRichMessage` is generic in 5.0.0 (`InputRichMessage<F>`), and `src/bot-utils/send-rich.ts` uses it bare at two places (the `richToPlainText` parameter and the `sendRich` parameter).

- [ ] **Step 4: Supply the type argument**

In `apps/telegram-bot/src/bot-utils/send-rich.ts`, the import stays as-is. Change the two bare uses to supply grammY's file flavor. Replace:

```ts
export function richToPlainText(msg: InputRichMessage): string {
```

with:

```ts
export function richToPlainText(msg: InputRichMessage<InputFile>): string {
```

and replace:

```ts
  msg: InputRichMessage,
```

with:

```ts
  msg: InputRichMessage<InputFile>,
```

Add `InputFile` to the grammy import at the top of the file:

```ts
import type { Context, InputFile } from "grammy";
```

If `tsc` reports a different concrete error than the generic-arity one, fix what it actually says rather than forcing this shape — report the deviation in your task report.

- [ ] **Step 5: Typecheck and run the suite**

```bash
cd apps/telegram-bot && npx tsc --noEmit -p tsconfig.json && npx vitest run
```

Expected: typecheck clean, **85 passed (10 files)**, output otherwise pristine. Two pre-existing `rich_message_fallback` WARN lines from `tests/bot-utils/send-rich.test.ts` are expected — that suite deliberately exercises the fallback path.

- [ ] **Step 6: Commit**

```bash
git add apps/telegram-bot/package.json apps/telegram-bot/src/bot-utils/send-rich.ts package-lock.json
git commit -m "chore(bot): upgrade grammy to 1.46 for rich message buttons"
```

---

### Task 2: Give merged events stable `source_ids`, and drop the dead category guesser

Two changes to the same four constructor methods, so they land together.

**Files:**
- Modify: `apps/vault-server/src/services/merger_service.py`
- Test: `apps/vault-server/tests/test_merger_service.py`

**Interfaces:**
- Produces, used by Tasks 3, 4 and 6:
  - `MergedEvent.source_ids: dict[str, str]` — new field, default `{}`
  - Every event `MergerService.merge` returns carries exactly one `source_ids` entry, deterministic across calls for the same input.
  - `MergedEvent.activity` is now always `None` from the merger. Classification is Ship 6.

- [ ] **Step 1: Write the failing tests**

Append to `apps/vault-server/tests/test_merger_service.py`:

```python
from src.services.events_service import EventsService


def _cal(id_="cal1", summary="Standup", start="2026-08-29T09:05", end="2026-08-29T10:00"):
    return {"id": id_, "summary": summary, "start": start, "end": end,
            "completed": False, "calendar": "Mazkir"}


def test_calendar_event_carries_its_calendar_id():
    m = MergerService()
    events = m.merge(calendar_events=[_cal()], timeline_data={"visits": [], "activities": []})
    assert events[0].source_ids == {"calendar_id": "cal1"}


def test_unplanned_stop_source_id_is_stable_for_the_same_visit():
    visit = {"name": "Xoho", "start_time": "2026-08-29T11:00", "end_time": "2026-08-29T12:00",
             "duration_minutes": 60, "lat": 32.07, "lng": 34.78, "place_id": "p123"}
    m = MergerService()
    a = m.merge(calendar_events=[], timeline_data={"visits": [visit], "activities": []})
    b = m.merge(calendar_events=[], timeline_data={"visits": [dict(visit)], "activities": []})
    assert a[0].source_ids == b[0].source_ids
    assert a[0].source_ids != {}


def test_merger_no_longer_guesses_an_activity():
    """CATEGORY_KEYWORDS targeted the single-facet model Phase 1 replaced.
    Blocks must arrive unclassified; Ship 6 fills `activity`."""
    m = MergerService()
    events = m.merge(
        calendar_events=[_cal(summary="Gym session")],
        timeline_data={"visits": [], "activities": []},
    )
    assert events[0].activity is None


def test_merged_event_survives_a_reopen_with_its_id_and_state(tmp_path):
    """Regression: without source_ids, refresh_events appends every fresh
    event as new and drops the persisted copy, so approval could never
    survive an open. Ship 5 depends on this holding."""
    m = MergerService()
    svc = EventsService(tmp_path)

    def fresh():
        return [e.model_dump() for e in m.merge(
            calendar_events=[_cal()], timeline_data={"visits": [], "activities": []},
        )]

    first = svc.refresh_events("2026-08-29", fresh())
    original_id = first[0]["id"]
    first[0]["state"] = "approved"
    first[0]["activity"] = "meetings"
    svc.save_events("2026-08-29", first)

    second = svc.refresh_events("2026-08-29", fresh())
    assert len(second) == 1
    assert second[0]["id"] == original_id
    assert second[0]["state"] == "approved"
    assert second[0]["activity"] == "meetings"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_merger_service.py -q -k "source_id or reopen or guesses"
```

Expected: FAIL. `source_ids` is not a field on `MergedEvent`; `activity` is `"gym"`; the reopen test shows a changed `id` and `state='suggested'`.

- [ ] **Step 3: Add the field and the id helper**

In `apps/vault-server/src/services/merger_service.py`, add to `MergedEvent` immediately after the `source` / `confidence` block:

```python
    # Reconciliation key. EventsService.refresh_events matches a freshly
    # merged event to its persisted counterpart through this, which is what
    # lets an id — and anything the user set on the event — survive a
    # re-merge. Exactly one entry; the key names the originating source.
    source_ids: dict[str, str] = Field(default_factory=dict)
```

Add a module-level helper below `CATEGORY_KEYWORDS`' former position:

```python
def _stable_id(*parts: object) -> str:
    """A deterministic short id for a source that has no id of its own.

    Timeline visits and transit segments carry no stable identifier, so we
    derive one from the fields that identify them. Same input, same id, on
    every re-merge — which is the whole point.
    """
    raw = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(raw.encode()).hexdigest()[:12]
```

Add `import hashlib` to the imports at the top of the file.

- [ ] **Step 4: Populate `source_ids` in all four constructors, and stop guessing**

In `_create_merged_event`, add to the `MergedEvent(...)` call:

```python
            source_ids={"calendar_id": str(cal.get("id", "")) or _stable_id(
                cal.get("summary"), cal.get("start"))},
```

In `_create_calendar_event`, replace `activity=self._infer_category(name),` with nothing (drop the line) and add:

```python
            source_ids={"calendar_id": str(cal.get("id", "")) or _stable_id(
                name, cal.get("start"))},
```

In `_create_unplanned_stop`, drop the `activity=self._infer_category(visit["name"]),` line and add:

```python
            source_ids={"visit_id": _stable_id(
                visit["start_time"], visit.get("place_id"), visit["name"])},
```

In `_create_transit_event`, add:

```python
            source_ids={"transit_id": _stable_id(
                activity["start_time"], activity["mode"])},
```

Then delete the now-unused `_infer_category` static method and the `CATEGORY_KEYWORDS` dict above `class MergerService`.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_merger_service.py tests/test_events_service.py -q
```

Expected: PASS. If an existing merger test asserted an inferred `activity`, update it to assert `None` — the guess is gone deliberately.

- [ ] **Step 6: Run the whole server suite**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/ -q
```

Expected: **789 passed** (785 baseline + 4 new), 1 pre-existing warning.

- [ ] **Step 7: Commit**

```bash
git add apps/vault-server/src/services/merger_service.py apps/vault-server/tests/test_merger_service.py
git commit -m "fix(events): give merged events stable source_ids so they survive a re-merge"
```

---

### Task 3: Timed checkboxes in the daily note become blocks

**Files:**
- Modify: `apps/vault-server/src/services/merger_service.py`
- Modify: `apps/vault-server/src/api/routes/events.py`
- Test: `apps/vault-server/tests/test_merger_service.py`

**Interfaces:**
- Consumes: `MergedEvent.source_ids` (Task 2); `parse_all_todos(body) -> list[Todo]` from `src.services.daily_tasks`, where `Todo` has `text`, `state`, `section`, `scheduled_at`, `duration_minutes`.
- Produces, used by Task 6: `MergerService.merge(..., daily_body: str = "", date: str = "")` emits one `MergedEvent` per timed checkbox with `type="task"`, `source="daily-note"`, `source_ids={"note_line": ...}`.

- [ ] **Step 1: Write the failing tests**

Append to `apps/vault-server/tests/test_merger_service.py`:

```python
NOTE_WITH_TIMED = """\
## Tasks
- [ ] 14:00 — Visit dentist (60m)
- [ ] Order dog food (30m)

## Notes
- [x] 09:00 — Take meds (5m)
"""


def test_timed_checkboxes_become_blocks_from_any_section():
    m = MergerService()
    events = m.merge(
        calendar_events=[], timeline_data={"visits": [], "activities": []},
        daily_body=NOTE_WITH_TIMED, date="2026-08-29",
    )
    by_name = {e.name: e for e in events}
    assert set(by_name) == {"Visit dentist", "Take meds"}
    assert by_name["Visit dentist"].start_time == "2026-08-29T14:00"
    assert by_name["Visit dentist"].end_time == "2026-08-29T15:00"
    assert by_name["Visit dentist"].duration_minutes == 60
    assert by_name["Visit dentist"].source == "daily-note"


def test_untimed_checkbox_is_not_a_block():
    """An untimed todo has no interval. It stays a todo; Ship 5 places it."""
    m = MergerService()
    events = m.merge(
        calendar_events=[], timeline_data={"visits": [], "activities": []},
        daily_body="## Tasks\n- [ ] Order dog food (30m)\n", date="2026-08-29",
    )
    assert events == []


def test_timed_checkbox_without_a_duration_is_zero_length():
    m = MergerService()
    events = m.merge(
        calendar_events=[], timeline_data={"visits": [], "activities": []},
        daily_body="## Tasks\n- [ ] 14:00 — Standup\n", date="2026-08-29",
    )
    assert events[0].start_time == events[0].end_time == "2026-08-29T14:00"
    assert events[0].duration_minutes == 0


def test_note_block_source_id_is_stable_across_merges():
    m = MergerService()
    kw = dict(calendar_events=[], timeline_data={"visits": [], "activities": []},
              daily_body=NOTE_WITH_TIMED, date="2026-08-29")
    a = m.merge(**kw)
    b = m.merge(**kw)
    assert [e.source_ids for e in a] == [e.source_ids for e in b]
    assert all("note_line" in e.source_ids for e in a)


def test_note_block_records_completion():
    m = MergerService()
    events = m.merge(
        calendar_events=[], timeline_data={"visits": [], "activities": []},
        daily_body=NOTE_WITH_TIMED, date="2026-08-29",
    )
    by_name = {e.name: e for e in events}
    assert by_name["Take meds"].tokens_earned == 0
    assert by_name["Take meds"].habit is None
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_merger_service.py -q -k "checkbox or note_block"
```

Expected: FAIL with `TypeError: merge() got an unexpected keyword argument 'daily_body'`.

- [ ] **Step 3: Add the constructor**

In `apps/vault-server/src/services/merger_service.py`, add this method to `MergerService`:

```python
    def _create_note_block(self, todo, date: str) -> MergedEvent:
        """A timed checkbox is a block: known start, known length.

        Untimed checkboxes are filtered out by the caller — without a start
        there is no interval, and coverage arithmetic needs one.
        """
        start = f"{date}T{todo.scheduled_at}"
        minutes = todo.duration_minutes or 0
        hh, mm = (int(x) for x in todo.scheduled_at.split(":"))
        end_total = hh * 60 + mm + minutes
        end = f"{date}T{end_total // 60 % 24:02d}:{end_total % 60:02d}"
        return MergedEvent(
            name=todo.text,
            type="task",
            start_time=start,
            end_time=end,
            duration_minutes=minutes,
            source="daily-note",
            confidence="high",
            source_ids={"note_line": _stable_id(date, todo.text, todo.scheduled_at)},
        )
```

Add the import at the top of the file:

```python
from src.services.daily_tasks import parse_all_todos
```

- [ ] **Step 4: Wire it into `merge`**

Change the `merge` signature to add two keyword arguments after `daily`:

```python
    def merge(
        self,
        calendar_events: list[dict],
        timeline_data: dict,
        habits: list[dict] | None = None,
        daily: dict | None = None,
        daily_body: str = "",
        date: str = "",
    ) -> list[MergedEvent]:
```

Then insert a new step immediately before the existing `# Step 4: Sort chronologically` comment:

```python
        # Timed checkboxes from the note body. The note is a worksurface; the
        # ledger is the source of truth for temporal data, so a checkbox that
        # has acquired a time is a block. It is regenerated from the note on
        # every merge and matched by source_ids, so nothing needs persisting
        # and no write path is involved.
        if daily_body and date:
            for todo in parse_all_todos(daily_body):
                if todo.scheduled_at:
                    merged.append(self._create_note_block(todo, date))
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_merger_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Pass the note body through the events route**

In `apps/vault-server/src/api/routes/events.py`, inside `_merge_from_sources`, the daily note is currently read for its frontmatter only:

```python
    daily = {}
    try:
        daily = vault.read_daily_note(date)
        daily = daily.get("metadata", {})
    except Exception:
        pass
```

Replace that block with:

```python
    daily = {}
    daily_body = ""
    try:
        raw_daily = vault.read_daily_note(date)
        daily = raw_daily.get("metadata", {})
        daily_body = raw_daily.get("content", "")
    except Exception:
        pass
```

and add the two new arguments to the `merger.merge(...)` call:

```python
        daily_body=daily_body,
        date=date.isoformat(),
```

- [ ] **Step 7: Run the whole server suite**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/ -q
```

Expected: **794 passed** (789 + 5 new), 1 pre-existing warning.

- [ ] **Step 8: Commit**

```bash
git add apps/vault-server/src/services/merger_service.py apps/vault-server/src/api/routes/events.py apps/vault-server/tests/test_merger_service.py
git commit -m "feat(events): timed checkboxes in the daily note become blocks"
```

---

### Task 4: Scheduled habits become standalone blocks

Today a habit is only ever *attached* to a calendar event whose name happens to match. A habit with `scheduled_at` and no calendar entry appears nowhere in the ledger — but does appear in today's `schedule[]`, so dropping `schedule[]` without this would lose it.

**Files:**
- Modify: `apps/vault-server/src/services/merger_service.py`
- Modify: `apps/vault-server/src/api/routes/events.py`
- Test: `apps/vault-server/tests/test_merger_service.py`

**Interfaces:**
- Consumes: `_stable_id` and `MergedEvent.source_ids` (Task 2).
- Produces, used by Task 6: a `MergedEvent` per unattached scheduled habit, `type="habit"`, `source="habit"`, `source_ids={"habit_slug": ...}`.
- The `habits` list entries gain two keys, supplied by `events.py`: `scheduled_at: str | None` and `duration_minutes: int`.

- [ ] **Step 1: Write the failing tests**

Append to `apps/vault-server/tests/test_merger_service.py`:

```python
def _habit(name="Dog Walk", scheduled_at="07:00", completed=False, duration=40,
           done_count=0, target=1):
    return {"name": name, "completed_today": completed, "streak": 3,
            "tokens_per_completion": 5, "scheduled_at": scheduled_at,
            "duration_minutes": duration, "completions_today": done_count,
            "daily_target": target}


def test_scheduled_habit_with_no_calendar_event_becomes_a_block():
    m = MergerService()
    events = m.merge(
        calendar_events=[], timeline_data={"visits": [], "activities": []},
        habits=[_habit()], date="2026-08-29",
    )
    assert len(events) == 1
    assert events[0].name == "Dog Walk"
    assert events[0].type == "habit"
    assert events[0].start_time == "2026-08-29T07:00"
    assert events[0].end_time == "2026-08-29T07:40"
    assert events[0].source_ids == {"habit_slug": "2026-08-29:dog-walk"}


def test_unscheduled_habit_is_not_a_block():
    m = MergerService()
    events = m.merge(
        calendar_events=[], timeline_data={"visits": [], "activities": []},
        habits=[_habit(scheduled_at=None)], date="2026-08-29",
    )
    assert events == []


def test_habit_already_attached_to_a_calendar_event_is_not_duplicated():
    """The existing name-match attaches habit data to the calendar event.
    Emitting a standalone block too would show the same thing twice."""
    m = MergerService()
    events = m.merge(
        calendar_events=[_cal(summary="Dog Walk", start="2026-08-29T07:00",
                              end="2026-08-29T07:40")],
        timeline_data={"visits": [], "activities": []},
        habits=[_habit()], date="2026-08-29",
    )
    assert len(events) == 1
    assert events[0].source == "calendar"
    assert events[0].habit["name"] == "Dog Walk"


def test_habit_block_carries_todays_progress():
    """Carried forward from Phase 1: the bot could only ever render a binary
    box because completions_today never reached it. It has to survive the
    merger for /daily to turn it into "1/2"."""
    m = MergerService()
    events = m.merge(
        calendar_events=[], timeline_data={"visits": [], "activities": []},
        habits=[_habit(done_count=1, target=2)], date="2026-08-29",
    )
    assert events[0].habit["completions_today"] == 1
    assert events[0].habit["daily_target"] == 2


def test_completed_habit_block_carries_its_tokens():
    m = MergerService()
    events = m.merge(
        calendar_events=[], timeline_data={"visits": [], "activities": []},
        habits=[_habit(completed=True)], date="2026-08-29",
    )
    assert events[0].habit["completed"] is True
    assert events[0].tokens_earned == 5
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_merger_service.py -q -k habit
```

Expected: FAIL — the standalone tests return `[]` because nothing emits habit blocks.

- [ ] **Step 3: Add the constructor**

In `apps/vault-server/src/services/merger_service.py`, add to `MergerService`:

```python
    def _create_habit_block(self, habit: dict, date: str) -> MergedEvent:
        """A scheduled habit with no calendar event of its own.

        Habits that DO have a calendar event are attached to it by the
        existing name match in step 1; emitting a block for those as well
        would render the same commitment twice.
        """
        name = habit.get("name", "")
        scheduled_at = habit["scheduled_at"]
        minutes = habit.get("duration_minutes") or 0
        hh, mm = (int(x) for x in scheduled_at.split(":"))
        end_total = hh * 60 + mm + minutes
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        completed = habit.get("completed_today", False)
        return MergedEvent(
            name=name,
            type="habit",
            start_time=f"{date}T{scheduled_at}",
            end_time=f"{date}T{end_total // 60 % 24:02d}:{end_total % 60:02d}",
            duration_minutes=minutes,
            habit={
                "name": name,
                "completed": completed,
                "streak": habit.get("streak", 0),
                "tokens_earned": habit.get("tokens_per_completion", 0),
                # /daily renders these as "1/2". Without them the bot can only
                # show a binary box, which is the Phase 1 §11 carry-forward.
                "completions_today": habit.get("completions_today", 0),
                "daily_target": habit.get("daily_target", 1),
            },
            tokens_earned=habit.get("tokens_per_completion", 0) if completed else 0,
            source="habit",
            confidence="high",
            source_ids={"habit_slug": f"{date}:{slug}"},
        )
```

Add `import re` to the imports if not already present.

- [ ] **Step 4: Wire it into `merge`**

In step 1 of `merge`, the habit match already records which habit was attached. Collect those names. Change the habit-attach block inside the calendar loop from:

```python
            habit_match = self._find_matching_habit(event.name, habits)
            if habit_match:
```

to:

```python
            habit_match = self._find_matching_habit(event.name, habits)
            if habit_match:
                attached_habits.add(habit_match["name"])
```

(keeping the existing body that follows), and declare the set alongside `matched_visit_indices` near the top of `merge`:

```python
        attached_habits: set[str] = set()
```

Then insert this immediately before the note-body step added in Task 3:

```python
        # Scheduled habits that no calendar event claimed. Without this,
        # dropping schedule[] would lose a habit that has a time but no
        # calendar entry — which is most of them.
        if date:
            for h in habits:
                if h.get("scheduled_at") and h.get("name") not in attached_habits:
                    merged.append(self._create_habit_block(h, date))
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_merger_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Supply the two new habit keys from the events route**

In `apps/vault-server/src/api/routes/events.py`, the habits list is built in `_merge_from_sources`. Add the two fields the merger now reads. Change the `habits.append({...})` call to include:

```python
                "scheduled_at": meta.get("scheduled_at") or meta.get("scheduled_time") or None,
                "duration_minutes": meta.get("duration_minutes", 0),
                "completions_today": completions_today(h, date),
                "daily_target": daily_target_of(meta),
```

and extend the existing `habit_completion` import at the top of the file:

```python
from src.services.habit_completion import completions_today, daily_target_of, is_complete_today
```

The `scheduled_at` fallback to `scheduled_time` mirrors `_habit_scheduled_at` in `routes/daily.py`: `scheduled_time` is the legacy key the habit template used to write, and habits created before the rename still carry it. `completions_today` and `daily_target_of` already exist in `src/services/habit_completion.py`; they have simply never reached the merger, which is why the bot can only render a binary box today.

- [ ] **Step 7: Run the whole server suite**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/ -q
```

Expected: **799 passed** (794 + 5 new), 1 pre-existing warning.

- [ ] **Step 8: Commit**

```bash
git add apps/vault-server/src/services/merger_service.py apps/vault-server/src/api/routes/events.py apps/vault-server/tests/test_merger_service.py
git commit -m "feat(events): scheduled habits become standalone blocks"
```

---

### Task 5: Coverage and gap arithmetic

Pure functions, no I/O. This is the arithmetic most likely to be subtly wrong, so it gets its own module and exhaustive tests.

**Files:**
- Create: `apps/vault-server/src/services/day_coverage.py`
- Test: `apps/vault-server/tests/test_day_coverage.py` (new file)

**Interfaces:**
- Produces, used by Task 6:
  - `@dataclass(frozen=True) Gap: start: str, end: str, minutes: int` — `start`/`end` are `"HH:MM"`
  - `@dataclass(frozen=True) Coverage: covered_minutes: int, unaccounted_minutes: int`
  - `minutes_into_day(timestamp: str, date: str) -> int | None`
  - `day_coverage(intervals: list[tuple[int, int]], elapsed_minutes: int) -> tuple[list[Gap], Coverage]`

- [ ] **Step 1: Write the failing tests**

Create `apps/vault-server/tests/test_day_coverage.py`:

```python
"""Coverage and gap arithmetic for a day's blocks."""

import pytest

from src.services.day_coverage import (
    Coverage,
    Gap,
    day_coverage,
    minutes_into_day,
)

DAY = 24 * 60


class TestMinutesIntoDay:
    def test_iso_timestamp_on_the_day(self):
        assert minutes_into_day("2026-08-29T09:05", "2026-08-29") == 545

    def test_bare_time_is_read_as_that_day(self):
        assert minutes_into_day("09:05", "2026-08-29") == 545

    def test_timestamp_on_another_day_returns_none(self):
        assert minutes_into_day("2026-08-28T09:05", "2026-08-29") is None

    def test_unparseable_returns_none(self):
        assert minutes_into_day("", "2026-08-29") is None
        assert minutes_into_day("garbage", "2026-08-29") is None


class TestDayCoverage:
    def test_the_worked_example_from_the_spec(self):
        """Friday, clock at 15:00, three blocks.
        covered 2.6h; unaccounted 12.4h across four gaps."""
        intervals = [(420, 460), (545, 600), (720, 780)]
        gaps, coverage = day_coverage(intervals, elapsed_minutes=900)
        assert coverage == Coverage(covered_minutes=155, unaccounted_minutes=745)
        assert gaps == [
            Gap("00:00", "07:00", 420),
            Gap("07:40", "09:05", 85),
            Gap("10:00", "12:00", 120),
            Gap("13:00", "15:00", 120),
        ]

    def test_a_fully_covered_day_has_no_gaps(self):
        gaps, coverage = day_coverage([(0, DAY)], elapsed_minutes=DAY)
        assert gaps == []
        assert coverage == Coverage(covered_minutes=DAY, unaccounted_minutes=0)

    def test_an_empty_day_is_one_gap(self):
        gaps, coverage = day_coverage([], elapsed_minutes=900)
        assert gaps == [Gap("00:00", "15:00", 900)]
        assert coverage == Coverage(covered_minutes=0, unaccounted_minutes=900)

    def test_a_future_day_has_no_gaps_and_no_coverage(self):
        """Nothing has elapsed, so nothing is unaccounted for."""
        gaps, coverage = day_coverage([(600, 660)], elapsed_minutes=0)
        assert gaps == []
        assert coverage == Coverage(covered_minutes=0, unaccounted_minutes=0)

    def test_overlapping_blocks_are_counted_once(self):
        """Eating while watching a video is one hour of the day, not two."""
        gaps, coverage = day_coverage([(600, 660), (630, 690)], elapsed_minutes=DAY)
        assert coverage.covered_minutes == 90

    def test_a_block_in_the_future_does_not_count_as_covered(self):
        """It has not happened. Counting it would let unaccounted go negative."""
        gaps, coverage = day_coverage([(600, 660), (1200, 1260)], elapsed_minutes=900)
        assert coverage.covered_minutes == 60
        assert coverage.unaccounted_minutes == 840

    def test_a_block_straddling_now_counts_only_its_elapsed_part(self):
        gaps, coverage = day_coverage([(840, 960)], elapsed_minutes=900)
        assert coverage.covered_minutes == 60
        assert gaps == [Gap("00:00", "14:00", 840)]

    def test_adjacent_blocks_produce_no_zero_length_gap(self):
        gaps, _ = day_coverage([(0, 600), (600, 900)], elapsed_minutes=900)
        assert gaps == []

    def test_blocks_arrive_in_any_order(self):
        gaps, coverage = day_coverage([(720, 780), (420, 460)], elapsed_minutes=900)
        assert coverage.covered_minutes == 100
        assert gaps[0] == Gap("00:00", "07:00", 420)

    def test_midnight_end_renders_as_24_00(self):
        """A gap running to the end of a past day ends at 24:00, not 00:00,
        which would read as a zero-length span."""
        gaps, _ = day_coverage([(0, 60)], elapsed_minutes=DAY)
        assert gaps == [Gap("01:00", "24:00", 1380)]
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_day_coverage.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.day_coverage'`.

- [ ] **Step 3: Write the module**

Create `apps/vault-server/src/services/day_coverage.py`:

```python
"""Coverage and gap arithmetic for one day's blocks.

Two numbers, per the Ship 2 design §3.3:

    covered      union of block intervals, intersected with elapsed time
    unaccounted  elapsed − covered

Every maximal unaccounted span becomes a `⚠` row in the timeline. Overnight
is deliberately included: sleep is the largest unlogged span in a typical
day and the one most in need of surfacing, so a standing gap for it is a
prompt rather than noise.

Blocks are unioned before measuring, so two things at once — eating while
watching a video — is one hour of the day, not two. Coverage can never
exceed elapsed time, which is what keeps `unaccounted` non-negative.

Pure arithmetic on minute offsets from midnight. No I/O, no timezone
handling: the caller resolves both before calling in.
"""

from __future__ import annotations

from dataclasses import dataclass

MINUTES_PER_DAY = 24 * 60


@dataclass(frozen=True)
class Gap:
    """An unaccounted span. `end` is "24:00" at the end of a day rather than
    "00:00", which would read as a zero-length interval."""
    start: str
    end: str
    minutes: int


@dataclass(frozen=True)
class Coverage:
    covered_minutes: int
    unaccounted_minutes: int


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def minutes_into_day(timestamp: str, date: str) -> int | None:
    """Minutes from midnight, or None if `timestamp` is unusable or belongs
    to another day.

    Accepts `YYYY-MM-DDTHH:MM[...]` and a bare `HH:MM`. A timestamp on a
    different date returns None rather than folding into this one — a
    block spanning midnight is clipped by the caller, not silently moved.
    """
    if not timestamp:
        return None
    time_part = timestamp
    if "T" in timestamp:
        day_part, _, time_part = timestamp.partition("T")
        if day_part != date:
            return None
    parts = time_part.split(":")
    if len(parts) < 2:
        return None
    try:
        hours, minutes = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (0 <= hours < 24 and 0 <= minutes < 60):
        return None
    return hours * 60 + minutes


def day_coverage(
    intervals: list[tuple[int, int]], elapsed_minutes: int
) -> tuple[list[Gap], Coverage]:
    """Gaps and coverage for a day.

    `intervals` are (start, end) minute offsets from midnight, in any order,
    possibly overlapping. `elapsed_minutes` is midnight→now for today, 1440
    for a past day, and 0 for a future one.
    """
    elapsed = max(0, min(elapsed_minutes, MINUTES_PER_DAY))
    if elapsed == 0:
        return [], Coverage(covered_minutes=0, unaccounted_minutes=0)

    # Clip to the elapsed window: a block still ahead has not happened, and
    # counting it would drive `unaccounted` negative.
    clipped = sorted(
        (max(0, start), min(end, elapsed))
        for start, end in intervals
        if min(end, elapsed) > max(0, start)
    )

    merged: list[list[int]] = []
    for start, end in clipped:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    covered = sum(end - start for start, end in merged)

    gaps: list[Gap] = []
    cursor = 0
    for start, end in merged:
        if start > cursor:
            gaps.append(Gap(_hhmm(cursor), _hhmm(start), start - cursor))
        cursor = end
    if cursor < elapsed:
        end_label = "24:00" if elapsed == MINUTES_PER_DAY else _hhmm(elapsed)
        gaps.append(Gap(_hhmm(cursor), end_label, elapsed - cursor))

    return gaps, Coverage(
        covered_minutes=covered, unaccounted_minutes=elapsed - covered
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_day_coverage.py -q
```

Expected: PASS, 15 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/day_coverage.py apps/vault-server/tests/test_day_coverage.py
git commit -m "feat(daily): coverage and gap arithmetic"
```

---

### Task 6: `/daily` returns blocks, gaps and coverage for any date

**Files:**
- Modify: `apps/vault-server/src/api/routes/daily.py`
- Test: `apps/vault-server/tests/test_daily_route.py`

**Interfaces:**
- Consumes: `day_coverage`, `minutes_into_day`, `Gap`, `Coverage` (Task 5); the events service's merged output (Tasks 2–4).
- Produces, used by Task 7: `GET /daily?date=YYYY-MM-DD` returning
  ```
  { date, tokens_today, tokens_total,
    blocks: [{id, start, end, title, source, type, completed,
              activity, category, state, habit_progress}],
    gaps:   [{start, end, minutes}],
    coverage: {covered_minutes, unaccounted_minutes},
    todos: [...], notes: [...] }
  ```
  `schedule` is **gone**.

- [ ] **Step 1: Write the failing tests**

Append to `apps/vault-server/tests/test_daily_route.py`:

```python
class TestDailyBlocks:
    def test_block_model_fields(self):
        from src.api.routes.daily import DailyBlock

        assert set(DailyBlock.model_fields) == {
            "id", "start", "end", "title", "source", "type", "completed",
            "activity", "category", "state", "habit_progress",
        }

    def test_response_model_replaces_schedule_with_blocks(self):
        from src.api.routes.daily import DailyResponse

        fields = set(DailyResponse.model_fields)
        assert "schedule" not in fields
        assert fields == {
            "date", "tokens_today", "tokens_total",
            "blocks", "gaps", "coverage", "todos", "notes",
        }

    def test_builds_blocks_and_gaps_from_events(self):
        from src.api.routes.daily import _build_blocks_and_coverage

        events = [
            {"id": "e1", "name": "Dog walk", "start_time": "2026-08-29T07:00",
             "end_time": "2026-08-29T07:40", "source": "habit", "type": "habit",
             "state": "suggested", "activity": None, "category": None},
            {"id": "e2", "name": "Standup", "start_time": "2026-08-29T09:05",
             "end_time": "2026-08-29T10:00", "source": "calendar", "type": "calendar",
             "state": "suggested", "activity": None, "category": None},
        ]
        blocks, gaps, coverage = _build_blocks_and_coverage(
            events, "2026-08-29", elapsed_minutes=600,
        )
        assert [b.title for b in blocks] == ["Dog walk", "Standup"]
        assert [b.start for b in blocks] == ["07:00", "09:05"]
        assert coverage.covered_minutes == 95
        assert [(g.start, g.end) for g in gaps] == [("00:00", "07:00"), ("07:40", "09:05")]

    def test_blocks_sort_by_start_time(self):
        from src.api.routes.daily import _build_blocks_and_coverage

        events = [
            {"id": "b", "name": "Later", "start_time": "2026-08-29T12:00",
             "end_time": "2026-08-29T13:00", "source": "calendar", "type": "calendar"},
            {"id": "a", "name": "Earlier", "start_time": "2026-08-29T09:00",
             "end_time": "2026-08-29T10:00", "source": "calendar", "type": "calendar"},
        ]
        blocks, _, _ = _build_blocks_and_coverage(events, "2026-08-29", elapsed_minutes=1440)
        assert [b.title for b in blocks] == ["Earlier", "Later"]

    def test_a_block_from_another_day_is_clipped_out(self):
        """Storage splits at midnight; a stray event from a neighbouring day
        must not distort this day's coverage."""
        from src.api.routes.daily import _build_blocks_and_coverage

        events = [{"id": "x", "name": "Yesterday", "start_time": "2026-08-28T22:00",
                   "end_time": "2026-08-28T23:00", "source": "calendar", "type": "calendar"}]
        blocks, _, coverage = _build_blocks_and_coverage(events, "2026-08-29", elapsed_minutes=1440)
        assert blocks == []
        assert coverage.covered_minutes == 0

    def test_habit_progress_is_surfaced(self):
        """Carried forward from Phase 1: the bot could only render a binary
        box because completions_today never reached it."""
        from src.api.routes.daily import _build_blocks_and_coverage

        events = [{"id": "h", "name": "Dog walk", "start_time": "2026-08-29T07:00",
                   "end_time": "2026-08-29T07:40", "source": "habit", "type": "habit",
                   "habit": {"name": "Dog walk", "completed": False,
                             "completions_today": 1, "daily_target": 2}}]
        blocks, _, _ = _build_blocks_and_coverage(events, "2026-08-29", elapsed_minutes=1440)
        assert blocks[0].habit_progress == "1/2"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_daily_route.py -q -k "Blocks"
```

Expected: FAIL with `ImportError: cannot import name 'DailyBlock'`.

- [ ] **Step 3: Replace the models**

In `apps/vault-server/src/api/routes/daily.py`, delete the `DailyScheduleItem` class entirely and add in its place:

```python
class DailyBlock(BaseModel):
    """One interval of the day, from the events ledger."""
    id: str
    start: str            # "HH:MM"
    end: str              # "HH:MM"
    title: str
    source: str           # "calendar" | "timeline" | "merged" | "daily-note" | "habit"
    type: str
    completed: bool = False
    activity: str | None = None   # populated by Ship 6
    category: str | None = None   # populated by Ship 6
    state: str = "suggested"      # "approved" arrives in Ship 5
    habit_progress: str | None = None  # "1/2" when a daily_target is set


class DailyGap(BaseModel):
    start: str
    end: str
    minutes: int


class DayCoverage(BaseModel):
    covered_minutes: int
    unaccounted_minutes: int
```

Change `DailyResponse`:

```python
class DailyResponse(BaseModel):
    date: str
    tokens_today: int
    tokens_total: int
    blocks: list[DailyBlock]
    gaps: list[DailyGap]
    coverage: DayCoverage
    todos: list[DailyTodo]
    notes: list[DailyNote]
```

- [ ] **Step 4: Write the builder**

Add to `apps/vault-server/src/api/routes/daily.py`, below `_build_notes`:

```python
def _build_blocks_and_coverage(
    events: list[dict], date: str, elapsed_minutes: int
) -> tuple[list[DailyBlock], list[DailyGap], DayCoverage]:
    """Turn merged events into the day's timeline, plus its coverage.

    Events whose start or end falls outside `date` are dropped: storage
    splits at midnight, so a neighbouring day's fragment here would distort
    this day's arithmetic.
    """
    blocks: list[DailyBlock] = []
    intervals: list[tuple[int, int]] = []

    for e in events:
        start = minutes_into_day(e.get("start_time", ""), date)
        end = minutes_into_day(e.get("end_time", ""), date)
        if start is None or end is None:
            continue
        habit = e.get("habit") or {}
        target = habit.get("daily_target")
        blocks.append(DailyBlock(
            id=e.get("id", ""),
            start=f"{start // 60:02d}:{start % 60:02d}",
            end=f"{end // 60:02d}:{end % 60:02d}",
            title=e.get("name", ""),
            source=e.get("source", ""),
            type=e.get("type", ""),
            completed=bool(habit.get("completed", False)),
            activity=e.get("activity"),
            category=e.get("category"),
            state=e.get("state", "suggested"),
            habit_progress=(
                f"{habit.get('completions_today', 0)}/{target}" if target else None
            ),
        ))
        intervals.append((start, end))

    blocks.sort(key=lambda b: b.start)
    raw_gaps, coverage = day_coverage(intervals, elapsed_minutes)
    return (
        blocks,
        [DailyGap(start=g.start, end=g.end, minutes=g.minutes) for g in raw_gaps],
        DayCoverage(
            covered_minutes=coverage.covered_minutes,
            unaccounted_minutes=coverage.unaccounted_minutes,
        ),
    )
```

Add the import:

```python
from src.services.day_coverage import day_coverage, minutes_into_day
```

- [ ] **Step 5: Rewrite the endpoint**

Replace the whole `get_daily` function in `apps/vault-server/src/api/routes/daily.py` with:

```python
@router.get("", response_model=DailyResponse)
async def get_daily(date: str | None = None):
    from src.main import get_vault
    from src.api.routes.events import get_events as get_events_route

    vault = get_vault()
    now = datetime.now(tz)
    today = now.strftime("%Y-%m-%d")
    target = date or today

    try:
        daily = vault.read_daily_note(target)
    except FileNotFoundError:
        daily = vault.create_daily_note() if target == today else {"content": ""}
    content = daily.get("content", "")

    # Blocks come from the events ledger, which owns temporal data. We call
    # the events route rather than re-merging: two implementations of the
    # same merge is how the ordinal bug in the Phase 2 design §7 happened.
    events: list[dict] = []
    try:
        payload = await get_events_route(dt_date.fromisoformat(target))
        events = payload.get("events", [])
    except Exception:
        pass

    if target < today:
        elapsed = 24 * 60
    elif target > today:
        elapsed = 0
    else:
        elapsed = now.hour * 60 + now.minute

    blocks, gaps, coverage = _build_blocks_and_coverage(events, target, elapsed)

    habits = vault.list_active_habits()
    todos = _build_todos(content, habits, now.date())
    notes = _build_notes(content)

    try:
        ledger = vault.read_token_ledger()
        tokens_today = ledger["metadata"].get("tokens_today", 0)
        tokens_total = ledger["metadata"].get("total_tokens", 0)
    except Exception:
        tokens_today = 0
        tokens_total = 0

    return DailyResponse(
        date=target,
        tokens_today=tokens_today,
        tokens_total=tokens_total,
        blocks=blocks,
        gaps=gaps,
        coverage=coverage,
        todos=todos,
        notes=notes,
    )
```

Add `date as dt_date` to the datetime import at the top — the module already imports `date as dt_date`, so verify rather than duplicating it. The `get_calendar` import in the old body is no longer needed here; the events route owns calendar access now.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_daily_route.py -q
```

Expected: PASS. Existing tests referencing `schedule` must be updated to `blocks` — the schedule concept is deliberately gone, so delete assertions that only tested its shape rather than reproducing them.

- [ ] **Step 7: Run the whole server suite**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/ -q
```

Expected: PASS, 1 pre-existing warning, no others.

- [ ] **Step 8: Verify against real data**

The Ship 1 review found that every review round stayed inside one function's logic and nobody ran the feature against real notes until the end. Do that now:

```bash
cd apps/vault-server && source venv/bin/activate && python -c "
import asyncio, datetime as dt
from src.api.routes.daily import _build_blocks_and_coverage
from src.services.vault_service import VaultService
from pathlib import Path
v = VaultService(Path('/home/marcellmc/dev/mazkir/memory'))
for d in ('2026-08-20', '2026-08-29', '2026-08-30'):
    body = v.read_daily_note(d)['content']
    print(d, 'todos:', len(body.splitlines()))
"
```

Then start the server and hit the endpoint for a real date, a date with no note at all, and a future date:

```bash
curl -s 'http://localhost:8000/daily?date=2026-08-29' | head -40
curl -s 'http://localhost:8000/daily?date=2020-01-01' | head -20
curl -s 'http://localhost:8000/daily?date=2026-12-25' | head -20
```

Record what you saw in your task report. A 500 on any of the three is a task failure.

- [ ] **Step 9: Commit**

```bash
git add apps/vault-server/src/api/routes/daily.py apps/vault-server/tests/test_daily_route.py
git commit -m "feat(daily): return blocks, gaps and coverage for any date"
```

---

### Task 7: Shared types and the rich formatter

**Files:**
- Modify: `packages/shared-types/src/daily.ts`
- Create: `apps/telegram-bot/src/formatters/day-rich.ts`
- Test: `apps/telegram-bot/tests/formatters/day-rich.test.ts` (new file)

**Interfaces:**
- Consumes: the `GET /daily` response shape (Task 6); `InputRichMessage<InputFile>` from `@grammyjs/types` (Task 1); `escapeHtml` from `../formatters/telegram.js`.
- Produces, used by Task 8: `buildDayRich(data: DailyResponse): InputRichMessage<InputFile>`.

- [ ] **Step 1: Update the shared types**

In `packages/shared-types/src/daily.ts`, delete the `DailyScheduleItem` interface and add:

```typescript
export interface DailyBlock {
  id: string;
  start: string;          // "HH:MM"
  end: string;            // "HH:MM"
  title: string;
  source: "calendar" | "timeline" | "merged" | "daily-note" | "habit";
  type: string;
  completed: boolean;
  activity: string | null;   // populated by Ship 6
  category: string | null;   // populated by Ship 6
  state: "suggested" | "approved";
  habit_progress: string | null;  // "1/2" when a daily_target is set
}

export interface DailyGap {
  start: string;
  end: string;
  minutes: number;
}

export interface DayCoverage {
  covered_minutes: number;
  unaccounted_minutes: number;
}
```

Change `DailyResponse` to:

```typescript
export interface DailyResponse {
  date: string;
  tokens_today: number;
  tokens_total: number;
  blocks: DailyBlock[];
  gaps: DailyGap[];
  coverage: DayCoverage;
  todos?: DailyTodo[];
  notes: DailyNote[];
}
```

- [ ] **Step 2: Write the failing tests**

Create `apps/telegram-bot/tests/formatters/day-rich.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { buildDayRich } from "../../src/formatters/day-rich.js";

const base = {
  date: "2026-08-29",
  tokens_today: 0,
  tokens_total: 0,
  blocks: [],
  gaps: [],
  coverage: { covered_minutes: 0, unaccounted_minutes: 0 },
  todos: [],
  notes: [],
};

function html(data: unknown): string {
  return buildDayRich(data as never).html ?? "";
}

describe("buildDayRich", () => {
  it("renders the date and coverage in the header", () => {
    const out = html({
      ...base,
      coverage: { covered_minutes: 155, unaccounted_minutes: 745 },
    });
    expect(out).toContain("29 Aug");
    expect(out).toContain("2.6h covered");
    expect(out).toContain("12.4h unaccounted");
  });

  it("renders blocks and gaps interleaved in time order", () => {
    const out = html({
      ...base,
      blocks: [
        { id: "a", start: "07:00", end: "07:40", title: "Dog walk", source: "habit",
          type: "habit", completed: false, activity: null, category: null,
          state: "suggested", habit_progress: "1/2" },
        { id: "b", start: "09:05", end: "10:00", title: "Standup", source: "calendar",
          type: "calendar", completed: false, activity: "meetings", category: "work",
          state: "suggested", habit_progress: null },
      ],
      gaps: [{ start: "07:40", end: "09:05", minutes: 85 }],
    });
    expect(out.indexOf("Dog walk")).toBeLessThan(out.indexOf("⚠"));
    expect(out.indexOf("⚠")).toBeLessThan(out.indexOf("Standup"));
    expect(out).toContain("1.4h");
  });

  it("shows the facet column only when populated", () => {
    const unclassified = html({
      ...base,
      blocks: [{ id: "a", start: "09:00", end: "10:00", title: "Standup",
                 source: "calendar", type: "calendar", completed: false,
                 activity: null, category: null, state: "suggested",
                 habit_progress: null }],
    });
    expect(unclassified).not.toContain("×");
    const classified = html({
      ...base,
      blocks: [{ id: "a", start: "09:00", end: "10:00", title: "Standup",
                 source: "calendar", type: "calendar", completed: false,
                 activity: "meetings", category: "work", state: "suggested",
                 habit_progress: null }],
    });
    expect(classified).toContain("meetings × work");
  });

  it("renders todos as native task list items", () => {
    const out = html({
      ...base,
      todos: [
        { text: "Order dog food", done: false, section: "Tasks",
          scheduled_at: null, duration_minutes: 30 },
        { text: "Walk dog", done: true, section: "Tasks",
          scheduled_at: null, duration_minutes: null },
      ],
    });
    expect(out).toContain('<input type="checkbox">Order dog food');
    expect(out).toContain('<input type="checkbox" checked>Walk dog');
  });

  it("omits timed todos, which the timeline already shows", () => {
    const out = html({
      ...base,
      blocks: [{ id: "a", start: "14:00", end: "15:00", title: "Visit dentist",
                 source: "daily-note", type: "task", completed: false,
                 activity: null, category: null, state: "suggested",
                 habit_progress: null }],
      todos: [{ text: "Visit dentist", done: false, section: "Tasks",
                scheduled_at: "14:00", duration_minutes: 60 }],
    });
    expect(out.match(/Visit dentist/g)).toHaveLength(1);
  });

  it("escapes user text", () => {
    const out = html({
      ...base,
      todos: [{ text: "Email <boss> about the R&D budget", done: false,
                section: "Tasks", scheduled_at: null, duration_minutes: null }],
    });
    expect(out).toContain("Email &lt;boss&gt; about the R&amp;D budget");
    expect(out).not.toContain("<boss>");
  });

  it("renders a week bar with the selected day styled primary", () => {
    const out = html({ ...base, date: "2026-08-29" });
    expect(out).toContain('data="day:2026-08-29"');
    expect(out).toContain('style="primary"');
    expect(out).toContain('data="day:today"');
    expect((out.match(/<tg-button type="callback_data" data="day:2026-/g) ?? []).length)
      .toBe(9);  // 7 week days + prev + next
  });

  it("says so when there is nothing to show", () => {
    expect(html(base)).toContain("no blocks");
  });

  it("tolerates a server that omits todos", () => {
    const { todos, ...withoutTodos } = base;
    expect(() => html(withoutTodos)).not.toThrow();
  });
});
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
cd apps/telegram-bot && npx vitest run tests/formatters/day-rich.test.ts
```

Expected: FAIL — `day-rich.ts` does not exist.

- [ ] **Step 4: Write the formatter**

Create `apps/telegram-bot/src/formatters/day-rich.ts`:

```typescript
import type { InputFile } from "grammy";
import type { InputRichMessage } from "@grammyjs/types";
import type { DailyResponse, DailyBlock, DailyGap } from "@mazkir/shared-types";
import { escapeHtml } from "./telegram.js";

/** Rich messages are authored as HTML here rather than markdown because
 *  button syntax (`<tg-button>`) has no markdown equivalent. That also means
 *  escapeHtml remains the right tool for user text — a miss renders wrong
 *  rather than losing the whole message, which is what HTML parse_mode did. */

const WEEK_RADIUS = 3;

function hours(minutes: number): string {
  return `${(minutes / 60).toFixed(1)}h`;
}

function shiftDate(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

function headerLabel(iso: string, today: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  const label = d.toLocaleDateString("en-GB", {
    weekday: "short", day: "numeric", month: "short", timeZone: "UTC",
  });
  return iso === today ? `${label} · today` : label;
}

function blockRow(b: DailyBlock): string {
  const facets = b.activity && b.category
    ? `${escapeHtml(b.activity)} × ${escapeHtml(b.category)}`
    : "";
  const marker = b.habit_progress ? escapeHtml(b.habit_progress) : facets;
  return `<tr><td>${b.start}–${b.end}</td><td>${escapeHtml(b.title)}</td><td>${marker}</td></tr>`;
}

function gapRow(g: DailyGap): string {
  return `<tr><td>⚠ ${g.start}–${g.end}</td><td>—</td><td>${hours(g.minutes)}</td></tr>`;
}

function weekBar(selected: string): string {
  const buttons: string[] = [];
  for (let offset = -WEEK_RADIUS; offset <= WEEK_RADIUS; offset++) {
    const iso = shiftDate(selected, offset);
    const day = Number(iso.slice(8, 10));
    const style = offset === 0 ? ' style="primary"' : "";
    buttons.push(
      `<tg-button type="callback_data" data="day:${iso}"${style}>${day}</tg-button>`,
    );
  }
  return `<tg-button-row align="center">${buttons.join("")}</tg-button-row>`;
}

function navBar(selected: string): string {
  return (
    `<tg-button-row align="center">` +
    `<tg-button type="callback_data" data="day:${shiftDate(selected, -1)}">◀</tg-button>` +
    `<tg-button type="callback_data" data="day:today">today</tg-button>` +
    `<tg-button type="callback_data" data="day:${shiftDate(selected, 1)}">▶</tg-button>` +
    `</tg-button-row>`
  );
}

export function buildDayRich(data: DailyResponse): InputRichMessage<InputFile> {
  const today = new Date().toISOString().slice(0, 10);
  const parts: string[] = [];

  parts.push(`<h2>${escapeHtml(headerLabel(data.date, today))}</h2>`);
  parts.push(
    `<p>${hours(data.coverage.covered_minutes)} covered · ` +
    `${hours(data.coverage.unaccounted_minutes)} unaccounted</p>`,
  );

  // Blocks and gaps interleave in time order: a gap is a hole between
  // blocks, so reading them as one sequence is the whole point.
  const rows = [
    ...data.blocks.map((b) => ({ at: b.start, html: blockRow(b) })),
    ...data.gaps.map((g) => ({ at: g.start, html: gapRow(g) })),
  ].sort((a, b) => a.at.localeCompare(b.at));

  if (rows.length === 0) {
    parts.push("<p>no blocks</p>");
  } else {
    parts.push(`<table>${rows.map((r) => r.html).join("")}</table>`);
  }

  // Timed todos already appear above as blocks; showing them again here
  // would render the same commitment twice.
  const untimed = (data.todos ?? []).filter((t) => !t.scheduled_at);
  if (untimed.length > 0) {
    const items = untimed.map((t) => {
      const box = t.done ? '<input type="checkbox" checked>' : '<input type="checkbox">';
      const dur = t.duration_minutes != null ? ` (${t.duration_minutes}m)` : "";
      return `<li>${box}${escapeHtml(t.text)}${escapeHtml(dur)}</li>`;
    });
    parts.push(`<ul>${items.join("")}</ul>`);
  }

  if (data.notes && data.notes.length > 0) {
    const items = data.notes.map((n) => {
      const text = n.text ?? (n.caption ? `📷 ${n.caption}` : "📷");
      return `<li>${escapeHtml(text)}</li>`;
    });
    parts.push(`<ul>${items.join("")}</ul>`);
  }

  parts.push(weekBar(data.date));
  parts.push(navBar(data.date));

  return { html: parts.join("\n") };
}
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd apps/telegram-bot && npx vitest run tests/formatters/day-rich.test.ts
```

Expected: PASS, 9 tests.

- [ ] **Step 6: Typecheck and run everything**

```bash
cd /home/marcellmc/dev/mazkir && npx tsc -b packages/shared-types && cd apps/telegram-bot && npx vitest run
```

Expected: typecheck clean; the old `formatDay` tests in `tests/formatters/telegram.test.ts` now fail to compile because `DailyResponse` no longer has `schedule`. Delete `formatDay` from `src/formatters/telegram.ts` and its `describe` blocks from the test file — it is superseded by `buildDayRich`, and leaving two day formatters is exactly the drift this ship removes.

- [ ] **Step 7: Commit**

```bash
git add packages/shared-types/src/daily.ts apps/telegram-bot/src/formatters/day-rich.ts apps/telegram-bot/src/formatters/telegram.ts apps/telegram-bot/tests/formatters/day-rich.test.ts apps/telegram-bot/tests/formatters/telegram.test.ts
git commit -m "feat(bot): rich formatter for the day view"
```

---

### Task 8: Navigation — `editRich` and the `day:` callbacks

**Files:**
- Modify: `apps/telegram-bot/src/bot-utils/send-rich.ts`
- Modify: `apps/telegram-bot/src/api/client.ts`
- Modify: `apps/telegram-bot/src/commands/day.ts`
- Modify: `apps/telegram-bot/src/callbacks/index.ts`
- Test: `apps/telegram-bot/tests/bot-utils/send-rich.test.ts`

**Interfaces:**
- Consumes: `buildDayRich` (Task 7); `GET /daily?date=` (Task 6).
- Produces: `editRich(ctx, msg)`; `api.getDaily(date?)`; callback `day:<YYYY-MM-DD>` and `day:today`.

- [ ] **Step 1: Write the failing tests**

Append to `apps/telegram-bot/tests/bot-utils/send-rich.test.ts`:

```typescript
describe("editRich", () => {
  it("edits the message in place with rich content", async () => {
    const editMessageText = vi.fn().mockResolvedValue(true);
    const ctx = { editMessageText } as never;
    const { editRich } = await import("../../src/bot-utils/send-rich.js");
    await editRich(ctx, { html: "<p>hi</p>" });
    expect(editMessageText).toHaveBeenCalledWith(
      "", { rich_message: { html: "<p>hi</p>" } },
    );
  });

  it("falls back to plain text when the rich payload is rejected", async () => {
    const editMessageText = vi.fn()
      .mockRejectedValueOnce(new Error("rich rejected"))
      .mockResolvedValue(true);
    const ctx = { editMessageText } as never;
    const { editRich } = await import("../../src/bot-utils/send-rich.js");
    await editRich(ctx, { html: "<p>hi &amp; bye</p>" });
    expect(editMessageText).toHaveBeenLastCalledWith("hi & bye");
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd apps/telegram-bot && npx vitest run tests/bot-utils/send-rich.test.ts
```

Expected: FAIL — `editRich` is not exported.

- [ ] **Step 3: Add `editRich` and correct the wrong comment**

In `apps/telegram-bot/src/bot-utils/send-rich.ts`, replace the comment block at the top:

```ts
// Rich content is an extended markup string in InputRichMessage. Send via the
// grammY context method ctx.replyWithRichMessage. There is no editMessageText on
// the rich path — rich is send-once only.
```

with:

```ts
// Rich content is an extended markup string in InputRichMessage. Send via
// ctx.replyWithRichMessage, edit via editMessageText's `rich_message`
// parameter — added in Bot API 10.1, the same release that introduced rich
// messages. An earlier comment here claimed rich was send-once; it never was.
```

Then append to the file:

```ts
/** Edit a message in place with rich content, falling back to plain text if
 *  the payload is rejected. The sibling of sendRich: navigation re-renders
 *  the same message, so a rejected payload must degrade rather than leave
 *  the user staring at a stale day. */
export async function editRich(
  ctx: Context,
  msg: InputRichMessage<InputFile>,
): Promise<void> {
  try {
    await ctx.editMessageText("", { rich_message: msg } as never);
  } catch (err) {
    markActiveSpanError(err);
    logger.warn(
      { event_type: "rich_edit_fallback", err: String(err) },
      "rich_edit_fallback",
    );
    await ctx.editMessageText(richToPlainText(msg));
  }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd apps/telegram-bot && npx vitest run tests/bot-utils/send-rich.test.ts
```

Expected: PASS.

- [ ] **Step 5: Add the date parameter to the API client**

In `apps/telegram-bot/src/api/client.ts`, change:

```typescript
    getDaily: () => request<DailyResponse>("/daily"),
```

to:

```typescript
    getDaily: (date?: string) =>
      request<DailyResponse>(date ? `/daily?date=${date}` : "/daily"),
```

- [ ] **Step 6: Rewrite the command**

Replace the whole body of `apps/telegram-bot/src/commands/day.ts` with:

```typescript
import { Composer } from "grammy";
import { api } from "../api/client.js";
import { buildDayRich } from "../formatters/day-rich.js";
import { sendRich } from "../bot-utils/send-rich.js";
import { markActiveSpanError } from "../tracing-utils.js";

export const dayCommand = new Composer();

dayCommand.command("day", async (ctx) => {
  // Fetch and send are reported separately: a bare catch around both used to
  // report a Telegram send failure as "is vault-server running?", pointing
  // the user at the wrong cause.
  let data;
  try {
    data = await api.getDaily();
  } catch (err) {
    markActiveSpanError(err);
    await ctx.reply("❌ Failed to load the day. Is vault-server running?");
    return;
  }
  await sendRich(ctx, buildDayRich(data));
});
```

- [ ] **Step 7: Add the callback handler**

In `apps/telegram-bot/src/callbacks/index.ts`, add before the `nav:` handler:

```typescript
// Date navigation re-renders the same message. The selected date lives in
// the callback data rather than server state, so a button on an old message
// still resolves to the day it was drawn for.
callbackHandlers.callbackQuery(/^day:(.+)$/, async (ctx) => {
  const arg = ctx.match[1]!;
  await ctx.answerCallbackQuery();
  const date = arg === "today" ? undefined : arg;
  try {
    const data = await api.getDaily(date);
    await editRich(ctx, buildDayRich(data));
  } catch (err) {
    markActiveSpanError(err);
    await ctx.editMessageText("❌ Failed to load the day.");
  }
});
```

Add the imports at the top of the file:

```typescript
import { buildDayRich } from "../formatters/day-rich.js";
import { sendRich, editRich } from "../bot-utils/send-rich.js";
```

(`sendRich` is already imported — add only `editRich` to the existing import.)

- [ ] **Step 8: Typecheck and run everything**

```bash
cd /home/marcellmc/dev/mazkir && npx tsc -b packages/shared-types && cd apps/telegram-bot && npx tsc --noEmit -p tsconfig.json && npx vitest run
```

Expected: typecheck clean; bot suite passing with the new tests. Test output pristine apart from the pre-existing `rich_message_fallback` WARN lines.

- [ ] **Step 9: Commit**

```bash
git add apps/telegram-bot/src/bot-utils/send-rich.ts apps/telegram-bot/src/api/client.ts apps/telegram-bot/src/commands/day.ts apps/telegram-bot/src/callbacks/index.ts apps/telegram-bot/tests/bot-utils/send-rich.test.ts
git commit -m "feat(bot): navigate /day by date, editing the message in place"
```

---

### Task 9: Correct the documentation this ship disproved

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/superpowers/specs/2026-08-29-ship2-navigable-day-design.md`

- [ ] **Step 1: Correct the rich-message claims in CLAUDE.md**

Find the "Streaming responses (P5)" bullet. It ends with:

> `editMessageText` is no longer used for replies (rich messages can't be edited in place). Command digests (`/tasks`, `/day`, `/tokens`, etc.) remain classic HTML `parse_mode` because their inline-keyboard UI is edit-driven.

Replace those two sentences with:

> Rich messages **can** be edited in place — `editMessageText` takes a `rich_message` parameter, added in Bot API 10.1 alongside rich messages themselves. `/day` uses that path (Ship 2). The other command digests (`/tasks`, `/tokens`, etc.) remain classic HTML `parse_mode` because nothing has needed converting them, not because rich cannot be edited.

- [ ] **Step 2: Update the `/day` and `GET /daily` descriptions**

Find the `- /day - Time-based feed:` bullet under "Telegram Bot Commands" and replace it with:

```
- `/day` (bot command; the endpoint is `GET /daily`) - Browsable day viewer backed by the events ledger. Returns `{date, tokens_today, tokens_total, blocks[], gaps[], coverage{}, todos[], notes[]}` for any `?date=`. Blocks are merged events — calendar, timeline visits, transit, timed checkboxes from the daily note, and scheduled habits — sorted by start. `gaps[]` are unaccounted spans, rendered as `⚠` rows. Rendered as a rich message with in-body date-navigation buttons, edited in place on each tap.
```

Find the `- GET /daily - Time-based feed:` bullet under "vault-server API Endpoints" and replace it with:

```
- `GET /daily?date=YYYY-MM-DD` - Day view: `{date, tokens_today, tokens_total, blocks[], gaps[], coverage{}, todos[], notes[]}`. Delegates block-building to the events service rather than re-merging. `schedule[]` was removed in Ship 2 — everything it carried now arrives as a block.
```

- [ ] **Step 3: Add the merger and coverage notes**

Under "Development Guidelines → Architecture", add:

```
- **Events ledger owns temporal data (Ship 2):** daily notes are a worksurface; the ledger is the source of truth for anything with a time. A timed checkbox becomes a block by *inference* — `MergerService` reads the note body on every merge and emits one block per timed checkbox, matched across opens by `source_ids`. Nothing is persisted and no write path is involved. Scheduled habits with no matching calendar event become standalone blocks the same way.
- **`source_ids` on merged events (Ship 2):** every event `MergerService` produces carries exactly one `source_ids` entry, so `EventsService.refresh_events` can match it to its persisted counterpart. Before this, merged events had no `source_ids` at all — every open assigned a new `id` and discarded anything set on the event, which would have made Ship 5's approval impossible to persist.
- **Coverage arithmetic (Ship 2):** `services/day_coverage.py` is pure arithmetic over minute offsets. Two numbers — `covered` (union of block intervals, clipped to elapsed time) and `unaccounted` (`elapsed − covered`). Overlapping blocks count once. Every maximal unaccounted span becomes a `⚠` gap row, overnight included: sleep is the largest unlogged span and surfacing it is the point.
```

- [ ] **Step 4: Record the source_ids discovery in the spec**

In `docs/superpowers/specs/2026-08-29-ship2-navigable-day-design.md`, §3.2 says note-derived blocks reconcile "the same way it matches `calendar_id`". Append to that paragraph:

```
**Correction found during implementation:** calendar events did not reconcile either. `MergerService` emitted no `source_ids` at all, so `refresh_events`' matching could never fire for a merged event — each open assigned a new `id` and dropped the persisted copy. Ship 2 fixes that for every merged source, which is what makes this paragraph true rather than aspirational, and is a precondition for Ship 5 persisting approval.
```

- [ ] **Step 5: Verify no stale claims remain**

```bash
cd /home/marcellmc/dev/mazkir
grep -n "can't be edited\|send-once\|schedule\[\]" CLAUDE.md
```

Expected: no matches.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-08-29-ship2-navigable-day-design.md
git commit -m "docs: correct rich-message and /daily claims for Ship 2"
```

---

## Final verification

After Task 9, before finishing the branch:

```bash
cd /home/marcellmc/dev/mazkir && npx turbo test
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/ -q
cd /home/marcellmc/dev/mazkir && npx tsc -b packages/shared-types
```

Then run the surface against real data — the step the Ship 1 review identified as the gap that let two Important findings through. Start the server and the bot, and in Telegram:

1. `/day` on today
2. Tap `◀` three times, then `today`
3. Tap a week-bar day
4. Open a date with no note (e.g. a year ago)
5. Open a future date

**Two checks only the user can make:** whether seven week-bar buttons wrap on a narrow phone, and whether the rich table renders legibly. Both have a defined fallback — collapse the week bar to arrows-only, and the plain-text path respectively. Report what you saw; do not decide these alone.
