import { create } from 'zustand'
import type { MergedEvent, MergedEventsResponse } from '../../models/event'
import { api } from '../../services/api'

interface DayplannerState {
  date: string
  events: MergedEvent[]
  totalTokens: number
  loading: boolean
  error: string | null
  setDate: (date: string) => void
  fetchDay: (date: string) => Promise<void>
}

function todayISO(): string {
  return new Date().toISOString().split('T')[0]
}

export const useDayplannerStore = create<DayplannerState>((set) => ({
  date: todayISO(),
  events: [],
  totalTokens: 0,
  loading: false,
  error: null,

  setDate: (date) => set({ date }),

  fetchDay: async (date) => {
    set({ loading: true, error: null })
    try {
      const data: MergedEventsResponse = await api.getEvents(date)
      set({
        events: data.events,
        totalTokens: data.summary.total_tokens,
        loading: false,
      })
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'Failed to load',
        loading: false,
      })
    }
  },
}))
