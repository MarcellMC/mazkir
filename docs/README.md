# Docs

Index of what lives where under `docs/`. Start at the repo root
[`CLAUDE.md`](../CLAUDE.md) for the live architecture reference; this folder
holds the design/planning history and reference material behind it.

- **`specs/`** — design docs (the "why" and "what", decided before code),
  named `YYYY-MM-DD-<topic>-design.md`. A doc that is both a design and a plan
  lives here too.
- **`plans/`** — implementation plans (the "how", task-by-task), named
  `YYYY-MM-DD-<topic>.md`.
- **`research/<topic>/`** — investigation reports and supporting notes on a
  question, not tied to a single ship (e.g. "should we adopt X").
- **`archive/`** — retired docs, kept for reference only.
- **`roadmap.md`** — the project roadmap.
- **`observability.md`**, **`technical-decisions-presentation.html`** — standalone reference docs.

There is one folder per *kind* of doc, not one per author: hand-written specs
and plans and ones written by the `superpowers` skills sit side by side in
`specs/` and `plans/`. Those skills default to `docs/superpowers/{specs,plans}/`
and the repo `CLAUDE.md` overrides that, so a file appearing under
`docs/superpowers/` means the override was missed — move it.

## Key docs

- [`roadmap.md`](roadmap.md) — project roadmap
- [`observability.md`](observability.md) — structured logs, Loki/Grafana, Phoenix tracing
- [`specs/2026-08-21-time-management-phase2-capture-design.md`](specs/2026-08-21-time-management-phase2-capture-design.md) — the parent design behind the Ship 2–5 and Fast Lane work
- [`specs/2026-09-27-fast-lane-design.md`](specs/2026-09-27-fast-lane-design.md) — the current arc
- [`research/jev-message-routing/report.md`](research/jev-message-routing/report.md) — whether TypeSafe AI's Jev fits Mazkir's message router

## Finding a doc

- Both folders sort chronologically by filename, so the newest design or plan
  is the last entry.
- Looking for the design behind a shipped feature named in `CLAUDE.md`? Check
  `specs/`.
- Looking for how something was built step-by-step? Check `plans/` — usually
  the same date prefix and topic slug as the spec, minus `-design`.
- Looking for background research behind a decision, not a design itself?
  Check `research/<topic>/`.
