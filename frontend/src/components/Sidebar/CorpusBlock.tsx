/** Presentational corpus status section (label + card, mock Citara-Empty-Chat). */
export interface CorpusBlockProps {
  ready: boolean
  documentCount: number
  chunkCount: number
  /** Opens the CorpusDrawer — state lives in Chat.tsx, not here. */
  onManage: () => void
}

// Spanish typographic thousands: "3 407" with a non-breaking space, so the
// mono stat line never wraps mid-number.
// Exported: the CorpusDrawer renders the same stat line and must format
// identically.
export function formatThousands(n: number): string {
  return n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
}

export function CorpusBlock({
  ready,
  documentCount,
  chunkCount,
  onManage,
}: CorpusBlockProps) {
  return (
    <div>
      <div className="px-1 pb-[10px] pt-[22px] font-mono text-[11px] uppercase tracking-[0.07em] text-faint">
        Corpus
      </div>
      <div className="rounded-md border border-border bg-surface px-[13px] py-3">
        <div className="mb-[6px] flex items-center gap-2">
          <span
            className={`h-2 w-2 shrink-0 rounded-full ${
              ready
                ? 'bg-ok shadow-[0_0_0_3px_rgba(70,207,166,0.18)]'
                : 'bg-border-strong'
            }`}
          />
          <span className="text-[12.5px] font-semibold text-text">
            {ready ? 'Corpus listo' : 'Corpus vacío'}
          </span>
        </div>
        <div className="font-mono text-[10.5px] text-muted">
          {formatThousands(documentCount)} docs ·{' '}
          {formatThousands(chunkCount)} fragmentos
        </div>
        <button
          type="button"
          onClick={onManage}
          className="mt-[10px] w-full rounded-[7px] border border-border bg-transparent px-2 py-[6px] font-mono text-[11px] text-muted transition-colors hover:border-accent-line hover:text-accent"
        >
          Gestionar corpus
        </button>
      </div>
    </div>
  )
}
