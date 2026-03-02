# Mazkir Telegram WebApp — Context Handoff

**Date:** 2026-02-28
**Target:** Claude Code session
**Project Location:** `apps/telegram-web-app` inside existing Mazkir Turborepo

---

## Project Overview

Build a Telegram Mini App (WebApp) for the Mazkir personal AI assistant bot. Two core features:

1. **Enriched Dayplanner** — a unified daily view merging Google Calendar events with Google Timeline geolocation data, enriched with generated visual assets (icons, route sketches, token summaries)
2. **Asset Generation Playground** — an interactive workspace for experimenting with different image/vector generation approaches for map illustrations, icons, and scene cards

The app lives inside an existing Turborepo monorepo as `apps/telegram-web-app`. TypeScript throughout.

---

## Architecture

### Turborepo Structure

```
mazkir/
├── apps/
│   ├── telegram-bot/          # Existing Mazkir Telegram bot
│   └── telegram-web-app/      # THIS PROJECT — new Telegram Mini App
├── packages/
│   ├── shared/                # Shared types, utilities
│   └── ...
├── turbo.json
└── package.json
```

### Telegram Mini App

- Launched from Mazkir bot via inline button or `/app` command
- Uses Telegram WebApp SDK (`@twa-dev/sdk` or vanilla `window.Telegram.WebApp`)
- Hosted as a web app, URL registered with BotFather
- Communicates with bot backend for data

### Agent-Parallel Development

Structure the app for independent parallel development by multiple agents:

```
apps/telegram-web-app/
├── src/
│   ├── app/                   # App shell, routing, Telegram SDK init
│   ├── features/
│   │   ├── dayplanner/        # HIGH — Enriched dayplanner view
│   │   └── playground/        # HIGH — Asset generation playground
│   ├── services/
│   │   ├── timeline/          # Google Timeline data parsing & cleaning
│   │   ├── calendar/          # Google Calendar data fetching
│   │   ├── merger/            # Event model merging logic
│   │   ├── imagery/           # Open-source image sourcing (Wikimedia, Mapillary, OSM)
│   │   └── generation/        # Image/vector generation pipelines
│   ├── models/
│   │   └── event.ts           # Merged Event Model types
│   └── shared/                # App-internal shared utils, components
├── public/
├── package.json
└── tsconfig.json
```

Each `features/*` and `services/*` directory is a self-contained module. Agents can work on them independently.

---

## Feature 1: Enriched Dayplanner (HIGH PRIORITY)

### What It Is

A vertical timeline view of a day showing every event/stop with:
- Event name, time, duration
- Location (place name + mini route sketch showing how you got there)
- Activity type icon (generated, styled)
- Habit completion status + tokens earned
- Contextual imagery (sourced from open data)

### Visual Layout (Approximate)

```
┌──────────────────────────────────────┐
│  📅 Friday, February 27, 2026       │
│  🪙 +28 tokens | Streak: 14 🔥      │
├──────────────────────────────────────┤
│  06:30  🌅 Wake up                   │
│                                      │
│  07:00  🐕 Dog walk — Yarkon Park    │
│         [route sketch: 0.8km walk]   │
│         [small contextual image]     │
│                                      │
│  08:30  ☕ Café Xoho, Dizengoff      │
│         [icon: coffee, styled]       │
│                                      │
│  10:00  💻 Home — Deep work          │
│         ╌╌╌ 6 hours ╌╌╌             │
│                                      │
│  16:00  💪 Gym — Holmes Place        │
│         [route: bus 🚌 12min]        │
│         ✅ Habit complete +10 🪙     │
│         [keyframe scene card]        │
│                                      │
│  18:30  🛒 Carmel Market             │
│         [route: walking 8min]        │
│                                      │
│  20:00  🏠 Home                      │
├──────────────────────────────────────┤
│  Day map: [thumbnail → tap to open]  │
└──────────────────────────────────────┘
```

### Data Flow

```
Google Calendar API ──┐
                      ├─→ Merger Service ──→ Merged Event[] ──→ Dayplanner UI
Google Timeline JSON ─┘         │
                                ├─→ Imagery Service (contextual photos)
                                └─→ Generation Service (icons, routes)
```

### Merged Event Model

