export interface SidebarToggleProps {
  collapsed: boolean
  onToggle: () => void
}

/**
 * Presentational collapse control for the chat sidebar. The collapsed state
 * lives in the layout (Chat.tsx) — this only reflects it and reports clicks.
 * Colors go through the CSS vars (not the hex Tailwind tokens) so the button
 * follows any runtime palette swap.
 */
export function SidebarToggle({ collapsed, onToggle }: SidebarToggleProps) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-label={collapsed ? 'Mostrar barra lateral' : 'Ocultar barra lateral'}
      aria-expanded={!collapsed}
      className={`flex h-7 w-7 cursor-pointer items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface)] text-[var(--muted)] transition-all duration-150 hover:border-[var(--accent-line)] hover:bg-[var(--surface2)] hover:text-[var(--accent)] ${
        collapsed ? 'shadow-[0_2px_10px_rgba(0,0,0,0.35)]' : ''
      }`}
    >
      {/* One ‹ path, flipped to › while collapsed: the arrow always points
          where the sidebar will go. The shadow only floats it over the chat
          area (collapsed); expanded it sits flush on the sidebar edge. */}
      <svg
        width="13"
        height="13"
        viewBox="0 0 18 18"
        fill="none"
        aria-hidden="true"
        className={`transition-transform duration-150 ${
          collapsed ? 'rotate-180' : ''
        }`}
      >
        {/* viewBox stays 18: at 13px rendered, stroke 2.2 paints ≈1.6px. */}
        <path
          d="M10.8 4.8L6.6 9L10.8 13.2"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </button>
  )
}
