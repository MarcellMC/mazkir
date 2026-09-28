# Unified Timed-Event Capture — Design

**Date:** 2026-06-09
**Status:** Approved, pending implementation plan
**Author:** brainstorming session (trace `9db5b780`)

## Problem

A timed event reported to Mazkir gets filed as a long-term knowledge note instead of
being recorded in the daily note and synced to Google Calendar.

**Observed failure** (Phoenix trace `9db5b78097c6567c7b48d8e24365435f`, 2026-06-07 19:59):

> User: *"I've attended a pub meeting with former colleagues from Momentick today
> between 20:00 to 22:30 at Shnitt brewery"*

Flow: router → `skill.capture` → `save_knowledge` → wrote
`60-knowledge/notes/pub-meeting-with-momentick-colleagues.md`. No daily-note record,
no calendar event.

### Root causes

1. **Tool mis-selection.** The `capture` skill (Haiku) classified a timed past event as
   "an idea/fact worth remembering" and called `save_knowledge`. Its prompt offers only
   four buckets — task / idea-fact / daily-log note / habit-goal — with no concept of a
   timed event. `edit_daily_section` was available and unused.
2. **Capability gap.** `create_event` — which *does* sync to Google Calendar directly
   (`agent_service.py:2403-2429`) — is **not** in the `capture` skill's toolset (only the
   `manager` skill has it). And `create_event` writes only to the events store
   (`data/events/{date}.json`) + GCal, **not** the daily markdown note.

So neither half of the user's expectation (daily-note record + calendar event) was
reachable from the path the message took.

## Decisions

| Decision | Choice | Rationale |
| --- | --- | --- |
| Data model | **Unified** — `create_event` is the one canonical "timed thing" action; it writes the daily-note line **and** the events store **and** syncs GCal | Avoids the two writes drifting out of sync; one tool call satisfies both halves |
| Recognition / handling | **In `capture`** — add `create_event` to its toolset + prompt rule | The router already routed correctly; the failure was tool choice *within* capture. Keeps it one fast Haiku hop |
| Daily-note home | **New `## Schedule` section** | Semantically correct home for timed events; mirrors the GCal entry; keeps events out of free-form `## Notes` |
| `/day` sourcing | **No new `/day` source** | `create_event` syncs to GCal, so the event already surfaces in `/day` and `/calendar` via the existing `calendar` source. Reading `## Schedule` too would double-count |
| Photo events | **Unchanged** | `create_event` calls with `photo_path` keep today's behavior (photo pipeline, no GCal, no `## Schedule` line). The unified daily-note write applies only to regular timed events |

## Components & Changes

### 1. `## Schedule` section in the daily note

- **Template** (`memory/00-system/templates/_daily_.md`): add `## Schedule` between
  `## Tasks` and `## Food`.
- **Line format:** `- {start}–{end} {title} @ {location} {wikilinks}` — `end`,
  `@ {location}`, and trailing wikilinks all optional. Example:
  `- 20:00–22:30 Pub meeting @ Shnitt brewery [[Momentick]]`
- **Parser/renderer:** a small service mirroring the existing `DailyTasksService`
  pattern (`services/daily_tasks.py`) — read existing lines, append idempotently,
  render back. Either extend `daily_tasks.py` or add a sibling `daily_schedule.py`
  (implementation plan decides; sibling preferred for single-purpose clarity).

### 2. `create_event` becomes the unified action

`agent_service.py::_tool_create_event`:

- **Kept:** events-store write + best-effort GCal sync (existing logic).
- **Added:** append a line to today's `## Schedule` section. Skipped when `photo_path`
  is set.
- **Order:** events store → daily-note line → GCal. The three writes are independent;
  a GCal failure never blocks the daily-note/events write (matches current
  warning-log behavior).
- **`_items`:** include the daily-note path alongside the events-store path so the
  write is auditable in `tool-calls.jsonl`.

### 3. `capture` skill gains `create_event`

`memory/00-system/mazkir-skills/capture.md`:

- Add `create_event` to the `tools:` list.
- Add a prompt rule: *content anchored to a specific time or timeframe (past or future)
  is an **event** → `create_event`. Pure facts / ideas / quotes with no time →
  `save_knowledge`.*
- Add a worked example (the pub-meeting case) so the classification is concrete.

## Data Flow (fixed)

```
"attended pub meeting 20:00–22:30 at Shnitt brewery"
  → router → capture
  → create_event{name, start_time, end_time, location, date=today}
      ├─ events store  (data/events/2026-06-07.json)
      ├─ daily note    (## Schedule line)
      └─ GCal          (best-effort sync, stores calendar_id in source_ids)
  → /day & /calendar surface it via the GCal calendar source (no double-count)
```

## Error Handling

- Events-store write + daily-note write are the durable record.
- GCal sync stays best-effort: failures log at WARNING with `trace_id`, never raise.
- Daily-note write failure also logs at WARNING and does not block the events-store
  write; the tool still returns `ok: true` with whatever succeeded reflected in
  `_items`.

## Testing

- `capture` routes a timed-event utterance to `create_event` (not `save_knowledge`).
- A timeless fact ("Paris is the capital of France") still routes to `save_knowledge`
  — regression guard against over-triggering `create_event`.
- `create_event` appends a correctly-formatted `## Schedule` line; the parser
  round-trips; a second call appends without clobbering existing lines.
- `photo_path` events skip the `## Schedule` write.
- GCal-unavailable path still writes the events store + daily note (`ok: true`).

## Out of Scope

- Backfilling / migrating the existing `pub-meeting-with-momentick-colleagues.md`
  knowledge note (can be handled manually or in a follow-up).
- Changing the `manager` skill (it already has `create_event` and will inherit the
  unified daily-note behavior for free).
- Any `/day` feed schema change.
