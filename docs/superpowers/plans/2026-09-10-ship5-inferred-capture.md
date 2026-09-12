# Ship 5 — Inferred Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/day` show a filled-in day whose blocks you confirm or dismiss with one tap, count only what you confirmed, and propose names for the gaps.

**Architecture:** Approval is *derived* from the source wherever a human action created the block (a checked checkbox is the approval) and *stored* only when the user taps `✓`/`✕` on a machine-inferred one — which are exactly the sources whose ids are stable across merges. Coverage then computes two unions from one block list: gaps over everything, `confirmed_minutes` over approved only. The bot renders controls inside `<td>` cells, the only place Telegram draws compact buttons.

**Tech Stack:** FastAPI + Python 3.13 (`apps/vault-server`), grammY + TypeScript (`apps/telegram-bot`), `@mazkir/shared-types`, pytest, vitest.

**Spec:** `docs/superpowers/specs/2026-09-10-ship5-inferred-capture-design.md`

## Global Constraints

- **Worktree setup, once, before Task 1.** A worktree has no venv (venvs hold absolute paths):
  ```bash
  ln -sfn /home/marcellmc/dev/mazkir/apps/vault-server/venv apps/vault-server/venv
  ```
  Do **not** symlink `memory/` into the worktree. The suite resolves the vault from config, and a symlink at the repo root is not matched by `.gitignore`'s `memory/` pattern — so it shows as untracked and a `git add -A` would commit it.
