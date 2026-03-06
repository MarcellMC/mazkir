import { describe, it, expect, vi, beforeEach } from 'vitest'
import { api } from '../api'

const mockFetch = vi.fn()
global.fetch = mockFetch

beforeEach(() => {
  mockFetch.mockReset()
})

describe('api client', () => {
  it('fetches events for a date', async () => {
    const mockResponse = {
      date: '2026-02-27',
      events: [],
      summary: { total_events: 0, total_tokens: 0 },
    }
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(mockResponse),
    })

    const result = await api.getEvents('2026-02-27')
    expect(result).toEqual(mockResponse)
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('/events/2026-02-27'),
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
