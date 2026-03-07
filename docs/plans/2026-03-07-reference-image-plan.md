# Reference Image for Generation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add img2img reference image support to the Playground — upload files via Replicate's file API, serve event photos for thumbnails, and control prompt strength from the UI.

**Architecture:** Backend gets `upload_file()` for Replicate file hosting, a media serving route, and img2img parameters in `generate()`. Frontend gets a reference image picker (from events or device upload), thumbnail preview, and prompt strength slider. All wired through shared types, store, and props.

**Tech Stack:** Python/FastAPI/httpx (backend), TypeScript/React/Zustand/Tailwind (webapp), Replicate Files API

---

### Task 1: Shared types — add `reference_image` and `prompt_strength`

**Files:**
- Modify: `packages/shared-types/src/generation.ts:1-18`

**Step 1: Add fields to GenerateRequest**

```typescript
export interface GenerateRequest {
  type: 'micro_icon' | 'keyframe_scene' | 'route_sketch' | 'full_day_map';
  event_name?: string;
  activity_category?: string;
  location_name?: string;
  style?: {
    preset?: string;
    palette?: string[];
    line_style?: string;
    texture?: string;
    art_reference?: string;
  };
  approach?: string;
  prompt_override?: string;
  reference_image?: string;
  prompt_strength?: number;
  width?: number;
  height?: number;
  params?: Record<string, unknown>;
}
```

**Step 2: Commit**

```bash
cd /home/marcellmc/dev/mazkir
git add packages/shared-types/src/generation.ts
git commit -m "feat(shared-types): add reference_image and prompt_strength to GenerateRequest"
```

---

### Task 2: Backend — `upload_file()` and img2img support in `GenerationService`

**Files:**
- Modify: `apps/vault-server/src/services/generation_service.py:32-43,50-114`
- Test: `apps/vault-server/tests/test_generation_service.py`

**Step 1: Write failing tests**

Add to `tests/test_generation_service.py` inside `TestGenerationService`:

```python
@pytest.mark.asyncio
async def test_upload_file_returns_url(self, gen_service, tmp_path):
    # Create a test file
    test_file = tmp_path / "test.jpg"
    test_file.write_bytes(b"fake image data")

    upload_resp = MagicMock()
    upload_resp.json.return_value = {
        "urls": {"get": "https://replicate.delivery/files/test.jpg"},
    }
    upload_resp.raise_for_status = MagicMock()

    with patch("src.services.generation_service.httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.post.return_value = upload_resp
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
        url = await gen_service.upload_file(str(test_file))

    assert url == "https://replicate.delivery/files/test.jpg"
    mock_client.post.assert_called_once()

@pytest.mark.asyncio
async def test_generate_passes_image_and_prompt_strength(self, gen_service):
    request = GenerationRequest(
        type="keyframe_scene",
        event_name="Cafe",
        style=StyleConfig(),
        reference_image="/tmp/ref.jpg",
        prompt_strength=0.7,
    )

    mock_client = _mock_httpx_client(["https://replicate.delivery/output.png"])

    with patch("src.services.generation_service.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
        # Mock upload_file to avoid actual file read
        with patch.object(gen_service, "upload_file", return_value="https://replicate.delivery/ref.jpg"):
            await gen_service.generate(request)

    call_json = mock_client.post.call_args[1]["json"]
    assert call_json["input"]["image"] == "https://replicate.delivery/ref.jpg"
    assert call_json["input"]["prompt_strength"] == 0.7

@pytest.mark.asyncio
async def test_generate_without_reference_has_no_image_input(self, gen_service):
    request = GenerationRequest(
        type="micro_icon",
        event_name="Gym",
        style=StyleConfig(),
    )

    mock_client = _mock_httpx_client(["https://replicate.delivery/output.png"])

    with patch("src.services.generation_service.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
        await gen_service.generate(request)

    call_json = mock_client.post.call_args[1]["json"]
    assert "image" not in call_json["input"]
    assert "prompt_strength" not in call_json["input"]
```

**Step 2: Run tests to verify they fail**

```bash
cd /home/marcellmc/dev/mazkir/apps/vault-server && source venv/bin/activate && python -m pytest tests/test_generation_service.py -v
```
Expected: FAIL — `upload_file` doesn't exist, `reference_image`/`prompt_strength` not on model.

**Step 3: Add fields to `GenerationRequest`**

In `generation_service.py`, add after line 42 (`height`):

```python
    reference_image: str | None = None
    prompt_strength: float | None = None
```

**Step 4: Add `upload_file` method**

In `GenerationService`, add after `__init__` (after line 48):

