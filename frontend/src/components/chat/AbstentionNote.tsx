import type { ReactNode } from 'react'

/**
 * Abstention framing (mock chat-1b.html): "sin coincidencias" pill above the
 * answer text, explanatory note below it. Takes the message text as children
 * because the mock interleaves it between pill and note — abstention is a
 * presented-as-expected outcome, never an error state.
 */
export interface AbstentionNoteProps {
  children: ReactNode
  /** True when retrieval DID return candidate fragments (the citations event
      carried hits) and the model still declined — the SOFT path. The old
      static "0 fragmentos" line was a lie there (a real smoke had 4 sources
      behind an abstention) and sent diagnosis at the retrieval gate instead
      of the model. The copy must never assert a retrieval fact the front
      didn't check. */
  hadCandidates: boolean
}

export function AbstentionNote({ children, hadCandidates }: AbstentionNoteProps) {
  return (
    <div>
      <span className="mb-2 inline-flex items-center gap-[6px] rounded-full border border-dashed border-border-strong bg-surface2 px-[9px] py-[3px] font-mono text-[10px] uppercase tracking-[0.05em] text-muted">
        {/* Same per-path truth as the lines below: "sin coincidencias" is
            only true on the HARD path — on SOFT there WERE matches, the
            model just didn't ground an answer in them. */}
        {hadCandidates
          ? 'Respuesta no fundamentada en los documentos'
          : 'Sin coincidencias en los documentos'}
      </span>
      {children}
      <div className="mt-[13px] flex gap-[11px] rounded-md border border-border bg-surface px-[15px] py-[13px]">
        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-[1.5px] border-muted font-serif text-xs italic text-muted">
          i
        </span>
        <div className="text-[13px] leading-[1.55] text-muted">
          {hadCandidates
            ? 'Esto es una respuesta esperada, no un fallo. Citara se ' +
              'abstiene cuando no encuentra apoyo suficiente en los ' +
              'documentos para una respuesta fundamentada.'
            : 'Esto es una respuesta esperada, no un fallo. Citara se ' +
              'abstiene cuando la pregunta queda fuera de los documentos ' +
              'cargados.'}
          <br />
          <span className="font-mono text-[11px] text-faint">
            {/* Per-path truth: only the HARD path (empty retrieval) may claim
                a fragment count; the SOFT path states the model's decline
                without inventing figures. */}
            {hadCandidates
              ? 'La respuesta no encontró apoyo suficiente en los documentos'
              : 'No se encontraron fragmentos relevantes'}
          </span>
        </div>
      </div>
    </div>
  )
}
