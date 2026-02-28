import type { MergedEvent } from '../../../models/event'

interface EventListProps {
  events: MergedEvent[]
  selectedEvent: MergedEvent | null
  onSelect: (event: MergedEvent) => void
}

export default function EventList({ events, selectedEvent, onSelect }: EventListProps) {
  return (
    <div className="border-r border-gray-200 overflow-y-auto">
      <div className="p-3 border-b border-gray-100">
        <h2 className="text-sm font-semibold text-gray-500 uppercase">Events</h2>
      </div>
      {events.filter(e => e.type !== 'transit').map((event) => (
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
      ))}
    </div>
  )
}
