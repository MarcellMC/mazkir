# Unified Timed-Event Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `create_event` the canonical "timed thing" action — it writes a `## Schedule` line in the daily note in addition to the events store + Google Calendar — and give the `capture` skill access to it so timed events stop being mis-filed as knowledge notes.

**Architecture:** A new `daily_schedule.py` module (mirroring the existing `daily_tasks.py`) parses/renders a `## Schedule` section. `_tool_create_event` gains a best-effort daily-note write using that module. The daily template gains the section, and the `capture` skill markdown gains the `create_event` tool plus a prompt rule distinguishing timed events from timeless facts.

**Tech Stack:** Python 3.14, FastAPI, pytest. Vault notes are markdown + YAML frontmatter. Tests run from `apps/vault-server` with the venv active.

**Spec:** `docs/plans/2026-06-09-unified-timed-event-capture-design.md`

**Setup (run once before Task 1):**
```bash
cd ~/dev/mazkir/apps/vault-server && source venv/bin/activate
```
All `pytest` commands below assume this venv is active and cwd is `apps/vault-server`.

---

### Task 1: `daily_schedule.py` — parse/render the `## Schedule` section

Mirrors `src/services/daily_tasks.py`. A `ScheduleEntry` holds `start`, optional `end`, and the
remaining line `text` verbatim (title + `@ location` + wikilinks composed by the caller), so the
section round-trips without brittle re-parsing of location/wikilinks.

**Files:**
- Create: `src/services/daily_schedule.py`
- Test: `tests/test_daily_schedule.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_daily_schedule.py`:

```python
"""Tests for the daily-note `## Schedule` section parser/renderer."""

from src.services.daily_schedule import (
    ScheduleEntry,
    parse_schedule_section,
    render_schedule_section,
)


def test_parse_empty_when_no_section():
    assert parse_schedule_section("## Tasks\n- [ ]\n") == []


def test_parse_single_entry_with_end_and_text():
    body = "## Schedule\n- 20:00–22:30 Pub meeting @ Shnitt brewery [[Momentick]]\n\n## Food\n"
    entries = parse_schedule_section(body)
    assert entries == [
        ScheduleEntry(
            start="20:00",
            end="22:30",
            text="Pub meeting @ Shnitt brewery [[Momentick]]",
        )
    ]


def test_parse_entry_without_end():
    entries = parse_schedule_section("## Schedule\n- 09:00 Standup\n")
    assert entries == [ScheduleEntry(start="09:00", end=None, text="Standup")]


def test_render_includes_header_and_dash_range():
    section = render_schedule_section(
        [ScheduleEntry(start="20:00", end="22:30", text="Pub meeting @ Shnitt brewery")]
    )
    assert section == "## Schedule\n- 20:00–22:30 Pub meeting @ Shnitt brewery\n"


def test_render_omits_end_when_absent():
    section = render_schedule_section([ScheduleEntry(start="09:00", end=None, text="Standup")])
    assert section == "## Schedule\n- 09:00 Standup\n"


def test_round_trip_preserves_entries():
    body = "## Schedule\n- 09:00 Standup\n- 20:00–22:30 Pub meeting [[Momentick]]\n"
    entries = parse_schedule_section(body)
    assert render_schedule_section(entries) == body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_daily_schedule.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.daily_schedule'`

- [ ] **Step 3: Write the implementation**

Create `src/services/daily_schedule.py`:

```python
"""Parser/writer for the `## Schedule` section in daily notes.

Format:
    ## Schedule
    - 20:00–22:30 Pub meeting @ Shnitt brewery [[Momentick]]
    - 09:00 Standup

Each line is `- HH:MM[–HH:MM] <text>`. The text (title, optional `@ location`,
trailing wikilinks) is stored and re-emitted verbatim so the section round-trips.
The dash between start and end times is an en-dash (U+2013).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SECTION_RE = re.compile(
    r"##\s+Schedule\s*\n(.*?)(?=^##|\Z)", re.DOTALL | re.IGNORECASE | re.MULTILINE
)
_LINE_RE = re.compile(
    r"^-\s+(?P<start>\d{1,2}:\d{2})(?:–(?P<end>\d{1,2}:\d{2}))?\s+(?P<text>.*\S)\s*$"
)


@dataclass
class ScheduleEntry:
    start: str
    end: str | None
    text: str


