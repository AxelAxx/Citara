import { useState } from 'react'
import { streamQuery } from '../api/client'
import type { AnswerPart, Citation } from '../api/client'

/**
 * Assistant lifecycle: 'thinking' from send until the first token (retrieval
 * + prompt eval), 'writing' while tokens stream, then 'done' | 'error'.
 * User messages are born 'done'.
 */
export type MessagePhase = 'thinking' | 'writing' | 'done' | 'error'

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
        onToken: (event) =>
          patchLast((m) => ({
            ...m,
            text: m.text + event.text,
            // First token flips thinking → writing (idempotent afterwards).
            phase: 'writing',
          })),
        onDone: (event) =>
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
          })),
        onError: (event) =>
          patchLast((m) => ({
            ...m,
            streaming: false,
            phase: 'error',
            error: event.message,
          })),
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
      setIsStreaming(false)
    }
  }

  return { messages, send, isStreaming }
}
