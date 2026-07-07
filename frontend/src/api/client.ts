/**
 * Typed client for the Citara API (docs/API_CONTRACT.md).
 *
 * The front is pure Presentation: it never imports Python and reaches core/
 * exclusively through these HTTP calls. The types below mirror the contract's
 * shapes 1:1 — Citation/CorpusStats serialize straight from core.models, so
 * redefining them anywhere else in the front would be drift.
 */

const API_BASE: string =
  import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api'

// --- contract types ----------------------------------------------------------

export interface Citation {
  document_id: string
  page: number
  section: string | null
  chunk_text: string
}

export interface CorpusStats {
  document_count: number
  chunk_count: number
  embedding_model: string
  document_ids: string[]
}

export interface VerticalView {
  id: string
  display_name: string
  domain_name: string
  domain_letter: string
  domain_sublabel: string
  domain_tagline: string
  example_questions: string[]
}

export interface ApiErrorBody {
  error_code: string
  message: string
}

export type Health =
  | {
      ok: true
      llm_model: string
      embedding_model: string
      ollama_base_url: string
      // The exact abstention literal (source of truth: core.generate
      // .ABSTENTION_TEXT, published by /health). Used ONLY for the cosmetic
      // streaming cleanup — the done event decides abstention.
      abstention_text: string
    }
  | ({ ok: false } & ApiErrorBody)

// SSE events, in contract order: citations → token* → done | error.
export interface CitationsEvent {
  citations: Citation[]
  // Early hard-path flag only (empty context ⇒ no citations); the DoneEvent
  // carries the authoritative resolution once the full text is known.
  is_abstention: boolean
}

export interface TokenEvent {
  text: string
}

// Typed view of the final answer text (the done event's `parts`, 3b): plain
// text runs interleaved with resolved citation references. Discriminated on
// `kind`, mirroring core.models.TextPart/CitePart 1:1. `n` is the 1-based
// index into the citations event's list — the client resolves it positionally
// (citations[n-1]) and NEVER parses [N] markers itself: core already
// validated, dropped garbage markers, and remapped n through the dedup.
export type AnswerPart =
  | { kind: 'text'; text: string }
  | { kind: 'cite'; n: number }

export interface DoneEvent {
  is_abstention: boolean
  // Mirrors is_abstention: when true the front drops the sources panel —
  // sources under "I can't find this" would contradict the answer.
  suppress_citations: boolean
  // Authoritative parsed view of the streamed text. On abstention: a single
  // TextPart and no CiteParts (consistent with suppress_citations).
  parts: AnswerPart[]
}

export type ErrorEvent = ApiErrorBody

// --- plain JSON endpoints ------------------------------------------------------

export class ApiError extends Error {
  // Explicit fields, not constructor parameter properties: the Vite template
  // enables erasableSyntaxOnly, which forbids TS-only runtime syntax.
  readonly errorCode: string
  readonly status: number

  constructor(errorCode: string, message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.errorCode = errorCode
    this.status = status
  }
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) {
    // Error bodies are the contract's uniform {error_code, message}.
    const body = (await res.json().catch(() => null)) as ApiErrorBody | null
    throw new ApiError(
      body?.error_code ?? 'http_error',
      body?.message ?? res.statusText,
      res.status,
    )
  }
  return (await res.json()) as T
}

export async function getHealth(): Promise<Health> {
  // No throw-on-503 here: the health body is typed for BOTH outcomes (ok:false
  // carries the actionable error_code/message the badge renders directly).
  const res = await fetch(`${API_BASE}/health`)
  return (await res.json()) as Health
}

export async function getVerticals(): Promise<VerticalView[]> {
  // The contract wraps the list in a {verticals} envelope — unwrap here so
  // callers get the array they actually iterate.
  const body = await getJson<{ verticals: VerticalView[] }>('/verticals')
  return body.verticals
}

export function getCorpus(verticalId: string): Promise<CorpusStats> {
  return getJson<CorpusStats>(`/verticals/${verticalId}/corpus`)
}

// --- SSE query stream ----------------------------------------------------------

export interface StreamHandlers {
  onCitations: (event: CitationsEvent) => void
  onToken: (event: TokenEvent) => void
  onDone: (event: DoneEvent) => void
  onError: (event: ErrorEvent) => void
}

/**
 * POST /verticals/{id}/query and dispatch the SSE stream to the handlers.
 *
 * fetch + body.getReader(), NOT EventSource: EventSource is GET-only and
 * cannot carry the {query} JSON body the contract requires — and reading the
 * stream manually lets us parse the NAMED events (citations/token/done/error)
 * sse-starlette emits, instead of only unnamed "message" events.
 */
export async function streamQuery(
  verticalId: string,
  query: string,
  handlers: StreamHandlers,
  // Cancellation: aborting tears down the fetch AND the body reader, so the
  // next read() rejects with an AbortError that propagates to the caller.
  // Deliberate cancels (vertical switch) are the caller's to recognize —
  // this function treats them as any other rejected read.
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_BASE}/verticals/${verticalId}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query }),
    signal,
  })
  if (!res.ok || !res.body) {
    // Pre-stream failures (unknown vertical, retrieval down) arrive as the
    // uniform JSON error responses, not as SSE — funnel them to onError so
    // the caller has ONE error path.
    const body = (await res.json().catch(() => null)) as ApiErrorBody | null
    handlers.onError({
      error_code: body?.error_code ?? 'http_error',
      message: body?.message ?? res.statusText,
    })
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    // SSE frames end with a blank line; sse-starlette emits \r\n line ends,
    // so normalize before splitting frames.
    buffer = (buffer + decoder.decode(value, { stream: true })).replace(
      /\r\n/g,
      '\n',
    )
    let separator: number
    while ((separator = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, separator)
      buffer = buffer.slice(separator + 2)
      dispatchFrame(frame, handlers)
    }
  }
}

function dispatchFrame(frame: string, handlers: StreamHandlers): void {
  let event = 'message'
  const dataLines: string[] = []
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) event = line.slice('event:'.length).trim()
    else if (line.startsWith('data:'))
      dataLines.push(line.slice('data:'.length).trimStart())
    // Lines starting with ':' are SSE comments (sse-starlette keep-alive
    // pings) — deliberately ignored.
  }
  if (dataLines.length === 0) return
  const data: unknown = JSON.parse(dataLines.join('\n'))
  switch (event) {
    case 'citations':
      handlers.onCitations(data as CitationsEvent)
      break
    case 'token':
      handlers.onToken(data as TokenEvent)
      break
    case 'done':
      handlers.onDone(data as DoneEvent)
      break
    case 'error':
      handlers.onError(data as ErrorEvent)
      break
    // Unknown events are skipped, never fatal: the stream contract may grow.
  }
}
