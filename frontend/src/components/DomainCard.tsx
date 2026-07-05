/**
 * One domain card on the Welcome screen. Purely presentational: it receives
 * ready-to-render strings and knows nothing about the API or vertical ids —
 * the accent it paints with is whatever :root currently carries.
 */
export interface DomainCardProps {
  letter: string
  name: string
  meta: string
  active: boolean
  onSelect: () => void
}

export function DomainCard({
  letter,
  name,
  meta,
  active,
  onSelect,
}: DomainCardProps) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`flex min-w-0 flex-col gap-2.5 rounded-[14px] border p-[18px] pb-4 text-left transition-all ${
        active ? 'border-accent-line bg-accent-tint' : 'border-border bg-surface'
      }`}
    >
      <span className="flex items-center justify-between">
        <span className="flex h-[34px] w-[34px] items-center justify-center rounded-[9px] bg-accent font-mono text-[15px] font-semibold text-accent-on">
          {letter}
        </span>
        {active && (
          <span className="font-mono text-[11px] text-accent">✓ activo</span>
        )}
      </span>
      <span>
        <span className="block text-[15px] font-semibold text-text">{name}</span>
        <span className="mt-0.5 block font-mono text-[11px] text-faint">
          {meta}
        </span>
      </span>
    </button>
  )
}
