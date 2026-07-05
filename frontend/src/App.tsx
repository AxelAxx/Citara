import { useEffect, useState } from 'react'
import { ChatLoading } from './components/ChatLoading'
import { Splash } from './components/Splash'
import { Chat } from './screens/Chat'
import { Welcome } from './screens/Welcome'
import { useEngineReady } from './hooks/useEngineReady'
import type { EnginePreload } from './hooks/useEngineReady'
import { useHealth } from './hooks/useHealth'
import { useVerticals } from './hooks/useVerticals'
import { asVerticalId, setAccent } from './theme/accent'

// Screen flow: Splash → Welcome → (Comenzar) → warm-up loading → Chat. A
// discriminated union rather than separate slots, so states like "chat
// without vertical (or without its preloaded data)" can't exist.
type View =
  | { screen: 'welcome' }
  | { screen: 'loading'; verticalId: string }
  | { screen: 'chat'; verticalId: string; preload: EnginePreload }

/**
 * Warm-up gate between welcome and chat (mock 10): keeps the fullscreen
 * loading up until warm-up AND the chat's data resolve, so the chat opens
 * hot and fully painted (same pattern as the splash covering the welcome
 * preload). A separate component because useEngineReady must only run while
 * gating.
 */
function WarmUpGate({
  verticalId,
  onReady,
  onBack,
}: {
  verticalId: string
  onReady: (preload: EnginePreload) => void
  onBack: () => void
}) {
  const { preload, error } = useEngineReady(verticalId)

  useEffect(() => {
    if (preload) onReady(preload)
  }, [preload, onReady])

  if (error) {
    // Same canvas as the loading, but the actionable failure replaces the
    // spinner — an eternal spinner would hide the fix (rule 5).
    return (
      <div
        className="fixed inset-0 z-[60] flex flex-col items-center justify-center gap-6"
        style={{
          background:
            'radial-gradient(120% 80% at 50% 38%, var(--accent-tint), transparent 60%), var(--bg2)',
        }}
      >
        <div className="w-full max-w-[480px] rounded-md border border-warn-line bg-warn-tint p-4 font-mono text-xs leading-relaxed text-warn">
          {error}
        </div>
        <button
          type="button"
          onClick={onBack}
          className="rounded-[9px] bg-accent px-[14px] py-[9px] text-[14px] font-semibold text-accent-on"
        >
          Volver
        </button>
      </div>
    )
  }

  return <ChatLoading />
}

// Boot splash and data preload run in parallel: the hooks fire on App mount,
// while the splash animation covers the fetch. The Welcome mounts only when
// BOTH finish — total wait is max(animation, fetch), never their sum — and so
// it never renders a loading state.
function App() {
  const [splashAnimationDone, setSplashAnimationDone] = useState(false)
  const [view, setView] = useState<View>({ screen: 'welcome' })
  const {
    verticals,
    loading: verticalsLoading,
    error: verticalsError,
  } = useVerticals()
  const { health } = useHealth()

  // A fetch error also readies the hand-off — the Welcome shows it; holding
  // the splash would hide the failure. health is deliberately not awaited:
  // its preflight can take seconds and only feeds the version pill.
  const ready = splashAnimationDone && !verticalsLoading

  if (!ready) return <Splash onDone={() => setSplashAnimationDone(true)} />

  if (view.screen === 'loading')
    return (
      <WarmUpGate
        verticalId={view.verticalId}
        onReady={(preload) =>
          setView({ screen: 'chat', verticalId: view.verticalId, preload })
        }
        onBack={() => setView({ screen: 'welcome' })}
      />
    )

  if (view.screen === 'chat')
    return (
      <Chat
        verticalId={view.verticalId}
        verticals={view.preload.verticals}
        health={view.preload.health}
      />
    )

  return (
    <Welcome
      verticals={verticals}
      error={verticalsError}
      health={health}
      onEnter={(verticalId) => {
        // Theme the loading halo with the chosen vertical before it mounts.
        setAccent(asVerticalId(verticalId))
        setView({ screen: 'loading', verticalId })
      }}
    />
  )
}

export default App
