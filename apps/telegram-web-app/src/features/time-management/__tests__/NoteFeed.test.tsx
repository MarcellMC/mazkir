import '@testing-library/jest-dom'
import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import NoteFeed from '../components/NoteFeed'
import type { NoteListItem } from '../../../models/note'

const items: NoteListItem[] = [
  { id: '2026-05-21', sort_key: '2026-05-21', kind: 'daily', title: 'Thu', has_photos: false, snippet: 'kebabs' },
]

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient()
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

// jsdom gives every element offsetWidth/offsetHeight of 0, so TanStack's
// virtualizer (which reads element.offsetHeight to size the scroll viewport)
// computes an empty visible range and renders no rows. Stub a non-zero layout
// so the virtualizer has a viewport to fill — this only affects layout
// measurement, not the rendered header text being asserted below.
const origW = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetWidth')
const origH = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetHeight')
beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, 'offsetWidth', { configurable: true, get: () => 360 })
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { configurable: true, get: () => 800 })
})
afterAll(() => {
  if (origW) Object.defineProperty(HTMLElement.prototype, 'offsetWidth', origW)
  if (origH) Object.defineProperty(HTMLElement.prototype, 'offsetHeight', origH)
})

describe('NoteFeed', () => {
  it('renders a day header for each list item', () => {
    wrap(<NoteFeed items={items} />)
    expect(screen.getByText('Thursday')).toBeInTheDocument()
  })
})
