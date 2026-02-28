import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import DayplannerPage from '../features/dayplanner/DayplannerPage'
import PlaygroundPage from '../features/playground/PlaygroundPage'

export default function Router() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/dayplanner" replace />} />
        <Route path="/dayplanner" element={<DayplannerPage />} />
        <Route path="/playground" element={<PlaygroundPage />} />
      </Routes>
    </BrowserRouter>
  )
}
