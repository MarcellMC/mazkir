import { useEffect } from 'react'
import { useDayplannerStore } from './store'
import DayHeader from './components/DayHeader'
import Timeline from './components/Timeline'

export default function DayplannerPage() {
  const { date, events, totalTokens, loading, error, fetchDay } =
    useDayplannerStore()

  useEffect(() => {
    fetchDay(date)
  }, [date, fetchDay])

  return (
    <div className="min-h-screen bg-gray-50">
      <DayHeader date={date} totalTokens={totalTokens} />

      {loading && (
        <div className="p-8 text-center text-gray-400">Loading...</div>
      )}

      {error && (
        <div className="p-4 m-4 bg-red-50 text-red-700 rounded-lg text-sm">
          {error}
        </div>
      )}

      {!loading && !error && <Timeline events={events} />}
    </div>
  )
}
