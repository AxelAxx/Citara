/**
 * One domain card, purely presentational: ready-to-render strings in, the
 * accent it paints with is whatever :root currently carries. Two layouts
 * behind one component (DRY): 'column' is the Welcome grid card, 'row' the
 * compact sidebar switcher entry (chip left, name+meta right, no "✓ activo").
 */
export interface DomainCardProps {
  letter: string
  name: string
  meta: string
  active: boolean
  onSelect: () => void
  variant?: 'column' | 'row'
}

export function DomainCard({
  letter,
  name,
  meta,
  active,
  onSelect,
  variant = 'column',
}: DomainCardProps) {
  const surface = active
    ? 'border-accent-line bg-accent-tint'
    : 'border-border bg-surface'

  if (variant === 'row') {
    // Tokens from sidebar.html: 11px radius, 30px chip (8px radius), 13.5/10.5px type.
    // The chip follows `active` here — an always-accent chip made inactive rows
    // read as selected. (The column variant signals state via "✓ activo" instead.)
    const chip = active
      ? 'bg-accent text-accent-on'
      : 'border border-border bg-surface2 text-muted'
    return (
      <button
        type="button"
        onClick={onSelect}
        className={`flex items-center gap-[11px] rounded-card border px-3 py-[11px] text-left transition-all ${surface}`}
      >
        <span
          className={`flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-sm font-mono text-[13px] font-semibold ${chip}`}
        >
          {letter}
        </span>
        <span className="leading-[1.3]">
          <span className="block text-[13.5px] font-semibold text-text">
            {name}
          </span>
          <span className="block font-mono text-[10.5px] text-faint">
            {meta}
          </span>
        </span>
      </button>
    )
  }

  return (
    <button
      type="button"
      onClick={onSelect}
      className={`flex min-w-0 flex-col gap-2.5 rounded-[14px] border p-[18px] pb-4 text-left transition-all ${surface}`}
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
