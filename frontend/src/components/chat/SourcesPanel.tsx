import { useState } from 'react'
import type { Citation } from '../../api/client'

/**
 * Collapsible "Fuentes citadas" panel under an answer (mock chat-1b.html).
 * Presentational: renders whatever citations it is handed, numbered in
 * arrival order (the same order the ¹ markers will use in step 3b). The
 * "Abrir fragmento" source viewer (mock 09) is deliberately deferred — the
 * snippet shows chunk_text inline.
 */
export interface SourcesPanelProps {
  citations: Citation[]
}

export function SourcesPanel({ citations }: SourcesPanelProps) {
  // Folded by default: the count badge advertises the evidence without
  // pushing a wall of snippets between consecutive answers.
  const [open, setOpen] = useState(false)

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
              className="flex gap-[13px] rounded-card border border-border bg-bg px-[14px] py-[13px] transition-all hover:border-accent-line hover:bg-surface2"
            >
              <div className="flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-[7px] border border-accent-line bg-accent-tint font-mono text-xs font-semibold text-accent">
                {index + 1}
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
