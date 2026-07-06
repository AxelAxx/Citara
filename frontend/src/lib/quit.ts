/**
 * Environment-aware app quit, isolated from all UI.
 *
 * Desktop runtime is post-migration (ADR-002): today we run in a browser tab,
 * so BOTH desktop branches are guarded behind runtime detection — they no-op
 * in the web build and light up on their own once the app ships packaged.
 * Nothing here invents a preload or a Tauri global that doesn't exist.
 */

declare global {
  interface Window {
    /** Injected by the future Electron preload via contextBridge (never
        `remote`). Absent today — hence the optional chaining at the call. */
    electronAPI?: { quitApp?: () => void }
    /** Set by the Tauri runtime inside a packaged window. Absent today. */
    __TAURI__?: unknown
  }
}

export type QuitOutcome = 'quitting' | 'blocked'

export async function quitApp(): Promise<QuitOutcome> {
  // Future cleanup hook (persist prefs/session before exit). Deliberately a
  // documented no-op today: conversations are client-side memory with no
  // persistence endpoint yet — there is nothing to save.

  if (window.electronAPI?.quitApp) {
    window.electronAPI.quitApp()
    return 'quitting'
  }

  if (window.__TAURI__) {
    // Non-literal specifier + @vite-ignore: the plugin is only installed in
    // the packaged desktop build; a literal import would break the web
    // build/typecheck where the dependency doesn't exist.
    const specifier = '@tauri-apps/plugin-process'
    const mod = (await import(/* @vite-ignore */ specifier)) as {
      exit: (code: number) => Promise<void>
    }
    await mod.exit(0)
    return 'quitting'
  }

  // Browser fallback: window.close() only succeeds for script-opened windows;
  // user-opened tabs block it silently. Give the browser a beat, then report
  // the outcome so the caller can render the farewell notice instead.
  window.close()
  return new Promise((resolve) => {
    window.setTimeout(() => {
      resolve(window.closed ? 'quitting' : 'blocked')
    }, 100)
  })
}
