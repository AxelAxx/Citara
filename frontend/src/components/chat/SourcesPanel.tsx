import { useEffect, useRef, useState } from 'react'
import type { Citation } from '../../api/client'
import { CiteChip } from './CiteChip'

/** A cite-chip click asking to reveal source n; key bumps per click so
    re-clicking the same chip re-triggers the effect. */
export interface SourceFocus {
  n: number
  key: number
}

/**
 * Collapsible "Fuentes citadas" panel under an answer (mock chat-1b.html).
 * Presentational: renders whatever citations it is handed, numbered in
 * arrival order (the same order the inline ¹ chips use). The "Abrir
 * fragmento" source viewer (mock 09) is deliberately deferred — the snippet
 * shows chunk_text inline.
 */
export interface SourcesPanelProps {
  citations: Citation[]
  /** Anchor namespace for the cite→source ids (src-<msgId>-<n>). */
  msgId?: string
  /** Inline chip click: unfold, scroll to and flash card n. */
  focus?: SourceFocus | null
}

export function SourcesPanel({ citations, msgId, focus }: SourcesPanelProps) {
  // Folded by default: the count badge advertises the evidence without
  // pushing a wall of snippets between consecutive answers.
  const [open, setOpen] = useState(false)
  const [flashN, setFlashN] = useState<number | null>(null)
  const cardRefs = useRef(new Map<number, HTMLDivElement>())

  useEffect(() => {
    if (!focus) return
    setOpen(true)
    setFlashN(focus.n)
    // One frame so the card exists when the panel was folded until now.
    const frame = requestAnimationFrame(() => {
      // block:'nearest' only moves the chat column — the app root is
      // h-screen/overflow-hidden, so no global page scroll can happen.
      cardRefs.current
        .get(focus.n)
        ?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    })
    const timer = window.setTimeout(() => setFlashN(null), 1200)
    return () => {
      cancelAnimationFrame(frame)
      window.clearTimeout(timer)
    }
  }, [focus])

  return (
    <div className="mt-[14px] rounded-[14px] border border-border bg-surface px-[14px] py-[13px]">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className="flex w-full items-center justify-between gap-[10px] p-px"
      >
        <span className="flex items-center gap-[9px]">
          <span
            className={`inline-flex w-4 items-center justify-center text-[15px] text-accent transition-transform duration-200 ${
              open ? 'rotate-90' : ''
            }`}
          >
            ›
          </span>
          <span className="text-[12.5px] font-semibold tracking-[0.01em] text-text">
            Fuentes citadas
          </span>
          <span className="rounded-full bg-accent-tint px-[7px] py-px font-mono text-[11px] text-accent">
            {citations.length}
          </span>
        </span>
        <span className="font-mono text-[11px] text-faint">
          {open ? 'Ocultar' : 'Mostrar'}
        </span>
      </button>

      {open && (
        <div className="mt-[13px] flex flex-col gap-[9px] border-t border-border pt-[13px]">
          {citations.map((citation, index) => (
            <div
              key={`${citation.document_id}-${citation.page}-${index}`}
              id={msgId ? `src-${msgId}-${index + 1}` : undefined}
              ref={(el) => {
                if (el) cardRefs.current.set(index + 1, el)
                else cardRefs.current.delete(index + 1)
              }}
              className={`flex gap-[13px] rounded-card border bg-bg px-[14px] py-[13px] transition-all hover:border-accent-line hover:bg-surface2 ${
                flashN === index + 1
                  ? 'border-accent-line bg-surface2 ring-1 ring-[var(--accent-line)]'
                  : 'border-border'
              }`}
            >
              {/* Same chip the ¹ markers will use inline (3b) — numbering by
                  arrival order stays the single link between both places. */}
              <div className="shrink-0">
                <CiteChip n={index + 1} variant="card" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <span className="font-mono text-[12.5px] font-medium text-text">
                    {citation.document_id}
                  </span>
                  <span className="rounded-[6px] border border-border bg-surface2 px-[7px] py-px font-mono text-[10.5px] text-muted">
                    pág. {citation.page}
                  </span>
                  {citation.section && (
                    <span className="ml-auto text-[10.5px] tracking-[0.02em] text-faint">
                      {citation.section}
                    </span>
                  )}
                </div>
                <div className="border-l-2 border-accent-line pl-[11px] font-serif text-[13.5px] italic leading-[1.6] text-muted">
                  «{citation.chunk_text}»
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
