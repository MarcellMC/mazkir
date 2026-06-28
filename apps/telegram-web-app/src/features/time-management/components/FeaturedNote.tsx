import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../../services/api'
import NoteMarkdown from './NoteMarkdown'

export default function FeaturedNote() {
  const [dismissed, setDismissed] = useState(false)
  const { data } = useQuery({
    queryKey: ['featured-note'],
    queryFn: () => api.getFeaturedNote(),
    retry: false,
  })
  if (!data || dismissed) return null
  return (
    <div className="tm-featured">
      <button
        className="tm-featured-close"
        aria-label="Dismiss"
        onClick={() => setDismissed(true)}
      >
        ×
      </button>
      <div className="tm-mono tm-featured-when">— from your notes</div>
      <div className="tm-display tm-featured-title">{data.title}</div>
      <NoteMarkdown noteId={data.id} markdown={data.markdown} onToggle={() => {}} />
    </div>
  )
}
