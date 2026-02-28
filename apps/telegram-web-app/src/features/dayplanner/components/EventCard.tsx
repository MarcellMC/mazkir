import type { MergedEvent } from '../../../models/event'

const TYPE_STYLES: Record<string, string> = {
  habit: 'border-l-green-500',
  calendar: 'border-l-blue-500',
  unplanned_stop: 'border-l-yellow-500',
  transit: 'border-l-gray-300',
  home: 'border-l-purple-300',
  task: 'border-l-orange-500',
}

const CATEGORY_ICONS: Record<string, string> = {
  gym: '\uD83D\uDCAA',
  walk: '\uD83D\uDEB6',
  cafe: '\u2615',
  shopping: '\uD83D\uDED2',
  work: '\uD83D\uDCBB',
  social: '\uD83C\uDF89',
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    })
  } catch {
    return ''
  }
}

function formatDuration(minutes: number): string {
  if (minutes < 60) return `${minutes}min`
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return m > 0 ? `${h}h ${m}min` : `${h}h`
}

interface EventCardProps {
  event: MergedEvent
}

export default function EventCard({ event }: EventCardProps) {
  if (event.type === 'transit') {
    return <TransitCard event={event} />
  }

  const icon = event.activity_category
    ? CATEGORY_ICONS[event.activity_category] || ''
    : ''
  const borderColor = TYPE_STYLES[event.type] || 'border-l-gray-400'

  return (
    <div className={`bg-white rounded-lg border-l-4 ${borderColor} p-3 shadow-sm`}>
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-gray-400">
              {formatTime(event.start_time)}
            </span>
            {icon && <span>{icon}</span>}
            <span className="font-medium text-gray-900">{event.name}</span>
          </div>

          {event.location && (
            <p className="text-sm text-gray-500 mt-1">
              {event.location.name}
            </p>
          )}

          {event.duration_minutes > 0 && (
            <p className="text-xs text-gray-400 mt-0.5">
              {formatDuration(event.duration_minutes)}
            </p>
          )}
        </div>

        {event.habit && (
          <div className="text-right flex-shrink-0 ml-2">
            {event.habit.completed && (
              <span className="text-green-600 text-sm font-medium">
                +{event.tokens_earned}
              </span>
            )}
            {event.habit.streak > 0 && (
              <p className="text-xs text-gray-400">
                streak: {event.habit.streak}
              </p>
            )}
          </div>
        )}
      </div>

      {event.route_from && event.type !== 'transit' && (
        <div className="mt-2 text-xs text-gray-400 flex items-center gap-1">
          <span>{event.route_from.mode}</span>
          <span>{'\u00B7'}</span>
          <span>{formatDuration(event.route_from.duration_minutes)}</span>
          {event.route_from.distance_meters > 0 && (
            <>
              <span>{'\u00B7'}</span>
              <span>{(event.route_from.distance_meters / 1000).toFixed(1)}km</span>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function TransitCard({ event }: EventCardProps) {
  const route = event.route_from
  if (!route) return null

  return (
    <div className="flex items-center gap-2 py-1 px-3 text-xs text-gray-400">
      <div className="w-px h-4 bg-gray-200" />
      <span>{route.mode}</span>
      <span>{'\u00B7'}</span>
      <span>{formatDuration(route.duration_minutes)}</span>
      {route.distance_meters > 0 && (
        <>
          <span>{'\u00B7'}</span>
          <span>{(route.distance_meters / 1000).toFixed(1)}km</span>
        </>
      )}
    </div>
  )
}
