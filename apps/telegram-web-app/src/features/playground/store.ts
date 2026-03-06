import { create } from 'zustand'
import type { MergedEvent } from '../../models/event'
import type { GenerateRequest, GenerateResponse } from '../../services/api'
import { api } from '../../services/api'

interface PlaygroundState {
  // Date + Event selection
  date: string
  events: MergedEvent[]
  selectedEvent: MergedEvent | null
  loadingEvents: boolean

  // Generation
  generating: boolean
  result: GenerateResponse | null
  history: GenerateResponse[]

  // Config
  genType: GenerateRequest['type']
  approach: string
  style: GenerateRequest['style']

  // Actions
  setDate: (date: string) => void
  loadEvents: (date: string) => Promise<void>
  selectEvent: (event: MergedEvent | null) => void
  setGenType: (type: GenerateRequest['type']) => void
  setApproach: (approach: string) => void
  setStyle: (style: GenerateRequest['style']) => void
  generate: () => Promise<void>
}

export const usePlaygroundStore = create<PlaygroundState>((set, get) => ({
  date: new Date().toISOString().split('T')[0]!,
  events: [],
  selectedEvent: null,
  loadingEvents: false,

  generating: false,
  result: null,
  history: [],

  genType: 'micro_icon',
  approach: 'ai_raster',
  style: { line_style: 'clean_vector', texture: 'clean' },

  setDate: (date) => {
    set({ date })
    get().loadEvents(date)
  },

  loadEvents: async (date) => {
    set({ loadingEvents: true })
    try {
      const data = await api.getEvents(date)
      set({ events: data.events, loadingEvents: false })
    } catch {
      set({ loadingEvents: false })
    }
  },

  selectEvent: (event) => set({ selectedEvent: event }),
  setGenType: (type) => set({ genType: type }),
  setApproach: (approach) => set({ approach }),
  setStyle: (style) => set({ style }),

  generate: async () => {
    const { selectedEvent, genType, approach, style } = get()
    if (!selectedEvent) return

    set({ generating: true })
    try {
      const result = await api.generate({
        type: genType,
        event_name: selectedEvent.name,
        activity_category: selectedEvent.activity_category || undefined,
        location_name: selectedEvent.location?.name,
        style,
        approach,
      })
      set((state) => ({
        result,
        history: [result, ...state.history],
        generating: false,
      }))
    } catch {
      set({ generating: false })
    }
  },
}))
