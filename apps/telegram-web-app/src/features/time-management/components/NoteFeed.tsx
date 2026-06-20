import { useMemo, useRef, useState, useEffect } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { NoteListItem, NoteDetail } from '../../../models/note'
import { api } from '../../../services/api'
import { fractionToIndex } from '../scrubber'
import NoteDay from './NoteDay'
import DateScrubber from './DateScrubber'
import BackToTopFab from './BackToTopFab'

interface Props { items: NoteListItem[] }

export default function NoteFeed({ items }: Props) {
  const parentRef = useRef<HTMLDivElement>(null)
  const qc = useQueryClient()
  const keys = useMemo(() => items.map((i) => i.sort_key), [items])
  const [activeIndex, setActiveIndex] = useState(0)
  const [showFab, setShowFab] = useState(false)

  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 280,
    overscan: 4,
  })

  const checkbox = useMutation({
    mutationFn: ({ id, line, checked }: { id: string; line: number; checked: boolean }) =>
      api.setNoteCheckbox(id, line, checked),
    onSuccess: (note: NoteDetail) => {
      qc.setQueryData(['note', note.id], note)
    },
  })

  useEffect(() => {
    const el = parentRef.current
    if (!el) return
    const onScroll = () => {
      setShowFab(el.scrollTop > 600)
      const first = virtualizer.getVirtualItems()[0]
      if (first) setActiveIndex(first.index)
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [virtualizer])

  function seek(fraction: number) {
    virtualizer.scrollToIndex(fractionToIndex(fraction, keys), { align: 'start' })
  }

  return (
    <div className="tm-feed-wrap">
      <div ref={parentRef} className="tm-scroll">
        <div style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
          {virtualizer.getVirtualItems().map((v) => {
            const item = items[v.index]!
            return (
              <div
                key={item.id}
                style={{ position: 'absolute', top: 0, left: 0, width: '100%', transform: `translateY(${v.start}px)` }}
              >
                <NoteDayRow item={item} measureElement={virtualizer.measureElement} index={v.index} onToggle={checkbox.mutate} />
              </div>
            )
          })}
        </div>
      </div>
      <DateScrubber keys={keys} activeIndex={activeIndex} onSeek={seek} />
      <BackToTopFab visible={showFab} onClick={() => virtualizer.scrollToIndex(0)} />
    </div>
  )
}

// Bridges NoteDay's onToggle to the mutation, binding the note id.
function NoteDayRow({ item, measureElement, index, onToggle }: {
  item: NoteListItem
  measureElement: (el: Element | null) => void
  index: number
  onToggle: (v: { id: string; line: number; checked: boolean }) => void
}) {
  return (
    <NoteDay
      item={item}
      onMeasure={(el) => {
        if (el) {
          el.setAttribute('data-index', String(index))
          measureElement(el)
        }
      }}
      onToggle={(line, checked) => onToggle({ id: item.id, line, checked })}
    />
  )
}
