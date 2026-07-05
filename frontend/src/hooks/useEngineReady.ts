import { useEffect, useState } from 'react'
import { getHealth } from '../api/client'
import type { Health } from '../api/client'
import { loadVerticalCorpora } from './useVerticals'
import type { VerticalCorpus } from './useVerticals'

/** Everything Chat needs to paint its first frame — no fetch on mount. */
export interface EnginePreload {
  health: Health
  verticals: VerticalCorpus[]
}

interface UseEngineReadyResult {
  ready: boolean
  /** Non-null exactly when ready — handed to Chat so it never refetches. */
  preload: EnginePreload | null
  error: string | null
}

/**
 * Gates the welcome→chat hand-off on warm-up AND data. GET /health builds
 * the engine server-side (get_engine → warm-up + both preflights), so that
 * request IS the warm-up; verticals + corpus stats load in parallel with it
 * so the chat's header, sidebar and empty-state paint on their first frame
 * instead of flashing empty. ok:false (Ollama down, model not pulled) or a
 * failed load surfaces its actionable message instead of spinning forever.
 */
export function useEngineReady(verticalId: string): UseEngineReadyResult {
  const [preload, setPreload] = useState<EnginePreload | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setPreload(null)
    setError(null)
    ;(async () => {
      try {
        const [health, verticals] = await Promise.all([
          getHealth(),
          loadVerticalCorpora(),
        ])
        if (cancelled) return
        if (!health.ok) {
          setError(health.message)
          return
        }
        setPreload({ health, verticals })
      } catch (err) {
        // Transport failure: the API process itself is unreachable.
        if (!cancelled)
          setError(err instanceof Error ? err.message : String(err))
      }
    })()
    return () => {
      cancelled = true
    }
    // verticalId dep: /api/health is vertical-independent today (the
    // preflight is model-level), but re-entering the gate with another
    // vertical must re-check rather than trust a stale result.
  }, [verticalId])

  return { ready: preload !== null, preload, error }
}
