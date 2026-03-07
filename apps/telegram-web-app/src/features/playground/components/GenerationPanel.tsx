import { useMemo } from 'react'
import type { MergedEvent } from '../../../models/event'
import type { GenerateRequest, GenerateResponse } from '../../../services/api'
import { buildPrompt } from '../buildPrompt'

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
  promptOverride: string | null
  width: number
  height: number
  aspectRatio: string
  onPromptOverrideChange: (prompt: string | null) => void
  onAspectRatioChange: (ratio: string) => void
  onCustomDimensionsChange: (width: number, height: number) => void
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
  { value: 'hybrid_svg_to_ai', label: 'Hybrid SVG\u2192AI' },
  { value: 'style_transfer', label: 'Style Transfer' },
]

const LINE_STYLES = ['clean_vector', 'loose_ink', 'crosshatch', 'watercolor_edge']
const PRESETS = ['default', 'tel-aviv', 'jerusalem']

const ASPECT_RATIOS = [
  { value: '1:1', label: '1:1' },
  { value: '4:3', label: '4:3' },
  { value: '3:4', label: '3:4' },
  { value: '16:9', label: '16:9' },
  { value: '9:16', label: '9:16' },
  { value: 'custom', label: 'Custom' },
]

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
  promptOverride,
  width,
  height,
  aspectRatio,
  onPromptOverrideChange,
  onAspectRatioChange,
  onCustomDimensionsChange,
}: GenerationPanelProps) {
  if (!selectedEvent) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400">
        Select an event to start generating
      </div>
    )
  }

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

  return (
    <div className="p-4">
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

      {/* Generate button */}
      <button
        onClick={onGenerate}
        disabled={generating}
        className="w-full bg-blue-500 text-white rounded py-2 text-sm font-medium hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {generating ? (
          <span className="flex items-center justify-center gap-2">
            <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            Generating...
          </span>
        ) : 'Generate'}
      </button>

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
    </div>
  )
}
