# Time-management web app — design

**Date:** 2026-06-20
**Status:** Approved for planning
**Supersedes:** the `dayplanner` feature in `apps/telegram-web-app`

## Goal

Replace the `dayplanner` feature with a new `time-management` feature: a continuous,
mobile-first, virtualized feed of the user's daily (and weekly) notes, rendered
faithfully (all sections, photos, wikilinks), with a Google-Photos-style date
scrubber and a back-to-top control, in an editorial "paper journal" aesthetic.

It is the first of a planned family of vault apps (alongside `playground`, and
future `knowledge-management` / `motivation-management`), so its design system is
extracted to be reusable.

## Scope

### In scope
- New `features/time-management/` frontend feature; route `/time-management`.
- Redirect `/dayplanner` → `/time-management`; default route points at it.
- New vault-server `notes` router: list notes, read one note body, flip a checkbox.
- A "featured note" card at the top of the feed surfacing **one random knowledge
  note** from `60-knowledge/notes/` (simplified stand-in for a future
  "on this day" memory feature).
- Checkbox writes are in scope for **any** note, including past and weekly notes.

### Out of scope
- `playground` feature (keeps using `/events` and the shared `DateNav`) — untouched.
- All other vault-server routes — untouched.
- Full inline markdown editing of note bodies.
- Dark mode (tokens are structured for a later dark "ink" variant; only the paper
  theme ships now).
- The prototype's journaling features (7 compose formats, temperature scales,
  format picker, compose editors) — we borrow the prototype's *design language*,
  not its feature set.

## Data model & ordering

- **Row = one existing note.** Empty calendar days are not rendered.
- **Order:** newest-first (most recent at top, scroll down into the past).
- **Notes included:** everything in `memory/10-daily/` — both `YYYY-MM-DD.md`
  dailies and `YYYY-Www.md` weeklies.
- **Weekly anchoring:** a weekly note's `sort_key` is the **last day of its ISO
  week**, so it lands in the feed where that week concluded.

## Backend (vault-server)

New `NotesService` + `notes` router (`/notes`, behind `verify_api_key`).

### `NotesService`
- Scans `memory/10-daily/`. For each file derives:
  - `kind`: `"daily"` if filename matches `YYYY-MM-DD`, `"weekly"` if `YYYY-Www`.
  - `sort_key` (ISO date string): the date for dailies; the ISO week's last day
    (Sunday) for weeklies.
  - `id`: the filename stem (e.g. `2026-05-21`, `2022-W34`).
  - `title`: from frontmatter / first H1, else a formatted date.
  - `has_photos`: body contains an `![[...]]` embed.
  - `snippet`: first ~140 chars of prose (markdown/headers stripped).
- Provides: `list_notes()` (lightweight, sorted newest-first), `read_note(id)`
  (raw markdown + frontmatter), `set_checkbox(id, line, checked)`,
  `random_knowledge_note()`.
