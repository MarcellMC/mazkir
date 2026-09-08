# Ship 4 — NL logging and single-block edits Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a full day loggable and correctable by talking — partial statements accepted rather than guessed, corrections that survive re-inference and reach Google Calendar, and blocks addressable by description.

**Architecture:** A new persisted `user_set` map gives each event per-field provenance, re-applied at the end of `reconcile` so a user's edit outlives a merge. Completeness is derived from the timestamps rather than stored, which makes a half-filled block a first-class row instead of a silently dropped one. `create_event` derives the third of start/end/duration from any two, and splits at midnight. The merge pipeline moves out of the route layer so the agent's `list_events` sees the same day `/day` renders.

**Tech Stack:** Python 3.13 / FastAPI / pydantic / pytest (`apps/vault-server`); TypeScript / grammY 1.46 / vitest (`apps/telegram-bot`); `@mazkir/shared-types`.

**Spec:** `docs/superpowers/specs/2026-09-08-ship4-nl-logging-design.md`

## Global Constraints

- **Worktree setup, once, before Task 1.** A worktree has no venv (venvs hold absolute paths):
  ```bash
  ln -sfn /home/marcellmc/dev/mazkir/apps/vault-server/venv apps/vault-server/venv
  ```
  Do **not** symlink `memory/` into the worktree. The suite resolves the vault from config, verified at 937 passing without it, and a symlink at the repo root is not matched by `.gitignore`'s `memory/` pattern — so it shows as untracked and a `git add -A` would commit it.
