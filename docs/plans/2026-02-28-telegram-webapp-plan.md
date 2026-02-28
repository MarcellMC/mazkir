# Telegram WebApp Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Telegram Mini App with an Enriched Dayplanner view and Asset Generation Playground, integrated into the existing Mazkir Turborepo monorepo.

**Architecture:** New React+Vite app at `apps/telegram-web-app/` consuming new vault-server endpoints (`/timeline/{date}`, `/merged-events/{date}`, `/generate`, `/imagery/search`). All data logic lives server-side in vault-server; the webapp is a pure UI layer. Timeline data comes from Google Takeout JSON files on disk.

**Tech Stack:** React 18 + Vite + Tailwind CSS + Zustand (webapp), FastAPI + Pydantic (server), Replicate API (generation), Wikimedia/Mapillary APIs (imagery), @twa-dev/sdk (Telegram)

**Design doc:** `docs/plans/2026-02-28-telegram-webapp-design.md`
**Handoff doc:** `docs/plans/mazkir-webapp-handoff.md`

---

## Dependency Graph

```
Task 1 (Scaffold webapp) ──────────────────────┐
Task 2 (Telegram SDK + routing) ←── Task 1     │
                                                │
Task 3 (CORS + config) ────────────────────┐    │
Task 4 (Timeline service) ←── Task 3       │    │
Task 5 (Merger service) ←── Task 4         │    │
Task 6 (Server routes) ←── Task 5          │    │
                                           │    │
Task 7 (API client + types) ←── Task 1,6 ──┘────┘
Task 8 (Dayplanner UI) ←── Task 2,7

Task 9 (Imagery service) ←── Task 3
Task 10 (Generation service) ←── Task 9
Task 11 (Gen+imagery routes) ←── Task 10
Task 12 (Playground UI) ←── Task 2,7,11
```

**Parallel tracks:**
- Track 1: Tasks 1→2 (app shell)
- Track 2: Tasks 3→4→5→6 (server data layer)
- Track 3: Tasks 9→10→11 (server generation layer)
- Track 1+2 merge at Task 7→8 (dayplanner)
- Track 1+2+3 merge at Task 12 (playground)

---

## Task 1: Scaffold Webapp

**Files:**
- Create: `apps/telegram-web-app/package.json`
- Create: `apps/telegram-web-app/tsconfig.json`
- Create: `apps/telegram-web-app/tsconfig.app.json`
- Create: `apps/telegram-web-app/tsconfig.node.json`
- Create: `apps/telegram-web-app/vite.config.ts`
- Create: `apps/telegram-web-app/tailwind.config.js`
- Create: `apps/telegram-web-app/postcss.config.js`
- Create: `apps/telegram-web-app/index.html`
- Create: `apps/telegram-web-app/src/main.tsx`
- Create: `apps/telegram-web-app/src/App.tsx`
- Create: `apps/telegram-web-app/src/index.css`
- Modify: `apps/telegram-web-app/.gitignore` (node_modules, dist)

**Step 1: Create package.json**

```json
{
  "name": "telegram-web-app",
  "private": true,
  "version": "0.0.1",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "lint": "eslint . --ext ts,tsx --report-unused-disable-directives --max-warnings 0",
    "test": "vitest run"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.28.0",
    "zustand": "^5.0.0",
    "@twa-dev/sdk": "^7.0.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.0",
    "autoprefixer": "^10.4.20",
    "postcss": "^8.4.49",
    "tailwindcss": "^3.4.17",
    "typescript": "^5.6.0",
    "vite": "^6.0.0",
    "vitest": "^2.1.0",
    "@testing-library/react": "^16.1.0",
    "@testing-library/jest-dom": "^6.6.0",
    "jsdom": "^25.0.0"
  }
}
```

**Step 2: Create vite.config.ts**

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Not proxying — webapp calls vault-server directly via CORS
    }
  }
})
```

**Step 3: Create Tailwind + PostCSS config**

`tailwind.config.js`:
```javascript
/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}
```

`postcss.config.js`:
```javascript
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
```

**Step 4: Create TypeScript configs**

`tsconfig.json`:
```json
{
  "files": [],
  "references": [
    { "path": "./tsconfig.app.json" },
    { "path": "./tsconfig.node.json" }
  ]
}
```

`tsconfig.app.json`:
```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "noUncheckedIndexedAccess": true,
    "baseUrl": ".",
    "paths": {
      "@/*": ["src/*"]
    }
  },
  "include": ["src"]
}
```

`tsconfig.node.json`:
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2023"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "strict": true
  },
  "include": ["vite.config.ts"]
}
```

**Step 5: Create index.html + entry point**

`index.html`:
```html
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
    <title>Mazkir</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`src/index.css`:
```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

`src/main.tsx`:
```tsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
```

`src/App.tsx`:
```tsx
function App() {
  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <h1 className="text-xl font-bold">Mazkir</h1>
      <p className="text-gray-600">App shell loaded.</p>
    </div>
  )
}

export default App
```

**Step 6: Install dependencies and verify**

```bash
cd apps/telegram-web-app && npm install
```

**Step 7: Verify dev server starts**

```bash
cd apps/telegram-web-app && npm run dev
# Expected: Vite dev server on http://localhost:5173, shows "Mazkir" heading
```

**Step 8: Verify Turborepo integration**

```bash
cd ~/dev/mazkir && npx turbo dev --filter=telegram-web-app
# Expected: Vite dev server starts via Turborepo
```

**Step 9: Commit**

```bash
git add apps/telegram-web-app/
git commit -m "feat: scaffold telegram-web-app with Vite + React + Tailwind"
```

---

## Task 2: Telegram SDK + Routing

**Files:**
- Create: `apps/telegram-web-app/src/app/telegram.ts`
- Create: `apps/telegram-web-app/src/app/Router.tsx`
- Create: `apps/telegram-web-app/src/features/dayplanner/DayplannerPage.tsx`
- Create: `apps/telegram-web-app/src/features/playground/PlaygroundPage.tsx`
- Modify: `apps/telegram-web-app/src/App.tsx`

**Step 1: Create Telegram SDK wrapper**

`src/app/telegram.ts`:
```typescript
import WebApp from '@twa-dev/sdk'

export function initTelegram() {
  WebApp.ready()
  WebApp.expand()
}

export function getTelegramTheme() {
  return {
    bgColor: WebApp.themeParams.bg_color || '#ffffff',
    textColor: WebApp.themeParams.text_color || '#000000',
    hintColor: WebApp.themeParams.hint_color || '#999999',
    buttonColor: WebApp.themeParams.button_color || '#3390ec',
    buttonTextColor: WebApp.themeParams.button_text_color || '#ffffff',
  }
}

export function getInitData(): { date?: string; mode?: string } {
  const params = new URLSearchParams(WebApp.initData)
  const startParam = params.get('start_param') || ''
  // Format: "dayplanner_2026-02-28" or "playground"
  const [mode, date] = startParam.split('_')
  return { mode: mode || 'dayplanner', date }
}
```

**Step 2: Create placeholder page components**

`src/features/dayplanner/DayplannerPage.tsx`:
```tsx
export default function DayplannerPage() {
  return (
    <div className="p-4">
      <h1 className="text-xl font-bold">Dayplanner</h1>
      <p className="text-gray-500">Coming soon</p>
    </div>
  )
}
```

`src/features/playground/PlaygroundPage.tsx`:
```tsx
export default function PlaygroundPage() {
  return (
    <div className="p-4">
      <h1 className="text-xl font-bold">Playground</h1>
      <p className="text-gray-500">Coming soon</p>
    </div>
  )
}
```

**Step 3: Create router**

`src/app/Router.tsx`:
```tsx
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import DayplannerPage from '../features/dayplanner/DayplannerPage'
import PlaygroundPage from '../features/playground/PlaygroundPage'

export default function Router() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/dayplanner" replace />} />
        <Route path="/dayplanner" element={<DayplannerPage />} />
        <Route path="/playground" element={<PlaygroundPage />} />
      </Routes>
    </BrowserRouter>
  )
}
```

**Step 4: Wire up App.tsx**

`src/App.tsx`:
```tsx
import { useEffect } from 'react'
import Router from './app/Router'
import { initTelegram } from './app/telegram'

function App() {
  useEffect(() => {
    try {
      initTelegram()
    } catch {
      // Not running inside Telegram — dev mode
    }
  }, [])

  return <Router />
}

export default App
```

**Step 5: Verify routing works in browser**

```bash
cd apps/telegram-web-app && npm run dev
# Visit http://localhost:5173/ → redirects to /dayplanner
# Visit http://localhost:5173/playground → shows Playground heading
```

**Step 6: Commit**

```bash
git add apps/telegram-web-app/src/
git commit -m "feat: add Telegram SDK init and dayplanner/playground routing"
```

---

## Task 3: Vault-Server CORS + Config

**Files:**
- Modify: `apps/vault-server/src/main.py` (add CORS middleware)
- Modify: `apps/vault-server/src/config.py` (add TIMELINE_DATA_PATH, REPLICATE_API_TOKEN, CORS settings)
- Modify: `.gitignore` (add `data/`)
- Create: `data/timeline/.gitkeep`

**Step 1: Add new config settings**

In `apps/vault-server/src/config.py`, add these fields to the `Settings` class after the existing Google Calendar settings:

```python
    # Timeline data
    timeline_data_path: Path = Path(os.getenv("TIMELINE_DATA_PATH", str(Path.home() / "dev" / "mazkir" / "data" / "timeline")))

    # Replicate API (for image generation)
    replicate_api_token: str | None = os.getenv("REPLICATE_API_TOKEN")

    # CORS
    cors_origins: str = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
```

**Step 2: Add CORS middleware to main.py**

In `apps/vault-server/src/main.py`, add after the FastAPI app creation (after line 56):

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Step 3: Add data/ to .gitignore**

Append to root `.gitignore`:

```
# Timeline data (Google Takeout exports)
data/
```

**Step 4: Create data directory**

```bash
mkdir -p data/timeline
touch data/timeline/.gitkeep
```

Wait — `.gitkeep` won't be tracked if `data/` is gitignored. Instead, just create the directory and document the path. The directory will be created by the user when they drop their Takeout export.

**Step 5: Verify vault-server still starts**

```bash
cd apps/vault-server && source venv/bin/activate && python -m uvicorn src.main:app --reload --port 8000
# Expected: Server starts, health endpoint still works
```

```bash
curl http://localhost:8000/health
# Expected: {"status":"ok","vault":true}
```

**Step 6: Verify CORS headers**

```bash
curl -i -X OPTIONS http://localhost:8000/health -H "Origin: http://localhost:5173" -H "Access-Control-Request-Method: GET"
# Expected: access-control-allow-origin: http://localhost:5173
```

**Step 7: Commit**

```bash
git add apps/vault-server/src/main.py apps/vault-server/src/config.py .gitignore
git commit -m "feat: add CORS middleware and timeline/replicate config to vault-server"
```

---

## Task 4: Timeline Parser Service

