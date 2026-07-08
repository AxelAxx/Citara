import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'

/**
 * Semantic palette for dialogs/toasts — exactly ONE semantic color per dialog
 * (design rule 4), all sourced from the existing token vars (no new hex).
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

export interface ConfirmDialogProps {
  open: boolean
  sem: DialogSem
  icon: DialogIcon
  title: string
  body: string
  /** ALWAYS the action's VERB (Salir/Quitar/Reintentar…) — never "Aceptar"
      (design rule 3: the button must name what it does). */
  primaryLabel: string
  secondaryLabel?: string
  onPrimary: () => void
  /** The safe way out — also reached via Esc and backdrop click (rule 2). */
  onSecondary: () => void
}

/**
 * Centered semantic confirmation — the generalization of the original
 * QuitDialog (same overlay, card, aria and keyboard contract; QuitDialog is
 * now a thin binding over this). Presentational: open state and the confirmed
 * action live in the caller (or in DialogProvider's confirm()).
 * Three ways out to the secondary: button, backdrop click, Escape.
 */
export function ConfirmDialog({
  open,
  sem,
  icon,
  title,
  body,
  primaryLabel,
  secondaryLabel = 'Cancelar',
  onPrimary,
  onSecondary,
}: ConfirmDialogProps) {
  const secondaryRef = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    if (!open) return
    // Initial focus lands on the SAFE action: Enter must never quit (or
    // delete, or reindex) by accident from a dialog the user may have opened
    // by misclick (design rule 5).
    secondaryRef.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onSecondary()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onSecondary])

  if (!open) return null

  const paint = SEM[sem]

  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 px-4"
      onClick={(event) => {
        // Backdrop only — clicks inside the panel arrive with another target.
        if (event.target === event.currentTarget) onSecondary()
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="w-full max-w-[420px] rounded-[16px] border border-[var(--border)] bg-[var(--surface)] px-6 py-[22px]"
      >
        <div
          className="flex h-11 w-11 items-center justify-center rounded-full"
          style={{ backgroundColor: paint.tint, color: paint.fg }}
        >
          {ICON[icon]}
        </div>
        <h2 className="mt-4 font-serif text-[19px] font-semibold text-[color:var(--text)]">
          {title}
        </h2>
        <p className="mt-2 text-[13.5px] leading-[1.55] text-[color:var(--muted)]">
          {body}
        </p>
        <div className="mt-5 flex justify-end gap-[10px]">
          <button
            ref={secondaryRef}
            type="button"
            onClick={onSecondary}
            className="rounded-[9px] border border-[var(--border)] bg-transparent px-4 py-2 text-[13.5px] font-semibold text-[color:var(--muted)] transition-colors hover:border-[var(--border-strong)] hover:text-[color:var(--text)]"
          >
            {secondaryLabel}
          </button>
          <button
            type="button"
            onClick={onPrimary}
            className="rounded-[9px] px-4 py-2 text-[13.5px] font-semibold transition-opacity hover:opacity-90"
            style={{ backgroundColor: paint.fg, color: paint.on }}
          >
            {primaryLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
