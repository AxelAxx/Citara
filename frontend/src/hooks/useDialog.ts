import { useContext } from 'react'
import { DialogContext } from '../components/dialogContext'
import type { DialogApi } from '../components/dialogContext'

/** Access the app-wide confirm()/toast() API provided by <DialogProvider>. */
export function useDialog(): DialogApi {
  const api = useContext(DialogContext)
  if (api === null) {
    // Fail fast and loud (house rule 5): a silent no-op dialog would swallow
    // confirmations of destructive actions.
    throw new Error('useDialog() requires a <DialogProvider> above (App.tsx).')
  }
  return api
}
