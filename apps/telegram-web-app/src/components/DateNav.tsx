interface DateNavProps {
  date: string
  onChange: (date: string) => void
}

function shiftDate(date: string, days: number): string {
  const d = new Date(date + 'T00:00:00')
  d.setDate(d.getDate() + days)
  return d.toISOString().split('T')[0]!
}

export default function DateNav({ date, onChange }: DateNavProps) {
  return (
    <div className="flex items-center gap-2 px-4 py-2 bg-white border-b border-gray-200">
      <button
        onClick={() => onChange(shiftDate(date, -1))}
        className="px-2 py-1 text-gray-500 hover:text-gray-900 hover:bg-gray-100 rounded"
      >
        &lt;
      </button>
      <input
        type="date"
        value={date}
        onChange={(e) => onChange(e.target.value)}
        className="flex-1 text-center text-sm font-medium bg-transparent border-none outline-none"
      />
      <button
        onClick={() => onChange(shiftDate(date, 1))}
        className="px-2 py-1 text-gray-500 hover:text-gray-900 hover:bg-gray-100 rounded"
      >
        &gt;
      </button>
    </div>
  )
}