```python
async def upload_file(self, file_path: str) -> str:
    """Upload a local file to Replicate's file hosting, return the serving URL."""
    from pathlib import Path

    file_data = Path(file_path).read_bytes()
    file_name = Path(file_path).name

    headers = {
        "Authorization": f"Bearer {self.api_token}",
    }

    async with httpx.AsyncClient(base_url=REPLICATE_API_BASE, headers=headers, timeout=60) as client:
        resp = await client.post(
            "/files",
            files={"content": (file_name, file_data, "application/octet-stream")},
        )
        resp.raise_for_status()
        data = resp.json()

    return data["urls"]["get"]
```

**Step 5: Update `generate()` to support img2img**

In `generate()`, after building `width`/`height` (line 68) and before the `resp = await client.post(...)` call (line 70), build the input dict conditionally:

```python
                prediction_input: dict[str, Any] = {
                    "prompt": prompt,
                    "width": width,
                    "height": height,
                    "num_outputs": 1,
                }

                # img2img: upload reference image and add to input
                if request.reference_image:
                    image_url = await self.upload_file(request.reference_image)
                    prediction_input["image"] = image_url
                    prediction_input["prompt_strength"] = request.prompt_strength or 0.7

                resp = await client.post("/predictions", json={
                    "version": version_id,
                    "input": prediction_input,
                })
```

This replaces the existing `resp = await client.post(...)` block (lines 70-78).

**Step 6: Run tests**

```bash
cd /home/marcellmc/dev/mazkir/apps/vault-server && source venv/bin/activate && python -m pytest tests/test_generation_service.py -v
```
Expected: ALL PASS

**Step 7: Commit**

```bash
cd /home/marcellmc/dev/mazkir
git add apps/vault-server/src/services/generation_service.py apps/vault-server/tests/test_generation_service.py
git commit -m "feat(vault-server): add upload_file and img2img support to GenerationService"
```

---

### Task 3: Backend — media serving route + upload endpoint

**Files:**
- Create: `apps/vault-server/src/api/routes/media.py`
- Modify: `apps/vault-server/src/api/routes/generate.py:13-24,36-48`
- Modify: `apps/vault-server/src/main.py` (register media router)

**Step 1: Create media route**

Create `apps/vault-server/src/api/routes/media.py`:

```python
"""Serve media files from data/media/ directory."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from src.config import settings

router = APIRouter(prefix="/media", tags=["media"])


@router.get("/{date}/{filename}")
async def get_media_file(date: str, filename: str):
    """Serve a photo file from data/media/{date}/{filename}."""
    file_path = settings.media_path / date / filename
    if not file_path.is_file():
        raise HTTPException(404, f"File not found: {date}/{filename}")
    # Prevent path traversal
    if not file_path.resolve().is_relative_to(settings.media_path.resolve()):
        raise HTTPException(403, "Access denied")
    return FileResponse(file_path)
```

**Step 2: Add `reference_image` and `prompt_strength` to generate route request model**

In `apps/vault-server/src/api/routes/generate.py`, add to `GenerateRequest` (after line 23):

```python
    reference_image: str | None = None
    prompt_strength: float | None = None
```

**Step 3: Pass new fields through in `generate_image()`**

In `generate_image()`, add to the `gen_request = GenerationRequest(...)` call (after line 46):

```python
        reference_image=request.reference_image,
        prompt_strength=request.prompt_strength,
```

**Step 4: Add file upload endpoint**

In `generate.py`, add at the end:

```python
from fastapi import UploadFile, File
import tempfile
import shutil


@router.post("/upload")
async def upload_reference_image(file: UploadFile = File(...)):
    """Upload a reference image, save to temp location, return path."""
    if not file.filename:
        raise HTTPException(400, "No filename provided")

    suffix = Path(file.filename).suffix or ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix="ref_") as tmp:
        shutil.copyfileobj(file.file, tmp)
        return {"path": tmp.name}
```

Add `from pathlib import Path` to the imports at the top if not already present.

**Step 5: Register media router in main.py**

In `apps/vault-server/src/main.py`, add after the events router import (line 164):

```python
from src.api.routes.media import router as media_router
```

And after `app.include_router(events_router)` (line 176):

```python
app.include_router(media_router)
```

**Step 6: Commit**

```bash
cd /home/marcellmc/dev/mazkir
git add apps/vault-server/src/api/routes/media.py apps/vault-server/src/api/routes/generate.py apps/vault-server/src/main.py
git commit -m "feat(vault-server): add media serving route and reference image upload endpoint"
```

---

### Task 4: Frontend — API helpers and store updates

**Files:**
- Modify: `apps/telegram-web-app/src/services/api.ts:29-55`
- Modify: `apps/telegram-web-app/src/features/playground/store.ts`