def parse_schedule_section(body: str) -> list[ScheduleEntry]:
    m = _SECTION_RE.search(body)
    if not m:
        return []
    entries: list[ScheduleEntry] = []
    for line in m.group(1).splitlines():
        lm = _LINE_RE.match(line)
        if not lm:
            continue
        entries.append(
            ScheduleEntry(
                start=lm.group("start"),
                end=lm.group("end"),
                text=lm.group("text"),
            )
        )
    return entries


def render_schedule_section(entries: list[ScheduleEntry]) -> str:
    lines = ["## Schedule"]
    for e in entries:
        rng = f"{e.start}–{e.end}" if e.end else e.start
        lines.append(f"- {rng} {e.text}")
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_daily_schedule.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/services/daily_schedule.py tests/test_daily_schedule.py
git commit -m "feat(vault-server): daily-note ## Schedule parser/renderer"
```

---

### Task 2: `_tool_create_event` writes the `## Schedule` line

Add a best-effort daily-note write after the events-store write. Compose the schedule
`text` from `name` + optional `@ location.name` + trailing wikilinks. Skip entirely when
`photo_path` is set (photo events keep the existing pipeline). A daily-note failure logs at
WARNING and never changes the tool's success — the events-store write is the durable record.

**Files:**
- Modify: `src/services/agent_service.py` — inside `_tool_create_event`, between the
  `self.events.create_event(...)` call (currently ~line 2433) and `return ok(result, items=items)`
  (currently ~line 2452).
- Test: `tests/test_agent_service.py` (add to the existing events test group near line 600).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_agent_service.py` (after `test_create_event_syncs_to_gcal`, ~line 629):

```python
    def test_create_event_writes_schedule_line(self, agent, mock_services):
        vault = mock_services[1]
        events_mock = mock_services[4]
        agent.calendar = None
        events_mock.create_event.return_value = {"id": "evt_new", "path": "data/events/2026-06-07.json"}
        vault.read_daily_note.return_value = {"content": "## Tasks\n- [ ]\n\n## Food\n"}

        result = agent._tool_create_event({
            "name": "Pub meeting",
            "date": "2026-06-07",
            "start_time": "20:00",
            "end_time": "22:30",
            "location": {"name": "Shnitt brewery"},
            "wikilinks": ["Momentick"],
        })

        assert result["ok"] is True
        vault.write_daily_note.assert_called_once()
        written_date, written_body = vault.write_daily_note.call_args[0]
        assert written_date == "2026-06-07"
        assert "## Schedule" in written_body
        assert "- 20:00–22:30 Pub meeting @ Shnitt brewery [[Momentick]]" in written_body
        # daily-note path is included in _items for audit
        assert any("2026-06-07" in str(p) for p in result["_items"])

    def test_create_event_skips_schedule_for_photo(self, agent, mock_services):
        vault = mock_services[1]
        events_mock = mock_services[4]
        agent.calendar = None
        events_mock.create_event.return_value = {"id": "evt_p", "path": "data/events/2026-06-07.json"}

        result = agent._tool_create_event({
            "name": "Lunch photo",
            "date": "2026-06-07",
            "start_time": "12:00",
            "photo_path": "memory/00-system/media/2026-06-07/lunch.jpg",
        })

        assert result["ok"] is True
        vault.write_daily_note.assert_not_called()

    def test_create_event_schedule_failure_does_not_break_result(self, agent, mock_services):
        vault = mock_services[1]
        events_mock = mock_services[4]
        agent.calendar = None
        events_mock.create_event.return_value = {"id": "evt_new", "path": "data/events/2026-06-07.json"}
        vault.read_daily_note.side_effect = Exception("vault down")

        result = agent._tool_create_event({
            "name": "Pub meeting",
            "date": "2026-06-07",
            "start_time": "20:00",
        })

        assert result["ok"] is True
        assert result["data"]["event_id"] == "evt_new"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_service.py -k "create_event_writes_schedule or create_event_skips_schedule or create_event_schedule_failure" -v`
Expected: FAIL — `test_create_event_writes_schedule_line` asserts `write_daily_note` called once but it is never called; `test_create_event_skips_schedule_for_photo` may pass vacuously (acceptable — it guards the photo branch once the write exists).

- [ ] **Step 3: Implement the daily-note write**

In `src/services/agent_service.py`, locate the end of `_tool_create_event`:

```python
        result["event_id"] = result.pop("id")
        items = [result["path"]]
        if calendar_synced:
            result["calendar_synced"] = True
        return ok(result, items=items)
