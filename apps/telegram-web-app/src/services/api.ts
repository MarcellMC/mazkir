import type { MergedEventsResponse, DailyResponse, TokensResponse } from '../models/event'
import type { GenerateRequest, GenerateResponse, ImageryResult } from '@mazkir/shared-types'

export type { GenerateRequest, GenerateResponse, ImageryResult }

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

  generate(req: GenerateRequest): Promise<GenerateResponse> {
    return request('/generate', { method: 'POST', body: JSON.stringify(req) })
  },

  searchImagery(lat: number, lng: number, radius?: number): Promise<{ results: ImageryResult[] }> {
    const params = new URLSearchParams({ lat: String(lat), lng: String(lng) })
    if (radius) params.set('radius', String(radius))
    return request(`/imagery/search?${params}`)
  },
}
