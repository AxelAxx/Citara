/**
 * Per-vertical accent palette, injected on :root — the same pattern
 * ui/theme.py's inject_theme used in Streamlit. This is the ONLY place the
 * front knows a vertical's colors; every component styles against the
 * --accent* vars (src/index.css carries the legal quartet as the first-paint
 * default, before any API data exists).
 */

export type VerticalId = 'legal' | 'health'

interface AccentQuartet {
  accent: string
  on: string
  tint: string
  line: string
}

// Verbatim from export/citara.css (dark-theme quartets).
const PALETTES: Record<VerticalId, AccentQuartet> = {
  legal: {
    accent: '#7C9CFF',
    on: '#0C0D10',
    tint: 'rgba(124,156,255,0.13)',
    line: 'rgba(124,156,255,0.36)',
  },
  health: {
    accent: '#46CFA6',
    on: '#06120D',
    tint: 'rgba(70,207,166,0.13)',
    line: 'rgba(70,207,166,0.36)',
  },
}

/**
 * Narrow an API vertical id to a palette key. Throws instead of falling back:
 * a vertical without a quartet would silently render half-themed, and the fix
 * belongs here, nowhere else (fail fast, loud).
 */
export function asVerticalId(id: string): VerticalId {
  if (id in PALETTES) return id as VerticalId
  throw new Error(
    `Unknown vertical "${id}": add its accent quartet to theme/accent.ts`,
  )
}

export function setAccent(vertical: VerticalId): void {
  const palette = PALETTES[vertical]
  const root = document.documentElement.style
  root.setProperty('--accent', palette.accent)
  root.setProperty('--accent-on', palette.on)
  root.setProperty('--accent-tint', palette.tint)
  root.setProperty('--accent-line', palette.line)
}
