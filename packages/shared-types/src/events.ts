export interface PhotoRef {
  path: string
  caption?: string
  wikilinks: string[]
}

export interface MergedEvent {
  id: string

  // What
  name: string
  type: 'habit' | 'task' | 'calendar' | 'unplanned_stop' | 'transit' | 'home'
  activity: string | null
  category: string | null
  tags: string[]
  state: 'suggested' | 'approved'

  // When
  start_time: string
  end_time: string
  duration_minutes: number

  // Where
  location?: {
    name: string
    lat: number
    lng: number
    place_id?: string
  }

  // How you got there
  route_from?: {
    mode: 'walking' | 'driving' | 'transit' | 'cycling' | 'unknown'
    distance_meters: number
    duration_minutes: number
    polyline: [number, number][]
    confidence: 'high' | 'medium' | 'low'
  }

  // PKM integration
  habit?: {
    name: string
    completed: boolean
    streak: number
    tokens_earned: number
  }
  tokens_earned: number

  // Whether the thing this event stands for is done — a checked checkbox, a
  // calendar event the sync marked complete, a habit whose target was met.
  // Optional because events persisted before it existed carry it only
  // inside `habit`.
  completed?: boolean

  // Photos
  photos: PhotoRef[]

  // Generated assets
  assets?: {
    micro_icon?: string
    keyframe_scene?: string
    route_sketch?: string
    context_image?: string
  }

  // Source tracking
  source: 'calendar' | 'timeline' | 'merged' | 'manual' | 'photo'
  source_ids?: {
    calendar_id?: string
    timeline_place_id?: string
  }
  confidence: 'high' | 'medium' | 'low'
}

export interface MergedEventsResponse {
  date: string
  events: MergedEvent[]
  summary: {
    total_events: number
    total_tokens: number
  }
}
