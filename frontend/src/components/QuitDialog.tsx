import { useEffect, useRef } from 'react'

export interface QuitDialogProps {
  open: boolean
  onCancel: () => void
  onConfirm: () => void
}

/**
 * Centered quit confirmation. Presentational — open state and the actual
 * quit live in the caller (Chat.tsx + lib/quit). Three ways out to Cancel:
 * button, backdrop click, Escape.
 */
export function QuitDialog({ open, onCancel, onConfirm }: QuitDialogProps) {
  const cancelRef = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    if (!open) return
    // Initial focus lands on the SAFE action: Enter must never quit by
    // accident from a dialog the user may have opened by misclick.
    cancelRef.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCancel()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onCancel])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 px-4"
      onClick={(event) => {
        // Backdrop only — clicks inside the panel arrive with another target.
        if (event.target === event.currentTarget) onCancel()
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="¿Salir de Citara?"
        className="w-full max-w-[420px] rounded-[16px] border border-[var(--border)] bg-[var(--surface)] px-6 py-[22px]"
      >
        <h2 className="font-serif text-[19px] font-semibold text-[color:var(--text)]">
          ¿Salir de Citara?
        </h2>
        <p className="mt-2 text-[13.5px] leading-[1.55] text-[color:var(--muted)]">
          Se cerrará la aplicación. Tus documentos y el índice permanecen
          guardados en tu equipo.
        </p>
        <div className="mt-5 flex justify-end gap-[10px]">
          <button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            aria-label="Cancelar y volver"
            className="rounded-[9px] border border-[var(--border)] bg-transparent px-4 py-2 text-[13.5px] font-semibold text-[color:var(--muted)] transition-colors hover:border-[var(--border-strong)] hover:text-[color:var(--text)]"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={onConfirm}
            aria-label="Salir de Citara"
            className="rounded-[9px] bg-[var(--danger)] px-4 py-2 text-[13.5px] font-semibold text-white transition-opacity hover:opacity-90"
          >
            Salir
          </button>
        </div>
      </div>
    </div>
  )
}
