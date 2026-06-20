# Time-management Web App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `dayplanner` web feature with `time-management`: a virtualized, newest-first feed of all daily/weekly notes rendered faithfully (sections, photos, wikilinks, interactive checkboxes), with a date scrubber and back-to-top, in an editorial "paper journal" aesthetic.

**Architecture:** New vault-server `NotesService` + `/notes` router exposes a lightweight metadata list, per-note raw markdown, a checkbox-flip write, and a random knowledge note. A new React feature renders the feed with `@tanstack/react-virtual` (dynamic measurement), `@tanstack/react-query` (list + lazy body caching + optimistic checkbox mutation), and `react-markdown`+`remark-gfm` with custom Obsidian transforms.

**Tech Stack:** Python/FastAPI/pytest (backend); React 18 + Vite + Tailwind + Zustand-era webapp, adding `@tanstack/react-virtual`, `@tanstack/react-query`, `react-markdown`, `remark-gfm`; Vitest + Testing Library.

**Design reference:** `docs/prototype.html` (paper/editorial design language). Spec: `docs/superpowers/specs/2026-06-20-time-management-webapp-design.md`. When building UI, consult the `frontend-design:frontend-design` skill.

---

## File Structure

**vault-server (backend)**
- Create: `apps/vault-server/src/services/notes_service.py` — `NotesService`: scan `10-daily/`, derive `kind`/`sort_key`/metadata, read body, flip checkbox, random knowledge note.
- Create: `apps/vault-server/src/api/routes/notes.py` — `/notes` router (list, read, checkbox PATCH, featured).
- Modify: `apps/vault-server/src/main.py` — construct `NotesService`, add `get_notes()` accessor, register router.
- Create: `apps/vault-server/tests/test_notes_service.py` — service unit tests.
- Create: `apps/vault-server/tests/test_notes_route.py` — route tests via `TestClient`.

**telegram-web-app (frontend)**
- Modify: `apps/telegram-web-app/package.json` — add 4 deps.
- Modify: `apps/telegram-web-app/src/main.tsx` — wrap app in `QueryClientProvider`.
- Modify: `apps/telegram-web-app/src/services/api.ts` — add `listNotes`, `getNote`, `setNoteCheckbox`, `getFeaturedNote`.
- Create: `apps/telegram-web-app/src/models/note.ts` — TS interfaces.
- Create: `apps/telegram-web-app/src/features/time-management/theme.css` — design tokens + paper texture + fonts.
- Create: `apps/telegram-web-app/src/features/time-management/obsidian.ts` — markdown transforms (`![[ ]]`, `[[ ]]`) + checkbox line mapping.
- Create: `apps/telegram-web-app/src/features/time-management/scrubber.ts` — date↔offset math (pure, tested).
- Create: `apps/telegram-web-app/src/features/time-management/components/NoteMarkdown.tsx`
- Create: `apps/telegram-web-app/src/features/time-management/components/NoteDay.tsx`
- Create: `apps/telegram-web-app/src/features/time-management/components/FeaturedNote.tsx`
- Create: `apps/telegram-web-app/src/features/time-management/components/DateScrubber.tsx`
- Create: `apps/telegram-web-app/src/features/time-management/components/BackToTopFab.tsx`
- Create: `apps/telegram-web-app/src/features/time-management/components/NoteFeed.tsx`
- Create: `apps/telegram-web-app/src/features/time-management/TimeManagementPage.tsx`
- Modify: `apps/telegram-web-app/src/app/Router.tsx` — route swap + redirect.
- Delete: `apps/telegram-web-app/src/features/dayplanner/` (whole dir).
- Create tests under `apps/telegram-web-app/src/features/time-management/__tests__/`.

---

## Task 1: NotesService — kind & sort_key derivation

**Files:**
- Create: `apps/vault-server/src/services/notes_service.py`
- Test: `apps/vault-server/tests/test_notes_service.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for NotesService."""
import datetime
import pytest
from src.services.notes_service import derive_kind, derive_sort_key


class TestDerive:
    def test_daily_kind_and_sort_key(self):
        assert derive_kind("2026-05-21") == "daily"
        assert derive_sort_key("2026-05-21") == "2026-05-21"

    def test_weekly_kind(self):
        assert derive_kind("2022-W34") == "weekly"

    def test_weekly_sort_key_is_last_day_of_iso_week(self):
        # ISO week 34 of 2022: Monday 2022-08-22 .. Sunday 2022-08-28
        assert derive_sort_key("2022-W34") == "2022-08-28"

    def test_weekly_sort_key_week_one(self):
        # ISO week 1 of 2023: ends Sunday 2023-01-08
        assert derive_sort_key("2023-W01") == "2023-01-08"

    def test_unknown_stem_is_daily_fallback(self):
        # Non-matching names sort by themselves, treated as daily
        assert derive_kind("random-note") == "daily"
        assert derive_sort_key("random-note") == "random-note"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_notes_service.py -v`
Expected: FAIL with `ImportError: cannot import name 'derive_kind'`

- [ ] **Step 3: Write minimal implementation**

```python
"""NotesService — read the daily/weekly note feed for the time-management app."""
import datetime
import re

_DAILY_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_WEEKLY_RE = re.compile(r"^(\d{4})-W(\d{2})$")


def derive_kind(stem: str) -> str:
    """Classify a note filename stem as 'weekly' or 'daily'."""
    return "weekly" if _WEEKLY_RE.match(stem) else "daily"


def derive_sort_key(stem: str) -> str:
    """Return an ISO date string used to order notes newest-first.

    Dailies sort by their own date. Weeklies are anchored to the LAST day
    (Sunday) of their ISO week, so they land where the week concluded.
    Unrecognized stems sort by themselves.
    """
    m = _WEEKLY_RE.match(stem)
    if m:
        year, week = int(m.group(1)), int(m.group(2))
        # ISO weekday 7 = Sunday, the last day of the ISO week.
        sunday = datetime.date.fromisocalendar(year, week, 7)
        return sunday.isoformat()
    if _DAILY_RE.match(stem):
        return stem
    return stem
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_notes_service.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/notes_service.py apps/vault-server/tests/test_notes_service.py
git commit -m "feat(notes): derive note kind + sort_key (weekly anchored to week end)"
```

---

## Task 2: NotesService — snippet & has_photos extraction

**Files:**
- Modify: `apps/vault-server/src/services/notes_service.py`
- Test: `apps/vault-server/tests/test_notes_service.py`

- [ ] **Step 1: Write the failing test (append to the file)**

```python
from src.services.notes_service import extract_snippet, has_photo_embed


class TestSnippet:
    def test_has_photo_embed_true(self):
        assert has_photo_embed("intro\n![[photo_2026-05-21.jpg]]\n") is True

    def test_has_photo_embed_false(self):
        assert has_photo_embed("just text, no embeds") is False

    def test_snippet_strips_headers_and_markdown(self):
        body = "# Title\n\n## Notes\n- Bought **kebabs** for the picnic\n"
        snip = extract_snippet(body)
        assert snip.startswith("Bought kebabs for the picnic")
        assert "#" not in snip
        assert "*" not in snip

    def test_snippet_truncates_to_140_chars(self):
        body = "x " * 200
        assert len(extract_snippet(body)) <= 140

    def test_snippet_empty_body(self):
        assert extract_snippet("") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_notes_service.py::TestSnippet -v`
Expected: FAIL with `ImportError: cannot import name 'extract_snippet'`

- [ ] **Step 3: Write minimal implementation (append to `notes_service.py`)**

