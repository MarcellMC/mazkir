# Playground Improvements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add editable prompt preview, contained image display, and aspect ratio controls to the Playground feature.

**Architecture:** Three independent changes: (1) port `build_prompt` to TypeScript and add prompt override to backend, (2) CSS container fix for images, (3) aspect ratio picker with custom size support wired through to Replicate. All changes touch shared-types, backend service/route, and webapp components/store.

**Tech Stack:** Python/FastAPI (backend), TypeScript/React/Zustand/Tailwind (webapp), @mazkir/shared-types

---

### Task 1: Add `prompt_override` and `width`/`height` to shared types

**Files:**
- Modify: `packages/shared-types/src/generation.ts:1-15`

**Step 1: Update GenerateRequest interface**

Add three optional fields to the existing `GenerateRequest`:

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
  width?: number;
  height?: number;
  params?: Record<string, unknown>;
}
```

**Step 2: Commit**

```bash
git add packages/shared-types/src/generation.ts
git commit -m "feat(shared-types): add prompt_override and width/height to GenerateRequest"
```

---

### Task 2: Backend — support `prompt_override` and `width`/`height`

**Files:**
- Modify: `apps/vault-server/src/api/routes/generate.py:13-21`
- Modify: `apps/vault-server/src/services/generation_service.py:32-40,47-70,156-170`
- Test: `apps/vault-server/tests/test_generation_service.py`

**Step 1: Write failing tests**

Add to `tests/test_generation_service.py`:

```python
def test_build_prompt_returns_override_when_set(self, gen_service):
    request = GenerationRequest(
        type="micro_icon",
        event_name="Gym",
        style=StyleConfig(),
        prompt_override="custom prompt text",
    )
    prompt = gen_service.build_prompt(request)
    assert prompt == "custom prompt text"

def test_build_prompt_ignores_empty_override(self, gen_service):
    request = GenerationRequest(
        type="micro_icon",
        event_name="Gym workout",
        style=StyleConfig(line_style="clean_vector"),
        prompt_override="",
    )
    prompt = gen_service.build_prompt(request)
    assert "icon" in prompt.lower()

