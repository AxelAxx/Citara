import type { ReactNode } from 'react'

/**
 * Abstention framing (mock chat-1b.html): "sin coincidencias" pill above the
 * answer text, explanatory note below it. Takes the message text as children
 * because the mock interleaves it between pill and note — abstention is a
 * presented-as-expected outcome, never an error state.
 */
export interface AbstentionNoteProps {
  children: ReactNode
}

export function AbstentionNote({ children }: AbstentionNoteProps) {
  return (
    <div>
      <span className="mb-2 inline-flex items-center gap-[6px] rounded-full border border-dashed border-border-strong bg-surface2 px-[9px] py-[3px] font-mono text-[10px] uppercase tracking-[0.05em] text-muted">
        Sin coincidencias en los documentos
      </span>
      {children}
      <div className="mt-[13px] flex gap-[11px] rounded-md border border-border bg-surface px-[15px] py-[13px]">
        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-[1.5px] border-muted font-serif text-xs italic text-muted">
          i
        </span>
        <div className="text-[13px] leading-[1.55] text-muted">
          Esto es una respuesta esperada, no un fallo. Citara se abstiene
          cuando la pregunta queda fuera de los documentos cargados.
          <br />
          <span className="font-mono text-[11px] text-faint">
            0 fragmentos con coincidencia suficiente
          </span>
        </div>
      </div>
    </div>
  )
}