```python
_PHOTO_RE = re.compile(r"!\[\[[^\]]+\]\]")
_HEADER_RE = re.compile(r"^#{1,6}\s*", re.MULTILINE)
_MD_TOKENS_RE = re.compile(r"[*_`>#\[\]!]|\!\[\[|\]\]")


def has_photo_embed(body: str) -> bool:
    """True if the body contains an Obsidian image embed."""
    return bool(_PHOTO_RE.search(body))


def extract_snippet(body: str, limit: int = 140) -> str:
    """First ~limit chars of human prose: drop frontmatter-free body's
    headers/list markers/markdown tokens, collapse whitespace."""
    text = _PHOTO_RE.sub("", body)
    text = _HEADER_RE.sub("", text)
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        line = line.lstrip("-* ").strip()       # list markers
        line = _MD_TOKENS_RE.sub("", line)       # leftover markdown tokens
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    snippet = " ".join(lines)
    return snippet[:limit].strip()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_notes_service.py::TestSnippet -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/notes_service.py apps/vault-server/tests/test_notes_service.py
git commit -m "feat(notes): snippet + photo-embed extraction"
```

---

## Task 3: NotesService — list_notes (newest-first)

**Files:**
- Modify: `apps/vault-server/src/services/notes_service.py`
- Test: `apps/vault-server/tests/test_notes_service.py`

- [ ] **Step 1: Write the failing test (append)**

```python
from pathlib import Path
from src.services.vault_service import VaultService
from src.services.notes_service import NotesService


def _make_vault(tmp_path: Path) -> VaultService:
    vault = tmp_path / "vault"
    (vault / "10-daily").mkdir(parents=True)
    (vault / "AGENTS.md").write_text("# Agents\n")
    return VaultService(vault)


class TestListNotes:
    def test_orders_newest_first_with_weekly_anchored(self, tmp_path):
        v = _make_vault(tmp_path)
        d = v.vault_path / "10-daily"
        (d / "2026-05-20.md").write_text("---\ntype: daily\n---\n\nolder day\n")
        (d / "2026-05-21.md").write_text("---\ntype: daily\n---\n\nnewer day\n")
        # ISO week 20 of 2026 ends Sunday 2026-05-17, so this sorts oldest.
        (d / "2026-W20.md").write_text("---\ntype: daily\n---\n\nweek note\n")

        notes = NotesService(v).list_notes()
        ids = [n["id"] for n in notes]
        assert ids == ["2026-05-21", "2026-05-20", "2026-W20"]
        assert notes[2]["kind"] == "weekly"
        assert notes[2]["sort_key"] == "2026-05-17"

    def test_list_item_shape(self, tmp_path):
        v = _make_vault(tmp_path)
        (v.vault_path / "10-daily" / "2026-05-21.md").write_text(
            "---\ntype: daily\n---\n\n## Notes\nBought kebabs\n![[p.jpg]]\n"
        )
        note = NotesService(v).list_notes()[0]
        assert set(note) == {"id", "sort_key", "kind", "title", "has_photos", "snippet"}
        assert note["has_photos"] is True
        assert "kebabs" in note["snippet"]

    def test_empty_dir_returns_empty(self, tmp_path):
        v = _make_vault(tmp_path)
        assert NotesService(v).list_notes() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_notes_service.py::TestListNotes -v`
Expected: FAIL with `ImportError: cannot import name 'NotesService'`

- [ ] **Step 3: Write minimal implementation (append)**

```python
class NotesService:
    """Reads the daily/weekly note feed from the Obsidian vault."""

    def __init__(self, vault: "VaultServiceLike"):
        self.vault = vault

    def _daily_dir(self):
        return self.vault.vault_path / "10-daily"

    def list_notes(self) -> list[dict]:
        """All notes in 10-daily/, newest-first."""
        out = []
        d = self._daily_dir()
        if not d.exists():
            return out
        for f in d.glob("*.md"):
            stem = f.stem
            rel = f"10-daily/{f.name}"
            parsed = self.vault.read_file(rel)
            body = parsed.get("content", "")
            meta = parsed.get("metadata", {}) or {}
            out.append({
                "id": stem,
                "sort_key": derive_sort_key(stem),
                "kind": derive_kind(stem),
                "title": _title_for(stem, meta, body),
                "has_photos": has_photo_embed(body),
                "snippet": extract_snippet(body),
            })
        out.sort(key=lambda n: n["sort_key"], reverse=True)
        return out
```

Also add the `_title_for` helper near the other module functions:

```python
def _title_for(stem: str, meta: dict, body: str) -> str:
    """Prefer an H1 in the body, else a frontmatter title, else the stem."""
    m = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    if m:
        return m.group(1).strip()
    for key in ("title", "name"):
        if meta.get(key):
            return str(meta[key])
    return stem
```

Add a typing shim at the top (so the annotation resolves):

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.services.vault_service import VaultService as VaultServiceLike
else:
    VaultServiceLike = object
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_notes_service.py::TestListNotes -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/notes_service.py apps/vault-server/tests/test_notes_service.py
git commit -m "feat(notes): list_notes newest-first with metadata"
```

---

## Task 4: NotesService — read_note

**Files:**
- Modify: `apps/vault-server/src/services/notes_service.py`
- Test: `apps/vault-server/tests/test_notes_service.py`

- [ ] **Step 1: Write the failing test (append)**

```python
class TestReadNote:
    def test_read_returns_markdown_and_frontmatter(self, tmp_path):
        v = _make_vault(tmp_path)
        (v.vault_path / "10-daily" / "2026-05-21.md").write_text(
            "---\ntype: daily\nmood: good\n---\n\n## Notes\nhello\n"
        )
        note = NotesService(v).read_note("2026-05-21")
        assert note["id"] == "2026-05-21"
        assert note["kind"] == "daily"
        assert note["sort_key"] == "2026-05-21"
        assert note["frontmatter"]["mood"] == "good"
        assert "## Notes" in note["markdown"]
        assert "hello" in note["markdown"]

    def test_read_missing_raises(self, tmp_path):
        v = _make_vault(tmp_path)
        with pytest.raises(FileNotFoundError):
            NotesService(v).read_note("2099-01-01")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_notes_service.py::TestReadNote -v`
Expected: FAIL with `AttributeError: 'NotesService' object has no attribute 'read_note'`

- [ ] **Step 3: Write minimal implementation (add method to `NotesService`)**

```python
    def read_note(self, note_id: str) -> dict:
        """Raw markdown + frontmatter for one note. Raises FileNotFoundError."""
        rel = f"10-daily/{note_id}.md"
        if not (self.vault.vault_path / rel).exists():
            raise FileNotFoundError(rel)
        parsed = self.vault.read_file(rel)
        return {
            "id": note_id,
            "kind": derive_kind(note_id),
            "sort_key": derive_sort_key(note_id),
            "frontmatter": parsed.get("metadata", {}) or {},
            "markdown": parsed.get("content", ""),
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_notes_service.py::TestReadNote -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/notes_service.py apps/vault-server/tests/test_notes_service.py
git commit -m "feat(notes): read_note raw markdown + frontmatter"
```

---

## Task 5: NotesService — set_checkbox

**Files:**
- Modify: `apps/vault-server/src/services/notes_service.py`
- Test: `apps/vault-server/tests/test_notes_service.py`

- [ ] **Step 1: Write the failing test (append)**