- **Baseline is 937 server tests passing**, verified in this worktree. Run `./venv/bin/python -m pytest tests/ -q` from `apps/vault-server`. Never accept a task that reduces this number.
- **The bot suite needs environment variables** or `tests/formatters/day-rich.test.ts` fails to *collect* — `day-rich.ts` imports `config.ts`, which throws without them. Always run it as `TELEGRAM_BOT_TOKEN=x AUTHORIZED_USER_ID=1 npx vitest run`. A bare `npx vitest run` reports `1 failed | 19 passed`, `107 passed`, and that is the environment, not your change. With the variables set the baseline is **147 passing across 20 files**.
- **`user_set` settable keys are exactly these five:** `name`, `start_time`, `end_time`, `location`, `activity`. Any other key present in the map is ignored on re-application.
- **`completed` and `habit` are never user-settable** — `reconcile` re-derives them from vault state every merge.
- **`state` is not touched by this ship.** It stays `"suggested"`; Ship 5 owns approval.
- **Completeness is never stored.** `is_complete(event)` is computed from `start_time` and `end_time` every time it is needed.
- **`end == start` is legal** (a zero-length moment). Only `end < start` is rejected.
- **Every calendar outcome uses the existing shape** `{"ok": bool, "attempted": bool, "reason"?: str, "event_id"?: str}`. `attempted: false` means "there was nothing to sync"; `attempted: true` with `ok: false` means "this did not happen and the user must be told".
- **Mazkir writes only to its own calendar.** Every Google write passes `calendarId=self._calendar_id`.
- **Error codes come from `src.services.tool_response.ErrorCode`.** Use `SCHEMA_INVALID` for contradictory input, `PATH_NOT_FOUND` for an unresolvable reference, `AMBIGUOUS_MATCH` for several.
- **Commit after every task.** Conventional-commit prefixes (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`).
- **The vault (`memory/`) is a separate git repo.** Never commit it from the monorepo.

---

## File Structure

**New files (vault-server):**

| Path | Responsibility |
|---|---|
| `src/services/async_bridge.py` | `maybe_await(value)` — run a coroutine from sync code. One home for the bridge that `sync_to_calendar.py` and two event tools each reach for today. |
| `src/services/day_assembly.py` | `merge_from_sources(date)` — the source fan-out currently private to `routes/events.py`. Imported by both the routes and the agent's event tools. |
| `src/services/block_resolver.py` | `resolve_block(reference, candidates)` — descriptive addressing, mirroring `resolver.py`'s ladder. |
| `src/services/interval.py` | Pure interval arithmetic: derive the third of start/end/duration, detect and split a midnight crossing. No I/O. |

**Modified (vault-server):** `src/services/events_service.py` (user_set, is_complete, interval guard, no argument mutation), `src/services/merger_service.py` (`calendar` field), `src/services/calendar_service.py` (`update_event`), `src/services/agent_service.py` (tool schemas + handlers + prompt tail), `src/api/routes/events.py` (import the extracted merge), `src/api/routes/daily.py` (`incomplete[]`), `src/api/routes/message.py` (`selected_date`).

**New files (bot):** `src/state/selected-date.ts`. **Modified (bot):** `src/bot.ts` (transformer), `src/commands/day.ts`, `src/callbacks/index.ts`, `src/conversations/message.ts`, `src/api/client.ts`, `src/formatters/day-rich.ts`, `packages/shared-types/src/daily.ts`.

**Task order and why:** Tasks 1–3 are pure functions and service-level state with no callers — they can be written and tested in isolation. Task 4 makes the agent see the reconciled day, which Tasks 5–6 depend on. Task 7 is the calendar. Tasks 8–9 are the surfaces. Task 10 is the bot's date hint, which is independent of everything else and could be dropped without breaking the rest.

---

### Task 1: Interval arithmetic

Pure functions with no dependencies. Everything later in the plan that touches times calls into here, so it lands first.

**Files:**
- Create: `apps/vault-server/src/services/interval.py`
- Test: `apps/vault-server/tests/test_interval.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `derive_interval(start: str | None, end: str | None, duration_minutes: int | None, date: str) -> dict` — returns `{"ok": True, "start_time": str|None, "end_time": str|None, "duration_minutes": int|None}` or `{"ok": False, "error": str}`.
  - `normalize_time(value: str | None, date: str) -> str | None` — `"18:00"` → `"2026-09-08T18:00:00"`; a value already carrying a date is returned unchanged.
  - `crosses_midnight(start_time: str, end_time: str) -> bool`
  - `split_at_midnight(start_time: str, end_time: str) -> list[tuple[str, str]]`

- [ ] **Step 1: Write the failing tests**

Create `apps/vault-server/tests/test_interval.py`:

```python
"""Interval arithmetic — the sums the model used to do and got wrong."""

from src.services.interval import (
    crosses_midnight,
    derive_interval,
    normalize_time,
    split_at_midnight,
)

DATE = "2026-09-08"


class TestNormalizeTime:
    def test_bare_hhmm_gets_the_date(self):
        assert normalize_time("18:00", DATE) == "2026-09-08T18:00:00"

    def test_iso_timestamp_is_left_alone(self):
        assert normalize_time("2026-09-07T18:00:00", DATE) == "2026-09-07T18:00:00"

    def test_none_stays_none(self):
        assert normalize_time(None, DATE) is None


class TestDeriveInterval:
    def test_start_and_end_give_duration(self):
        r = derive_interval("18:00", "19:00", None, DATE)
        assert r["ok"] is True
        assert r["start_time"] == "2026-09-08T18:00:00"
        assert r["end_time"] == "2026-09-08T19:00:00"
        assert r["duration_minutes"] == 60

    def test_start_and_duration_give_end(self):
        r = derive_interval("18:00", None, 40, DATE)
        assert r["end_time"] == "2026-09-08T18:40:00"
        assert r["duration_minutes"] == 40

    def test_end_and_duration_give_start(self):
        """'Just got back from the 40-minute dog walk' — the utterance
        anchors the END, and the start is arithmetic the model should
        never be asked to do."""
        r = derive_interval(None, "16:40", 40, DATE)
        assert r["start_time"] == "2026-09-08T16:00:00"
        assert r["end_time"] == "2026-09-08T16:40:00"

    def test_all_three_consistent_is_accepted(self):
        r = derive_interval("18:00", "19:00", 60, DATE)
        assert r["ok"] is True
        assert r["duration_minutes"] == 60

    def test_all_three_inconsistent_is_rejected(self):
        """Never silently pick one. Two of the three are wrong and we do
        not know which."""
        r = derive_interval("18:00", "19:00", 90, DATE)
        assert r["ok"] is False
        assert "90" in r["error"] and "60" in r["error"]

    def test_only_start_is_incomplete_not_an_error(self):
        r = derive_interval("18:00", None, None, DATE)
        assert r["ok"] is True
        assert r["start_time"] == "2026-09-08T18:00:00"
        assert r["end_time"] is None
        assert r["duration_minutes"] is None

    def test_only_end_is_incomplete_not_an_error(self):
        r = derive_interval(None, "16:40", None, DATE)
        assert r["ok"] is True
        assert r["start_time"] is None
        assert r["end_time"] == "2026-09-08T16:40:00"

    def test_nothing_given_is_allowed(self):
        r = derive_interval(None, None, None, DATE)
        assert r["ok"] is True
        assert r["start_time"] is None and r["end_time"] is None

    def test_duration_alone_cannot_place_anything(self):
        r = derive_interval(None, None, 40, DATE)
        assert r["ok"] is True
        assert r["start_time"] is None and r["end_time"] is None
        assert r["duration_minutes"] == 40

    def test_zero_length_is_legal(self):
        r = derive_interval("18:00", "18:00", None, DATE)
        assert r["ok"] is True
        assert r["duration_minutes"] == 0

    def test_end_before_start_on_explicit_dates_is_rejected(self):
        """Two full timestamps in the wrong order is a contradiction, not
        a midnight crossing — the dates say so."""
        r = derive_interval("2026-09-08T19:00:00", "2026-09-08T18:00:00", None, DATE)
        assert r["ok"] is False


class TestMidnight:
    def test_bare_times_in_reverse_order_cross_midnight(self):
        r = derive_interval("23:30", "07:15", None, DATE)
        assert r["ok"] is True
        assert r["start_time"] == "2026-09-08T23:30:00"
        assert r["end_time"] == "2026-09-09T07:15:00"
        assert r["duration_minutes"] == 465

    def test_crosses_midnight_detects_a_date_change(self):
        assert crosses_midnight("2026-09-08T23:30:00", "2026-09-09T07:15:00") is True
        assert crosses_midnight("2026-09-08T18:00:00", "2026-09-08T19:00:00") is False

    def test_split_produces_one_fragment_per_day(self):
        parts = split_at_midnight("2026-09-08T23:30:00", "2026-09-09T07:15:00")
        assert parts == [
            ("2026-09-08T23:30:00", "2026-09-08T23:59:59"),
            ("2026-09-09T00:00:00", "2026-09-09T07:15:00"),
        ]

    def test_split_handles_more_than_one_boundary(self):
        parts = split_at_midnight("2026-09-08T22:00:00", "2026-09-10T06:00:00")
        assert len(parts) == 3
        assert parts[0][0] == "2026-09-08T22:00:00"
        assert parts[1] == ("2026-09-09T00:00:00", "2026-09-09T23:59:59")
        assert parts[2][1] == "2026-09-10T06:00:00"

    def test_split_of_a_same_day_interval_is_one_fragment(self):
        parts = split_at_midnight("2026-09-08T18:00:00", "2026-09-08T19:00:00")
        assert parts == [("2026-09-08T18:00:00", "2026-09-08T19:00:00")]
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd apps/vault-server && ./venv/bin/python -m pytest tests/test_interval.py -q
```

Expected: collection error — `ModuleNotFoundError: No module named 'src.services.interval'`.

- [ ] **Step 3: Write the implementation**

Create `apps/vault-server/src/services/interval.py`:

```python
"""Interval arithmetic for events: derive, validate, split at midnight.

Pure. No I/O, no timezone conversion — every timestamp here is local wall
clock, the same convention `day_coverage` uses.

This module exists because the arithmetic it does is the arithmetic the
model demonstrably gets wrong. On 2026-08-16 a retrospective utterance was
turned into a block shifted by its own length, because computing the second
endpoint was left to the model. Given any two of start/end/duration, the
third is a subtraction — so the tool takes any two and does it here.
"""

from __future__ import annotations

import datetime as dt

_FMT = "%Y-%m-%dT%H:%M:%S"


def normalize_time(value: str | None, date: str) -> str | None:
    """Anchor a bare `HH:MM` to `date`. Anything else is returned as-is."""
    if not value:
        return None
    if "T" in value:
        return value
    if len(value) <= 5:
        return f"{date}T{value}:00"
    return value


def _parse(value: str) -> dt.datetime:
    # `fromisoformat` accepts both "…T18:00" and "…T18:00:00"; normalizing
    # to a datetime here means every comparison below is on real instants
    # rather than on string prefixes.
    return dt.datetime.fromisoformat(value)


def _fmt(value: dt.datetime) -> str:
    return value.strftime(_FMT)


def derive_interval(
    start: str | None,
    end: str | None,
    duration_minutes: int | None,
    date: str,
) -> dict:
    """Fill in whichever of start/end/duration was not given.

    Fewer than two known values is not an error: it produces an incomplete
    block, which is the correct record of an incomplete statement. Three
    mutually inconsistent values IS an error — two of them are wrong and
    nothing here can tell which, so guessing would silently corrupt the day.
    """
    start_iso = normalize_time(start, date)
    end_iso = normalize_time(end, date)

    # Two bare times in reverse order mean the interval crossed midnight:
    # "slept 23:30 to 07:15" is one night, not a contradiction. Only bare
    # times get this reading — two explicit dates in reverse order are a
    # contradiction, because the dates already said what was meant.
    if (
        start_iso
        and end_iso
        and start and end
        and "T" not in start and "T" not in end
        and _parse(end_iso) < _parse(start_iso)
    ):
        end_iso = _fmt(_parse(end_iso) + dt.timedelta(days=1))

    known = sum(x is not None for x in (start_iso, end_iso, duration_minutes))
    if known < 2:
        return {
            "ok": True,
            "start_time": start_iso,
            "end_time": end_iso,
            "duration_minutes": duration_minutes,
        }

    if start_iso and end_iso:
        delta = int((_parse(end_iso) - _parse(start_iso)).total_seconds() // 60)
        if delta < 0:
            return {
                "ok": False,
                "error": f"End {end_iso} is before start {start_iso}",
            }
        if duration_minutes is not None and duration_minutes != delta:
            return {
                "ok": False,
                "error": (
                    f"start {start_iso} and end {end_iso} are {delta} minutes apart, "
                    f"but duration_minutes says {duration_minutes}. "
                    "Supply two of the three, not three that disagree."
                ),
            }
        return {
            "ok": True,
            "start_time": start_iso,
            "end_time": end_iso,
            "duration_minutes": delta,
        }

    if start_iso and duration_minutes is not None:
        end_iso = _fmt(_parse(start_iso) + dt.timedelta(minutes=duration_minutes))
    else:
        start_iso = _fmt(_parse(end_iso) - dt.timedelta(minutes=duration_minutes))

    return {
        "ok": True,
        "start_time": start_iso,
        "end_time": end_iso,
        "duration_minutes": duration_minutes,
    }


def crosses_midnight(start_time: str, end_time: str) -> bool:
    """True when the two timestamps fall on different calendar days."""
    if not start_time or not end_time:
        return False
    return _parse(start_time).date() != _parse(end_time).date()


def split_at_midnight(start_time: str, end_time: str) -> list[tuple[str, str]]:
    """One `(start, end)` fragment per calendar day the interval touches.

    Storage splits at 00:00 (Phase 1 §4.2): `data/events/{date}.json` is
    keyed by day and `day_coverage` measures minute offsets within one, so
    an interval spanning a boundary has no single correct home. The first
    fragment ends at 23:59:59 rather than the next midnight, so the two do
    not both claim the boundary minute.
    """
    if not crosses_midnight(start_time, end_time):
        return [(start_time, end_time)]

    fragments: list[tuple[str, str]] = []
    cursor = _parse(start_time)
    finish = _parse(end_time)

    while cursor.date() < finish.date():
        day_end = dt.datetime.combine(cursor.date(), dt.time(23, 59, 59))
        fragments.append((_fmt(cursor), _fmt(day_end)))
        cursor = dt.datetime.combine(
            cursor.date() + dt.timedelta(days=1), dt.time(0, 0, 0)
        )

    fragments.append((_fmt(cursor), _fmt(finish)))
    return fragments
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd apps/vault-server && ./venv/bin/python -m pytest tests/test_interval.py -q
```

Expected: `20 passed`.

- [ ] **Step 5: Run the full suite**

```bash
cd apps/vault-server && ./venv/bin/python -m pytest tests/ -q
```

Expected: `957 passed` (937 baseline + 20).

- [ ] **Step 6: Commit**

```bash
git add apps/vault-server/src/services/interval.py apps/vault-server/tests/test_interval.py
git commit -m "feat(events): interval arithmetic — derive, validate, split at midnight"
```

---

### Task 2: `user_set` — per-field provenance

The load-bearing change. Without it, every edit made in Tasks 5–6 is reverted the next time `/day` is opened.

**Files:**
- Modify: `apps/vault-server/src/services/events_service.py` (`save_events` ~line 126; `reconcile`'s matched branch ~line 482)
- Test: `apps/vault-server/tests/test_events_service.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - `USER_SETTABLE_FIELDS: frozenset[str]` — module-level in `events_service.py`.
  - `apply_user_set(event: dict) -> None` — module-level; mutates in place, recomputes `duration_minutes` when it moved an end.
  - `is_complete(event: dict) -> bool` — module-level.
  - `EventsService.update_event(..., user_set_fields: list[str] | None = None, revert_fields: list[str] | None = None)`.

- [ ] **Step 1: Write the failing tests**

Append to `apps/vault-server/tests/test_events_service.py`:

```python
class TestUserSet:
    """Per-field provenance: a merge must not undo what the user said.

    `reconcile` re-derives name/start/end/location from the source on every
    read. Before `user_set`, renaming a calendar block worked and then
    silently reverted the next time the day was opened.
    """

    def _calendar_event(self):
        return {
            "id": "evt_1",
            "name": "Daily sync",
            "start_time": "2026-09-08T10:00:00",
            "end_time": "2026-09-08T10:30:00",
            "source": "calendar",
            "source_ids": {"calendar_id": "gcal_1"},
        }

    def _fresh(self):
        return [{
            "name": "Daily sync",
            "start_time": "2026-09-08T10:00:00",
            "end_time": "2026-09-08T10:30:00",
            "source": "calendar",
            "source_ids": {"calendar_id": "gcal_1"},
        }]

    def test_save_events_defaults_user_set_to_empty(self, events_service):
        events_service.save_events("2026-09-08", [self._calendar_event()])
        assert events_service.get_events("2026-09-08")[0]["user_set"] == {}

    def test_pinned_name_survives_reconcile(self, events_service):
        """The exact 2026-09-08 regression, asserted directly."""
        events_service.save_events("2026-09-08", [self._calendar_event()])
        events_service.update_event(
            "2026-09-08", "evt_1", {"name": "Standup"}, user_set_fields=["name"],
        )
        result = events_service.reconcile(
            "2026-09-08", self._fresh(), available_sources={"calendar"},
        )
        assert result[0]["name"] == "Standup"

    def test_unpinned_fields_still_track_the_source(self, events_service):
        events_service.save_events("2026-09-08", [self._calendar_event()])
        events_service.update_event(
            "2026-09-08", "evt_1", {"name": "Standup"}, user_set_fields=["name"],
        )
        fresh = self._fresh()
        fresh[0]["start_time"] = "2026-09-08T11:00:00"
        fresh[0]["end_time"] = "2026-09-08T11:30:00"

        result = events_service.reconcile(
            "2026-09-08", fresh, available_sources={"calendar"},
        )

        assert result[0]["name"] == "Standup"          # pinned
        assert result[0]["start_time"] == "2026-09-08T11:00:00"  # not pinned

    def test_pinned_times_recompute_duration_after_reconcile(self, events_service):
        events_service.save_events("2026-09-08", [self._calendar_event()])
        events_service.update_event(
            "2026-09-08", "evt_1",
            {"end_time": "2026-09-08T11:00:00"},
            user_set_fields=["end_time"],
        )
        result = events_service.reconcile(
            "2026-09-08", self._fresh(), available_sources={"calendar"},
        )
        assert result[0]["end_time"] == "2026-09-08T11:00:00"
        assert result[0]["duration_minutes"] == 60

    def test_non_settable_keys_are_ignored(self, events_service):
        """A stray key must not become a way to pin `completed`, which
        reconcile re-derives from vault state every merge."""
        event = self._calendar_event()
        event["user_set"] = {"completed": True, "source_ids": {"calendar_id": "hijacked"}}
        events_service.save_events("2026-09-08", [event])

        result = events_service.reconcile(
            "2026-09-08", self._fresh(), available_sources={"calendar"},
        )

        assert result[0]["completed"] is False
        assert result[0]["source_ids"] == {"calendar_id": "gcal_1"}

    def test_empty_user_set_is_a_no_op(self, events_service):
        events_service.save_events("2026-09-08", [self._calendar_event()])
        result = events_service.reconcile(
            "2026-09-08", self._fresh(), available_sources={"calendar"},
        )
        assert result[0]["name"] == "Daily sync"

    def test_revert_fields_restores_source_tracking(self, events_service):
        events_service.save_events("2026-09-08", [self._calendar_event()])
        events_service.update_event(
            "2026-09-08", "evt_1", {"name": "Standup"}, user_set_fields=["name"],
        )
        events_service.update_event("2026-09-08", "evt_1", {}, revert_fields=["name"])

        result = events_service.reconcile(
            "2026-09-08", self._fresh(), available_sources={"calendar"},
        )
        assert result[0]["name"] == "Daily sync"

    def test_revert_is_applied_before_the_calls_own_updates(self, events_service):
        """Naming a field in both reverts it and then pins the new value —
        the only reading under which one call cannot contradict itself."""
        events_service.save_events("2026-09-08", [self._calendar_event()])
        events_service.update_event(
            "2026-09-08", "evt_1", {"name": "Standup"}, user_set_fields=["name"],
        )
        events_service.update_event(
            "2026-09-08", "evt_1", {"name": "Morning sync"},
            user_set_fields=["name"], revert_fields=["name"],
        )
        result = events_service.reconcile(
            "2026-09-08", self._fresh(), available_sources={"calendar"},
        )
        assert result[0]["name"] == "Morning sync"


class TestIsComplete:
    def test_both_ends_is_complete(self):
        from src.services.events_service import is_complete
        assert is_complete({"start_time": "2026-09-08T10:00:00", "end_time": "2026-09-08T11:00:00"}) is True

    def test_missing_end_is_incomplete(self):
        from src.services.events_service import is_complete
        assert is_complete({"start_time": "2026-09-08T10:00:00", "end_time": None}) is False

    def test_missing_start_is_incomplete(self):
        from src.services.events_service import is_complete
        assert is_complete({"start_time": None, "end_time": "2026-09-08T11:00:00"}) is False

    def test_neither_is_incomplete(self):
        from src.services.events_service import is_complete
        assert is_complete({}) is False


class TestUpdateEventGuards:
    def test_inverted_interval_is_rejected_and_nothing_is_written(self, events_service):
        """Verified on c3ffcee: this used to persist start 21:00 / end 19:00
        / duration 0, which renders as `21:00–19:00` and counts for nothing."""
        events_service.create_event(
            date="2026-09-08", name="Gym",
            start_time="2026-09-08T18:00:00", end_time="2026-09-08T19:00:00",
        )
        event_id = events_service.get_events("2026-09-08")[0]["id"]

        result = events_service.update_event(
            "2026-09-08", event_id, {"start_time": "2026-09-08T21:00:00"},
        )

        assert "error" in result
        stored = events_service.get_events("2026-09-08")[0]
        assert stored["start_time"] == "2026-09-08T18:00:00"

    def test_zero_length_update_is_allowed(self, events_service):
        events_service.create_event(
            date="2026-09-08", name="Gym",
            start_time="2026-09-08T18:00:00", end_time="2026-09-08T19:00:00",
        )
        event_id = events_service.get_events("2026-09-08")[0]["id"]

        result = events_service.update_event(
            "2026-09-08", event_id, {"end_time": "2026-09-08T18:00:00"},
        )

        assert result.get("updated") is True

    def test_updates_dict_is_not_mutated(self, events_service):
        """A side effect on an argument. Harmless today because every caller
        builds the dict locally, which is exactly why it would surprise the
        first caller that does not."""
        events_service.create_event(
            date="2026-09-08", name="Gym", start_time="2026-09-08T18:00:00",
        )
        event_id = events_service.get_events("2026-09-08")[0]["id"]
        updates = {"end_time": "2026-09-08T19:00:00"}

        events_service.update_event("2026-09-08", event_id, updates)

        assert updates == {"end_time": "2026-09-08T19:00:00"}
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd apps/vault-server && ./venv/bin/python -m pytest tests/test_events_service.py -q -k "UserSet or IsComplete or UpdateEventGuards"
```

Expected: FAIL — `is_complete` cannot be imported, and `update_event` has no `user_set_fields` keyword.

- [ ] **Step 3: Add the module-level helpers**

In `apps/vault-server/src/services/events_service.py`, after `_DELETABLE_SOURCE_SYSTEMS` (line 47) and before `_date_part`:

```python
# The only fields a user can pin against re-inference.
#
# `completed` and `habit` are deliberately absent: `reconcile` re-derives
# both from checkbox and habit-log state on every merge, so a pinned value
# would be stale the instant the vault changed. `id`, `source_ids`, `state`,
# `photos` and `assets` are absent because they are already preserved by
# other means, and letting `user_set` reach them would turn a stray key into
# a way to rewrite reconciliation's own bookkeeping.
USER_SETTABLE_FIELDS = frozenset({
    "name", "start_time", "end_time", "location", "activity",
})


def is_complete(event: dict[str, Any]) -> bool:
    """Whether the event has enough to be drawn as a block.

    Derived, never stored: a status field that restates what the timestamps
    already say is a status field that goes stale, and the timestamps are
    right here.
    """
    return bool(event.get("start_time")) and bool(event.get("end_time"))


def apply_user_set(event: dict[str, Any]) -> None:
    """Re-apply the user's pinned fields over freshly merged values.

    Called at the end of `reconcile`'s matched branch, so the user gets the
    last word on the fields they set while every other field keeps tracking
    its source. Mutates in place.
    """
    pinned = event.get("user_set") or {}
    if not isinstance(pinned, dict):
        return

    moved_an_end = False
    for field, value in pinned.items():
        if field not in USER_SETTABLE_FIELDS:
            continue
        event[field] = value
        if field in ("start_time", "end_time"):
            moved_an_end = True

    if moved_an_end:
        start, end = event.get("start_time"), event.get("end_time")
        if start and end:
            try:
                from datetime import datetime as _dt
                delta = (_dt.fromisoformat(end) - _dt.fromisoformat(start)).total_seconds()
                event["duration_minutes"] = max(0, int(delta / 60))
            except (ValueError, TypeError):
                pass
```

- [ ] **Step 4: Default `user_set` in `save_events`**

In `save_events` (line ~126), add one line beside the existing defaults:

```python
            event.setdefault("tags", [])
            event.setdefault("state", "suggested")
            event.setdefault("user_set", {})
```

- [ ] **Step 5: Re-apply pins at the end of `reconcile`'s matched branch**

In `reconcile` (line ~488), immediately after `matched_existing["habit"] = fresh.get("habit")`:

```python
                matched_existing["completed"] = fresh.get("completed", False)
                matched_existing["habit"] = fresh.get("habit")
                # The user gets the last word. Everything above re-derives
                # from the source; this puts back the fields the user
                # explicitly set, and only those.
                apply_user_set(matched_existing)
                result.append(matched_existing)
```

- [ ] **Step 6: Teach `update_event` about pinning, reverting, and the interval guard**

In `update_event`, replace the signature and the body's opening so it no longer mutates its argument, applies `revert_fields` first, records `user_set_fields`, and rejects an inverted result. The signature becomes:

```python
    def update_event(
        self,
        date: str | None,
        event_id: str,
        updates: dict,
        new_date: str | None = None,
        user_set_fields: list[str] | None = None,
        revert_fields: list[str] | None = None,
    ) -> dict:
```

Immediately after the `source_date` resolution and before the loop, take a private copy:

```python
        source_date = self.resolve_event_date(event_id, date)
        if source_date is None:
            return {"error": f"Event {event_id} not found"}
        # Copy: this function re-dates timestamps and writes duration into
        # the mapping, and doing that to the caller's dict is a side effect
        # on an argument.
        updates = dict(updates)
        events = self.get_events(source_date)
```

Inside the matched-event branch, after the `new_date` re-dating block and before the duration recalculation, add the guard; then after `event.update(updates)`, maintain `user_set`:

```python
            # Reject an interval that ends before it starts. This used to
            # persist silently: `day_coverage` drops such a span so the
            # numbers stayed right, but `/day` rendered `21:00–19:00` and
            # the block counted for nothing.
            start = updates.get("start_time", event.get("start_time"))
            end = updates.get("end_time", event.get("end_time"))
            if start and end:
                from datetime import datetime as _dt
                try:
                    if _dt.fromisoformat(end) < _dt.fromisoformat(start):
                        return {
                            "error": (
                                f"End {end} is before start {start} — refusing to "
                                "write an inverted interval"
                            )
                        }
                except (ValueError, TypeError):
                    pass

            if "start_time" in updates or "end_time" in updates:
                if start and end and start != end:
                    from datetime import datetime as _dt
                    try:
                        st = _dt.fromisoformat(start)
                        et = _dt.fromisoformat(end)
                        updates["duration_minutes"] = max(0, int((et - st).total_seconds() / 60))
                    except (ValueError, TypeError):
                        pass

            event.update(updates)

            # Provenance. Revert first, then pin: naming a field in both
            # reverts it and pins the new value, which is the only reading
            # under which a single call cannot contradict itself.
            pinned = dict(event.get("user_set") or {})
            for field in revert_fields or []:
                pinned.pop(field, None)
            for field in user_set_fields or []:
                if field in USER_SETTABLE_FIELDS and field in updates:
                    pinned[field] = updates[field]
            event["user_set"] = pinned
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
cd apps/vault-server && ./venv/bin/python -m pytest tests/test_events_service.py -q
```

Expected: all pass, including the pre-existing `TestUpdateEventAcrossDates` and `TestDeleteEvent` classes.

- [ ] **Step 8: Run the full suite**

```bash
cd apps/vault-server && ./venv/bin/python -m pytest tests/ -q
```

Expected: `971 passed` (957 + 14).

- [ ] **Step 9: Commit**

```bash
git add apps/vault-server/src/services/events_service.py apps/vault-server/tests/test_events_service.py
git commit -m "feat(events): per-field provenance so edits survive re-inference"
```

---

### Task 3: Descriptive block addressing

**Files:**
- Create: `apps/vault-server/src/services/block_resolver.py`
- Test: `apps/vault-server/tests/test_block_resolver.py`

**Interfaces:**
- Consumes: `src.services.tool_response.{ok, err, ErrorCode}`.
- Produces: `resolve_block(reference: str, candidates: list[dict]) -> dict` — a `ToolResponse`. `ok` carries `{"id", "name", "date", "score"}`.

Candidates are event dicts that each additionally carry a `"date"` key naming the day file they came from; the caller supplies it (Task 5).

- [ ] **Step 1: Write the failing tests**

Create `apps/vault-server/tests/test_block_resolver.py`:

```python
"""Descriptive addressing: "the gym block", not `evt_7a8857a4`.

Mirrors `resolver.py`'s ladder deliberately — two resolvers that disagree
about what counts as ambiguous are two behaviours the user has to learn.
"""

from src.services.block_resolver import resolve_block


def block(id_, name, date="2026-09-08", start="2026-09-08T18:00:00"):
    return {"id": id_, "name": name, "date": date, "start_time": start}


class TestResolveBlock:
    def test_exact_id_wins(self):
        r = resolve_block("evt_1", [block("evt_1", "Gym"), block("evt_2", "Dinner")])
        assert r["ok"] is True
        assert r["data"]["id"] == "evt_1"
        assert r["data"]["score"] == 100.0

    def test_exact_name_wins(self):
        r = resolve_block("Gym", [block("evt_1", "Gym"), block("evt_2", "Dinner")])
        assert r["data"]["id"] == "evt_1"

    def test_unique_substring_matches(self):
        r = resolve_block("gym", [block("evt_1", "Gym session"), block("evt_2", "Dinner")])
        assert r["ok"] is True
        assert r["data"]["id"] == "evt_1"
        assert r["data"]["score"] == 95.0

    def test_multiple_substring_hits_are_ambiguous(self):
        r = resolve_block("walk", [
            block("evt_1", "Dog walk", start="2026-09-08T08:00:00"),
            block("evt_2", "Evening walk", start="2026-09-08T19:00:00"),
        ])
        assert r["ok"] is False
        assert r["error"]["code"] == "AMBIGUOUS_MATCH"
        assert len(r["error"]["details"]["candidates"]) == 2

    def test_candidates_carry_their_date(self):
        """Two days can both have a dog walk, and the reply has to be able
        to say which one it means."""
        r = resolve_block("dog walk", [
            block("evt_1", "Dog walk", date="2026-09-07"),
            block("evt_2", "Dog walk", date="2026-09-08"),
        ])
        assert r["ok"] is False
        dates = {c["date"] for c in r["error"]["details"]["candidates"]}
        assert dates == {"2026-09-07", "2026-09-08"}

    def test_fuzzy_match_above_the_floor(self):
        r = resolve_block("standup meeting", [block("evt_1", "Standup"), block("evt_2", "Lunch")])
        assert r["ok"] is True
        assert r["data"]["id"] == "evt_1"

    def test_below_the_floor_is_not_found(self):
        r = resolve_block("dentist", [block("evt_1", "Gym"), block("evt_2", "Lunch")])
        assert r["ok"] is False
        assert r["error"]["code"] == "PATH_NOT_FOUND"

    def test_empty_candidates_is_not_found(self):
        r = resolve_block("gym", [])
        assert r["ok"] is False
        assert r["error"]["code"] == "PATH_NOT_FOUND"

    def test_near_tie_is_ambiguous(self):
        r = resolve_block("review", [
            block("evt_1", "Review email"),
            block("evt_2", "Review notes"),
        ])
        assert r["ok"] is False
        assert r["error"]["code"] == "AMBIGUOUS_MATCH"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd apps/vault-server && ./venv/bin/python -m pytest tests/test_block_resolver.py -q
```

Expected: `ModuleNotFoundError: No module named 'src.services.block_resolver'`.

- [ ] **Step 3: Write the implementation**

Create `apps/vault-server/src/services/block_resolver.py`:

```python
"""Resolve a spoken reference — "the gym block" — to one event.

Mirrors `services/resolver.py`'s ladder and its `SCORE_AMBIGUOUS_DELTA`
deliberately. Two resolvers that disagree about what counts as ambiguous
are two behaviours the user has to learn, and the difference would show up
only in the rare case where being consistent matters most.

Candidates are event dicts that additionally carry a `date` key naming the
day file they came from. The caller supplies it, because an event dict on
its own does not know which day's reconciliation produced it — and a
candidate list spanning two days is the normal case here (§5 of the spec).
"""

from __future__ import annotations

from typing import Any

from rapidfuzz import fuzz

from src.services.tool_response import ErrorCode, err, ok

SCORE_AMBIGUOUS_DELTA = 10.0
SCORE_FLOOR = 60.0


def _summary(candidate: dict[str, Any], score: float) -> dict[str, Any]:
    return {
        "id": candidate.get("id", ""),
        "name": candidate.get("name", ""),
        "date": candidate.get("date", ""),
        "start_time": candidate.get("start_time"),
        "score": score,
    }


def resolve_block(reference: str, candidates: list[dict[str, Any]]) -> dict:
    """Resolve `reference` to a unique block among `candidates`."""
    if not candidates:
        return err(ErrorCode.PATH_NOT_FOUND, "No blocks available to match against")

    for candidate in candidates:
        if candidate.get("id") == reference:
            return ok(_summary(candidate, 100.0))

    for candidate in candidates:
        if candidate.get("name") == reference:
            return ok(_summary(candidate, 100.0))

    lowered = reference.lower()
    substring_hits = [
        c for c in candidates if lowered in (c.get("name") or "").lower()
    ]
    if len(substring_hits) == 1:
        return ok(_summary(substring_hits[0], 95.0))
    if len(substring_hits) > 1:
        return err(
            ErrorCode.AMBIGUOUS_MATCH,
            f"Several blocks match '{reference}'",
            details={
                "query": reference,
                "candidates": [_summary(c, 95.0) for c in substring_hits[:5]],
            },
        )

    ranked = sorted(
        (_summary(c, float(fuzz.token_set_ratio(reference, c.get("name") or "")))
         for c in candidates),
        key=lambda r: r["score"],
        reverse=True,
    )

    if ranked[0]["score"] < SCORE_FLOOR:
        return err(
            ErrorCode.PATH_NOT_FOUND,
            f"No block matched '{reference}'",
            details={"query": reference, "best_score": ranked[0]["score"]},
        )

    if len(ranked) > 1 and (ranked[0]["score"] - ranked[1]["score"]) < SCORE_AMBIGUOUS_DELTA:
        return err(
            ErrorCode.AMBIGUOUS_MATCH,
            f"Several blocks match '{reference}' similarly",
            details={"query": reference, "candidates": ranked[:5]},
        )

    return ok(ranked[0])
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd apps/vault-server && ./venv/bin/python -m pytest tests/test_block_resolver.py -q
```

Expected: `9 passed`.

- [ ] **Step 5: Run the full suite and commit**

```bash
cd apps/vault-server && ./venv/bin/python -m pytest tests/ -q
git add apps/vault-server/src/services/block_resolver.py apps/vault-server/tests/test_block_resolver.py
git commit -m "feat(events): resolve blocks by description"
```

Expected: `980 passed`.

---

### Task 4: Extract the merge pipeline and the async bridge

Two pure refactors, no behaviour change. They exist so Task 5 can make `list_events` return the day the user is looking at.

**Files:**
- Create: `apps/vault-server/src/services/day_assembly.py`, `apps/vault-server/src/services/async_bridge.py`
- Modify: `apps/vault-server/src/api/routes/events.py` (delete `_merge_from_sources`, import it), `apps/vault-server/src/services/hooks/sync_to_calendar.py` (delete `_maybe_await`, import it), `apps/vault-server/src/services/agent_service.py` (`_tool_delete_event`'s import)
- Test: `apps/vault-server/tests/test_day_assembly.py`

**Interfaces:**
- Produces:
  - `async merge_from_sources(date: datetime.date) -> tuple[list[dict], set[str]]` in `day_assembly.py` — byte-for-byte the body currently in `routes/events.py:21`.
  - `maybe_await(value)` in `async_bridge.py` — the body currently at `sync_to_calendar.py:45`, renamed without the leading underscore because it now has callers outside its own module.

- [ ] **Step 1: Create `async_bridge.py`**

```python
"""Run a coroutine from synchronous code.

Agent tool handlers are strictly synchronous — neither `tool_executor` nor
`parallel_executor` ever awaits one — but several of the services they call
(Google Calendar, the source merge) are async. Making the whole execution
path async is a much larger change than any single tool justifies, so the
handlers bridge instead.

This lived as `_maybe_await` inside `hooks/sync_to_calendar.py` and was
imported across module boundaries by `_tool_delete_event`, which is what a
shared helper looks like just before it gets a home.
"""

from __future__ import annotations

import asyncio
import concurrent.futures


def maybe_await(value):
    """If `value` is a coroutine, run it to completion; otherwise return it."""
    if asyncio.iscoroutine(value):
        try:
            return asyncio.run(value)
        except RuntimeError:
            # Already inside an event loop — run in a worker thread with
            # its own loop, which is the only way to block on a coroutine
            # from inside a running loop's own thread.
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                return ex.submit(asyncio.run, value).result()
    return value
```

- [ ] **Step 2: Point the old callers at it**

In `apps/vault-server/src/services/hooks/sync_to_calendar.py`, delete the `_maybe_await` definition (lines 45–56) and add near the other imports:

```python
from src.services.async_bridge import maybe_await as _maybe_await
```

The alias keeps the three existing call sites in that file unchanged. In `agent_service.py`'s `_tool_delete_event`, replace `from src.services.hooks.sync_to_calendar import _maybe_await` with `from src.services.async_bridge import maybe_await as _maybe_await`.

- [ ] **Step 3: Create `day_assembly.py`**

Move the entire `_merge_from_sources` function from `apps/vault-server/src/api/routes/events.py` (lines 21–117) into a new `apps/vault-server/src/services/day_assembly.py`, renamed to `merge_from_sources` and with its docstring preserved verbatim. Add this module docstring above it:

```python
"""Fan out to every source and merge one day's events.

Lived in `routes/events.py`, which made it reachable only from HTTP. The
agent's `list_events` needs the same day the `/day` view renders — reading
the raw persisted file instead is how `list_events` and `/day` came to
disagree about what exists.
"""
```

Move the `from src.services.habit_completion import ...` and `from src.services.merger_service import MergerService` imports with it.

- [ ] **Step 4: Import it back into the route**

In `apps/vault-server/src/api/routes/events.py`, replace the deleted function with:

```python
from src.services.day_assembly import merge_from_sources as _merge_from_sources
```

Keeping the underscored local name means the three call sites in that file are untouched, so this step cannot change routing behaviour.

- [ ] **Step 5: Write a test that pins the extraction**

Create `apps/vault-server/tests/test_day_assembly.py`:

```python
"""The merge is reachable from outside HTTP.

The point of the extraction is that the agent can call it. A test that only
went through the route would pass even if the import had been left behind.
"""

import datetime


def test_merge_from_sources_is_importable_as_a_service():
    from src.services.day_assembly import merge_from_sources
    assert callable(merge_from_sources)


def test_route_uses_the_extracted_function():
    from src.api.routes import events as events_route
    from src.services.day_assembly import merge_from_sources
    assert events_route._merge_from_sources is merge_from_sources


def test_maybe_await_runs_a_coroutine_from_sync_code():
    from src.services.async_bridge import maybe_await

    async def answer():
        return 42

    assert maybe_await(answer()) == 42


def test_maybe_await_passes_through_a_plain_value():
    from src.services.async_bridge import maybe_await
    assert maybe_await(42) == 42


def test_sync_to_calendar_hook_uses_the_shared_bridge():
    from src.services.async_bridge import maybe_await
    from src.services.hooks import sync_to_calendar
    assert sync_to_calendar._maybe_await is maybe_await
```

- [ ] **Step 6: Run the full suite**

```bash
cd apps/vault-server && ./venv/bin/python -m pytest tests/ -q
```

Expected: `985 passed`. A pure refactor — any pre-existing test that fails here means the move changed behaviour, so fix the move rather than the test.

- [ ] **Step 7: Commit**

```bash
git add apps/vault-server/src/services/day_assembly.py apps/vault-server/src/services/async_bridge.py \
        apps/vault-server/src/api/routes/events.py apps/vault-server/src/services/hooks/sync_to_calendar.py \
        apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_day_assembly.py
git commit -m "refactor(events): lift the source merge and async bridge into services"
```

---

### Task 5: `list_events` returns the reconciled day

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py` (`_tool_list_events`, line ~2704; its schema, line ~868)
- Test: `apps/vault-server/tests/test_agent_service.py`

**Interfaces:**
- Consumes: `merge_from_sources` and `maybe_await` (Task 4); `is_complete` (Task 2).
- Produces: `AgentService._reconciled_events(date: str) -> list[dict]` — every event carries a `"date"` key, which `resolve_block` (Task 3) requires and Task 6 relies on.

- [ ] **Step 1: Write the failing tests**

Append to `apps/vault-server/tests/test_agent_service.py`:

```python
class TestListEventsReconciles:
    """`list_events` must show the day `/day` shows.

    It used to read `EventsService.get_events` — the raw persisted file —
    while `/day` rendered a reconciled view that is deliberately not
    persisted. A calendar block the user was looking at could be entirely
    absent from what the agent saw.
    """

    def test_list_events_uses_the_reconciled_view(self, agent, mock_services):
        from unittest.mock import patch
        events_mock = mock_services[4]
        events_mock.reconcile.return_value = [{
            "id": "evt_1", "name": "Standup",
            "start_time": "2026-09-08T10:00:00", "end_time": "2026-09-08T10:30:00",
            "source": "calendar", "source_ids": {"calendar_id": "gcal_1"},
        }]

        async def fake_merge(date):
            return [], {"calendar"}

        with patch("src.services.day_assembly.merge_from_sources", fake_merge):
            result = agent._tool_list_events({"date": "2026-09-08"})

        assert result["ok"] is True
        assert result["data"]["events"][0]["name"] == "Standup"
        events_mock.reconcile.assert_called_once()
        # Reading must not write: `/day` navigation relies on that, and the
        # agent listing a day is the same kind of read.
        events_mock.refresh_events.assert_not_called()

    def test_listed_events_report_completeness(self, agent, mock_services):
        from unittest.mock import patch
        events_mock = mock_services[4]
        events_mock.reconcile.return_value = [
            {"id": "evt_1", "name": "Standup",
             "start_time": "2026-09-08T10:00:00", "end_time": "2026-09-08T10:30:00"},
            {"id": "evt_2", "name": "Dog walk",
             "start_time": None, "end_time": "2026-09-08T16:40:00"},
        ]

        async def fake_merge(date):
            return [], set()

        with patch("src.services.day_assembly.merge_from_sources", fake_merge):
            result = agent._tool_list_events({"date": "2026-09-08"})

        by_id = {e["id"]: e for e in result["data"]["events"]}
        assert by_id["evt_1"]["complete"] is True
        assert by_id["evt_2"]["complete"] is False

    def test_listed_events_carry_their_date(self, agent, mock_services):
        from unittest.mock import patch
        events_mock = mock_services[4]
        events_mock.reconcile.return_value = [
            {"id": "evt_1", "name": "Standup", "start_time": "2026-09-08T10:00:00",
             "end_time": "2026-09-08T10:30:00"},
        ]

        async def fake_merge(date):
            return [], set()

        with patch("src.services.day_assembly.merge_from_sources", fake_merge):
            result = agent._tool_list_events({"date": "2026-09-08"})

        assert result["data"]["events"][0]["date"] == "2026-09-08"

    def test_merge_failure_falls_back_to_the_persisted_store(self, agent, mock_services):
        """A source outage must degrade to the stored day, never to nothing:
        an empty list would read to the agent as 'that block does not
        exist', which is the shape of the denial bug Ship 3 fixed."""
        from unittest.mock import patch
        events_mock = mock_services[4]
        events_mock.get_events.return_value = [
            {"id": "evt_1", "name": "Standup",
             "start_time": "2026-09-08T10:00:00", "end_time": "2026-09-08T10:30:00"},
        ]

        async def boom(date):
            raise RuntimeError("calendar unreachable")

        with patch("src.services.day_assembly.merge_from_sources", boom):
            result = agent._tool_list_events({"date": "2026-09-08"})

        assert result["ok"] is True
        assert result["data"]["events"][0]["id"] == "evt_1"
        assert result["data"]["degraded"] is True
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd apps/vault-server && ./venv/bin/python -m pytest tests/test_agent_service.py -q -k TestListEventsReconciles
```

Expected: FAIL — `reconcile` is never called; `complete` and `date` are absent.

- [ ] **Step 3: Add `_reconciled_events` and rewrite the handler**

In `apps/vault-server/src/services/agent_service.py`, replace `_tool_list_events` (line ~2704) with:

```python
    def _reconciled_events(self, date: str) -> tuple[list[dict], bool]:
        """The day as `/day` renders it, plus whether it is degraded.

        Merges from every source and reconciles against the persisted
        store — but does not persist. Reading a day must not rewrite it;
        that is Ship 2's rule and it applies to the agent looking at a day
        exactly as it applies to the user browsing one.

        On a source failure this falls back to the persisted store rather
        than to an empty list. An empty list would read to the agent as
        "that block does not exist", which is the shape of the 2026-08-20
        denial bug — a temporary outage must not become a confident denial.
        Every event carries a `date` key, which `resolve_block` needs.
        """
        import datetime as dt

        degraded = False
        try:
            from src.services.async_bridge import maybe_await
            import src.services.day_assembly as day_assembly
            fresh, available = maybe_await(
                day_assembly.merge_from_sources(dt.date.fromisoformat(date))
            )
            events = self.events.reconcile(date, fresh, available)
        except Exception as e:
            logger.warning(f"Falling back to the persisted store for {date}: {e}")
            events = self.events.get_events(date)
            degraded = True

        for event in events:
            event["date"] = date
        return events, degraded

    def _tool_list_events(self, params: dict) -> dict:
        import datetime as dt
        from src.services.events_service import is_complete

        date = params.get("date", dt.date.today().isoformat())
        if not self.events:
            return err(ErrorCode.EXTERNAL_FAILURE, "Events service not available")

        events, degraded = self._reconciled_events(date)
        summary = []
        for e in events:
            summary.append({
                "id": e["id"],
                "date": date,
                "name": e["name"],
                "type": e.get("type", "unknown"),
                "start_time": e.get("start_time"),
                "end_time": e.get("end_time"),
                "location": e.get("location"),
                "activity": e.get("activity"),
                "complete": is_complete(e),
                "logical_id": e.get("logical_id"),
                "photo_count": len(e.get("photos", [])),
                "source": e.get("source"),
            })
        result = {"events": summary, "date": date}
        if degraded:
            result["degraded"] = True
        return ok(result)
```

Note `import src.services.day_assembly as day_assembly` rather than `from … import merge_from_sources`: the tests patch the module attribute, and a `from` import would bind the original function before the patch takes effect.

- [ ] **Step 4: Update the tool's description**

In `_register_tools`, replace `list_events`'s description (line ~846):

```python
                    "description": (
                        "List a day's events exactly as /day shows them — calendar, "
                        "timeline, timed checkboxes and scheduled habits, merged. "
                        "Each row carries `complete`: false means the block is missing "
                        "a start or an end time. Reaches the calendar, so it is not free."
                    ),
```

- [ ] **Step 5: Run the tests and the full suite**

```bash
cd apps/vault-server && ./venv/bin/python -m pytest tests/ -q
```

Expected: `989 passed`.

- [ ] **Step 6: Commit**

```bash
git add apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_agent_service.py
git commit -m "feat(agent): list_events returns the day /day renders"
```

---

### Task 6: `create_event` and `update_event` speak intervals and references

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py` (`create_event`/`update_event` schemas, lines ~889–1005; `_tool_create_event` ~2743; `_tool_update_event` ~2887; `_tool_delete_event` ~2969)
- Test: `apps/vault-server/tests/test_agent_service.py`

**Interfaces:**
- Consumes: `derive_interval`, `crosses_midnight`, `split_at_midnight` (Task 1); `USER_SETTABLE_FIELDS` (Task 2); `resolve_block` (Task 3); `_reconciled_events` (Task 5).
- Produces: `AgentService._resolve_reference(params) -> dict` — a `ToolResponse` whose `ok` data is `{"event_id", "date"}`; used by both write tools.

- [ ] **Step 1: Write the failing tests**

Append to `apps/vault-server/tests/test_agent_service.py`:

```python
class TestCreateEventIntervals:
    def test_start_and_duration_derives_the_end(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.create_event.return_value = {"id": "evt_1", "path": "data/events/2026-09-08.json"}
        agent.calendar = None

        agent._tool_create_event({
            "name": "Dog walk", "date": "2026-09-08",
            "start_time": "16:00", "duration_minutes": 40,
        })

        kwargs = events_mock.create_event.call_args.kwargs
        assert kwargs["start_time"] == "2026-09-08T16:00:00"
        assert kwargs["end_time"] == "2026-09-08T16:40:00"

    def test_end_and_duration_derives_the_start(self, agent, mock_services):
        """'Just got back from the 40-minute dog walk.'"""
        events_mock = mock_services[4]
        events_mock.create_event.return_value = {"id": "evt_1", "path": "p"}
        agent.calendar = None

        agent._tool_create_event({
            "name": "Dog walk", "date": "2026-09-08",
            "end_time": "16:40", "duration_minutes": 40,
        })

        kwargs = events_mock.create_event.call_args.kwargs
        assert kwargs["start_time"] == "2026-09-08T16:00:00"

    def test_contradictory_values_are_rejected(self, agent, mock_services):
        events_mock = mock_services[4]
        agent.calendar = None

        result = agent._tool_create_event({
            "name": "Gym", "date": "2026-09-08",
            "start_time": "18:00", "end_time": "19:00", "duration_minutes": 90,
        })

        assert result["ok"] is False
        assert result["error"]["code"] == "SCHEMA_INVALID"
        events_mock.create_event.assert_not_called()

    def test_one_endpoint_creates_an_incomplete_block(self, agent, mock_services):
        """'Just got back from the dog walk' — the end is now, the start is
        unknown, and inventing one is how a block gets shifted by its own
        length."""
        events_mock = mock_services[4]
        events_mock.create_event.return_value = {"id": "evt_1", "path": "p"}
        agent.calendar = None

        result = agent._tool_create_event({
            "name": "Dog walk", "date": "2026-09-08", "end_time": "16:40",
        })

        kwargs = events_mock.create_event.call_args.kwargs
        assert kwargs["start_time"] is None
        assert kwargs["end_time"] == "2026-09-08T16:40:00"
        assert result["data"]["complete"] is False
        assert result["data"]["calendar_sync"]["reason"] == "incomplete"

    def test_name_is_the_only_required_field(self, agent):
        schema = agent.tools["create_event"]["schema"]["input_schema"]
        assert schema["required"] == ["name"]
        assert "duration_minutes" in schema["properties"]


class TestCreateEventMidnight:
    def test_sleep_splits_into_two_fragments(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.create_event.side_effect = [
            {"id": "evt_a", "path": "data/events/2026-09-08.json"},
            {"id": "evt_b", "path": "data/events/2026-09-09.json"},
        ]
        agent.calendar = None

        result = agent._tool_create_event({
            "name": "Sleep", "date": "2026-09-08",
            "start_time": "23:30", "end_time": "07:15",
        })

        assert events_mock.create_event.call_count == 2
        first, second = [c.kwargs for c in events_mock.create_event.call_args_list]
        assert first["date"] == "2026-09-08"
        assert first["start_time"] == "2026-09-08T23:30:00"
        assert first["end_time"] == "2026-09-08T23:59:59"
        assert second["date"] == "2026-09-09"
        assert second["start_time"] == "2026-09-09T00:00:00"
        assert second["end_time"] == "2026-09-09T07:15:00"
        assert first["logical_id"] == second["logical_id"]
        assert result["data"]["calendar_sync"]["reason"] == "crosses_midnight"
        assert result["data"]["calendar_sync"]["attempted"] is False


class TestUpdateEventShiftAndReference:
    def test_shift_minutes_moves_both_ends(self, agent, mock_services):
        """'Move gym -30m'. A start-only update stretches the block instead
        — verified on c3ffcee: 18:00-19:00 became 17:30-19:00, 90 minutes."""
        events_mock = mock_services[4]
        events_mock.resolve_event_date.return_value = "2026-09-08"
        events_mock.get_events.return_value = [{
            "id": "evt_1", "name": "Gym",
            "start_time": "2026-09-08T18:00:00", "end_time": "2026-09-08T19:00:00",
        }]
        events_mock.update_event.return_value = {"updated": True, "event": {}, "date": "2026-09-08"}
        events_mock._file_path.side_effect = lambda d: f"data/events/{d}.json"
        agent.calendar = None

        agent._tool_update_event({"event_id": "evt_1", "shift_minutes": -30})

        updates = events_mock.update_event.call_args.kwargs["updates"]
        assert updates["start_time"] == "2026-09-08T17:30:00"
        assert updates["end_time"] == "2026-09-08T18:30:00"

    def test_shift_on_an_incomplete_block_is_rejected(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.resolve_event_date.return_value = "2026-09-08"
        events_mock.get_events.return_value = [{
            "id": "evt_1", "name": "Dog walk",
            "start_time": None, "end_time": "2026-09-08T16:40:00",
        }]
        agent.calendar = None

        result = agent._tool_update_event({"event_id": "evt_1", "shift_minutes": -30})

        assert result["ok"] is False
        assert result["error"]["code"] == "SCHEMA_INVALID"
        events_mock.update_event.assert_not_called()

    def test_edited_fields_are_pinned(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.resolve_event_date.return_value = "2026-09-08"
        events_mock.get_events.return_value = [{"id": "evt_1", "name": "Daily sync"}]
        events_mock.update_event.return_value = {"updated": True, "event": {}, "date": "2026-09-08"}
        events_mock._file_path.side_effect = lambda d: f"data/events/{d}.json"
        agent.calendar = None

        agent._tool_update_event({"event_id": "evt_1", "name": "Standup"})

        assert events_mock.update_event.call_args.kwargs["user_set_fields"] == ["name"]

    def test_revert_fields_are_forwarded(self, agent, mock_services):
        events_mock = mock_services[4]
        events_mock.resolve_event_date.return_value = "2026-09-08"
        events_mock.get_events.return_value = [{"id": "evt_1", "name": "Standup"}]
        events_mock.update_event.return_value = {"updated": True, "event": {}, "date": "2026-09-08"}
        events_mock._file_path.side_effect = lambda d: f"data/events/{d}.json"
        agent.calendar = None

        agent._tool_update_event({"event_id": "evt_1", "revert_fields": ["name"]})

        assert events_mock.update_event.call_args.kwargs["revert_fields"] == ["name"]

    def test_block_reference_materialises_the_day(self, agent, mock_services):
        """An inferred block has no row to update. The edit is explicit
        write intent, so persisting the reconciled day here is correct —
        unlike navigation, which must never write."""
        from unittest.mock import patch
        events_mock = mock_services[4]
        events_mock.reconcile.return_value = [{
            "id": "evt_gym", "name": "Gym",
            "start_time": "2026-09-08T18:00:00", "end_time": "2026-09-08T19:00:00",
        }]
        events_mock.update_event.return_value = {"updated": True, "event": {}, "date": "2026-09-08"}
        events_mock._file_path.side_effect = lambda d: f"data/events/{d}.json"
        agent.calendar = None

        async def fake_merge(date):
            return [], {"calendar"}

        with patch("src.services.day_assembly.merge_from_sources", fake_merge):
            agent._tool_update_event({"block_reference": "gym", "name": "Workout"})

        events_mock.refresh_events.assert_called_once()
        assert events_mock.update_event.call_args.kwargs["event_id"] == "evt_gym"

    def test_ambiguous_reference_surfaces_candidates(self, agent, mock_services):
        from unittest.mock import patch
        events_mock = mock_services[4]
        events_mock.reconcile.return_value = [
            {"id": "evt_1", "name": "Dog walk", "start_time": "2026-09-08T08:00:00"},
            {"id": "evt_2", "name": "Evening walk", "start_time": "2026-09-08T19:00:00"},
        ]

        async def fake_merge(date):
            return [], set()

        with patch("src.services.day_assembly.merge_from_sources", fake_merge):
            result = agent._tool_update_event({"block_reference": "walk", "name": "X"})

        assert result["ok"] is False
        assert result["error"]["code"] == "AMBIGUOUS_MATCH"
        events_mock.update_event.assert_not_called()

    def test_reference_searches_the_selected_date_and_today(self, agent, mock_services):
        """A stale hint only matters when the block exists on that day and
        nowhere else, because both days are searched."""
        from unittest.mock import patch
        events_mock = mock_services[4]
        events_mock.reconcile.return_value = []

        async def fake_merge(date):
            return [], set()

        with patch("src.services.day_assembly.merge_from_sources", fake_merge):
            agent._tool_update_event({
                "block_reference": "gym", "name": "X", "selected_date": "2026-08-20",
            })

        searched = {c.args[0] for c in events_mock.reconcile.call_args_list}
        assert "2026-08-20" in searched
        assert len(searched) == 2

    def test_delete_event_accepts_a_reference(self, agent, mock_services):
        from unittest.mock import patch
        events_mock = mock_services[4]
        events_mock.reconcile.return_value = [
            {"id": "evt_dup", "name": "Lunch", "start_time": "2026-09-08T13:00:00",
             "source_ids": {}},
        ]
        events_mock.resolve_event_date.return_value = "2026-09-08"
        events_mock.get_events.return_value = [
            {"id": "evt_dup", "name": "Lunch", "source_ids": {}},
        ]
        events_mock.delete_event.return_value = {
            "deleted": True, "event": {"name": "Lunch"}, "date": "2026-09-08",
        }
        events_mock._file_path.side_effect = lambda d: f"data/events/{d}.json"
        agent.calendar = None

        async def fake_merge(date):
            return [], set()

        with patch("src.services.day_assembly.merge_from_sources", fake_merge):
            result = agent._tool_delete_event({"block_reference": "lunch"})

        assert result["ok"] is True
        assert events_mock.delete_event.call_args.kwargs["event_id"] == "evt_dup"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd apps/vault-server && ./venv/bin/python -m pytest tests/test_agent_service.py -q \
  -k "CreateEventIntervals or CreateEventMidnight or UpdateEventShiftAndReference"
```

Expected: FAIL — no `duration_minutes`, no `shift_minutes`, no `block_reference`.

- [ ] **Step 3: Update the three tool schemas**

In `_register_tools`, `create_event`'s properties gain `duration_minutes` and lose the `start_time` requirement:

```python
                            "start_time": {"type": "string", "description": "Start time ISO or HH:MM"},
                            "end_time": {"type": "string", "description": "End time ISO or HH:MM"},
                            "duration_minutes": {
                                "type": "integer",
                                "description": (
                                    "How long it lasted, in minutes. Supply any TWO of "
                                    "start_time / end_time / duration_minutes and the third "
                                    "is computed — never work it out yourself. Supply only "
                                    "one and the block is created incomplete, which is the "
                                    "right outcome for 'just got back from the dog walk': "
                                    "record the end, leave the start empty, and ask."
                                ),
                            },
```

with `"required": ["name"]`.

`update_event` gains three properties:

```python
                            "block_reference": {
                                "type": "string",
                                "description": (
                                    "Name the block instead of its ID — 'the gym block', "
                                    "'dog walk'. Searched across the day being viewed and "
                                    "today. Use this OR event_id."
                                ),
                            },
                            "shift_minutes": {
                                "type": "integer",
                                "description": (
                                    "Move the whole block by this many minutes, negative to "
                                    "move earlier. Use this for 'move gym -30m' — setting "
                                    "start_time alone stretches the block instead of moving it."
                                ),
                            },
                            "revert_fields": {
                                "type": "array", "items": {"type": "string"},
                                "description": (
                                    "Stop pinning these fields, so they track their source "
                                    "again. For 'use the calendar's name for that'."
                                ),
                            },
```

with `"required": []`. `delete_event` gains the same `block_reference` property and `"required": []`.

- [ ] **Step 4: Add the shared reference resolver**

In `agent_service.py`, above `_tool_create_event`:

```python
    def _resolve_reference(self, params: dict) -> dict:
        """Turn `event_id` or `block_reference` into a concrete event id.

        A `block_reference` is resolved against the reconciled view of the
        day being viewed and today — an inferred block has no persisted row
        yet, so the day is materialised (`refresh_events`) before the write
        proceeds. Persisting here is correct: an explicit edit is write
        intent, unlike navigation, which Ship 2 deliberately made read-only.
        """
        import datetime as dt
        from src.services.block_resolver import resolve_block

        event_id = params.get("event_id")
        if event_id:
            date = self.events.resolve_event_date(event_id, params.get("date"))
            if date is None:
                return err(
                    ErrorCode.PATH_NOT_FOUND,
                    f"Event {event_id} not found",
                    details={"event_id": event_id},
                )
            return ok({"event_id": event_id, "date": date})

        reference = params.get("block_reference")
        if not reference:
            return err(
                ErrorCode.SCHEMA_INVALID,
                "Supply either event_id or block_reference",
            )

        today = dt.date.today().isoformat()
        dates = [d for d in dict.fromkeys([params.get("selected_date"), today]) if d]

        candidates: list[dict] = []
        for date in dates:
            events, _ = self._reconciled_events(date)
            candidates.extend(events)

        resolved = resolve_block(reference, candidates)
        if not resolved["ok"]:
            return resolved

        # Materialise: the resolved block may exist only as inference.
        target_date = resolved["data"]["date"]
        try:
            from src.services.async_bridge import maybe_await
            import src.services.day_assembly as day_assembly
            fresh, available = maybe_await(
                day_assembly.merge_from_sources(dt.date.fromisoformat(target_date))
            )
            self.events.refresh_events(target_date, fresh, available)
        except Exception as e:
            logger.warning(f"Could not materialise {target_date} before editing: {e}")

        return ok({"event_id": resolved["data"]["id"], "date": target_date})
```

- [ ] **Step 5: Rewrite `_tool_create_event`'s time handling**

Replace the `_normalize_time` / `start_time` / `end_time` block at the top of `_tool_create_event` with:

```python
        from src.services.interval import (
            crosses_midnight, derive_interval, split_at_midnight,
        )

        derived = derive_interval(
            params.get("start_time"),
            params.get("end_time"),
            params.get("duration_minutes"),
            date,
        )
        if not derived["ok"]:
            return err(ErrorCode.SCHEMA_INVALID, derived["error"])

        start_time = derived["start_time"]
        end_time = derived["end_time"]
        complete = bool(start_time and end_time)
        spans_midnight = complete and crosses_midnight(start_time, end_time)
```

Guard the calendar-sync block so it is skipped for an incomplete or midnight-spanning event, inserting these two branches ahead of the existing `if params.get("photo_path")` branch:

```python
        if not complete:
            calendar_sync = {"ok": False, "attempted": False, "reason": "incomplete"}
        elif spans_midnight:
            # Google stores this natively as one event, which would then hand
            # a single fresh event to two per-day fragments on the next
            # merge. Deferred rather than guessed at.
            calendar_sync = {"ok": False, "attempted": False, "reason": "crosses_midnight"}
        elif params.get("photo_path"):
```

Replace the single `self.events.create_event(...)` call with a loop over fragments:

```python
        from uuid import uuid4
        fragments = split_at_midnight(start_time, end_time) if spans_midnight else [(start_time, end_time)]
        # A shared id so Ship 5 can approve both halves of one night's sleep
        # at once. Written now because the link is unrecoverable later;
        # nothing in this ship branches on it.
        logical_id = uuid4().hex[:8] if len(fragments) > 1 else None

        created = []
        items = []
        for frag_start, frag_end in fragments:
            frag_date = (frag_start or frag_end or f"{date}T00:00:00")[:10]
            frag = self.events.create_event(
                date=frag_date,
                name=params["name"],
                start_time=frag_start,
                end_time=frag_end,
                location=params.get("location"),
                activity=_event_activity(params),
                photo_path=params.get("photo_path"),
                caption=params.get("caption"),
                wikilinks=params.get("wikilinks"),
                source_ids=source_ids,
                logical_id=logical_id,
            )
            created.append(frag)
            items.append(frag["path"])

        result = dict(created[0])
        result["event_id"] = result.pop("id")
        result["complete"] = complete
        if len(created) > 1:
            result["fragments"] = [c["id"] for c in created]
            result["logical_id"] = logical_id
```

`EventsService.create_event` gains a `logical_id: str | None = None` keyword that it stores on the event; add it to that method's signature and to the dict it builds.

- [ ] **Step 6: Rewrite `_tool_update_event`'s opening and `_tool_delete_event`'s**

Replace `_tool_update_event`'s date resolution with the shared resolver and add `shift_minutes`:

```python
    def _tool_update_event(self, params: dict) -> dict:
        if not self.events:
            return err(ErrorCode.EXTERNAL_FAILURE, "Events service not available")

        resolved = self._resolve_reference(params)
        if not resolved["ok"]:
            return resolved
        event_id = resolved["data"]["event_id"]
        current_date = resolved["data"]["date"]

        new_date = params.get("new_date")
        date = new_date or current_date

        shift = params.get("shift_minutes")
        if shift:
            import datetime as _dt
            from src.services.events_service import is_complete
            event = next(
                (e for e in self.events.get_events(current_date) if e["id"] == event_id), {}
            )
            if not is_complete(event):
                return err(
                    ErrorCode.SCHEMA_INVALID,
                    "Cannot shift a block that is missing a start or end time",
                    details={"event_id": event_id},
                )
            delta = _dt.timedelta(minutes=shift)
            for field in ("start_time", "end_time"):
                moved = _dt.datetime.fromisoformat(event[field]) + delta
                params[field] = moved.strftime("%Y-%m-%dT%H:%M:%S")
```

The existing `_normalize_time` and `updates` construction follow unchanged. After `updates` is built, forward the provenance arguments:

```python
        # Every field the user names in an edit is a field they have now
        # claimed: without pinning, the next merge puts the source's value
        # back and the edit silently disappears.
        user_set_fields = [f for f in updates if f in USER_SETTABLE_FIELDS]

        result = self.events.update_event(
            date=current_date,
            event_id=event_id,
            updates=updates,
            new_date=new_date,
            user_set_fields=user_set_fields,
            revert_fields=params.get("revert_fields"),
        )
```

with `from src.services.events_service import USER_SETTABLE_FIELDS` at the top of the method. `_tool_delete_event`'s opening likewise becomes:

```python
        resolved = self._resolve_reference(params)
        if not resolved["ok"]:
            return resolved
        event_id = resolved["data"]["event_id"]
        date = resolved["data"]["date"]
```

replacing its own `resolve_event_date` call.

- [ ] **Step 7: Run the full suite**

```bash
cd apps/vault-server && ./venv/bin/python -m pytest tests/ -q
```

Expected: `1002 passed`.

- [ ] **Step 8: Commit**

```bash
git add apps/vault-server/src/services/agent_service.py apps/vault-server/src/services/events_service.py \
        apps/vault-server/tests/test_agent_service.py
git commit -m "feat(agent): intervals, midnight splits, shift and descriptive references"
```

---

### Task 7: Calendar updates and ownership

**Files:**
- Modify: `apps/vault-server/src/services/calendar_service.py` (add `update_event` after `create_event`, line ~511), `apps/vault-server/src/services/merger_service.py` (`MergedEvent.calendar`; `_create_calendar_event` ~line 278 and `_create_merged_event` ~line 262), `apps/vault-server/src/services/agent_service.py` (sync on update)
- Test: `apps/vault-server/tests/test_calendar_service.py`, `apps/vault-server/tests/test_merger_service.py`, `apps/vault-server/tests/test_agent_service.py`

**Interfaces:**
- Produces: `async CalendarService.update_event(event_id: str, name: str | None = None, date: str | None = None, start_time: str | None = None, end_time: str | None = None) -> bool`; `MergedEvent.calendar: str | None`.

- [ ] **Step 1: Write the failing tests**

Append to `apps/vault-server/tests/test_merger_service.py`:

```python
class TestCalendarOwnership:
    """Which calendar an event came from must survive the merge.

    `get_todays_events_with_status` returns `'calendar': cal['name']` per
    event and `_calendar_source_ids` dropped it, so Mazkir could not tell
    its own events from the ones it must not write to without asking Google
    and reading a 404.
    """

    def test_calendar_name_is_carried_onto_the_merged_event(self):
        from src.services.merger_service import MergerService
        merger = MergerService(timezone="Asia/Jerusalem")
        events = merger.merge(
            calendar_events=[{
                "id": "gcal_1", "summary": "Standup", "calendar": "Mazkir",
                "start": "2026-09-08T10:00:00", "end": "2026-09-08T10:30:00",
            }],
            timeline_data={"visits": [], "activities": []},
            habits=[], daily_body="", date="2026-09-08",
        )
        assert events[0].calendar == "Mazkir"

    def test_absent_calendar_name_is_none_not_a_crash(self):
        from src.services.merger_service import MergerService
        merger = MergerService(timezone="Asia/Jerusalem")
        events = merger.merge(
            calendar_events=[{
                "id": "gcal_1", "summary": "Standup",
                "start": "2026-09-08T10:00:00", "end": "2026-09-08T10:30:00",
            }],
            timeline_data={"visits": [], "activities": []},
            habits=[], daily_body="", date="2026-09-08",
        )
        assert events[0].calendar is None
```

Append to `apps/vault-server/tests/test_agent_service.py`:

```python
class TestUpdateEventCalendarSync:
    def _stored(self, **over):
        base = {
            "id": "evt_1", "name": "Standup",
            "start_time": "2026-09-08T10:00:00", "end_time": "2026-09-08T10:30:00",
            "source_ids": {"calendar_id": "gcal_1"}, "calendar": "Mazkir",
        }
        base.update(over)
        return base

    def _wire(self, mock_services, stored):
        events_mock = mock_services[4]
        events_mock.resolve_event_date.return_value = "2026-09-08"
        events_mock.get_events.return_value = [stored]
        events_mock.update_event.return_value = {
            "updated": True, "event": stored, "date": "2026-09-08",
        }
        events_mock._file_path.side_effect = lambda d: f"data/events/{d}.json"
        return events_mock

    def test_edit_patches_the_google_entry(self, agent, mock_services):
        """Without this the ledger changes, Google does not, and the next
        merge puts the old value back."""
        from unittest.mock import AsyncMock
        self._wire(mock_services, self._stored())
        agent.calendar.is_initialized = True
        agent.calendar.update_event = AsyncMock(return_value=True)

        result = agent._tool_update_event({"event_id": "evt_1", "name": "Morning sync"})

        agent.calendar.update_event.assert_awaited_once()
        assert result["data"]["calendar_sync"]["ok"] is True

    def test_event_in_another_calendar_is_not_patched(self, agent, mock_services):
        from unittest.mock import AsyncMock
        self._wire(mock_services, self._stored(calendar="Work"))
        agent.calendar.is_initialized = True
        agent.calendar.update_event = AsyncMock(return_value=True)

        result = agent._tool_update_event({"event_id": "evt_1", "name": "X"})

        agent.calendar.update_event.assert_not_awaited()
        assert result["data"]["calendar_sync"]["reason"] == "not_in_mazkir_calendar"

    def test_incomplete_block_is_not_synced(self, agent, mock_services):
        from unittest.mock import AsyncMock
        self._wire(mock_services, self._stored(end_time=None, source_ids={}))
        agent.calendar.is_initialized = True
        agent.calendar.create_event = AsyncMock(return_value="gcal_new")

        result = agent._tool_update_event({"event_id": "evt_1", "name": "X"})

        agent.calendar.create_event.assert_not_awaited()
        assert result["data"]["calendar_sync"]["reason"] == "incomplete"

    def test_completing_a_block_creates_its_calendar_entry(self, agent, mock_services):
        """'Sync it once it's complete' needs no flag: the absence of a
        calendar_id already records that it is not in the calendar yet."""
        from unittest.mock import AsyncMock
        stored = self._stored(source_ids={}, calendar=None)
        events_mock = self._wire(mock_services, stored)
        events_mock.update_event.return_value = {
            "updated": True, "event": stored, "date": "2026-09-08",
        }
        agent.calendar.is_initialized = True
        agent.calendar.create_event = AsyncMock(return_value="gcal_new")

        result = agent._tool_update_event({
            "event_id": "evt_1", "end_time": "2026-09-08T10:30:00",
        })

        agent.calendar.create_event.assert_awaited_once()
        assert result["data"]["calendar_sync"]["event_id"] == "gcal_new"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd apps/vault-server && ./venv/bin/python -m pytest tests/ -q \
  -k "TestCalendarOwnership or TestUpdateEventCalendarSync"
```

Expected: FAIL — `MergedEvent` has no `calendar`; `CalendarService` has no `update_event`.

- [ ] **Step 3: Add `calendar` to `MergedEvent` and populate it**

In `merger_service.py`, in the `MergedEvent` model beside `source_ids`:

```python
    # Which Google calendar this came from, by display name. Mazkir writes
    # only to its own calendar (`calendarId=self._calendar_id` on every
    # write), so knowing the owner up front is what lets an edit report
    # "not in Mazkir's calendar" instead of issuing a doomed API call and
    # reading a 404 as an unexplained failure.
    calendar: str | None = None
```

In both `_create_calendar_event` and `_create_merged_event`, add `calendar=cal.get("calendar")` beside `source_ids=_calendar_source_ids(cal)`.

- [ ] **Step 4: Add `CalendarService.update_event`**

After `create_event` (line ~511) in `calendar_service.py`:

```python
    async def update_event(
        self,
        event_id: str,
        name: str | None = None,
        date: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> bool:
        """Patch an existing event in Mazkir's own calendar.

        The one write `CalendarService` was missing. Without it an edit made
        by talking changed the ledger and never reached Google — and then
        the next merge read the unchanged Google values back over the edit.

        Only the supplied fields are sent, so a rename does not have to
        restate the times.
        """
        if not self._initialized or not self._calendar_id:
            logger.error("Calendar service not properly initialized")
            return False

        body: Dict = {}
        if name is not None:
            body["summary"] = name
        if start_time is not None:
            body["start"] = {"dateTime": start_time, "timeZone": self.timezone}
        if end_time is not None:
            body["end"] = {"dateTime": end_time, "timeZone": self.timezone}
        if not body:
            return True

        try:
            self._service.events().patch(
                calendarId=self._calendar_id,
                eventId=event_id,
                body=body,
            ).execute()
            logger.info(f"Updated event: {event_id}")
            return True
        except HttpError as e:
            logger.error(f"Failed to update event: {e}")
            return False
```

`self.timezone` is the attribute the rest of the class uses for exactly this (see `_build_event` and `_build_habit_event`) — not `_timezone`.

- [ ] **Step 5: Sync from `_tool_update_event`**

After the `self.events.update_event(...)` call succeeds and before the existing `moved_from` handling, add:

```python
        # Push the edit upstream. The ledger holding the change is only half
        # of it: an un-propagated source value gets merged back over the
        # edit on the very next read.
        stored = result.get("event") or {}
        calendar_id = (stored.get("source_ids") or {}).get("calendar_id")
        owning = stored.get("calendar")
        from src.services.events_service import is_complete

        if not is_complete(stored):
            result["calendar_sync"] = {"ok": False, "attempted": False, "reason": "incomplete"}
        elif not self.calendar or not getattr(self.calendar, "is_initialized", False):
            result["calendar_sync"] = {
                "ok": False, "attempted": False, "reason": "calendar_not_configured",
            }
        elif calendar_id and owning not in (None, "Mazkir"):
            result["calendar_sync"] = {
                "ok": False, "attempted": False, "reason": "not_in_mazkir_calendar",
            }
        else:
            from src.services.async_bridge import maybe_await
            try:
                if calendar_id:
                    pushed = maybe_await(self.calendar.update_event(
                        event_id=calendar_id,
                        name=stored.get("name"),
                        start_time=stored.get("start_time"),
                        end_time=stored.get("end_time"),
                    ))
                    result["calendar_sync"] = {
                        "ok": bool(pushed), "attempted": True, "event_id": calendar_id,
                    }
                else:
                    gcal_id = maybe_await(self.calendar.create_event(
                        name=stored.get("name"),
                        date=stored_date,
                        start_time=(stored.get("start_time") or "")[11:16],
                        end_time=(stored.get("end_time") or "")[11:16] or None,
                    ))
                    result["calendar_sync"] = {
                        "ok": bool(gcal_id), "attempted": True, "event_id": gcal_id,
                    }
            except Exception as e:
                logger.warning(f"Failed to sync event edit to Google Calendar: {e}")
                result["calendar_sync"] = {"ok": False, "attempted": True, "reason": str(e)}
```

The existing `moved_from` branch keeps its own `calendar_sync` assignment and must run *after* this one, so a cross-date move still reports `cross_date_move_not_supported` rather than being overwritten.

- [ ] **Step 6: Run the full suite**

```bash
cd apps/vault-server && ./venv/bin/python -m pytest tests/ -q
```

Expected: `1008 passed`.

- [ ] **Step 7: Commit**

```bash
git add apps/vault-server/src/services/calendar_service.py apps/vault-server/src/services/merger_service.py \
        apps/vault-server/src/services/agent_service.py apps/vault-server/tests/
git commit -m "feat(calendar): patch Google entries on edit, and know which calendar owns them"
```

---

### Task 8: `/daily` returns incomplete blocks

**Files:**
- Modify: `apps/vault-server/src/api/routes/daily.py` (`DailyResponse`, `_build_blocks_and_coverage`)
- Modify: `packages/shared-types/src/daily.ts`
- Test: `apps/vault-server/tests/test_daily_route.py`

**Interfaces:**
- Produces: `DailyIncomplete` pydantic model and `DailyResponse.incomplete: list[DailyIncomplete]`; the matching `DailyIncomplete` TypeScript interface and `DailyResponse.incomplete?: DailyIncomplete[]`.

- [ ] **Step 1: Write the failing tests**

Append to `apps/vault-server/tests/test_daily_route.py`:

```python
class TestIncompleteBlocks:
    """A block missing an end used to be dropped by `continue`.

    That is Bug A's exact shape — written correctly, parsed correctly,
    invisible — and it is why partial capture needs its own array rather
    than relying on the timeline.
    """

    def test_block_missing_an_end_is_reported_not_dropped(self):
        from src.api.routes.daily import _build_blocks_and_coverage, _build_incomplete
        events = [{"id": "evt_1", "name": "Dog walk", "start_time": "2026-09-08T16:00:00",
                   "end_time": None, "source": "manual", "type": "manual"}]
        blocks, _, _ = _build_blocks_and_coverage(events, "2026-09-08", 1440)
        incomplete = _build_incomplete(events, "2026-09-08")
        assert blocks == []
        assert len(incomplete) == 1
        assert incomplete[0].title == "Dog walk"
        assert incomplete[0].missing == ["end_time"]
        assert incomplete[0].start == "16:00"

    def test_block_missing_a_start_reports_its_end(self):
        from src.api.routes.daily import _build_incomplete
        incomplete = _build_incomplete(
            [{"id": "evt_1", "name": "Dog walk", "start_time": None,
              "end_time": "2026-09-08T16:40:00", "source": "manual", "type": "manual"}],
            "2026-09-08",
        )
        assert incomplete[0].missing == ["start_time"]
        assert incomplete[0].end == "16:40"
        assert incomplete[0].start is None

    def test_incomplete_blocks_do_not_change_coverage(self):
        """The gap is the reason to finish the block. A half-block that
        quietly claimed the span would hide the very hole it represents."""
        from src.api.routes.daily import _build_blocks_and_coverage
        _, gaps_with, coverage_with = _build_blocks_and_coverage(
            [{"id": "evt_1", "name": "Dog walk", "start_time": "2026-09-08T16:00:00",
              "end_time": None, "source": "manual", "type": "manual"}],
            "2026-09-08", 1440,
        )
        _, gaps_without, coverage_without = _build_blocks_and_coverage(
            [], "2026-09-08", 1440,
        )
        assert coverage_with.covered_minutes == coverage_without.covered_minutes
        assert len(gaps_with) == len(gaps_without)

    def test_event_belonging_to_another_day_is_still_dropped(self):
        """Present-but-elsewhere and genuinely-absent both make
        `minutes_into_day` return None; only the second is incomplete."""
        from src.api.routes.daily import _build_blocks_and_coverage, _build_incomplete
        events = [{"id": "evt_1", "name": "Yesterday", "start_time": "2026-09-07T16:00:00",
                   "end_time": "2026-09-07T17:00:00", "source": "manual", "type": "manual"}]
        blocks, _, _ = _build_blocks_and_coverage(events, "2026-09-08", 1440)
        incomplete = _build_incomplete(events, "2026-09-08")
        assert blocks == []
        assert incomplete == []
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd apps/vault-server && ./venv/bin/python -m pytest tests/test_daily_route.py -q -k TestIncompleteBlocks
```

Expected: FAIL — `ImportError: cannot import name '_build_incomplete'`.

- [ ] **Step 3: Add the model**

In `apps/vault-server/src/api/routes/daily.py`, after `DailyGap`:

```python
class DailyIncomplete(BaseModel):
    """A block that cannot be drawn on a timeline yet.

    Missing a start or an end, so it has no interval — which is why it is
    its own array rather than a `blocks[]` entry with null fields. It is
    also why it contributes nothing to coverage: the gap it sits inside is
    the prompt to finish it.
    """
    id: str
    title: str
    start: str | None = None      # "HH:MM" when known
    end: str | None = None
    missing: list[str]            # subset of ["start_time", "end_time"]
    source: str
```

and on `DailyResponse`, beside `gaps`:

```python
    incomplete: list[DailyIncomplete] = []
```

- [ ] **Step 4: Collect incomplete events in their own function**

**Do not change `_build_blocks_and_coverage`'s arity.** Thirteen existing tests in `test_daily_route.py` unpack its 3-tuple (`blocks, gaps, coverage = …`, `blocks, _, _ = …`); returning a 4-tuple breaks every one of them for no benefit. Add a sibling function instead, and share the timestamp reading so the two cannot drift.

Above `_build_blocks_and_coverage` in `apps/vault-server/src/api/routes/daily.py`:

```python
def _block_times(e: dict, date: str) -> tuple[int | None, int | None, str | None, str | None]:
    """Minute offsets for one event, alongside the raw timestamps.

    The raw values are returned too because `minutes_into_day` answers None
    for two different questions — "there is no timestamp" and "the timestamp
    belongs to another day" — and the callers need to tell those apart.
    """
    start_raw = e.get("start_time")
    end_raw = e.get("end_time")
    return (
        minutes_into_day(start_raw or "", date),
        _end_minutes(end_raw or "", date),
        start_raw,
        end_raw,
    )


def _build_incomplete(events: list[dict], date: str) -> list[DailyIncomplete]:
    """Events that belong to `date` but cannot be drawn as blocks.

    `_build_blocks_and_coverage` drops these with a bare `continue`, which is
    Bug A's exact shape: written correctly, parsed correctly, invisible. They
    are reported separately rather than as blocks with null fields because
    they have no interval — nothing to sort by, nothing to measure.
    """
    out: list[DailyIncomplete] = []
    for e in events:
        start, end, start_raw, end_raw = _block_times(e, date)
        if start is not None and end is not None:
            continue
        # A timestamp that is present but belongs to another day is a
        # neighbouring fragment, not an incomplete block — it stays out, or
        # it would appear on a day it does not belong to.
        if start_raw and end_raw:
            continue
        out.append(DailyIncomplete(
            id=e.get("id", ""),
            title=e.get("name", ""),
            start=f"{start // 60:02d}:{start % 60:02d}" if start is not None else None,
            end=f"{end // 60:02d}:{end % 60:02d}" if end is not None else None,
            missing=[f for f, v in (("start_time", start_raw), ("end_time", end_raw)) if not v],
            source=e.get("source") or "",
        ))
    return out
```

Then in `_build_blocks_and_coverage`, replace only the first four lines of its loop body so it reads its timestamps through the shared helper — its `continue` and everything after are unchanged:

```python
    for e in events:
        start, end, _, _ = _block_times(e, date)
        if start is None or end is None:
            continue
```

At the route's call site (`daily.py:292`), leave the existing unpacking alone and add one line after it:

```python
    blocks, gaps, coverage = _build_blocks_and_coverage(events, target, elapsed)
    incomplete = _build_incomplete(events, target)
```

and pass `incomplete=incomplete` into `DailyResponse`.

- [ ] **Step 5: Mirror the type in shared-types**

In `packages/shared-types/src/daily.ts`, after `DailyGap`:

```typescript
/** A block with no drawable interval — missing a start or an end time.
 *  Kept out of `blocks` deliberately: it has no interval, contributes
 *  nothing to coverage, and the gap it sits inside is what prompts you to
 *  finish it. */
export interface DailyIncomplete {
  id: string;
  title: string;
  start?: string | null;
  end?: string | null;
  missing: string[];
  source: string;
}
```

and add `incomplete?: DailyIncomplete[];` to `DailyResponse`, exporting the new interface from `packages/shared-types/src/index.ts` alongside the other daily types.

- [ ] **Step 6: Run both suites**

```bash
cd apps/vault-server && ./venv/bin/python -m pytest tests/ -q
cd ../../packages/shared-types && npx tsc -b
```

Expected: `1012 passed`; `tsc -b` exits 0.

- [ ] **Step 7: Commit**

```bash
git add apps/vault-server/src/api/routes/daily.py apps/vault-server/tests/test_daily_route.py \
        packages/shared-types/src/daily.ts packages/shared-types/src/index.ts
git commit -m "feat(daily): report incomplete blocks instead of dropping them"
```

---

### Task 9: Surfacing — `/day` section and the context line

**Files:**
- Modify: `apps/telegram-bot/src/formatters/day-rich.ts`
- Modify: `apps/vault-server/src/services/agent_service.py` (`_build_system_prompt` ~line 1943; `_static_guidelines` ~line 1859)
- Test: `apps/telegram-bot/tests/formatters/day-rich.test.ts`, `apps/vault-server/tests/test_agent_service.py`

**Interfaces:**
- Consumes: `DailyIncomplete` (Task 8), `is_complete` (Task 2).
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing tests**

Append to `apps/telegram-bot/tests/formatters/day-rich.test.ts`. That file already has a `base` fixture and an `html(data)` helper that calls `buildDayRich(data as never).html ?? ""` — use both rather than introducing a second style:

```typescript
describe("incomplete blocks", () => {
  it("renders a needs-a-time section", () => {
    const out = html({
      ...base,
      incomplete: [
        { id: "e1", title: "Dog walk", start: null, end: "16:40",
          missing: ["start_time"], source: "manual" },
      ],
    });
    expect(out).toContain("Needs a time");
    expect(out).toContain("Dog walk");
    expect(out).toContain("16:40");
  });

  it("omits the section entirely when there are none", () => {
    expect(html({ ...base, incomplete: [] })).not.toContain("Needs a time");
  });

  it("survives a payload with no incomplete field at all", () => {
    // `base` predates this feature and has no `incomplete` key, which is
    // exactly the shape an older server sends.
    expect(html(base)).not.toContain("Needs a time");
  });

  it("escapes the title", () => {
    const out = html({
      ...base,
      incomplete: [
        { id: "e1", title: "Dog & <walk>", start: null, end: "16:40",
          missing: ["start_time"], source: "manual" },
      ],
    });
    expect(out).toContain("Dog &amp; &lt;walk&gt;");
  });
});
```

Append to `apps/vault-server/tests/test_agent_service.py`:

```python
class TestIncompleteBlocksInContext:
    """Push, not pull.

    Ship 3's lesson: the agent will not call a tool to discover something
    it does not know to look for. Bug B was one iteration and zero tool
    calls with two read tools in hand.
    """

    def test_incomplete_blocks_appear_in_the_prompt_tail(self, agent, mock_services):
        from types import SimpleNamespace
        events_mock = mock_services[4]
        events_mock.get_events.return_value = [
            {"id": "e1", "name": "Dog walk", "start_time": None,
             "end_time": "2026-09-08T16:40:00"},
            {"id": "e2", "name": "Standup", "start_time": "2026-09-08T10:00:00",
             "end_time": "2026-09-08T10:30:00"},
        ]
        # test_agent_service.py defines its OWN mock_services fixture, and
        # unlike conftest.py's it does not set `tz` — leaving `vault.tz` a
        # MagicMock that `datetime.now()` would silently accept, making the
        # test pass for the wrong reason.
        import pytz
        mock_services[1].tz = pytz.timezone("Asia/Jerusalem")
        ctx = SimpleNamespace(vault_snapshot="1 task", knowledge=None)

        prompt = agent._build_system_prompt(ctx)

        assert "Incomplete blocks today: 1" in prompt
        assert "Dog walk" in prompt
        assert "no start time" in prompt
        assert "Standup" not in prompt

    def test_no_line_when_every_block_is_complete(self, agent, mock_services):
        from types import SimpleNamespace
        events_mock = mock_services[4]
        events_mock.get_events.return_value = [
            {"id": "e2", "name": "Standup", "start_time": "2026-09-08T10:00:00",
             "end_time": "2026-09-08T10:30:00"},
        ]
        import pytz
        mock_services[1].tz = pytz.timezone("Asia/Jerusalem")
        ctx = SimpleNamespace(vault_snapshot="1 task", knowledge=None)

        assert "Incomplete blocks" not in agent._build_system_prompt(ctx)

    def test_a_failing_read_costs_the_line_not_the_turn(self, agent, mock_services):
        from types import SimpleNamespace
        import pytz
        mock_services[1].tz = pytz.timezone("Asia/Jerusalem")
        mock_services[4].get_events.side_effect = OSError("disk gone")
        ctx = SimpleNamespace(vault_snapshot="1 task", knowledge=None)

        prompt = agent._build_system_prompt(ctx)

        assert "Current date/time" in prompt
        assert "Incomplete blocks" not in prompt
```

- [ ] **Step 2: Run both to verify they fail**

```bash
cd apps/telegram-bot && TELEGRAM_BOT_TOKEN=x AUTHORIZED_USER_ID=1 npx vitest run tests/formatters/day-rich.test.ts
cd ../vault-server && ./venv/bin/python -m pytest tests/test_agent_service.py -q -k TestIncompleteBlocksInContext
```

- [ ] **Step 3: Render the section**

In `apps/telegram-bot/src/formatters/day-rich.ts`, import `DailyIncomplete` from `@mazkir/shared-types` and add, between the Todos block and the Notes block:

```typescript
  // Read-only text, no buttons: a block is completed by talking, and a
  // button that opens a conversation is machinery this view does not need.
  const incomplete = data.incomplete ?? [];
  if (incomplete.length > 0) {
    const items = incomplete.map((b: DailyIncomplete) => {
      const known = b.start ? `started ${b.start}` : b.end ? `ended ${b.end}` : "no times";
      const want = b.missing.includes("start_time") ? "no start time" : "no end time";
      return `<li>⁇ <b>${escapeHtml(b.title)}</b> — ${escapeHtml(known)}, ${escapeHtml(want)}</li>`;
    });
    parts.push(`<h3>⁇ Needs a time</h3>`);
    parts.push(`<ul>${items.join("")}</ul>`);
  }
```

- [ ] **Step 4: Add the context line**

In `agent_service.py`'s `_build_system_prompt`, after the `parts` list is built:

```python
        # Push, not pull. The agent will not call a tool to discover
        # something it does not know to look for — that is Bug B — so
        # unfinished blocks arrive in the prompt rather than waiting to be
        # queried. Cheap: an incomplete block is always user-created, so it
        # is always in the persisted store. A local read, never a merge.
        try:
            from src.services.events_service import is_complete
            import datetime as _dt
            today = _dt.datetime.now(self.vault.tz).strftime("%Y-%m-%d")
            unfinished = [e for e in self.events.get_events(today) if not is_complete(e)]
            if unfinished:
                described = "; ".join(
                    f"{e.get('name', '?')} — "
                    f"{'no start time' if not e.get('start_time') else 'no end time'}"
                    for e in unfinished[:5]
                )
                parts.extend([
                    "",
                    f"Incomplete blocks today: {len(unfinished)} ({described})",
                ])
        except Exception as e:
            logger.debug(f"Could not list incomplete blocks: {e}")
```

- [ ] **Step 5: Add the prompt rules**

In `_static_guidelines`, after the existing `attach_to_daily` bullet:

```python
            "- Logging time: supply any TWO of start_time / end_time / duration_minutes to create_event and the third is computed. Never compute one yourself.",
            "- Which end does the utterance anchor? 'just got back from X' / 'finished X' gives the END; 'starting X' gives the START; 'X from A to B' gives both.",
            "- Never invent a missing time. Create the block with what you were told, leave the rest empty, and ask. An incomplete block is a correct record of an incomplete statement.",
            "- To move a block, use update_event's shift_minutes. Setting start_time alone stretches the block rather than moving it.",
            "- If the context lists incomplete blocks, you may mention them once when it fits the conversation. Do not raise them every turn.",
            "- When you write to a day that is not today, say which day in your reply.",
```

- [ ] **Step 6: Run both suites**

```bash
cd apps/telegram-bot && TELEGRAM_BOT_TOKEN=x AUTHORIZED_USER_ID=1 npx vitest run
cd ../vault-server && ./venv/bin/python -m pytest tests/ -q
```

Expected: bot `151 passed` (147 + 4); server `1015 passed`.

- [ ] **Step 7: Commit**

```bash
git add apps/telegram-bot/src/formatters/day-rich.ts apps/telegram-bot/tests/formatters/day-rich.test.ts \
        apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_agent_service.py
git commit -m "feat: surface incomplete blocks on /day and in the agent's context"
```

---

### Task 10: The selected-date hint

Independent of Tasks 1–9: dropping this task leaves everything else working, with corrections always meaning today.

**Files:**
- Create: `apps/telegram-bot/src/state/selected-date.ts`
- Modify: `apps/telegram-bot/src/bot.ts`, `src/commands/day.ts`, `src/callbacks/index.ts`, `src/conversations/message.ts`, `src/api/client.ts`
- Modify: `apps/vault-server/src/api/routes/message.py`, `apps/vault-server/src/services/agent_service.py`
- Test: `apps/telegram-bot/tests/state/selected-date.test.ts`, `apps/vault-server/tests/test_message_models.py`

**Interfaces:**
- Produces: `noteDayView(chatId: number)`, `noteOtherSend(chatId: number)`, `getSelectedDate(chatId: number): string | undefined`, `setSelectedDate(chatId: number, date: string)`; `MessageRequest.selected_date: str | None`; `AgentService.handle_message(..., selected_date: str | None = None)`.

- [ ] **Step 1: Write the failing tests**

Create `apps/telegram-bot/tests/state/selected-date.test.ts` (beside the existing `pending-confirmations.test.ts`, which this module is modelled on):

```typescript
import { describe, it, expect, beforeEach } from "vitest";
import {
  getSelectedDate, setSelectedDate, noteDayView, noteOtherSend, resetSelectedDates,
} from "../src/state/selected-date.js";

describe("selected date hint", () => {
  beforeEach(() => resetSelectedDates());

  it("is absent before any day view", () => {
    expect(getSelectedDate(1)).toBeUndefined();
  });

  it("is offered after a day view renders", () => {
    setSelectedDate(1, "2026-08-20");
    noteDayView(1);
    expect(getSelectedDate(1)).toBe("2026-08-20");
  });

  it("is dropped once the bot sends anything else", () => {
    // A day view scrolled off behind other output is no longer what the
    // user is looking at — and a date they have forgotten selecting must
    // not silently steer a much later message.
    setSelectedDate(1, "2026-08-20");
    noteDayView(1);
    noteOtherSend(1);
    expect(getSelectedDate(1)).toBeUndefined();
  });

  it("comes back when a new day view renders", () => {
    setSelectedDate(1, "2026-08-20");
    noteDayView(1);
    noteOtherSend(1);
    setSelectedDate(1, "2026-08-21");
    noteDayView(1);
    expect(getSelectedDate(1)).toBe("2026-08-21");
  });

  it("keeps chats separate", () => {
    setSelectedDate(1, "2026-08-20");
    noteDayView(1);
    setSelectedDate(2, "2026-08-21");
    noteDayView(2);
    noteOtherSend(1);
    expect(getSelectedDate(1)).toBeUndefined();
    expect(getSelectedDate(2)).toBe("2026-08-21");
  });
});
```

Append to `apps/vault-server/tests/test_message_models.py`. That file tests the request model and the
kwargs mapping directly rather than through an HTTP client — there is no `client`/`mock_agent` fixture
for this route, and the two functions below are the whole surface the hint travels through:

```python
def test_selected_date_is_accepted_on_the_request():
    from src.api.routes.message import MessageRequest
    req = MessageRequest(text="move gym -30m", chat_id=1, selected_date="2026-08-20")
    assert req.selected_date == "2026-08-20"


def test_selected_date_is_optional():
    from src.api.routes.message import MessageRequest
    assert MessageRequest(text="hello", chat_id=1).selected_date is None


def test_selected_date_is_forwarded_to_the_agent():
    from src.api.routes.message import MessageRequest, _prepare_agent_kwargs
    kwargs = _prepare_agent_kwargs(
        MessageRequest(text="move gym -30m", chat_id=1, selected_date="2026-08-20")
    )
    assert kwargs["selected_date"] == "2026-08-20"


def test_absent_selected_date_forwards_as_none():
    from src.api.routes.message import MessageRequest, _prepare_agent_kwargs
    kwargs = _prepare_agent_kwargs(MessageRequest(text="hello", chat_id=1))
    assert kwargs["selected_date"] is None
```

- [ ] **Step 2: Run both to verify they fail**

```bash
cd apps/telegram-bot && TELEGRAM_BOT_TOKEN=x AUTHORIZED_USER_ID=1 npx vitest run tests/state/selected-date.test.ts
cd ../vault-server && ./venv/bin/python -m pytest tests/test_message_models.py -q -k selected_date
```

- [ ] **Step 3: Write the bot state module**

Create `apps/telegram-bot/src/state/selected-date.ts`:

```typescript
/**
 * Which day the user is looking at, and whether that is still true.
 *
 * The hint only counts while the day view is the last thing the bot sent
 * to the chat. Send anything else — an agent reply, /tasks, a photo
 * acknowledgement — and it is dropped: a day view that has scrolled off
 * behind other output is no longer what the user is looking at, and a date
 * they have forgotten selecting must not silently steer a much later
 * message.
 *
 * No clock and no tuning parameter, deliberately. A TTL would be wrong in
 * both directions: too short mid-conversation, too long after walking away.
 *
 * In-memory, like pending-confirmations.ts: this is a property of the
 * current conversation, and falling back to today after a restart is the
 * safe default.
 */
interface Entry {
  date: string;
  /** True while the day view is still the bot's most recent message here. */
  onScreen: boolean;
}

const state = new Map<number, Entry>();

export function setSelectedDate(chatId: number, date: string): void {
  state.set(chatId, { date, onScreen: false });
}

export function noteDayView(chatId: number): void {
  const entry = state.get(chatId);
  if (entry) entry.onScreen = true;
}

export function noteOtherSend(chatId: number): void {
  const entry = state.get(chatId);
  if (entry) entry.onScreen = false;
}

export function getSelectedDate(chatId: number): string | undefined {
  const entry = state.get(chatId);
  return entry?.onScreen ? entry.date : undefined;
}

/** Test seam. Never called in production. */
export function resetSelectedDates(): void {
  state.clear();
}
```

- [ ] **Step 4: Wire the bot**

In `src/commands/day.ts`, before `sendRich`, record the date and mark the view on screen:

```typescript
  setSelectedDate(ctx.chat!.id, data.date);
  try {
    await sendRich(ctx, rich, { reply_markup: buildNavKeyboard("day") });
    noteDayView(ctx.chat!.id);
  } catch (err) {
```

Do the same in the `day:` callback handler in `src/callbacks/index.ts` after its edit succeeds.

In `src/bot.ts`, register an API transformer so every *other* send clears the flag without each call site having to remember:

```typescript
// A transformer, not a per-call-site update: the hint has to be dropped by
// every send in the bot, and a rule that each new send site must opt into
// is a rule that will be missed. `day.ts` and the `day:` callback re-arm it
// immediately after their own send.
bot.api.config.use(async (prev, method, payload, signal) => {
  const result = await prev(method, payload, signal);
  const chatId = (payload as { chat_id?: number }).chat_id;
  if (chatId !== undefined) noteOtherSend(chatId);
  return result;
});
```

In `src/conversations/message.ts`, attach the hint to the payload built around line 98:

```typescript
  const selected_date = getSelectedDate(chatId);

  return {
    text,
    chat_id: chatId,
    ...(selected_date ? { selected_date } : {}),
    ...(attachments.length > 0 ? { attachments } : {}),
    ...(reply_to ? { reply_to } : {}),
    ...(forwarded_from ? { forwarded_from } : {}),
  };
```

and add `selected_date?: string;` to `StreamMessagePayload` in `src/api/client.ts`.

- [ ] **Step 5: Thread it through the server**

In `apps/vault-server/src/api/routes/message.py`, add `selected_date: str | None = None` to `MessageRequest` and `"selected_date": body.selected_date` to `_prepare_agent_kwargs`'s returned dict.

In `agent_service.py`, add `selected_date: str | None = None` to `handle_message`'s signature, store it as `self._selected_date = selected_date` at the top of the method, and read it in `_resolve_reference` — replacing `params.get("selected_date")` with `params.get("selected_date") or getattr(self, "_selected_date", None)`. In `_build_system_prompt`, add the line when it is set and is not today:

```python
        selected = getattr(self, "_selected_date", None)
        if selected:
            parts.extend(["", f"The user is currently viewing {selected}."])
```

- [ ] **Step 6: Run both suites**

```bash
cd apps/telegram-bot && TELEGRAM_BOT_TOKEN=x AUTHORIZED_USER_ID=1 npx vitest run
cd ../vault-server && ./venv/bin/python -m pytest tests/ -q
```

Expected: bot `156 passed`; server `1019 passed`.

- [ ] **Step 7: Commit**

```bash
git add apps/telegram-bot/src apps/telegram-bot/tests apps/vault-server/src apps/vault-server/tests
git commit -m "feat: the bot tells the server which day is on screen"
```

---

### Task 11: Skill registration and documentation

The tools are unreachable through the skill loop until the vault's frontmatter lists them — `delete_event` spent its first days in exactly that state.

**Files:**
- Modify: `memory/00-system/skills/time-management.md` (**separate git repo — commit there, never from the monorepo**)
- Modify: `CLAUDE.md`
- Test: `apps/vault-server/tests/test_skill_set.py`

- [ ] **Step 1: Check what the skill loop can actually reach**

```bash
grep -n "list_events\|create_event\|update_event\|delete_event" ~/pkm/00-system/skills/time-management.md
```

All four must be present. `delete_event` was added on 2026-09-08 (vault commit `0f22833`); the other three predate this ship.

- [ ] **Step 2: Update the skill's `when_to_use`**

In `memory/00-system/skills/time-management.md`, replace the events line under `when_to_use`:

```yaml
  - Events: scheduling something at a clock time, logging what already happened ("slept 23:30 to 07:15", "just got back from the dog walk"), correcting a block by name, deleting a duplicate, or attaching a photo to an event
```

and add to the body's rules, after the existing `create_event` bullet:

```markdown
- **Give `create_event` any two of `start_time` / `end_time` / `duration_minutes`** and the third is computed. Never compute one yourself. Told only one, create the block anyway — an incomplete block is a correct record of an incomplete statement, and it will be raised again rather than lost.
- **"Just got back from X" anchors the END**, not the start. "Starting X" anchors the start. Getting this backwards shifts the block by its own length.
- **To move a block use `shift_minutes`.** Setting `start_time` alone stretches it.
- **Refer to a block by name** with `block_reference` rather than asking for an ID.
```

- [ ] **Step 3: Commit in the vault repo**

```bash
cd memory && git add 00-system/skills/time-management.md \
  && git commit -m "feat(skills): teach time-management to log and correct by talking"
```

- [ ] **Step 4: Update `CLAUDE.md`**

Add to the Architecture bullets:

```markdown
- **Per-field provenance (Ship 4):** an event's `user_set` map holds the fields the user set explicitly — one of `name`, `start_time`, `end_time`, `location`, `activity`. `reconcile` merges from the source as usual and then re-applies `user_set` last, so a rename or a corrected time survives re-inference while every unpinned field keeps tracking its source. This is the fix for a rename that persisted and then silently reverted on the next `/day` open. It is *not* the same mechanism as `moved_from_source_ids`: detach is for relocation (the event left the day its source owns and can never be matched there again), pinning is for override (the event is still that source's, but one field is now the user's). `revert_fields` on `update_event` removes a pin.
- **Completeness is derived (Ship 4):** `is_complete(event)` is `start_time and end_time`, computed wherever it is needed and never stored — a status that restates the timestamps goes stale. A block missing either end used to be dropped by `_build_blocks_and_coverage`; it now arrives as `/daily`'s `incomplete[]` and contributes nothing to coverage, so the gap it sits in stays visible as the prompt to finish it. `create_event` takes any two of `start_time` / `end_time` / `duration_minutes` and derives the third; given one, it writes an incomplete block rather than inventing the rest.
- **Cross-midnight blocks split (Ship 4):** `create_event` splits at 00:00 into one fragment per day, sharing a `logical_id` that nothing reads yet — Ship 5 needs it to approve both halves of a night's sleep at once, and the link is unrecoverable if not written at creation. Such a block is deliberately not synced to Google (`reason: "crosses_midnight"`): Google stores it natively as one event, which would hand a single fresh event to two per-day fragments on the next merge.
- **`list_events` returns the reconciled day (Ship 4):** it read the raw persisted file while `/day` rendered a reconciled, deliberately unpersisted view, so the two could disagree entirely. `services/day_assembly.py` now owns the source fan-out and both callers use it. On a source failure `list_events` falls back to the persisted store and sets `degraded: true` — an empty list would read to the agent as "that block does not exist", which is the shape of the denial bug Ship 3 fixed.
- **Calendar edits propagate (Ship 4):** `CalendarService.update_event` patches Mazkir's own calendar; before it existed, an edit made by talking changed the ledger and never reached Google, and the next merge read the unchanged Google values back over it. `MergedEvent.calendar` carries the owning calendar's name through the merge, so an event in another calendar reports `not_in_mazkir_calendar` rather than issuing a doomed call and reading a 404 as an unexplained failure.
- **The selected-date hint (Ship 4):** the bot passes `selected_date` on `POST /message` while the `/day` view is still the last message it sent to that chat, and drops it after any other send. Two guards make a stale hint harmless: `block_reference` resolves against the hinted day *and* today (so a stale hint only matters when the block exists on that day alone), and any write to a day that is not today names the day in the reply.
```

Update the tool-count line's `34 registered tools` to `34` (no new tools are added by this ship — `create_event`, `update_event`, `delete_event` and `list_events` all gain parameters) and add `list_events` to the note that it now reaches the calendar.

- [ ] **Step 5: Run everything**

```bash
cd apps/vault-server && ./venv/bin/python -m pytest tests/ -q
cd ../telegram-bot && TELEGRAM_BOT_TOKEN=x AUTHORIZED_USER_ID=1 npx vitest run
cd ../telegram-web-app && npx vitest run
cd ../../packages/shared-types && npx tsc -b
```

Expected: server `1019 passed`, bot `156 passed`, webapp `21 passed`, `tsc -b` exits 0.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md apps/vault-server/tests/test_skill_set.py
git commit -m "docs(ship4): record the provenance, completeness and sync decisions"
```

---

## Self-Review

**1. Spec coverage.** §2.1 `user_set` → Task 2. §2.2 the two mechanisms → documented in Task 11. §2.3 completeness → Tasks 2 and 8. §3.1 any-two-of-three → Tasks 1 and 6. §3.1 anchoring rules → Tasks 9 and 11. §3.2 two-step conversation → Tasks 8, 9. §3.3 cross-midnight → Tasks 1 and 6. §4.1 reconciled `list_events` → Tasks 4 and 5. §4.2 addressing → Task 3. §4.3 materialise-on-edit → Task 6. §4.4 interval guards → Tasks 1, 2, 6. §5 selected date → Task 10. §6 calendar → Task 7. §7.1 `/day` section → Task 9. §7.2 context line → Task 9. §9's test list is distributed across the tasks that own each behaviour.

**2. Placeholders.** None: every step carries the code or the exact command it needs.

**3. Type consistency.** `is_complete`, `apply_user_set`, `USER_SETTABLE_FIELDS` are defined in Task 2 and imported by 5, 6, 7, 8, 9 under those names. `derive_interval` / `crosses_midnight` / `split_at_midnight` / `normalize_time` are defined in Task 1 and used in Task 6. `resolve_block` (Task 3) is called only from `_resolve_reference` (Task 6). `merge_from_sources` and `maybe_await` (Task 4) are used in 5, 6, 7. `_reconciled_events` returns `(events, degraded)` in Task 5 and both call sites unpack the pair. `DailyIncomplete` is the same name in the pydantic model and the TypeScript interface.

**One known gap, deliberate.** `EventsService.create_event` gains a `logical_id` keyword in Task 6 rather than in Task 2, because Task 2's subject is provenance and the split is the only thing that needs the field. A reviewer of Task 2 will not see it; Task 6's step 5 names the change explicitly.

## Expected test counts

| After task | Server | Bot |
|---|---|---|
| baseline (`c3ffcee`) | 937 | 147 |
| 1 | 957 | 147 |
| 2 | 971 | 147 |
| 3 | 980 | 147 |
| 4 | 985 | 147 |
| 5 | 989 | 147 |
| 6 | 1002 | 147 |
| 7 | 1008 | 147 |
| 8 | 1012 | 147 |
| 9 | 1015 | 151 |
| 10 | 1019 | 156 |

**These numbers are advisory and were counted by hand — treat a small discrepancy as an arithmetic slip in this table, not a defect.** Two rules bind instead, and both are checkable: the count must never *decrease*, and every test written in a task's step 1 must be present and passing at that task's end. A task that lands more tests than listed is fine.
