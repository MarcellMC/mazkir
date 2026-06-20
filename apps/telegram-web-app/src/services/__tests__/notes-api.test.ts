import { describe, it, expect, vi, beforeEach } from 'vitest'
import { api } from '../api'

const mockFetch = vi.fn()
global.fetch = mockFetch
beforeEach(() => mockFetch.mockReset())

function ok(body: unknown) {
  return { ok: true, json: () => Promise.resolve(body) }
}

describe('notes api', () => {
  it('lists notes', async () => {
    mockFetch.mockResolvedValueOnce(ok({ notes: [{ id: '2026-05-21' }] }))
    const res = await api.listNotes()
    expect(res.notes[0]?.id).toBe('2026-05-21')
    expect(mockFetch).toHaveBeenCalledWith(expect.stringContaining('/notes'), expect.any(Object))
  })

  it('gets one note', async () => {
    mockFetch.mockResolvedValueOnce(ok({ id: '2026-05-21', markdown: '# hi' }))
    const res = await api.getNote('2026-05-21')
    expect(res.markdown).toBe('# hi')
    expect(mockFetch).toHaveBeenCalledWith(expect.stringContaining('/notes/2026-05-21'), expect.any(Object))
  })

  it('patches a checkbox', async () => {
    mockFetch.mockResolvedValueOnce(ok({ id: '2026-05-21', markdown: '- [x] x' }))
    await api.setNoteCheckbox('2026-05-21', 2, true)
    const [url, opts] = mockFetch.mock.calls[0]!
    expect(url).toContain('/notes/2026-05-21/checkbox')
    expect(opts.method).toBe('PATCH')
    expect(JSON.parse(opts.body)).toEqual({ line: 2, checked: true })
  })
})
