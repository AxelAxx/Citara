import { useEffect, useState } from 'react'
import { getCorpus, getVerticals } from '../api/client'
import type { VerticalView } from '../api/client'

export interface VerticalCorpus {
  view: VerticalView
  /** Real ingested-corpus stats from /corpus — mock numbers never ship. */
  documentCount: number
  chunkCount: number
}

interface UseVerticalsResult {
  verticals: VerticalCorpus[]
  loading: boolean
  error: string | null
}

/**
 * One fetch plan shared by this hook and the warm-up gate (useEngineReady):
 * every Vertical plus its live corpus stats, corpus calls in parallel. Any
 * failure rejects the whole load — a card with a made-up count would hide
 * the actual problem (fail fast, loud).
 */
export async function loadVerticalCorpora(): Promise<VerticalCorpus[]> {
  const views = await getVerticals()
  return Promise.all(
    views.map(async (view) => {
      const stats = await getCorpus(view.id)
      return {
        view,
        documentCount: stats.document_count,
        chunkCount: stats.chunk_count,
      }
    }),
  )
}

/** React-state wrapper over loadVerticalCorpora for screens that mount cold. */
export function useVerticals(): UseVerticalsResult {
  const [verticals, setVerticals] = useState<VerticalCorpus[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // StrictMode double-mounts effects in dev; the flag keeps the unmounted
    // run's responses from landing in state.
    let cancelled = false
    ;(async () => {
      try {
        const loaded = await loadVerticalCorpora()
        if (!cancelled) setVerticals(loaded)
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

  return { verticals, loading, error }
}
