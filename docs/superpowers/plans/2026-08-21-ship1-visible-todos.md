# Ship 1 — Visible Todos Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every checkbox in a daily note visible in `/day`, wherever in the note it lives and whether or not it has a time.

**Architecture:** `parse_tasks_section` already parses checkbox lines correctly — it is only scoped to the `## Tasks` section by one regex, and `/day` then discards anything without a `scheduled_at`. This plan extracts the line-parsing loop into a reusable helper, adds a whole-note `parse_all_todos`, returns those todos from `/day` as their own list, and stops `## Notes` checkboxes from rendering as note prose. No write path changes.

**Tech Stack:** Python 3.14 / FastAPI / pytest on the server; TypeScript / grammY / vitest on the bot; `@mazkir/shared-types` between them.

**Spec:** `docs/plans/2026-08-21-time-management-phase2-capture-design.md` §8

## Global Constraints

- Every agent tool returns the `{ok, data|error, _items}` shape from `src/services/tool_response.py`. Never a bare dict. (No tools change here, but the constraint binds any that do.)
- `tests/conftest.py` redirects `LOGS_DIR` and `MAZKIR_AUDIT_LOG_PATH` to temp dirs. No test may write to `data/logs/`.
- `memory/` is the user's live Obsidian vault — a separate nested git repo, gitignored, and **absent from a worktree**. Never write to a path starting `memory/`.
- Server tests run from `apps/vault-server` with the venv active: `source venv/bin/activate && python -m pytest tests/ -q`. The venv is a symlink; never recreate it.
- Baseline: **732 server tests passing**, plus one pre-existing `StarletteDeprecationWarning` from `fastapi/testclient.py`. Bot: `npx vitest run` from `apps/telegram-bot`.
- **Write paths are out of scope.** `daily_add_task` and friends keep writing to `## Tasks`. This ship is read-side only.
- Commit per task, conventional prefixes.

## File Structure

**Modified:**
- `apps/vault-server/src/services/daily_tasks.py` — extract `_parse_todo_line`, add `is_todo_line` and `parse_all_todos`. Keeps one parsing rule rather than a second copy that can drift.
- `apps/vault-server/src/api/routes/daily.py` — add `todos[]` to the response; exclude checkbox lines from `notes[]`.
- `packages/shared-types/src/daily.ts` — `DailyTodo`, extended `DailyResponse`.
- `apps/telegram-bot/src/formatters/telegram.ts` — render a Todos block.

**Tests:**
- `apps/vault-server/tests/test_daily_tasks.py`
- `apps/vault-server/tests/test_daily_route.py`
- `apps/telegram-bot/tests/formatters/telegram.test.ts`

## Design decisions this plan locks in

1. **A todo is any checkbox line in the daily note**, regardless of section. Section provenance is preserved on each todo so callers can tell where it came from.
2. **`schedule[]` is unchanged.** Timed checkboxes keep appearing there. `todos[]` carries *every* checkbox including timed ones, so the API is a faithful representation of the note; the bot renders only untimed ones under Todos, because timed ones are already in the schedule above.
3. **`moved` todos are excluded** from `todos[]`. A struck-through line has been rolled to another day and is not outstanding.
4. **A checkbox in `## Notes` is a todo, not a note.** Without this it renders twice — once as a todo and once as note prose reading `[ ] Buy milk`.

---

### Task 1: Parse checkboxes from anywhere in the note

**Files:**
- Modify: `apps/vault-server/src/services/daily_tasks.py`
- Test: `apps/vault-server/tests/test_daily_tasks.py`

