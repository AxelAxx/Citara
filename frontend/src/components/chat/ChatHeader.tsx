/**
 * Compact single-row chat bar (mock: empty-1b.html) — replaces the earlier
 * hero-style header. Left: active domain display; right: live stat chips.
 * Purely presentational: numbers/model arrive as props (API values — the
 * mock's "14"/"llama3.1" are placeholders).
 */
export interface ChatHeaderProps {
  letter: string
  domainName: string
  tagline: string
  documentCount: number
  model: string
}

export function ChatHeader({
  letter,
  domainName,
  tagline,
  documentCount,
  model,
}: ChatHeaderProps) {
  const chip =
    'inline-flex items-center rounded-sm border border-border bg-surface px-[11px] py-[6px] font-mono text-[11px] text-muted'

  // .chat-header: hook for the collapse rule (index.css) — with the sidebar
  // gone, extra padding-left clears the floating › toggle. Expanded, that
  // toggle straddles the sidebar edge and ends 17px into this bar, so pl-8
  // (not the symmetric px-6) keeps ~15px of air between ‹ and the chip.
  return (
    <div
      className="chat-header flex items-center gap-4 border-b border-border py-5 pl-8 pr-6"
      style={{
        background: 'linear-gradient(180deg, var(--surface) 0%, var(--bg) 100%)',
      }}
    >
      {/* A display, not a button: switching domains lives in the sidebar (one
          control). */}
      <div className="flex min-w-0 items-center gap-[13px]">
        <span className="flex h-[42px] w-[42px] shrink-0 items-center justify-center rounded-[11px] bg-accent font-mono text-[15px] font-semibold text-accent-on">
          {letter}
        </span>
        {/* The 8px column gap is what keeps the tagline clear of the name —
            both lines sit at line-height:1 (mock tokens). */}
        <div className="flex min-w-0 flex-col items-start gap-2">
          <span className="whitespace-nowrap font-serif text-[17px] font-semibold leading-none text-text">
            {domainName}
          </span>
          {/* pb-px: at line-height:1 the 11px box clips the mono descenders
              ("g") under overflow:hidden — one pixel of slack frees them. */}
          <span className="max-w-full overflow-hidden text-ellipsis whitespace-nowrap pb-px font-mono text-[11px] leading-none text-faint">
            {tagline}
          </span>
        </div>
      </div>

      <div className="ml-auto flex shrink-0 items-center gap-2">
        <span className={`${chip} gap-[6px]`}>
          <span className="font-serif font-semibold text-text">
            {documentCount}
          </span>{' '}
          docs
        </span>
        <span className={`${chip} gap-[6px]`}>{model}</span>
        <span className={`${chip} gap-[7px]`}>
          <span className="h-[6px] w-[6px] rounded-full bg-ok shadow-[0_0_0_3px_rgba(70,207,166,0.16)]" />
          local
        </span>
      </div>
    </div>
  )
}