```python
class TestSetCheckbox:
    def _vault_with_note(self, tmp_path):
        v = _make_vault(tmp_path)
        body = "## Tasks\n- [ ] Pack cooler\n- [ ] Buy charcoal\n"
        (v.vault_path / "10-daily" / "2026-05-21.md").write_text(
            "---\ntype: daily\nupdated: '2026-05-21'\n---\n\n" + body
        )
        return v

    def test_check_flips_the_right_line(self, tmp_path):
        v = self._vault_with_note(tmp_path)
        # body line numbering is 1-based within the markdown body (no frontmatter):
        # 1: "## Tasks", 2: "- [ ] Pack cooler", 3: "- [ ] Buy charcoal"
        note = NotesService(v).set_checkbox("2026-05-21", line=3, checked=True)
        assert "- [x] Buy charcoal" in note["markdown"]
        assert "- [ ] Pack cooler" in note["markdown"]

    def test_uncheck(self, tmp_path):
        v = self._vault_with_note(tmp_path)
        NotesService(v).set_checkbox("2026-05-21", line=2, checked=True)
        note = NotesService(v).set_checkbox("2026-05-21", line=2, checked=False)
        assert "- [ ] Pack cooler" in note["markdown"]

    def test_bumps_updated_frontmatter(self, tmp_path):
        v = self._vault_with_note(tmp_path)
        note = NotesService(v).set_checkbox("2026-05-21", line=2, checked=True)
        # VaultService.write_file always stamps 'updated' to today.
        assert note["frontmatter"]["updated"] != "2026-05-21"

    def test_non_checkbox_line_raises_value_error(self, tmp_path):
        v = self._vault_with_note(tmp_path)
        with pytest.raises(ValueError):
            NotesService(v).set_checkbox("2026-05-21", line=1, checked=True)

    def test_missing_note_raises_filenotfound(self, tmp_path):
        v = _make_vault(tmp_path)
        with pytest.raises(FileNotFoundError):
            NotesService(v).set_checkbox("2099-01-01", line=1, checked=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_notes_service.py::TestSetCheckbox -v`
Expected: FAIL with `AttributeError: ... 'set_checkbox'`

- [ ] **Step 3: Write minimal implementation (add method + module regex)**

Add near the top with the other regexes:

```python
_CHECKBOX_RE = re.compile(r"^(\s*[-*]\s*\[)[ xX](\].*)$")
```

Add the method to `NotesService`:

```python
    def set_checkbox(self, note_id: str, line: int, checked: bool) -> dict:
        """Flip one checkbox at the given 1-based body line. Returns read_note().

        Raises FileNotFoundError if the note is missing, ValueError if the
        target line is not a markdown checkbox.
        """
        rel = f"10-daily/{note_id}.md"
        if not (self.vault.vault_path / rel).exists():
            raise FileNotFoundError(rel)
        parsed = self.vault.read_file(rel)
        body = parsed.get("content", "")
        lines = body.split("\n")
        idx = line - 1
        if idx < 0 or idx >= len(lines) or not _CHECKBOX_RE.match(lines[idx]):
            raise ValueError(f"line {line} is not a checkbox")
        mark = "x" if checked else " "
        lines[idx] = _CHECKBOX_RE.sub(rf"\g<1>{mark}\g<2>", lines[idx])
        new_body = "\n".join(lines)
        # write_file preserves frontmatter and stamps 'updated' to today.
        self.vault.write_file(rel, parsed.get("metadata", {}) or {}, new_body)
        return self.read_note(note_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_notes_service.py::TestSetCheckbox -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/notes_service.py apps/vault-server/tests/test_notes_service.py
git commit -m "feat(notes): set_checkbox flips a checkbox line + bumps updated"
```

---

## Task 6: NotesService — random_knowledge_note

**Files:**
- Modify: `apps/vault-server/src/services/notes_service.py`
- Test: `apps/vault-server/tests/test_notes_service.py`

- [ ] **Step 1: Write the failing test (append)**

```python
class TestRandomKnowledge:
    def test_returns_a_knowledge_note(self, tmp_path):
        v = _make_vault(tmp_path)
        kdir = v.vault_path / "60-knowledge" / "notes"
        kdir.mkdir(parents=True)
        (kdir / "espresso.md").write_text(
            "---\ntype: knowledge\nname: Espresso\n---\n\n9 bars, 25 seconds.\n"
        )
        note = NotesService(v).random_knowledge_note()
        assert note["id"] == "espresso"
        assert note["title"] == "Espresso"
        assert "9 bars" in note["markdown"]
        assert note["source"] == "60-knowledge/notes/espresso.md"

    def test_returns_none_when_no_knowledge(self, tmp_path):
        v = _make_vault(tmp_path)
        assert NotesService(v).random_knowledge_note() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_notes_service.py::TestRandomKnowledge -v`
Expected: FAIL with `AttributeError: ... 'random_knowledge_note'`

- [ ] **Step 3: Write minimal implementation (add `import random` at top; add method)**

```python
    def random_knowledge_note(self) -> dict | None:
        """One random note from 60-knowledge/notes/, or None if none exist."""
        kdir = self.vault.vault_path / "60-knowledge" / "notes"
        if not kdir.exists():
            return None
        files = sorted(kdir.glob("*.md"))
        if not files:
            return None
        f = random.choice(files)
        rel = f"60-knowledge/notes/{f.name}"
        parsed = self.vault.read_file(rel)
        meta = parsed.get("metadata", {}) or {}
        body = parsed.get("content", "")
        return {
            "id": f.stem,
            "title": _title_for(f.stem, meta, body),
            "markdown": body,
            "source": rel,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_notes_service.py::TestRandomKnowledge -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/notes_service.py apps/vault-server/tests/test_notes_service.py
git commit -m "feat(notes): random_knowledge_note for the featured card"
```

---

## Task 7: /notes router + wiring

**Files:**
- Create: `apps/vault-server/src/api/routes/notes.py`
- Modify: `apps/vault-server/src/main.py`
- Test: `apps/vault-server/tests/test_notes_route.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the /notes router."""
from pathlib import Path
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Point the vault at a temp dir BEFORE importing the app.
    vault = tmp_path / "vault"
    (vault / "10-daily").mkdir(parents=True)
    (vault / "AGENTS.md").write_text("# Agents\n")
    (vault / "10-daily" / "2026-05-21.md").write_text(
        "---\ntype: daily\nupdated: '2026-05-21'\n---\n\n## Tasks\n- [ ] Pack cooler\n"
    )
    monkeypatch.setenv("VAULT_PATH", str(vault))
    monkeypatch.setenv("API_KEY", "")
    import importlib
    import src.config, src.main
    importlib.reload(src.config)
    importlib.reload(src.main)
    return TestClient(src.main.app)


def test_list_notes(client):
    r = client.get("/notes")
    assert r.status_code == 200
    notes = r.json()["notes"]
    assert notes[0]["id"] == "2026-05-21"


def test_get_note(client):
    r = client.get("/notes/2026-05-21")
    assert r.status_code == 200
    assert "## Tasks" in r.json()["markdown"]


def test_get_note_404(client):
    assert client.get("/notes/2099-01-01").status_code == 404


def test_patch_checkbox(client):
    r = client.patch("/notes/2026-05-21/checkbox", json={"line": 2, "checked": True})
    assert r.status_code == 200
    assert "- [x] Pack cooler" in r.json()["markdown"]


def test_patch_checkbox_conflict(client):
    r = client.patch("/notes/2026-05-21/checkbox", json={"line": 1, "checked": True})
    assert r.status_code == 409
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_notes_route.py -v`
Expected: FAIL (404 on `/notes` — router not registered)

- [ ] **Step 3a: Create the router**

