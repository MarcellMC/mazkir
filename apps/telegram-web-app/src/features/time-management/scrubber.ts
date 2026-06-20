function ms(key: string): number {
  return new Date(key + 'T00:00:00Z').getTime()
}

/** Fraction 0..1 (top=newest) → index of the note nearest that point in time. */
export function fractionToIndex(fraction: number, keys: string[]): number {
  if (keys.length === 0) return 0
  const newest = ms(keys[0])
  const oldest = ms(keys[keys.length - 1])
  if (newest === oldest) return 0
  const target = newest - fraction * (newest - oldest)
  let best = 0
  let bestDist = Infinity
  keys.forEach((k, i) => {
    const d = Math.abs(ms(k) - target)
    if (d < bestDist) { bestDist = d; best = i }
  })
  return best
}

/** Index → fraction 0..1 along the time span (for placing the thumb). */
export function indexToFraction(index: number, keys: string[]): number {
  if (keys.length <= 1) return 0
  const newest = ms(keys[0])
  const oldest = ms(keys[keys.length - 1])
  if (newest === oldest) return 0
  return (newest - ms(keys[index])) / (newest - oldest)
}

const MONTHS = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC']

export function labelForSortKey(key: string): string {
  const d = new Date(key + 'T00:00:00Z')
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`
}