@pytest.mark.asyncio
async def test_generate_uses_custom_dimensions(self, gen_service):
    request = GenerationRequest(
        type="micro_icon",
        event_name="Gym",
        style=StyleConfig(),
        width=512,
        height=768,
    )

    mock_client = _mock_httpx_client(["https://replicate.delivery/output.png"])

    with patch("src.services.generation_service.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
        await gen_service.generate(request)

    call_json = mock_client.post.call_args[1]["json"]
    assert call_json["input"]["width"] == 512
    assert call_json["input"]["height"] == 768

def test_clamp_dimension(self, gen_service):
    assert gen_service._clamp_dimension(100) == 128    # rounds up to nearest 64
    assert gen_service._clamp_dimension(1200) == 1024  # caps at 1024
    assert gen_service._clamp_dimension(768) == 768    # already valid
    assert gen_service._clamp_dimension(50) == 64      # minimum 64
```

**Step 2: Run tests to verify they fail**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_generation_service.py -v
```
Expected: FAIL — `prompt_override` and `width`/`height` fields don't exist, `_clamp_dimension` doesn't exist.

**Step 3: Update `GenerationRequest` model**

In `apps/vault-server/src/services/generation_service.py`, add fields to `GenerationRequest` (line 32-40):

```python
class GenerationRequest(BaseModel):
    type: str  # 'micro_icon' | 'keyframe_scene' | 'route_sketch' | 'full_day_map'
    event_name: str = ""
    activity_category: str | None = None
    location_name: str | None = None
    style: StyleConfig = StyleConfig()
    approach: str = "ai_raster"
    reference_images: list[str] | None = None
    prompt_override: str | None = None
    width: int | None = None
    height: int | None = None
    params: dict[str, Any] | None = None
```

**Step 4: Add `_clamp_dimension` static method**

After `_get_height` (line 170), add:

```python
@staticmethod
def _clamp_dimension(value: int) -> int:
    """Clamp to multiple of 64, min 64, max 1024."""
    clamped = max(64, min(1024, value))
    return round(clamped / 64) * 64
```

**Step 5: Update `build_prompt` to respect override**

At the top of `build_prompt()` (line 110), add early return:

```python
def build_prompt(self, request: GenerationRequest) -> str:
    """Build a generation prompt based on request type and style."""
    if request.prompt_override:
        return request.prompt_override
    # ... rest unchanged
```

**Step 6: Update `generate` to use custom dimensions**

In `generate()`, replace the hardcoded width/height (lines 68-69):

```python
width = self._clamp_dimension(request.width) if request.width else self._get_width(request.type)
height = self._clamp_dimension(request.height) if request.height else self._get_height(request.type)
```

And use `width`/`height` variables in the prediction input:

```python
"input": {
    "prompt": prompt,
    "width": width,
    "height": height,
    "num_outputs": 1,
},
```

**Step 7: Update route request model**

In `apps/vault-server/src/api/routes/generate.py`, add fields to `GenerateRequest` (line 13-21):

```python
class GenerateRequest(BaseModel):
    type: str
    event_name: str = ""
    activity_category: str | None = None
    location_name: str | None = None
    style: dict[str, Any] | None = None
    approach: str = "ai_raster"
    reference_images: list[str] | None = None
    prompt_override: str | None = None
    width: int | None = None
    height: int | None = None
    params: dict[str, Any] | None = None
```

And pass them through in `generate_image()` (line 33-42):

```python
gen_request = GenerationRequest(
    type=request.type,
    event_name=request.event_name,
    activity_category=request.activity_category,
    location_name=request.location_name,
    style=style,
    approach=request.approach,
    reference_images=request.reference_images,
    prompt_override=request.prompt_override,
    width=request.width,
    height=request.height,
    params=request.params,
)
```

**Step 8: Run tests to verify they pass**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_generation_service.py -v
```
Expected: ALL PASS

**Step 9: Commit**

```bash
git add apps/vault-server/src/services/generation_service.py apps/vault-server/src/api/routes/generate.py apps/vault-server/tests/test_generation_service.py
git commit -m "feat(vault-server): support prompt_override and custom width/height in generation"
```

---

### Task 3: Client — `buildPrompt` TypeScript helper

**Files:**
- Create: `apps/telegram-web-app/src/features/playground/buildPrompt.ts`

**Step 1: Create the helper**

Port the Python `build_prompt` logic to TypeScript. This is a pure function mirroring `generation_service.py:110-154`:

```typescript
import type { GenerateRequest } from '../../services/api'

const LINE_STYLE_DESCRIPTIONS: Record<string, string> = {
  loose_ink: 'loose ink drawing style',
  clean_vector: 'clean vector art',
  crosshatch: 'crosshatch pen illustration',
  watercolor_edge: 'watercolor edges, soft blending',
}

export function buildPrompt(req: {
  type: GenerateRequest['type']
  event_name?: string
  activity_category?: string
  location_name?: string
  style?: GenerateRequest['style']
}): string {
  const parts: string[] = []

  switch (req.type) {
    case 'micro_icon':
      parts.push(`Minimal vector icon of ${req.event_name || ''}`)
      if (req.activity_category) parts.push(`representing ${req.activity_category} activity`)
      parts.push('simple, clean, flat design, single color')
      break
    case 'route_sketch':
      parts.push(`Hand-drawn route sketch map for ${req.event_name || ''}`)
      if (req.location_name) parts.push(`in ${req.location_name}`)
      parts.push('illustrated path, minimalist')
      break
    case 'keyframe_scene':
      parts.push(`Illustrated scene card for ${req.event_name || ''}`)
      if (req.location_name) parts.push(`at ${req.location_name}`)
      parts.push('atmospheric, detailed, warm lighting')
      break
    case 'full_day_map':
      parts.push('Illustrated day journey map showing connected stops')
      parts.push("bird's eye view, illustrated style")
      break
  }

  const style = req.style
  if (style?.preset === 'tel-aviv') {
    parts.push('Tel Aviv Mediterranean style, warm tones, Bauhaus architecture')
  }
  if (style?.line_style) {
    const desc = LINE_STYLE_DESCRIPTIONS[style.line_style]
    if (desc) parts.push(desc)
  }
  if (style?.texture && style.texture !== 'clean') {
    parts.push(`${style.texture.replace(/_/g, ' ')} texture`)
  }
  if (style?.art_reference) {
    parts.push(`inspired by ${style.art_reference}`)
  }

  return parts.join(', ')
}
```

**Step 2: Commit**

```bash
git add apps/telegram-web-app/src/features/playground/buildPrompt.ts
git commit -m "feat(webapp): add buildPrompt helper mirroring server-side logic"
```

---

### Task 4: Store — add prompt, aspect ratio, and dimension state

**Files:**
- Modify: `apps/telegram-web-app/src/features/playground/store.ts`

**Step 1: Update store with new state and actions**

Add to the `PlaygroundState` interface (after line 21):

```typescript
// Prompt
promptOverride: string | null
setPromptOverride: (prompt: string | null) => void

// Dimensions
aspectRatio: string
width: number
height: number
setAspectRatio: (ratio: string) => void
setCustomDimensions: (width: number, height: number) => void
```

Add to initial state (after line 45):

```typescript
promptOverride: null,
aspectRatio: '1:1',
width: 768,
height: 768,
```

Add actions:

```typescript
setPromptOverride: (prompt) => set({ promptOverride: prompt }),

setAspectRatio: (ratio) => {
  const presets: Record<string, [number, number]> = {
    '1:1': [768, 768],
    '4:3': [768, 576],
    '3:4': [576, 768],
    '16:9': [768, 448],
    '9:16': [448, 768],
  }
  const dims = presets[ratio]
  if (dims) {
    set({ aspectRatio: ratio, width: dims[0], height: dims[1] })
  } else {
    set({ aspectRatio: ratio })
  }
},

setCustomDimensions: (width, height) => set({ aspectRatio: 'custom', width, height }),
```

Update `generate` action to include new fields (inside the `api.generate()` call):

```typescript
const result = await api.generate({
  type: genType,
  event_name: selectedEvent.name,
  activity_category: selectedEvent.activity_category || undefined,
  location_name: selectedEvent.location?.name,
  style,
  approach,
  prompt_override: get().promptOverride || undefined,
  width: get().width,
  height: get().height,
})
```

**Step 2: Commit**

```bash
git add apps/telegram-web-app/src/features/playground/store.ts
git commit -m "feat(webapp): add prompt override and dimension state to playground store"
```

---

### Task 5: GenerationPanel — prompt textarea, aspect ratio picker, image container

**Files:**
- Modify: `apps/telegram-web-app/src/features/playground/components/GenerationPanel.tsx`

**Step 1: Update props interface**

Add new props to `GenerationPanelProps` (after line 13):

```typescript
promptOverride: string | null
width: number
height: number
aspectRatio: string
onPromptOverrideChange: (prompt: string | null) => void
onAspectRatioChange: (ratio: string) => void
onCustomDimensionsChange: (width: number, height: number) => void
```

**Step 2: Add aspect ratio presets constant**

After the existing constants (after line 32):

```typescript
const ASPECT_RATIOS = [
  { value: '1:1', label: '1:1' },
  { value: '4:3', label: '4:3' },
  { value: '3:4', label: '3:4' },
  { value: '16:9', label: '16:9' },
  { value: '9:16', label: '9:16' },
  { value: 'custom', label: 'Custom' },
]
```

**Step 3: Add prompt preview with auto-generation**

Import `buildPrompt` and add `useMemo`/`useState` for prompt management. Inside the component, compute the auto-generated prompt and show a textarea:

```tsx
import { useMemo } from 'react'
import { buildPrompt } from '../buildPrompt'

// Inside the component function body:
const autoPrompt = useMemo(
  () =>
    buildPrompt({
      type: genType,
      event_name: selectedEvent?.name,
      activity_category: selectedEvent?.activity_category || undefined,
      location_name: selectedEvent?.location?.name,
      style,
    }),
  [genType, selectedEvent, style],
)

const displayPrompt = promptOverride ?? autoPrompt
```

Add prompt textarea section between the style grid and the Generate button (after line 118, before line 120):

```tsx
{/* Prompt preview */}
<div className="mb-3">
  <div className="flex items-center justify-between mb-1">
    <label className="block text-xs font-medium text-gray-500">Prompt</label>
    {promptOverride !== null && (
      <button
        onClick={() => onPromptOverrideChange(null)}
        className="text-xs text-blue-500 hover:text-blue-700"
      >
        Reset to auto
      </button>
    )}
  </div>
  <textarea
    value={displayPrompt}
    onChange={(e) => onPromptOverrideChange(e.target.value)}
    rows={3}
    className="w-full text-sm border border-gray-200 rounded px-2 py-1 resize-y"
  />
</div>
```

**Step 4: Add aspect ratio picker**

Add between the prompt textarea and the Generate button:

```tsx
{/* Aspect ratio */}
<div className="mb-3">
  <label className="block text-xs font-medium text-gray-500 mb-1">Size</label>
  <div className="flex flex-wrap gap-1">
    {ASPECT_RATIOS.map((r) => (
      <button
        key={r.value}
        onClick={() => onAspectRatioChange(r.value)}
        className={`px-2 py-1 text-xs rounded ${
          aspectRatio === r.value
            ? 'bg-blue-500 text-white'
            : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
        }`}
      >
        {r.label}
      </button>
    ))}
  </div>
  {aspectRatio === 'custom' && (
    <div className="mt-2 grid grid-cols-2 gap-2">
      <div>
        <label className="block text-xs text-gray-400">Width</label>
        <input
          type="number"
          value={width}
          onChange={(e) => onCustomDimensionsChange(Number(e.target.value), height)}
          className="w-full text-sm border border-gray-200 rounded px-2 py-1"
          min={64}
          max={1024}
          step={64}
        />
      </div>
      <div>
        <label className="block text-xs text-gray-400">Height</label>
        <input
          type="number"
          value={height}
          onChange={(e) => onCustomDimensionsChange(width, Number(e.target.value))}
          className="w-full text-sm border border-gray-200 rounded px-2 py-1"
          min={64}
          max={1024}
          step={64}
        />
      </div>
    </div>
  )}
  <p className="text-xs text-gray-400 mt-1">{width}×{height}px</p>
</div>
```

**Step 5: Contain the image result**

Replace the current result display section (lines 130-154) with a contained version:

```tsx
{/* Result */}
{result && (
  <div className="mt-4 max-w-sm mx-auto">
    {result.error ? (
      <div className="bg-red-50 text-red-700 text-sm rounded p-3">
        {result.error}
      </div>
    ) : result.image_url ? (
      <div className="border border-gray-200 rounded-lg bg-white p-2">
        <img
          src={result.image_url}
          alt="Generated"
          className="w-full h-auto rounded"
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
```

**Step 6: Commit**

```bash
git add apps/telegram-web-app/src/features/playground/components/GenerationPanel.tsx
git commit -m "feat(webapp): add prompt editor, aspect ratio picker, and image container to GenerationPanel"
```

---

### Task 6: Wire new props through PlaygroundPage

**Files:**
- Modify: `apps/telegram-web-app/src/features/playground/PlaygroundPage.tsx`

**Step 1: Read PlaygroundPage.tsx and pass new props**

The `PlaygroundPage` currently passes store values to `GenerationPanel`. Add the new props:

```tsx
<GenerationPanel
  selectedEvent={store.selectedEvent}
  genType={store.genType}
  approach={store.approach}
  style={store.style}
  generating={store.generating}
  result={store.result}
  promptOverride={store.promptOverride}
  width={store.width}
  height={store.height}
  aspectRatio={store.aspectRatio}
  onGenTypeChange={store.setGenType}
  onApproachChange={store.setApproach}
  onStyleChange={store.setStyle}
  onGenerate={store.generate}
  onPromptOverrideChange={store.setPromptOverride}
  onAspectRatioChange={store.setAspectRatio}
  onCustomDimensionsChange={store.setCustomDimensions}
/>
```

**Step 2: Commit**

```bash
git add apps/telegram-web-app/src/features/playground/PlaygroundPage.tsx
git commit -m "feat(webapp): wire new playground props through PlaygroundPage"
```

---

### Task 7: Verify end-to-end

**Step 1: Run backend tests**

```bash
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_generation_service.py -v
```
Expected: ALL PASS

**Step 2: Run webapp type check**

```bash
cd apps/telegram-web-app && npx tsc --noEmit
```
Expected: No new errors (pre-existing errors may exist per MEMORY.md)

**Step 3: Run webapp tests**

```bash
cd apps/telegram-web-app && npx vitest run
```
Expected: PASS

**Step 4: Manual smoke test (optional)**

Start vault-server and webapp, navigate to Playground:
- Verify prompt textarea shows auto-generated text and updates when changing form fields
- Verify editing the prompt shows "Reset to auto" link
- Verify aspect ratio chips work and "Custom" shows width/height inputs
- Verify generated image is contained in a bordered box (max-w-sm)

**Step 5: Final commit (if any fixups needed)**

```bash
git add -A && git commit -m "fix: playground improvements integration fixes"
```
