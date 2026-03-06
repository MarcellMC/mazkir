# Timeline Events Unification Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Unify `/merged-events` and `/events` into a single auto-refreshing endpoint, switch the webapp to use it, and add date navigation to both Playground and Dayplanner.

**Architecture:** `GET /events/{date}` auto-merges from all sources (calendar, timeline, habits, daily notes), reconciles with persisted data (preserving photos/assets/manual events), saves to disk, and returns enriched events. `/merged-events` is removed. Webapp gets a shared `DateNav` component with back/forward buttons and date picker.

**Tech Stack:** Python (FastAPI, pytest), TypeScript (React, Zustand, Tailwind, vitest)

---

### Task 1: EventsService — add `auto_refresh` method

**Files:**
- Modify: `apps/vault-server/src/services/events_service.py`
- Test: `apps/vault-server/tests/test_events_service.py`

**Step 1: Write the failing tests**

Add to `tests/test_events_service.py`:

```python
class TestAutoRefresh:
    def test_auto_refresh_returns_merged_events(self, events_service):
        fresh = [
            {"name": "Standup", "type": "calendar", "start_time": "10:00",
             "end_time": "10:30", "source": "calendar",
             "source_ids": {"calendar_id": "cal_1"}},
        ]
        result = events_service.auto_refresh("2026-03-06", fresh)
        assert len(result) == 1
        assert result[0]["name"] == "Standup"
        assert "id" in result[0]

        # Should be persisted
        persisted = events_service.get_events("2026-03-06")
        assert len(persisted) == 1

    def test_auto_refresh_preserves_photos(self, events_service):
        events_service.create_event(
            date="2026-03-06", name="Cafe", start_time="15:00",
            photo_path="photo.jpg", caption="Latte",
        )
        fresh = [
            {"name": "Standup", "type": "calendar", "start_time": "10:00",
             "end_time": "10:30", "source": "calendar",
             "source_ids": {"calendar_id": "cal_1"}},
        ]
        result = events_service.auto_refresh("2026-03-06", fresh)
        names = [e["name"] for e in result]
        assert "Standup" in names
        assert "Cafe" in names
        cafe = next(e for e in result if e["name"] == "Cafe")
        assert len(cafe["photos"]) == 1

    def test_auto_refresh_empty_fresh_keeps_manual(self, events_service):
        events_service.create_event(
            date="2026-03-06", name="Manual event", start_time="14:00",
        )
        result = events_service.auto_refresh("2026-03-06", [])
        assert len(result) == 1
        assert result[0]["name"] == "Manual event"
```

