import '@testing-library/jest-dom'
import { describe, it, expect, vi, beforeEach, beforeAll, afterAll } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import TimeManagementPage from '../TimeManagementPage'
import { api } from '../../../services/api'

beforeEach(() => {
  vi.spyOn(api, 'listNotes').mockResolvedValue({ notes: [
    { id: '2026-05-21', sort_key: '2026-05-21', kind: 'daily', title: 'Thu', has_photos: false, snippet: 's' },
  ] })
  vi.spyOn(api, 'getNote').mockResolvedValue({ id: '2026-05-21', kind: 'daily', sort_key: '2026-05-21', frontmatter: {}, markdown: '## Notes\nhi' })
  vi.spyOn(api, 'getFeaturedNote').mockRejectedValue(new Error('none'))
})

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

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><TimeManagementPage /></QueryClientProvider>)
}

describe('TimeManagementPage', () => {
  it('loads the notes list and renders the brand + a day', async () => {
    wrap()
    expect(screen.getByText('Time')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('Thursday')).toBeInTheDocument())
  })
})