**Files:**
- Create: `apps/vault-server/src/services/timeline_service.py`
- Create: `apps/vault-server/tests/test_timeline_service.py`

This service reads Google Takeout Semantic Location History JSON and returns structured place visits + activity segments for a given date.

**Reference — Semantic Location History JSON structure:**

```json
{
  "timelineObjects": [
    {
      "placeVisit": {
        "location": {
          "latitudeE7": 321234567,
          "longitudeE7": 346789012,
          "name": "Holmes Place Dizengoff",
          "address": "Dizengoff St 123, Tel Aviv",
          "placeId": "ChIJ...",
          "locationConfidence": 85.0
        },
        "duration": {
          "startTimestamp": "2026-02-27T16:00:00.000Z",
          "endTimestamp": "2026-02-27T17:30:00.000Z"
        },
        "placeConfidence": "HIGH_CONFIDENCE",
        "visitConfidence": 95
      }
    },
    {
      "activitySegment": {
        "startLocation": { "latitudeE7": 321234567, "longitudeE7": 346789012 },
        "endLocation": { "latitudeE7": 321234890, "longitudeE7": 346789345 },
        "duration": {
          "startTimestamp": "2026-02-27T15:30:00.000Z",
          "endTimestamp": "2026-02-27T16:00:00.000Z"
        },
        "distance": 2400,
        "activityType": "IN_BUS",
        "confidence": "HIGH",
        "waypointPath": {
          "waypoints": [
            { "latE7": 321234567, "lngE7": 346789012 },
            { "latE7": 321234700, "lngE7": 346789100 }
          ]
        }
      }
    }
  ]
}
```

The newer on-device format uses `semanticSegments` instead of `timelineObjects`. The service should handle both.

**Step 1: Write failing tests**

`apps/vault-server/tests/test_timeline_service.py`:

```python
import json
from datetime import date
from pathlib import Path

import pytest

from src.services.timeline_service import TimelineService


SAMPLE_LEGACY_DATA = {
    "timelineObjects": [
        {
            "placeVisit": {
                "location": {
                    "latitudeE7": 321078900,
                    "longitudeE7": 346818400,
                    "name": "Holmes Place Dizengoff",
                    "address": "Dizengoff St 123, Tel Aviv",
                    "placeId": "ChIJtest123",
                    "locationConfidence": 85.0,
                },
                "duration": {
                    "startTimestamp": "2026-02-27T16:00:00.000Z",
                    "endTimestamp": "2026-02-27T17:30:00.000Z",
                },
                "placeConfidence": "HIGH_CONFIDENCE",
                "visitConfidence": 95,
            }
        },
        {
            "activitySegment": {
                "startLocation": {"latitudeE7": 321078900, "longitudeE7": 346818400},
                "endLocation": {"latitudeE7": 321085000, "longitudeE7": 346825000},
                "duration": {
                    "startTimestamp": "2026-02-27T15:30:00.000Z",
                    "endTimestamp": "2026-02-27T16:00:00.000Z",
                },
                "distance": 2400,
                "activityType": "IN_BUS",
                "confidence": "HIGH",
                "waypointPath": {
                    "waypoints": [
                        {"latE7": 321078900, "lngE7": 346818400},
                        {"latE7": 321085000, "lngE7": 346825000},
                    ]
                },
            }
        },
    ]
}


SAMPLE_NEW_FORMAT_DATA = {
    "semanticSegments": [
        {
            "startTime": "2026-02-27T16:00:00.000Z",
            "endTime": "2026-02-27T17:30:00.000Z",
            "visit": {
                "topCandidate": {
                    "placeId": "ChIJtest456",
                    "semanticType": "TYPE_SEARCHED_ADDRESS",
                    "probability": 0.85,
                    "placeLocation": {
                        "latLng": "32.1079°N, 34.6818°E"
                    }
                }
            }
        },
        {
            "startTime": "2026-02-27T15:30:00.000Z",
            "endTime": "2026-02-27T16:00:00.000Z",
            "activity": {
                "topCandidate": {
                    "type": "IN_BUS",
                    "probability": 0.9
                },
                "distanceMeters": 2400.0
            },
            "timelinePath": [
                {"point": "32.1079°N, 34.6818°E", "time": "2026-02-27T15:30:00.000Z"},
                {"point": "32.1085°N, 34.6825°E", "time": "2026-02-27T15:45:00.000Z"}
            ]
        }
    ]
}


@pytest.fixture
def timeline_path(tmp_path):
    """Create a temporary timeline data directory with sample files."""
    timeline_dir = tmp_path / "timeline"
    timeline_dir.mkdir()

    # Legacy format: monthly file
    month_dir = timeline_dir / "Semantic Location History" / "2026"
    month_dir.mkdir(parents=True)
    (month_dir / "2026_FEBRUARY.json").write_text(json.dumps(SAMPLE_LEGACY_DATA))

    return timeline_dir


@pytest.fixture
def timeline_path_new_format(tmp_path):
    """Create timeline directory with new on-device format."""
    timeline_dir = tmp_path / "timeline"
    timeline_dir.mkdir()

    # New format: single file per export
    (timeline_dir / "Timeline.json").write_text(json.dumps(SAMPLE_NEW_FORMAT_DATA))

    return timeline_dir


@pytest.fixture
def timeline_service(timeline_path):
    return TimelineService(timeline_path, timezone="Asia/Jerusalem")


@pytest.fixture
def timeline_service_new(timeline_path_new_format):
    return TimelineService(timeline_path_new_format, timezone="Asia/Jerusalem")


class TestTimelineServiceLegacy:
    def test_get_visits_for_date(self, timeline_service):
        visits = timeline_service.get_visits(date(2026, 2, 27))
        assert len(visits) == 1
        assert visits[0]["name"] == "Holmes Place Dizengoff"
        assert visits[0]["lat"] == pytest.approx(32.10789, abs=0.001)
        assert visits[0]["lng"] == pytest.approx(34.68184, abs=0.001)

    def test_get_activities_for_date(self, timeline_service):
        activities = timeline_service.get_activities(date(2026, 2, 27))
        assert len(activities) == 1
        assert activities[0]["mode"] == "transit"
        assert activities[0]["distance_meters"] == 2400

    def test_get_visits_empty_for_other_date(self, timeline_service):
        visits = timeline_service.get_visits(date(2026, 2, 20))
        assert visits == []

    def test_get_day_data_returns_both(self, timeline_service):
        data = timeline_service.get_day(date(2026, 2, 27))
        assert "visits" in data
        assert "activities" in data
        assert len(data["visits"]) == 1
        assert len(data["activities"]) == 1

    def test_waypoints_parsed_to_polyline(self, timeline_service):
        activities = timeline_service.get_activities(date(2026, 2, 27))
        polyline = activities[0]["polyline"]
        assert len(polyline) == 2
        assert polyline[0] == pytest.approx([32.10789, 34.68184], abs=0.001)


class TestTimelineServiceNewFormat:
    def test_get_visits_new_format(self, timeline_service_new):
        visits = timeline_service_new.get_visits(date(2026, 2, 27))
        assert len(visits) == 1
        assert visits[0]["place_id"] == "ChIJtest456"

    def test_get_activities_new_format(self, timeline_service_new):
        activities = timeline_service_new.get_activities(date(2026, 2, 27))
        assert len(activities) == 1
        assert activities[0]["mode"] == "transit"


class TestTimelineServiceMissing:
    def test_no_data_dir_returns_empty(self, tmp_path):
        service = TimelineService(tmp_path / "nonexistent", timezone="Asia/Jerusalem")
        data = service.get_day(date(2026, 2, 27))
        assert data["visits"] == []
        assert data["activities"] == []
```

**Step 2: Run tests to verify they fail**

```bash
cd apps/vault-server && source venv/bin/activate && pytest tests/test_timeline_service.py -v
# Expected: FAIL — ModuleNotFoundError: No module named 'src.services.timeline_service'
```

**Step 3: Implement TimelineService**

`apps/vault-server/src/services/timeline_service.py`:

```python
"""Parse Google Takeout Semantic Location History JSON files."""

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytz


# Map Google activity types to our transport modes
ACTIVITY_MODE_MAP = {
    "WALKING": "walking",
    "ON_FOOT": "walking",
    "RUNNING": "walking",
    "IN_BUS": "transit",
    "IN_SUBWAY": "transit",
    "IN_TRAIN": "transit",
    "IN_TRAM": "transit",
    "IN_VEHICLE": "driving",
    "IN_PASSENGER_VEHICLE": "driving",
    "CYCLING": "cycling",
    "MOTORCYCLING": "driving",
    "IN_FERRY": "transit",
    "FLYING": "unknown",
    "SKIING": "walking",
    "STILL": "unknown",
    "UNKNOWN_ACTIVITY_TYPE": "unknown",
}


class TimelineService:
    def __init__(self, data_path: Path, timezone: str = "Asia/Jerusalem"):
        self.data_path = Path(data_path)
        self.tz = pytz.timezone(timezone)

    def get_day(self, target_date: date) -> dict[str, list]:
        """Get all visits and activities for a given date."""
        return {
            "visits": self.get_visits(target_date),
            "activities": self.get_activities(target_date),
        }

    def get_visits(self, target_date: date) -> list[dict[str, Any]]:
        """Get place visits for a given date."""
        objects = self._load_timeline_objects(target_date)
        visits = []

        for obj in objects:
            visit = self._parse_visit(obj)
            if visit and self._is_on_date(visit["start_time"], target_date):
                visits.append(visit)

        visits.sort(key=lambda v: v["start_time"])
        return visits

    def get_activities(self, target_date: date) -> list[dict[str, Any]]:
        """Get activity segments (transit) for a given date."""
        objects = self._load_timeline_objects(target_date)
        activities = []

        for obj in objects:
            activity = self._parse_activity(obj)
            if activity and self._is_on_date(activity["start_time"], target_date):
                activities.append(activity)

        activities.sort(key=lambda a: a["start_time"])
        return activities

    def _load_timeline_objects(self, target_date: date) -> list[dict]:
        """Load timeline objects from either legacy or new format files."""
        if not self.data_path.exists():
            return []

        objects = []

        # Try legacy format: Semantic Location History/YYYY/YYYY_MONTH.json
        legacy_dir = self.data_path / "Semantic Location History" / str(target_date.year)
        if legacy_dir.exists():
            month_name = target_date.strftime("%B").upper()
            month_file = legacy_dir / f"{target_date.year}_{month_name}.json"
            if month_file.exists():
                data = json.loads(month_file.read_text())
                objects.extend(data.get("timelineObjects", []))

        # Try new format: Timeline.json or per-date files
        for pattern in ["Timeline.json", "*.json"]:
            for f in self.data_path.glob(pattern):
                if f.parent.name == str(target_date.year):
                    continue  # Already handled in legacy path
                try:
                    data = json.loads(f.read_text())
                    if "semanticSegments" in data:
                        objects.extend(
                            self._convert_new_format(data["semanticSegments"])
                        )
                except (json.JSONDecodeError, KeyError):
                    continue

        return objects

    def _convert_new_format(self, segments: list[dict]) -> list[dict]:
        """Convert new semanticSegments format to legacy-compatible objects."""
        objects = []
        for seg in segments:
            if "visit" in seg:
                candidate = seg["visit"].get("topCandidate", {})
                lat, lng = self._parse_latlng_string(
                    candidate.get("placeLocation", {}).get("latLng", "")
                )
                objects.append({
                    "placeVisit": {
                        "location": {
                            "latitudeE7": int(lat * 1e7) if lat else 0,
                            "longitudeE7": int(lng * 1e7) if lng else 0,
                            "name": candidate.get("semanticType", "Unknown"),
                            "placeId": candidate.get("placeId"),
                            "locationConfidence": (candidate.get("probability", 0) * 100),
                        },
                        "duration": {
                            "startTimestamp": seg["startTime"],
                            "endTimestamp": seg["endTime"],
                        },
                        "placeConfidence": "HIGH_CONFIDENCE"
                        if candidate.get("probability", 0) > 0.7
                        else "LOW_CONFIDENCE",
                    }
                })
            elif "activity" in seg:
                candidate = seg["activity"].get("topCandidate", {})
                waypoints = []
                for point in seg.get("timelinePath", []):
                    lat, lng = self._parse_latlng_string(point.get("point", ""))
                    if lat and lng:
                        waypoints.append({"latE7": int(lat * 1e7), "lngE7": int(lng * 1e7)})

                start_lat, start_lng = (
                    (waypoints[0]["latE7"], waypoints[0]["lngE7"]) if waypoints else (0, 0)
                )
                end_lat, end_lng = (
                    (waypoints[-1]["latE7"], waypoints[-1]["lngE7"]) if waypoints else (0, 0)
                )

                objects.append({
                    "activitySegment": {
                        "startLocation": {"latitudeE7": start_lat, "longitudeE7": start_lng},
                        "endLocation": {"latitudeE7": end_lat, "longitudeE7": end_lng},
                        "duration": {
                            "startTimestamp": seg["startTime"],
                            "endTimestamp": seg["endTime"],
                        },
                        "distance": int(seg["activity"].get("distanceMeters", 0)),
                        "activityType": candidate.get("type", "UNKNOWN_ACTIVITY_TYPE"),
                        "confidence": "HIGH"
                        if candidate.get("probability", 0) > 0.7
                        else "LOW",
                        "waypointPath": {"waypoints": waypoints} if waypoints else None,
                    }
                })

        return objects

    @staticmethod
    def _parse_latlng_string(s: str) -> tuple[float | None, float | None]:
        """Parse '32.1079°N, 34.6818°E' to (32.1079, 34.6818)."""
        if not s:
            return None, None
        match = re.findall(r"([\d.]+)°([NSEW])", s)
        if len(match) < 2:
            return None, None
        lat = float(match[0][0]) * (-1 if match[0][1] == "S" else 1)
        lng = float(match[1][0]) * (-1 if match[1][1] == "W" else 1)
        return lat, lng

    def _parse_visit(self, obj: dict) -> dict[str, Any] | None:
        """Parse a placeVisit object into a normalized visit dict."""
        pv = obj.get("placeVisit")
        if not pv:
            return None

        loc = pv.get("location", {})
        dur = pv.get("duration", {})

        start = self._parse_timestamp(dur.get("startTimestamp", ""))
        end = self._parse_timestamp(dur.get("endTimestamp", ""))
        if not start or not end:
            return None

        lat = loc.get("latitudeE7", 0) / 1e7
        lng = loc.get("longitudeE7", 0) / 1e7

        return {
            "name": loc.get("name", "Unknown"),
            "address": loc.get("address"),
            "lat": lat,
            "lng": lng,
            "place_id": loc.get("placeId"),
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "duration_minutes": int((end - start).total_seconds() / 60),
            "confidence": self._map_confidence(pv.get("placeConfidence", "")),
        }

    def _parse_activity(self, obj: dict) -> dict[str, Any] | None:
        """Parse an activitySegment into a normalized activity dict."""
        seg = obj.get("activitySegment")
        if not seg:
            return None

        dur = seg.get("duration", {})
        start = self._parse_timestamp(dur.get("startTimestamp", ""))
        end = self._parse_timestamp(dur.get("endTimestamp", ""))
        if not start or not end:
            return None

        polyline = []
        wp = seg.get("waypointPath")
        if wp and wp.get("waypoints"):
            for w in wp["waypoints"]:
                lat = w.get("latE7", 0) / 1e7
                lng = w.get("lngE7", 0) / 1e7
                polyline.append([lat, lng])

        start_loc = seg.get("startLocation", {})
        end_loc = seg.get("endLocation", {})

        return {
            "mode": ACTIVITY_MODE_MAP.get(seg.get("activityType", ""), "unknown"),
            "distance_meters": seg.get("distance", 0),
            "duration_minutes": int((end - start).total_seconds() / 60),
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "start_lat": start_loc.get("latitudeE7", 0) / 1e7,
            "start_lng": start_loc.get("longitudeE7", 0) / 1e7,
            "end_lat": end_loc.get("latitudeE7", 0) / 1e7,
            "end_lng": end_loc.get("longitudeE7", 0) / 1e7,
            "polyline": polyline,
            "confidence": self._map_confidence(seg.get("confidence", "")),
        }

    def _parse_timestamp(self, ts: str) -> datetime | None:
        """Parse ISO timestamp to timezone-aware datetime."""
        if not ts:
            return None
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.astimezone(self.tz)
        except ValueError:
            return None

    def _is_on_date(self, iso_string: str, target_date: date) -> bool:
        """Check if an ISO timestamp string falls on the target date in local timezone."""
        try:
            dt = datetime.fromisoformat(iso_string)
            return dt.date() == target_date
        except ValueError:
            return False

    @staticmethod
    def _map_confidence(conf: str) -> str:
        conf_upper = conf.upper()
        if "HIGH" in conf_upper:
            return "high"
        if "MEDIUM" in conf_upper or "MED" in conf_upper:
            return "medium"
        return "low"
```

**Step 4: Run tests to verify they pass**

```bash
cd apps/vault-server && source venv/bin/activate && pytest tests/test_timeline_service.py -v
# Expected: All tests PASS
```

**Step 5: Commit**

```bash
git add apps/vault-server/src/services/timeline_service.py apps/vault-server/tests/test_timeline_service.py
git commit -m "feat: add timeline parser service for Google Takeout data"
```

---

## Task 5: Merger Service

**Files:**
- Create: `apps/vault-server/src/services/merger_service.py`
- Create: `apps/vault-server/tests/test_merger_service.py`

The merger service combines calendar events, timeline data, and PKM vault data (habits, tokens) into a unified `MergedEvent[]` for a given date.

**Step 1: Write failing tests**

`apps/vault-server/tests/test_merger_service.py`:

```python
from datetime import date

import pytest

from src.services.merger_service import MergerService, MergedEvent


@pytest.fixture
def calendar_events():
    """Sample calendar events as returned by /calendar/events."""
    return [
        {
            "id": "cal-1",
            "summary": "Gym — Holmes Place",
            "start": "2026-02-27T16:00:00+02:00",
            "end": "2026-02-27T17:30:00+02:00",
            "completed": False,
            "calendar": "Mazkir",
        },
        {
            "id": "cal-2",
            "summary": "Team standup",
            "start": "2026-02-27T10:00:00+02:00",
            "end": "2026-02-27T10:30:00+02:00",
            "completed": False,
            "calendar": "Work",
        },
    ]


@pytest.fixture
def timeline_data():
    """Sample timeline data as returned by TimelineService.get_day()."""
    return {
        "visits": [
            {
                "name": "Holmes Place Dizengoff",
                "address": "Dizengoff St 123, Tel Aviv",
                "lat": 32.1079,
                "lng": 34.6818,
                "place_id": "ChIJtest123",
                "start_time": "2026-02-27T16:05:00+02:00",
                "end_time": "2026-02-27T17:25:00+02:00",
                "duration_minutes": 80,
                "confidence": "high",
            },
            {
                "name": "Carmel Market",
                "lat": 32.0660,
                "lng": 34.7678,
                "place_id": "ChIJmarket",
                "start_time": "2026-02-27T18:30:00+02:00",
                "end_time": "2026-02-27T19:00:00+02:00",
                "duration_minutes": 30,
                "confidence": "medium",
            },
        ],
        "activities": [
            {
                "mode": "transit",
                "distance_meters": 2400,
                "duration_minutes": 12,
                "start_time": "2026-02-27T15:48:00+02:00",
                "end_time": "2026-02-27T16:00:00+02:00",
                "start_lat": 32.0800,
                "start_lng": 34.7800,
                "end_lat": 32.1079,
                "end_lng": 34.6818,
                "polyline": [[32.0800, 34.7800], [32.1079, 34.6818]],
                "confidence": "high",
            },
        ],
    }


@pytest.fixture
def habits_data():
    """Sample habits data as returned by /habits."""
    return [
        {
            "name": "gym",
            "completed_today": True,
            "streak": 15,
            "tokens_per_completion": 10,
        },
    ]


@pytest.fixture
def daily_data():
    """Sample daily data as returned by /daily."""
    return {
        "date": "2026-02-27",
        "tokens_earned": 10,
        "tokens_total": 250,
    }


class TestMergerService:
    def test_merge_calendar_with_timeline_match(
        self, calendar_events, timeline_data, habits_data, daily_data
    ):
        """Calendar gym event + timeline gym visit → single merged event."""
        merger = MergerService(timezone="Asia/Jerusalem")
        events = merger.merge(
            calendar_events=calendar_events,
            timeline_data=timeline_data,
            habits=habits_data,
            daily=daily_data,
        )

        # Find the gym event
        gym = next(e for e in events if "gym" in e.name.lower() or "holmes" in e.name.lower())
        assert gym.source == "merged"
        assert gym.location is not None
        assert gym.location["name"] == "Holmes Place Dizengoff"
        assert gym.location["lat"] == pytest.approx(32.1079, abs=0.001)

    def test_unmatched_calendar_event_preserved(
        self, calendar_events, timeline_data, habits_data, daily_data
    ):
        """Calendar event with no timeline match → kept as calendar-only."""
        merger = MergerService(timezone="Asia/Jerusalem")
        events = merger.merge(
            calendar_events=calendar_events,
            timeline_data=timeline_data,
            habits=habits_data,
            daily=daily_data,
        )

        standup = next(e for e in events if "standup" in e.name.lower())
        assert standup.source == "calendar"
        assert standup.location is None

    def test_unmatched_timeline_visit_becomes_unplanned_stop(
        self, calendar_events, timeline_data, habits_data, daily_data
    ):
        """Timeline visit with no calendar match → unplanned_stop."""
        merger = MergerService(timezone="Asia/Jerusalem")
        events = merger.merge(
            calendar_events=calendar_events,
            timeline_data=timeline_data,
            habits=habits_data,
            daily=daily_data,
        )

        market = next(e for e in events if "carmel" in e.name.lower())
        assert market.type == "unplanned_stop"
        assert market.source == "timeline"

    def test_transit_activity_becomes_route(
        self, calendar_events, timeline_data, habits_data, daily_data
    ):
        """Activity segments → transit events with route data."""
        merger = MergerService(timezone="Asia/Jerusalem")
        events = merger.merge(
            calendar_events=calendar_events,
            timeline_data=timeline_data,
            habits=habits_data,
            daily=daily_data,
        )

        transit = [e for e in events if e.type == "transit"]
        assert len(transit) >= 1
        assert transit[0].route_from is not None
        assert transit[0].route_from["mode"] == "transit"

    def test_habit_attached_to_matching_event(
        self, calendar_events, timeline_data, habits_data, daily_data
    ):
        """Gym habit → attached to gym calendar event."""
        merger = MergerService(timezone="Asia/Jerusalem")
        events = merger.merge(
            calendar_events=calendar_events,
            timeline_data=timeline_data,
            habits=habits_data,
            daily=daily_data,
        )

        gym = next(e for e in events if "gym" in e.name.lower() or "holmes" in e.name.lower())
        assert gym.habit is not None
        assert gym.habit["completed"] is True
        assert gym.habit["streak"] == 15

    def test_events_sorted_chronologically(
        self, calendar_events, timeline_data, habits_data, daily_data
    ):
        """All events sorted by start_time."""
        merger = MergerService(timezone="Asia/Jerusalem")
        events = merger.merge(
            calendar_events=calendar_events,
            timeline_data=timeline_data,
            habits=habits_data,
            daily=daily_data,
        )

        times = [e.start_time for e in events]
        assert times == sorted(times)

    def test_merged_event_serializes_to_dict(
        self, calendar_events, timeline_data, habits_data, daily_data
    ):
        """MergedEvent can be serialized to dict for JSON response."""
        merger = MergerService(timezone="Asia/Jerusalem")
        events = merger.merge(
            calendar_events=calendar_events,
            timeline_data=timeline_data,
            habits=habits_data,
            daily=daily_data,
        )

        for event in events:
            d = event.model_dump()
            assert "id" in d
            assert "name" in d
            assert "type" in d
            assert "start_time" in d
```