```python
"""Notes API routes — feed for the time-management web app."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.auth import verify_api_key

router = APIRouter(prefix="/notes", tags=["notes"], dependencies=[Depends(verify_api_key)])


class CheckboxPatch(BaseModel):
    line: int
    checked: bool


def _svc():
    from src.main import get_notes
    return get_notes()


@router.get("")
async def list_notes():
    return {"notes": _svc().list_notes()}


@router.get("/featured")
async def featured_note():
    note = _svc().random_knowledge_note()
    if note is None:
        raise HTTPException(status_code=404, detail="no knowledge notes")
    return note


@router.get("/{note_id}")
async def get_note(note_id: str):
    try:
        return _svc().read_note(note_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="note not found")


@router.patch("/{note_id}/checkbox")
async def set_checkbox(note_id: str, patch: CheckboxPatch):
    try:
        return _svc().set_checkbox(note_id, patch.line, patch.checked)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="note not found")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
```

Note: `/featured` is declared before `/{note_id}` so it isn't swallowed by the path param.

- [ ] **Step 3b: Wire into `main.py`**

After the other service constructions (near `events = ...`), add:

```python
from src.services.notes_service import NotesService
notes = NotesService(vault)
```

Add the accessor next to `get_events`:

```python
def get_notes():
    return notes
```

Add the import + registration alongside the other routers:

```python
from src.api.routes.notes import router as notes_router
app.include_router(notes_router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_notes_route.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Run the full backend suite (no regressions)**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add apps/vault-server/src/api/routes/notes.py apps/vault-server/src/main.py apps/vault-server/tests/test_notes_route.py
git commit -m "feat(notes): /notes router (list, read, checkbox, featured) + wiring"
```

---

## Task 8: Frontend deps + QueryClient + API client + types

**Files:**
- Modify: `apps/telegram-web-app/package.json`
- Modify: `apps/telegram-web-app/src/main.tsx`
- Modify: `apps/telegram-web-app/src/services/api.ts`
- Create: `apps/telegram-web-app/src/models/note.ts`
- Test: `apps/telegram-web-app/src/services/__tests__/notes-api.test.ts`

- [ ] **Step 1: Install deps**

Run:
```bash
cd apps/telegram-web-app && npm install @tanstack/react-virtual@^3 @tanstack/react-query@^5 react-markdown@^9 remark-gfm@^4
```
Expected: the four packages added to `dependencies`.

- [ ] **Step 2: Create the types**

`src/models/note.ts`:
```ts
export type NoteKind = 'daily' | 'weekly'

export interface NoteListItem {
  id: string
  sort_key: string
  kind: NoteKind
  title: string
  has_photos: boolean
  snippet: string
}

export interface NoteDetail {
  id: string
  kind: NoteKind
  sort_key: string
  frontmatter: Record<string, unknown>
  markdown: string
}

export interface FeaturedNote {
  id: string
  title: string
  markdown: string
  source: string
}
```

- [ ] **Step 3: Write the failing API-client test**

`src/services/__tests__/notes-api.test.ts`:
```ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { api } from '../api'

const mockFetch = vi.fn()
global.fetch = mockFetch
beforeEach(() => mockFetch.mockReset())

function ok(body: unknown) {
  return { ok: true, json: () => Promise.resolve(body) }
}

describe('notes api', () => {
  it('lists notes', async () => {
    mockFetch.mockResolvedValueOnce(ok({ notes: [{ id: '2026-05-21' }] }))
    const res = await api.listNotes()
    expect(res.notes[0].id).toBe('2026-05-21')
    expect(mockFetch).toHaveBeenCalledWith(expect.stringContaining('/notes'), expect.any(Object))
  })

  it('gets one note', async () => {
    mockFetch.mockResolvedValueOnce(ok({ id: '2026-05-21', markdown: '# hi' }))
    const res = await api.getNote('2026-05-21')
    expect(res.markdown).toBe('# hi')
    expect(mockFetch).toHaveBeenCalledWith(expect.stringContaining('/notes/2026-05-21'), expect.any(Object))
  })

  it('patches a checkbox', async () => {
    mockFetch.mockResolvedValueOnce(ok({ id: '2026-05-21', markdown: '- [x] x' }))
    await api.setNoteCheckbox('2026-05-21', 2, true)
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/notes/2026-05-21/checkbox')
    expect(opts.method).toBe('PATCH')
    expect(JSON.parse(opts.body)).toEqual({ line: 2, checked: true })
  })
})
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd apps/telegram-web-app && npx vitest run src/services/__tests__/notes-api.test.ts`
Expected: FAIL (`api.listNotes is not a function`)

- [ ] **Step 5: Add methods to `src/services/api.ts`**

Add the imports near the top:
```ts
import type { NoteListItem, NoteDetail, FeaturedNote } from '../models/note'
```
Add to the `api` object:
```ts
  listNotes(): Promise<{ notes: NoteListItem[] }> {
    return request('/notes')
  },

  getNote(id: string): Promise<NoteDetail> {
    return request(`/notes/${id}`)
  },

  setNoteCheckbox(id: string, line: number, checked: boolean): Promise<NoteDetail> {
    return request(`/notes/${id}/checkbox`, {
      method: 'PATCH',
      body: JSON.stringify({ line, checked }),
    })
  },

  getFeaturedNote(): Promise<FeaturedNote> {
    return request('/notes/featured')
  },
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd apps/telegram-web-app && npx vitest run src/services/__tests__/notes-api.test.ts`
Expected: PASS (3 tests)

- [ ] **Step 7: Wrap app in QueryClientProvider**

In `src/main.tsx`, wrap the rendered app:
```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 60_000, refetchOnWindowFocus: false } },
})
```
Wrap the existing `<App />` (or `<Router />`) render in `<QueryClientProvider client={queryClient}>...</QueryClientProvider>`.

- [ ] **Step 8: Commit**

```bash
git add apps/telegram-web-app/package.json apps/telegram-web-app/package-lock.json apps/telegram-web-app/src/main.tsx apps/telegram-web-app/src/models/note.ts apps/telegram-web-app/src/services/api.ts apps/telegram-web-app/src/services/__tests__/notes-api.test.ts
git commit -m "feat(web): notes api client + types + react-query provider"
```

---

## Task 9: Obsidian transforms + checkbox line mapping (pure module)

**Files:**
- Create: `apps/telegram-web-app/src/features/time-management/obsidian.ts`
- Test: `apps/telegram-web-app/src/features/time-management/__tests__/obsidian.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect } from 'vitest'
import { mediaUrlForEmbed, parseWikiEmbed, parseWikiLink } from '../obsidian'

describe('obsidian transforms', () => {
  it('builds a media url from an image embed + note date', () => {
    expect(mediaUrlForEmbed('photo_2026-05-21.jpg', '2026-05-21'))
      .toContain('/media/2026-05-21/photo_2026-05-21.jpg')
  })

  it('detects an image embed token', () => {
    expect(parseWikiEmbed('![[p.jpg]]')).toEqual({ file: 'p.jpg' })
    expect(parseWikiEmbed('![[note]]')).toEqual({ file: 'note' })
    expect(parseWikiEmbed('not an embed')).toBeNull()
  })

  it('parses a wikilink to its label', () => {
    expect(parseWikiLink('[[Mount Carmel]]')).toEqual({ label: 'Mount Carmel' })
    expect(parseWikiLink('[[a|b]]')).toEqual({ label: 'b' })
    expect(parseWikiLink('plain')).toBeNull()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/telegram-web-app && npx vitest run src/features/time-management/__tests__/obsidian.test.ts`
Expected: FAIL (module not found)