```typescript
interface MergedEvent {
  id: string;
  
  // What
  name: string;
  type: 'habit' | 'task' | 'calendar' | 'unplanned_stop' | 'transit' | 'home';
  activityCategory?: 'gym' | 'walk' | 'cafe' | 'shopping' | 'work' | 'social' | string;
  
  // When
  startTime: Date;
  endTime: Date;
  durationMinutes: number;
  
  // Where
  location?: {
    name: string;
    lat: number;
    lng: number;
    placeId?: string;  // Google or OSM place ID
  };
  
  // How you got there
  routeFrom?: {
    mode: 'walking' | 'driving' | 'transit' | 'cycling' | 'unknown';
    distanceMeters: number;
    durationMinutes: number;
    polyline: [number, number][];  // lat,lng pairs
    confidence: 'high' | 'medium' | 'low';  // data quality
  };
  
  // PKM integration
  habit?: {
    name: string;
    completed: boolean;
    streak: number;
    tokensEarned: number;
  };
  tokensEarned: number;
  
  // Generated assets (populated by generation pipeline)
  assets?: {
    microIcon?: string;      // URL/path to generated vector icon
    keyframeScene?: string;  // URL/path to generated scene card
    routeSketch?: string;    // URL/path to generated route illustration
    contextImage?: string;   // URL/path to sourced contextual image
  };
  
  // Data quality
  source: 'calendar' | 'timeline' | 'merged';
  confidence: 'high' | 'medium' | 'low';
}
```

### Merger Logic

1. Load calendar events for the day (structured, named, intentional)
2. Load Timeline data for the day (GPS traces, place visits, activity segments)
3. For each calendar event: find Timeline visit with overlapping time window (±30min) and proximity (<500m)
4. Matched → merge into single MergedEvent with combined data
5. Unmatched calendar events → keep as-is, no geo data
6. Unmatched Timeline visits → create as `unplanned_stop` type
7. Timeline activity segments between stops → become `transit` events with route data
8. Sort chronologically, fill gaps with `home` or `unknown`

---

## Feature 2: Asset Generation Playground (HIGH PRIORITY)

### What It Is

An interactive sandbox UI where I can:
- Load a day's merged event data (or mock data)
- Select individual events or the full day
- Try different generation approaches and compare results
- Tweak parameters, styles, prompts
- Save successful outputs and configurations

### Generation Experiments to Support

| Experiment | Priority | Description |
|---|---|---|
| Hybrid SVG→AI map | Medium | Programmatic route SVG as ControlNet input → styled output |
| Micro icon generation | Medium | Small vector/raster activity icons in various art styles |
| Keyframe scene cards | Medium | Larger illustrated "moment" cards per event, using location photos + local art as reference |
| Contextual imagery sourcing | Medium | Pull and display relevant open-source images (Wikimedia, Mapillary, paintings) |
| Artistic data corruption | Low | Fog/clouds for missing GPS, dashed uncertain paths |
| Day-score-to-quality mapping | Low | Map render quality/detail scales with day productivity |
| Collectible card art | Low | Place cards that evolve visually with visit frequency |

### Playground UI

```
┌─────────────────────────────────────────────┐
│  🎨 Asset Generation Playground             │
├──────────┬──────────────────────────────────┤
│          │                                  │
│  Event   │  Generation Panel                │
│  List    │                                  │
│          │  [Approach selector]              │
│  • Walk  │  [Style / model config]          │
│  • Café  │  [Reference images]              │
│  > Gym ← │  [Generate button]               │
│  • Shop  │                                  │
│  • Home  │  ┌──────────────────────┐        │
│          │  │                      │        │
│  ──────  │  │   Generated Output   │        │
│  Full    │  │                      │        │
│  Day Map │  │                      │        │
│          │  └──────────────────────┘        │
│          │                                  │
│          │  [Save] [Compare] [Params JSON]  │
└──────────┴──────────────────────────────────┘
```

### Generation Service Interface

```typescript
interface GenerationRequest {
  type: 'micro_icon' | 'keyframe_scene' | 'route_sketch' | 'full_day_map';
  event?: MergedEvent;           // single event context
  events?: MergedEvent[];        // full day context (for map)
  style: StyleConfig;
  approach: 'ai_raster' | 'svg_programmatic' | 'hybrid_svg_to_ai' | 'style_transfer';
  referenceImages?: string[];    // URLs of contextual/reference images
  params?: Record<string, any>; // approach-specific parameters
}

interface StyleConfig {
  // Can be a named city style or custom
  preset?: string;              // 'tel-aviv' | 'jerusalem' | 'default' | ...
  palette?: string[];           // override colors
  lineStyle?: 'loose_ink' | 'clean_vector' | 'crosshatch' | 'watercolor_edge';
  texture?: 'linen_paper' | 'rough_paper' | 'clean' | 'aged_parchment';
  artReference?: string;        // description or image URL of reference style
}

interface GenerationResult {
  imageUrl: string;
  format: 'png' | 'svg' | 'webp';
  metadata: {
    approach: string;
    model?: string;
    prompt?: string;
    generationTimeMs: number;
    params: Record<string, any>;
  };
}
```

---

