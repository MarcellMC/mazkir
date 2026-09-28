# Docs

Index of what lives where under `docs/`. Start at the repo root
[`CLAUDE.md`](../CLAUDE.md) for the live architecture reference; this folder
holds the design/planning history and reference material behind it.

- **`specs/`** — hand-written design docs (the "why" and "what", decided
  before code). A doc that is both a design and a plan lives here too.
- **`plans/`** — hand-written implementation plans (the "how", task-by-task).
- **`superpowers/specs/`, `superpowers/plans/`** — same split, but owned by
  the `superpowers` skills, which write here by default. Left in place.
- **`research/<topic>/`** — investigation reports and supporting notes on a
  question, not tied to a single ship (e.g. "should we adopt X").
- **`archive/`** — retired docs, kept for reference only.
- **`roadmap.md`** — the project roadmap (moved from the repo root).
- **`observability.md`**, **`technical-decisions-presentation.html`** — standalone reference docs.

## Key docs

- [`roadmap.md`](roadmap.md) — project roadmap
- [`observability.md`](observability.md) — structured logs, Loki/Grafana, Phoenix tracing
- [`specs/2026-08-21-time-management-phase2-capture-design.md`](specs/2026-08-21-time-management-phase2-capture-design.md) — the parent design behind the current Ship 2–5 and Fast Lane work in `superpowers/`
- [`research/jev-message-routing/report.md`](research/jev-message-routing/report.md) — whether TypeSafe AI's Jev fits Mazkir's message router

## Finding a doc

- Looking for the design behind a shipped feature named in `CLAUDE.md`? Check
  `superpowers/specs/` first (recent ships), then `specs/` (everything
  before the superpowers workflow).
- Looking for how something was built step-by-step? Check `superpowers/plans/`
  or `plans/` the same way.
- Looking for background research behind a decision, not a design itself?
  Check `research/<topic>/`.