- Checkbox write: load file, locate the `- [ ] / - [x]` at the given 1-based line,
  flip it, bump `updated` frontmatter, write back. Errors:
  `PATH_NOT_FOUND` (no such note), `STATE_CONFLICT` (line isn't a checkbox).

### Endpoints
- `GET /notes` → `{ notes: [{ id, sort_key, kind, title, has_photos, snippet }] }`
  — all notes, newest-first. Lightweight; powers the scrubber + virtual list.
- `GET /notes/{id}` → `{ id, kind, sort_key, frontmatter, markdown }` — one note's
  raw body, fetched lazily per row.
- `PATCH /notes/{id}/checkbox` body `{ line: int, checked: bool }` → updated note;
  flips one checkbox in that exact file.
- `GET /notes/featured` → `{ id, title, markdown, source }` — one random knowledge
  note from `60-knowledge/notes/`.

Registered in `apps/vault-server/src/main.py` with a `get_notes()` accessor
following the existing service-accessor pattern.

## Frontend (`apps/telegram-web-app/src/features/time-management/`)

### Dependencies (new)
- `@tanstack/react-virtual` — virtualization.
- `@tanstack/react-query` — list + per-note body caching, optimistic checkbox mutation.
- `react-markdown` + `remark-gfm` — markdown rendering with GFM task lists.
- Fonts: Fraunces, Newsreader, JetBrains Mono (self-hosted or via `<link>`).

### Data flow
- One TanStack Query for `GET /notes` (the metadata list) — drives the virtual
  list and scrubber immediately.
- Per-note `GET /notes/{id}` queries, triggered as rows enter the viewport, cached
  by `id`.
- Checkbox tap → optimistic `PATCH /notes/{id}/checkbox` mutation; on error, roll
  back and toast. On success, toast "task checked".

### Virtualization
- `@tanstack/react-virtual` over the metadata array.
- Dynamic measurement via `measureElement`; rows start at an estimated height,
  re-measure once the body loads.
- Lazy body load keyed on the metadata `id`.

### Rendering
- `react-markdown` + `remark-gfm` renders each note body.
- Custom transforms for Obsidian syntax:
  - `![[file]]` → `<img src="/media/{date}/{file}">` (the `/media` route already
    falls back to vault-wide filename search when the date URL doesn't match).
  - `[[link]]` → styled, non-navigable chip.
- GFM task-list items expose their source line via mdast `position.start.line`;
  a tap maps back to `{ id, line }` for the checkbox PATCH.
- Heterogeneous `##` sections render generically (no per-section special-casing).

### Components
- `TimeManagementPage` — query wiring, layout, scroll container ref.
- `NoteFeed` — the virtualizer over the metadata list.
- `NoteDay` — one day/week: sticky header (weekday/date or "Week NN", token chip),
  lazy body, month-divider when the month changes vs the previous row.
- `NoteMarkdown` — react-markdown wrapper with the Obsidian transforms + interactive
  checkboxes.
- `FeaturedNote` — the random-knowledge-note card pinned at the top of the feed.
- `DateScrubber` — right-edge draggable thumb; while dragging shows a month/year
  bubble; maps drag position → scroll offset using the date distribution of the
  metadata list (proportional to **time**, not item index, so gaps feel right).
- `BackToTopFab` + a "jump to today" affordance in the top bar.

### Design system
- Extract prototype tokens into `theme.css` / a tokens module:
  `--paper / --paper-deep / --ink / --ink-soft / --ink-mute / --rule / --rule-soft
  / --terra / --terra-deep / --moss` + shadows. Structured so a dark "ink" palette
  is a later drop-in (same token names, different values under a `data-theme`).
- Paper texture: the two fixed layers (radial warmth + SVG `feTurbulence` noise,
  multiply blend).
- Type utilities: `.display` (Fraunces), body (Newsreader), `.mono` / `.label`
  (JetBrains Mono).
- Reused micro-interactions: hairline month dividers (`::before/::after` flex
  rules), hover/tap padding nudge on tappable rows, bottom-sheet + toast
  (toast confirms checkbox writes).

### Routing / cleanup
- `app/Router.tsx`: add `/time-management`, redirect `/dayplanner` → it, point `/`
  at it.
- Remove `features/dayplanner/` (DayplannerPage, store, Timeline, DayHeader,
  EventCard) and the events-only types in `models/event` that only it used
  (keep what `playground` imports).
- Keep shared `DateNav` (used by `playground`).

## Testing

### vault-server
- `NotesService`: `kind`/`sort_key` derivation — daily vs weekly end-of-week anchor.
- List ordering newest-first; weekly slotted by week's last day.
- `snippet` / `has_photos` extraction.
- `set_checkbox`: flips the correct line, bumps `updated`; `STATE_CONFLICT` when the
  line isn't a checkbox; `PATH_NOT_FOUND` for a missing note.
- `random_knowledge_note` returns a well-formed note (or empty-safe when none).

### webapp
- Obsidian transforms: `![[file]]` → media URL, `[[link]]` → chip.
- Checkbox line-mapping: rendered checkbox ↔ source line round-trips.
- Scrubber position ↔ date math (proportional to time across uneven density).
- List ordering / weekly anchoring in the metadata transform.

## Risks & mitigations
- **Font glyph coverage** — notes mix English/Russian/Hebrew; Fraunces has limited
  Cyrillic. Body uses Newsreader (full Cyrillic); verify a display fallback for
  headings that contain Cyrillic/Hebrew before shipping.
- **Scrubber ↔ virtual mapping** with uneven note density — map by date span, not
  item index, so dragging feels proportional to time and gaps don't collapse.
- **Initial body fetch storms** — cap concurrent in-view body fetches; rely on
  TanStack Query caching + the estimated-height placeholder to keep scroll smooth.
