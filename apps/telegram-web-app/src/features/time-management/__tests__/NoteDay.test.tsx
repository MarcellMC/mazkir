import { describe, it, expect } from 'vitest'
import { headerParts } from '../components/NoteDay'

describe('NoteDay.headerParts', () => {
  it('formats a daily header', () => {
    const p = headerParts({ id: '2026-05-21', kind: 'daily', sort_key: '2026-05-21' })
    expect(p.dow).toBe('Thursday')
    expect(p.sub).toBe('21 MAY 2026')
  })

  it('formats a weekly header by week number', () => {
    const p = headerParts({ id: '2022-W34', kind: 'weekly', sort_key: '2022-08-28' })
    expect(p.dow).toBe('Week 34')
    expect(p.sub).toContain('ENDS')
  })
})
