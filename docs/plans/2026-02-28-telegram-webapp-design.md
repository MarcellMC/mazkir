# Mazkir Telegram WebApp — Design Document

**Date:** 2026-02-28
**Status:** Approved
**Handoff doc:** `docs/plans/mazkir-webapp-handoff.md`

---

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Data strategy | Real vault-server APIs from day one | Mock data for TDD tests, real data for QA |
| Build order | App shell + data layer, then Dayplanner + Playground in parallel | Independent workstreams, fastest path to MVP |
| Generation backend | Replicate API | ControlNet + style transfer support needed for playground experiments |
| Timeline data source | JSON (Semantic Location History) from disk | Best semantic info (activity types, place names, durations) |
| Timeline data path | `data/timeline/` (gitignored) | User drops Takeout export here, vault-server reads it |
| CORS | FastAPI CORS middleware for localhost | Webapp makes browser fetch() calls to vault-server |
| Generation API calls | Proxied through vault-server | Keep API keys server-side, consistent with architecture |

## Architecture

### New Vault-Server Endpoints

```
GET  /timeline/{date}        → Parse Timeline JSON, return place visits + activity segments
GET  /merged-events/{date}   → Merge calendar + timeline + daily (habits/tokens) into MergedEvent[]
POST /generate               → Proxy generation request to Replicate API
GET  /imagery/search         → Search Wikimedia/Mapillary for contextual images by lat/lng
```

### Webapp Structure

```
apps/telegram-web-app/
├── src/
│   ├── app/                   # App shell, routing, Telegram SDK init
│   ├── features/
│   │   ├── dayplanner/        # Vertical timeline view of merged events
│   │   └── playground/        # Generation experiment workspace
│   ├── services/
│   │   └── api.ts             # HTTP client for vault-server endpoints
│   ├── models/
│   │   └── event.ts           # MergedEvent types (mirrors vault-server)
│   └── shared/                # Shared components, utils
├── public/
├── index.html
├── package.json
├── tsconfig.json
├── vite.config.ts
└── tailwind.config.js
```

### Data Flow

```
Google Calendar API ──→ /calendar/events ──┐
                                           ├──→ /merged-events/{date} ──→ MergedEvent[]
Timeline JSON on disk ──→ /timeline/{date} ┘           │
                                                       ├──→ Dayplanner UI
/daily (habits, tokens) ──────────────────────────────→┘

MergedEvent + style config ──→ /generate ──→ Replicate API ──→ Generated assets
lat/lng ──→ /imagery/search ──→ Wikimedia/Mapillary ──→ Contextual images
```

### MergedEvent Model

As defined in handoff doc (`docs/plans/mazkir-webapp-handoff.md`, lines 129-179). Implemented as:
- Pydantic model in vault-server (Python)
- TypeScript interface in webapp (mirrored)

### Merger Logic

1. Load calendar events for date via existing `/calendar/events`
2. Load Timeline data for date via new `/timeline/{date}`
3. Match calendar events to Timeline visits by time overlap (±30min) and proximity (<500m)
4. Matched → merge into single MergedEvent with combined data
5. Unmatched calendar → keep as-is, no geo data
6. Unmatched Timeline visits → `unplanned_stop` type
7. Timeline activity segments between stops → `transit` events with route data
8. Sort chronologically, fill gaps with `home` or `unknown`
9. Attach habit/token data from `/daily`

## Stack

- **Framework:** React 18 + Vite
- **Styling:** Tailwind CSS
- **Telegram SDK:** `@twa-dev/sdk`
- **State:** Zustand (simple global store)
- **HTTP:** fetch API with typed wrapper
- **Generation:** Replicate API (via vault-server proxy)
- **Maps (playground):** Leaflet with custom styling
- **SVG:** D3.js for programmatic route sketches

## Vault-Server Changes

1. Add CORS middleware in `main.py`
2. Add `TIMELINE_DATA_PATH` and `REPLICATE_API_TOKEN` to config
3. New service: `timeline_service.py` — parse Semantic Location History JSON
4. New service: `merger_service.py` — merge calendar + timeline + daily data
5. New service: `generation_service.py` — Replicate API proxy
6. New service: `imagery_service.py` — Wikimedia/Mapillary search
7. New routes: `timeline.py`, `merged_events.py`, `generate.py`, `imagery.py`
8. Add `data/` to root `.gitignore`

## Not In Scope (YAGNI)

- Interactive animated SVG maps
- Collectible place cards / territory fog-of-war
- File upload UI for Timeline data
- Production deployment / hosting
- Bot-side slash commands (`/map`, `/app`, `/playground`)
- WebApp ↔ bot `sendData()` communication