**Step 1: Add API helpers**

In `apps/telegram-web-app/src/services/api.ts`, add to the `api` object (after `searchImagery`, before the closing `}`):

```typescript
  uploadReferenceImage(file: File): Promise<{ path: string }> {
    const formData = new FormData()
    formData.append('file', file)
    const headers: Record<string, string> = {}
    if (API_KEY) headers['X-API-Key'] = API_KEY
    return fetch(`${API_BASE}/generate/upload`, {
      method: 'POST',
      headers,
      body: formData,
    }).then(res => {
      if (!res.ok) throw new Error(`Upload failed: ${res.status}`)
      return res.json()
    })
  },

  getMediaUrl(date: string, filename: string): string {
    return `${API_BASE}/media/${date}/${filename}`
  },
```

Note: `uploadReferenceImage` can't use the generic `request()` helper because it sends `FormData`, not JSON (no `Content-Type: application/json` header).

**Step 2: Update store interface and state**

In `apps/telegram-web-app/src/features/playground/store.ts`, add to the `PlaygroundState` interface after the dimensions section (after line 29):

```typescript
  // Reference image
  referenceImage: string | null
  referenceImagePreview: string | null
  promptStrength: number
  uploadingReference: boolean
```

Add to actions section (after line 40, before `generate`):

```typescript
  setReferenceImage: (path: string, previewUrl: string) => void
  clearReferenceImage: () => void
  setPromptStrength: (value: number) => void
  uploadReferenceImage: (file: File) => Promise<void>
```

**Step 3: Add initial state values**

After line 62 (`height: 768,`):

```typescript
  referenceImage: null,
  referenceImagePreview: null,
  promptStrength: 0.7,
  uploadingReference: false,
```

**Step 4: Add actions**

After `setCustomDimensions` (line 102):

```typescript
  setReferenceImage: (path, previewUrl) => set({ referenceImage: path, referenceImagePreview: previewUrl }),

  clearReferenceImage: () => set({ referenceImage: null, referenceImagePreview: null }),

  setPromptStrength: (value) => set({ promptStrength: value }),

  uploadReferenceImage: async (file) => {
    set({ uploadingReference: true })
    try {
      const { path } = await api.uploadReferenceImage(file)
      set({
        referenceImage: path,
        referenceImagePreview: URL.createObjectURL(file),
        uploadingReference: false,
      })
    } catch {
      set({ uploadingReference: false })
    }
  },
```

**Step 5: Update `generate` action**

In the `api.generate()` call (around line 110-120), add the new fields:

```typescript
        reference_image: get().referenceImage || undefined,
        prompt_strength: get().referenceImage ? get().promptStrength : undefined,
```

**Step 6: Commit**

```bash
cd /home/marcellmc/dev/mazkir
git add apps/telegram-web-app/src/services/api.ts apps/telegram-web-app/src/features/playground/store.ts
git commit -m "feat(webapp): add reference image API helpers and store state"
```

---

### Task 5: Frontend — Reference image UI in GenerationPanel

**Files:**
- Modify: `apps/telegram-web-app/src/features/playground/components/GenerationPanel.tsx`
- Modify: `apps/telegram-web-app/src/features/playground/PlaygroundPage.tsx`

**Step 1: Add new props to GenerationPanelProps**

In `GenerationPanel.tsx`, add after line 23 (`onCustomDimensionsChange`):

```typescript
  referenceImage: string | null
  referenceImagePreview: string | null
  promptStrength: number
  uploadingReference: boolean
  eventPhotos: Array<{ path: string; previewUrl: string }>
  onSetReferenceImage: (path: string, previewUrl: string) => void
  onClearReferenceImage: () => void
  onPromptStrengthChange: (value: number) => void
  onUploadReferenceImage: (file: File) => void
```

**Step 2: Add `useRef` import**

Update the import line at top:

```typescript
import { useMemo, useRef } from 'react'
```

**Step 3: Destructure new props and add file input ref**

Add the new props to the destructured parameter list, and inside the component body (after the `displayPrompt` line):

```typescript
  const fileInputRef = useRef<HTMLInputElement>(null)
```

**Step 4: Add reference image section**

Insert between the aspect ratio section (ends at line 227) and the Generate button (line 229):