**Step 2: Run tests to verify they fail**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_events_service.py::TestAutoRefresh -v`
Expected: FAIL — `auto_refresh` not defined

**Step 3: Implement `auto_refresh`**

Add to `apps/vault-server/src/services/events_service.py` after `refresh_events`:

```python
def auto_refresh(self, date: str, fresh_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge fresh events with persisted data and save.

    Alias for refresh_events — used by the unified GET /events endpoint.
    """
    return self.refresh_events(date, fresh_events)
```

**Step 4: Run tests to verify they pass**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_events_service.py::TestAutoRefresh -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add apps/vault-server/src/services/events_service.py apps/vault-server/tests/test_events_service.py
git commit -m "feat(events-service): add auto_refresh method for unified endpoint"
```

---

### Task 2: Rewrite `GET /events/{date}` to auto-refresh from sources

**Files:**
- Modify: `apps/vault-server/src/api/routes/events.py`

**Step 1: Read the current file**

Read `apps/vault-server/src/api/routes/events.py` and `apps/vault-server/src/api/routes/merged_events.py` to understand both patterns.

**Step 2: Rewrite events.py**

Replace `apps/vault-server/src/api/routes/events.py` with:

```python
"""Unified events API — auto-merges from sources on read, persists enriched data."""

from datetime import date as date_type

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.services.merger_service import MergerService

router = APIRouter(prefix="/events", tags=["events"])


class PatchEventBody(BaseModel):
    photos: list[dict] | None = None
    assets: dict[str, str] | None = None
    name: str | None = None
    location: dict | None = None


async def _merge_from_sources(date: date_type) -> list[dict]:
    """Run MergerService against all sources and return fresh event dicts."""
    from src.main import get_vault, get_calendar, get_timeline

    vault = get_vault()
    calendar = get_calendar()
    timeline = get_timeline()

    calendar_events = []
    if calendar and calendar.is_initialized:
        try:
            calendar_events = await calendar.get_todays_events(
                all_calendars=True, target_date=date,
            )
        except Exception:
            pass

    timeline_data = {"visits": [], "activities": []}
    if timeline:
        try:
            timeline_data = timeline.get_day(date)
        except Exception:
            pass

    habits = []
    try:
        raw_habits = vault.list_active_habits()
        date_str = date.isoformat()
        for h in raw_habits:
            meta = h["metadata"]
            habits.append({
                "name": meta.get("name", ""),
                "completed_today": meta.get("last_completed") == date_str,
                "streak": meta.get("streak", 0),
                "tokens_per_completion": meta.get("tokens_per_completion", 5),
            })
    except Exception:
        pass

    daily = {}
    try:
        daily = vault.read_daily_note(date)
        daily = daily.get("metadata", {})
    except Exception:
        pass

    merger = MergerService(timezone="Asia/Jerusalem")
    events = merger.merge(
        calendar_events=calendar_events,
        timeline_data=timeline_data,
        habits=habits,
        daily=daily,
    )
    return [e.model_dump() for e in events]


@router.get("/{date}")
async def get_events(date: date_type):
    """Get events for a date — auto-merges from sources and persists."""
    from src.main import get_events as get_events_svc
    events_svc = get_events_svc()
    if not events_svc:
        raise HTTPException(503, "Events service not initialized")

    fresh = await _merge_from_sources(date)
    result = events_svc.auto_refresh(date.isoformat(), fresh)

    return {
        "date": date.isoformat(),
        "events": result,
        "summary": {
            "total_events": len(result),
            "total_tokens": sum(e.get("tokens_earned", 0) for e in result),
        },
    }


@router.post("/{date}/refresh")
async def refresh_events(date: date_type):
    """Force-refresh events from sources (same as GET, explicit intent)."""
    result = await get_events(date)
    result["refreshed"] = True
    return result


@router.patch("/{date}/{event_id}")
async def patch_event(date: str, event_id: str, body: PatchEventBody):
    """Update a single persisted event."""
    from src.main import get_events as get_events_svc
    events_svc = get_events_svc()
    if not events_svc:
        raise HTTPException(503, "Events service not initialized")

    events = events_svc.get_events(date)
    for event in events:
        if event["id"] == event_id:
            updates = body.model_dump(exclude_none=True)
            event.update(updates)
            events_svc.save_events(date, events)
            return {"updated": event_id, "event": event}

    raise HTTPException(404, f"Event {event_id} not found")
```

**Step 3: Verify server tests still pass**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/ -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add apps/vault-server/src/api/routes/events.py
git commit -m "feat(events): rewrite GET /events to auto-refresh from all sources"
```

---

### Task 3: Remove `/merged-events` endpoint

**Files:**
- Delete: `apps/vault-server/src/api/routes/merged_events.py`
- Modify: `apps/vault-server/src/main.py`

**Step 1: Remove router registration from main.py**

In `apps/vault-server/src/main.py`:
- Remove: `from src.api.routes.merged_events import router as merged_events_router`
- Remove: `app.include_router(merged_events_router)`

**Step 2: Delete the file**

Delete `apps/vault-server/src/api/routes/merged_events.py`.

**Step 3: Check no tests reference merged_events**

Run: `cd apps/vault-server && grep -r "merged_events\|merged-events" tests/`
Expected: No matches (or only in comments)

**Step 4: Run full server tests**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/ -v`
Expected: All PASS

**Step 5: Commit**

```bash
git rm apps/vault-server/src/api/routes/merged_events.py
git add apps/vault-server/src/main.py
git commit -m "refactor: remove /merged-events endpoint, replaced by unified /events"
```

---

### Task 4: Webapp — switch API client to `/events`

**Files:**
- Modify: `apps/telegram-web-app/src/services/api.ts`
- Modify: `apps/telegram-web-app/src/features/playground/store.ts`
- Modify: `apps/telegram-web-app/src/features/dayplanner/store.ts`

**Step 1: Update API client**

In `apps/telegram-web-app/src/services/api.ts`, replace the `getMergedEvents` method:

```typescript
// Replace:
getMergedEvents(date: string): Promise<MergedEventsResponse> {
    return request(`/merged-events/${date}`)
},

// With:
getEvents(date: string): Promise<MergedEventsResponse> {
    return request(`/events/${date}`)
},
```

**Step 2: Update Playground store**

In `apps/telegram-web-app/src/features/playground/store.ts`, change the `loadEvents` method:

```typescript
// Replace api.getMergedEvents(date) with:
const data = await api.getEvents(date)
```

**Step 3: Update Dayplanner store**

In `apps/telegram-web-app/src/features/dayplanner/store.ts`, change the `fetchDay` method:

```typescript
// Replace api.getMergedEvents(date) with:
const data: MergedEventsResponse = await api.getEvents(date)
```

**Step 4: Run webapp tests**

Run: `cd apps/telegram-web-app && npx vitest run`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/telegram-web-app/src/services/api.ts \
  apps/telegram-web-app/src/features/playground/store.ts \
  apps/telegram-web-app/src/features/dayplanner/store.ts
git commit -m "feat(webapp): switch to unified /events endpoint"
```

---

### Task 5: Webapp — shared DateNav component

**Files:**
- Create: `apps/telegram-web-app/src/components/DateNav.tsx`

**Step 1: Create the component**

Create `apps/telegram-web-app/src/components/DateNav.tsx`:

```tsx
interface DateNavProps {
  date: string
  onChange: (date: string) => void
}

function shiftDate(date: string, days: number): string {
  const d = new Date(date + 'T00:00:00')
  d.setDate(d.getDate() + days)
  return d.toISOString().split('T')[0]!
}

export default function DateNav({ date, onChange }: DateNavProps) {
  return (
    <div className="flex items-center gap-2 px-4 py-2 bg-white border-b border-gray-200">
      <button
        onClick={() => onChange(shiftDate(date, -1))}
        className="px-2 py-1 text-gray-500 hover:text-gray-900 hover:bg-gray-100 rounded"
      >
        &lt;
      </button>
      <input
        type="date"
        value={date}
        onChange={(e) => onChange(e.target.value)}
        className="flex-1 text-center text-sm font-medium bg-transparent border-none outline-none"
      />
      <button
        onClick={() => onChange(shiftDate(date, 1))}
        className="px-2 py-1 text-gray-500 hover:text-gray-900 hover:bg-gray-100 rounded"
      >
        &gt;
      </button>
    </div>
  )
}
```

**Step 2: Commit**

```bash
git add apps/telegram-web-app/src/components/DateNav.tsx
git commit -m "feat(webapp): add shared DateNav component with date picker and day navigation"
```

---

### Task 6: Webapp — add date navigation to Playground

**Files:**
- Modify: `apps/telegram-web-app/src/features/playground/store.ts`
- Modify: `apps/telegram-web-app/src/features/playground/PlaygroundPage.tsx`

**Step 1: Add date state to Playground store**

In `apps/telegram-web-app/src/features/playground/store.ts`:

Add to `PlaygroundState` interface:
```typescript
date: string
setDate: (date: string) => void
```

Add to `create()` initial state:
```typescript
date: new Date().toISOString().split('T')[0]!,
```

Add `setDate` action:
```typescript
setDate: (date) => {
    set({ date })
    get().loadEvents(date)
},
```

Update the `useEffect` trigger in `PlaygroundPage.tsx` — change from hardcoded today to `store.date`:
```typescript
useEffect(() => {
    store.loadEvents(store.date)
}, [])
```

**Step 2: Wire DateNav into PlaygroundPage**

Update `apps/telegram-web-app/src/features/playground/PlaygroundPage.tsx`:

```tsx
import { useEffect } from 'react'
import { usePlaygroundStore } from './store'
import EventList from './components/EventList'
import GenerationPanel from './components/GenerationPanel'
import DateNav from '../../components/DateNav'

export default function PlaygroundPage() {
  const store = usePlaygroundStore()

  useEffect(() => {
    store.loadEvents(store.date)
  }, [])

  return (
    <div className="h-screen flex flex-col bg-gray-50">
      <div className="px-4 py-3 border-b border-gray-200 bg-white">
        <h1 className="text-lg font-semibold">Asset Generation Playground</h1>
      </div>

      <DateNav date={store.date} onChange={store.setDate} />

      <div className="flex-1 flex overflow-hidden">
        <div className="w-1/3 min-w-[140px] max-w-[200px]">
          <EventList
            events={store.events}
            selectedEvent={store.selectedEvent}
            onSelect={store.selectEvent}
          />
        </div>
        <div className="flex-1">
          <GenerationPanel
            selectedEvent={store.selectedEvent}
            genType={store.genType}
            approach={store.approach}
            style={store.style}
            generating={store.generating}
            result={store.result}
            onGenTypeChange={store.setGenType}
            onApproachChange={store.setApproach}
            onStyleChange={store.setStyle}
            onGenerate={store.generate}
          />
        </div>
      </div>
    </div>
  )
}
```

**Step 3: Run webapp tests**

Run: `cd apps/telegram-web-app && npx vitest run`
Expected: PASS

**Step 4: Commit**

```bash
git add apps/telegram-web-app/src/features/playground/store.ts \
  apps/telegram-web-app/src/features/playground/PlaygroundPage.tsx
git commit -m "feat(playground): add date navigation with DateNav component"
```

---

### Task 7: Webapp — add date navigation to Dayplanner

**Files:**
- Modify: `apps/telegram-web-app/src/features/dayplanner/DayplannerPage.tsx`
- Modify: `apps/telegram-web-app/src/features/dayplanner/components/DayHeader.tsx`

**Step 1: Update DayHeader to remove date display (now handled by DateNav)**

Replace `apps/telegram-web-app/src/features/dayplanner/components/DayHeader.tsx`:

```tsx
interface DayHeaderProps {
  totalTokens: number
}

export default function DayHeader({ totalTokens }: DayHeaderProps) {
  if (totalTokens <= 0) return null
  return (
    <div className="px-4 py-1 bg-white border-b border-gray-100">
      <p className="text-sm text-gray-500">+{totalTokens} tokens</p>
    </div>
  )
}
```

**Step 2: Wire DateNav into DayplannerPage**

Replace `apps/telegram-web-app/src/features/dayplanner/DayplannerPage.tsx`:

```tsx
import { useEffect } from 'react'
import { useDayplannerStore } from './store'
import DateNav from '../../components/DateNav'
import DayHeader from './components/DayHeader'
import Timeline from './components/Timeline'

export default function DayplannerPage() {
  const { date, events, totalTokens, loading, error, setDate, fetchDay } =
    useDayplannerStore()

  useEffect(() => {
    fetchDay(date)
  }, [date, fetchDay])

  return (
    <div className="min-h-screen bg-gray-50">
      <DateNav date={date} onChange={setDate} />
      <DayHeader totalTokens={totalTokens} />

      {loading && (
        <div className="p-8 text-center text-gray-400">Loading...</div>
      )}

      {error && (
        <div className="p-4 m-4 bg-red-50 text-red-700 rounded-lg text-sm">
          {error}
        </div>
      )}

      {!loading && !error && <Timeline events={events} />}
    </div>
  )
}
```

**Step 3: Run webapp tests**

Run: `cd apps/telegram-web-app && npx vitest run`
Expected: PASS

**Step 4: Commit**

```bash
git add apps/telegram-web-app/src/features/dayplanner/DayplannerPage.tsx \
  apps/telegram-web-app/src/features/dayplanner/components/DayHeader.tsx
git commit -m "feat(dayplanner): add date navigation with DateNav component"
```

---

### Task 8: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update endpoint docs**

- Remove all `/merged-events` references
- Update `/events/{date}` description: "Auto-merges calendar+timeline+habits+daily notes, reconciles with persisted data (preserving photos/assets), returns enriched events"
- Update `GET /events/{date}` in quick commands section
- Update webapp description to mention date navigation
- Note that `POST /events/{date}/refresh` is kept as explicit force-refresh alias

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for unified events endpoint and webapp date navigation"
```