**Interfaces:**
- Consumes: the existing `DailyTask` dataclass and `_LINE_RE` / `_TIME_RE` / `_DURATION_RE` / `_STRIKE_RE` module regexes.
- Produces, used by Task 2:
  - `@dataclass(frozen=True) Todo: text: str, state: TaskState, section: str, scheduled_at: str | None, duration_minutes: int | None`
  - `parse_all_todos(body: str) -> list[Todo]` — every checkbox line in the note, in document order, `moved` excluded. `section` is the enclosing `## Heading` text, or `""` for a checkbox above the first heading.
  - `is_todo_line(line: str) -> bool` — True when a single raw line is a checkbox. Public so callers outside this module can filter checkboxes out of prose without reaching for a private helper.

- [ ] **Step 1: Write the failing tests**

Append to `apps/vault-server/tests/test_daily_tasks.py`:

```python
from src.services.daily_tasks import parse_all_todos

WHOLE_NOTE = """\
- [ ] Stray above any heading

## Tasks
- [ ] 14:00 — Visit dentist (60m)
- [x] Walk dog
- [ ] ~~Order phone~~ — moved to [[2026-06-05#Tasks]]

## Notes
- Bought dog food
- [ ] Order dog food (30m)

## Schedule
09:00–10:00 Standup
"""


def test_collects_checkboxes_from_every_section():
    todos = parse_all_todos(WHOLE_NOTE)
    assert [t.text for t in todos] == [
        "Stray above any heading",
        "Visit dentist",
        "Walk dog",
        "Order dog food",
    ]


def test_records_the_enclosing_section():
    todos = {t.text: t.section for t in parse_all_todos(WHOLE_NOTE)}
    assert todos["Stray above any heading"] == ""
    assert todos["Visit dentist"] == "Tasks"
    assert todos["Order dog food"] == "Notes"


def test_moved_todos_are_excluded():
    assert "Order phone" not in [t.text for t in parse_all_todos(WHOLE_NOTE)]


def test_preserves_time_duration_and_state():
    by_text = {t.text: t for t in parse_all_todos(WHOLE_NOTE)}
    assert by_text["Visit dentist"].scheduled_at == "14:00"
    assert by_text["Visit dentist"].duration_minutes == 60
    assert by_text["Visit dentist"].state == "unchecked"
    assert by_text["Walk dog"].state == "checked"
    assert by_text["Order dog food"].duration_minutes == 30


def test_plain_bullets_are_not_todos():
    assert "Bought dog food" not in [t.text for t in parse_all_todos(WHOLE_NOTE)]


def test_note_with_no_checkboxes_returns_empty():
    assert parse_all_todos("## Notes\n- just a thought\n") == []


def test_is_todo_line_identifies_checkboxes():
    from src.services.daily_tasks import is_todo_line
    assert is_todo_line("- [ ] Order dog food") is True
    assert is_todo_line("- [x] Walk dog") is True
    assert is_todo_line("- Bought dog food") is False
    assert is_todo_line("## Notes") is False
    assert is_todo_line("") is False


def test_parse_tasks_section_still_scoped_to_tasks():
    """The existing write-path parser must not start seeing Notes checkboxes."""
    from src.services.daily_tasks import parse_tasks_section
    texts = [t.text for t in parse_tasks_section(WHOLE_NOTE)]
    assert "Order dog food" not in texts
    assert "Visit dentist" in texts
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_daily_tasks.py -v -k "parse_all_todos or checkboxes or enclosing or moved_todos or preserves_time or plain_bullets or no_checkboxes or still_scoped"`
Expected: ImportError — `cannot import name 'parse_all_todos'`.

- [ ] **Step 3: Extract the line parser**

In `apps/vault-server/src/services/daily_tasks.py`, add above `parse_tasks_section`:

