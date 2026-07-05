import { useEffect, useState } from 'react'
import { getHealth } from '../api/client'
import type { Health } from '../api/client'

interface UseHealthResult {
  health: Health | null
  loading: boolean
  error: string | null
}

/**
 * Load /health once (llm_model for the version pill, and later the sidebar
 * badge). getHealth resolves for ok:false bodies too — those carry their own
 * actionable error_code/message — so `error` here is transport-level only
 * (API process unreachable).
 */
export function useHealth(): UseHealthResult {
  const [health, setHealth] = useState<Health | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const body = await getHealth()
        if (!cancelled) setHealth(body)
      } catch (err) {
        if (!cancelled)
          setError(err instanceof Error ? err.message : String(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  return { health, loading, error }
}
