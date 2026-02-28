import type { MergedEvent } from '../../../models/event'
import EventCard from './EventCard'

interface TimelineProps {
  events: MergedEvent[]
}

export default function Timeline({ events }: TimelineProps) {
  if (events.length === 0) {
    return (
      <div className="p-8 text-center text-gray-400">
        <p>No events for this day</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2 p-4">
      {events.map((event) => (
        <EventCard key={event.id} event={event} />
      ))}
    </div>
  )
}
