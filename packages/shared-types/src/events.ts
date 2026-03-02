export interface MergedEvent {
  id: string

  // What
  name: string
  type: 'habit' | 'task' | 'calendar' | 'unplanned_stop' | 'transit' | 'home'
  activity_category?: string

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

  // Generated assets
  assets?: {
    micro_icon?: string
    keyframe_scene?: string
    route_sketch?: string
    context_image?: string
  }

  // Data quality
  source: 'calendar' | 'timeline' | 'merged'
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
