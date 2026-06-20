import { useQuery } from '@tanstack/react-query'
import { api } from '../../../services/api'
import type { NoteListItem } from '../../../models/note'
import NoteMarkdown from './NoteMarkdown'

const DOW = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
const MON = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']

export function headerParts(item: Pick<NoteListItem, 'id' | 'kind' | 'sort_key'>) {
  const d = new Date(item.sort_key + 'T00:00:00Z')
  if (item.kind === 'weekly') {
    const week = item.id.split('-W')[1] ?? ''
    return {
      dow: `Week ${parseInt(week, 10)}`,
      sub: `ENDS ${d.getUTCDate()} ${MON[d.getUTCMonth()]} ${d.getUTCFullYear()}`,
    }
  }
  return {
    dow: DOW[d.getUTCDay()],
    sub: `${d.getUTCDate()} ${MON[d.getUTCMonth()]} ${d.getUTCFullYear()}`,
  }
}

interface Props {
  item: NoteListItem
  onMeasure?: (el: HTMLElement | null) => void
  onToggle?: (line: number, checked: boolean) => void
}

export default function NoteDay({ item, onMeasure, onToggle }: Props) {
  const { data } = useQuery({
    queryKey: ['note', item.id],
    queryFn: () => api.getNote(item.id),
  })
  const h = headerParts(item)

  return (
    <div ref={onMeasure} data-note-id={item.id}>
      <div className="tm-day-hd">
        <span className="tm-display tm-dow">{h.dow}</span>
        <span className="tm-mono">{h.sub}</span>
      </div>
      <div className="tm-day-bd">
        {data
          ? <NoteMarkdown noteId={item.id} markdown={data.markdown} onToggle={onToggle ?? (() => {})} />
          : <div className="tm-skeleton" style={{ height: 120 }} />}
      </div>
    </div>
  )
}