**Step 2: Run tests to verify they fail**

```bash
cd apps/vault-server && source venv/bin/activate && pytest tests/test_merger_service.py -v
# Expected: FAIL — ModuleNotFoundError
```

**Step 3: Implement MergerService**

`apps/vault-server/src/services/merger_service.py`:

```python
"""Merge calendar events, timeline data, and PKM vault data into MergedEvent[]."""

import uuid
from datetime import datetime
from math import radians, sin, cos, sqrt, atan2
from typing import Any

import pytz
from pydantic import BaseModel, Field


class MergedEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])

    # What
    name: str
    type: str  # 'habit' | 'task' | 'calendar' | 'unplanned_stop' | 'transit' | 'home'
    activity_category: str | None = None

    # When
    start_time: str  # ISO format
    end_time: str
    duration_minutes: int = 0

    # Where
    location: dict[str, Any] | None = None  # {name, lat, lng, place_id}

    # How you got there
    route_from: dict[str, Any] | None = None  # {mode, distance_meters, duration_minutes, polyline, confidence}

    # PKM integration
    habit: dict[str, Any] | None = None  # {name, completed, streak, tokens_earned}
    tokens_earned: int = 0

    # Generated assets (populated later)
    assets: dict[str, str] | None = None

    # Data quality
    source: str  # 'calendar' | 'timeline' | 'merged'
    confidence: str = "medium"  # 'high' | 'medium' | 'low'


# Fuzzy matching config
TIME_MATCH_MINUTES = 30
DISTANCE_MATCH_METERS = 500

# Keywords for activity category detection
CATEGORY_KEYWORDS = {
    "gym": ["gym", "fitness", "workout", "holmes place", "crossfit"],
    "walk": ["walk", "hike", "park", "dog walk"],
    "cafe": ["cafe", "café", "coffee", "xoho", "starbucks"],
    "shopping": ["market", "mall", "shop", "store", "carmel"],
    "work": ["work", "office", "meeting", "standup", "deep work"],
    "social": ["dinner", "lunch", "drinks", "party", "friend"],
}


class MergerService:
    def __init__(self, timezone: str = "Asia/Jerusalem"):
        self.tz = pytz.timezone(timezone)

    def merge(
        self,
        calendar_events: list[dict],
        timeline_data: dict,
        habits: list[dict] | None = None,
        daily: dict | None = None,
    ) -> list[MergedEvent]:
        visits = timeline_data.get("visits", [])
        activities = timeline_data.get("activities", [])
        habits = habits or []

        merged: list[MergedEvent] = []
        matched_visit_indices: set[int] = set()

        # Step 1: Match calendar events to timeline visits
        for cal in calendar_events:
            best_visit_idx = self._find_matching_visit(cal, visits, matched_visit_indices)

            if best_visit_idx is not None:
                # Merged event
                visit = visits[best_visit_idx]
                matched_visit_indices.add(best_visit_idx)
                event = self._create_merged_event(cal, visit)
            else:
                # Calendar-only event
                event = self._create_calendar_event(cal)

            # Attach habit data
            habit_match = self._find_matching_habit(event.name, habits)
            if habit_match:
                event.habit = {
                    "name": habit_match["name"],
                    "completed": habit_match.get("completed_today", False),
                    "streak": habit_match.get("streak", 0),
                    "tokens_earned": habit_match.get("tokens_per_completion", 0),
                }
                if event.habit["completed"]:
                    event.tokens_earned = event.habit["tokens_earned"]

            merged.append(event)

        # Step 2: Unmatched timeline visits → unplanned stops
        for i, visit in enumerate(visits):
            if i not in matched_visit_indices:
                merged.append(self._create_unplanned_stop(visit))

        # Step 3: Activity segments → transit events
        for activity in activities:
            merged.append(self._create_transit_event(activity))

        # Step 4: Sort chronologically
        merged.sort(key=lambda e: e.start_time)

        # Step 5: Attach route_from to events that follow transit
        self._attach_routes(merged)

        return merged

    def _find_matching_visit(
        self, cal: dict, visits: list[dict], excluded: set[int]
    ) -> int | None:
        """Find the best matching timeline visit for a calendar event."""
        cal_start = self._parse_time(cal.get("start", ""))
        if not cal_start:
            return None

        best_idx = None
        best_time_diff = float("inf")

        for i, visit in enumerate(visits):
            if i in excluded:
                continue
            visit_start = self._parse_time(visit.get("start_time", ""))
            if not visit_start:
                continue

            time_diff = abs((cal_start - visit_start).total_seconds() / 60)
            if time_diff > TIME_MATCH_MINUTES:
                continue

            if time_diff < best_time_diff:
                best_time_diff = time_diff
                best_idx = i

        return best_idx

    def _create_merged_event(self, cal: dict, visit: dict) -> MergedEvent:
        name = cal.get("summary", "Unknown")
        return MergedEvent(
            name=name,
            type=self._infer_type(cal),
            activity_category=self._infer_category(name),
            start_time=cal.get("start", visit["start_time"]),
            end_time=cal.get("end", visit["end_time"]),
            duration_minutes=visit.get("duration_minutes", 0),
            location={
                "name": visit["name"],
                "lat": visit["lat"],
                "lng": visit["lng"],
                "place_id": visit.get("place_id"),
            },
            source="merged",
            confidence=visit.get("confidence", "medium"),
        )

    def _create_calendar_event(self, cal: dict) -> MergedEvent:
        name = cal.get("summary", "Unknown")
        return MergedEvent(
            name=name,
            type=self._infer_type(cal),
            activity_category=self._infer_category(name),
            start_time=cal.get("start", ""),
            end_time=cal.get("end", ""),
            duration_minutes=self._calc_duration(cal.get("start", ""), cal.get("end", "")),
            source="calendar",
            confidence="medium",
        )

    def _create_unplanned_stop(self, visit: dict) -> MergedEvent:
        return MergedEvent(
            name=visit["name"],
            type="unplanned_stop",
            activity_category=self._infer_category(visit["name"]),
            start_time=visit["start_time"],
            end_time=visit["end_time"],
            duration_minutes=visit.get("duration_minutes", 0),
            location={
                "name": visit["name"],
                "lat": visit["lat"],
                "lng": visit["lng"],
                "place_id": visit.get("place_id"),
            },
            source="timeline",
            confidence=visit.get("confidence", "low"),
        )

    def _create_transit_event(self, activity: dict) -> MergedEvent:
        return MergedEvent(
            name=f"Transit ({activity['mode']})",
            type="transit",
            start_time=activity["start_time"],
            end_time=activity["end_time"],
            duration_minutes=activity.get("duration_minutes", 0),
            route_from={
                "mode": activity["mode"],
                "distance_meters": activity.get("distance_meters", 0),
                "duration_minutes": activity.get("duration_minutes", 0),
                "polyline": activity.get("polyline", []),
                "confidence": activity.get("confidence", "low"),
            },
            source="timeline",
            confidence=activity.get("confidence", "low"),
        )

    def _attach_routes(self, events: list[MergedEvent]) -> None:
        """Move route_from from transit events to the next non-transit event."""
        for i, event in enumerate(events):
            if event.type == "transit" and event.route_from:
                # Find next non-transit event
                for j in range(i + 1, len(events)):
                    if events[j].type != "transit":
                        events[j].route_from = event.route_from
                        break

    def _find_matching_habit(self, event_name: str, habits: list[dict]) -> dict | None:
        """Find a habit that matches an event name by keyword overlap."""
        name_lower = event_name.lower()
        for habit in habits:
            habit_name = habit.get("name", "").lower()
            if habit_name in name_lower or name_lower in habit_name:
                return habit
            # Check if any word overlaps
            habit_words = set(habit_name.split())
            name_words = set(name_lower.replace("—", " ").replace("-", " ").split())
            if habit_words & name_words:
                return habit
        return None

    @staticmethod
    def _infer_type(cal: dict) -> str:
        calendar_name = cal.get("calendar", "").lower()
        if "mazkir" in calendar_name:
            return "habit"
        return "calendar"

    @staticmethod
    def _infer_category(name: str) -> str | None:
        name_lower = name.lower()
        for category, keywords in CATEGORY_KEYWORDS.items():
            if any(kw in name_lower for kw in keywords):
                return category
        return None

    def _parse_time(self, ts: str) -> datetime | None:
        if not ts:
            return None
        try:
            return datetime.fromisoformat(ts)
        except ValueError:
            return None

    def _calc_duration(self, start: str, end: str) -> int:
        s = self._parse_time(start)
        e = self._parse_time(end)
        if s and e:
            return int((e - s).total_seconds() / 60)
        return 0

    @staticmethod
    def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """Distance in meters between two lat/lng points."""
        R = 6371000
        dlat = radians(lat2 - lat1)
        dlng = radians(lng2 - lng1)
        a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
        return R * 2 * atan2(sqrt(a), sqrt(1 - a))
```

**Step 4: Run tests**

```bash
cd apps/vault-server && source venv/bin/activate && pytest tests/test_merger_service.py -v
# Expected: All tests PASS
```

