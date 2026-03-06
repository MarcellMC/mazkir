# Agent Editing & Events Unification Design

**Date:** 2026-03-06
**Status:** Approved

## Overview

Four related improvements to Mazkir:
1. Give the agent full vault editing capabilities (daily note sections, delete/archive items)
2. Unify `/merged-events` and `/events` into a single auto-refreshing endpoint
3. Add date picker to Playground webapp
4. Sync persisted events to Google Calendar (lower priority)

## Issue 1: Agent Vault Editing Gaps

### Current State

The agent has 19 tools including `update_item(path, updates)` for generic frontmatter updates, `create_task/habit/goal`, and `complete_task/habit`. Gaps:

- **Daily note body:** Only `append_to_daily_section()` exists. No way to read or replace section content.
- **Delete/archive:** Only `complete_task` (archive + award tokens) and `complete_habit` exist. No way to delete tasks, archive without completing, delete habits, or archive goals.

### New Agent Tools

#### Safe (read-only)

| Tool | Parameters | Purpose |
|------|-----------|---------|
| `read_daily_section` | `section` (str), `date?` (YYYY-MM-DD) | Read content of a daily note section as text |

#### Write

| Tool | Parameters | Purpose |
|------|-----------|---------|
| `edit_daily_section` | `section` (str), `content` (str), `date?` (YYYY-MM-DD) | Replace entire section content in daily note |

#### Destructive

| Tool | Parameters | Purpose |
|------|-----------|---------|
| `delete_task` | `task_name` (str, fuzzy) | Delete a task file permanently |
| `archive_task` | `task_name` (str, fuzzy) | Move task to archive without awarding tokens |
| `delete_habit` | `habit_name` (str, fuzzy) | Delete a habit file permanently |
| `archive_goal` | `goal_name` (str, fuzzy) | Set goal status to "archived" |

### VaultService Changes

- Add `read_daily_section(section, date?) -> str` — parse daily note, return section content
- Add `replace_daily_section(section, content, date?)` — find section header, replace content up to next header
- Add `delete_file(relative_path)` — delete a vault file
- Add `archive_task(task_path)` — move to `40-tasks/archive/` without token award
- Existing `find_task_by_name` and similar fuzzy matching reused for new tools

## Issue 2: Unify `/merged-events` and `/events`

### Current State

- `GET /merged-events/{date}` — live merge from calendar + timeline + habits + daily notes. Ephemeral, no persistence. No photos/assets.
- `GET /events/{date}` — reads persisted `data/events/{date}.json`. Has photos/assets. Only populated by explicit `POST /events/{date}/refresh` or agent tools.

These should be one endpoint.

### Design

- **`GET /events/{date}`** becomes the single endpoint. On each request it:
  1. Runs MergerService to get fresh events from all sources
  2. Loads existing persisted events from `data/events/{date}.json` (if any)
  3. Reconciles: matches by `source_ids`, preserves `id`/`photos`/`assets` from existing, updates name/time/location from fresh
  4. Saves reconciled result to disk
  5. Returns the result

- **`GET /merged-events/{date}`** — deprecated, redirects to `/events/{date}` or removed outright
- **`POST /events/{date}/refresh`** — kept as alias (same behavior as GET now, but explicit intent)
- **Webapp** — switch both Playground and Dayplanner to use `/events/{date}`

### Performance Note

The merge + persist on every GET adds latency (calendar API call, timeline parse, disk write). If this becomes a problem, add a short TTL cache (e.g., 60s) so repeated requests within a minute return cached data without re-merging.

## Issue 3: Date Picker in Playground

### Current State

Playground hardcodes today's date. Dayplanner has `setDate()` in store but no UI.

### Design

- Add `date` and `setDate(date)` to Playground Zustand store
- Add a shared `DateNav` component: `< [date-input] >` with back/forward day buttons
- Use native `<input type="date">` for the picker
- Place above the event list in both Playground and Dayplanner
- On date change, reload events

## Issue 4: Events-to-Calendar Sync (Lower Priority)

### Current State

One-way: Google Calendar feeds into merged events. Manually created or photo-based events in `data/events/` have no calendar representation.

### Design

- When `EventsService.create_event()` is called and the event has a time, optionally create a Google Calendar event
- Store the resulting `calendar_id` in `source_ids` so future refreshes match correctly
- Add `sync_to_calendar` flag (default: false) to `create_event` to opt in
- Agent tool `create_event` gets optional `sync_to_calendar` parameter
