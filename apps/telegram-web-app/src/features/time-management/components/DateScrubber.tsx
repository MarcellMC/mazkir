import { useRef, useState } from 'react'
import { labelForSortKey, indexToFraction } from '../scrubber'

interface Props {
  keys: string[]
  activeIndex: number
  onSeek: (fraction: number) => void
}

export default function DateScrubber({ keys, activeIndex, onSeek }: Props) {
  const trackRef = useRef<HTMLDivElement>(null)
  const [dragging, setDragging] = useState(false)

  function fractionFromEvent(clientY: number): number {
    const el = trackRef.current
    if (!el) return 0
    const r = el.getBoundingClientRect()
    return Math.min(1, Math.max(0, (clientY - r.top) / r.height))
  }
  function handle(clientY: number) { onSeek(fractionFromEvent(clientY)) }

  const thumbTop = `${indexToFraction(activeIndex, keys) * 100}%`
  const label = keys[activeIndex] ? labelForSortKey(keys[activeIndex]) : ''

  return (
    <div className="tm-scrub">
      <div
        ref={trackRef}
        data-testid="scrub-track"
        className="tm-scrub-track"
        onPointerDown={(e) => { setDragging(true); handle(e.clientY) }}
        onPointerMove={(e) => { if (dragging) handle(e.clientY) }}
        onPointerUp={() => setDragging(false)}
        onPointerLeave={() => setDragging(false)}
      />
      {dragging && <div className="tm-scrub-bubble" style={{ top: thumbTop }}>{label}</div>}
      <div className="tm-scrub-thumb" style={{ top: thumbTop }} />
    </div>
  )
}
