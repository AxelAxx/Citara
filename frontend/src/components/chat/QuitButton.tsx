export interface QuitButtonProps {
  onClick: () => void
}

/**
 * Discreet "Salir de Citara" row for the sidebar footer. Presentational:
 * confirmation/quit live upstream (QuitDialog + lib/quit). Quiet by default,
 * soft red on hover — the danger tokens, not the vertical accent: quitting
 * never changes meaning per vertical.
 */
export function QuitButton({ onClick }: QuitButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Salir de Citara"
      className="mt-3 flex w-full items-center justify-center gap-2 rounded-[9px] border border-[var(--border)] bg-transparent px-3 py-[7px] text-[12px] text-[color:var(--muted)] transition-colors hover:border-[var(--danger-line)] hover:bg-[var(--danger-tint)] hover:text-[color:var(--danger)]"
    >
      {/* Door + arrow leaving through it. */}
      <svg
        width="14"
        height="14"
        viewBox="0 0 16 16"
        fill="none"
        aria-hidden="true"
        className="shrink-0"
      >
        <path
          d="M6 14H4a1.5 1.5 0 0 1-1.5-1.5v-9A1.5 1.5 0 0 1 4 2h2"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
        <path
          d="M10.5 5l3 3-3 3"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d="M13.5 8H6"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      </svg>
      Salir de Citara
    </button>
  )
}