```

Replace it with:

```python
        result["event_id"] = result.pop("id")
        items = [result["path"]]
        if calendar_synced:
            result["calendar_synced"] = True

        # Unified record: also log the event in the daily note's ## Schedule section.
        # Best-effort — a failure here never invalidates the events-store write.
        if not params.get("photo_path"):
            try:
                from src.services.daily_schedule import (
                    ScheduleEntry,
                    parse_schedule_section,
                    render_schedule_section,
                )
                from src.services.daily_tasks import replace_or_append_section

                text = params["name"]
                loc = params.get("location") or {}
                if loc.get("name"):
                    text = f"{text} @ {loc['name']}"
                for link in params.get("wikilinks") or []:
                    text = f"{text} [[{link}]]"

                daily = self.vault.read_daily_note(date)
                body = daily["content"]
                entries = parse_schedule_section(body)
                entries.append(
                    ScheduleEntry(
                        start=_extract_hhmm(start_time),
                        end=_extract_hhmm(end_time),
                        text=text,
                    )
                )
                new_section = render_schedule_section(entries)
                new_body = replace_or_append_section(body, "Schedule", new_section)
                self.vault.write_daily_note(date, new_body)
                daily_path = f"10-daily/{date}.md"
                items.append(daily_path)
                result["daily_note"] = daily_path
            except Exception as e:
                logger.warning(f"Failed to write event to daily note: {e}")

        return ok(result, items=items)
```

Note: `_extract_hhmm` is already defined earlier in this method (it strips the date prefix to `HH:MM`), so `start`/`end` land in the schedule line as bare times.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_service.py -k "create_event" -v`
Expected: PASS (all `create_event` tests, including the three new ones and the pre-existing `test_create_event_calls_service` / `test_create_event_syncs_to_gcal`)

- [ ] **Step 5: Commit**

```bash
git add src/services/agent_service.py tests/test_agent_service.py
git commit -m "feat(vault-server): create_event writes daily-note ## Schedule line"
```

---

### Task 3: Add `## Schedule` to the daily-note template

So new daily notes carry the section; `replace_or_append_section` handles older notes
that lack it by appending.

**Files:**
- Modify: `memory/00-system/templates/_daily_.md`

- [ ] **Step 1: Edit the template**

In `memory/00-system/templates/_daily_.md`, the body currently reads:

```markdown
## Tasks
- [ ]

## Food
```

Change it to insert a `## Schedule` section between `## Tasks` and `## Food`:

```markdown
## Tasks
- [ ]

## Schedule

## Food
```

- [ ] **Step 2: Verify the change**

Run: `grep -n "## Schedule" /home/marcellmc/dev/mazkir/memory/00-system/templates/_daily_.md`
Expected: one matching line between the `## Tasks` and `## Food` sections.

- [ ] **Step 3: Commit**

The vault is a separate nested git repo. Commit there:

```bash
cd ~/dev/mazkir/memory
git add 00-system/templates/_daily_.md
git commit -m "feat(vault): add ## Schedule section to daily template"
cd ~/dev/mazkir/apps/vault-server
```

---

### Task 4: Give the `capture` skill `create_event` + a timed-event prompt rule

The router already routes timed events to `capture`; the fix is the tool availability +
a classification rule. The capture skill markdown lives in the vault.

**Files:**
- Modify: `memory/00-system/mazkir-skills/capture.md`
- Test: `tests/test_capture_skill.py` (new — asserts the real skill file declares `create_event`)

- [ ] **Step 1: Write the failing test**

Create `tests/test_capture_skill.py`:

