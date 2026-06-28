import { useRef, useState } from 'react'
import { labelForSortKey, indexToFraction, fractionToIndex } from '../scrubber'

interface Props {
  keys: string[]
  activeIndex: number
  onSeek: (fraction: number) => void
}

export default function DateScrubber({ keys, activeIndex, onSeek }: Props) {
  const trackRef = useRef<HTMLDivElement>(null)
  const [dragging, setDragging] = useState(false)
  // While dragging we drive the thumb from the finger position directly, so it
  // tracks instantly instead of waiting for the virtualizer's scroll to catch up.
  const [dragFraction, setDragFraction] = useState(0)
  const rafRef = useRef<number | null>(null)

  function fractionFromEvent(clientY: number): number {
    const el = trackRef.current
    if (!el) return 0
    const r = el.getBoundingClientRect()
    return Math.min(1, Math.max(0, (clientY - r.top) / r.height))
  }

  // Coalesce the (heavy) scrollToIndex to one call per frame.
  function scheduleSeek(fraction: number) {
    if (rafRef.current != null) return
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null
      onSeek(fraction)
    })
  }

  function onDown(e: React.PointerEvent<HTMLDivElement>) {
    // Capture so the drag survives the finger drifting off the thin rail.
    e.currentTarget.setPointerCapture?.(e.pointerId)
    setDragging(true)
    const f = fractionFromEvent(e.clientY)
    setDragFraction(f)
    onSeek(f)
  }
  function onMove(e: React.PointerEvent<HTMLDivElement>) {
    if (!dragging) return
    const f = fractionFromEvent(e.clientY)
    setDragFraction(f)
    scheduleSeek(f)
  }
  function endDrag() {
    setDragging(false)
    if (rafRef.current != null) {
      cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
  }

  const fraction = dragging ? dragFraction : indexToFraction(activeIndex, keys)
  const thumbTop = `${fraction * 100}%`
  const labelIndex = dragging ? fractionToIndex(dragFraction, keys) : activeIndex
  const label = keys[labelIndex] ? labelForSortKey(keys[labelIndex]!) : ''

  return (
    <div className="tm-scrub">
      <div
        ref={trackRef}
        data-testid="scrub-track"
        className="tm-scrub-track"
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      />
      {dragging && <div className="tm-scrub-bubble" style={{ top: thumbTop }}>{label}</div>}
      <div className="tm-scrub-thumb" style={{ top: thumbTop }} />
    </div>
  )
}
