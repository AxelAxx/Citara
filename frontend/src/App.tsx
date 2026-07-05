import { useState } from 'react'
import { Splash } from './components/Splash'
import { Chat } from './screens/Chat'
import { Welcome } from './screens/Welcome'
import { useHealth } from './hooks/useHealth'
import { useVerticals } from './hooks/useVerticals'

// Screen flow: Splash → Welcome → Chat. A discriminated union rather than two
// state slots, so a "chat without vertical" state can't exist.
type View = { screen: 'welcome' } | { screen: 'chat'; verticalId: string }

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

  if (view.screen === 'chat') return <Chat verticalId={view.verticalId} />

  return (
    <Welcome
      verticals={verticals}
      error={verticalsError}
      health={health}
      onEnter={(verticalId) => setView({ screen: 'chat', verticalId })}
    />
  )
}

export default App