**Step 5: Commit**

```bash
git add apps/vault-server/src/services/merger_service.py apps/vault-server/tests/test_merger_service.py
git commit -m "feat: add merger service combining calendar, timeline, and PKM data"
```

---

## Task 6: Server Routes — Timeline + Merged Events

**Files:**
- Create: `apps/vault-server/src/api/routes/timeline.py`
- Create: `apps/vault-server/src/api/routes/merged_events.py`
- Modify: `apps/vault-server/src/main.py` (register routers, init timeline service)
- Modify: `apps/vault-server/src/config.py` (if not already done in Task 3)

**Step 1: Write timeline route**

`apps/vault-server/src/api/routes/timeline.py`:

```python
from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from src.auth import verify_api_key
from src.main import get_timeline

router = APIRouter(
    prefix="/timeline", tags=["timeline"], dependencies=[Depends(verify_api_key)]
)


@router.get("/{target_date}")
async def get_timeline_data(target_date: date):
    timeline = get_timeline()
    if not timeline:
        raise HTTPException(status_code=503, detail="Timeline service not available")
    return timeline.get_day(target_date)
```

**Step 2: Write merged events route**

`apps/vault-server/src/api/routes/merged_events.py`:

```python
from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from src.auth import verify_api_key
from src.main import get_vault, get_calendar, get_timeline
from src.services.merger_service import MergerService

router = APIRouter(
    prefix="/merged-events",
    tags=["merged-events"],
    dependencies=[Depends(verify_api_key)],
)


@router.get("/{target_date}")
async def get_merged_events(target_date: date):
    vault = get_vault()
    timeline = get_timeline()
    calendar = get_calendar()

    # Get calendar events
    calendar_events = []
    if calendar and calendar.is_initialized:
        try:
            calendar_events = await calendar.get_todays_events(all_calendars=True)
        except Exception:
            pass  # Calendar is best-effort

    # Get timeline data
    timeline_data = {"visits": [], "activities": []}
    if timeline:
        timeline_data = timeline.get_day(target_date)

    # Get habits
    habits = []
    try:
        raw_habits = vault.list_active_habits()
        today_str = target_date.isoformat()
        for h in raw_habits:
            meta = h["metadata"]
            habits.append({
                "name": meta.get("name", ""),
                "completed_today": meta.get("last_completed") == today_str,
                "streak": meta.get("streak", 0),
                "tokens_per_completion": meta.get("tokens_per_completion", 5),
            })
    except Exception:
        pass

    # Get daily summary
    daily = {}
    try:
        daily = vault.read_daily_note(target_date)
        daily = daily.get("metadata", {})
    except Exception:
        pass

    # Merge
    merger = MergerService(timezone="Asia/Jerusalem")
    events = merger.merge(
        calendar_events=calendar_events,
        timeline_data=timeline_data,
        habits=habits,
        daily=daily,
    )

    return {
        "date": target_date.isoformat(),
        "events": [e.model_dump() for e in events],
        "summary": {
            "total_events": len(events),
            "total_tokens": sum(e.tokens_earned for e in events),
        },
    }
```

**Step 3: Register new routers + timeline service in main.py**

In `apps/vault-server/src/main.py`:

1. Add a global `timeline` variable alongside existing globals
2. In the `lifespan()` function, initialize `TimelineService`
3. Add a `get_timeline()` getter function
4. Import and register the two new routers

Changes to add:

```python
# Global variable (alongside vault, claude, calendar):
timeline: "TimelineService | None" = None

# In lifespan(), after calendar init:
from src.services.timeline_service import TimelineService
nonlocal timeline
if settings.timeline_data_path.exists():
    timeline = TimelineService(
        data_path=settings.timeline_data_path,
        timezone=settings.vault_timezone,
    )

# Getter function:
def get_timeline():
    return timeline

# Router registration:
from src.api.routes.timeline import router as timeline_router
from src.api.routes.merged_events import router as merged_events_router
app.include_router(timeline_router)
app.include_router(merged_events_router)
```

**Step 4: Verify server starts**

```bash
cd apps/vault-server && source venv/bin/activate && python -m uvicorn src.main:app --reload --port 8000
curl http://localhost:8000/health
# Expected: {"status":"ok","vault":true}
```

**Step 5: Test timeline endpoint (expect empty if no data yet)**

```bash
curl http://localhost:8000/timeline/2026-02-27
# Expected: {"visits":[],"activities":[]} (no timeline data on disk yet)
```

**Step 6: Commit**

```bash
git add apps/vault-server/src/api/routes/timeline.py apps/vault-server/src/api/routes/merged_events.py apps/vault-server/src/main.py
git commit -m "feat: add /timeline and /merged-events endpoints"
```

---

## Task 7: Webapp API Client + TypeScript Types

**Files:**
- Create: `apps/telegram-web-app/src/models/event.ts`
- Create: `apps/telegram-web-app/src/services/api.ts`
- Create: `apps/telegram-web-app/src/services/__tests__/api.test.ts`

**Step 1: Create MergedEvent TypeScript types**

`apps/telegram-web-app/src/models/event.ts`:

```typescript
export interface MergedEvent {
  id: string

  // What
  name: string
  type: 'habit' | 'task' | 'calendar' | 'unplanned_stop' | 'transit' | 'home'
  activity_category?: string

  // When
  start_time: string
  end_time: string
  duration_minutes: number

  // Where
  location?: {
    name: string
    lat: number
    lng: number
    place_id?: string
  }

  // How you got there
  route_from?: {
    mode: 'walking' | 'driving' | 'transit' | 'cycling' | 'unknown'
    distance_meters: number
    duration_minutes: number
    polyline: [number, number][]
    confidence: 'high' | 'medium' | 'low'
  }

  // PKM integration
  habit?: {
    name: string
    completed: boolean
    streak: number
    tokens_earned: number
  }
  tokens_earned: number

  // Generated assets
  assets?: {
    micro_icon?: string
    keyframe_scene?: string
    route_sketch?: string
    context_image?: string
  }

  // Data quality
  source: 'calendar' | 'timeline' | 'merged'
  confidence: 'high' | 'medium' | 'low'
}

export interface MergedEventsResponse {
  date: string
  events: MergedEvent[]
  summary: {
    total_events: number
    total_tokens: number
  }
}

export interface DailyResponse {
  date: string
  day_of_week: string
  tokens_earned: number
  tokens_total: number
  habits: Array<{
    name: string
    completed: boolean
    streak: number
  }>
  calendar_events: Array<{
    id: string
    summary: string
    start: string
    end: string
    completed: boolean
    calendar: string
  }>
}

export interface TokensResponse {
  total: number
  today: number
  all_time: number
}
```

**Step 2: Create API client**

`apps/telegram-web-app/src/services/api.ts`:

```typescript
import type { MergedEventsResponse, DailyResponse, TokensResponse } from '../models/event'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'
const API_KEY = import.meta.env.VITE_API_KEY || ''

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  if (API_KEY) {
    headers['X-API-Key'] = API_KEY
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...headers, ...options?.headers },
  })

  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`)
  }

  return res.json()
}

export const api = {
  getMergedEvents(date: string): Promise<MergedEventsResponse> {
    return request(`/merged-events/${date}`)
  },

  getDaily(): Promise<DailyResponse> {
    return request('/daily')
  },

  getTokens(): Promise<TokensResponse> {
    return request('/tokens')
  },

  getHealth(): Promise<{ status: string }> {
    return request('/health')
  },
}
```

**Step 3: Write API client test**

`apps/telegram-web-app/src/services/__tests__/api.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { api } from '../api'

const mockFetch = vi.fn()
global.fetch = mockFetch

beforeEach(() => {
  mockFetch.mockReset()
})

describe('api client', () => {
  it('fetches merged events for a date', async () => {
    const mockResponse = {
      date: '2026-02-27',
      events: [],
      summary: { total_events: 0, total_tokens: 0 },
    }
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(mockResponse),
    })

    const result = await api.getMergedEvents('2026-02-27')
    expect(result).toEqual(mockResponse)
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('/merged-events/2026-02-27'),
      expect.any(Object),
    )
  })

  it('throws on non-ok response', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
    })

    await expect(api.getHealth()).rejects.toThrow('API error: 500')
  })
})
```

**Step 4: Add vitest config**

Create `apps/telegram-web-app/vitest.config.ts` (or add to vite.config.ts):

```typescript
/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
  },
})
```

**Step 5: Run tests**

```bash
cd apps/telegram-web-app && npm test
# Expected: PASS
```

**Step 6: Commit**

```bash
git add apps/telegram-web-app/src/models/ apps/telegram-web-app/src/services/ apps/telegram-web-app/vitest.config.ts
git commit -m "feat: add API client and MergedEvent types for webapp"
```

---

## Task 8: Dayplanner UI

**Files:**
- Create: `apps/telegram-web-app/src/features/dayplanner/store.ts`
- Create: `apps/telegram-web-app/src/features/dayplanner/components/EventCard.tsx`
- Create: `apps/telegram-web-app/src/features/dayplanner/components/DayHeader.tsx`
- Create: `apps/telegram-web-app/src/features/dayplanner/components/Timeline.tsx`
- Modify: `apps/telegram-web-app/src/features/dayplanner/DayplannerPage.tsx`

**Step 1: Create Zustand store**

`apps/telegram-web-app/src/features/dayplanner/store.ts`:

```typescript
import { create } from 'zustand'
import type { MergedEvent, MergedEventsResponse } from '../../models/event'
import { api } from '../../services/api'

interface DayplannerState {
  date: string
  events: MergedEvent[]
  totalTokens: number
  loading: boolean
  error: string | null
  setDate: (date: string) => void
  fetchDay: (date: string) => Promise<void>
}

function todayISO(): string {
  return new Date().toISOString().split('T')[0]
}

export const useDayplannerStore = create<DayplannerState>((set) => ({
  date: todayISO(),
  events: [],
  totalTokens: 0,
  loading: false,
  error: null,

  setDate: (date) => set({ date }),

  fetchDay: async (date) => {
    set({ loading: true, error: null })
    try {
      const data: MergedEventsResponse = await api.getMergedEvents(date)
      set({
        events: data.events,
        totalTokens: data.summary.total_tokens,
        loading: false,
      })
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'Failed to load',
        loading: false,
      })
    }
  },
}))
```

**Step 2: Create DayHeader component**

`apps/telegram-web-app/src/features/dayplanner/components/DayHeader.tsx`:

```tsx
interface DayHeaderProps {
  date: string
  totalTokens: number
}

export default function DayHeader({ date, totalTokens }: DayHeaderProps) {
  const d = new Date(date + 'T00:00:00')
  const formatted = d.toLocaleDateString('en-US', {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })

  return (
    <div className="px-4 py-3 border-b border-gray-200 bg-white">
      <h1 className="text-lg font-semibold text-gray-900">{formatted}</h1>
      {totalTokens > 0 && (
        <p className="text-sm text-gray-500 mt-0.5">
          +{totalTokens} tokens
        </p>
      )}
    </div>
  )
}
```

**Step 3: Create EventCard component**

`apps/telegram-web-app/src/features/dayplanner/components/EventCard.tsx`:

```tsx
import type { MergedEvent } from '../../../models/event'