```python
_HEADING_RE = re.compile(r"^##\s+(?P<name>.+?)\s*$")


def _parse_todo_line(line: str) -> dict | None:
    """Parse one checkbox line. Returns None for anything that isn't one.

    Shares the module's regexes with `parse_tasks_section` so the two
    cannot drift apart on what a checkbox looks like.
    """
    lm = _LINE_RE.match(line)
    if not lm or lm.group("box") is None:
        return None

    text = lm.group("rest")
    state: TaskState = "checked" if lm.group("box") == "x" else "unchecked"
    scheduled_at = None
    duration = None

    sm = _STRIKE_RE.match(text)
    if sm:
        state = "moved"
        text = sm.group("text")

    tm = _TIME_RE.match(text)
    if tm:
        scheduled_at = tm.group("time")
        text = tm.group("text")

    dm = _DURATION_RE.search(text)
    if dm:
        duration = int(dm.group("n"))
        text = _DURATION_RE.sub("", text).rstrip()

    return {
        "text": text.strip(),
        "state": state,
        "scheduled_at": scheduled_at,
        "duration_minutes": duration,
    }
```

- [ ] **Step 4: Add the public predicate, the Todo dataclass, and `parse_all_todos`**

Add below `_parse_todo_line`:

```python
def is_todo_line(line: str) -> bool:
    """True when `line` is a checkbox. Public so other modules can filter
    checkboxes out of prose without importing a private helper."""
    return _parse_todo_line(line) is not None
```

and then:

