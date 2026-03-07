import type { MergedEvent } from '../../../models/event'

interface EventListProps {
  events: MergedEvent[]
  loading: boolean
  selectedEvent: MergedEvent | null
  onSelect: (event: MergedEvent) => void
}

export default function EventList({ events, loading, selectedEvent, onSelect }: EventListProps) {
  return (
    <div>
      <div className="p-3 border-b border-gray-100">
        <h2 className="text-sm font-semibold text-gray-500 uppercase">Events</h2>
      </div>
      {loading ? (
        <div className="flex items-center justify-center py-8">
          <svg className="animate-spin h-5 w-5 text-gray-400" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
        </div>
      ) : events.filter(e => e.type !== 'transit').length === 0 ? (
        <p className="p-3 text-sm text-gray-400">No events</p>
      ) : (
        events.filter(e => e.type !== 'transit').map((event) => (
          <button
            key={event.id}
            onClick={() => onSelect(event)}
            className={`w-full text-left px-3 py-2 border-b border-gray-50 hover:bg-gray-50 ${
              selectedEvent?.id === event.id ? 'bg-blue-50 border-l-2 border-l-blue-500' : ''
            }`}
          >
            <p className="text-sm font-medium text-gray-900 truncate">{event.name}</p>
            <p className="text-xs text-gray-400">{event.type}</p>
          </button>
        ))
      )}
    </div>
  )
}
