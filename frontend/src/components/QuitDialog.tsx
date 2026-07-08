import { ConfirmDialog } from './ConfirmDialog'

export interface QuitDialogProps {
  open: boolean
  onCancel: () => void
  onConfirm: () => void
}

/**
 * Quit confirmation — now a thin binding over ConfirmDialog (the pattern this
 * dialog pioneered, generalized). Open state and the actual quit stay in the
 * caller (Chat.tsx + lib/quit, including the 'blocked' → farewell path),
 * untouched: this file only owns the quit COPY (danger semantics, exit icon,
 * the verb "Salir", focus on Cancelar).
 */
export function QuitDialog({ open, onCancel, onConfirm }: QuitDialogProps) {
  return (
    <ConfirmDialog
      open={open}
      sem="danger"
      icon="exit"
      title="¿Salir de Citara?"
      body="Se cerrará la aplicación. Tus documentos y el índice permanecen guardados en tu equipo."
      primaryLabel="Salir"
      secondaryLabel="Cancelar"
      onPrimary={onConfirm}
      onSecondary={onCancel}
    />
  )
}