```python
@dataclass(frozen=True)
class Todo:
    """A checkbox anywhere in a daily note.

    Distinct from `DailyTask`, which models the nested `## Tasks` tree the
    write tools edit. A Todo is flat and carries the section it came from.
    """
    text: str
    state: TaskState
    section: str
    scheduled_at: str | None = None
    duration_minutes: int | None = None


def parse_all_todos(body: str) -> list[Todo]:
    """Every outstanding checkbox in the note, in document order.

    Section-agnostic: a checkbox under `## Notes` is as much a todo as one
    under `## Tasks`. `moved` items are excluded — they have been rolled to
    another day and are no longer outstanding.
    """
    todos: list[Todo] = []
    section = ""
    for line in body.splitlines():
        hm = _HEADING_RE.match(line)
        if hm:
            section = hm.group("name")
            continue
        fields = _parse_todo_line(line)
        if fields is None or fields["state"] == "moved":
            continue
        todos.append(Todo(section=section, **fields))
    return todos
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_daily_tasks.py -v`
Expected: all passed, including the pre-existing 14.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: 740 passed (732 + 8 new), 1 pre-existing warning.

- [ ] **Step 7: Commit**

```bash
git add apps/vault-server/src/services/daily_tasks.py \
        apps/vault-server/tests/test_daily_tasks.py
git commit -m "feat(daily): parse checkboxes from any section of a daily note"
```

---

### Task 2: `/day` returns todos and stops rendering them as notes

**Files:**
- Modify: `apps/vault-server/src/api/routes/daily.py`
- Test: `apps/vault-server/tests/test_daily_route.py`

**Interfaces:**
- Consumes: `parse_all_todos(body) -> list[Todo]` and the `Todo` dataclass from Task 1.
- Produces: `DailyResponse` gains `todos: list[DailyTodo]`, where `DailyTodo` is `{text: str, done: bool, section: str, scheduled_at: str | None, duration_minutes: int | None}`. `notes[]` no longer contains checkbox lines.

- [ ] **Step 1: Write the failing tests**

Append to `apps/vault-server/tests/test_daily_route.py`:

```python
class TestDayTodos:
    """Bug A: a checkbox with no time was parsed and then silently dropped."""

    NOTE = (
        "## Tasks\n"
        "- [ ] Order dog food (30m)\n"
        "- [ ] 14:00 — Visit dentist (60m)\n"
        "\n"
        "## Notes\n"
        "- Bought dog food today\n"
        "- [ ] Bring the bicycle to repair shop (60m)\n"
    )

    def test_untimed_todos_are_returned(self):
        from src.api.routes.daily import _build_todos
        texts = [t.text for t in _build_todos(self.NOTE)]
        assert "Order dog food" in texts
        assert "Bring the bicycle to repair shop" in texts

    def test_timed_todos_are_also_returned(self):
        from src.api.routes.daily import _build_todos
        by_text = {t.text: t for t in _build_todos(self.NOTE)}
        assert by_text["Visit dentist"].scheduled_at == "14:00"

    def test_duration_survives(self):
        from src.api.routes.daily import _build_todos
        by_text = {t.text: t for t in _build_todos(self.NOTE)}
        assert by_text["Order dog food"].duration_minutes == 30

    def test_section_is_reported(self):
        from src.api.routes.daily import _build_todos
        by_text = {t.text: t for t in _build_todos(self.NOTE)}
        assert by_text["Order dog food"].section == "Tasks"
        assert by_text["Bring the bicycle to repair shop"].section == "Notes"

    def test_checkbox_in_notes_is_not_also_a_note(self):
        """Otherwise it renders twice — once as a todo, once as '[ ] …' prose."""
        from src.api.routes.daily import _build_notes
        texts = [n.text for n in _build_notes(self.NOTE) if n.text]
        assert texts == ["Bought dog food today"]

    def test_done_flag_reflects_the_box(self):
        from src.api.routes.daily import _build_todos
        note = "## Tasks\n- [x] Walk dog\n- [ ] Order dog food\n"
        by_text = {t.text: t.done for t in _build_todos(note)}
        assert by_text["Walk dog"] is True
        assert by_text["Order dog food"] is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_daily_route.py -v -k TestDayTodos`
Expected: ImportError — `cannot import name '_build_todos'`.

- [ ] **Step 3: Add the response model and the two builders**

In `apps/vault-server/src/api/routes/daily.py`, add `parse_all_todos` to the existing `daily_tasks` import, then add the model beside `DailyNote`:

```python
class DailyTodo(BaseModel):
    text: str
    done: bool = False
    section: str = ""
    scheduled_at: str | None = None
    duration_minutes: int | None = None
```

Add `todos` to `DailyResponse`:

```python
class DailyResponse(BaseModel):
    date: str
    tokens_today: int
    tokens_total: int
    schedule: list[DailyScheduleItem]
    todos: list[DailyTodo]
    notes: list[DailyNote]
```

Add both builders beside `_habit_scheduled_at`:

```python
def _build_todos(content: str) -> list[DailyTodo]:
    """Every outstanding checkbox in the note, wherever it lives.

    `schedule[]` only carries checkboxes that have a time, so without this
    an untimed todo is parsed and then silently dropped.
    """
    return [
        DailyTodo(
            text=t.text,
            done=t.state == "checked",
            section=t.section,
            scheduled_at=t.scheduled_at,
            duration_minutes=t.duration_minutes,
        )
        for t in parse_all_todos(content)
    ]


def _build_notes(content: str) -> list[DailyNote]:
    """Prose and photos from `## Notes` — checkboxes there are todos, not notes."""
    notes: list[DailyNote] = []
    for line in _extract_section(content, "Notes").splitlines():
        if is_todo_line(line):
            continue
        stripped = line.strip().lstrip("- ").strip()
        if not stripped:
            continue
        img_match = re.match(r"!\[([^\]]*)\]\(([^)]*)\)", stripped)
        if img_match:
            notes.append(DailyNote(
                caption=img_match.group(1) or None,
                photo_path=img_match.group(2) or None,
            ))
        else:
            notes.append(DailyNote(text=stripped))
    return notes
```

Import `is_todo_line` alongside `parse_all_todos` — both are public members of `src.services.daily_tasks`.

- [ ] **Step 4: Use the builders in the route**

In `get_daily`, replace the inline notes loop with a call to `_build_notes(content)`, and add todos to the returned model:

```python
    notes = _build_notes(content)
    todos = _build_todos(content)
```

and in the `return DailyResponse(...)`, add `todos=todos,` before `notes=notes,`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_daily_route.py -v`
Expected: all passed.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: 746 passed (740 + 6 new).

- [ ] **Step 7: Verify against the real note that triggered the bug**

```bash
source venv/bin/activate && python -c "
from src.api.routes.daily import _build_todos
body = open('/home/marcellmc/dev/mazkir/memory/10-daily/2026-08-20.md').read()
for t in _build_todos(body):
    print(f'{t.text[:45]:45} done={t.done} sched={t.scheduled_at} dur={t.duration_minutes}')
"
```

Expected: both todos listed — `Order dog food` (30m) and `Bring the bicycle to repair shop …` (60m). This is the exact case that was invisible.

- [ ] **Step 8: Commit**

```bash
git add apps/vault-server/src/api/routes/daily.py \
        apps/vault-server/tests/test_daily_route.py
git commit -m "fix(daily): return untimed todos from /day (Bug A)"
```

---

### Task 3: Render todos in the bot

**Files:**
- Modify: `packages/shared-types/src/daily.ts`
- Modify: `apps/telegram-bot/src/formatters/telegram.ts:51-77`
- Test: `apps/telegram-bot/tests/formatters/telegram.test.ts`

**Interfaces:**
- Consumes: the `/day` response shape from Task 2.
- Produces: `formatDay` renders a `☑️ Todos` block listing todos **without** a `scheduled_at`. Timed todos are omitted here because `schedule[]` already shows them above.

- [ ] **Step 1: Add the shared types**

In `packages/shared-types/src/daily.ts`, add beside `DailyNote`:

```typescript
export interface DailyTodo {
  text: string;
  done: boolean;
  section: string;
  scheduled_at: string | null;
  duration_minutes: number | null;
}
```

and add to `DailyResponse`, between `schedule` and `notes`:

```typescript
  todos: DailyTodo[];
```

- [ ] **Step 2: Write the failing tests**

Append to `apps/telegram-bot/tests/formatters/telegram.test.ts`:

```typescript
describe("formatDay todos", () => {
  const base = {
    date: "2026-08-20",
    tokens_today: 0,
    tokens_total: 0,
    schedule: [],
    notes: [],
  };

  it("lists untimed todos", () => {
    const out = formatDay({
      ...base,
      todos: [
        { text: "Order dog food", done: false, section: "Tasks",
          scheduled_at: null, duration_minutes: 30 },
      ],
    } as never);
    expect(out).toContain("Order dog food");
    expect(out).toContain("30m");
  });

  it("marks done todos", () => {
    const out = formatDay({
      ...base,
      todos: [
        { text: "Walk dog", done: true, section: "Tasks",
          scheduled_at: null, duration_minutes: null },
      ],
    } as never);
    expect(out).toContain("☑️ Walk dog");
  });

  it("omits timed todos, which the schedule already shows", () => {
    const out = formatDay({
      ...base,
      schedule: [{ start: "14:00", title: "Visit dentist",
                   source: "daily-task", completed: false }],
      todos: [
        { text: "Visit dentist", done: false, section: "Tasks",
          scheduled_at: "14:00", duration_minutes: 60 },
      ],
    } as never);
    expect(out.match(/Visit dentist/g)).toHaveLength(1);
  });

  it("renders no todo block when there are none", () => {
    const out = formatDay({ ...base, todos: [] } as never);
    expect(out).not.toContain("Todos");
  });
});
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd apps/telegram-bot && npx vitest run tests/formatters/telegram.test.ts`
Expected: FAIL — the todo text is absent from the output.

- [ ] **Step 4: Render the block**

In `apps/telegram-bot/src/formatters/telegram.ts`, insert between the schedule block and the notes block in `formatDay`:

```typescript
  const untimed = (data.todos ?? []).filter((t) => !t.scheduled_at);
  if (untimed.length > 0) {
    if (data.schedule.length > 0) lines.push("");
    lines.push("☑️ <b>Todos</b>");
    for (const t of untimed) {
      const box = t.done ? "☑️" : "☐";
      const dur = t.duration_minutes ? ` <i>(${t.duration_minutes}m)</i>` : "";
      lines.push(`  ${box} ${t.text}${dur}`);
    }
  }
```

Change the `if (data.notes && ...)` guard's preceding blank-line rule to account for the new block:

```typescript
  if (data.notes && data.notes.length > 0) {
    if (data.schedule.length > 0 || untimed.length > 0) lines.push("");
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd apps/telegram-bot && npx vitest run tests/formatters/telegram.test.ts`
Expected: all passed.

- [ ] **Step 6: Typecheck and run everything**

```bash
cd /home/marcellmc/dev/mazkir && npx tsc -b packages/shared-types && npx turbo test
```
Expected: clean typecheck, all packages green.

- [ ] **Step 7: Commit**

```bash
git add packages/shared-types/src/daily.ts \
        apps/telegram-bot/src/formatters/telegram.ts \
        apps/telegram-bot/tests/formatters/telegram.test.ts
git commit -m "feat(bot): render daily todos in /day"
```

---

### Task 4: Correct two stale claims in CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:** none — documentation only.

Both were verified false during Phase 1: a reviewer type-checked both revisions against the real 354-package dependency tree and found the webapp clean, and `apps/telegram-web-app/src/features/` contains `time-management/` and `playground/`, with no `dayplanner/`.

- [ ] **Step 1: Confirm both claims are still wrong**

```bash
cd /home/marcellmc/dev/mazkir
grep -n "dayplanner" CLAUDE.md
ls apps/telegram-web-app/src/features/
```

Expected: `CLAUDE.md` mentions `dayplanner`; the directory listing shows `playground` and `time-management` only. If `dayplanner/` does exist, stop and report — the doc would be right and this task is void.

- [ ] **Step 2: Fix the webapp structure section**

In `CLAUDE.md`, in the repository-structure block under `apps/telegram-web-app/src/features/`, replace the `dayplanner/` entry with:

```
│       │       ├── time-management/   # Daily/weekly note feed with date scrubber
```

and in the "Telegram Mini App (Web)" capabilities section, replace the `**Dayplanner**` bullet with:

```
- **Time-management** - Continuous virtualized feed of daily and weekly notes with a date scrubber, rendered faithfully (sections, photos, wikilinks)
```

- [ ] **Step 3: Remove the stale pre-existing-errors claim**

Search for the sentence claiming the webapp has known pre-existing `tsc` errors around `import.meta.env`:

```bash
grep -n "import.meta.env\|pre-existing tsc" CLAUDE.md
```

Delete that clause. It sent Phase 1 implementers hunting for errors that do not exist, and one correctly reported being unable to reproduce them.

- [ ] **Step 4: Verify the doc no longer contradicts the tree**

```bash
grep -c "dayplanner" CLAUDE.md   # expect 0
grep -c "import.meta.env" CLAUDE.md   # expect 0
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: correct stale webapp claims in CLAUDE.md"
```

---

## Verification

- [ ] `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/ -q` — 746 passed
- [ ] `cd /home/marcellmc/dev/mazkir && npx turbo test` — all packages green
- [ ] `git status --porcelain` clean in the code repo
- [ ] End-to-end against the live note:

```bash
cd apps/vault-server && source venv/bin/activate \
  && python -m uvicorn src.main:app --port 8000 &
sleep 3 && curl -s localhost:8000/daily | jq '{todos, notes}'
```

Expected: `todos` contains `Order dog food` and `Bring the bicycle to repair shop`; `notes` contains no `[ ]` prose.

## Out of scope

- **Write paths.** `daily_add_task`, `daily_set_task_state`, `daily_rollover` and `promote_daily_task` remain `## Tasks`-scoped. A todo written into `## Notes` by hand will be *visible* after this ship but not yet checkable by asking Mazkir — that matcher widens in Ship 4 (NL logging and editing).
- **Date navigation** — Ship 2.
- **Blocks, approval, classification** — Ships 4 onward.
