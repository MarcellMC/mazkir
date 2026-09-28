# Photo → Merged Events → Playground Pipeline

## Problem

Photos sent via Telegram are saved to disk and passed to Claude vision, but:
1. No EXIF metadata (GPS, timestamp) is extracted
2. Photos have no structured link to merged events
3. Merged events are ephemeral — regenerated on every request, no persistence
4. `/day` command doesn't render the Notes section where photo entries land
5. Webapp Dayplanner/Playground can't use photos as they aren't on events

## Design Decisions

- **Event persistence:** JSON file per day at `data/events/{date}.json`
- **Photo metadata:** EXIF extracted on save via Pillow, stored in sidecar `data/media/{date}/metadata.json`
- **Event association:** Photos linked to events in the event JSON, not the photo sidecar
- **Agent-driven disposition:** Claude agent decides whether to attach photo to existing event, create a new event, or simply log to daily note
- **Generic event creation:** `create_event` tool works for any source (photo, text, calendar), not photo-specific

## Architecture

### Data Flow

```
Telegram photo → bot downloads → POST /message with base64
    ↓
AgentService._save_photo()
  1. Save JPEG to data/media/{date}/
  2. Extract EXIF (GPS, timestamp) via Pillow
  3. Append entry to data/media/{date}/metadata.json
  4. Surface to agent: "[Photo saved: path | EXIF: lat, lng, taken]"
    ↓
Claude agent (vision + context)
  - Sees photo + EXIF context + conversation history
  - Calls list_events to check today's events
  - Infers user intent, then one of:
    a) attach_photo_to_event (link to existing event)
    b) create_event (new event from photo/text/etc.)
    c) attach_to_daily (just log to Notes, no event)
  - If unable to infer, asks user for clarification
    ↓
data/events/{date}.json updated
    ↓
GET /merged-events/{date} → reads persisted JSON
    ↓
Webapp: Dayplanner shows photo thumbs, Playground uses photos as references
```

## Component Details

### 1. EXIF Extraction

**New dependency:** Pillow (PIL)

In `_save_photo()`, after writing the file:
- Open with `PIL.Image.open()`, read EXIF via `image._getexif()`
- Extract GPS coordinates (tags 0x8825 → GPSLatitude, GPSLongitude, GPSLatitudeRef, GPSLongitudeRef)
- Extract DateTimeOriginal (tag 0x9003)
- Convert GPS from DMS to decimal degrees
- If EXIF is absent or incomplete, fields are null

**Sidecar JSON** at `data/media/{date}/metadata.json`:

```json
[
  {
    "filename": "photo_2026-03-04_14-30-00.jpg",
    "path": "data/media/2026-03-04/photo_2026-03-04_14-30-00.jpg",
    "saved_at": "2026-03-04T14:30:00",
    "exif_timestamp": "2026-03-04T14:28:15",
    "exif_location": {"lat": 32.0853, "lng": 34.7818},
    "exif_camera": "Apple iPhone 15 Pro"
  }
]
```

The sidecar is a photo registry only — no event associations here.

**Agent context string:**
```
[Photo saved to: data/media/2026-03-04/photo_14-30-00.jpg | EXIF: 32.0853, 34.7818 taken 14:28 | Camera: iPhone 15 Pro]
```
If no EXIF GPS: `[Photo saved to: ... | No GPS data in EXIF]`

### 2. Merged Event Persistence

**Storage:** `data/events/{date}.json`

**Lifecycle:**
- `GET /merged-events/{date}` — if JSON exists, return it. Otherwise run merge algorithm, persist, return.
- `POST /merged-events/{date}/refresh` — re-merge from sources (calendar + timeline + habits). Reconcile with persisted data: match by `source_ids`, carry over `photos` and `assets` from existing events. Preserve manually-created events (source='manual'/'photo') that have no source match.
- `PATCH /merged-events/{date}/{event_id}` — update a single event (photos, assets, caption, etc.).