- [ ] **Step 3: Write the module**

```ts
import { api } from '../../services/api'

const IMG_EXT = /\.(jpe?g|png|gif|webp|heic)$/i

export function parseWikiEmbed(text: string): { file: string } | null {
  const m = text.match(/^!\[\[([^\]]+)\]\]$/)
  return m ? { file: m[1].trim() } : null
}

export function parseWikiLink(text: string): { label: string } | null {
  const m = text.match(/^\[\[([^\]]+)\]\]$/)
  if (!m) return null
  const inner = m[1]
  const label = inner.includes('|') ? inner.split('|').pop()!.trim() : inner.trim()
  return { label }
}

export function isImageEmbed(file: string): boolean {
  return IMG_EXT.test(file)
}

export function mediaUrlForEmbed(file: string, noteDate: string): string {
  return api.getMediaUrl(noteDate, file)
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/telegram-web-app && npx vitest run src/features/time-management/__tests__/obsidian.test.ts`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/telegram-web-app/src/features/time-management/obsidian.ts apps/telegram-web-app/src/features/time-management/__tests__/obsidian.test.ts
git commit -m "feat(web): obsidian embed/wikilink parsing helpers"
```

---

## Task 10: Scrubber date↔offset math (pure module)

**Files:**
- Create: `apps/telegram-web-app/src/features/time-management/scrubber.ts`
- Test: `apps/telegram-web-app/src/features/time-management/__tests__/scrubber.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect } from 'vitest'
import { fractionToIndex, indexToFraction, labelForSortKey } from '../scrubber'

// Notes are newest-first; fraction 0 = top (newest), 1 = bottom (oldest).
const keys = ['2026-05-21', '2026-05-20', '2026-01-02', '2025-12-31']

