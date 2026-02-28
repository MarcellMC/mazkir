import { useEffect } from 'react'
import Router from './app/Router'
import { initTelegram } from './app/telegram'

function App() {
  useEffect(() => {
    try {
      initTelegram()
    } catch {
      // Not running inside Telegram — dev mode
    }
  }, [])

  return <Router />
}

export default App
