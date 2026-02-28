interface DayHeaderProps {
  date: string
  totalTokens: number
}

export default function DayHeader({ date, totalTokens }: DayHeaderProps) {
  const d = new Date(date + 'T00:00:00')
  const formatted = d.toLocaleDateString('en-US', {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })

  return (
    <div className="px-4 py-3 border-b border-gray-200 bg-white">
      <h1 className="text-lg font-semibold text-gray-900">{formatted}</h1>
      {totalTokens > 0 && (
        <p className="text-sm text-gray-500 mt-0.5">
          +{totalTokens} tokens
        </p>
      )}
    </div>
  )
}
