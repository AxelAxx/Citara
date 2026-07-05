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
 * Load the configured Verticals plus each one's live corpus stats. Any
 * failure (API down, empty corpus, store unreachable) surfaces as `error`
 * instead of a partial list — a card with a made-up count would hide the
 * actual problem (fail fast, loud).
 */
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
        const views = await getVerticals()
        const loaded = await Promise.all(
          views.map(async (view) => {
            const stats = await getCorpus(view.id)
            return {
              view,
              documentCount: stats.document_count,
              chunkCount: stats.chunk_count,
            }
          }),
        )
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