describe('scrubber math', () => {
  it('maps drag fraction to nearest note index by TIME, not item index', () => {
    expect(fractionToIndex(0, keys)).toBe(0)            // newest
    expect(fractionToIndex(1, keys)).toBe(keys.length - 1) // oldest
    // A point ~10% down the time span lands near the big May cluster (index 1),
    // not the temporal midpoint between Jan and Dec.
    expect(fractionToIndex(0.1, keys)).toBe(1)
  })

  it('round-trips an index back to a fraction within tolerance', () => {
    const f = indexToFraction(2, keys)
    expect(f).toBeGreaterThan(0)
    expect(f).toBeLessThan(1)
  })

  it('formats a month/year bubble label', () => {
    expect(labelForSortKey('2026-05-21')).toBe('MAY 2026')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/telegram-web-app && npx vitest run src/features/time-management/__tests__/scrubber.test.ts`
Expected: FAIL (module not found)

- [ ] **Step 3: Write the module**

```ts
function ms(key: string): number {
  return new Date(key + 'T00:00:00Z').getTime()
}

/** Fraction 0..1 (top=newest) → index of the note nearest that point in time. */
export function fractionToIndex(fraction: number, keys: string[]): number {
  if (keys.length === 0) return 0
  const newest = ms(keys[0])
  const oldest = ms(keys[keys.length - 1])
  if (newest === oldest) return 0
  const target = newest - fraction * (newest - oldest)
  let best = 0
  let bestDist = Infinity
  keys.forEach((k, i) => {
    const d = Math.abs(ms(k) - target)
    if (d < bestDist) { bestDist = d; best = i }
  })
  return best
}

/** Index → fraction 0..1 along the time span (for placing the thumb). */
export function indexToFraction(index: number, keys: string[]): number {
  if (keys.length <= 1) return 0
  const newest = ms(keys[0])
  const oldest = ms(keys[keys.length - 1])
  if (newest === oldest) return 0
  return (newest - ms(keys[index])) / (newest - oldest)
}

const MONTHS = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC']

export function labelForSortKey(key: string): string {
  const d = new Date(key + 'T00:00:00Z')
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/telegram-web-app && npx vitest run src/features/time-management/__tests__/scrubber.test.ts`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/telegram-web-app/src/features/time-management/scrubber.ts apps/telegram-web-app/src/features/time-management/__tests__/scrubber.test.ts
git commit -m "feat(web): scrubber date<->offset math (proportional to time)"
```

---

## Task 11: theme.css — design tokens, paper texture, fonts

**Files:**
- Create: `apps/telegram-web-app/src/features/time-management/theme.css`

(No test — pure styling. Verified visually in Task 16.)

- [ ] **Step 1: Write `theme.css`**

```css
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght,SOFT@9..144,300..900,0..100&family=Newsreader:opsz,wght,ital@6..72,200..800,0;6..72,200..800,1&family=JetBrains+Mono:wght@300;400&display=swap');

/* Token set — structured so a dark "ink" variant is a later drop-in under
   [data-theme="dark"]. Ship paper only for now. */
.tm-root {
  --paper: #f3ecdf; --paper-deep: #ebe2d0;
  --ink: #1a1512; --ink-soft: #4d4138; --ink-mute: #8a7a6b;
  --rule: #d8cab1; --rule-soft: #e3d7bf;
  --terra: #b04a22; --terra-deep: #8a3814; --moss: #5a6b3a;
  --shadow-md: 0 8px 24px rgba(26,21,18,0.08);
  --shadow-lg: 0 24px 60px rgba(26,21,18,0.18);
  background: var(--paper); color: var(--ink);
  font-family: 'Newsreader', Georgia, serif;
  min-height: 100vh; position: relative;
}
.tm-root::after {
  content: ""; position: fixed; inset: 0; pointer-events: none;
  opacity: 0.4; mix-blend-mode: multiply; z-index: 0;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 0.2 0 0 0 0 0.15 0 0 0 0 0.1 0 0 0 0.06 0'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
}
.tm-display { font-family: 'Fraunces', Georgia, serif; font-variation-settings: 'opsz' 144, 'SOFT' 40; font-weight: 300; letter-spacing: -0.01em; }
.tm-mono { font-family: 'JetBrains Mono', monospace; font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--ink-mute); }
.tm-content { position: relative; z-index: 2; }
.tm-wikilink { font-style: italic; color: var(--terra); }
.tm-img { width: 100%; display: block; }
```

- [ ] **Step 2: Commit**

```bash
git add apps/telegram-web-app/src/features/time-management/theme.css
git commit -m "feat(web): paper/editorial theme tokens + texture"
```

---

## Task 12: NoteMarkdown — render markdown with Obsidian transforms + interactive checkboxes

**Files:**
- Create: `apps/telegram-web-app/src/features/time-management/components/NoteMarkdown.tsx`
- Test: `apps/telegram-web-app/src/features/time-management/__tests__/NoteMarkdown.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import NoteMarkdown from '../components/NoteMarkdown'

describe('NoteMarkdown', () => {
  it('renders prose and a wikilink chip', () => {
    render(<NoteMarkdown noteId="2026-05-21" markdown="Hi [[Mount Carmel]]" onToggle={() => {}} />)
    expect(screen.getByText('Mount Carmel')).toBeInTheDocument()
  })

  it('renders an image embed as an img with the media url', () => {
    render(<NoteMarkdown noteId="2026-05-21" markdown="![[photo_2026-05-21.jpg]]" onToggle={() => {}} />)
    const img = screen.getByRole('img') as HTMLImageElement
    expect(img.src).toContain('/media/2026-05-21/photo_2026-05-21.jpg')
  })

  it('fires onToggle with the source line when a checkbox is clicked', () => {
    const onToggle = vi.fn()
    // line 1 = "## Tasks", line 2 = the checkbox
    render(<NoteMarkdown noteId="2026-05-21" markdown={'## Tasks\n- [ ] Pack cooler'} onToggle={onToggle} />)
    fireEvent.click(screen.getByRole('checkbox'))
    expect(onToggle).toHaveBeenCalledWith(2, true)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/telegram-web-app && npx vitest run src/features/time-management/__tests__/NoteMarkdown.test.tsx`
Expected: FAIL (module not found)

- [ ] **Step 3: Write the component**

```tsx
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { parseWikiEmbed, parseWikiLink, isImageEmbed, mediaUrlForEmbed } from '../obsidian'

interface Props {
  noteId: string
  markdown: string
  onToggle: (line: number, checked: boolean) => void
}

// react-markdown strips raw "![[ ]]"/"[[ ]]" as plain text nodes. Pre-process
// embeds into standard markdown image syntax so they render as <img>, and leave
// [[wikilinks]] for the text renderer to chip-ify.
function preprocess(md: string, noteId: string): string {
  return md.replace(/!\[\[([^\]]+)\]\]/g, (_m, file) => {
    const f = String(file).trim()
    return isImageEmbed(f) ? `![](${mediaUrlForEmbed(f, noteId)})` : f
  })
}

// Split a text string into wikilink chips + plain text.
function renderText(text: string) {
  const parts = text.split(/(\[\[[^\]]+\]\])/g)
  return parts.map((p, i) => {
    const link = parseWikiLink(p)
    return link
      ? <span key={i} className="tm-wikilink">{link.label}</span>
      : <span key={i}>{p}</span>
  })
}

export default function NoteMarkdown({ noteId, markdown, onToggle }: Props) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        img: ({ src, ...rest }) => <img className="tm-img" src={src} {...rest} />,
        a: ({ href, children }) => <span className="tm-wikilink">{children ?? href}</span>,
        input: ({ type, checked, node }) => {
          if (type !== 'checkbox') return null
          const line = node?.position?.start?.line ?? 0
          return (
            <input
              type="checkbox"
              defaultChecked={checked}
              onChange={(e) => onToggle(line, e.target.checked)}
            />
          )
        },
        text: ({ children }) => <>{renderText(String(children))}</>,
      }}
    >
      {preprocess(markdown, noteId)}
    </ReactMarkdown>
  )
}
```

Note: GFM checkbox list items carry the parent list-item's `position` — verify the line maps to the checkbox source line in the test; if `node.position` resolves to the list item line, the assertion in Step 1 (line 2) still holds because the checkbox and its text share that line. Adjust the expected line in the test to the observed value if the GFM plugin reports differently, keeping the test as the source of truth.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/telegram-web-app && npx vitest run src/features/time-management/__tests__/NoteMarkdown.test.tsx`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/telegram-web-app/src/features/time-management/components/NoteMarkdown.tsx apps/telegram-web-app/src/features/time-management/__tests__/NoteMarkdown.test.tsx
git commit -m "feat(web): NoteMarkdown renders embeds, wikilinks, interactive checkboxes"
```

---

## Task 13: NoteDay — one day/week row (sticky header + lazy body + month divider)

**Files:**
- Create: `apps/telegram-web-app/src/features/time-management/components/NoteDay.tsx`
- Test: `apps/telegram-web-app/src/features/time-management/__tests__/NoteDay.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, it, expect } from 'vitest'
import { headerParts } from '../components/NoteDay'

describe('NoteDay.headerParts', () => {
  it('formats a daily header', () => {
    const p = headerParts({ id: '2026-05-21', kind: 'daily', sort_key: '2026-05-21' })
    expect(p.dow).toBe('Thursday')
    expect(p.sub).toBe('21 MAY 2026')
  })

  it('formats a weekly header by week number', () => {
    const p = headerParts({ id: '2022-W34', kind: 'weekly', sort_key: '2022-08-28' })
    expect(p.dow).toBe('Week 34')
    expect(p.sub).toContain('ENDS')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/telegram-web-app && npx vitest run src/features/time-management/__tests__/NoteDay.test.tsx`
Expected: FAIL (module not found)

- [ ] **Step 3: Write the component**

```tsx
import { useQuery } from '@tanstack/react-query'
import { api } from '../../../services/api'
import type { NoteListItem } from '../../../models/note'
import NoteMarkdown from './NoteMarkdown'

const DOW = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday']
const MON = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC']

export function headerParts(item: Pick<NoteListItem, 'id' | 'kind' | 'sort_key'>) {
  const d = new Date(item.sort_key + 'T00:00:00Z')
  if (item.kind === 'weekly') {
    const week = item.id.split('-W')[1] ?? ''
    return {
      dow: `Week ${parseInt(week, 10)}`,
      sub: `ENDS ${d.getUTCDate()} ${MON[d.getUTCMonth()]} ${d.getUTCFullYear()}`,
    }
  }
  return {
    dow: DOW[d.getUTCDay()],
    sub: `${d.getUTCDate()} ${MON[d.getUTCMonth()]} ${d.getUTCFullYear()}`,
  }
}

interface Props {
  item: NoteListItem
  onMeasure: (el: HTMLElement | null) => void
}

export default function NoteDay({ item, onMeasure }: Props) {
  const { data } = useQuery({
    queryKey: ['note', item.id],
    queryFn: () => api.getNote(item.id),
  })
  const h = headerParts(item)

  return (
    <div ref={onMeasure} data-note-id={item.id}>
      <div className="tm-day-hd">
        <span className="tm-display tm-dow">{h.dow}</span>
        <span className="tm-mono">{h.sub}</span>
      </div>
      <div className="tm-day-bd">
        {data
          ? <NoteMarkdown noteId={item.id} markdown={data.markdown} onToggle={() => {}} />
          : <div className="tm-skeleton" style={{ height: 120 }} />}
      </div>
    </div>
  )
}
```

(The checkbox `onToggle` is wired through from the feed in Task 15; the local stub keeps this component independently testable. The `headerParts` export is what the unit test targets.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/telegram-web-app && npx vitest run src/features/time-management/__tests__/NoteDay.test.tsx`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/telegram-web-app/src/features/time-management/components/NoteDay.tsx apps/telegram-web-app/src/features/time-management/__tests__/NoteDay.test.tsx
git commit -m "feat(web): NoteDay sticky header + lazy body"
```

---

## Task 14: FeaturedNote, DateScrubber, BackToTopFab (presentational)

**Files:**
- Create: `apps/telegram-web-app/src/features/time-management/components/FeaturedNote.tsx`
- Create: `apps/telegram-web-app/src/features/time-management/components/DateScrubber.tsx`
- Create: `apps/telegram-web-app/src/features/time-management/components/BackToTopFab.tsx`
- Test: `apps/telegram-web-app/src/features/time-management/__tests__/DateScrubber.test.tsx`

- [ ] **Step 1: Write the failing test (DateScrubber drag → callback)**

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import DateScrubber from '../components/DateScrubber'

describe('DateScrubber', () => {
  it('calls onSeek with a fraction when the track is pointer-dragged', () => {
    const onSeek = vi.fn()
    const { container } = render(
      <DateScrubber keys={['2026-05-21', '2026-05-20']} activeIndex={0} onSeek={onSeek} />,
    )
    const track = container.querySelector('[data-testid="scrub-track"]') as HTMLElement
    // jsdom gives 0-size rects; stub a height so fraction math runs.
    track.getBoundingClientRect = () => ({ top: 0, height: 100, left: 0, width: 10, right: 10, bottom: 100, x: 0, y: 0, toJSON: () => {} })
    track.dispatchEvent(new MouseEvent('pointerdown', { clientY: 50, bubbles: true }))
    expect(onSeek).toHaveBeenCalledWith(0.5)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/telegram-web-app && npx vitest run src/features/time-management/__tests__/DateScrubber.test.tsx`
Expected: FAIL (module not found)

- [ ] **Step 3: Write the three components**

`DateScrubber.tsx`:
```tsx
import { useRef, useState } from 'react'
import { labelForSortKey, indexToFraction } from '../scrubber'

interface Props {
  keys: string[]
  activeIndex: number
  onSeek: (fraction: number) => void
}

export default function DateScrubber({ keys, activeIndex, onSeek }: Props) {
  const trackRef = useRef<HTMLDivElement>(null)
  const [dragging, setDragging] = useState(false)

  function fractionFromEvent(clientY: number): number {
    const el = trackRef.current
    if (!el) return 0
    const r = el.getBoundingClientRect()
    return Math.min(1, Math.max(0, (clientY - r.top) / r.height))
  }
  function handle(clientY: number) { onSeek(fractionFromEvent(clientY)) }

  const thumbTop = `${indexToFraction(activeIndex, keys) * 100}%`
  const label = keys[activeIndex] ? labelForSortKey(keys[activeIndex]) : ''

  return (
    <div className="tm-scrub">
      <div
        ref={trackRef}
        data-testid="scrub-track"
        className="tm-scrub-track"
        onPointerDown={(e) => { setDragging(true); handle(e.clientY) }}
        onPointerMove={(e) => { if (dragging) handle(e.clientY) }}
        onPointerUp={() => setDragging(false)}
        onPointerLeave={() => setDragging(false)}
      />
      {dragging && <div className="tm-scrub-bubble" style={{ top: thumbTop }}>{label}</div>}
      <div className="tm-scrub-thumb" style={{ top: thumbTop }} />
    </div>
  )
}
```

`BackToTopFab.tsx`:
```tsx
interface Props { visible: boolean; onClick: () => void }
export default function BackToTopFab({ visible, onClick }: Props) {
  if (!visible) return null
  return <button className="tm-fab" aria-label="Back to top" onClick={onClick}>↑</button>
}
```

`FeaturedNote.tsx`:
```tsx
import { useQuery } from '@tanstack/react-query'
import { api } from '../../../services/api'
import NoteMarkdown from './NoteMarkdown'

export default function FeaturedNote() {
  const { data } = useQuery({
    queryKey: ['featured-note'],
    queryFn: () => api.getFeaturedNote(),
    retry: false,
  })
  if (!data) return null
  return (
    <div className="tm-featured">
      <div className="tm-mono tm-featured-when">— from your notes</div>
      <div className="tm-display tm-featured-title">{data.title}</div>
      <NoteMarkdown noteId={data.id} markdown={data.markdown} onToggle={() => {}} />
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/telegram-web-app && npx vitest run src/features/time-management/__tests__/DateScrubber.test.tsx`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add apps/telegram-web-app/src/features/time-management/components/FeaturedNote.tsx apps/telegram-web-app/src/features/time-management/components/DateScrubber.tsx apps/telegram-web-app/src/features/time-management/components/BackToTopFab.tsx apps/telegram-web-app/src/features/time-management/__tests__/DateScrubber.test.tsx
git commit -m "feat(web): FeaturedNote, DateScrubber, BackToTopFab"
```

---

## Task 15: NoteFeed — virtualizer wiring checkbox mutation + scrubber + FAB

**Files:**
- Create: `apps/telegram-web-app/src/features/time-management/components/NoteFeed.tsx`
- Test: `apps/telegram-web-app/src/features/time-management/__tests__/NoteFeed.test.tsx`

- [ ] **Step 1: Write the failing test (renders rows from a provided list)**

```tsx
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import NoteFeed from '../components/NoteFeed'
import type { NoteListItem } from '../../../models/note'

const items: NoteListItem[] = [
  { id: '2026-05-21', sort_key: '2026-05-21', kind: 'daily', title: 'Thu', has_photos: false, snippet: 'kebabs' },
]

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient()
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('NoteFeed', () => {
  it('renders a day header for each list item', () => {
    wrap(<NoteFeed items={items} />)
    expect(screen.getByText('Thursday')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/telegram-web-app && npx vitest run src/features/time-management/__tests__/NoteFeed.test.tsx`
Expected: FAIL (module not found)

- [ ] **Step 3: Write the component**

```tsx
import { useMemo, useRef, useState, useEffect } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { NoteListItem, NoteDetail } from '../../../models/note'
import { api } from '../../../services/api'
import { fractionToIndex } from '../scrubber'
import NoteDay from './NoteDay'
import DateScrubber from './DateScrubber'
import BackToTopFab from './BackToTopFab'

interface Props { items: NoteListItem[] }

export default function NoteFeed({ items }: Props) {
  const parentRef = useRef<HTMLDivElement>(null)
  const qc = useQueryClient()
  const keys = useMemo(() => items.map((i) => i.sort_key), [items])
  const [activeIndex, setActiveIndex] = useState(0)
  const [showFab, setShowFab] = useState(false)

  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 280,
    overscan: 4,
  })

  const checkbox = useMutation({
    mutationFn: ({ id, line, checked }: { id: string; line: number; checked: boolean }) =>
      api.setNoteCheckbox(id, line, checked),
    onSuccess: (note: NoteDetail) => {
      qc.setQueryData(['note', note.id], note)
    },
  })

  useEffect(() => {
    const el = parentRef.current
    if (!el) return
    const onScroll = () => {
      setShowFab(el.scrollTop > 600)
      const first = virtualizer.getVirtualItems()[0]
      if (first) setActiveIndex(first.index)
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [virtualizer])

  function seek(fraction: number) {
    virtualizer.scrollToIndex(fractionToIndex(fraction, keys), { align: 'start' })
  }

  return (
    <div className="tm-feed-wrap">
      <div ref={parentRef} className="tm-scroll">
        <div style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
          {virtualizer.getVirtualItems().map((v) => {
            const item = items[v.index]
            return (
              <div
                key={item.id}
                data-index={v.index}
                style={{ position: 'absolute', top: 0, left: 0, width: '100%', transform: `translateY(${v.start}px)` }}
              >
                <NoteDayRow item={item} virtualizer={virtualizer} index={v.index} onToggle={checkbox.mutate} />
              </div>
            )
          })}
        </div>
      </div>
      <DateScrubber keys={keys} activeIndex={activeIndex} onSeek={seek} />
      <BackToTopFab visible={showFab} onClick={() => virtualizer.scrollToIndex(0)} />
    </div>
  )
}

// Bridges NoteDay's onToggle to the mutation, binding the note id.
function NoteDayRow({ item, virtualizer, index, onToggle }: {
  item: NoteListItem
  virtualizer: ReturnType<typeof useVirtualizer>
  index: number
  onToggle: (v: { id: string; line: number; checked: boolean }) => void
}) {
  return (
    <NoteDay
      item={item}
      onMeasure={(el) => el && virtualizer.measureElement(el)}
      onToggle={(line, checked) => onToggle({ id: item.id, line, checked })}
    />
  )
}
```

Update `NoteDay`'s `Props` to accept the `onToggle` and pass it into `NoteMarkdown`:
- In `NoteDay.tsx`, change the interface to `{ item; onMeasure; onToggle: (line: number, checked: boolean) => void }` and pass `onToggle={onToggle}` to `<NoteMarkdown>`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/telegram-web-app && npx vitest run src/features/time-management/__tests__/NoteFeed.test.tsx`
Expected: PASS. (If the virtualizer renders zero items in jsdom because the scroll element has no height, set the test's parent height by stubbing `getBoundingClientRect`, or assert on `virtualizer` via a height-stubbed container as in Task 14. Keep the test asserting at least one header renders.)

- [ ] **Step 5: Commit**

```bash
git add apps/telegram-web-app/src/features/time-management/components/NoteFeed.tsx apps/telegram-web-app/src/features/time-management/components/NoteDay.tsx apps/telegram-web-app/src/features/time-management/__tests__/NoteFeed.test.tsx
git commit -m "feat(web): NoteFeed virtualizer + checkbox mutation + scrubber/FAB wiring"
```

---

## Task 16: TimeManagementPage + routing + remove dayplanner

**Files:**
- Create: `apps/telegram-web-app/src/features/time-management/TimeManagementPage.tsx`
- Modify: `apps/telegram-web-app/src/app/Router.tsx`
- Delete: `apps/telegram-web-app/src/features/dayplanner/` (entire dir)
- Test: `apps/telegram-web-app/src/features/time-management/__tests__/TimeManagementPage.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import TimeManagementPage from '../TimeManagementPage'
import { api } from '../../../services/api'

beforeEach(() => {
  vi.spyOn(api, 'listNotes').mockResolvedValue({ notes: [
    { id: '2026-05-21', sort_key: '2026-05-21', kind: 'daily', title: 'Thu', has_photos: false, snippet: 's' },
  ] })
  vi.spyOn(api, 'getNote').mockResolvedValue({ id: '2026-05-21', kind: 'daily', sort_key: '2026-05-21', frontmatter: {}, markdown: '## Notes\nhi' })
  vi.spyOn(api, 'getFeaturedNote').mockRejectedValue(new Error('none'))
})

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><TimeManagementPage /></QueryClientProvider>)
}

describe('TimeManagementPage', () => {
  it('loads the notes list and renders the brand + a day', async () => {
    wrap()
    expect(screen.getByText('Time')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('Thursday')).toBeInTheDocument())
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/telegram-web-app && npx vitest run src/features/time-management/__tests__/TimeManagementPage.test.tsx`
Expected: FAIL (module not found)

- [ ] **Step 3: Write the page**

```tsx
import { useQuery } from '@tanstack/react-query'
import { api } from '../../services/api'
import NoteFeed from './components/NoteFeed'
import FeaturedNote from './components/FeaturedNote'
import './theme.css'

export default function TimeManagementPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['notes-list'],
    queryFn: () => api.listNotes(),
  })

  return (
    <div className="tm-root">
      <div className="tm-content">
        <header className="tm-top">
          <span className="tm-display tm-brand">Time</span>
        </header>
        {isLoading && <div className="tm-state">Loading…</div>}
        {error && <div className="tm-state tm-error">Couldn’t load notes.</div>}
        {data && (
          <>
            <FeaturedNote />
            <NoteFeed items={data.notes} />
          </>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/telegram-web-app && npx vitest run src/features/time-management/__tests__/TimeManagementPage.test.tsx`
Expected: PASS (1 test)

- [ ] **Step 5: Swap routing + delete dayplanner**

`src/app/Router.tsx` becomes:
```tsx
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import TimeManagementPage from '../features/time-management/TimeManagementPage'
import PlaygroundPage from '../features/playground/PlaygroundPage'

export default function Router() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/time-management" replace />} />
        <Route path="/time-management" element={<TimeManagementPage />} />
        <Route path="/dayplanner" element={<Navigate to="/time-management" replace />} />
        <Route path="/playground" element={<PlaygroundPage />} />
      </Routes>
    </BrowserRouter>
  )
}
```

Then delete the old feature:
```bash
git rm -r apps/telegram-web-app/src/features/dayplanner
```

- [ ] **Step 6: Run the full webapp suite + typecheck**

Run: `cd apps/telegram-web-app && npx vitest run && npx tsc -b`
Expected: tests pass. (Pre-existing `import.meta.env` tsc notes may remain as before — do not introduce new type errors in `features/time-management`.)

- [ ] **Step 7: Commit**

```bash
git add apps/telegram-web-app/src/features/time-management apps/telegram-web-app/src/app/Router.tsx
git commit -m "feat(web): TimeManagementPage + route swap, remove dayplanner"
```

---

## Task 17: Finishing styles + manual visual pass

**Files:**
- Modify: `apps/telegram-web-app/src/features/time-management/theme.css` (add layout classes used by the components: `.tm-top`, `.tm-brand`, `.tm-day-hd`, `.tm-dow`, `.tm-day-bd`, `.tm-scroll`, `.tm-feed-wrap`, `.tm-scrub*`, `.tm-fab`, `.tm-featured*`, `.tm-state`, `.tm-skeleton`, `.tm-mono`, photo edge-bleed).

- [ ] **Step 1: Add the layout CSS**

Add classes to `theme.css` matching the approved mockup (`docs/superpowers/specs/2026-06-20-time-management-webapp-design.md` references the companion mockups): sticky `.tm-day-hd` with backdrop blur + hairline rule; `.tm-day-bd` padding with photos bled to the edges (`img { margin-inline: -18px; width: calc(100% + 36px) }` wrapper or `.tm-img` full-bleed); right-edge `.tm-scrub` track + terra thumb + ink bubble; ink circular `.tm-fab` bottom-right; `.tm-featured` paper-deep card with a terra top rule; month divider hairlines. Consult the `frontend-design:frontend-design` skill for spacing/hierarchy.

- [ ] **Step 2: Manual visual verification**

Run both servers and open the app on a mobile viewport:
```bash
# terminal 1
cd apps/vault-server && source venv/bin/activate && python -m uvicorn src.main:app --reload --port 8000
# terminal 2
cd apps/telegram-web-app && npm run dev
```
Open `http://localhost:5173/time-management` in a narrow window. Confirm:
- Days render newest-first; sections, photos, wikilinks, mood blocks display.
- Checkbox tap persists (re-fetch the note in another tab / check the file).
- Scrubber drag jumps by date; bubble shows month/year; thumb tracks scroll.
- Back-to-top appears after scrolling and returns to the top.
- Weekly notes show "Week NN · ends …" at the right position.

- [ ] **Step 3: Commit**

```bash
git add apps/telegram-web-app/src/features/time-management/theme.css
git commit -m "style(web): time-management layout + paper aesthetic polish"
```

---

## Self-Review notes (for the implementer)

- **Spec coverage:** list/read/checkbox/featured endpoints (Tasks 1–7), newest-first + weekly end-of-week anchoring (Tasks 1, 3, 13), lazy bodies + virtualization (Tasks 13, 15), Obsidian transforms + interactive checkboxes (Tasks 9, 12), scrubber proportional-to-time (Tasks 10, 14, 15), back-to-top (Tasks 14, 15), featured random knowledge note (Tasks 6, 14, 16), paper theme + tokens for future dark mode (Tasks 11, 17), routing swap + dayplanner removal (Task 16). Playground untouched (no tasks modify it).
- **Checkbox line semantics:** the backend treats `line` as 1-based within the **markdown body** (frontmatter excluded), because `VaultService.read_file` returns the body in `content`. The frontend obtains the line from react-markdown's mdast `position`, which is also relative to the rendered markdown string (the body). These two coordinate systems match because the frontend renders exactly the `markdown` field returned by `read_note`. Task 12's test pins the exact line value.
- **`/featured` route ordering** is declared before `/{note_id}` so FastAPI doesn't treat "featured" as a note id.
```
