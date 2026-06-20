import { describe, it, expect } from 'vitest'
import { fractionToIndex, indexToFraction, labelForSortKey } from '../scrubber'

// Notes are newest-first; fraction 0 = top (newest), 1 = bottom (oldest).
const keys = ['2026-05-21', '2026-05-20', '2026-01-02', '2025-12-31']

describe('scrubber math', () => {
  it('maps drag fraction to nearest note index by TIME, not item index', () => {
    expect(fractionToIndex(0, keys)).toBe(0)            // newest
    expect(fractionToIndex(1, keys)).toBe(keys.length - 1) // oldest
    // A point ~10% down the time span lands near the big May cluster (index 1),
    // not the temporal midpoint between Jan and Dec.
    expect(fractionToIndex(0.1, keys)).toBe(1)
  })

  it('round-trips an index back to a fraction within tolerance', () => {
    const f = indexToFraction(2, keys)
    expect(f).toBeGreaterThan(0)
    expect(f).toBeLessThan(1)
  })

  it('formats a month/year bubble label', () => {
    expect(labelForSortKey('2026-05-21')).toBe('MAY 2026')
  })
})
