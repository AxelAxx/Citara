/**
 * First-use hero for an empty chat (mock: empty-1b.html), left-aligned inside
 * a 720px column. Suggestions are the vertical's real example_questions in a
 * flat 2×2 grid — deliberately WITHOUT the mock's category headers: the
 * config exposes a flat list, and inventing categories here would hardcode
 * vertical structure into Presentation (golden rule 2).
 */
export interface EmptyStateProps {
  suggestions: string[]
  onSelect: (question: string) => void
}

export function EmptyState({ suggestions, onSelect }: EmptyStateProps) {
  return (
    <div className="w-full max-w-[720px]">
      <div>
        <div className="mb-5 inline-flex items-center gap-[14px] font-mono text-[11px] text-faint">
          <span className="inline-flex items-center gap-[7px]">
            <span className="h-[6px] w-[6px] rounded-full bg-ok shadow-[0_0_0_3px_rgba(70,207,166,0.16)]" />
            100% local
          </span>
          <span className="opacity-40">·</span>
          <span>Cita la fuente</span>
          <span className="opacity-40">·</span>
          <span>Responde en español</span>
        </div>
        <h2 className="mb-3 font-serif text-[40px] font-semibold leading-[1.12] tracking-[-0.025em] text-text">
          ¿Qué necesitas consultar hoy?
        </h2>
        <p className="max-w-[540px] text-[15.5px] leading-[1.6] text-muted">
          Pregunta en español; respondo{' '}
          <strong className="font-semibold text-text">solo</strong> con los
          documentos cargados y cito la fuente exacta.
        </p>
      </div>

      <div className="mt-[34px] grid grid-cols-2 gap-x-5 gap-y-[14px]">
        {suggestions.map((question) => (
          <button
            key={question}
            type="button"
            onClick={() => onSelect(question)}
            className="group flex w-full items-center gap-[11px] rounded-md border border-border bg-surface px-[15px] py-[13px] text-left text-[14px] leading-[1.4] text-text transition-all hover:border-accent-line hover:bg-surface2"
          >
            <span className="flex-1">{question}</span>
            <span className="text-[15px] text-faint transition-all group-hover:translate-x-[3px]">
              →
            </span>
          </button>
        ))}
      </div>

      {/* Static teaching aid: shows what a citation chip will look like. The
          reference is illustrative copy, not data — it never varies. */}
      <div className="mt-[34px] flex items-center gap-3 border-t border-border pt-[22px] text-[13px] leading-[1.5] text-faint">
        <span className="flex-1">
          Cada afirmación se ancla a su origen. Verás chips como este junto al
          texto:
        </span>
        <span className="inline-flex shrink-0 items-center gap-2 rounded-[9px] border border-border bg-surface px-[11px] py-[7px]">
          <sup className="inline-flex h-4 min-w-4 items-center justify-center rounded-[5px] border border-accent-line bg-accent-tint px-1 font-mono text-[10.5px] font-semibold text-accent">
            1
          </sup>
          <span className="font-mono text-[11.5px] text-muted">
            BOE-A-2015-11430 · pág. 49
          </span>
        </span>
      </div>
    </div>
  )
}
