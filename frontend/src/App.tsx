import { useEffect, useState } from 'react'
import './App.css'

type HealthStatus = 'loading' | 'ok' | 'error'

function App() {
  const [status, setStatus] = useState<HealthStatus>('loading')

  useEffect(() => {
    let cancelled = false

    async function checkHealth() {
      try {
        const response = await fetch('/api/health')
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`)
        }
        const data: unknown = await response.json()
        if (
          !cancelled &&
          typeof data === 'object' &&
          data !== null &&
          'status' in data &&
          (data as { status: unknown }).status === 'ok'
        ) {
          setStatus('ok')
        } else if (!cancelled) {
          setStatus('error')
        }
      } catch {
        if (!cancelled) {
          setStatus('error')
        }
      }
    }

    void checkHealth()
    return () => {
      cancelled = true
    }
  }, [])

  const statusLabel =
    status === 'loading' ? 'loading' : status === 'ok' ? 'ok' : 'error'

  return (
    <main className="app">
      <h1>Pioneers Price Updater</h1>
      <p className="subtitle">GheymatYar</p>
      <p className={`status status-${status}`} aria-live="polite">
        Backend status: <strong>{statusLabel}</strong>
      </p>
    </main>
  )
}

export default App