const TYPE_STYLES: Record<string, string> = {
  habit: 'border-l-green-500',
  calendar: 'border-l-blue-500',
  unplanned_stop: 'border-l-yellow-500',
  transit: 'border-l-gray-300',
  home: 'border-l-purple-300',
  task: 'border-l-orange-500',
}

const CATEGORY_ICONS: Record<string, string> = {
  gym: '\uD83D\uDCAA',
  walk: '\uD83D\uDEB6',
  cafe: '\u2615',
  shopping: '\uD83D\uDED2',
  work: '\uD83D\uDCBB',
  social: '\uD83C\uDF89',
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    })
  } catch {
    return ''
  }
}

function formatDuration(minutes: number): string {
  if (minutes < 60) return `${minutes}min`
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return m > 0 ? `${h}h ${m}min` : `${h}h`
}

interface EventCardProps {
  event: MergedEvent
}

export default function EventCard({ event }: EventCardProps) {
  if (event.type === 'transit') {
    return <TransitCard event={event} />
  }

  const icon = event.activity_category
    ? CATEGORY_ICONS[event.activity_category] || ''
    : ''
  const borderColor = TYPE_STYLES[event.type] || 'border-l-gray-400'

  return (
    <div className={`bg-white rounded-lg border-l-4 ${borderColor} p-3 shadow-sm`}>
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-gray-400">
              {formatTime(event.start_time)}
            </span>
            {icon && <span>{icon}</span>}
            <span className="font-medium text-gray-900">{event.name}</span>
          </div>

          {event.location && (
            <p className="text-sm text-gray-500 mt-1">
              {event.location.name}
            </p>
          )}

          {event.duration_minutes > 0 && (
            <p className="text-xs text-gray-400 mt-0.5">
              {formatDuration(event.duration_minutes)}
            </p>
          )}
        </div>

        {event.habit && (
          <div className="text-right flex-shrink-0 ml-2">
            {event.habit.completed && (
              <span className="text-green-600 text-sm font-medium">
                \u2705 +{event.tokens_earned}
              </span>
            )}
            {event.habit.streak > 0 && (
              <p className="text-xs text-gray-400">
                streak: {event.habit.streak}
              </p>
            )}
          </div>
        )}
      </div>

      {event.route_from && event.type !== 'transit' && (
        <div className="mt-2 text-xs text-gray-400 flex items-center gap-1">
          <span>{event.route_from.mode}</span>
          <span>\u00B7</span>
          <span>{formatDuration(event.route_from.duration_minutes)}</span>
          {event.route_from.distance_meters > 0 && (
            <>
              <span>\u00B7</span>
              <span>{(event.route_from.distance_meters / 1000).toFixed(1)}km</span>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function TransitCard({ event }: EventCardProps) {
  const route = event.route_from
  if (!route) return null

  return (
    <div className="flex items-center gap-2 py-1 px-3 text-xs text-gray-400">
      <div className="w-px h-4 bg-gray-200" />
      <span>{route.mode}</span>
      <span>\u00B7</span>
      <span>{formatDuration(route.duration_minutes)}</span>
      {route.distance_meters > 0 && (
        <>
          <span>\u00B7</span>
          <span>{(route.distance_meters / 1000).toFixed(1)}km</span>
        </>
      )}
    </div>
  )
}
```

**Step 4: Create Timeline component**

`apps/telegram-web-app/src/features/dayplanner/components/Timeline.tsx`:

```tsx
import type { MergedEvent } from '../../../models/event'
import EventCard from './EventCard'

interface TimelineProps {
  events: MergedEvent[]
}

export default function Timeline({ events }: TimelineProps) {
  if (events.length === 0) {
    return (
      <div className="p-8 text-center text-gray-400">
        <p>No events for this day</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2 p-4">
      {events.map((event) => (
        <EventCard key={event.id} event={event} />
      ))}
    </div>
  )
}
```

**Step 5: Wire up DayplannerPage**

`apps/telegram-web-app/src/features/dayplanner/DayplannerPage.tsx`:

```tsx
import { useEffect } from 'react'
import { useDayplannerStore } from './store'
import DayHeader from './components/DayHeader'
import Timeline from './components/Timeline'

export default function DayplannerPage() {
  const { date, events, totalTokens, loading, error, fetchDay } =
    useDayplannerStore()

  useEffect(() => {
    fetchDay(date)
  }, [date, fetchDay])

  return (
    <div className="min-h-screen bg-gray-50">
      <DayHeader date={date} totalTokens={totalTokens} />

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

**Step 6: Verify in browser**

```bash
cd apps/telegram-web-app && npm run dev
# Visit http://localhost:5173/dayplanner
# If vault-server is running: shows empty or real data
# If not: shows error message (API connection refused)
```

**Step 7: Commit**

```bash
git add apps/telegram-web-app/src/features/dayplanner/
git commit -m "feat: add dayplanner UI with timeline, event cards, and Zustand store"
```

---

## Task 9: Imagery Service

**Files:**
- Create: `apps/vault-server/src/services/imagery_service.py`
- Create: `apps/vault-server/tests/test_imagery_service.py`

This service searches Wikimedia Commons and Mapillary for contextual images near a given lat/lng.

**Step 1: Write failing tests**

`apps/vault-server/tests/test_imagery_service.py`:

```python
from unittest.mock import AsyncMock, patch

import pytest

from src.services.imagery_service import ImageryService


@pytest.fixture
def imagery_service():
    return ImageryService()


class TestImageryService:
    @pytest.mark.asyncio
    async def test_search_wikimedia_returns_images(self, imagery_service):
        """Wikimedia search returns image results with URL and metadata."""
        mock_response = {
            "query": {
                "geosearch": [
                    {
                        "pageid": 123,
                        "title": "File:Tel Aviv Beach.jpg",
                        "lat": 32.08,
                        "lon": 34.77,
                        "dist": 150.0,
                    }
                ]
            }
        }

        with patch.object(imagery_service, "_fetch_json", new_callable=AsyncMock) as mock:
            mock.return_value = mock_response
            results = await imagery_service.search_wikimedia(32.08, 34.77, radius=500)

        assert len(results) == 1
        assert results[0]["title"] == "File:Tel Aviv Beach.jpg"
        assert results[0]["source"] == "wikimedia"

    @pytest.mark.asyncio
    async def test_search_returns_empty_on_error(self, imagery_service):
        """Gracefully returns empty list on API error."""
        with patch.object(imagery_service, "_fetch_json", new_callable=AsyncMock) as mock:
            mock.side_effect = Exception("Network error")
            results = await imagery_service.search_wikimedia(32.08, 34.77)

        assert results == []

    @pytest.mark.asyncio
    async def test_search_all_combines_sources(self, imagery_service):
        """search_all combines Wikimedia results."""
        with patch.object(imagery_service, "search_wikimedia", new_callable=AsyncMock) as mock_wiki:
            mock_wiki.return_value = [{"title": "test.jpg", "source": "wikimedia"}]
            results = await imagery_service.search_all(32.08, 34.77)

        assert len(results) >= 1
```

**Step 2: Run tests to verify they fail**

```bash
cd apps/vault-server && source venv/bin/activate && pytest tests/test_imagery_service.py -v
# Expected: FAIL — ModuleNotFoundError
```

**Step 3: Implement ImageryService**

`apps/vault-server/src/services/imagery_service.py`:

```python
"""Search open-source imagery APIs for contextual photos by location."""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"


class ImageryService:
    def __init__(self):
        self._client = httpx.AsyncClient(timeout=10.0)

    async def search_all(
        self, lat: float, lng: float, radius: int = 500, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Search all imagery sources and combine results."""
        results = await self.search_wikimedia(lat, lng, radius=radius, limit=limit)
        return results

    async def search_wikimedia(
        self, lat: float, lng: float, radius: int = 500, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Search Wikimedia Commons for geotagged images near a point."""
        try:
            data = await self._fetch_json(WIKIMEDIA_API, params={
                "action": "query",
                "list": "geosearch",
                "gscoord": f"{lat}|{lng}",
                "gsradius": str(min(radius, 10000)),
                "gslimit": str(limit),
                "gsnamespace": "6",  # File namespace
                "format": "json",
            })

            results = []
            for item in data.get("query", {}).get("geosearch", []):
                title = item.get("title", "")
                results.append({
                    "title": title,
                    "page_id": item.get("pageid"),
                    "lat": item.get("lat"),
                    "lng": item.get("lon"),
                    "distance_meters": item.get("dist"),
                    "thumbnail_url": self._wikimedia_thumb_url(title),
                    "source": "wikimedia",
                })

            return results

        except Exception as e:
            logger.warning(f"Wikimedia search failed: {e}")
            return []

    async def _fetch_json(self, url: str, params: dict | None = None) -> dict:
        """Fetch JSON from a URL."""
        response = await self._client.get(url, params=params)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _wikimedia_thumb_url(title: str, width: int = 300) -> str:
        """Generate a Wikimedia Commons thumbnail URL from a file title."""
        filename = title.replace("File:", "").replace(" ", "_")
        return f"https://commons.wikimedia.org/wiki/Special:FilePath/{filename}?width={width}"

    async def close(self):
        await self._client.aclose()
```

**Step 4: Add httpx to vault-server dependencies**

httpx is already in dev dependencies. Check if it's in main dependencies too. If not, add to `pyproject.toml` dependencies:

```
"httpx>=0.27.0"
```

**Step 5: Run tests**

```bash
cd apps/vault-server && source venv/bin/activate && pip install httpx && pytest tests/test_imagery_service.py -v
# Expected: All tests PASS
```

**Step 6: Commit**

```bash
git add apps/vault-server/src/services/imagery_service.py apps/vault-server/tests/test_imagery_service.py
git commit -m "feat: add imagery service for Wikimedia Commons geo search"
```

---

## Task 10: Generation Service (Replicate)

**Files:**
- Create: `apps/vault-server/src/services/generation_service.py`
- Create: `apps/vault-server/tests/test_generation_service.py`
- Modify: `apps/vault-server/pyproject.toml` (add replicate dependency)

**Step 1: Add replicate to dependencies**

In `apps/vault-server/pyproject.toml`, add to dependencies:

```
"replicate>=0.25.0"
```

Install:

```bash
cd apps/vault-server && source venv/bin/activate && pip install replicate
```

**Step 2: Write failing tests**

`apps/vault-server/tests/test_generation_service.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.generation_service import GenerationService, GenerationRequest, StyleConfig


@pytest.fixture
def gen_service():
    return GenerationService(api_token="test-token")


class TestGenerationService:
    def test_build_prompt_for_micro_icon(self, gen_service):
        request = GenerationRequest(
            type="micro_icon",
            event_name="Gym workout",
            activity_category="gym",
            style=StyleConfig(line_style="clean_vector"),
        )
        prompt = gen_service.build_prompt(request)
        assert "gym" in prompt.lower()
        assert "icon" in prompt.lower()

    def test_build_prompt_for_route_sketch(self, gen_service):
        request = GenerationRequest(
            type="route_sketch",
            event_name="Walk to park",
            activity_category="walk",
            style=StyleConfig(line_style="loose_ink"),
        )
        prompt = gen_service.build_prompt(request)
        assert "route" in prompt.lower() or "path" in prompt.lower()

    def test_build_prompt_for_keyframe_scene(self, gen_service):
        request = GenerationRequest(
            type="keyframe_scene",
            event_name="Café Xoho",
            location_name="Dizengoff Street, Tel Aviv",
            style=StyleConfig(preset="tel-aviv"),
        )
        prompt = gen_service.build_prompt(request)
        assert "tel aviv" in prompt.lower() or "café" in prompt.lower()

    @pytest.mark.asyncio
    async def test_generate_calls_replicate(self, gen_service):
        request = GenerationRequest(
            type="micro_icon",
            event_name="Gym",
            style=StyleConfig(),
        )

        mock_output = ["https://replicate.delivery/output.png"]
        with patch("replicate.async_run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = mock_output
            result = await gen_service.generate(request)

        assert result["image_url"] == "https://replicate.delivery/output.png"
        assert result["approach"] == "ai_raster"

    @pytest.mark.asyncio
    async def test_generate_returns_error_on_failure(self, gen_service):
        request = GenerationRequest(
            type="micro_icon",
            event_name="Gym",
            style=StyleConfig(),
        )

        with patch("replicate.async_run", new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = Exception("API error")
            result = await gen_service.generate(request)

        assert "error" in result
```

**Step 3: Run tests to verify they fail**

```bash
cd apps/vault-server && source venv/bin/activate && pytest tests/test_generation_service.py -v
# Expected: FAIL — ModuleNotFoundError
```

**Step 4: Implement GenerationService**

`apps/vault-server/src/services/generation_service.py`:

```python
"""Image generation service using Replicate API."""

import logging
import time
from typing import Any

import replicate
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Default Replicate models per generation type
DEFAULT_MODELS = {
    "micro_icon": "stability-ai/sdxl:39ed52f2a78e934b3ba6e2a89f5b1c712de7dfea535525255b1aa35c5565e08b",
    "keyframe_scene": "stability-ai/sdxl:39ed52f2a78e934b3ba6e2a89f5b1c712de7dfea535525255b1aa35c5565e08b",
    "route_sketch": "stability-ai/sdxl:39ed52f2a78e934b3ba6e2a89f5b1c712de7dfea535525255b1aa35c5565e08b",
    "full_day_map": "stability-ai/sdxl:39ed52f2a78e934b3ba6e2a89f5b1c712de7dfea535525255b1aa35c5565e08b",
}


class StyleConfig(BaseModel):
    preset: str | None = None
    palette: list[str] | None = None
    line_style: str = "clean_vector"
    texture: str = "clean"
    art_reference: str | None = None


class GenerationRequest(BaseModel):
    type: str  # 'micro_icon' | 'keyframe_scene' | 'route_sketch' | 'full_day_map'
    event_name: str = ""
    activity_category: str | None = None
    location_name: str | None = None
    style: StyleConfig = StyleConfig()
    approach: str = "ai_raster"
    reference_images: list[str] | None = None
    params: dict[str, Any] | None = None


class GenerationService:
    def __init__(self, api_token: str):
        self.api_token = api_token
        # Set the token for the replicate library
        import os
        os.environ["REPLICATE_API_TOKEN"] = api_token

    async def generate(self, request: GenerationRequest) -> dict[str, Any]:
        """Generate an image using Replicate."""
        start = time.time()
        prompt = self.build_prompt(request)
        model = DEFAULT_MODELS.get(request.type, DEFAULT_MODELS["micro_icon"])

        try:
            output = await replicate.async_run(
                model,
                input={
                    "prompt": prompt,
                    "width": self._get_width(request.type),
                    "height": self._get_height(request.type),
                    "num_outputs": 1,
                },
            )

            image_url = output[0] if isinstance(output, list) else str(output)
            elapsed = int((time.time() - start) * 1000)

            return {
                "image_url": image_url,
                "format": "png",
                "approach": request.approach,
                "model": model.split(":")[0],
                "prompt": prompt,
                "generation_time_ms": elapsed,
                "params": request.params or {},
            }

        except Exception as e:
            logger.error(f"Generation failed: {e}")
            return {
                "error": str(e),
                "prompt": prompt,
                "approach": request.approach,
            }

    def build_prompt(self, request: GenerationRequest) -> str:
        """Build a generation prompt based on request type and style."""
        parts = []

        if request.type == "micro_icon":
            parts.append(f"Minimal vector icon of {request.event_name}")
            if request.activity_category:
                parts.append(f"representing {request.activity_category} activity")
            parts.append("simple, clean, flat design, single color")

        elif request.type == "route_sketch":
            parts.append(f"Hand-drawn route sketch map for {request.event_name}")
            if request.location_name:
                parts.append(f"in {request.location_name}")
            parts.append("illustrated path, minimalist")

        elif request.type == "keyframe_scene":
            parts.append(f"Illustrated scene card for {request.event_name}")
            if request.location_name:
                parts.append(f"at {request.location_name}")
            parts.append("atmospheric, detailed, warm lighting")

        elif request.type == "full_day_map":
            parts.append("Illustrated day journey map showing connected stops")
            parts.append("bird's eye view, illustrated style")

        # Apply style
        style = request.style
        if style.preset == "tel-aviv":
            parts.append("Tel Aviv Mediterranean style, warm tones, Bauhaus architecture")
        if style.line_style:
            line_desc = {
                "loose_ink": "loose ink drawing style",
                "clean_vector": "clean vector art",
                "crosshatch": "crosshatch pen illustration",
                "watercolor_edge": "watercolor edges, soft blending",
            }.get(style.line_style, "")
            if line_desc:
                parts.append(line_desc)
        if style.texture and style.texture != "clean":
            parts.append(f"{style.texture.replace('_', ' ')} texture")
        if style.art_reference:
            parts.append(f"inspired by {style.art_reference}")

        return ", ".join(parts)

    @staticmethod
    def _get_width(gen_type: str) -> int:
        if gen_type == "micro_icon":
            return 256
        if gen_type == "route_sketch":
            return 512
        return 768

    @staticmethod
    def _get_height(gen_type: str) -> int:
        if gen_type == "micro_icon":
            return 256
        if gen_type == "route_sketch":
            return 512
        return 768
```

**Step 5: Run tests**

```bash
cd apps/vault-server && source venv/bin/activate && pytest tests/test_generation_service.py -v
# Expected: All tests PASS
```

**Step 6: Commit**

```bash
git add apps/vault-server/src/services/generation_service.py apps/vault-server/tests/test_generation_service.py apps/vault-server/pyproject.toml
git commit -m "feat: add generation service using Replicate API"
```

---

## Task 11: Server Routes — Generation + Imagery

**Files:**
- Create: `apps/vault-server/src/api/routes/generate.py`
- Create: `apps/vault-server/src/api/routes/imagery.py`
- Modify: `apps/vault-server/src/main.py` (register routers, init services)

**Step 1: Write generation route**

`apps/vault-server/src/api/routes/generate.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Any

from src.auth import verify_api_key
from src.main import get_generation

router = APIRouter(
    prefix="/generate", tags=["generate"], dependencies=[Depends(verify_api_key)]
)


class GenerateRequest(BaseModel):
    type: str  # 'micro_icon' | 'keyframe_scene' | 'route_sketch' | 'full_day_map'
    event_name: str = ""
    activity_category: str | None = None
    location_name: str | None = None
    style: dict[str, Any] | None = None
    approach: str = "ai_raster"
    reference_images: list[str] | None = None
    params: dict[str, Any] | None = None


@router.post("")
async def generate_image(request: GenerateRequest):
    gen = get_generation()
    if not gen:
        raise HTTPException(status_code=503, detail="Generation service not available (no REPLICATE_API_TOKEN)")

    from src.services.generation_service import GenerationRequest, StyleConfig

    style = StyleConfig(**(request.style or {}))
    gen_request = GenerationRequest(
        type=request.type,
        event_name=request.event_name,
        activity_category=request.activity_category,
        location_name=request.location_name,
        style=style,
        approach=request.approach,
        reference_images=request.reference_images,
        params=request.params,
    )

    result = await gen.generate(gen_request)
    return result
```

**Step 2: Write imagery route**

`apps/vault-server/src/api/routes/imagery.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Query

from src.auth import verify_api_key
from src.main import get_imagery

router = APIRouter(
    prefix="/imagery", tags=["imagery"], dependencies=[Depends(verify_api_key)]
)


@router.get("/search")
async def search_imagery(
    lat: float = Query(..., description="Latitude"),
    lng: float = Query(..., description="Longitude"),
    radius: int = Query(500, description="Search radius in meters"),
    limit: int = Query(5, description="Max results"),
):
    imagery = get_imagery()
    if not imagery:
        raise HTTPException(status_code=503, detail="Imagery service not available")

    results = await imagery.search_all(lat, lng, radius=radius, limit=limit)
    return {"results": results}
```

**Step 3: Register in main.py**

Add to `apps/vault-server/src/main.py`:

```python
# Globals:
generation: "GenerationService | None" = None
imagery: "ImageryService | None" = None

# In lifespan():
from src.services.generation_service import GenerationService
from src.services.imagery_service import ImageryService
nonlocal generation, imagery
if settings.replicate_api_token:
    generation = GenerationService(api_token=settings.replicate_api_token)
imagery = ImageryService()

# Getters:
def get_generation():
    return generation

def get_imagery():
    return imagery

# Router registration:
from src.api.routes.generate import router as generate_router
from src.api.routes.imagery import router as imagery_router
app.include_router(generate_router)
app.include_router(imagery_router)
```

**Step 4: Verify server starts**

```bash
cd apps/vault-server && source venv/bin/activate && python -m uvicorn src.main:app --reload --port 8000
curl http://localhost:8000/health
```

**Step 5: Commit**

```bash
git add apps/vault-server/src/api/routes/generate.py apps/vault-server/src/api/routes/imagery.py apps/vault-server/src/main.py
git commit -m "feat: add /generate and /imagery/search endpoints"
```

---

## Task 12: Playground UI

**Files:**
- Create: `apps/telegram-web-app/src/features/playground/store.ts`
- Create: `apps/telegram-web-app/src/features/playground/components/EventList.tsx`
- Create: `apps/telegram-web-app/src/features/playground/components/GenerationPanel.tsx`
- Modify: `apps/telegram-web-app/src/features/playground/PlaygroundPage.tsx`
- Modify: `apps/telegram-web-app/src/services/api.ts` (add generation + imagery methods)

**Step 1: Add generation + imagery API methods**

Add to `apps/telegram-web-app/src/services/api.ts`:

```typescript
export interface GenerateRequest {
  type: 'micro_icon' | 'keyframe_scene' | 'route_sketch' | 'full_day_map'
  event_name?: string
  activity_category?: string
  location_name?: string
  style?: {
    preset?: string
    palette?: string[]
    line_style?: string
    texture?: string
    art_reference?: string
  }
  approach?: string
  params?: Record<string, unknown>
}

export interface GenerateResponse {
  image_url?: string
  error?: string
  format?: string
  approach?: string
  model?: string
  prompt?: string
  generation_time_ms?: number
}

export interface ImageryResult {
  title: string
  thumbnail_url: string
  source: string
  distance_meters?: number
}

// Add to api object:
  generate(request: GenerateRequest): Promise<GenerateResponse> {
    return request('/generate', { method: 'POST', body: JSON.stringify(request) })
  },

  searchImagery(lat: number, lng: number, radius?: number): Promise<{ results: ImageryResult[] }> {
    const params = new URLSearchParams({ lat: String(lat), lng: String(lng) })
    if (radius) params.set('radius', String(radius))
    return request(`/imagery/search?${params}`)
  },
```

**Step 2: Create Playground store**

`apps/telegram-web-app/src/features/playground/store.ts`:

```typescript
import { create } from 'zustand'
import type { MergedEvent } from '../../models/event'
import type { GenerateRequest, GenerateResponse } from '../../services/api'
import { api } from '../../services/api'

interface PlaygroundState {
  // Event selection
  events: MergedEvent[]
  selectedEvent: MergedEvent | null
  loadingEvents: boolean

  // Generation
  generating: boolean
  result: GenerateResponse | null
  history: GenerateResponse[]

  // Config
  genType: GenerateRequest['type']
  approach: string
  style: GenerateRequest['style']

  // Actions
  loadEvents: (date: string) => Promise<void>
  selectEvent: (event: MergedEvent | null) => void
  setGenType: (type: GenerateRequest['type']) => void
  setApproach: (approach: string) => void
  setStyle: (style: GenerateRequest['style']) => void
  generate: () => Promise<void>
}

export const usePlaygroundStore = create<PlaygroundState>((set, get) => ({
  events: [],
  selectedEvent: null,
  loadingEvents: false,

  generating: false,
  result: null,
  history: [],

  genType: 'micro_icon',
  approach: 'ai_raster',
  style: { line_style: 'clean_vector', texture: 'clean' },

  loadEvents: async (date) => {
    set({ loadingEvents: true })
    try {
      const data = await api.getMergedEvents(date)
      set({ events: data.events, loadingEvents: false })
    } catch {
      set({ loadingEvents: false })
    }
  },

  selectEvent: (event) => set({ selectedEvent: event }),
  setGenType: (type) => set({ genType: type }),
  setApproach: (approach) => set({ approach }),
  setStyle: (style) => set({ style }),

  generate: async () => {
    const { selectedEvent, genType, approach, style } = get()
    if (!selectedEvent) return

    set({ generating: true })
    try {
      const result = await api.generate({
        type: genType,
        event_name: selectedEvent.name,
        activity_category: selectedEvent.activity_category || undefined,
        location_name: selectedEvent.location?.name,
        style,
        approach,
      })
      set((state) => ({
        result,
        history: [result, ...state.history],
        generating: false,
      }))
    } catch {
      set({ generating: false })
    }
  },
}))
```

**Step 3: Create EventList component**

`apps/telegram-web-app/src/features/playground/components/EventList.tsx`:

```tsx
import type { MergedEvent } from '../../../models/event'

interface EventListProps {
  events: MergedEvent[]
  selectedEvent: MergedEvent | null
  onSelect: (event: MergedEvent) => void
}

export default function EventList({ events, selectedEvent, onSelect }: EventListProps) {
  return (
    <div className="border-r border-gray-200 overflow-y-auto">
      <div className="p-3 border-b border-gray-100">
        <h2 className="text-sm font-semibold text-gray-500 uppercase">Events</h2>
      </div>
      {events.filter(e => e.type !== 'transit').map((event) => (
        <button
          key={event.id}
          onClick={() => onSelect(event)}
          className={`w-full text-left px-3 py-2 border-b border-gray-50 hover:bg-gray-50 ${
            selectedEvent?.id === event.id ? 'bg-blue-50 border-l-2 border-l-blue-500' : ''
          }`}
        >
          <p className="text-sm font-medium text-gray-900 truncate">{event.name}</p>
          <p className="text-xs text-gray-400">{event.type}</p>
        </button>
      ))}
    </div>
  )
}
```

**Step 4: Create GenerationPanel component**

`apps/telegram-web-app/src/features/playground/components/GenerationPanel.tsx`:

```tsx
import type { MergedEvent } from '../../../models/event'
import type { GenerateRequest, GenerateResponse } from '../../../services/api'

interface GenerationPanelProps {
  selectedEvent: MergedEvent | null
  genType: GenerateRequest['type']
  approach: string
  style: GenerateRequest['style']
  generating: boolean
  result: GenerateResponse | null
  onGenTypeChange: (type: GenerateRequest['type']) => void
  onApproachChange: (approach: string) => void
  onStyleChange: (style: GenerateRequest['style']) => void
  onGenerate: () => void
}

const GEN_TYPES = [
  { value: 'micro_icon', label: 'Micro Icon' },
  { value: 'keyframe_scene', label: 'Keyframe Scene' },
  { value: 'route_sketch', label: 'Route Sketch' },
  { value: 'full_day_map', label: 'Full Day Map' },
] as const

const APPROACHES = [
  { value: 'ai_raster', label: 'AI Raster' },
  { value: 'svg_programmatic', label: 'SVG Programmatic' },
  { value: 'hybrid_svg_to_ai', label: 'Hybrid SVG→AI' },
  { value: 'style_transfer', label: 'Style Transfer' },
]

const LINE_STYLES = ['clean_vector', 'loose_ink', 'crosshatch', 'watercolor_edge']
const PRESETS = ['default', 'tel-aviv', 'jerusalem']

export default function GenerationPanel({
  selectedEvent,
  genType,
  approach,
  style,
  generating,
  result,
  onGenTypeChange,
  onApproachChange,
  onStyleChange,
  onGenerate,
}: GenerationPanelProps) {
  if (!selectedEvent) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400">
        Select an event to start generating
      </div>
    )
  }

  return (
    <div className="p-4 overflow-y-auto">
      <h2 className="text-lg font-semibold mb-3">{selectedEvent.name}</h2>

      {/* Generation type */}
      <div className="mb-3">
        <label className="block text-xs font-medium text-gray-500 mb-1">Type</label>
        <div className="flex flex-wrap gap-1">
          {GEN_TYPES.map((t) => (
            <button
              key={t.value}
              onClick={() => onGenTypeChange(t.value)}
              className={`px-2 py-1 text-xs rounded ${
                genType === t.value
                  ? 'bg-blue-500 text-white'
                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Approach */}
      <div className="mb-3">
        <label className="block text-xs font-medium text-gray-500 mb-1">Approach</label>
        <select
          value={approach}
          onChange={(e) => onApproachChange(e.target.value)}
          className="w-full text-sm border border-gray-200 rounded px-2 py-1"
        >
          {APPROACHES.map((a) => (
            <option key={a.value} value={a.value}>{a.label}</option>
          ))}
        </select>
      </div>

      {/* Style */}
      <div className="mb-3 grid grid-cols-2 gap-2">
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Preset</label>
          <select
            value={style?.preset || 'default'}
            onChange={(e) => onStyleChange({ ...style, preset: e.target.value })}
            className="w-full text-sm border border-gray-200 rounded px-2 py-1"
          >
            {PRESETS.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Line Style</label>
          <select
            value={style?.line_style || 'clean_vector'}
            onChange={(e) => onStyleChange({ ...style, line_style: e.target.value })}
            className="w-full text-sm border border-gray-200 rounded px-2 py-1"
          >
            {LINE_STYLES.map((l) => (
              <option key={l} value={l}>{l.replace('_', ' ')}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Generate button */}
      <button
        onClick={onGenerate}
        disabled={generating}
        className="w-full bg-blue-500 text-white rounded py-2 text-sm font-medium hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {generating ? 'Generating...' : 'Generate'}
      </button>

      {/* Result */}
      {result && (
        <div className="mt-4">
          {result.error ? (
            <div className="bg-red-50 text-red-700 text-sm rounded p-3">
              {result.error}
            </div>
          ) : result.image_url ? (
            <div>
              <img
                src={result.image_url}
                alt="Generated"
                className="w-full rounded-lg shadow-md"
              />
              <div className="mt-2 text-xs text-gray-400">
                <p>Model: {result.model}</p>
                <p>Time: {result.generation_time_ms}ms</p>
                <details className="mt-1">
                  <summary className="cursor-pointer">Prompt</summary>
                  <p className="mt-1 text-gray-500">{result.prompt}</p>
                </details>
              </div>
            </div>
          ) : null}
        </div>
      )}
    </div>
  )
}
```

**Step 5: Wire up PlaygroundPage**

`apps/telegram-web-app/src/features/playground/PlaygroundPage.tsx`:

```tsx
import { useEffect } from 'react'
import { usePlaygroundStore } from './store'
import EventList from './components/EventList'
import GenerationPanel from './components/GenerationPanel'

export default function PlaygroundPage() {
  const store = usePlaygroundStore()

  useEffect(() => {
    const today = new Date().toISOString().split('T')[0]
    store.loadEvents(today)
  }, [])

  return (
    <div className="h-screen flex flex-col bg-gray-50">
      <div className="px-4 py-3 border-b border-gray-200 bg-white">
        <h1 className="text-lg font-semibold">Asset Generation Playground</h1>
      </div>

      <div className="flex-1 flex overflow-hidden">
        {/* Left: Event list */}
        <div className="w-1/3 min-w-[140px] max-w-[200px]">
          <EventList
            events={store.events}
            selectedEvent={store.selectedEvent}
            onSelect={store.selectEvent}
          />
        </div>

        {/* Right: Generation panel */}
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

**Step 6: Verify in browser**

```bash
cd apps/telegram-web-app && npm run dev
# Visit http://localhost:5173/playground
# Should show split layout with event list on left, generation panel on right
```

**Step 7: Commit**

```bash
git add apps/telegram-web-app/src/features/playground/ apps/telegram-web-app/src/services/api.ts
git commit -m "feat: add playground UI with generation panel and style controls"
```

---

## Post-Implementation Checklist

After all tasks are complete, verify:

1. **Turborepo integration:** `npx turbo dev` starts both vault-server and webapp
2. **Webapp loads:** http://localhost:5173/ redirects to dayplanner
3. **Dayplanner shows data:** If vault-server is running with calendar enabled, events appear
4. **Playground loads:** http://localhost:5173/playground shows the generation workspace
5. **API endpoints work:**
   - `GET /timeline/2026-02-27` returns timeline data (or empty)
   - `GET /merged-events/2026-02-27` returns merged events
   - `GET /imagery/search?lat=32.08&lng=34.77` returns Wikimedia results
   - `POST /generate` returns generation result (requires REPLICATE_API_TOKEN)
6. **All tests pass:** `npx turbo test`
