/** Presentational pill: green status dot + mono caption. */
export interface PrivacyPillProps {
  text: string
}

export function PrivacyPill({ text }: PrivacyPillProps) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1.5">
      {/* Always --ok green: the dot states "local/private", not the active vertical. */}
      <span className="h-[7px] w-[7px] rounded-full bg-ok shadow-[0_0_0_3px_rgba(70,207,166,0.18)]" />
      <span className="font-mono text-[11px] tracking-[0.02em] text-muted">
        {text}
      </span>
    </span>
  )
}
