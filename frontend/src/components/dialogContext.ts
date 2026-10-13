import { createContext } from 'react'
import type { DialogIcon, DialogSem } from './dialogSemantics'

export interface ConfirmOptions {
  sem: DialogSem
  icon: DialogIcon
  title: string
  body: string
  primaryLabel: string
  secondaryLabel?: string
}

export interface ToastOptions {
  message: string
  /** Defaults to 'success' (check icon) — the design's light-feedback case. */
  sem?: DialogSem
  action?: { label: string; onClick: () => void }
}

export interface DialogApi {
  /** Resolves true on the primary verb, false on secondary/Esc/backdrop. */
  confirm(options: ConfirmOptions): Promise<boolean>
  /** Ephemeral, non-blocking notice; auto-dismisses (~3.2s). */
  toast(options: ToastOptions): void
}

/** Null until a <DialogProvider> mounts; useDialog() turns that into a loud error. */
export const DialogContext = createContext<DialogApi | null>(null)