```python
"""Guards the capture skill declares create_event so timed events aren't mis-filed."""

from src.config import settings
from src.services.skill_registry import SkillRegistry


def test_capture_skill_has_create_event():
    registry = SkillRegistry(skills_dir=settings.skills_dir)
    registry.load()
    capture = registry.get("capture")
    assert capture is not None, f"capture skill not found in {settings.skills_dir}"
    assert "create_event" in capture.tools
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_capture_skill.py -v`
Expected: FAIL with `assert 'create_event' in [...]` (capture's current tools list excludes it)

- [ ] **Step 3: Edit `capture.md` — add the tool**

In `memory/00-system/mazkir-skills/capture.md` frontmatter, the `tools:` list currently is:

```yaml
tools:
  - save_knowledge
  - attach_to_daily
  - edit_daily_section
  - create_task
  - create_habit
  - create_goal
  - daily_add_task
  - daily_set_task_state
```

Add `create_event`:

```yaml
tools:
  - save_knowledge
  - attach_to_daily
  - edit_daily_section
  - create_task
  - create_habit
  - create_goal
  - create_event
  - daily_add_task
  - daily_set_task_state
```

- [ ] **Step 4: Edit `capture.md` — add the classification rule**

In the prompt body, the classification bullet currently reads:

```markdown
- Classify the content: is it a task to do, an idea / fact worth remembering, a note for the daily log, or a new habit / goal to track?
```

Replace it with a version that names the event case, and add a worked example after the bullet list:

```markdown
- Classify the content: is it a task to do, a **timed event** (something that happened or will happen at a specific time / timeframe), an idea / fact worth remembering, a note for the daily log, or a new habit / goal to track?
- **Timed events use `create_event`, not `save_knowledge`.** If the content is anchored to a clock time or a timeframe (e.g. "met X from 20:00 to 22:30", "lunch at noon", "dentist tomorrow 3pm"), call `create_event` with `name`, `start_time`, optional `end_time`, `location`, and `wikilinks`. This records it in the daily note's ## Schedule section and syncs it to the calendar. Reserve `save_knowledge` for timeless facts, ideas, and quotes with no time anchor.

Example — user says "I attended a pub meeting with former colleagues from Momentick today between 20:00 to 22:30 at Shnitt brewery":
→ `create_event(name="Pub meeting with Momentick colleagues", start_time="20:00", end_time="22:30", location={"name": "Shnitt brewery"}, wikilinks=["Momentick"])`
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest tests/test_capture_skill.py -v`
Expected: PASS

- [ ] **Step 6: Commit (code repo + vault repo)**

```bash
git add tests/test_capture_skill.py
git commit -m "test(vault-server): guard capture skill declares create_event"
cd ~/dev/mazkir/memory
git add 00-system/mazkir-skills/capture.md
git commit -m "feat(vault): capture skill gains create_event + timed-event rule"
cd ~/dev/mazkir/apps/vault-server
```

---

### Task 5: Full test sweep + CLAUDE.md note

**Files:**
- Modify: `CLAUDE.md` (P5 section — note the unified create_event behavior)

- [ ] **Step 1: Run the vault-server test suite**

Run: `pytest tests/ -q`
Expected: PASS (no regressions; new tests from Tasks 1, 2, 4 included)

- [ ] **Step 2: Update CLAUDE.md**

In `CLAUDE.md`, under the agent-tools / P5 area, add a bullet:

```markdown
- **Unified timed-event capture:** `create_event` is the canonical "timed thing" action — it writes the events store, syncs Google Calendar (best-effort), AND appends a line to the daily note's `## Schedule` section (`services/daily_schedule.py`), skipped for `photo_path` events. The `capture` skill now includes `create_event` and a prompt rule routing time-anchored content there instead of `save_knowledge`.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude-md): document unified create_event timed-event capture"
```

---

## Self-Review

**Spec coverage:**
- `## Schedule` section + parser → Task 1, Task 3. ✓
- Unified `create_event` (events store + daily note + GCal, photo skip, best-effort) → Task 2. ✓
- `capture` gains `create_event` + prompt rule + worked example → Task 4. ✓
- No new `/day` source → nothing to build (explicitly out of scope). ✓
- Regression guard for timeless facts → this is LLM-classification behavior, not unit-testable
  deterministically; covered by the prompt rule + worked example in Task 4 and verified manually
  (see Manual Verification below). The deterministic guard is `test_capture_skill_has_create_event`.

**Placeholder scan:** No TBD/TODO; every code step shows full code. ✓

**Type consistency:** `ScheduleEntry(start, end, text)`, `parse_schedule_section`,
`render_schedule_section` used identically in Tasks 1 and 2. `replace_or_append_section` reused
from `daily_tasks.py` with section name `"Schedule"`. `_extract_hhmm` is the existing local
helper in `_tool_create_event`. ✓

## Manual Verification (post-implementation)

The classification behavior (capture choosing `create_event` over `save_knowledge`) is an LLM
decision, not covered by unit tests. After implementation, verify end-to-end:

1. Start vault-server + bot (see CLAUDE.md Quick Commands).
2. Send: *"I attended a pub meeting with former colleagues from Momentick today between 20:00 to 22:30 at Shnitt brewery."*
3. Confirm: a `## Schedule` line appears in today's daily note, an event lands in `data/events/{today}.json`, and (if GCal is configured) a Mazkir calendar event is created.
4. Send a timeless fact: *"Espresso has more caffeine per ml than drip coffee."* → confirm it still goes to `save_knowledge`, not `create_event`.
5. Cross-check the Phoenix trace: `skill.capture` → `create_event` tool call.
