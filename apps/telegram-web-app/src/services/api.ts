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

  generate(req: GenerateRequest): Promise<GenerateResponse> {
    return request('/generate', { method: 'POST', body: JSON.stringify(req) })
  },

  searchImagery(lat: number, lng: number, radius?: number): Promise<{ results: ImageryResult[] }> {
    const params = new URLSearchParams({ lat: String(lat), lng: String(lng) })
    if (radius) params.set('radius', String(radius))
    return request(`/imagery/search?${params}`)
  },
}
