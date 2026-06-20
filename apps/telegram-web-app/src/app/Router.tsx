import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import TimeManagementPage from '../features/time-management/TimeManagementPage'
import PlaygroundPage from '../features/playground/PlaygroundPage'

export default function Router() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/time-management" replace />} />
        <Route path="/time-management" element={<TimeManagementPage />} />
        <Route path="/dayplanner" element={<Navigate to="/time-management" replace />} />
        <Route path="/playground" element={<PlaygroundPage />} />
      </Routes>
    </BrowserRouter>
  )
}
