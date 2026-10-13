import { useEffect, useRef } from 'react'
import { ICON, SEM } from './dialogSemantics'
import type { DialogIcon, DialogSem } from './dialogSemantics'

// Re-exported so callers keep a single import path for the dialog vocabulary.
export type { DialogIcon, DialogSem } from './dialogSemantics'

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
