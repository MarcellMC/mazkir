# Reference Image for Generation — Design

**Date:** 2026-03-07
**Status:** Approved

## Overview

Add reference image support (img2img) to the Playground. Users can pick a photo from event data or upload from their device. The image is uploaded to Replicate's file API to get a serving URL, then passed to SDXL as the `image` input alongside a `prompt_strength` slider.

## 1. Backend — Replicate File Upload + img2img

### New method: `GenerationService.upload_file(file_path) -> str`
- Reads a local file from disk
- Uploads to `POST https://api.replicate.com/v1/files` (multipart)
- Returns the Replicate-hosted serving URL

### Updated `generate()` flow
- If `reference_image` is set, call `upload_file()` to get a Replicate URL
- Add `image: <url>` and `prompt_strength: <value>` to the SDXL prediction input
- If no reference image, works exactly as before (text-to-image)

### New field on `GenerationRequest`
- `reference_image: str | None = None` — local file path (from event photos or temp upload)
- `prompt_strength: float | None = None` — 0.0 (keep original) to 1.0 (ignore reference), default None = text-only

### New API routes
- `POST /generate/upload` — accepts multipart file upload, saves to temp location, returns `{ path: string }`
- `GET /media/{date}/{filename}` — serves files from `data/media/` for webapp thumbnails

## 2. Shared Types + API

### `GenerateRequest` additions
```typescript
reference_image?: string   // path like "data/media/2026-03-05/photo.jpg" or temp upload path
prompt_strength?: number   // 0.0-1.0, only used when reference_image is set
```

Singular `reference_image` (not the existing `reference_images` array). Old field stays, unused.

### New endpoints
- `POST /generate/upload` — multipart file, returns `{ path: string }`
- `GET /media/{date}/{filename}` — static file serving

### `GenerateResponse` — no changes

## 3. Frontend — Reference Image UI

### GenerationPanel section (between aspect ratio picker and Generate button)
- Label: "Reference Image" + optional "Clear" link
- Two source buttons: `[From Events]` `[Upload]`
- **From Events**: thumbnails from selected event's `photos` array via `GET /media/{date}/{filename}`. Click to select.
- **Upload**: hidden `<input type="file" accept="image/*">` behind styled button. Uploads to `POST /generate/upload`, gets path back.
- Selected reference: small thumbnail preview
- **Prompt strength slider**: visible only when reference is selected. Range 0.0–1.0, default 0.7, shows current value.

### Store additions
- `referenceImage: string | null` — the server path
- `referenceImagePreview: string | null` — thumbnail URL or object URL for display
- `promptStrength: number` — default 0.7
- `uploadingReference: boolean` — loading state
- Actions: `setReferenceImage`, `clearReferenceImage`, `setPromptStrength`, `uploadReferenceImage`

## Files Affected

### Backend (vault-server)
- `src/services/generation_service.py` — `upload_file()`, img2img in `generate()`, new fields on `GenerationRequest`
- `src/api/routes/generate.py` — new fields, `POST /generate/upload` endpoint
- `src/api/routes/media.py` — new route serving `data/media/` files
- `src/main.py` — register media router

### Shared Types
- `packages/shared-types/src/generation.ts` — `reference_image`, `prompt_strength` on `GenerateRequest`

### Frontend (telegram-web-app)
- `src/services/api.ts` — `uploadReferenceImage()`, `getMediaUrl()` helpers
- `src/features/playground/store.ts` — reference image state + actions
- `src/features/playground/components/GenerationPanel.tsx` — reference image picker, slider, thumbnail
- `src/features/playground/PlaygroundPage.tsx` — wire new props