- **Baseline is 1066 server tests passing.** Run `./venv/bin/python -m pytest tests/ -q` from `apps/vault-server`. **The count never decreases.** A task that ends with fewer than it started with is not done.
- **Baseline is 159 bot tests across 22 files.** The bot suite needs environment variables or `tests/formatters/day-rich.test.ts` fails to *collect* — `day-rich.ts` imports `config.ts`, which throws without them. Always run `TELEGRAM_BOT_TOKEN=x AUTHORIZED_USER_ID=1 npx vitest run`. A bare `npx vitest run` reports a collection failure that is the environment, not your change.
- **`tsc -b` must stay clean** in `apps/telegram-bot` and `apps/telegram-web-app`.
- **Only `"approved"` and `"dismissed"` are ever stored in `state`.** Absent means *derive it*. `"suggested"` is never written, and is dropped on read.
- **The four glyphs are exactly these characters:** `✓` (U+2713) settled, `●` (U+25CF) happened-and-pending, `░` (U+2591) unaccounted, `◌` (U+25CC) still-ahead. No emoji-presentation variants, no `⚠`, no `⟳`, no `✅`.
- **Buttons must render inside `<td>` elements.** A `<tg-button-row>` at top level stretches full width; inside an `<li>` it is hoisted out and stretched. Only a table cell gives compact pills.
- **Callback data is at most 64 bytes, and every block-scoped callback carries its date.** The shapes are exactly `block:approve:<date>:<id>`, `block:dismiss:<date>:<id>`, `block:edit:<date>:<id>`, `adj:<date>:<id>:<start_delta>:<end_delta>`, `adjsave:<date>:<id>:<start_delta>:<end_delta>`, `prop:<approve|dismiss|edit>:<date>:<start_min>:<end_min>`, `gap:fill:<date>:<start_min>:<end_min>`. The date is never taken from the bot's clock: a button drawn on a browsed day must address *that* day, or confirming anything but today fails.
- **Proposal thresholds are exactly these:** a candidate block must overlap the gap by **at least half the gap's length**, and its name must appear on **at least 3 distinct days** out of the previous **14**.
- **The overnight rule fires only when a gap fully contains 02:00–05:00**, and proposes the name `Sleep`.
- **Nothing unticks a habit or retracts tokens.** There is no reverse path in this ship.
- **`/daily` never persists.** It reaches events through `get_events_preview` → `reconcile`, never `refresh_events`. Only an explicit user action writes.
- **Mazkir writes only to its own calendar.** Every Google write passes `calendarId=self._calendar_id`. This ship makes no Google writes at all.
- **Commit after every task.** Conventional-commit prefixes (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`).
- **The vault (`memory/`) is a separate git repo.** Never commit it from the monorepo. Never `git add -A`; stage explicit paths.

---

## File Structure

| File | Responsibility |
|---|---|
| `apps/vault-server/src/services/approval.py` | **new.** `resolve_state(event)` and `is_approved(event)`. Pure, one dict in, string out. Imports `_SOURCE_SYSTEM_BY_ID_KEY` from `events_service`; `events_service` must never import this, or the cycle closes. |
| `apps/vault-server/src/services/gap_proposals.py` | **new.** The history ladder and overnight rule. Takes already-loaded date data, so it stays pure and testable without a filesystem. |
| `apps/vault-server/src/services/events_service.py` | `_normalize` / `save_events` stop defaulting `state`. |
| `apps/vault-server/src/services/habit_completion.py` | `complete_habit` gains a timezone-aware default. |
| `apps/vault-server/src/api/routes/daily.py` | Two coverage unions; block `state`; dismissed omitted; gap proposals; `approve-all` and `gaps/fill` endpoints. |
| `apps/vault-server/src/api/routes/events.py` | `POST /{date}/{id}/state`; `PATCH` gains `user_set` pinning. |
| `packages/shared-types/src/daily.ts` | `DailyBlock.state`, `DayCoverage`, `DailyGap.proposal`. |
| `apps/telegram-bot/src/formatters/day-rich.ts` | Glyphs, in-row controls, summary row + refresh, new divider, new tail. |
| `apps/telegram-bot/src/formatters/block-edit-rich.ts` | **new.** The edit view. Split out because `day-rich.ts` is already 249 lines and the two views share nothing but helpers. |
| `apps/telegram-bot/src/callbacks/day-actions.ts` | **new.** The Ship 5 handlers. Split out because `callbacks/index.ts` is 196 lines and would roughly double. |

---

## Task 1: `resolve_state` — approval derived from the source

**Files:**
- Create: `apps/vault-server/src/services/approval.py`
- Test: `apps/vault-server/tests/test_approval.py`

**Interfaces:**
- Consumes: `_SOURCE_SYSTEM_BY_ID_KEY` from `src.services.events_service` (maps a `source_ids` key to a source-system name: `calendar_id`→`calendar`, `visit_id`/`transit_id`→`timeline`, `note_line`→`daily-note`, `habit_slug`→`habit`).
- Produces: `resolve_state(event: dict) -> str` returning exactly `"approved"`, `"pending"` or `"dismissed"`; `is_approved(event: dict) -> bool`.

Spec §2.1, §2.3. The rule: a stored `"approved"`/`"dismissed"` wins; otherwise derive — `manual`/`photo` sources are approved, a habit- or note-derived block is approved when `completed` is true, everything else is pending.

The case a careless implementation gets wrong is **calendar + `completed`**. `merger_service.py:279,297` set `completed` from Google's green colour or a `✅` summary prefix, so a completed calendar event exists and must still be `"pending"` — it is machine-inferred intent, not a human action. That is why the derivation keys on the source *system*, not on `completed` alone.

- [ ] **Step 1: Write the failing tests**

Create `apps/vault-server/tests/test_approval.py`:

```python
"""resolve_state — spec §2.1, §2.3."""

from src.services.approval import is_approved, resolve_state


def ev(**kw):
    """An event with the keys resolve_state reads, all defaulted."""
    base = {"source": "merged", "source_ids": {}, "completed": False}
    base.update(kw)
    return base


class TestStoredWins:
    def test_stored_approved(self):
        assert resolve_state(ev(state="approved")) == "approved"

    def test_stored_dismissed(self):
        assert resolve_state(ev(state="dismissed")) == "dismissed"

    def test_stored_dismissed_beats_a_completed_habit(self):
        """An explicit dismissal is the user's word and outranks derivation."""
        e = ev(state="dismissed", source_ids={"habit_slug": "dog-walk"}, completed=True)
        assert resolve_state(e) == "dismissed"

    def test_a_bare_suggested_is_not_stored_state(self):
        """"suggested" is never written any more (§2.2). If an old row still
        carries it, it must be treated as absent and derived, not returned."""
        e = ev(state="suggested", source_ids={"habit_slug": "dog-walk"}, completed=True)
        assert resolve_state(e) == "approved"


class TestDerivedApproved:
    def test_manual_source(self):
        assert resolve_state(ev(source="manual")) == "approved"

    def test_photo_source(self):
        assert resolve_state(ev(source="photo")) == "approved"

    def test_ticked_habit(self):
        e = ev(source_ids={"habit_slug": "dog-walk"}, completed=True)
        assert resolve_state(e) == "approved"

    def test_checked_checkbox(self):
        e = ev(source_ids={"note_line": "abc123"}, completed=True)
        assert resolve_state(e) == "approved"


class TestDerivedPending:
    def test_unfired_habit(self):
        e = ev(source_ids={"habit_slug": "dog-walk"}, completed=False)
        assert resolve_state(e) == "pending"

    def test_unchecked_checkbox(self):
        e = ev(source_ids={"note_line": "abc123"}, completed=False)
        assert resolve_state(e) == "pending"

    def test_calendar_event(self):
        e = ev(source="calendar", source_ids={"calendar_id": "g1"})
        assert resolve_state(e) == "pending"

    def test_completed_calendar_event_is_still_pending(self):
        """THE case to get right. Google's green colour and a ✅ prefix both
        set `completed` (merger_service.py:279,297), but a calendar entry is
        machine-inferred intent — the source system decides, not `completed`."""
        e = ev(source="calendar", source_ids={"calendar_id": "g1"}, completed=True)
        assert resolve_state(e) == "pending"

    def test_timeline_visit(self):
        e = ev(source="timeline", source_ids={"visit_id": "v1"})
        assert resolve_state(e) == "pending"

    def test_completed_timeline_visit_is_still_pending(self):
        e = ev(source="timeline", source_ids={"visit_id": "v1"}, completed=True)
        assert resolve_state(e) == "pending"

    def test_transit(self):
        e = ev(source="timeline", source_ids={"transit_id": "t1"})
        assert resolve_state(e) == "pending"


class TestTolerance:
    def test_missing_keys_entirely(self):
        """A persisted row from before any of these fields existed."""
        assert resolve_state({}) == "pending"

    def test_source_ids_explicitly_none(self):
        """`.get` returns None for an explicit null, not the default."""
        assert resolve_state({"source_ids": None}) == "pending"

    def test_unknown_source_ids_key(self):
        assert resolve_state(ev(source_ids={"martian_id": "x"}, completed=True)) == "pending"

    def test_multi_key_event_with_one_human_source(self):
        """Ship 2 guarantees MergerService emits one key, but a persisted row
        can have accumulated more. Any human source is enough."""
        e = ev(source_ids={"calendar_id": "g1", "habit_slug": "dog-walk"}, completed=True)
        assert resolve_state(e) == "approved"


class TestIsApproved:
    def test_true_for_approved(self):
        assert is_approved(ev(state="approved")) is True

    def test_false_for_pending(self):
        assert is_approved(ev(source="calendar", source_ids={"calendar_id": "g1"})) is False

    def test_false_for_dismissed(self):
        assert is_approved(ev(state="dismissed")) is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run from `apps/vault-server`:
```bash
./venv/bin/python -m pytest tests/test_approval.py -q
```
Expected: collection error, `ModuleNotFoundError: No module named 'src.services.approval'`.

- [ ] **Step 3: Write the implementation**

Create `apps/vault-server/src/services/approval.py`:

```python
"""Whether a block counts — derived from its source, stored only when tapped.

Spec §2.1. Writing `state` on every confirmed block would persist rows keyed
by `note_line` and `habit_slug` ids, which are hashes of user-editable text.
`events_service.py`'s own comment says what happens then: the row matches
nothing on the next merge and lingers *beside* the freshly-inferred block, so
the same block renders twice.

The auto-approval rule makes that unnecessary rather than solving it. The
sources with unstable ids are exactly the human-created ones, and those
auto-approve — which needs no row at all, because a checked checkbox *is* the
approval. So the only rows we ever persist are calendar and timeline, whose
ids come from upstream and are stable across merges.

This module must never be imported by `events_service`: it imports from it.
"""

from __future__ import annotations

from typing import Any

from src.services.events_service import _SOURCE_SYSTEM_BY_ID_KEY

# Source systems whose blocks a human action created, and which therefore
# need no tap. `daily-note` is a checkbox the user wrote; `habit` is one they
# ticked. Both are also the two whose ids are unstable — which is the whole
# reason this set and the persisted-state set are complements.
_HUMAN_SOURCE_SYSTEMS = frozenset({"habit", "daily-note"})

# `source` values that mean the user made this block directly, with no
# upstream to infer from: `create_event` writes "manual", photo attachment
# writes "photo".
_HUMAN_SOURCES = frozenset({"manual", "photo"})

_STORABLE = frozenset({"approved", "dismissed"})


def resolve_state(event: dict[str, Any]) -> str:
    """"approved", "pending" or "dismissed".

    A stored value wins; anything else is derived from the source. Note that
    only "approved" and "dismissed" count as stored — a legacy `"suggested"`
    is treated as absent, because it was written by a `setdefault` that no
    longer exists and never expressed a decision (§2.2).
    """
    stored = event.get("state")
    if stored in _STORABLE:
        return stored

    if event.get("source") in _HUMAN_SOURCES:
        return "approved"

    # `or {}` rather than a `.get` default: a persisted row can carry an
    # explicit null here, and `.get`'s default only applies when the key is
    # absent entirely.
    source_ids = event.get("source_ids") or {}
    systems = {_SOURCE_SYSTEM_BY_ID_KEY.get(key) for key in source_ids}

    # `completed` is not sufficient on its own. A calendar entry carries it
    # too — merger_service.py:279,297 set it from Google's green colour or a
    # `✅` summary prefix — and a calendar entry is machine-inferred intent.
    # The source system decides; `completed` only qualifies a human one.
    if systems & _HUMAN_SOURCE_SYSTEMS and event.get("completed"):
        return "approved"

    return "pending"


def is_approved(event: dict[str, Any]) -> bool:
    """Whether this block counts toward `confirmed_minutes` (§3)."""
    return resolve_state(event) == "approved"
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
./venv/bin/python -m pytest tests/test_approval.py -q
```
Expected: all pass.

- [ ] **Step 5: Run the whole server suite**

```bash
./venv/bin/python -m pytest tests/ -q
```
Expected: 1066 + the new tests, nothing broken.

- [ ] **Step 6: Commit**

```bash
git add apps/vault-server/src/services/approval.py apps/vault-server/tests/test_approval.py
git commit -m "feat(events): derive approval from the source"
```

---

## Task 2: `state` stops defaulting to `"suggested"`

**Files:**
- Modify: `apps/vault-server/src/services/events_service.py` — `_normalize` (line ~156) and `save_events` (line ~178)
- Test: `apps/vault-server/tests/test_events_service.py`

**Interfaces:**
- Consumes: `resolve_state` (Task 1).
- Produces: events read or written by `EventsService` no longer carry a `state` key unless it is `"approved"` or `"dismissed"`.

Spec §2.2. Both `_normalize` and `save_events` call `setdefault("state", "suggested")`, which makes "never touched" indistinguishable from "explicitly pending". Absent must mean *derive it*.

**Two existing tests assert the old behaviour and must be updated, not deleted.** They are `test_legacy_events_default_to_suggested` (`tests/test_events_service.py:728`) and an assertion at line 705. Both were correct for Ship 4 and are wrong now; each becomes an assertion that `state` is *absent* and that `resolve_state` answers `"pending"` — which preserves what they were actually protecting ("events written before this change must not silently count as logged").

- [ ] **Step 1: Update the two existing tests and add new ones**

In `apps/vault-server/tests/test_events_service.py`, replace the line 705 assertion:

```python
    assert event["state"] == "suggested"
```

with:

```python
    # `state` is absent, not "suggested" (spec §2.2): absent means "derive
    # it from the source", and a stored value means the user decided. A
    # default would make those two indistinguishable.
    assert "state" not in event
```

Replace `test_legacy_events_default_to_suggested` entirely, and add three more:

```python
def test_legacy_events_carry_no_state_and_resolve_to_pending(tmp_path):
    """Events written before approval existed must not silently count as
    logged. They now carry no `state` at all, and `resolve_state` derives
    "pending" for them — same protection, without a stored default that
    would be indistinguishable from a real decision."""
    import json
    from src.services.approval import resolve_state
    from src.services.events_service import EventsService

    events_dir = tmp_path / "events"
    events_dir.mkdir()
    (events_dir / "2026-05-01.json").write_text(
        json.dumps([{"id": "evt_old", "name": "Coffee"}]), encoding="utf-8"
    )

    svc = EventsService(events_dir)
    event = svc.get_events("2026-05-01")[0]

    assert "state" not in event
    assert resolve_state(event) == "pending"


def test_a_stored_suggested_is_dropped_on_read(tmp_path):
    """Rows written by Ship 4 carry state="suggested". It never expressed a
    decision, so it is stripped rather than preserved — otherwise it would
    read as stored state forever."""
    import json
    from src.services.events_service import EventsService

    events_dir = tmp_path / "events"
    events_dir.mkdir()
    (events_dir / "2026-05-01.json").write_text(
        json.dumps([{"id": "e1", "name": "Coffee", "state": "suggested"}]),
        encoding="utf-8",
    )

    assert "state" not in EventsService(events_dir).get_events("2026-05-01")[0]


def test_approved_and_dismissed_survive_a_save_and_read(tmp_path):
    from src.services.events_service import EventsService

    svc = EventsService(tmp_path / "events")
    svc.save_events("2026-05-01", [
        {"id": "a", "state": "approved"},
        {"id": "b", "state": "dismissed"},
    ])

    by_id = {e["id"]: e for e in svc.get_events("2026-05-01")}
    assert by_id["a"]["state"] == "approved"
    assert by_id["b"]["state"] == "dismissed"


def test_save_events_does_not_invent_a_state(tmp_path):
    from src.services.events_service import EventsService

    svc = EventsService(tmp_path / "events")
    svc.save_events("2026-05-01", [{"id": "a", "name": "Coffee"}])

    raw = (tmp_path / "events" / "2026-05-01.json").read_text()
    assert '"state"' not in raw
```

- [ ] **Step 2: Run to verify the new ones fail**

```bash
./venv/bin/python -m pytest tests/test_events_service.py -q -k "state or suggested"
```
Expected: FAIL — `state` is still being defaulted to `"suggested"`.

- [ ] **Step 3: Change `_normalize`**

In `apps/vault-server/src/services/events_service.py`, in `_normalize`, replace:

```python
        event.setdefault("state", "suggested")
        return event
```

with:

```python
        # `state` is deliberately NOT defaulted. Absent means "derive it from
        # the source" (see services/approval.py); only "approved" and
        # "dismissed" are ever stored. A default would make an untouched row
        # indistinguishable from a decided one.
        #
        # A legacy `"suggested"` — written by the setdefault this replaces —
        # is stripped rather than kept, because it never expressed a decision
        # and would otherwise read as stored state forever.
        if event.get("state") == "suggested":
            del event["state"]
        return event
```

- [ ] **Step 4: Change `save_events`**

In the same file, in `save_events`, delete this line:

```python
            event.setdefault("state", "suggested")
```

Leave every other `setdefault` in that loop alone — `photos`, `assets`, `source_ids`, `activity`, `category`, `tags` and `user_set` all still default.

- [ ] **Step 5: Run the tests**

```bash
./venv/bin/python -m pytest tests/test_events_service.py -q
./venv/bin/python -m pytest tests/ -q
```
Expected: both green. If any other test asserts `"suggested"`, it is in the same category as the two above — update it to assert absence plus `resolve_state(...) == "pending"`, and say so in the commit.

- [ ] **Step 6: Commit**

```bash
git add apps/vault-server/src/services/events_service.py apps/vault-server/tests/test_events_service.py
git commit -m "refactor(events): state defaults to absent, not suggested"
```

---

## Task 3: Coverage splits into two unions

**Files:**
- Modify: `apps/vault-server/src/api/routes/daily.py` — `DayCoverage` (line ~55), `_build_blocks_and_coverage` (line ~240)
- Test: `apps/vault-server/tests/test_daily_route.py`

**Interfaces:**
- Consumes: `resolve_state` from `src.services.approval`.
- Produces: `DayCoverage` gains `confirmed_minutes: int` and `pending_minutes: int`; `DailyBlock.state` now holds `"approved"` or `"pending"`; `_build_blocks_and_coverage` keeps its 3-tuple return `(blocks, gaps, coverage)`.

Spec §3. Three numbers, **two different unions**:

| | |
|---|---|
| `confirmed_minutes` | union of approved intervals, clipped to elapsed |
| `pending_minutes` | union of pending intervals, minus anything already confirmed |
| gaps + `unaccounted_minutes` | over **all** blocks, approved and pending together |

The two unions are the point. Computing gaps over approved blocks only would put every pending block inside a `░` row covering the same span — two rows claiming the same time with opposite meanings. Over everything, `░` always means *nothing is there at all*.

`covered_minutes` **keeps its current meaning** (union over all blocks), so the webapp and any other consumer do not break.

Dismissed blocks are omitted from `blocks[]` entirely, and the span they occupied becomes a gap (§2.5).

`day_coverage.py` is not modified. It is called twice with different interval lists.

**Do not change the arity of `_build_blocks_and_coverage`.** Thirteen existing tests unpack its 3-tuple.

- [ ] **Step 1: Write the failing tests**

Add to `apps/vault-server/tests/test_daily_route.py`, inside `class TestDailyBlocks`:

```python
    def test_coverage_model_fields(self):
        from src.api.routes.daily import DayCoverage

        assert set(DayCoverage.model_fields) == {
            "covered_minutes", "unaccounted_minutes", "elapsed_minutes",
            "confirmed_minutes", "pending_minutes",
        }

    def test_pending_block_closes_the_gap_but_does_not_confirm(self):
        """THE test that pins §3. A pending block must not leave a gap over
        its own span — that would render two rows claiming the same time with
        opposite meanings — and must not count as confirmed either."""
        from src.api.routes.daily import _build_blocks_and_coverage

        events = [{
            "id": "e1", "name": "Standup", "source": "calendar",
            "source_ids": {"calendar_id": "g1"},
            "start_time": "2026-09-10T09:00", "end_time": "2026-09-10T10:00",
        }]

        blocks, gaps, coverage = _build_blocks_and_coverage(events, "2026-09-10", 720)

        assert [b.state for b in blocks] == ["pending"]
        assert coverage.confirmed_minutes == 0
        assert coverage.pending_minutes == 60
        # 09:00-10:00 is accounted for, so no gap covers it.
        assert not any(g.start <= "09:30" <= g.end for g in gaps)
        assert coverage.covered_minutes == 60
        assert coverage.unaccounted_minutes == 720 - 60

    def test_approved_block_counts_as_confirmed(self):
        from src.api.routes.daily import _build_blocks_and_coverage

        events = [{
            "id": "e1", "name": "Dog walk", "source": "manual",
            "source_ids": {},
            "start_time": "2026-09-10T07:00", "end_time": "2026-09-10T08:00",
        }]

        blocks, _gaps, coverage = _build_blocks_and_coverage(events, "2026-09-10", 720)

        assert [b.state for b in blocks] == ["approved"]
        assert coverage.confirmed_minutes == 60
        assert coverage.pending_minutes == 0

    def test_pending_minutes_excludes_time_already_confirmed(self):
        """Overlapping blocks of different states must not double-count: the
        confirmed hour wins and pending reports only what it adds."""
        from src.api.routes.daily import _build_blocks_and_coverage

        events = [
            {"id": "a", "name": "Lunch", "source": "manual", "source_ids": {},
             "start_time": "2026-09-10T12:00", "end_time": "2026-09-10T13:00"},
            {"id": "b", "name": "Lunch meeting", "source": "calendar",
             "source_ids": {"calendar_id": "g1"},
             "start_time": "2026-09-10T12:30", "end_time": "2026-09-10T14:00"},
        ]

        _blocks, _gaps, coverage = _build_blocks_and_coverage(events, "2026-09-10", 900)

        assert coverage.confirmed_minutes == 60      # 12:00-13:00
        assert coverage.pending_minutes == 60        # 13:00-14:00 only
        assert coverage.covered_minutes == 120       # 12:00-14:00

    def test_dismissed_block_is_omitted_and_its_time_reopens(self):
        """§2.5. A meeting you skipped means that hour really is unaccounted,
        and the gap is then the prompt to say what you did instead."""
        from src.api.routes.daily import _build_blocks_and_coverage

        events = [{
            "id": "e1", "name": "Standup", "source": "calendar",
            "source_ids": {"calendar_id": "g1"}, "state": "dismissed",
            "start_time": "2026-09-10T09:00", "end_time": "2026-09-10T10:00",
        }]

        blocks, gaps, coverage = _build_blocks_and_coverage(events, "2026-09-10", 720)

        assert blocks == []
        assert coverage.covered_minutes == 0
        assert any(g.start <= "09:30" <= g.end for g in gaps)

    def test_still_ahead_blocks_count_toward_neither(self):
        """day_coverage already clips to elapsed; assert it holds for both
        of the new numbers, not just the old one."""
        from src.api.routes.daily import _build_blocks_and_coverage

        events = [{
            "id": "e1", "name": "Guitar", "source": "manual", "source_ids": {},
            "start_time": "2026-09-10T21:00", "end_time": "2026-09-10T22:00",
        }]

        blocks, _gaps, coverage = _build_blocks_and_coverage(events, "2026-09-10", 720)

        assert len(blocks) == 1              # still rendered
        assert coverage.confirmed_minutes == 0
        assert coverage.pending_minutes == 0
```

- [ ] **Step 2: Run to verify they fail**

```bash
./venv/bin/python -m pytest tests/test_daily_route.py -q -k "coverage or pending or dismissed or ahead"
```
Expected: FAIL — `DayCoverage` has no `confirmed_minutes`.

- [ ] **Step 3: Add the two fields to `DayCoverage`**

In `apps/vault-server/src/api/routes/daily.py`, add to `class DayCoverage` after `elapsed_minutes`:

```python
    # Two different unions over the same block list (spec §3). `covered` is
    # every drawable block, which is what gaps are computed from — so a `░`
    # row always means nothing is there at all, and can never overlap a
    # pending block. `confirmed` is approved blocks only, and is the only
    # number the weekly readout (Ship 9) may read.
    confirmed_minutes: int = 0
    # Pending time that is not already confirmed. Subtracted rather than
    # counted independently, so two overlapping blocks of different states
    # do not add up to more than the wall clock.
    pending_minutes: int = 0
```

- [ ] **Step 4: Rewrite `_build_blocks_and_coverage`**

Replace `_build_blocks_and_coverage` in `apps/vault-server/src/api/routes/daily.py` with:

```python
def _build_blocks_and_coverage(
    events: list[dict], date: str, elapsed_minutes: int
) -> tuple[list[DailyBlock], list[DailyGap], DayCoverage]:
    """Turn merged events into the day's timeline, plus its coverage.

    Events that *start* outside `date` are dropped: storage splits at
    midnight, so a neighbouring day's fragment here would distort this
    day's arithmetic. An event that starts on `date` and ends after it is
    clipped to `24:00` rather than dropped — see `_end_minutes`.

    Dismissed events are dropped entirely and the span they occupied becomes
    a gap (spec §2.5): a meeting you skipped means that hour really is
    unaccounted, and the gap is the prompt to say what you did instead.
    """
    blocks: list[DailyBlock] = []
    all_intervals: list[tuple[int, int]] = []
    approved_intervals: list[tuple[int, int]] = []

    for e in events:
        state = resolve_state(e)
        if state == "dismissed":
            continue
        start, end, _, _ = _block_times(e, date)
        if start is None or end is None:
            continue
        habit = e.get("habit") or {}
        target = habit.get("daily_target")
        blocks.append(DailyBlock(
            id=e.get("id", ""),
            start=f"{start // 60:02d}:{start % 60:02d}",
            end=f"{end // 60:02d}:{end % 60:02d}",
            title=e.get("name", ""),
            # `or default`, not `.get(k, default)`: a persisted event can
            # carry an explicit `null` for these keys, and `.get` only
            # supplies its default when the key is absent — an explicit
            # None sails through and 500s the endpoint at the pydantic
            # boundary (`type`/`source`/`state` are non-optional `str`).
            source=e.get("source") or "",
            type=e.get("type") or "",
            # `habit.completed` is the fallback, not the source: it is
            # where completion used to live, so persisted events written
            # before `MergedEvent.completed` existed still carry it there.
            completed=bool(e.get("completed") or habit.get("completed", False)),
            activity=e.get("activity"),
            category=e.get("category"),
            state=state,
            habit_progress=(
                f"{habit.get('completions_today', 0)}/{target}" if target else None
            ),
        ))
        all_intervals.append((start, end))
        if state == "approved":
            approved_intervals.append((start, end))

    blocks.sort(key=lambda b: b.start)

    # Two calls, two unions. Gaps come from the first — over every drawable
    # block — so a gap means nothing is there at all. Were gaps computed
    # from the approved set, every pending block would sit inside a `░` row
    # covering the same span, which is incoherent to read.
    raw_gaps, coverage = day_coverage(all_intervals, elapsed_minutes)
    _approved_gaps, approved_coverage = day_coverage(approved_intervals, elapsed_minutes)

    confirmed = approved_coverage.covered_minutes
    return (
        blocks,
        [DailyGap(start=g.start, end=g.end, minutes=g.minutes) for g in raw_gaps],
        DayCoverage(
            covered_minutes=coverage.covered_minutes,
            unaccounted_minutes=coverage.unaccounted_minutes,
            elapsed_minutes=elapsed_minutes,
            confirmed_minutes=confirmed,
            # Never negative: `confirmed` is a union over a subset of
            # `all_intervals`, so it cannot exceed `covered`.
            pending_minutes=coverage.covered_minutes - confirmed,
        ),
    )
```

Add the import at the top of the file, beside the existing `day_coverage` import:

```python
from src.services.approval import resolve_state
```

- [ ] **Step 5: Run the tests**

```bash
./venv/bin/python -m pytest tests/test_daily_route.py -q
./venv/bin/python -m pytest tests/ -q
```
Expected: green. The 13 existing tests that unpack the 3-tuple keep working — its arity is deliberately unchanged.

- [ ] **Step 6: Commit**

```bash
git add apps/vault-server/src/api/routes/daily.py apps/vault-server/tests/test_daily_route.py
git commit -m "feat(daily): confirmed and pending coverage from two unions"
```

---

## Task 4: Gap proposals — the history ladder

**Files:**
- Create: `apps/vault-server/src/services/gap_proposals.py`
- Test: `apps/vault-server/tests/test_gap_proposals.py`

**Interfaces:**
- Consumes: `is_approved` from `src.services.approval`; `minutes_into_day` from `src.services.day_coverage`.
- Produces:
  - `propose_for_gap(start: int, end: int, history: list[list[dict]]) -> dict | None` returning `{"name": str, "days_seen": int}` or `None`. `history` is one event list per previous day, most recent first, already loaded by the caller.
  - `HISTORY_DAYS = 14`, `MIN_DAYS_SEEN = 3`, `OVERLAP_FRACTION = 0.5`, `SLEEP_CORE = (120, 300)`, `SLEEP_NAME = "Sleep"`.

Spec §4.1. Ladder, first hit wins:

1. **History.** Approved blocks from the previous 14 days that overlap the same clock window by **at least half the gap's length**. If the most frequent `name` among them appears on **at least 3 distinct days**, propose it.
2. **The overnight rule.** A gap that **fully contains 02:00–05:00** proposes `Sleep`. Cold-start seed only — with history present, step 1 already fired.
3. **Nothing.** Return `None`; the gap keeps its `+ <duration>` button and asks.

The module takes already-loaded history rather than a path, so every test is a list literal and no test touches the filesystem.

- [ ] **Step 1: Write the failing tests**

Create `apps/vault-server/tests/test_gap_proposals.py`:

```python
"""Gap proposals — spec §4.1."""

from src.services.gap_proposals import (
    HISTORY_DAYS, MIN_DAYS_SEEN, propose_for_gap,
)


def blk(name, start, end, *, approved=True):
    """An event spanning `start`-`end` as "HH:MM" strings on an arbitrary day.
    `propose_for_gap` compares clock windows, so the date is irrelevant."""
    return {
        "name": name,
        "start_time": f"2026-09-01T{start}",
        "end_time": f"2026-09-01T{end}",
        "source": "manual" if approved else "calendar",
        "source_ids": {} if approved else {"calendar_id": "g1"},
    }


def day(*blocks):
    return list(blocks)


class TestHistory:
    def test_proposes_a_name_seen_on_three_days(self):
        history = [day(blk("Sleep", "00:20", "06:40")) for _ in range(3)]

        assert propose_for_gap(20, 400, history) == {"name": "Sleep", "days_seen": 3}

    def test_two_days_is_below_the_floor(self):
        history = [day(blk("Sleep", "00:20", "06:40")) for _ in range(2)]

        assert propose_for_gap(20, 400, history) is None

    def test_counts_distinct_days_not_blocks(self):
        """Three blocks on one day is one day's evidence, not three."""
        history = [day(
            blk("Lunch", "12:00", "12:20"),
            blk("Lunch", "12:20", "12:40"),
            blk("Lunch", "12:40", "13:00"),
        )]

        assert propose_for_gap(720, 780, history) is None

    def test_most_frequent_name_wins(self):
        history = [
            day(blk("Lunch", "12:00", "13:00")),
            day(blk("Lunch", "12:00", "13:00")),
            day(blk("Lunch", "12:00", "13:00")),
            day(blk("Errand", "12:00", "13:00")),
        ]

        assert propose_for_gap(720, 780, history) == {"name": "Lunch", "days_seen": 3}

    def test_overlap_below_half_the_gap_does_not_count(self):
        """A 20-minute coffee inside a two-hour hole is not evidence for what
        filled the hole."""
        history = [day(blk("Coffee", "12:00", "12:20")) for _ in range(5)]

        assert propose_for_gap(720, 840, history) is None

    def test_overlap_of_exactly_half_counts(self):
        """The threshold is "at least half", so the boundary is inclusive."""
        history = [day(blk("Nap", "12:00", "13:00")) for _ in range(3)]

        assert propose_for_gap(720, 840, history) == {"name": "Nap", "days_seen": 3}

    def test_pending_blocks_are_not_evidence(self):
        """Only approved blocks are history. An unconfirmed calendar entry is
        exactly the guess we are trying not to compound."""
        history = [day(blk("Standup", "12:00", "13:00", approved=False))
                   for _ in range(5)]

        assert propose_for_gap(720, 780, history) is None

    def test_dismissed_blocks_are_not_evidence(self):
        history = []
        for _ in range(5):
            b = blk("Standup", "12:00", "13:00")
            b["state"] = "dismissed"
            history.append(day(b))

        assert propose_for_gap(720, 780, history) is None

    def test_history_beats_the_overnight_rule(self):
        """An overnight gap where history says something else must follow
        history — the sleep rule is a cold-start seed, not an override."""
        history = [day(blk("Night shift", "00:00", "07:00")) for _ in range(4)]

        assert propose_for_gap(0, 420, history) == {"name": "Night shift", "days_seen": 4}

    def test_ignores_blocks_with_unusable_times(self):
        """Ten days, deliberately: at two the test sits below MIN_DAYS_SEEN and
        would pass whether or not the bad times were skipped, asserting nothing
        about the behaviour it names."""
        history = []
        for _ in range(5):
            history.append(day({"name": "Broken", "source": "manual",
                                "source_ids": {}}))
            history.append(day({"name": "Broken", "start_time": "nonsense",
                                "end_time": "also nonsense",
                                "source": "manual", "source_ids": {}}))

        assert propose_for_gap(720, 780, history) is None

    def test_only_the_first_HISTORY_DAYS_days_are_read(self):
        """A caller passing more than 14 must not get a proposal from day 20."""
        history = [day() for _ in range(HISTORY_DAYS)]
        history += [day(blk("Ancient", "12:00", "13:00")) for _ in range(5)]

        assert propose_for_gap(720, 780, history) is None


class TestOvernightRule:
    def test_fires_on_an_empty_store(self):
        assert propose_for_gap(20, 400, []) == {"name": "Sleep", "days_seen": 0}

    def test_needs_the_whole_core_window(self):
        """A gap must fully contain 02:00-05:00. An evening hole is not sleep
        however long it is."""
        assert propose_for_gap(1080, 1380, []) is None      # 18:00-23:00
        assert propose_for_gap(120, 240, []) is None        # 02:00-04:00, partial
        assert propose_for_gap(180, 360, []) is None        # 03:00-06:00, partial

    def test_fires_on_exactly_the_core_window(self):
        assert propose_for_gap(120, 300, []) == {"name": "Sleep", "days_seen": 0}


class TestDegenerateInput:
    def test_a_zero_length_gap_proposes_nothing(self):
        assert propose_for_gap(720, 720, []) is None

    def test_an_inverted_gap_proposes_nothing(self):
        assert propose_for_gap(800, 700, []) is None


class TestConstants:
    def test_thresholds_are_the_spec_values(self):
        """These are stated constraints, not tuning knobs. If a test needs one
        changed, the test data is wrong — see Ship 4's R8, where an
        implementer lowered a fuzzy-match floor to make a bad test pass."""
        assert HISTORY_DAYS == 14
        assert MIN_DAYS_SEEN == 3
```

- [ ] **Step 2: Run to verify they fail**

```bash
./venv/bin/python -m pytest tests/test_gap_proposals.py -q
```
Expected: collection error, `No module named 'src.services.gap_proposals'`.

- [ ] **Step 3: Write the implementation**

Create `apps/vault-server/src/services/gap_proposals.py`:

```python
"""What probably filled a gap — spec §4.1.

Guess when there is a basis, ask otherwise. The basis is the events store
itself: the last two weeks of approved blocks. No new store, no network, no
accumulation mechanism to build.

Pure arithmetic over minute offsets and a caller-supplied history, so nothing
here touches the filesystem. The caller loads the date files; this decides
what they mean.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from src.services.approval import is_approved
from src.services.day_coverage import minutes_into_day

# How many previous days of approved blocks count as history.
HISTORY_DAYS = 14

# How many *distinct days* a name must appear on before it is proposed. Three
# of fourteen is deliberately low: a proposal is a question with a ✕ next to
# it, not an assertion, and the row shows the count so it can be judged.
MIN_DAYS_SEEN = 3

# How much of the gap a historical block must cover to be evidence for what
# filled it. A twenty-minute coffee inside a two-hour hole says nothing about
# the hole. Inclusive: exactly half counts.
OVERLAP_FRACTION = 0.5

# The core of the night, in minutes from midnight (02:00-05:00). A gap must
# contain all of it to read as sleep — an evening hole is not sleep however
# long it is.
SLEEP_CORE = (120, 300)

SLEEP_NAME = "Sleep"


def _overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start))


def _block_window(event: dict[str, Any]) -> tuple[int, int] | None:
    """The event's clock window in minutes from midnight, or None.

    The date the block sits on is irrelevant here — we are asking "what
    usually happens at this time of day", so only the clock matters. An end
    that parses as at or before its start belongs to a cross-midnight
    fragment whose other half lives in its own date file; ignore it rather
    than guess which.
    """
    start_raw, end_raw = event.get("start_time"), event.get("end_time")
    if not start_raw or not end_raw:
        return None
    start_day = str(start_raw).partition("T")[0]
    start = minutes_into_day(str(start_raw), start_day)
    end = minutes_into_day(str(end_raw), start_day)
    if start is None or end is None or end <= start:
        return None
    return start, end


def propose_for_gap(
    start: int, end: int, history: list[list[dict[str, Any]]]
) -> dict[str, Any] | None:
    """`{"name", "days_seen"}` for a gap `[start, end)`, or None to ask.

    `history` is one event list per previous day, most recent first, already
    loaded by the caller. Only the first `HISTORY_DAYS` are read, so a caller
    passing more cannot smuggle in older evidence.

    Ladder, first hit wins: history, then the overnight seed, then nothing.
    """
    gap_minutes = end - start
    if gap_minutes <= 0:
        return None

    needed = gap_minutes * OVERLAP_FRACTION
    days_by_name: dict[str, set[int]] = defaultdict(set)

    for day_index, events in enumerate(history[:HISTORY_DAYS]):
        for event in events:
            if not is_approved(event):
                continue
            window = _block_window(event)
            if window is None:
                continue
            if _overlap(start, end, *window) >= needed:
                name = (event.get("name") or "").strip()
                if name:
                    days_by_name[name].add(day_index)

    if days_by_name:
        # Ties break on the name, so the same history always yields the same
        # proposal. §4.2 depends on that: the server recomputes the proposal
        # when the user approves it rather than trusting a client-sent name,
        # and a nondeterministic tiebreak would make the two disagree.
        name, days = max(days_by_name.items(), key=lambda kv: (len(kv[1]), kv[0]))
        if len(days) >= MIN_DAYS_SEEN:
            return {"name": name, "days_seen": len(days)}

    core_start, core_end = SLEEP_CORE
    if start <= core_start and end >= core_end:
        return {"name": SLEEP_NAME, "days_seen": 0}

    return None
```

- [ ] **Step 4: Run the tests**

```bash
./venv/bin/python -m pytest tests/test_gap_proposals.py -q
./venv/bin/python -m pytest tests/ -q
```
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/gap_proposals.py apps/vault-server/tests/test_gap_proposals.py
git commit -m "feat(daily): propose what filled a gap, from your own history"
```

---

## Task 5: Wire proposals into `/daily`

**Files:**
- Modify: `apps/vault-server/src/api/routes/daily.py`
- Test: `apps/vault-server/tests/test_daily_route.py`

**Interfaces:**
- Consumes: `propose_for_gap`, `HISTORY_DAYS` from `src.services.gap_proposals`.
- Produces: new model `GapProposal` with `name: str`, `days_seen: int`; `DailyGap` gains `proposal: GapProposal | None`; helpers `_load_history(events_svc, target_date) -> list[list[dict]]` and `_decorate_gaps(gaps, history) -> list[DailyGap]`.

Spec §4.1. History comes from the persisted store for the 14 dates before the one being viewed — `EventsService.get_events` per date, which is local file reads and no network. A missing date file yields `[]`, which the service already does.

Gaps are built inside `_build_blocks_and_coverage`, which is pure and has no service access. Rather than thread a service into it, `get_daily` decorates the gaps it returns. That keeps the pure function pure and the I/O at the route — the same reason `day_coverage.py` takes minute offsets rather than events.

- [ ] **Step 1: Write the failing tests**

Add to `apps/vault-server/tests/test_daily_route.py`:

```python
class TestGapProposals:
    def test_gap_model_has_a_proposal_field(self):
        from src.api.routes.daily import DailyGap, GapProposal

        assert set(DailyGap.model_fields) == {"start", "end", "minutes", "proposal"}
        assert set(GapProposal.model_fields) == {"name", "days_seen"}

    def test_decorates_gaps_with_proposals(self):
        from src.api.routes.daily import DailyGap, _decorate_gaps

        gaps = [
            DailyGap(start="00:20", end="06:40", minutes=380),
            DailyGap(start="16:00", end="17:30", minutes=90),
        ]

        decorated = _decorate_gaps(gaps, history=[])

        assert decorated[0].proposal is not None
        assert decorated[0].proposal.name == "Sleep"
        assert decorated[1].proposal is None

    def test_a_gap_ending_at_2400_is_handled(self):
        """day_coverage emits "24:00" for a gap running to end of day, which
        is not a parseable clock time. It must not crash the decorator."""
        from src.api.routes.daily import DailyGap, _decorate_gaps

        gaps = [DailyGap(start="23:00", end="24:00", minutes=60)]

        assert _decorate_gaps(gaps, history=[])[0].proposal is None

    def test_history_is_read_from_the_days_before_the_target(self, tmp_path):
        """Reads the 14 date files before the one being viewed, and never the
        target's own — today's blocks are not evidence about today."""
        import datetime as dt
        from src.api.routes.daily import _load_history
        from src.services.events_service import EventsService

        svc = EventsService(tmp_path / "events")
        svc.save_events("2026-09-09", [{"id": "a", "name": "Sleep"}])
        svc.save_events("2026-09-10", [{"id": "b", "name": "Target day"}])

        history = _load_history(svc, dt.date(2026, 9, 10))

        assert len(history) == 14
        names = [e["name"] for day in history for e in day]
        assert "Sleep" in names
        assert "Target day" not in names

    def test_history_order_is_most_recent_first(self, tmp_path):
        import datetime as dt
        from src.api.routes.daily import _load_history
        from src.services.events_service import EventsService

        svc = EventsService(tmp_path / "events")
        svc.save_events("2026-09-09", [{"id": "a", "name": "Yesterday"}])
        svc.save_events("2026-09-08", [{"id": "b", "name": "Day before"}])

        history = _load_history(svc, dt.date(2026, 9, 10))

        assert history[0][0]["name"] == "Yesterday"
        assert history[1][0]["name"] == "Day before"
```

- [ ] **Step 2: Run to verify they fail**

```bash
./venv/bin/python -m pytest tests/test_daily_route.py -q -k "proposal or history"
```
Expected: FAIL — no `GapProposal`, no `_decorate_gaps`.

- [ ] **Step 3: Add the model**

In `apps/vault-server/src/api/routes/daily.py`, add above `class DailyGap`:

```python
class GapProposal(BaseModel):
    """What probably filled a gap. A question, not an assertion — the row
    renders it with a ✕ beside it, and `days_seen` is shown so the guess can
    be judged rather than trusted."""
    name: str
    days_seen: int
```

Change `class DailyGap` to:

```python
class DailyGap(BaseModel):
    start: str
    end: str
    minutes: int
    # None means "no basis to guess" — the gap asks instead (spec §4.1).
    proposal: GapProposal | None = None
```

- [ ] **Step 4: Add the two helpers**

Add after `_build_blocks_and_coverage`:

```python
def _load_history(events_svc, target_date: dt_date) -> list[list[dict]]:
    """The `HISTORY_DAYS` date files before `target_date`, most recent first.

    Local reads only — `get_events` returns [] for a missing file, so a short
    history needs no special case. The target's own date is excluded: today's
    blocks are not evidence about what usually happens today.
    """
    return [
        events_svc.get_events((target_date - timedelta(days=offset)).isoformat())
        for offset in range(1, HISTORY_DAYS + 1)
    ]


def _decorate_gaps(
    gaps: list[DailyGap], history: list[list[dict]]
) -> list[DailyGap]:
    """Attach a proposal to each gap that has a basis for one.

    Done here rather than inside `_build_blocks_and_coverage` so that
    function stays pure arithmetic with no service access — the same reason
    `day_coverage.py` takes minute offsets and not events.
    """
    out: list[DailyGap] = []
    for gap in gaps:
        # `minutes_into_day` needs a date only to reject timestamps belonging
        # to another day; gap times are bare "HH:MM", so "" never matches and
        # never rejects. "24:00" is deliberately unparseable (day_coverage
        # emits it for end-of-day) and comes back None rather than raising.
        start = minutes_into_day(gap.start, "")
        end = minutes_into_day(gap.end, "")
        proposal = None
        if start is not None and end is not None:
            found = propose_for_gap(start, end, history)
            if found:
                proposal = GapProposal(**found)
        out.append(gap.model_copy(update={"proposal": proposal}))
    return out
```

Update the imports at the top of the file — add `timedelta` to the existing datetime import and add the gap-proposals import:

```python
from datetime import date as dt_date, datetime, timedelta
from src.services.gap_proposals import HISTORY_DAYS, propose_for_gap
```

- [ ] **Step 5: Call them from `get_daily`**

In `get_daily`, after the `incomplete = _build_incomplete(events, target)` line, insert:

```python
    # Gap proposals read the persisted store for previous dates. Local file
    # reads, no network — and a failure here must cost the proposals only,
    # never the day: an unreadable history is not a reason to show no blocks.
    from src.main import get_events as get_events_svc
    events_svc = get_events_svc()
    if events_svc is not None:
        try:
            gaps = _decorate_gaps(gaps, _load_history(events_svc, target_date))
        except Exception:
            logger.warning(
                "GET /daily?date=%s: gap proposals failed, gaps will ask instead",
                target, exc_info=True,
            )
```

- [ ] **Step 6: Run the tests**

```bash
./venv/bin/python -m pytest tests/test_daily_route.py -q
./venv/bin/python -m pytest tests/ -q
```
Expected: green. The `DailyResponse` field-set tripwire is untouched by this task and must still pass unchanged.

- [ ] **Step 7: Commit**

```bash
git add apps/vault-server/src/api/routes/daily.py apps/vault-server/tests/test_daily_route.py
git commit -m "feat(daily): attach gap proposals to /daily"
```

---

## Task 6: `complete_habit` stamps in `VAULT_TIMEZONE`

**Files:**
- Modify: `apps/vault-server/src/services/habit_completion.py:76-97`
- Test: `apps/vault-server/tests/test_habit_completion.py`

**Interfaces:**
- Consumes: `settings.vault_timezone` from `src.config`.
- Produces: `complete_habit(vault, path, now=None)` — signature unchanged; its default `now` becomes timezone-aware.

Spec §8.2, closing a pre-recorded bug. The phase doc §11 says: *"`habits.py` reads 'today' in `VAULT_TIMEZONE` but writes via the server clock — inert while they match. Fix in Ship 5, which is the code that cares."*

Ship 5 is that code, because Task 7 approves blocks on past dates and each must stamp *that* date. The `now` parameter already exists and is already honoured; only the default is wrong.

- [ ] **Step 1: Write the failing tests**

Add to `apps/vault-server/tests/test_habit_completion.py`. Put the helper class at module level:

```python
class _FrozenDatetime:
    """Stands in for `dt.datetime` so `dt.datetime.now(tz)` is deterministic.
    Only `now` is overridden; everything else defers to the real class."""

    def __init__(self, instant):
        self._instant = instant

    def now(self, tz=None):
        return self._instant.astimezone(tz) if tz else self._instant.replace(tzinfo=None)

    def __getattr__(self, name):
        import datetime as _dt
        return getattr(_dt.datetime, name)


class _RecordingVault:
    """The minimum surface complete_habit touches."""

    def __init__(self):
        self.written = {}

    def read_file(self, path):
        return {"metadata": {"name": "Dog walk", "streak": 0}, "content": ""}

    def write_file(self, path, metadata, content):
        self.written["last_completed"] = metadata.get("last_completed")

    def read_token_ledger(self):
        return {"metadata": {"tokens_today": 0, "total_tokens": 0}}

    def write_token_ledger(self, *a, **kw):
        pass


def test_default_now_is_vault_timezone_not_the_server_clock(monkeypatch):
    """The recorded bug (phase doc §11): the default was `dt.datetime.now()` —
    naive, server-clock — while habits.py has always read "today" in the
    vault's timezone. Inert while the two agree, and wrong by a day for the
    first hours of every local day when they don't."""
    import datetime as dt
    from src.services import habit_completion

    # A UTC instant that is already the next day in Asia/Jerusalem (UTC+3 in
    # September): 22:30Z on the 10th is 01:30 on the 11th.
    monkeypatch.setattr(
        habit_completion.dt, "datetime",
        _FrozenDatetime(dt.datetime(2026, 9, 10, 22, 30, tzinfo=dt.timezone.utc)),
    )
    vault = _RecordingVault()

    result = habit_completion.complete_habit(vault, "20-habits/dog-walk.md")

    assert result["date"] == "2026-09-11"
    assert vault.written["last_completed"] == "2026-09-11"


def test_an_explicit_now_stamps_that_date():
    """What Task 7 relies on: approving Monday's block records Monday."""
    import datetime as dt
    from src.services.habit_completion import complete_habit

    vault = _RecordingVault()

    result = complete_habit(
        vault, "20-habits/dog-walk.md", now=dt.datetime(2026, 9, 7, 19, 0),
    )

    assert result["date"] == "2026-09-07"
    assert vault.written["last_completed"] == "2026-09-07"
```

If `_RecordingVault`'s method set does not match what `complete_habit` actually calls, read the function and extend the stub — the assertion to keep is that `last_completed` and the returned `date` are the intended day.

- [ ] **Step 2: Run to verify the first test fails**

```bash
./venv/bin/python -m pytest tests/test_habit_completion.py -q -k timezone
```
Expected: FAIL — the naive default gives `2026-09-10`, not `2026-09-11`.

- [ ] **Step 3: Fix the default**

In `apps/vault-server/src/services/habit_completion.py`, replace:

```python
    now = now or dt.datetime.now()
```

with:

```python
    # `VAULT_TIMEZONE`, not the server clock. `habits.py` has always read
    # "today" in the vault's timezone while this wrote in the server's —
    # inert while the two agree, and off by a day for the first hours of
    # every local day when they don't (phase-2 doc §11). Ship 5 is the code
    # that cares: approving a block on a past date must stamp that date, and
    # a caller passing `now` explicitly is how it does so.
    now = now or dt.datetime.now(pytz.timezone(settings.vault_timezone))
```

Add to the imports at the top of the file:

```python
import pytz

from src.config import settings
```

- [ ] **Step 4: Run the tests**

```bash
./venv/bin/python -m pytest tests/test_habit_completion.py -q
./venv/bin/python -m pytest tests/ -q
```
Expected: green. Any existing habit test that passes `now` explicitly still passes — that path was already honoured and is unchanged.

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/habit_completion.py apps/vault-server/tests/test_habit_completion.py
git commit -m "fix(habits): stamp completions in VAULT_TIMEZONE"
```

---

## Task 7: `POST /events/{date}/{event_id}/state`

**Files:**
- Modify: `apps/vault-server/src/api/routes/events.py`
- Test: `apps/vault-server/tests/test_events_route.py`

**Interfaces:**
- Consumes: `resolve_state` (Task 1), `complete_habit` (Task 6), `_merge_from_sources` (already imported in this file as `_merge_from_sources`).
- Produces: `SetStateBody` with `state: Literal["approved", "dismissed"]`; `POST /events/{date}/{event_id}/state` returning
  ```python
  {"ok": bool, "state": str, "event_id": str,
   "habit": {"name": str, "tokens_earned": int, "new_streak": int} | None,
   "checkbox": {"text": str} | None}
  ```

Spec §2.3. The dispatch:

| source | `approved` | `dismissed` |
|---|---|---|
| calendar | store `approved` | store `dismissed` |
| timeline visit / transit | store `approved` | store `dismissed` |
| habit, not fired | **tick the habit**, store nothing | store `dismissed` |
| checkbox, timed, unchecked | **check it**, store nothing | store `dismissed` |
| manual / spoken | already approved — no-op | store `dismissed` |

Ticking writes no `state` row: once the habit is ticked, `resolve_state` derives `"approved"` from `completed` on the next merge. Storing one as well would key an approval to an unstable `habit_slug` — the stale-row bug of §2.1.

Two things must be right or this route is subtly broken:

1. **Read the merged view, not the raw file.** A habit- or note-derived block often has no persisted row at all, because `/daily` reconciles without saving. So resolve the event out of `reconcile`'s output.
2. **Persist only when storing state.** Approving a habit block needs no row and must not write one.

**Nothing in this ship unticks a habit or retracts tokens** (§2.4). Dismissing an already-approved human-source block is unreachable from `/day` (approved rows carry no buttons), so the endpoint refuses it with 409 rather than inventing a reverse path.

- [ ] **Step 1: Write the failing tests**

Add to `apps/vault-server/tests/test_events_route.py`:

```python
class TestSetState:
    """POST /events/{date}/{id}/state — spec §2.3."""

    def _install(self, monkeypatch, events):
        """Stub the events service and the source merge, returning the fake so
        tests can inspect what was saved."""
        import src.main as main
        import src.api.routes.events as events_route

        class FakeEvents:
            def __init__(self):
                self.saved = {}

            def get_events(self, date):
                return [dict(e) for e in events]

            def reconcile(self, date, fresh, available=None):
                return [dict(e) for e in events]

            def save_events(self, date, evts):
                self.saved[date] = evts

        fake = FakeEvents()
        monkeypatch.setattr(main, "get_events", lambda: fake)

        async def no_sources(date):
            return [], set()

        monkeypatch.setattr(events_route, "_merge_from_sources", no_sources)
        return fake

    def _client(self):
        from fastapi.testclient import TestClient
        from src.main import app
        return TestClient(app)

    def test_approving_a_calendar_block_stores_approved(self, monkeypatch):
        fake = self._install(monkeypatch, [
            {"id": "e1", "name": "Standup", "source": "calendar",
             "source_ids": {"calendar_id": "g1"}},
        ])

        r = self._client().post("/events/2026-09-10/e1/state",
                                json={"state": "approved"})

        assert r.status_code == 200
        assert r.json()["state"] == "approved"
        assert fake.saved["2026-09-10"][0]["state"] == "approved"

    def test_dismissing_a_calendar_block_stores_dismissed(self, monkeypatch):
        fake = self._install(monkeypatch, [
            {"id": "e1", "name": "Standup", "source": "calendar",
             "source_ids": {"calendar_id": "g1"}},
        ])

        r = self._client().post("/events/2026-09-10/e1/state",
                                json={"state": "dismissed"})

        assert r.json()["state"] == "dismissed"
        assert fake.saved["2026-09-10"][0]["state"] == "dismissed"

    def test_dismissing_never_touches_google(self, monkeypatch):
        """§2.5 and §9: dismissal is local in this ship. cancel and delete are
        deferred, and a dismissal must not quietly become either."""
        import src.main as main

        calls = []
        self._install(monkeypatch, [
            {"id": "e1", "name": "Standup", "source": "calendar",
             "source_ids": {"calendar_id": "g1"}, "calendar_id": "g1"},
        ])

        class LoudCalendar:
            async def delete_event(self, *a, **kw):
                calls.append("delete")

            async def update_event(self, *a, **kw):
                calls.append("update")

        monkeypatch.setattr(main, "get_calendar", lambda: LoudCalendar())

        self._client().post("/events/2026-09-10/e1/state",
                            json={"state": "dismissed"})

        assert calls == []

    def test_approving_an_unfired_habit_ticks_it_and_stores_nothing(self, monkeypatch):
        """Ticking makes `completed` true, so resolve_state derives approved on
        the next merge. Storing a state row as well is the §2.1 stale-row bug,
        because habit_slug ids are not stable."""
        import src.main as main
        import src.api.routes.events as events_route

        fake = self._install(monkeypatch, [
            {"id": "e1", "name": "Dog walk", "source": "habit",
             "source_ids": {"habit_slug": "dog-walk"}, "completed": False,
             "habit": {"name": "Dog walk"},
             "start_time": "2026-09-10T19:00", "end_time": "2026-09-10T20:00"},
        ])

        class FakeVault:
            def list_active_habits(self):
                return [{"metadata": {"name": "Dog walk"},
                         "path": "20-habits/dog-walk.md"}]

        monkeypatch.setattr(main, "get_vault", lambda: FakeVault())

        seen = {}

        def fake_complete(vault, path, now=None):
            seen["path"] = path
            seen["now"] = now
            return {"already_completed": False, "name": "Dog walk",
                    "tokens_earned": 5, "new_streak": 13,
                    "date": now.date().isoformat()}

        monkeypatch.setattr(events_route, "complete_habit", fake_complete)

        r = self._client().post("/events/2026-09-10/e1/state",
                                json={"state": "approved"})

        assert r.json()["habit"]["tokens_earned"] == 5
        assert r.json()["habit"]["new_streak"] == 13
        assert seen["path"] == "20-habits/dog-walk.md"
        assert fake.saved == {}          # no state row written

    def test_approving_a_habit_block_stamps_the_blocks_date(self, monkeypatch):
        """The reason Task 6 exists. Confirming Monday's block records Monday,
        not today."""
        import src.main as main
        import src.api.routes.events as events_route

        self._install(monkeypatch, [
            {"id": "e1", "name": "Dog walk", "source": "habit",
             "source_ids": {"habit_slug": "dog-walk"}, "completed": False,
             "habit": {"name": "Dog walk"},
             "start_time": "2026-09-07T19:00", "end_time": "2026-09-07T20:00"},
        ])

        class FakeVault:
            def list_active_habits(self):
                return [{"metadata": {"name": "Dog walk"},
                         "path": "20-habits/dog-walk.md"}]

        monkeypatch.setattr(main, "get_vault", lambda: FakeVault())

        seen = {}

        def fake_complete(vault, path, now=None):
            seen["now"] = now
            return {"already_completed": False, "name": "Dog walk",
                    "tokens_earned": 5, "new_streak": 2,
                    "date": now.date().isoformat()}

        monkeypatch.setattr(events_route, "complete_habit", fake_complete)

        self._client().post("/events/2026-09-07/e1/state",
                            json={"state": "approved"})

        assert seen["now"].date().isoformat() == "2026-09-07"

    def test_dismissing_a_ticked_habit_is_refused(self, monkeypatch):
        """§2.4: nothing in this ship unticks a habit. Unreachable from /day,
        so refuse rather than invent a reverse path."""
        fake = self._install(monkeypatch, [
            {"id": "e1", "name": "Dog walk", "source": "habit",
             "source_ids": {"habit_slug": "dog-walk"}, "completed": True,
             "habit": {"name": "Dog walk"}},
        ])

        r = self._client().post("/events/2026-09-10/e1/state",
                                json={"state": "dismissed"})

        assert r.status_code == 409
        assert "untick" in r.json()["detail"].lower()
        assert fake.saved == {}

    def test_approving_an_already_approved_block_is_a_no_op(self, monkeypatch):
        fake = self._install(monkeypatch, [
            {"id": "e1", "name": "Dog walk", "source": "manual", "source_ids": {}},
        ])

        r = self._client().post("/events/2026-09-10/e1/state",
                                json={"state": "approved"})

        assert r.status_code == 200
        assert r.json()["state"] == "approved"
        assert fake.saved == {}

    def test_unknown_event_is_404(self, monkeypatch):
        self._install(monkeypatch, [])

        r = self._client().post("/events/2026-09-10/nope/state",
                                json={"state": "approved"})

        assert r.status_code == 404

    def test_an_invalid_state_is_rejected(self, monkeypatch):
        self._install(monkeypatch, [
            {"id": "e1", "source": "calendar", "source_ids": {"calendar_id": "g1"}},
        ])

        r = self._client().post("/events/2026-09-10/e1/state",
                                json={"state": "suggested"})

        assert r.status_code == 422
```

- [ ] **Step 2: Run to verify they fail**

```bash
./venv/bin/python -m pytest tests/test_events_route.py -q -k SetState
```
Expected: 404s — the route does not exist.

- [ ] **Step 3: Write the route**

Add to `apps/vault-server/src/api/routes/events.py`:

```python
class SetStateBody(BaseModel):
    # `Literal`, so "suggested" is a 422 at the boundary rather than a stored
    # value nothing would ever read (spec §2.2).
    state: Literal["approved", "dismissed"]


def _source_systems(event: dict) -> set[str]:
    return {
        _SOURCE_SYSTEM_BY_ID_KEY.get(key)
        for key in (event.get("source_ids") or {})
    }


def _habit_path(vault, name: str) -> str | None:
    """The vault path of the active habit called `name`, case-insensitively."""
    wanted = name.strip().casefold()
    for habit in vault.list_active_habits():
        if (habit.get("metadata", {}).get("name") or "").strip().casefold() == wanted:
            return habit.get("path")
    return None


@router.post("/{date}/{event_id}/state")
async def set_event_state(date: str, event_id: str, body: SetStateBody):
    """Approve or dismiss one block (spec §2.3).

    Dispatches on the block's source system. Two branches write no `state` at
    all: ticking a habit or checking a checkbox makes `completed` true, and
    `resolve_state` then derives "approved" from the source on every later
    merge. Storing a state row as well would key an approval to an unstable
    `habit_slug`/`note_line` id — the stale-row trap §2.1 exists to avoid.
    """
    from src.main import get_events as get_events_svc, get_vault
    events_svc = get_events_svc()
    if not events_svc:
        raise HTTPException(503, "Events service not initialized")

    # The reconciled view, not the raw file: a habit- or note-derived block
    # often has no persisted row at all, because /daily reconciles without
    # saving. Resolving from the raw store would 404 on exactly the blocks
    # this route most needs to act on.
    fresh, available = await _merge_from_sources(date_type.fromisoformat(date))
    merged = events_svc.reconcile(date, fresh, available)

    event = next((e for e in merged if e.get("id") == event_id), None)
    if event is None:
        raise HTTPException(404, f"No event {event_id} on {date}")

    systems = _source_systems(event)
    current = resolve_state(event)

    # --- nothing in this ship reverses a human action --------------------
    if body.state == "dismissed" and current == "approved" and (
        systems & {"habit", "daily-note"}
    ):
        raise HTTPException(
            409,
            "This block is approved because you ticked it. Nothing in Mazkir "
            "unticks a habit or unchecks a checkbox yet — untick it in "
            "/habits or in the note.",
        )

    # --- approve a habit block by ticking the habit ----------------------
    if body.state == "approved" and "habit" in systems and not event.get("completed"):
        habit_name = (event.get("habit") or {}).get("name") or event.get("name") or ""
        vault = get_vault()
        path = _habit_path(vault, habit_name)
        if path is None:
            raise HTTPException(404, f"No active habit named {habit_name!r}")
        # The block's date, not today. Midday so a timezone conversion can
        # never roll it into a neighbouring day; complete_habit only reads
        # `.date()` off it.
        stamp = datetime.combine(
            date_type.fromisoformat(date), time(12, 0),
            tzinfo=pytz.timezone(settings.vault_timezone),
        )
        outcome = complete_habit(vault, path, now=stamp)
        return {
            "ok": True, "state": "approved", "event_id": event_id,
            "habit": {
                "name": outcome.get("name", habit_name),
                "tokens_earned": outcome.get("tokens_earned", 0),
                "new_streak": outcome.get("new_streak", 0),
            },
            "checkbox": None,
        }

    # --- approve a checkbox block by checking it -------------------------
    if body.state == "approved" and "daily-note" in systems and not event.get("completed"):
        from src.services.tool_handlers.daily import daily_set_task_state
        text = event.get("name") or ""
        daily_set_task_state(
            get_vault(), {"task": text, "state": "checked", "date": date}
        )
        return {
            "ok": True, "state": "approved", "event_id": event_id,
            "habit": None, "checkbox": {"text": text},
        }

    # --- already approved, nothing to write ------------------------------
    if body.state == "approved" and current == "approved":
        return {"ok": True, "state": "approved", "event_id": event_id,
                "habit": None, "checkbox": None}

    # --- store the state -------------------------------------------------
    # Persist the reconciled day so the row exists to carry the state. This
    # is the deliberate exception to "reads never persist": an explicit user
    # action may write, and Ship 4 drew the same line for _resolve_reference.
    for candidate in merged:
        if candidate.get("id") == event_id:
            candidate["state"] = body.state
    events_svc.save_events(date, merged)

    return {"ok": True, "state": body.state, "event_id": event_id,
            "habit": None, "checkbox": None}
```

Add to the imports at the top of `events.py`:

```python
from datetime import date as date_type, datetime, time
from typing import Literal

import pytz

from src.config import settings
from src.services.approval import resolve_state
from src.services.events_service import _SOURCE_SYSTEM_BY_ID_KEY
from src.services.habit_completion import complete_habit
```

(the existing `from datetime import date as date_type` line becomes the one above.)

- [ ] **Step 4: Run the tests**

```bash
./venv/bin/python -m pytest tests/test_events_route.py -q
./venv/bin/python -m pytest tests/ -q
```
Expected: green.

**If `daily_set_task_state`'s signature differs from the call above, read `apps/vault-server/src/services/tool_handlers/daily.py` and match the real one.** The behaviour required is: check the box whose text is `text`, in the daily note for `date`. Do not change the handler to fit the call.

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/api/routes/events.py apps/vault-server/tests/test_events_route.py
git commit -m "feat(events): approve or dismiss one block"
```

---

## Task 8: `approve-all` and `gaps/fill`

**Files:**
- Modify: `apps/vault-server/src/api/routes/daily.py`
- Test: `apps/vault-server/tests/test_daily_route.py`

**Interfaces:**
- Consumes: `set_event_state` and `SetStateBody` (Task 7), `propose_for_gap` and `_load_history` (Tasks 4–5).
- Produces:
  - `FillGapBody` with `start: str`, `end: str`, `name: str | None`
  - `POST /daily/{date}/gaps/fill` → `{"ok": True, "event_id": str, "name": str, "was_guess": bool}`
  - `POST /daily/{date}/approve-all` → `{"ok": True, "approved": [{"event_id", "name", "was_guess"}], "failed": [{"event_id", "reason"}]}`
  - Seams `_set_state_for_approve_all(date, event_id, body)` and `_fill_gap_for_approve_all(date, body)`, so approve-all can be tested without a live events service.

Spec §5.6 and §4.4. `approve-all` **includes proposals** — decided 2026-09-10 against the recommendation; the decision stands. Two mitigations, neither weakening it: the response enumerates what was banked with `was_guess` set so the bot can say *"Approved 3, including Sleep 00:20–06:40 (a guess)"*, and the button's label carries the count.

`gaps/fill` without a `name` **recomputes the proposal server-side** rather than trusting a client-sent one (§4.2) — safe because `propose_for_gap` breaks ties on the name and is therefore deterministic.

One failure must never abort the rest: a 409 on a ticked habit cannot strand the approvals after it.

- [ ] **Step 1: Write the failing tests**

Add to `apps/vault-server/tests/test_daily_route.py`:

```python
def _fake_day(blocks, gaps):
    """A DailyResponse with just the fields approve-all reads."""
    from src.api.routes.daily import DailyResponse, DayCoverage

    return DailyResponse(
        date="2026-09-10", tokens_today=0, tokens_total=0,
        blocks=blocks, gaps=gaps,
        coverage=DayCoverage(
            covered_minutes=0, unaccounted_minutes=0, elapsed_minutes=720,
            confirmed_minutes=0, pending_minutes=0,
        ),
        todos=[], notes=[],
    )


class TestApproveAll:
    def test_approves_pending_blocks_and_banks_guesses(self, monkeypatch):
        """§5.6: approve-all includes proposals, and says which were guesses."""
        from fastapi.testclient import TestClient
        from src.main import app
        from src.api.routes.daily import DailyBlock, DailyGap, GapProposal
        import src.api.routes.daily as daily_route

        blocks = [
            DailyBlock(id="e1", start="09:00", end="10:00", title="Standup",
                       source="calendar", type="event", state="pending"),
            DailyBlock(id="e2", start="07:00", end="08:00", title="Dog walk",
                       source="manual", type="event", state="approved"),
        ]
        gaps = [DailyGap(start="00:20", end="06:40", minutes=380,
                         proposal=GapProposal(name="Sleep", days_seen=11))]

        async def fake_get_daily(date=None):
            return _fake_day(blocks, gaps)

        approvals, fills = [], []

        async def fake_set_state(date, event_id, body):
            approvals.append(event_id)
            return {"ok": True, "state": "approved", "event_id": event_id,
                    "habit": None, "checkbox": None}

        async def fake_fill(date, body):
            fills.append((body.start, body.end, body.name))
            return {"ok": True, "event_id": "n1", "name": "Sleep", "was_guess": True}

        monkeypatch.setattr(daily_route, "get_daily", fake_get_daily)
        monkeypatch.setattr(daily_route, "_set_state_for_approve_all", fake_set_state)
        monkeypatch.setattr(daily_route, "_fill_gap_for_approve_all", fake_fill)

        body = TestClient(app).post("/daily/2026-09-10/approve-all").json()

        assert approvals == ["e1"]                    # not the approved e2
        assert fills == [("00:20", "06:40", None)]    # name recomputed server-side
        assert [a["was_guess"] for a in body["approved"]] == [False, True]
        assert body["failed"] == []

    def test_a_failure_does_not_strand_the_rest(self, monkeypatch):
        """A 409 on a ticked habit must not abort the approvals after it."""
        from fastapi.testclient import TestClient
        from fastapi import HTTPException
        from src.main import app
        from src.api.routes.daily import DailyBlock
        import src.api.routes.daily as daily_route

        blocks = [
            DailyBlock(id="bad", start="09:00", end="10:00", title="Dog walk",
                       source="habit", type="habit", state="pending"),
            DailyBlock(id="good", start="10:00", end="11:00", title="Standup",
                       source="calendar", type="event", state="pending"),
        ]

        async def fake_get_daily(date=None):
            return _fake_day(blocks, [])

        async def fake_set_state(date, event_id, body):
            if event_id == "bad":
                raise HTTPException(409, "untick it in /habits")
            return {"ok": True, "state": "approved", "event_id": event_id,
                    "habit": None, "checkbox": None}

        monkeypatch.setattr(daily_route, "get_daily", fake_get_daily)
        monkeypatch.setattr(daily_route, "_set_state_for_approve_all", fake_set_state)

        body = TestClient(app).post("/daily/2026-09-10/approve-all").json()

        assert [a["event_id"] for a in body["approved"]] == ["good"]
        assert [f["event_id"] for f in body["failed"]] == ["bad"]
        assert "untick" in body["failed"][0]["reason"]

    def test_still_ahead_blocks_are_not_approved(self, monkeypatch):
        """A block that has not happened cannot be confirmed — the /day view
        gives it no buttons, and approve-all must agree."""
        from fastapi.testclient import TestClient
        from src.main import app
        from src.api.routes.daily import DailyBlock
        import src.api.routes.daily as daily_route

        blocks = [DailyBlock(id="later", start="21:00", end="22:00", title="Guitar",
                             source="manual", type="event", state="pending")]

        async def fake_get_daily(date=None):
            return _fake_day(blocks, [])

        called = []

        async def fake_set_state(date, event_id, body):
            called.append(event_id)
            return {"ok": True, "state": "approved", "event_id": event_id,
                    "habit": None, "checkbox": None}

        monkeypatch.setattr(daily_route, "get_daily", fake_get_daily)
        monkeypatch.setattr(daily_route, "_set_state_for_approve_all", fake_set_state)

        TestClient(app).post("/daily/2026-09-10/approve-all")

        assert called == []


class TestGapFill:
    def _install(self, monkeypatch, history=None):
        import src.main as main

        class FakeEvents:
            def __init__(self):
                self.created = []

            def get_events(self, date):
                return (history or {}).get(date, [])

            def create_event(self, **kwargs):
                self.created.append(kwargs)
                return {"id": "n1", **kwargs}

        fake = FakeEvents()
        monkeypatch.setattr(main, "get_events", lambda: fake)
        return fake

    def test_a_named_fill_creates_that_block(self, monkeypatch):
        from fastapi.testclient import TestClient
        from src.main import app

        fake = self._install(monkeypatch)

        body = TestClient(app).post(
            "/daily/2026-09-10/gaps/fill",
            json={"start": "16:00", "end": "17:30", "name": "Reading"},
        ).json()

        assert body["name"] == "Reading"
        assert body["was_guess"] is False
        assert fake.created[0]["name"] == "Reading"

    def test_an_unnamed_fill_recomputes_the_proposal(self, monkeypatch):
        """§4.2: the client sends only the interval. A client-supplied name is
        a client-supplied write, and a long one would not fit in 64 bytes."""
        from fastapi.testclient import TestClient
        from src.main import app

        fake = self._install(monkeypatch)

        body = TestClient(app).post(
            "/daily/2026-09-10/gaps/fill",
            json={"start": "00:20", "end": "06:40"},
        ).json()

        # Empty history, overnight gap -> the cold-start Sleep seed.
        assert body["name"] == "Sleep"
        assert body["was_guess"] is True
        assert fake.created[0]["name"] == "Sleep"

    def test_an_unnamed_fill_with_no_proposal_is_422(self, monkeypatch):
        """Nothing to guess and nothing supplied — the bot should have asked."""
        from fastapi.testclient import TestClient
        from src.main import app

        self._install(monkeypatch)

        r = TestClient(app).post(
            "/daily/2026-09-10/gaps/fill",
            json={"start": "16:00", "end": "17:30"},
        )

        assert r.status_code == 422
```

- [ ] **Step 2: Run to verify they fail**

```bash
./venv/bin/python -m pytest tests/test_daily_route.py -q -k "ApproveAll or GapFill"
```
Expected: 404s — neither route exists.

- [ ] **Step 3: Write `gaps/fill`**

Add to `apps/vault-server/src/api/routes/daily.py`:

```python
class FillGapBody(BaseModel):
    start: str                      # "HH:MM"
    end: str                        # "HH:MM"
    # Absent means "use whatever you proposed for this interval". The client
    # never sends the proposed name: a name can exceed the 64-byte callback
    # budget, and a client-supplied name is a client-supplied write (§4.2).
    name: str | None = None


@router.post("/{date}/gaps/fill")
async def fill_gap(date: str, body: FillGapBody):
    """Turn a gap into a block (spec §4.4).

    A gap has no id — it is derived — so this keys on the interval. Without a
    `name`, the proposal for that interval is recomputed here rather than
    taken from the client.
    """
    from src.main import get_events as get_events_svc
    events_svc = get_events_svc()
    if not events_svc:
        raise HTTPException(503, "Events service not initialized")

    target_date = dt_date.fromisoformat(date)
    name = body.name
    was_guess = False

    if not name:
        start = minutes_into_day(body.start, "")
        end = minutes_into_day(body.end, "")
        if start is None or end is None:
            raise HTTPException(422, f"Unusable interval {body.start}-{body.end}")
        proposal = propose_for_gap(start, end, _load_history(events_svc, target_date))
        if not proposal:
            raise HTTPException(
                422, f"Nothing to propose for {body.start}-{body.end} — send a name.",
            )
        name = proposal["name"]
        was_guess = True

    created = events_svc.create_event(
        date=date, name=name,
        start_time=f"{date}T{body.start}", end_time=f"{date}T{body.end}",
    )
    return {"ok": True, "event_id": created.get("id", ""), "name": name,
            "was_guess": was_guess}
```

**If `EventsService.create_event`'s signature differs, read it and adapt.** The behaviour required is one manual event on `date` spanning the interval.

- [ ] **Step 4: Write `approve-all`**

Add below `fill_gap`:

```python
# Thin seams so approve-all is testable without a live events service, and so
# both routes share one implementation of each action.
async def _set_state_for_approve_all(date: str, event_id: str, body):
    from src.api.routes.events import set_event_state
    return await set_event_state(date, event_id, body)


async def _fill_gap_for_approve_all(date: str, body: FillGapBody):
    return await fill_gap(date, body)


@router.post("/{date}/approve-all")
async def approve_all(date: str):
    """Approve every elapsed pending block on `date`, and bank every proposal.

    Proposals are included deliberately (spec §5.6) — decided 2026-09-10
    against the recommendation. The mitigation is that the response names what
    it banked and flags guesses, so the bot can say "Approved 3, including
    Sleep 00:20-06:40 (a guess)" and a wrong one is correctable in the same
    breath rather than discovered weeks later in the readout.

    One failure never aborts the rest: a 409 on a ticked habit must not strand
    the approvals after it.
    """
    from src.api.routes.events import SetStateBody

    day = await get_daily(dt_date.fromisoformat(date))
    elapsed = day.coverage.elapsed_minutes
    approved: list[dict] = []
    failed: list[dict] = []

    for block in day.blocks:
        if block.state != "pending":
            continue
        # A block that has not happened cannot be confirmed. The /day view
        # gives it no buttons for the same reason (spec §5.1's `◌`), so
        # sweeping it here would confirm something the surface says you can't.
        start = minutes_into_day(block.start, "")
        if start is None or start >= elapsed:
            continue
        try:
            await _set_state_for_approve_all(
                date, block.id, SetStateBody(state="approved")
            )
            approved.append({"event_id": block.id, "name": block.title,
                             "was_guess": False})
        except HTTPException as exc:
            failed.append({"event_id": block.id, "reason": str(exc.detail)})

    for gap in day.gaps:
        if gap.proposal is None:
            continue
        try:
            result = await _fill_gap_for_approve_all(
                date, FillGapBody(start=gap.start, end=gap.end)
            )
            approved.append({"event_id": result["event_id"],
                             "name": result["name"], "was_guess": True})
        except HTTPException as exc:
            failed.append({"event_id": f"gap:{gap.start}-{gap.end}",
                           "reason": str(exc.detail)})

    return {"ok": True, "approved": approved, "failed": failed}
```

Add `HTTPException` to the FastAPI import at the top of `daily.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
```

- [ ] **Step 5: Run the tests**

```bash
./venv/bin/python -m pytest tests/test_daily_route.py -q
./venv/bin/python -m pytest tests/ -q
```
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add apps/vault-server/src/api/routes/daily.py apps/vault-server/tests/test_daily_route.py
git commit -m "feat(daily): approve-all and gap fill"
```

---

## Task 9: `PATCH /events/{date}/{event_id}` pins what it changes

**Files:**
- Modify: `apps/vault-server/src/api/routes/events.py:88-104`
- Test: `apps/vault-server/tests/test_events_route.py`

**Interfaces:**
- Consumes: `USER_SETTABLE_FIELDS`, `apply_user_set` from `src.services.events_service`.
- Produces: `PATCH` writes into `user_set` for any user-settable field it changes.

A recorded Ship 4 follow-up, listed in spec §7: *"`PATCH /events/{date}/{event_id}` doesn't pin, so edits through it still revert."* The route sets fields directly, so the next `reconcile` overwrites them from the source. Ship 4 built `user_set` for exactly this and wired it only into the agent's `update_event`.

`USER_SETTABLE_FIELDS` is exactly `{"name", "start_time", "end_time", "location", "activity"}`. `photos` and `assets` are not in it and must not be pinned — they are preserved by other means, and letting a stray key into `user_set` would turn it into a way to rewrite reconciliation's own bookkeeping.

- [ ] **Step 1: Write the failing tests**

Add to `apps/vault-server/tests/test_events_route.py`:

```python
def test_patch_pins_the_fields_it_changes(monkeypatch, tmp_path):
    """A rename through PATCH must survive the next merge. Ship 4 built
    user_set for this and wired it only into the agent's update_event."""
    from fastapi.testclient import TestClient
    from src.main import app
    from src.services.events_service import EventsService
    import src.main as main

    svc = EventsService(tmp_path / "events")
    svc.save_events("2026-09-10", [{
        "id": "e1", "name": "Standup", "source": "calendar",
        "source_ids": {"calendar_id": "g1"},
        "start_time": "2026-09-10T09:00", "end_time": "2026-09-10T10:00",
    }])
    monkeypatch.setattr(main, "get_events", lambda: svc)

    r = TestClient(app).patch("/events/2026-09-10/e1",
                              json={"name": "Sprint planning"})

    assert r.status_code == 200
    stored = svc.get_events("2026-09-10")[0]
    assert stored["name"] == "Sprint planning"
    assert stored["user_set"]["name"] == "Sprint planning"

    # And it survives a merge that says otherwise — which is the whole point.
    fresh = [{
        "id": "whatever", "name": "Standup", "source": "calendar",
        "source_ids": {"calendar_id": "g1"},
        "start_time": "2026-09-10T09:00", "end_time": "2026-09-10T10:00",
    }]
    reconciled = svc.reconcile("2026-09-10", fresh, {"calendar"})
    assert reconciled[0]["name"] == "Sprint planning"


def test_patch_does_not_pin_photos(monkeypatch, tmp_path):
    """Only the five USER_SETTABLE_FIELDS are pinnable. photos and assets are
    preserved by other means, and a stray key in user_set would become a way
    to rewrite reconciliation's own bookkeeping."""
    from fastapi.testclient import TestClient
    from src.main import app
    from src.services.events_service import EventsService
    import src.main as main

    svc = EventsService(tmp_path / "events")
    svc.save_events("2026-09-10", [{
        "id": "e1", "name": "Standup", "source": "calendar",
        "source_ids": {"calendar_id": "g1"},
    }])
    monkeypatch.setattr(main, "get_events", lambda: svc)

    TestClient(app).patch("/events/2026-09-10/e1",
                          json={"photos": [{"path": "a.jpg"}]})

    stored = svc.get_events("2026-09-10")[0]
    assert stored["photos"] == [{"path": "a.jpg"}]
    assert "photos" not in stored.get("user_set", {})
```

- [ ] **Step 2: Run to verify they fail**

```bash
./venv/bin/python -m pytest tests/test_events_route.py -q -k pins
```
Expected: FAIL — `user_set` is absent or has no `name`.

- [ ] **Step 3: Pin in the route**

In `apps/vault-server/src/api/routes/events.py`, in `patch_event`, replace:

```python
            updates = body.model_dump(exclude_none=True)
            event.update(updates)
```

with:

```python
            updates = body.model_dump(exclude_none=True)
            event.update(updates)
            # Pin whatever the user just set, or the next reconcile overwrites
            # it from the source and the edit silently reverts. Ship 4 built
            # user_set for exactly this and wired it only into the agent's
            # update_event; this route was the recorded gap.
            #
            # Only the five USER_SETTABLE_FIELDS are pinnable: `photos` and
            # `assets` are preserved by other means, and letting a stray key
            # into user_set would turn it into a way to rewrite
            # reconciliation's own bookkeeping.
            pinned = event.setdefault("user_set", {})
            for field, value in updates.items():
                if field in USER_SETTABLE_FIELDS:
                    pinned[field] = value
            apply_user_set(event)
```

Add `USER_SETTABLE_FIELDS` and `apply_user_set` to the `events_service` import added in Task 7:

```python
from src.services.events_service import (
    USER_SETTABLE_FIELDS, _SOURCE_SYSTEM_BY_ID_KEY, apply_user_set,
)
```

- [ ] **Step 4: Run the tests**

```bash
./venv/bin/python -m pytest tests/test_events_route.py -q
./venv/bin/python -m pytest tests/ -q
```
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/api/routes/events.py apps/vault-server/tests/test_events_route.py
git commit -m "fix(events): PATCH pins the fields it sets"
```

---

## Task 10: Shared types

**Files:**
- Modify: `packages/shared-types/src/daily.ts`, `packages/shared-types/src/index.ts`

**Interfaces:**
- Produces: `DailyBlock.state: "approved" | "pending" | "dismissed"`; `DayCoverage.confirmed_minutes`, `.pending_minutes`; `DailyGap.proposal: GapProposal | null`; `GapProposal { name: string; days_seen: number }`.

`DailyBlock.state` is currently typed `"suggested" | "approved"`. `"suggested"` is gone from the server (Task 2) and `"pending"`/`"dismissed"` are new. `"dismissed"` never reaches the bot — the server omits those blocks — but the type mirrors the server's vocabulary rather than inventing a narrower one that would drift.

- [ ] **Step 1: Update the types**

In `packages/shared-types/src/daily.ts`, replace `DailyBlock`, `DailyGap` and `DayCoverage`, and add `GapProposal`:

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
  /** Resolved server-side (spec §2.1): derived from the source for anything
   *  a human action created, stored only for calendar and timeline blocks the
   *  user has tapped. `"dismissed"` never arrives here — the server omits
   *  those blocks — but the vocabulary mirrors the server's rather than
   *  inventing a narrower one that would drift from it. */
  state: "approved" | "pending" | "dismissed";
  habit_progress: string | null;  // "1/2" when a daily_target is set
}

/** What probably filled a gap. A question, not an assertion: the row renders
 *  it with a ✕ beside it, and `days_seen` is shown so the guess can be judged
 *  rather than trusted. */
export interface GapProposal {
  name: string;
  days_seen: number;
}

export interface DailyGap {
  start: string;
  end: string;
  minutes: number;
  /** null means Mazkir had no basis to guess, so the gap asks instead. */
  proposal: GapProposal | null;
}

export interface DayCoverage {
  /** Union over every drawable block — what gaps are computed from, so a `░`
   *  row always means nothing is there at all. Meaning unchanged from Ship 2,
   *  so existing consumers are unaffected. */
  covered_minutes: number;
  unaccounted_minutes: number;
  /** Minutes since local midnight for today, 1440 for a past day, 0 for a
   * future day. Carries the "is it today" signal for free: the bot needs no
   * timezone comparison at all — the divider between elapsed and
   * still-to-come rows shows exactly when `0 < elapsed_minutes < 1440`. */
  elapsed_minutes: number;
  /** Approved blocks only. The one number the weekly readout may read. */
  confirmed_minutes: number;
  /** Pending time not already confirmed, so two overlapping blocks of
   *  different states never add up to more than the wall clock. */
  pending_minutes: number;
}
```

Export `GapProposal` from `packages/shared-types/src/index.ts` beside the other daily types.

- [ ] **Step 2: Typecheck both consumers**

```bash
cd apps/telegram-bot && npx tsc -b
cd ../telegram-web-app && npx tsc -b
```

Expected: the **bot** reports errors where `day-rich.ts` reads the old shape — Task 11 fixes those. The **webapp** must be clean; the added coverage fields are additive, so nothing should break. **Fix any webapp error in this task**, not later.

- [ ] **Step 3: Commit**

```bash
git add packages/shared-types/src/daily.ts packages/shared-types/src/index.ts
git commit -m "feat(types): approval state, gap proposals, split coverage"
```

---

## Task 11: The `/day` view

**Files:**
- Modify: `apps/telegram-bot/src/formatters/day-rich.ts`
- Test: `apps/telegram-bot/tests/formatters/day-rich.test.ts`

**Interfaces:**
- Consumes: the Task 10 types.
- Produces: `buildDayRich(data: DailyResponse)` — signature unchanged. New exports for tests to assert against: `GLYPH_CONFIRMED`, `GLYPH_PENDING`, `GLYPH_GAP`, `GLYPH_AHEAD`, `NOW_DIVIDER`.

Spec §5. Every value here was chosen from on-device renders and is not adjustable without re-prototyping.

**Glyphs** (§5.1) — exactly `✓` U+2713, `●` U+25CF, `░` U+2591, `◌` U+25CC. `✅`, `⚠` and `⟳` are all removed. Completion folds into `✓`.

**Controls in the row** (§5.2) — a `<tg-button-row>` inside the third `<td>`. Pending elapsed rows get `[✓][✕][✎]`; approved rows get their facet label (usually empty until Ship 6); still-ahead rows get nothing, because a 19:00 block cannot be confirmed at 14:00. Gap rows get `[+ 1.2h]`, or the proposal's name with the full control set when one exists.

**Summary row** (§5.3) — `<h2>` header stays; below it a one-row table with the coverage words in `<sub>` on the left and `⟲` right-aligned via `<td align="right">`.

**Now divider** (§5.4) — exactly twelve U+00B7 middle dots, `" now "`, twelve more, inside a centred cell wrapped in `<sub>`.

**Tail** (§5.5) — `<p>&nbsp;</p><hr>`, week bar, `<p>&nbsp;</p>`, nav. One rule, not two.

- [ ] **Step 1: Write the failing tests**

Add to `apps/telegram-bot/tests/formatters/day-rich.test.ts`:

```typescript
import type { DailyResponse, DailyBlock, DailyGap } from "@mazkir/shared-types";

function s5block(over: Partial<DailyBlock> = {}): DailyBlock {
  return {
    id: "e1", start: "09:00", end: "10:00", title: "Standup",
    source: "calendar", type: "event", completed: false,
    activity: null, category: null, state: "pending", habit_progress: null,
    ...over,
  };
}

function s5gap(over: Partial<DailyGap> = {}): DailyGap {
  return { start: "13:00", end: "14:15", minutes: 75, proposal: null, ...over };
}

function s5day(over: Partial<DailyResponse> = {}): DailyResponse {
  return {
    date: "2026-09-10", tokens_today: 0, tokens_total: 0,
    blocks: [], gaps: [], incomplete: [], todos: [], notes: [],
    coverage: {
      covered_minutes: 120, unaccounted_minutes: 60, elapsed_minutes: 720,
      confirmed_minutes: 60, pending_minutes: 60,
    },
    ...over,
  } as DailyResponse;
}

describe("Ship 5 glyphs", () => {
  it("marks a confirmed block with ✓ and gives it no buttons", () => {
    const html = buildDayRich(s5day({ blocks: [s5block({ state: "approved" })] })).html!;
    expect(html).toContain("✓ 09:00–10:00");
    expect(html).not.toMatch(/data="block:/);
  });

  it("marks a pending elapsed block with ● and three buttons", () => {
    const html = buildDayRich(s5day({ blocks: [s5block()] })).html!;
    expect(html).toContain("● 09:00–10:00");
    expect(html).toMatch(/data="block:approve:2026-09-10:e1"/);
    expect(html).toMatch(/data="block:dismiss:2026-09-10:e1"/);
    expect(html).toMatch(/data="block:edit:2026-09-10:e1"/);
  });

  it("marks a still-ahead block with ◌ and gives it no buttons", () => {
    const html = buildDayRich(s5day({
      blocks: [s5block({ id: "e9", start: "19:00", end: "20:00" })],
    })).html!;
    expect(html).toContain("◌ 19:00–20:00");
    expect(html).not.toMatch(/data="block:approve:2026-09-10:e9"/);
  });

  it("marks a gap with ░", () => {
    const html = buildDayRich(s5day({ gaps: [s5gap()] })).html!;
    expect(html).toContain("░ 13:00–14:15");
  });

  it("never renders ✅, ⚠ or ⟳ anywhere", () => {
    const html = buildDayRich(s5day({
      blocks: [
        s5block({ state: "approved", completed: true }),
        s5block({ id: "e2", start: "21:00", end: "22:00" }),
      ],
      gaps: [s5gap()],
    })).html!;
    for (const glyph of ["✅", "⚠", "⟳"]) expect(html).not.toContain(glyph);
  });

  it("folds completion into ✓ rather than adding a second marker", () => {
    const html = buildDayRich(s5day({
      blocks: [s5block({ state: "approved", completed: true })],
    })).html!;
    expect(html).toContain("✓ 09:00–10:00");
  });
});

describe("buttons live inside table cells", () => {
  it("wraps every block button row in a <td>", () => {
    // A top-level row stretches full width and an <li> hoists it out; only a
    // cell gives compact pills. Assert the containment, not just presence.
    const html = buildDayRich(s5day({ blocks: [s5block()] })).html!;
    expect(html).toMatch(/<td><tg-button-row>[\s\S]*?<\/tg-button-row><\/td>/);
  });
});

describe("gap proposals", () => {
  it("renders a proposal as a named row with the full control set", () => {
    const html = buildDayRich(s5day({
      gaps: [s5gap({
        start: "00:20", end: "06:40", minutes: 380,
        proposal: { name: "Sleep", days_seen: 11 },
      })],
    })).html!;
    expect(html).toContain("Sleep");
    expect(html).toContain("11/14");
    expect(html).toMatch(/data="prop:approve:2026-09-10:20:400"/);
    expect(html).toMatch(/data="prop:dismiss:2026-09-10:20:400"/);
  });

  it("renders an unproposed gap with a fill button carrying the duration", () => {
    const html = buildDayRich(s5day({ gaps: [s5gap()] })).html!;
    expect(html).toContain("+ 1.2h");
    expect(html).toMatch(/data="gap:fill:2026-09-10:780:855"/);
  });
});

describe("summary row and refresh", () => {
  it("keeps the h2 and puts coverage in a sub beside a right-aligned refresh", () => {
    const html = buildDayRich(s5day()).html!;
    expect(html).toContain("<h2>");
    expect(html).toMatch(/<sub>[^<]*1\.0h confirmed[^<]*<\/sub>/);
    expect(html).toMatch(
      /<td align="right"><tg-button-row><tg-button[^>]*data="day:refresh:2026-09-10"/,
    );
  });
});

describe("the now divider", () => {
  it("is a centred subscript run of twelve middle dots either side", () => {
    const html = buildDayRich(s5day({
      blocks: [
        s5block({ id: "past", state: "approved" }),
        s5block({ id: "future", start: "19:00", end: "20:00" }),
      ],
    })).html!;
    expect(html).toContain(
      '<table><tr><td align="center"><sub>' +
      "·".repeat(12) + " now " + "·".repeat(12) +
      "</sub></td></tr></table>",
    );
  });

  it("is suppressed when one side is empty", () => {
    const html = buildDayRich(s5day({
      blocks: [s5block({ state: "approved" })],
    })).html!;
    expect(html).not.toContain(" now ");
  });
});

describe("approve all", () => {
  it("carries the count of what it will act on", () => {
    const html = buildDayRich(s5day({
      blocks: [s5block(), s5block({ id: "e2", start: "10:00", end: "11:00" })],
      gaps: [s5gap({ proposal: { name: "Sleep", days_seen: 11 } })],
    })).html!;
    // Two pending elapsed blocks plus one proposal. The number is in the
    // label deliberately: approve-all banks guesses, so it must not hide how
    // many things it touches behind the word "all".
    expect(html).toContain("approve all 3");
    expect(html).toMatch(/data="day:approveall:2026-09-10"/);
  });

  it("is absent when there is nothing to approve", () => {
    const html = buildDayRich(s5day({
      blocks: [s5block({ state: "approved" })],
    })).html!;
    expect(html).not.toContain("approve all");
  });
});

describe("the tail", () => {
  it("has one rule, before the week bar, and none between bar and nav", () => {
    const html = buildDayRich(s5day()).html!;
    expect((html.match(/<hr>/g) ?? []).length).toBe(1);
    const rule = html.lastIndexOf("<hr>");
    expect(html.indexOf('data="day:2026-09-06"')).toBeGreaterThan(rule);
    expect(html.indexOf('data="day:today"')).toBeGreaterThan(rule);
  });
});
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd apps/telegram-bot
TELEGRAM_BOT_TOKEN=x AUTHORIZED_USER_ID=1 npx vitest run tests/formatters/day-rich.test.ts
```
Expected: FAIL on the new tests.

- [ ] **Step 3: Replace the glyph constants, divider and row builders**

In `apps/telegram-bot/src/formatters/day-rich.ts`, delete the old `NOW_DIVIDER` constant and replace `blockRow` and `gapRow`:

```typescript
// The four states a row can be in, as exactly the characters chosen from
// on-device renders (spec §5.1). Not emoji-presentation variants: `⚠` used to
// render at a size that dominated the row, which is why it is gone.
//
// `✓` folds in what used to be `✅` (completed). The two occupied the same
// slot with nearly the same meaning, and where they diverged — a Google entry
// Google marks green, which is `completed` yet machine-inferred — the honest
// answer is `●`, because "the source says it was done" is one input to
// approval, not approval itself.
export const GLYPH_CONFIRMED = "✓";   // U+2713 — settled, counts
export const GLYPH_PENDING = "●";     // U+25CF — happened, waiting on you
export const GLYPH_GAP = "░";         // U+2591 — unaccounted
export const GLYPH_AHEAD = "◌";       // U+25CC — still ahead, no buttons

// A centred table cell is the only centring the rich grammar offers: `<p>` has
// no alignment at all, which is why the old `─`-run divider only looked
// centred when the dash count happened to match the message width, and drifted
// whenever it did not. `<sub>` shrinks it; middle dots thin it.
export const NOW_DIVIDER =
  '<table><tr><td align="center"><sub>' +
  "·".repeat(12) + " now " + "·".repeat(12) +
  "</sub></td></tr></table>";

function button(label: string, data: string, style?: string): string {
  const s = style ? ` style="${style}"` : "";
  return `<tg-button type="callback_data" data="${data}"${s}>${label}</tg-button>`;
}

/** A `<tg-button-row>` wrapped in the `<td>` it must live in. Buttons only
 *  render as compact pills inside a cell — at top level the row stretches to
 *  full width, and inside an `<li>` Telegram hoists it out of the list and
 *  stretches it anyway. Verified on device 2026-09-10. */
function cellButtons(...buttons: string[]): string {
  return `<td><tg-button-row>${buttons.join("")}</tg-button-row></td>`;
}

function blockRow(b: DailyBlock, ahead: boolean, date: string): string {
  const glyph = ahead
    ? GLYPH_AHEAD
    : b.state === "approved" ? GLYPH_CONFIRMED : GLYPH_PENDING;
  const time = `<td>${glyph} ${b.start}–${b.end}</td>`;
  const title = `<td>${escapeHtml(b.title)}</td>`;
  const marker = b.habit_progress ? escapeHtml(b.habit_progress) : facetLabel(b);

  // A still-ahead block gets no controls: it has not happened, so there is
  // nothing to confirm. That is what the `◌` is explaining.
  if (ahead || b.state !== "pending") {
    // Pending rows spend the third column on controls; approved rows spend it
    // on the facet label. The two are mutually exclusive, so the column never
    // holds both and the table stays three columns wide. Until Ship 6
    // populates activity/category that cell is usually empty on an approved
    // row, which matches the pre-Ship-5 rendering.
    return `<tr>${time}${title}<td>${marker}</td></tr>`;
  }

  // The date rides in the callback because the button must address the day it
  // was drawn for. Deriving "today" in the handler instead would make every
  // control on a browsed day act on the wrong date.
  return `<tr>${time}${title}${cellButtons(
    button(GLYPH_CONFIRMED, `block:approve:${date}:${b.id}`, "success"),
    button("✕", `block:dismiss:${date}:${b.id}`, "danger"),
    button("✎", `block:edit:${date}:${b.id}`),
  )}</tr>`;
}

function gapRow(g: DailyGap, date: string): string {
  const start = toMinutes(g.start);
  // `end` may be "24:00" — day_coverage emits it for a gap running to end of
  // day. toMinutes handles it arithmetically (1440), which is what the fill
  // endpoint wants anyway.
  const end = toMinutes(g.end);
  const time = `<td>${GLYPH_GAP} ${g.start}–${g.end}</td>`;

  if (g.proposal) {
    // A proposal is a question with a ✕ beside it, so it carries the same
    // controls as a pending block. The day count is shown so the guess can be
    // judged rather than trusted.
    const seen = `${g.proposal.days_seen}/14`;
    return `<tr>${time}<td>${escapeHtml(g.proposal.name)}? <sub>${seen}</sub></td>` +
      cellButtons(
        button(GLYPH_CONFIRMED, `prop:approve:${date}:${start}:${end}`, "success"),
        button("✕", `prop:dismiss:${date}:${start}:${end}`, "danger"),
        button("✎", `prop:edit:${date}:${start}:${end}`),
      ) + "</tr>";
  }

  return `<tr>${time}<td>—</td>` + cellButtons(
    button(`+ ${hours(g.minutes)}`, `gap:fill:${date}:${start}:${end}`),
  ) + "</tr>";
}
```

- [ ] **Step 4: Update `buildDayRich`**

Replace the coverage paragraph:

```typescript
  parts.push(
    `<p>${hours(data.coverage.covered_minutes)} covered · ` +
    `${hours(data.coverage.unaccounted_minutes)} unaccounted</p>`,
  );
```

with:

```typescript
  // The summary and the refresh button share a one-row table, because
  // `<td align="right">` is the only right-alignment the rich grammar offers.
  // The `<h2>` stays outside it: table cells take inline formatting only, so
  // a heading inside one degrades to bold body text.
  parts.push(
    "<table><tr>" +
    `<td><sub>${hours(data.coverage.confirmed_minutes)} confirmed · ` +
    `${hours(data.coverage.pending_minutes)} pending · ` +
    `${hours(data.coverage.unaccounted_minutes)} unaccounted</sub></td>` +
    `<td align="right"><tg-button-row>` +
    button("⟲", `day:refresh:${data.date}`) +
    "</tg-button-row></td>" +
    "</tr></table>",
  );
```

Pass the date into both row builders. `blockRow` gained a third parameter, so its call site in the `rows` array changes too:

```typescript
    ...data.blocks.map((b) => {
      const ahead = toMinutes(b.start) >= elapsedMinutes;
      return { at: b.start, ahead, html: blockRow(b, ahead, data.date) };
    }),
    ...data.gaps.map((g) => ({
      at: g.start,
      ahead: toMinutes(g.start) >= elapsedMinutes,
      html: gapRow(g, data.date),
    })),
```

Change the divider push from `parts.push(\`<p>${NOW_DIVIDER}</p>\`)` to:

```typescript
      parts.push(NOW_DIVIDER);
```

Add the approve-all row after the tables and before the todos section:

```typescript
  // The count is in the label deliberately: approve-all includes gap
  // proposals (spec §5.6), so the number tells you how many things it will
  // actually act on rather than hiding them behind the word "all". Only
  // elapsed pending blocks count — a still-ahead one has no buttons and
  // approve-all skips it server-side too.
  const pendingCount =
    data.blocks.filter(
      (b) => b.state === "pending" && toMinutes(b.start) < elapsedMinutes,
    ).length +
    data.gaps.filter((g) => g.proposal !== null).length;
  if (pendingCount > 0) {
    parts.push(
      `<p>&nbsp;</p><tg-button-row align="center">` +
      button(
        `${GLYPH_CONFIRMED} approve all ${pendingCount}`,
        `day:approveall:${data.date}`,
        "primary",
      ) +
      "</tg-button-row>",
    );
  }
```

Replace the tail:

```typescript
  parts.push(weekBar(data.date));
  parts.push("<p>&nbsp;</p><hr>");
  parts.push(navBar(data.date));
```

with:

```typescript
  // One rule for all navigation, week bar and nav grouped beneath it. This
  // removes an `<hr>` rather than adding one: with two rules in the message
  // the now divider stopped being unambiguous, which is what the comment on
  // this divider's predecessor recorded.
  parts.push("<p>&nbsp;</p><hr>");
  parts.push(weekBar(data.date));
  parts.push("<p>&nbsp;</p>");
  parts.push(navBar(data.date));
```

Leave `weekBar` and `navBar` alone. They emit their own `<tg-button>` strings, and that duplication is one line of interpolation — rewriting two working functions onto the shared helper is scope creep in a task that already rewrites most of this file.

- [ ] **Step 5: Run the tests**

```bash
TELEGRAM_BOT_TOKEN=x AUTHORIZED_USER_ID=1 npx vitest run
npx tsc -b
```

Expected: green and clean. **Existing `day-rich` tests that assert `⚠`, `⟳` or `✅` are asserting the pre-Ship-5 surface — update them to the new glyphs.** Never delete a test to make the run green; the count must not drop.

- [ ] **Step 6: Commit**

```bash
git add apps/telegram-bot/src/formatters/day-rich.ts apps/telegram-bot/tests/formatters/day-rich.test.ts
git commit -m "feat(bot): /day renders approval state with in-row controls"
```

---

## Task 12: The bot's Ship 5 callbacks

**Files:**
- Create: `apps/telegram-bot/src/callbacks/day-actions.ts`
- Modify: `apps/telegram-bot/src/callbacks/index.ts`, `apps/telegram-bot/src/api/client.ts`
- Test: `apps/telegram-bot/tests/callbacks/day-actions.test.ts`

**Interfaces:**
- Consumes: `buildDayRich`, `buildBlockEditRich` (Task 13), `editRich`, `buildNavKeyboard`, `api`.
- Produces: `dayActionHandlers` (a grammY `Composer`), registered in `callbacks/index.ts`. API client methods `setBlockState(date, eventId, state)`, `approveAll(date)`, `fillGap(date, start, end, name?)`, `patchEvent(date, eventId, body)`.

Handlers, matching the callback data Task 11 emits:

| pattern | action |
|---|---|
| `day:refresh:<date>` | re-render |
| `block:approve:<id>` | `POST /events/{date}/{id}/state` `approved`, re-render |
| `block:dismiss:<id>` | same with `dismissed` |
| `block:edit:<id>` | render the edit view |
| `prop:approve:<date>:<s>:<e>` | `POST /daily/{date}/gaps/fill` with no name |
| `prop:dismiss:<date>:<s>:<e>` | re-render only — nothing is written (§4.3) |
| `gap:fill:<date>:<s>:<e>` | ask what it was, in a reply |
| `day:approveall:<date>` | `POST /daily/{date}/approve-all`, re-render, name the guesses |

**The one ordering trap:** `day:refresh:` and `day:approveall:` both match the existing `day:(.+)` date handler in `callbacks/index.ts`. This Composer must be registered **before** it, or `refresh:2026-09-10` is parsed as a date.

`prop:dismiss:` deliberately does nothing but re-render — §4.3: a refused proposal reappears, and that is the decision, not an oversight. Its test says so, because a later reader would otherwise "fix" it.

- [ ] **Step 1: Write the failing tests**

Create `apps/telegram-bot/tests/callbacks/day-actions.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";

const api = vi.hoisted(() => ({
  getDaily: vi.fn(), setBlockState: vi.fn(), approveAll: vi.fn(),
  fillGap: vi.fn(), patchEvent: vi.fn(),
}));
vi.mock("../../src/api/client.js", () => ({ api }));

const richMocks = vi.hoisted(() => ({ editRich: vi.fn(), sendRich: vi.fn() }));
vi.mock("../../src/bot-utils/send-rich.js", () => richMocks);

import { dayActionHandlers } from "../../src/callbacks/day-actions.js";

/** Drive one callback through the Composer's middleware. */
async function fire(data: string) {
  const ctx: any = {
    callbackQuery: { data },
    chat: { id: 1 },
    update: { callback_query: { data } },
    answerCallbackQuery: vi.fn(),
    editMessageText: vi.fn(),
    reply: vi.fn(),
  };
  await dayActionHandlers.middleware()(ctx, async () => {});
  return ctx;
}

const emptyDay = {
  date: "2026-09-10", tokens_today: 0, tokens_total: 0,
  blocks: [], gaps: [], incomplete: [], todos: [], notes: [],
  coverage: {
    covered_minutes: 0, unaccounted_minutes: 0, elapsed_minutes: 720,
    confirmed_minutes: 0, pending_minutes: 0,
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  api.getDaily.mockResolvedValue(emptyDay);
});

describe("block controls", () => {
  it("approve calls the state endpoint and re-renders", async () => {
    api.setBlockState.mockResolvedValue({ ok: true, state: "approved", habit: null });

    await fire("block:approve:2026-09-10:e1");

    expect(api.setBlockState).toHaveBeenCalledWith("2026-09-10", "e1", "approved");
    expect(richMocks.editRich).toHaveBeenCalled();
  });

  it("dismiss calls the state endpoint with dismissed", async () => {
    api.setBlockState.mockResolvedValue({ ok: true, state: "dismissed", habit: null });

    await fire("block:dismiss:2026-09-10:e1");

    expect(api.setBlockState).toHaveBeenCalledWith("2026-09-10", "e1", "dismissed");
  });

  it("says what a habit approval paid", async () => {
    api.setBlockState.mockResolvedValue({
      ok: true, state: "approved",
      habit: { name: "Dog walk", tokens_earned: 5, new_streak: 13 },
    });

    const ctx = await fire("block:approve:2026-09-10:e1");

    const said = ctx.answerCallbackQuery.mock.calls[0][0].text as string;
    expect(said).toContain("5");
    expect(said).toContain("13");
  });

  it("reports a 409 as a toast without wiping the day", async () => {
    api.setBlockState.mockRejectedValue(new Error("409 untick it in /habits"));

    const ctx = await fire("block:dismiss:2026-09-10:e1");

    expect(ctx.answerCallbackQuery).toHaveBeenCalled();
    expect(ctx.editMessageText).not.toHaveBeenCalled();
  });
});

describe("proposals", () => {
  it("approving one fills the gap with no name, letting the server decide", async () => {
    api.fillGap.mockResolvedValue({
      ok: true, event_id: "n1", name: "Sleep", was_guess: true,
    });

    await fire("prop:approve:2026-09-10:20:400");

    expect(api.fillGap).toHaveBeenCalledWith("2026-09-10", "00:20", "06:40", undefined);
  });

  it("dismissing one writes nothing at all", async () => {
    await fire("prop:dismiss:2026-09-10:20:400");

    // §4.3, deliberate: a refused proposal reappears rather than leaving a
    // dead row behind. If this ever starts writing, that decision was
    // reversed without anyone saying so.
    expect(api.fillGap).not.toHaveBeenCalled();
    expect(api.setBlockState).not.toHaveBeenCalled();
    expect(api.patchEvent).not.toHaveBeenCalled();
  });
});

describe("gap fill", () => {
  it("asks what the span was rather than guessing", async () => {
    const ctx = await fire("gap:fill:2026-09-10:780:855");

    expect(api.fillGap).not.toHaveBeenCalled();
    expect(ctx.reply).toHaveBeenCalled();
    expect(ctx.reply.mock.calls[0][0]).toContain("13:00");
    expect(ctx.reply.mock.calls[0][0]).toContain("14:15");
  });
});

describe("approve all", () => {
  it("names the guesses it banked", async () => {
    api.approveAll.mockResolvedValue({
      ok: true,
      approved: [
        { event_id: "e1", name: "Standup", was_guess: false },
        { event_id: "n1", name: "Sleep", was_guess: true },
      ],
      failed: [],
    });

    const ctx = await fire("day:approveall:2026-09-10");

    const said = ctx.answerCallbackQuery.mock.calls[0][0].text as string;
    expect(said).toContain("2");
    expect(said.toLowerCase()).toContain("guess");
    expect(said).toContain("Sleep");
  });

  it("reports failures alongside successes", async () => {
    api.approveAll.mockResolvedValue({
      ok: true,
      approved: [{ event_id: "e1", name: "Standup", was_guess: false }],
      failed: [{ event_id: "e2", reason: "untick it in /habits" }],
    });

    const ctx = await fire("day:approveall:2026-09-10");

    expect(ctx.answerCallbackQuery.mock.calls[0][0].text).toContain("1 could not");
  });
});

describe("refresh", () => {
  it("re-renders the day for the date in the callback", async () => {
    await fire("day:refresh:2026-09-10");

    expect(api.getDaily).toHaveBeenCalledWith("2026-09-10");
    expect(richMocks.editRich).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run to verify they fail**

```bash
TELEGRAM_BOT_TOKEN=x AUTHORIZED_USER_ID=1 npx vitest run tests/callbacks/day-actions.test.ts
```
Expected: cannot resolve `day-actions.js`.

- [ ] **Step 3: Add the API client methods**

In `apps/telegram-bot/src/api/client.ts`, beside `getDaily`:

```typescript
    setBlockState: (date: string, eventId: string, state: "approved" | "dismissed") =>
      request<{
        ok: boolean; state: string; event_id: string;
        habit: { name: string; tokens_earned: number; new_streak: number } | null;
        checkbox: { text: string } | null;
      }>(`/events/${date}/${eventId}/state`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ state }),
      }),

    approveAll: (date: string) =>
      request<{
        ok: boolean;
        approved: { event_id: string; name: string; was_guess: boolean }[];
        failed: { event_id: string; reason: string }[];
      }>(`/daily/${date}/approve-all`, { method: "POST" }),

    fillGap: (date: string, start: string, end: string, name?: string) =>
      request<{ ok: boolean; event_id: string; name: string; was_guess: boolean }>(
        `/daily/${date}/gaps/fill`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ start, end, name: name ?? null }),
        },
      ),

    patchEvent: (date: string, eventId: string, body: Record<string, unknown>) =>
      request<Record<string, unknown>>(`/events/${date}/${eventId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
```

- [ ] **Step 4: Write the handlers**

Create `apps/telegram-bot/src/callbacks/day-actions.ts`:

```typescript
import { Composer } from "grammy";
import { api } from "../api/client.js";
import { buildDayRich } from "../formatters/day-rich.js";
import { buildBlockEditRich } from "../formatters/block-edit-rich.js";
import { editRich } from "../bot-utils/send-rich.js";
import { buildNavKeyboard } from "../keyboards/nav.js";
import { markActiveSpanError } from "../tracing-utils.js";
import { logger } from "../logger.js";
import { setSelectedDate, noteDayView } from "../state/selected-date.js";

export const dayActionHandlers = new Composer();

/** "HH:MM" from minutes since midnight — the inverse of day-rich's toMinutes.
 *  Callback data carries minutes because they are compact and unambiguous. */
export function hhmm(minutes: number): string {
  const m = Math.max(0, Math.floor(minutes));
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

/** Re-render the day in place. Every action ends here, because the day view IS
 *  the feedback — a toast alone leaves stale glyphs and stale numbers on
 *  screen. */
async function rerender(ctx: any, date: string): Promise<void> {
  const data = await api.getDaily(date);
  setSelectedDate(ctx.chat!.id, data.date);
  await editRich(ctx, buildDayRich(data), { reply_markup: buildNavKeyboard("day") });
  noteDayView(ctx.chat!.id);
}

/** Report a failure as a toast and leave the message alone. The previous
 *  render is still navigable; replacing it with an error string would cost the
 *  user their whole day view to tell them one tap failed. */
async function toastFailure(ctx: any, err: unknown, what: string): Promise<void> {
  markActiveSpanError(err);
  logger.warn(
    { event_type: "day_action_failed", what, err: String(err) },
    "day_action_failed",
  );
  const text = String(err).includes("409")
    ? "Can't undo that here — untick it in /habits."
    : `❌ ${what} failed.`;
  await ctx.answerCallbackQuery({ text });
}

// MUST precede the `day:(.+)` date handler in callbacks/index.ts, or
// "refresh:2026-09-10" is parsed as a date.
dayActionHandlers.callbackQuery(/^day:refresh:(.+)$/, async (ctx) => {
  const date = ctx.match[1]!;
  await ctx.answerCallbackQuery({ text: "Refreshed" });
  try {
    await rerender(ctx, date);
  } catch (err) {
    await toastFailure(ctx, err, "Refresh");
  }
});

dayActionHandlers.callbackQuery(/^day:approveall:(.+)$/, async (ctx) => {
  const date = ctx.match[1]!;
  try {
    const result = await api.approveAll(date);
    const guesses = result.approved.filter((a) => a.was_guess);
    // Name the guesses. approve-all banks them (spec §5.6), so a wrong sleep
    // block has to be visible in the same breath rather than discovered weeks
    // later in the readout.
    let text = `✓ Approved ${result.approved.length}`;
    if (guesses.length > 0) {
      text += `, including ${guesses.map((g) => g.name).join(", ")} (a guess)`;
    }
    if (result.failed.length > 0) {
      text += ` · ${result.failed.length} could not be approved`;
    }
    await ctx.answerCallbackQuery({ text });
    await rerender(ctx, date);
  } catch (err) {
    await toastFailure(ctx, err, "Approve all");
  }
});

dayActionHandlers.callbackQuery(/^block:(approve|dismiss):([^:]+):(.+)$/, async (ctx) => {
  const action = ctx.match[1] as "approve" | "dismiss";
  const date = ctx.match[2]!;
  const eventId = ctx.match[3]!;
  const state = action === "approve" ? "approved" : "dismissed";
  try {
    const result = await api.setBlockState(date, eventId, state);
    // Say what it paid. A silent token award is one the user never connects
    // to the tap that earned it, which defeats the point of paying.
    const text = result.habit
      ? `✓ ${result.habit.name} · +${result.habit.tokens_earned} tokens · streak ${result.habit.new_streak}`
      : action === "approve" ? "✓ Confirmed" : "Dismissed";
    await ctx.answerCallbackQuery({ text });
    await rerender(ctx, date);
  } catch (err) {
    await toastFailure(ctx, err, action === "approve" ? "Confirm" : "Dismiss");
  }
});

dayActionHandlers.callbackQuery(/^prop:approve:([^:]+):(\d+):(\d+)$/, async (ctx) => {
  const date = ctx.match[1]!;
  const [start, end] = [Number(ctx.match[2]), Number(ctx.match[3])];
  try {
    // No name: the server recomputes the proposal for this interval (§4.2).
    // A client-sent name is a client-sent write, and a long one would not fit
    // in the 64 bytes Telegram allows.
    const result = await api.fillGap(date, hhmm(start), hhmm(end), undefined);
    await ctx.answerCallbackQuery({ text: `✓ ${result.name}` });
    await rerender(ctx, date);
  } catch (err) {
    await toastFailure(ctx, err, "Confirm");
  }
});

dayActionHandlers.callbackQuery(/^prop:dismiss:([^:]+):(\d+):(\d+)$/, async (ctx) => {
  const date = ctx.match[1]!;
  // Writes nothing, deliberately. A refused proposal reappears on the next
  // open (spec §4.3) rather than leaving behind a row whose only purpose is
  // suppression. If this ever starts writing, that decision was reversed
  // without anyone saying so — the test asserts the silence.
  await ctx.answerCallbackQuery({ text: "Skipped — it'll ask again" });
  try {
    await rerender(ctx, date);
  } catch (err) {
    await toastFailure(ctx, err, "Skip");
  }
});

dayActionHandlers.callbackQuery(/^prop:edit:([^:]+):(\d+):(\d+)$/, async (ctx) => {
  const date = ctx.match[1]!;
  const [start, end] = [Number(ctx.match[2]), Number(ctx.match[3])];
  await ctx.answerCallbackQuery();
  // A proposal has no block to edit yet, so there is nothing for the nudge pad
  // to operate on. Asking is the honest fallback, and the answer goes through
  // create_event like any other described block.
  await ctx.reply(
    `${hhmm(start)}–${hhmm(end)} on ${date} — tell me what it was and when.`,
  );
});

dayActionHandlers.callbackQuery(/^gap:fill:([^:]+):(\d+):(\d+)$/, async (ctx) => {
  const date = ctx.match[1]!;
  const [start, end] = [Number(ctx.match[2]), Number(ctx.match[3])];
  await ctx.answerCallbackQuery();
  // No proposal to accept, so ask. The answer goes through the normal NL path
  // into create_event, which Ship 4 already built.
  await ctx.reply(
    `${hhmm(start)}–${hhmm(end)} on ${date} — what was that? Just tell me.`,
  );
});

dayActionHandlers.callbackQuery(/^block:edit:([^:]+):(.+)$/, async (ctx) => {
  const date = ctx.match[1]!;
  const eventId = ctx.match[2]!;
  await ctx.answerCallbackQuery();
  try {
    const data = await api.getDaily(date);
    const block = data.blocks.find((b) => b.id === eventId);
    if (!block) {
      await ctx.answerCallbackQuery({ text: "That block is gone — refresh." });
      return;
    }
    await editRich(ctx, buildBlockEditRich(block, date, 0, 0),
      { reply_markup: buildNavKeyboard("day") });
  } catch (err) {
    await toastFailure(ctx, err, "Edit");
  }
});
```

Register it in `apps/telegram-bot/src/callbacks/index.ts`, **above** the `day:(.+)` handler:

```typescript
import { dayActionHandlers } from "./day-actions.js";

// Registered before the `day:(.+)` date handler below: that pattern would
// otherwise swallow `day:refresh:2026-09-10` and `day:approveall:2026-09-10`
// and try to parse the whole tail as a date.
callbackHandlers.use(dayActionHandlers);
```

- [ ] **Step 5: Run the tests**

```bash
TELEGRAM_BOT_TOKEN=x AUTHORIZED_USER_ID=1 npx vitest run
npx tsc -b
```

Expected: green and clean. Task 13 provides `buildBlockEditRich`; until it exists, add a temporary stub in `apps/telegram-bot/src/formatters/block-edit-rich.ts` returning `{ html: "" }` so `tsc` passes, and delete it in Task 13.

- [ ] **Step 6: Commit**

```bash
git add apps/telegram-bot/src/callbacks/day-actions.ts apps/telegram-bot/src/callbacks/index.ts apps/telegram-bot/src/api/client.ts apps/telegram-bot/tests/callbacks/day-actions.test.ts
git commit -m "feat(bot): wire the /day approval controls"
```

---

## Task 13: The edit view

**Files:**
- Create: `apps/telegram-bot/src/formatters/block-edit-rich.ts`
- Modify: `apps/telegram-bot/src/callbacks/day-actions.ts`
- Test: `apps/telegram-bot/tests/formatters/block-edit-rich.test.ts`

**Interfaces:**
- Consumes: `DailyBlock` from `@mazkir/shared-types`; `hhmm` from `day-actions.ts`.
- Produces: `buildBlockEditRich(block: DailyBlock, date: string, startDelta: number, endDelta: number): InputRichMessage<InputFile>`, and `NUDGES = [30, 15, 5]`.

Spec §6. The nudge pad is two explicit rows per field, **magnitudes aligned in columns, largest on the outside**:

```
start 09:05    [−30][−15][−5]
               [+30][+15][+5]
```

Two rows, not one of six: six buttons in a single row wrap to 3+3 at phone width on their own, so the wrap point has to be ours or the arrangement is Telegram's to choose.

**Drafts ride in the callback data** (§6.2): `adj:<id>:<start_delta>:<end_delta>`, about 20 of the 64 bytes available. Nothing is written until `✓ save & approve`. No server-side edit state to evict, no leak when the screen is abandoned, and a button on yesterday's message cannot apply its offsets to something since changed.

Each button carries the **accumulated** draft, not its own step. That is what makes the callback data self-sufficient.

`cancel` and `delete` are rendered but **inert** (§6.3, §9) — they answer with a toast saying so. They are drawn because the layout was approved with them present and their absence reads as an unfinished view.

- [ ] **Step 1: Write the failing tests**

Create `apps/telegram-bot/tests/formatters/block-edit-rich.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { buildBlockEditRich, NUDGES } from "../../src/formatters/block-edit-rich.js";
import type { DailyBlock } from "@mazkir/shared-types";

const block: DailyBlock = {
  id: "e1", start: "09:05", end: "10:00", title: "Standup",
  source: "calendar", type: "event", completed: false,
  activity: null, category: null, state: "pending", habit_progress: null,
};

describe("the nudge pad", () => {
  it("offers 30, 15 and 5 minute steps, largest first", () => {
    expect(NUDGES).toEqual([30, 15, 5]);
  });

  it("puts the minus row above the plus row, magnitudes aligned", () => {
    const html = buildBlockEditRich(block, "2026-09-10", 0, 0).html!;
    // Two explicit rows per field: a single row of six wraps to 3+3 on its
    // own, so pinning the arrangement means emitting the rows ourselves.
    expect(html.indexOf("−30")).toBeLessThan(html.indexOf("+30"));
    expect(html.indexOf("−30")).toBeLessThan(html.indexOf("−15"));
    expect(html.indexOf("−15")).toBeLessThan(html.indexOf("−5"));
  });

  it("carries the running draft in the callback data", () => {
    const html = buildBlockEditRich(block, "2026-09-10", -15, 30).html!;
    // Each button adds its own step to what is already accumulated.
    expect(html).toContain('data="adj:2026-09-10:e1:-45:30"');  // start −15 then −30
    expect(html).toContain('data="adj:2026-09-10:e1:-10:30"');  // start −15 then +5
    expect(html).toContain('data="adj:2026-09-10:e1:-15:60"');  // end 30 then +30
  });

  it("keeps every callback inside the 64-byte budget", () => {
    const html = buildBlockEditRich(block, "2026-09-10", -120, 120).html!;
    for (const m of html.matchAll(/data="([^"]+)"/g)) {
      expect(new TextEncoder().encode(m[1]!).length).toBeLessThanOrEqual(64);
    }
  });

  it("shows the drafted times, not the stored ones", () => {
    const html = buildBlockEditRich(block, "2026-09-10", 10, -20).html!;
    expect(html).toContain("09:15");
    expect(html).toContain("09:40");
  });

  it("puts the nudge rows inside <td> elements", () => {
    const html = buildBlockEditRich(block, "2026-09-10", 0, 0).html!;
    expect(html).toMatch(/<td><tg-button-row>[\s\S]*?−30[\s\S]*?<\/tg-button-row>/);
  });
});

describe("save and back", () => {
  it("saves with the accumulated deltas", () => {
    const html = buildBlockEditRich(block, "2026-09-10", -15, 30).html!;
    expect(html).toContain('data="adjsave:2026-09-10:e1:-15:30"');
  });

  it("goes back to the day it came from", () => {
    const html = buildBlockEditRich(block, "2026-09-10", 0, 0).html!;
    expect(html).toContain('data="day:2026-09-10"');
  });

  it("offers one save button, not a separate save and approve", () => {
    const html = buildBlockEditRich(block, "2026-09-10", 0, 0).html!;
    expect((html.match(/data="adjsave:/g) ?? []).length).toBe(1);
  });
});

describe("the deferred calendar actions", () => {
  it("renders cancel and delete, delete styled as dangerous", () => {
    const html = buildBlockEditRich(block, "2026-09-10", 0, 0).html!;
    expect(html).toContain("cancel in calendar");
    expect(html).toContain("delete");
    expect(html).toMatch(/data="cal:delete:e1"[^>]*style="danger"|style="danger"[^>]*>delete/);
  });
});

describe("no rename button", () => {
  it("does not offer one", () => {
    // Ship 4 already renames by talking, and a button whose only power is to
    // open a text prompt is not an improvement on saying it.
    const html = buildBlockEditRich(block, "2026-09-10", 0, 0).html!;
    expect(html.toLowerCase()).not.toContain("rename");
  });
});
```

- [ ] **Step 2: Run to verify they fail**

```bash
TELEGRAM_BOT_TOKEN=x AUTHORIZED_USER_ID=1 npx vitest run tests/formatters/block-edit-rich.test.ts
```
Expected: FAIL — the module is a stub or missing.

- [ ] **Step 3: Write the formatter**

Replace `apps/telegram-bot/src/formatters/block-edit-rich.ts` (deleting the Task 12 stub):

```typescript
import type { InputFile } from "grammy";
import type { InputRichMessage } from "@grammyjs/types";
import type { DailyBlock } from "@mazkir/shared-types";
import { escapeHtml } from "./telegram.js";

/** Step sizes, largest first so the magnitudes align in columns with the
 *  biggest on the outside — chosen from on-device renders (spec §6.1). */
export const NUDGES = [30, 15, 5];

function button(label: string, data: string, style?: string): string {
  const s = style ? ` style="${style}"` : "";
  return `<tg-button type="callback_data" data="${data}"${s}>${label}</tg-button>`;
}

function toMinutes(hhmmStr: string): number {
  const [h, m] = hhmmStr.split(":").map(Number);
  return (h ?? 0) * 60 + (m ?? 0);
}

function toClock(minutes: number): string {
  // Wraps rather than clamps: nudging past midnight is a real edit, and the
  // server decides whether the result is legal.
  const m = ((minutes % 1440) + 1440) % 1440;
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

/** One field's two nudge rows, inside a single `<td>`.
 *
 *  Two explicit rows rather than one row of six: at phone width Telegram wraps
 *  six buttons to 3+3 on its own, so pinning the arrangement means emitting
 *  the rows ourselves.
 *
 *  Each button carries the *accumulated* draft, not its own step — that is
 *  what lets the offsets live in the callback data instead of on the server
 *  (spec §6.2), so there is no edit state to evict and a button on an old
 *  message cannot apply its offsets to something since changed. */
function nudgePad(
  id: string, date: string, field: "start" | "end",
  startDelta: number, endDelta: number,
): string {
  const rows = [-1, 1].map((sign) =>
    "<tg-button-row>" +
    NUDGES.map((step) => {
      const delta = sign * step;
      const nextStart = field === "start" ? startDelta + delta : startDelta;
      const nextEnd = field === "end" ? endDelta + delta : endDelta;
      const label = `${sign < 0 ? "−" : "+"}${step}`;
      return button(label, `adj:${date}:${id}:${nextStart}:${nextEnd}`);
    }).join("") +
    "</tg-button-row>",
  );
  return `<td>${rows.join("")}</td>`;
}

export function buildBlockEditRich(
  block: DailyBlock, date: string, startDelta: number, endDelta: number,
): InputRichMessage<InputFile> {
  const start = toClock(toMinutes(block.start) + startDelta);
  const end = toClock(toMinutes(block.end) + endDelta);
  const length = ((toMinutes(end) - toMinutes(start)) + 1440) % 1440;

  const parts: string[] = [
    `<h2>${escapeHtml(block.title)}</h2>`,
    `<p>${start} – ${end} · ${length}m · ${escapeHtml(block.source)}</p>`,
    "<table>" +
      `<tr><td>start ${start}</td>${nudgePad(block.id, date, "start", startDelta, endDelta)}</tr>` +
      `<tr><td>end ${end}</td>${nudgePad(block.id, date, "end", startDelta, endDelta)}</tr>` +
    "</table>",
    "<p><i>nothing is written until you save</i></p>",
    // One button, not two: bothering to fix the times is taken as
    // confirmation that it happened (spec §6.2).
    `<tg-button-row align="center">` +
      button("✓ save &amp; approve", `adjsave:${date}:${block.id}:${startDelta}:${endDelta}`, "success") +
      button("← back", `day:${date}`) +
    "</tg-button-row>",
    "<h3>this event</h3>",
    // Rendered but inert in this ship (spec §6.3, §9). Drawn because the
    // layout was approved with them present and their absence reads as an
    // unfinished view; they answer with a toast saying they are not wired up.
    "<tg-button-row>" +
      button("cancel in calendar", `cal:cancel:${block.id}`) +
      button("delete", `cal:delete:${block.id}`, "danger") +
    "</tg-button-row>",
  ];

  // No rename button: Ship 4 already renames by talking, and a button whose
  // only power is to open a text prompt is not an improvement on saying it.
  return { html: parts.join("\n") };
}
```

- [ ] **Step 4: Add the three handlers**

Append to `apps/telegram-bot/src/callbacks/day-actions.ts`:

```typescript
/** "HH:MM" shifted by `delta` minutes, wrapping at midnight. */
function shiftClock(hhmmStr: string, delta: number): string {
  const [h, m] = hhmmStr.split(":").map(Number);
  return hhmm(((((h ?? 0) * 60 + (m ?? 0) + delta) % 1440) + 1440) % 1440);
}

dayActionHandlers.callbackQuery(/^adj:([^:]+):([^:]+):(-?\d+):(-?\d+)$/, async (ctx) => {
  const date = ctx.match[1]!;
  const eventId = ctx.match[2]!;
  const [startDelta, endDelta] = [Number(ctx.match[3]), Number(ctx.match[4])];
  await ctx.answerCallbackQuery();
  try {
    const data = await api.getDaily(date);
    const block = data.blocks.find((b) => b.id === eventId);
    if (!block) {
      await ctx.answerCallbackQuery({ text: "That block is gone — refresh." });
      return;
    }
    await editRich(ctx, buildBlockEditRich(block, date, startDelta, endDelta),
      { reply_markup: buildNavKeyboard("day") });
  } catch (err) {
    await toastFailure(ctx, err, "Adjust");
  }
});

dayActionHandlers.callbackQuery(/^adjsave:([^:]+):([^:]+):(-?\d+):(-?\d+)$/, async (ctx) => {
  const date = ctx.match[1]!;
  const eventId = ctx.match[2]!;
  const [startDelta, endDelta] = [Number(ctx.match[3]), Number(ctx.match[4])];
  try {
    const data = await api.getDaily(date);
    const block = data.blocks.find((b) => b.id === eventId);
    if (!block) {
      await ctx.answerCallbackQuery({ text: "That block is gone — refresh." });
      return;
    }
    if (startDelta !== 0 || endDelta !== 0) {
      // PATCH pins what it sets (Task 9), so these times survive the next
      // merge instead of being overwritten from the source.
      await api.patchEvent(date, eventId, {
        start_time: `${date}T${shiftClock(block.start, startDelta)}`,
        end_time: `${date}T${shiftClock(block.end, endDelta)}`,
      });
    }
    if (block.state === "pending") {
      await api.setBlockState(date, eventId, "approved");
    }
    await ctx.answerCallbackQuery({ text: "✓ Saved" });
    await rerender(ctx, date);
  } catch (err) {
    await toastFailure(ctx, err, "Save");
  }
});

dayActionHandlers.callbackQuery(/^cal:(cancel|delete):(.+)$/, async (ctx) => {
  // Deferred from this ship (spec §6.3, §9): the user chose local dismissal
  // for now, "cheap and non-destructive", pending real use to see which of the
  // two they reach for. The buttons are drawn because the layout was approved
  // with them; they say so rather than silently doing nothing.
  await ctx.answerCallbackQuery({
    text: "Not wired up yet — ✕ on the day view dismisses it locally.",
  });
});
```

Add tests for these three to `tests/callbacks/day-actions.test.ts`:

```typescript
describe("the edit view", () => {
  it("a nudge re-renders without writing anything", async () => {
    api.getDaily.mockResolvedValue({
      ...emptyDay,
      blocks: [{
        id: "e1", start: "09:05", end: "10:00", title: "Standup",
        source: "calendar", type: "event", completed: false,
        activity: null, category: null, state: "pending", habit_progress: null,
      }],
    });

    await fire("adj:2026-09-10:e1:-15:0");

    expect(api.patchEvent).not.toHaveBeenCalled();
    expect(api.setBlockState).not.toHaveBeenCalled();
    expect(richMocks.editRich).toHaveBeenCalled();
  });

  it("save patches the times and approves in one go", async () => {
    api.getDaily.mockResolvedValue({
      ...emptyDay,
      blocks: [{
        id: "e1", start: "09:05", end: "10:00", title: "Standup",
        source: "calendar", type: "event", completed: false,
        activity: null, category: null, state: "pending", habit_progress: null,
      }],
    });
    api.patchEvent.mockResolvedValue({});
    api.setBlockState.mockResolvedValue({ ok: true, state: "approved", habit: null });

    await fire("adjsave:2026-09-10:e1:-15:0");

    expect(api.patchEvent).toHaveBeenCalledWith("2026-09-10", "e1", {
      start_time: "2026-09-10T08:50",
      end_time: "2026-09-10T10:00",
    });
    expect(api.setBlockState).toHaveBeenCalledWith("2026-09-10", "e1", "approved");
  });

  it("save with no change still approves", async () => {
    api.getDaily.mockResolvedValue({
      ...emptyDay,
      blocks: [{
        id: "e1", start: "09:05", end: "10:00", title: "Standup",
        source: "calendar", type: "event", completed: false,
        activity: null, category: null, state: "pending", habit_progress: null,
      }],
    });
    api.setBlockState.mockResolvedValue({ ok: true, state: "approved", habit: null });

    await fire("adjsave:2026-09-10:e1:0:0");

    expect(api.patchEvent).not.toHaveBeenCalled();
    expect(api.setBlockState).toHaveBeenCalled();
  });

  it("cancel and delete say they are not wired up", async () => {
    const ctx = await fire("cal:delete:e1");

    expect(api.patchEvent).not.toHaveBeenCalled();
    expect(ctx.answerCallbackQuery.mock.calls[0][0].text).toContain("Not wired up");
  });
});
```

- [ ] **Step 5: Run the tests**

```bash
TELEGRAM_BOT_TOKEN=x AUTHORIZED_USER_ID=1 npx vitest run
npx tsc -b
```
Expected: green and clean.

- [ ] **Step 6: Commit**

```bash
git add apps/telegram-bot/src/formatters/block-edit-rich.ts apps/telegram-bot/src/callbacks/day-actions.ts apps/telegram-bot/tests/formatters/block-edit-rich.test.ts apps/telegram-bot/tests/callbacks/day-actions.test.ts
git commit -m "feat(bot): the block edit view"
```

---

## Task 14: Documentation

**Files:**
- Modify: `apps/vault-server/src/services/events_service.py` (delete the line-45 comment)
- Modify: `docs/plans/2026-08-21-time-management-phase2-capture-design.md`
- Modify: `CLAUDE.md`

Three documentation debts the code now contradicts.

- [ ] **Step 1: Replace the stale-row comment**

In `apps/vault-server/src/services/events_service.py`, in the `_DELETABLE_SOURCE_SYSTEMS` block, replace:

```python
# Stale rows for these two linger until Ship 5 gives them stable identity.
# That is visible clutter; the alternative is silent loss.
```

with:

```python
# Ship 5 made stable identity unnecessary rather than providing it: these two
# sources are the human-created ones, so their approval is derived from the
# checkbox or the habit at read time (services/approval.py) and no row is ever
# persisted against their ids. An unmatched row here is still preserved rather
# than deleted, for the reasons above.
```

- [ ] **Step 2: Update the phase doc**

In `docs/plans/2026-08-21-time-management-phase2-capture-design.md`, add to the status block at the top:

```markdown
**Ship 5 shipped:** see `docs/superpowers/specs/2026-09-10-ship5-inferred-capture-design.md`. Reordered ahead of 4b — see that spec's §1.3.
```

In §2's table, swap the `4b` and `5` rows so the order matches reality, and append to 4b's "Why here" cell: `now after 5 — see the Ship 5 spec §1.3`.

In §11, mark the habit-clock item resolved:

```markdown
- ~~`habits.py` reads "today" in `VAULT_TIMEZONE` but writes via the server clock~~ — fixed in Ship 5; `habit_completion.complete_habit` now defaults `now` to a `VAULT_TIMEZONE`-aware datetime, which is what let approval stamp a past block's own date.
```

- [ ] **Step 3: Update `CLAUDE.md`**

Add these bullets to the Architecture section:

```markdown
- **Approval is derived where it can be, stored where it must be (Ship 5):** `services/approval.py`'s `resolve_state(event)` answers `approved`/`pending`/`dismissed`. A stored `state` wins; otherwise a block a *human action* created is approved — a habit you ticked, a checkbox you checked, anything `create_event` wrote — and a machine-inferred one is pending. It keys on the **source system**, not on `completed`: a calendar entry carries `completed` too (Google's green colour, `merger_service.py:279`) while still being intent rather than evidence. The payoff is that the only persisted state rows are calendar and timeline, whose ids come from upstream and are stable — so approval never keys to a `note_line` hash or a `habit_slug`, which is the stale-duplicate trap `events_service.py`'s own comment used to warn about. `state` therefore defaults to **absent**, and a legacy `"suggested"` is dropped on read.
- **Coverage is two unions over one block list (Ship 5):** gaps and `unaccounted_minutes` come from **every** drawable block, so a `░` row always means nothing is there at all and can never overlap a pending block; `confirmed_minutes` comes from approved blocks only and is the one number the weekly readout may read. `pending_minutes` subtracts what is already confirmed, so two overlapping blocks of different states never exceed the wall clock. `covered_minutes` keeps its Ship 2 meaning. `day_coverage.py` is unchanged — it is simply called twice.
- **Gap proposals read your own history (Ship 5):** `services/gap_proposals.py` looks at approved blocks in the last 14 date files, keeps those covering at least half the gap, and proposes the most frequent name if it appears on at least 3 distinct days. An overnight gap containing 02:00–05:00 falls back to `Sleep` as a cold-start seed, which history beats once there is any. A refused proposal **reappears** on the next open — deliberately, rather than leaving behind a row whose only purpose is suppression. `✓` on a proposal sends only the interval and the server recomputes the name, so a client can never write a name of its choosing.
- **Approving a habit block ticks the habit (Ship 5):** one tap confirms the block and pays the tokens, stamped on the **block's** date rather than today. Nothing unticks a habit or retracts tokens — approval is one-way from `/day`, and an approved row carries no buttons at all.
- **In-cell buttons are the only compact ones (Ship 5):** a `<tg-button-row>` inside a `<td>` renders as pills sized to their content; the same row at top level stretches full width, and inside an `<li>` Telegram hoists it out of the list and stretches it. Verified on device — `@grammyjs/types` cannot answer this, because the bot resolves the hoisted root copy at 3.28.0 despite `grammy ^1.46.0`, and that version's rich grammar predates buttons entirely. `/day` therefore puts `[✓][✕][✎]` in each pending row's third column, and the edit view puts its nudge pads in cells.
- **The `/day` glyphs (Ship 5):** `✓` settled · `●` happened, waiting on you · `░` unaccounted · `◌` still ahead, no buttons. `✅`, `⚠` and `⟳` are gone; completion folds into `✓`, because "the source says it was done" is one input to approval rather than approval itself.
- **Block edit drafts live in callback data (Ship 5):** `adj:<id>:<start_delta>:<end_delta>` carries the whole pending edit in ~20 of Telegram's 64 bytes, so nothing is written until save, there is no server-side edit state to evict, and a button on an old message cannot apply its offsets to something since changed. Same reasoning as the selected date living in `day:2026-09-10`.
```

Update the endpoint list with the four new routes (`POST /events/{date}/{id}/state`, `POST /daily/{date}/approve-all`, `POST /daily/{date}/gaps/fill`, and `PATCH /events/{date}/{id}` now pinning), and update `/daily`'s documented response shape with `confirmed_minutes`, `pending_minutes` and `gaps[].proposal`.

- [ ] **Step 4: Run everything one last time**

```bash
cd apps/vault-server && ./venv/bin/python -m pytest tests/ -q
cd ../telegram-bot && TELEGRAM_BOT_TOKEN=x AUTHORIZED_USER_ID=1 npx vitest run && npx tsc -b
cd ../telegram-web-app && npx tsc -b
```
Expected: server ≥ 1066 + new, bot ≥ 159 + new, both typechecks clean.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md docs/plans/2026-08-21-time-management-phase2-capture-design.md apps/vault-server/src/services/events_service.py
git commit -m "docs: record Ship 5"
```

---

## Self-Review

**Spec coverage.** Every section maps to a task: §2.1/§2.3 → T1; §2.2 → T2; §2.4 → T6 (the date) and T7 (the 409 refusal); §2.5 → T3; §3 → T3; §4.1/§4.2 → T4, T5; §4.3 → T12's "writes nothing at all" test; §4.4 → T8; §5.1–§5.5 → T11; §5.6 → T8 and T11's `pendingCount` and T12's guess-naming; §6.1/§6.2 → T13; §6.3 → T13's inert buttons; §7 → T5, T7, T8, T9; §8.1 → T14; §8.2 → T6; §9 → each deferral asserted where it could silently regress; §10's six testing notes → tests in T1, T3, T4, T6, T7, T11.

**Two gaps found while reviewing, both closed.** The spec's §7 lists `PATCH` pinning as part of Ship 5 and it had no task — that is now Task 9. And §5.6's "the button carries its count" needs the bot to compute it, which is Task 11's `pendingCount`, not left implicit.

**One correctness bug found while reviewing.** An early draft of Task 8 approved every pending block, including still-ahead ones — which would confirm a 21:00 block at 14:00, contradicting §5.1's whole reason for `◌` having no buttons. `approve_all` now skips blocks starting at or after `elapsed_minutes`, and `test_still_ahead_blocks_are_not_approved` pins it.

**One ordering trap, called out where it bites.** `day:refresh:` and `day:approveall:` both match the existing `day:(.+)` pattern. Task 12 registers the new Composer first and says why in a code comment, not just in the plan.

**A timezone trap, avoided by construction.** An earlier draft had Task 12's handlers derive "today" for block actions, which would have made every control on a browsed day act on the wrong date. Every block-scoped callback now carries its own date (see Global Constraints), so no handler needs a clock at all. `day-rich.ts` still derives today's date for the `· today` header label, which is display-only and already uses `config.vaultTimezone` rather than `new Date()`.

**Three places the plan knowingly guesses at a signature.** Tasks 7, 8 and 13 call `daily_set_task_state`, `EventsService.create_event` and `api.patchEvent` from memory of their shapes. Each step says to read the real signature and adapt, and states the behaviour required so an implementer verifies rather than assumes — and explicitly says not to change the handler to fit the call.

**Two test-churn sites, flagged rather than discovered.** T2 updates two tests asserting `state == "suggested"`; T11 updates existing `day-rich` tests asserting `⚠`/`⟳`/`✅`. Both say: update to the new expectation, never delete to go green, and the count must not drop.

**One cross-task dependency that needs care.** Task 12 imports `buildBlockEditRich`, which Task 13 writes. Task 12 says to stub it and Task 13 says to delete the stub. If the tasks run in order this is a two-line detour; if they are reordered, Task 13 must come first.
