interface DayHeaderProps {
  totalTokens: number
}

export default function DayHeader({ totalTokens }: DayHeaderProps) {
  if (totalTokens <= 0) return null
  return (
    <div className="px-4 py-1 bg-white border-b border-gray-100">
      <p className="text-sm text-gray-500">+{totalTokens} tokens</p>
    </div>
  )
}
