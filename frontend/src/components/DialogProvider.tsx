import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { ConfirmDialog } from './ConfirmDialog'
import { DialogContext } from './dialogContext'
import type { ConfirmOptions, DialogApi, ToastOptions } from './dialogContext'
import { ICON, SEM } from './dialogSemantics'
import type { DialogIcon, DialogSem } from './dialogSemantics'

// Re-exported so callers keep a single import path for the dialog API types.
export type { ConfirmOptions, DialogApi, ToastOptions } from './dialogContext'

// Auto-dismiss window: long enough to read one sentence, short enough to
// never feel like UI the user must manage (design #7: non-blocking).
const TOAST_MS = 3200

// The neutral↔success color collision (accent turns green in health) is
// resolved by shape: a semantic without an explicit glyph falls back here.
const TOAST_ICON: Record<DialogSem, DialogIcon> = {
  success: 'check',
  warn: 'warn',
  danger: 'warn',
  accent: 'refresh',
}

/**
 * The app-wide dialog seam the diagnostic identified as missing: state is
 * plain provider-local useState (context is the house's minimal step beyond
 * lifted state — no state-manager), while any screen/hook triggers via
 * useDialog(). Exactly ONE confirm slot is alive: dialogs are modal, so a
 * second confirm() while one is open settles the first as false (dismissed)
 * and takes the slot — stacking modals would break the one-decision contract.
 */
export function DialogProvider({ children }: { children: ReactNode }) {
  const [confirmState, setConfirmState] = useState<{
    options: ConfirmOptions
    resolve: (value: boolean) => void
  } | null>(null)
  const [toastState, setToastState] = useState<ToastOptions | null>(null)
  const toastTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const confirm = useCallback((options: ConfirmOptions): Promise<boolean> => {
    return new Promise<boolean>((resolve) => {
      setConfirmState((previous) => {
        previous?.resolve(false) // displaced = dismissed, never left pending
        return { options, resolve }
      })
    })
  }, [])

  const toast = useCallback((options: ToastOptions): void => {
    if (toastTimer.current !== undefined) clearTimeout(toastTimer.current)
    setToastState(options)
    toastTimer.current = setTimeout(() => setToastState(null), TOAST_MS)
  }, [])

  // Unmount cleanup only — a live timer outliving the provider would setState
  // on an unmounted component.
  useEffect(() => {
    return () => {
      if (toastTimer.current !== undefined) clearTimeout(toastTimer.current)
    }
  }, [])

  const api = useMemo<DialogApi>(() => ({ confirm, toast }), [confirm, toast])

  // Dev-only manual-QA seam: lets a console session fire dialogs/toasts
  // without shipping a throwaway trigger button. import.meta.env.DEV strips
  // this from the production build entirely.
  useEffect(() => {
    if (!import.meta.env.DEV) return
    window.__citaraDialog = api
    return () => {
      delete window.__citaraDialog
    }
  }, [api])

  const settle = (value: boolean) => {
    confirmState?.resolve(value)
    setConfirmState(null)
  }

  const toastSem = toastState?.sem ?? 'success'

  return (
    <DialogContext.Provider value={api}>
      {children}

      {confirmState && (
        <ConfirmDialog
          open
          sem={confirmState.options.sem}
          icon={confirmState.options.icon}
          title={confirmState.options.title}
          body={confirmState.options.body}
          primaryLabel={confirmState.options.primaryLabel}
          secondaryLabel={confirmState.options.secondaryLabel}
          onPrimary={() => settle(true)}
          onSecondary={() => settle(false)}
        />
      )}

      {/* Toast slot: above dialogs (z-[80]) but pointer-transparent except the
          pill itself, so it never blocks interaction (design #7). */}
      {toastState && (
        <div className="pointer-events-none fixed inset-x-0 bottom-6 z-[80] flex justify-center px-4">
          <div
            role="status"
            aria-live="polite"
            className="pointer-events-auto flex items-center gap-[10px] rounded-[12px] border border-[var(--border-strong)] bg-[var(--elevated)] py-[10px] pl-[12px] pr-[14px] text-[13.5px] text-[color:var(--text)] shadow-[0_18px_50px_-12px_rgba(0,0,0,0.6)]"
          >
            <span
              className="flex h-6 w-6 items-center justify-center rounded-full"
              style={{
                backgroundColor: SEM[toastSem].tint,
                color: SEM[toastSem].fg,
              }}
            >
              {ICON[TOAST_ICON[toastSem]]}
            </span>
            <span>{toastState.message}</span>
            {toastState.action && (
              <button
                type="button"
                onClick={() => {
                  toastState.action?.onClick()
                  setToastState(null)
                }}
                className="ml-1 font-semibold"
                style={{ color: SEM[toastSem].fg }}
              >
                {toastState.action.label}
              </button>
            )}
          </div>
        </div>
      )}
    </DialogContext.Provider>
  )
}

declare global {
  interface Window {
    /** Dev-only QA seam set by DialogProvider; absent in production builds. */
    __citaraDialog?: DialogApi
  }
}