**Stable IDs:** Generated on first persist. Format: `evt_{uuid4_short}` (8 chars). Stored alongside source IDs for re-merge matching.

**MergedEvent gains:**
```python
photos: list[PhotoRef]    # [{path, caption, wikilinks}]
source_ids: SourceIds     # {calendar_id?, timeline_place_id?}
```

**PhotoRef:**
```python
class PhotoRef:
    path: str              # relative path: "data/media/2026-03-04/photo.jpg"
    caption: str | None
    wikilinks: list[str]
```

**Re-merge reconciliation algorithm:**
1. Run fresh merge from sources → new_events[]
2. Load persisted events → old_events[]
3. For each new_event, find matching old_event by source_ids (calendar_id or timeline_place_id)
4. If match: keep old event's `id`, `photos`, `assets`; update time/location/name from source
5. If no match: assign new ID, add to result
6. Append any old events with source='manual'/'photo' that weren't matched (agent-created)
7. Persist and return

### 3. Agent Tools

**`list_events`** (safe)
- Returns today's persisted events: id, name, start_time, end_time, location, source, photo count
- Agent uses this to decide whether to attach or create

**`attach_photo_to_event`** (write)
- Params: `event_id`, `photo_path`, `caption?`, `wikilinks?`
- Reads event JSON, finds event by ID, appends to `photos[]`
- Requires `_confidence`, `_reasoning`

**`create_event`** (write)
- Params: `name`, `start_time?`, `end_time?`, `location?` ({lat, lng, name}), `category?`, `photo_path?`, `caption?`, `wikilinks?`
- Creates new event in `data/events/{date}.json` with `source='manual'` (or `source='photo'` if photo_path provided)
- Generates stable `evt_` ID
- Requires `_confidence`, `_reasoning`

**`attach_to_daily`** (write) — unchanged
- Simple markdown logging to `## Notes`
- Used when the photo doesn't warrant an event (e.g., a screenshot, a meme)

### 4. `/day` Command — Notes Section

**vault-server:**
- `VaultService` gets a `get_daily_notes_section()` method that parses `## Notes` content from the daily note markdown
- `GET /daily` response (`DailyResponse`) gains a `notes: list[str]` field with the parsed entries

**telegram-bot:**
- `formatDay()` renders a Notes section after Schedule if `data.notes.length > 0`
- Photo entries shown as caption text (no inline images in Telegram — just the text description)

### 5. Webapp Integration (future phase, not in scope for initial implementation)

- Dayplanner `EventCard` renders photo thumbnails from `event.photos[]`
- Playground passes attached photos as `reference_images` to generation
- New endpoint to serve photos: `GET /media/{date}/{filename}`

## File Changes Summary

### vault-server
- `pyproject.toml` — add Pillow dependency
- `config.py` — add `events_path` setting (default: `~/dev/mazkir/data/events`)
- `main.py` — pass `events_path` to AgentService
- `services/agent_service.py` — EXIF extraction in `_save_photo()`, sidecar JSON write, new tools (`list_events`, `attach_photo_to_event`, `create_event`), updated agent context string
- `services/merger_service.py` — persistence layer: read/write `data/events/{date}.json`, re-merge reconciliation, stable IDs
- `api/routes/merged_events.py` — read from persisted JSON, add `POST .../refresh` and `PATCH .../event_id`
- `services/vault_service.py` — add `get_daily_notes_section()`
- `api/routes/daily.py` — include notes in response

### telegram-bot
- `src/formatters/telegram.ts` — render Notes section in `formatDay()`

### shared-types
- `src/events.ts` — add `photos`, `source_ids` to `MergedEvent`; add `PhotoRef` interface
- `src/daily.ts` — add `notes` to `DailyResponse`

## Non-Goals (this iteration)
- Webapp changes (Dayplanner photo thumbs, Playground reference images)
- Photo serving endpoint
- Strengthening system prompt to auto-call attach_to_daily for photos
- Batch photo upload
- Video attachments
