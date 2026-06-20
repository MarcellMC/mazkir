import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import DateScrubber from '../components/DateScrubber'

describe('DateScrubber', () => {
  it('calls onSeek with a fraction when the track is pointer-dragged', () => {
    const onSeek = vi.fn()
    const { container } = render(
      <DateScrubber keys={['2026-05-21', '2026-05-20']} activeIndex={0} onSeek={onSeek} />,
    )
    const track = container.querySelector('[data-testid="scrub-track"]') as HTMLElement
    // jsdom gives 0-size rects; stub a height so fraction math runs.
    track.getBoundingClientRect = () => ({ top: 0, height: 100, left: 0, width: 10, right: 10, bottom: 100, x: 0, y: 0, toJSON: () => {} })
    track.dispatchEvent(new MouseEvent('pointerdown', { clientY: 50, bubbles: true }))
    expect(onSeek).toHaveBeenCalledWith(0.5)
  })
})
