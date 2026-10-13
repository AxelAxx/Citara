import { useEffect, useRef, useState } from 'react'
import { RECOVERABLE_ERROR_CODES, streamQuery } from '../api/client'
import type { AnswerPart, Citation, ErrorEvent } from '../api/client'
import { useDialog } from './useDialog'

/**
 * Assistant lifecycle: 'thinking' from send until the first token (retrieval
 * + prompt eval), 'writing' while tokens stream, 'anchoring' when the token
 * stream has gone quiet but done hasn't arrived (the structured citation
 * pass runs server-side over the full text — a real ~4-5s gap), then
 * 'done' | 'error'. User messages are born 'done'.
 */
export type MessagePhase = 'thinking' | 'writing' | 'anchoring' | 'done' | 'error'

// How long the token stream must be silent (while 'writing') before we call
// it 'anchoring'. This is DETECTION, not an artificial delay: the SSE has no
// end-of-tokens event, so silence is the only client-side signal. In
// off/abstention mode done arrives in the same tick as the last token, so
// this timer never fires and no effect is shown; in structured mode the
// anchor pass gap is seconds long, far past this threshold. Trade-off: a slow
// LLM pausing longer than this mid-write flips to 'anchoring' briefly — the
// next token flips it right back (self-correcting).
const ANCHORING_SILENCE_MS = 700

export interface Message {
  role: 'user' | 'assistant'
  text: string
  citations: Citation[]
  /** Typed view of the final text, from the done event (core's parser). null
      until done arrives — while streaming only the raw `text` exists. */
  parts: AnswerPart[] | null
  isAbstention: boolean
  suppressCitations: boolean
  streaming: boolean
  phase: MessagePhase
  /** Set when the stream failed; the text may be partial. */
  error: string | null
}

interface UseChatResult {
  messages: Message[]
  send: (query: string) => Promise<void>
  isStreaming: boolean
}

function emptyAssistant(): Message {
  return {
    role: 'assistant',
    text: '',
    citations: [],
    parts: null,
    isAbstention: false,
    suppressCitations: false,
    streaming: true,
    phase: 'thinking',
    error: null,
  }
}

/**
 * Isolates the SSE query stream (api/client streamQuery) behind chat state.
 * Contract order citations → token* → done|error maps onto ONE assistant
 * message appended per send; every handler patches that last message, so
 * tokens render incrementally as they arrive.
 */
