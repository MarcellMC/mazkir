import { useEffect } from 'react'
import { usePlaygroundStore } from './store'
import EventList from './components/EventList'
import GenerationPanel from './components/GenerationPanel'
import DateNav from '../../components/DateNav'

export default function PlaygroundPage() {
  const store = usePlaygroundStore()

  useEffect(() => {
    store.loadEvents(store.date)
  }, [])

  return (
    <div className="h-screen flex flex-col bg-gray-50">
      <div className="px-4 py-3 border-b border-gray-200 bg-white">
        <h1 className="text-lg font-semibold">Asset Generation Playground</h1>
      </div>

      <DateNav date={store.date} onChange={store.setDate} />

      <div className="flex-1 flex overflow-hidden">
        <div className="w-1/3 min-w-[140px] max-w-[200px]">
          <EventList
            events={store.events}
            selectedEvent={store.selectedEvent}
            onSelect={store.selectEvent}
          />
        </div>
        <div className="flex-1">
          <GenerationPanel
            selectedEvent={store.selectedEvent}
            genType={store.genType}
            approach={store.approach}
            style={store.style}
            generating={store.generating}
            result={store.result}
            promptOverride={store.promptOverride}
            width={store.width}
            height={store.height}
            aspectRatio={store.aspectRatio}
            onGenTypeChange={store.setGenType}
            onApproachChange={store.setApproach}
            onStyleChange={store.setStyle}
            onGenerate={store.generate}
            onPromptOverrideChange={store.setPromptOverride}
            onAspectRatioChange={store.setAspectRatio}
            onCustomDimensionsChange={store.setCustomDimensions}
          />
        </div>
      </div>
    </div>
  )
}
