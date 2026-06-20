import { useQuery } from '@tanstack/react-query'
import { api } from '../../services/api'
import NoteFeed from './components/NoteFeed'
import FeaturedNote from './components/FeaturedNote'
import './theme.css'

export default function TimeManagementPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['notes-list'],
    queryFn: () => api.listNotes(),
  })

  return (
    <div className="tm-root">
      <div className="tm-content">
        <header className="tm-top">
          <span className="tm-display tm-brand">Time</span>
        </header>
        {isLoading && <div className="tm-state">Loading…</div>}
        {error && <div className="tm-state tm-error">Couldn’t load notes.</div>}
        {data && (
          <>
            <FeaturedNote />
            <NoteFeed items={data.notes} />
          </>
        )}
      </div>
    </div>
  )
}
