import { useEffect, useMemo } from 'react'
import { usePlaygroundStore } from './store'
import EventList from './components/EventList'
import GenerationPanel from './components/GenerationPanel'
import DateNav from '../../components/DateNav'
import { api } from '../../services/api'

export default function PlaygroundPage() {
  const store = usePlaygroundStore()

  useEffect(() => {
    store.loadEvents(store.date)
  }, [])

  const eventPhotos = useMemo(() => {
    const photos = store.selectedEvent?.photos || []
    return photos.map((p: { path: string }) => {
      const filename = p.path.split('/').pop() || ''
      return {
        path: p.path,
        previewUrl: api.getMediaUrl(store.date, filename),
      }
    })
  }, [store.selectedEvent, store.date])

  return (
    <div className="h-screen flex flex-col bg-gray-50">
      <div className="w-full max-w-4xl mx-auto flex flex-col flex-1 min-h-0">
        <div className="px-4 py-3 border-b border-gray-200 bg-white">
          <h1 className="text-lg font-semibold">Asset Generation Playground</h1>
        </div>

        <DateNav date={store.date} onChange={store.setDate} />

        <div className="flex-1 flex min-h-0">
          <div className="w-1/3 min-w-[140px] max-w-[200px] overflow-y-auto border-r border-gray-200">
            <EventList
              events={store.events}
              loading={store.loadingEvents}
              selectedEvent={store.selectedEvent}
              onSelect={store.selectEvent}
            />
          </div>
          <div className="flex-1 overflow-y-auto">
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
              referenceImage={store.referenceImage}
              referenceImagePreview={store.referenceImagePreview}
              promptStrength={store.promptStrength}
              uploadingReference={store.uploadingReference}
              eventPhotos={eventPhotos}
              onSetReferenceImage={store.setReferenceImage}
              onClearReferenceImage={store.clearReferenceImage}
              onPromptStrengthChange={store.setPromptStrength}
              onUploadReferenceImage={store.uploadReferenceImage}
            />
          </div>
        </div>
      </div>
    </div>
  )
}
