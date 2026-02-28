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
  { value: 'hybrid_svg_to_ai', label: 'Hybrid SVG\u2192AI' },
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