export function useChat(verticalId: string): UseChatResult {
  const [messages, setMessages] = useState<Message[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  // App-wide dialog seam: surfaces recoverable backend failures (Ollama down,
  // model not pulled…) as the amber retry dialog. Requires DialogProvider
  // above (App.tsx) — useDialog fails loudly otherwise.
  const dialog = useDialog()
  // The in-flight stream's controller — null when nothing is streaming.
  const abortRef = useRef<AbortController | null>(null)
  // Monotonic thread id, bumped on every vertical switch. A send belongs to
  // the thread it started in; after a reset its late callbacks (the abort
  // rejection, the finally) must not touch the fresh thread's state.
  const threadRef = useRef(0)

  // Switching verticals resets the conversation: the transcript belongs to
  // the vertical it was grounded in, and letting an in-flight legal answer
  // land in the fresh health thread would mix corpora in one thread (bug d).
  // Cancel first, then wipe. Runs on mount too — aborting nothing and
  // emptying an empty list are both no-ops, so no first-run guard is needed.
  useEffect(() => {
    threadRef.current += 1
    abortRef.current?.abort() // no-op guard: null when no stream is in flight
    abortRef.current = null
    setMessages([])
    // Re-enable the composer immediately; the aborted send's own finally is
    // thread-guarded and won't race a query already started here.
    setIsStreaming(false)
  }, [verticalId])

  // Functional updates throughout: token events arrive faster than renders,
  // and reading `messages` from the closure would drop tokens.
  const patchLast = (patch: (message: Message) => Message) => {
    setMessages((prev) => {
      // A reset may have emptied the thread while a stale callback (late
      // watchdog timer) was pending — patching nothing is the right no-op.
      if (prev.length === 0) return prev
      const next = prev.slice()
      next[next.length - 1] = patch(next[next.length - 1])
      return next
    })
  }

  const send = async (query: string) => {
    if (isStreaming) return // one in-flight query; the composer is disabled anyway
    const thread = threadRef.current
    const controller = new AbortController()
    abortRef.current = controller
    setIsStreaming(true)
    setMessages((prev) => [
      ...prev,
      {
        role: 'user',
        text: query,
        citations: [],
        parts: null,
        isAbstention: false,
        suppressCitations: false,
        streaming: false,
        phase: 'done',
        error: null,
      },
      emptyAssistant(),
    ])
    // Silence watchdog for the anchoring gap (see ANCHORING_SILENCE_MS). One
    // send is in flight at a time (guard above), so the timer always refers
    // to the assistant message this send appended.
    let anchoringTimer: ReturnType<typeof setTimeout> | undefined
    const clearAnchoringTimer = () => {
      if (anchoringTimer !== undefined) clearTimeout(anchoringTimer)
      anchoringTimer = undefined
    }
    // Amber recoverable-failure dialog (design #4). ONE semantics for the two
    // error mouths of the query path: pre-stream JSON errors and the
    // mid-stream SSE error event both funnel through onError (client.ts), so
    // hooking here covers both. The body is core's actionable message
    // VERBATIM — never rewritten. Additive to the passive surfaces: the
    // sidebar OllamaBadge and the WarmUpGate error card keep reporting the
    // idle/startup state; this dialog only fires for the query that actively
    // failed. Fire-and-forget: the in-chat error message (patchLast above)
    // stays regardless of the user's dialog choice.
    const offerRetry = (event: ErrorEvent) => {
      if (!RECOVERABLE_ERROR_CODES.has(event.error_code)) return
      void dialog
        .confirm({
          sem: 'warn',
          icon: 'warn',
          title: 'No se pudo completar la consulta',
          body: event.message,
          primaryLabel: 'Reintentar',
          secondaryLabel: 'Cerrar',
        })
        .then((retry) => {
          // Thread guard, same rule as the abort path: a vertical switch
          // while the dialog sat open moved the conversation — re-asking
          // there would cross corpora.
          if (retry && threadRef.current === thread) void send(query)
        })
    }
    try {
      await streamQuery(verticalId, query, {
        // Early, provisional flag; DoneEvent below is authoritative. Phase
        // stays 'thinking' — citations arrive before generation starts.
        onCitations: (event) =>
          patchLast((m) => ({
            ...m,
            citations: event.citations,
            isAbstention: event.is_abstention,
          })),
        onToken: (event) => {
          // A new token proves we're still writing: reset the silence
          // watchdog (and revert a premature 'anchoring' from a long pause).
          clearAnchoringTimer()
          anchoringTimer = setTimeout(() => {
            patchLast((m) =>
              m.phase === 'writing' ? { ...m, phase: 'anchoring' } : m,
            )
          }, ANCHORING_SILENCE_MS)
          patchLast((m) => ({
            ...m,
            text: m.text + event.text,
            // First token flips thinking → writing (idempotent afterwards,
            // and flips a premature 'anchoring' back to writing).
            phase: 'writing',
          }))
        },
        onDone: (event) => {
          clearAnchoringTimer()
          patchLast((m) => ({
            ...m,
            streaming: false,
            phase: 'done',
            isAbstention: event.is_abstention,
            suppressCitations: event.suppress_citations,
            // Authoritative typed view (core's parser) — Message renders from
            // this, not from the accumulated raw text. `?? null` keeps the
            // fallback path alive against an older server without parts.
            parts: event.parts ?? null,
          }))
        },
        onError: (event) => {
          clearAnchoringTimer()
          patchLast((m) => ({
            ...m,
            streaming: false,
            phase: 'error',
            error: event.message,
          }))
          offerRetry(event)
        },
      }, controller.signal)
    } catch (err) {
      // A deliberate cancel (vertical switch aborted us) is not an error:
      // the thread that could display it is already gone. Return early —
      // the finally below still clears the watchdog.
      if (controller.signal.aborted) return
      // Transport-level failure (API process down mid-stream); HTTP-level
      // errors already arrived via onError.
      patchLast((m) => ({
        ...m,
        streaming: false,
        phase: 'error',
        error: err instanceof Error ? err.message : String(err),
      }))
    } finally {
      clearAnchoringTimer()
      // Thread guard: after a switch this send's cleanup must not clobber
      // the fresh thread (e.g. re-enabling the composer mid-query there).
      if (threadRef.current === thread) {
        setIsStreaming(false)
        abortRef.current = null
      }
    }
  }

  return { messages, send, isStreaming }
}