```tsx
      {/* Reference image */}
      <div className="mb-3">
        <div className="flex items-center justify-between mb-1">
          <label className="block text-xs font-medium text-gray-500">Reference Image</label>
          {referenceImage && (
            <button
              onClick={onClearReferenceImage}
              className="text-xs text-blue-500 hover:text-blue-700"
            >
              Clear
            </button>
          )}
        </div>

        {referenceImagePreview ? (
          <div className="flex items-center gap-2 p-2 border border-gray-200 rounded bg-gray-50">
            <img src={referenceImagePreview} alt="Reference" className="w-16 h-16 object-cover rounded" />
            <span className="text-xs text-gray-500 truncate flex-1">Reference selected</span>
          </div>
        ) : (
          <div className="flex gap-1">
            {eventPhotos.length > 0 && (
              <div className="flex gap-1 flex-wrap">
                {eventPhotos.map((photo) => (
                  <button
                    key={photo.path}
                    onClick={() => onSetReferenceImage(photo.path, photo.previewUrl)}
                    className="w-12 h-12 rounded border border-gray-200 overflow-hidden hover:border-blue-400"
                  >
                    <img src={photo.previewUrl} alt="" className="w-full h-full object-cover" />
                  </button>
                ))}
              </div>
            )}
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploadingReference}
              className="px-3 py-2 text-xs border border-dashed border-gray-300 rounded hover:border-blue-400 hover:text-blue-500 disabled:opacity-50"
            >
              {uploadingReference ? (
                <svg className="animate-spin h-4 w-4 mx-auto" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              ) : 'Upload'}
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) onUploadReferenceImage(file)
                e.target.value = ''
              }}
            />
          </div>
        )}

        {/* Prompt strength slider */}
        {referenceImage && (
          <div className="mt-2">
            <div className="flex items-center justify-between">
              <label className="text-xs text-gray-400">Prompt Strength</label>
              <span className="text-xs text-gray-500">{promptStrength.toFixed(2)}</span>
            </div>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={promptStrength}
              onChange={(e) => onPromptStrengthChange(Number(e.target.value))}
              className="w-full h-1 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-blue-500"
            />
            <div className="flex justify-between text-[10px] text-gray-300">
              <span>Keep original</span>
              <span>Full restyle</span>
            </div>
          </div>
        )}
      </div>
```

**Step 5: Wire props in PlaygroundPage**

In `PlaygroundPage.tsx`, add to the `<GenerationPanel>` props. First, compute `eventPhotos` from the selected event using the api helper. Add import and computation:

At the top, add:
```typescript
import { useMemo } from 'react'
import { api } from '../../services/api'
```

Inside the component, before the return:
```typescript
  const eventPhotos = useMemo(() => {
    const photos = store.selectedEvent?.photos || []
    return photos.map((p: { path: string }) => {
      const parts = p.path.split('/')
      const date = parts[parts.length - 2] || ''
      const filename = parts[parts.length - 1] || ''
      return {
        path: p.path,
        previewUrl: api.getMediaUrl(date, filename),
      }
    })
  }, [store.selectedEvent])
```

Add new props to `<GenerationPanel>`:

```tsx
              referenceImage={store.referenceImage}
              referenceImagePreview={store.referenceImagePreview}
              promptStrength={store.promptStrength}
              uploadingReference={store.uploadingReference}
              eventPhotos={eventPhotos}
              onSetReferenceImage={store.setReferenceImage}
              onClearReferenceImage={store.clearReferenceImage}
              onPromptStrengthChange={store.setPromptStrength}
              onUploadReferenceImage={store.uploadReferenceImage}
```

**Step 6: Commit**

```bash
cd /home/marcellmc/dev/mazkir
git add apps/telegram-web-app/src/features/playground/components/GenerationPanel.tsx apps/telegram-web-app/src/features/playground/PlaygroundPage.tsx
git commit -m "feat(webapp): add reference image picker, upload, and prompt strength slider"
```

---

### Task 6: Verify end-to-end

**Step 1: Run backend tests**

```bash
cd /home/marcellmc/dev/mazkir/apps/vault-server && source venv/bin/activate && python -m pytest tests/test_generation_service.py -v
```
Expected: ALL PASS (12 tests)

**Step 2: Run webapp type check**

```bash
cd /home/marcellmc/dev/mazkir/apps/telegram-web-app && npx tsc --noEmit
```
Expected: No new errors

**Step 3: Run webapp tests**

```bash
cd /home/marcellmc/dev/mazkir/apps/telegram-web-app && npx vitest run
```
Expected: PASS

**Step 4: Manual smoke test (optional)**

Start vault-server and webapp:
- Navigate to Playground, select an event
- If event has photos, thumbnails should appear in the Reference Image section
- Click "Upload" to upload a photo from device — should show spinner, then thumbnail preview
- Prompt strength slider appears when reference is selected (0.0–1.0)
- "Clear" link removes the reference image
- Generate with reference → should produce img2img result

**Step 5: Commit any fixups**

```bash
cd /home/marcellmc/dev/mazkir && git add -A && git commit -m "fix: reference image integration fixes"
```
