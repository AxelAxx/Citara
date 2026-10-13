import type { ReactNode } from 'react'

/**
 * Semantic palette and icon set shared by ConfirmDialog and DialogProvider.
 * Lives in its own module (no React components exported here) so the component
 * files stay Fast-Refresh friendly.
 *
 * Exactly ONE semantic color per dialog (design rule 4), all sourced from the
 * existing token vars (no new hex).
 *
 * COLLISION NOTE (deliberate, do not "fix" by color): 'accent' swaps per
 * vertical (theme/accent.ts) — in health it becomes the SAME green as
 * --ok/'success'. That is brand semantics, wanted. The consequence is a hard
 * rule: neutral and success dialogs must be distinguishable by ICON SHAPE
 * (neutral carries refresh/info glyphs, success carries the check), never by
 * hue alone.
 */
export type DialogSem = 'danger' | 'accent' | 'warn' | 'success'

interface SemPaint {
  /** Icon + emphasis color. */
  fg: string
  /** The icon's tinted circle. */
  tint: string
  /** Text color ON the sem-colored primary button. */
  on: string
}

export const SEM: Record<DialogSem, SemPaint> = {
  // White on this red passes contrast (QuitDialog precedent); the light
  // amber/green/periwinkle need dark text instead (--bg2).
  danger: { fg: 'var(--danger)', tint: 'var(--danger-tint)', on: '#ffffff' },
  // --accent-on already tracks the swapped accent per vertical.
  accent: { fg: 'var(--accent)', tint: 'var(--accent-tint)', on: 'var(--accent-on)' },
  warn: { fg: 'var(--warn)', tint: 'var(--warn-tint)', on: 'var(--bg2)' },
  success: { fg: 'var(--ok)', tint: 'var(--ok-tint)', on: 'var(--bg2)' },
}

/** The reference design's icon set, ported as inline paths — no icon library. */
export type DialogIcon = 'exit' | 'trash' | 'refresh' | 'warn' | 'check'

function glyph(children: ReactNode): ReactNode {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-[18px] w-[18px]"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  )
}

export const ICON: Record<DialogIcon, ReactNode> = {
  exit: glyph(
    <>
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <path d="M16 17l5-5-5-5" />
      <path d="M21 12H9" />
    </>,
  ),
  trash: glyph(
    <>
      <path d="M3 6h18" />
      <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
    </>,
  ),
  refresh: glyph(
    <>
      <path d="M23 4v6h-6" />
      <path d="M1 20v-6h6" />
      <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10" />
      <path d="M20.49 15a9 9 0 0 1-14.85 3.36L1 14" />
    </>,
  ),
  warn: glyph(
    <>
      <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <path d="M12 9v4" />
      <path d="M12 17h.01" />
    </>,
  ),
  check: glyph(<path d="M20 6 9 17l-5-5" />),
}