## Service: Open-Source Imagery (MEDIUM PRIORITY)

### Sources

| Source | What | API/Access |
|---|---|---|
| Wikimedia Commons | Geotagged CC photos of places, landmarks | MediaWiki API, geosearch endpoint |
| Mapillary | Street-level imagery | Mapillary API v4 (free tier) |
| OpenStreetMap | Building footprints, POI data, map tiles | Overpass API, tile servers |
| WikiArt / public domain art | Paintings by local artists for style reference | WikiArt API or curated collection |
| Unsplash | High-quality keyword-based photos | Unsplash API (free tier) |

### Usage

- **As generation context:** feed location photos to AI model as style/composition reference
- **As dayplanner content:** display relevant contextual images alongside events
- **As style reference:** local artist paintings inform city-specific art style configs

---

## Backlog (Not for initial build, but for awareness)

- **Interactive animated SVG map** — route draws itself, fog reveals, timeline scrubber
- **Tap-to-expand stops** on map
- **Collectible place cards** — functional gamification (unlock, level up)
- **Territory fog-of-war** — cumulative city exploration tracking
- **Route achievements** — distance/exploration badges
- **Stop vignettes on full map** — illustrated icons at stops
- **Combo triptychs** — merged art for habit stacks (low priority, playground first)

---

## Technical Decisions

### Stack (Suggested)

- **Framework:** React + Vite (fast, Turborepo-friendly)
- **Styling:** Tailwind CSS
- **Telegram SDK:** `@twa-dev/sdk`
- **Maps (if needed in playground):** Leaflet or Mapbox GL JS with custom styling
- **State:** Zustand or React Context (keep it simple)
- **Image generation:** API-based initially (configurable — could be OpenAI DALL-E, Stability AI, or self-hosted SD)
- **SVG generation:** D3.js or custom programmatic SVG builders

### Telegram Mini App Setup

- Register WebApp URL with BotFather
- Bot sends inline keyboard button to launch app
- App reads `window.Telegram.WebApp` for theme, user data, init params
- Init params can pass context (e.g., selected date)
- App can send data back to bot via `sendData()`

### Data Access

- Google Timeline: user uploads JSON export (Google Takeout), or future API integration
- Google Calendar: via bot backend (already has Calendar MCP integration)
- PKM vault: via bot backend API (reads habit/token data from vault)

### Slash Commands (Bot Side)

```
/map [date]        → Generates static illustrated map, sends as image
/app [date]        → Opens WebApp with dayplanner for that date
/playground        → Opens WebApp in playground mode
```

These are bot-side commands that launch the WebApp or trigger generation. The WebApp itself doesn't implement slash commands.

---

## PKM Vault Context

The app integrates with Marc's Obsidian-based PKM vault. Key details:

- **Vault path:** `/home/marcellmc/pkm`
- **Daily notes:** `10-daily/YYYY-MM-DD.md`
- **Habits:** `20-habits/[habit-name].md` — has streak, last_completed, tokens_per_completion
- **Token ledger:** `00-system/motivation-tokens.md`
- **Full vault schema:** see `AGENTS.md` in vault root

The dayplanner view should reflect data from daily notes (completed habits, tokens) merged with geo data. Generated assets could eventually be stored in the vault alongside daily notes.

---

## Development Approach

### Parallel Workstreams

| Stream | Scope | Dependencies |
|---|---|---|
| **A: App Shell** | Vite + React scaffold, Telegram SDK, routing, Turborepo integration | None |
| **B: Data Layer** | Timeline parser, Calendar fetcher, Merger service, Event model | None |
| **C: Dayplanner UI** | Dayplanner component, event cards, layout | A (shell), B (data) |
| **D: Playground UI** | Playground component, generation panel, comparison view | A (shell) |
| **E: Imagery Service** | Wikimedia/Mapillary/OSM API clients, image sourcing | None |
| **F: Generation Service** | Generation interfaces, initial approach implementations | E (imagery as input) |

Streams A, B, D, E can start immediately in parallel.
C needs A+B. F needs E.

### MVP Milestone

Deployable Telegram Mini App with:
- ✅ Opens from bot
- ✅ Dayplanner view showing merged Calendar + Timeline events for a day
- ✅ Playground view with at least one working generation approach
- ✅ Contextual images displayed from open sources

---

## Key Principles

- **Manual triggers, not scheduled** — generation happens via slash commands or user-initiated actions, not cron jobs
- **Experiment-first** — the playground is for rapid iteration on visual approaches, not production polish
- **Lightweight** — don't over-engineer; simple data flow, simple UI, focus on the visual/generative experiments
- **Parallel-friendly** — modular structure so multiple agents can work simultaneously without conflicts
