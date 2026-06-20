import '@testing-library/jest-dom'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import NoteMarkdown from '../components/NoteMarkdown'

describe('NoteMarkdown', () => {
  it('renders prose and a wikilink chip', () => {
    render(<NoteMarkdown noteId="2026-05-21" markdown="Hi [[Mount Carmel]]" onToggle={() => {}} />)
    const chip = screen.getByText('Mount Carmel')
    expect(chip).toBeInTheDocument()
    expect(chip).toHaveClass('tm-wikilink')
  })

  it('renders an image embed as an img with the media url', () => {
    render(<NoteMarkdown noteId="2026-05-21" markdown="![[photo_2026-05-21.jpg]]" onToggle={() => {}} />)
    const img = screen.getByRole('img') as HTMLImageElement
    expect(img.src).toContain('/media/2026-05-21/photo_2026-05-21.jpg')
  })

  it('fires onToggle with the source line when a single-line checkbox is clicked', () => {
    const onToggle = vi.fn()
    // line 1 = "## Tasks", line 2 = the checkbox
    render(<NoteMarkdown noteId="2026-05-21" markdown={'## Tasks\n- [ ] Pack cooler'} onToggle={onToggle} />)
    fireEvent.click(screen.getByRole('checkbox'))
    expect(onToggle).toHaveBeenCalledWith(2, true)
  })

  it('maps the correct source line for a checkbox lower in the body', () => {
    const onToggle = vi.fn()
    // 1: "## Tasks", 2: "- [ ] A", 3: "- [ ] B"
    render(<NoteMarkdown noteId="2026-05-21" markdown={'## Tasks\n- [ ] A\n- [ ] B'} onToggle={onToggle} />)
    const boxes = screen.getAllByRole('checkbox')
    fireEvent.click(boxes[1]) // second checkbox → source line 3
    expect(onToggle).toHaveBeenCalledWith(3, true)
  })

  it('keeps real markdown links as navigable anchors, not wikilink chips', () => {
    render(<NoteMarkdown noteId="2026-05-21" markdown="[docs](https://example.com)" onToggle={() => {}} />)
    const link = screen.getByRole('link')
    expect(link).toHaveAttribute('href', 'https://example.com')
    expect(link).not.toHaveClass('tm-wikilink')
  })
})
