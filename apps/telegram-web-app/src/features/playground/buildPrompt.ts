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
