# Playground Improvements Design

**Date:** 2026-03-07
**Status:** Approved

## Overview

Three improvements to the Telegram Mini App Playground feature:
1. Editable prompt preview before generation
2. Contained image display sizing
3. Aspect ratio / image size controls

## 1. Editable Prompt Preview

### Behavior
- Current form fields (type, approach, preset, line style) remain unchanged
- Below form fields, a new prompt textarea shows a live preview of what `build_prompt()` would produce
- Prompt auto-updates when form fields change (client-side mirror of server's `build_prompt` logic)
- Once manually edited, prompt is "detached" from form fields — a "Reset to auto" link restores it
- On Generate, edited prompt is sent directly to Replicate bypassing server-side `build_prompt()`

### Backend Changes
- Add optional `prompt_override: str | None` field to `GenerateRequest` (generation_service.py)
- Add optional `prompt_override` to route's `GenerateRequest` (generate.py)
- In `generate()`: if `prompt_override` is set, use it instead of calling `build_prompt()`
- Add `prompt_override` to shared types `GenerateRequest`

### Client Changes
- Port `build_prompt` logic to a TypeScript helper (`buildPrompt()` in playground feature)
- GenerationPanel gets a textarea showing `buildPrompt()` output, updated on form field changes
- Store tracks `promptOverride: string | null` — null means auto-generated, string means user-edited
- Generate action sends `prompt_override` when set

## 2. Image Container Sizing

### Current Problem
`w-full` on the image stretches it to fill the entire right panel — too large on desktop, no breathing room on mobile.

### Fix
- Wrap result image in `max-w-sm mx-auto` container (max 384px, centered) with padding and subtle border/background
- Image inside uses `w-full h-auto` within the constrained box
- Metadata (model, time, prompt) below the box, same max-width
- CSS-only change, no logic changes

## 3. Aspect Ratio / Image Size Control

### UI
Row of chip-style buttons below style dropdowns:
```
Size: [1:1] [4:3] [3:4] [16:9] [9:16] [Custom]
```
"Custom" expands two number inputs (width/height) below chips. Presets auto-populate width/height.

### Preset-to-Pixel Mapping (SDXL multiples of 64)

| Ratio | Width | Height |
|-------|-------|--------|
| 1:1   | 768   | 768    |
| 4:3   | 768   | 576    |
| 3:4   | 576   | 768    |
| 16:9  | 768   | 448    |
| 9:16  | 448   | 768    |

Custom inputs accept any value — backend clamps to multiples of 64 and caps at 1024 max per dimension.

### Data Flow
- Store gets `width: number`, `height: number`, `aspectRatio: string` fields
- `GenerateRequest` shared type gets optional `width`/`height` fields
- Backend `generation_service.py`: if request has width/height, use those instead of hardcoded `_get_width`/`_get_height`
- Backend clamps custom values to multiples of 64, max 1024 per dimension

## Files Affected

### Backend (vault-server)
- `src/services/generation_service.py` — prompt_override support, width/height from request, clamping
- `src/api/routes/generate.py` — new request fields (prompt_override, width, height)

### Shared Types
- `packages/shared-types/src/generation.ts` — add prompt_override, width, height to GenerateRequest

### Frontend (telegram-web-app)
- `src/features/playground/buildPrompt.ts` — new file, TypeScript mirror of build_prompt()
- `src/features/playground/store.ts` — new state fields (promptOverride, width, height, aspectRatio)
- `src/features/playground/components/GenerationPanel.tsx` — prompt textarea, aspect ratio picker, image container
