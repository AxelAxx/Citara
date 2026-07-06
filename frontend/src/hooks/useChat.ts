import { useState } from 'react'
import { streamQuery } from '../api/client'
import type { AnswerPart, Citation } from '../api/client'

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

  // Functional updates throughout: token events arrive faster than renders,
  // and reading `messages` from the closure would drop tokens.
  const patchLast = (patch: (message: Message) => Message) => {
    setMessages((prev) => {
      const next = prev.slice()
      next[next.length - 1] = patch(next[next.length - 1])
      return next
    })
  }

  const send = async (query: string) => {
    if (isStreaming) return // one in-flight query; the composer is disabled anyway
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
        },
      })
    } catch (err) {
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
      setIsStreaming(false)
    }
  }

  return { messages, send, isStreaming }
}
