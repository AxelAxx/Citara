export interface CiteChipProps {
  n: number
  /** 'card': the Fuentes-card square. 'inline': the smaller superscript-like
      chip for in-text citations (step 3b). Default 'card'. */
  variant?: 'inline' | 'card'
}

/**
 * The citation-number chip (mock: Citara-Chat.html citeChip tokens) — ONE
 * source of truth for the rounded accent square, reused by the SourcesPanel
 * cards today and inline in the answer text when 3b lands. Presentational:
 * renders ONLY the number; resolving n → Citation stays with the caller.
 * Accent tokens are CSS vars on purpose: the chip follows the active
 * vertical's palette swap.
 */
export function CiteChip({ n, variant = 'card' }: CiteChipProps) {
  const size =
    variant === 'card'
      ? 'h-[22px] min-w-[22px] text-[13px]'
      : // align-[2px]: a gentle superscript lift without <sup> — the browser's
        // vertical-align:super is what misaligned the EmptyState chip before.
        // cite-chip-in (index.css): entry fade+scale — inline chips mount in
        // one batch when the done parts land, and without it they pop in.
        'h-4 min-w-4 align-[2px] text-[10.5px] cite-chip-in'
  return (
    <span
      className={`inline-flex items-center justify-center rounded-[5px] border border-[var(--accent-line)] bg-[var(--accent-tint)] px-1 font-mono font-semibold text-[color:var(--accent)] ${size}`}
    >
      {n}
    </span>
  )
}
