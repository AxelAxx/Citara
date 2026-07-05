import { useState } from 'react'
import { Splash } from './components/Splash'
import { Welcome } from './screens/Welcome'
import { useHealth } from './hooks/useHealth'
import { useVerticals } from './hooks/useVerticals'

// Boot splash and data preload run in parallel: the hooks fire on App mount,
// while the splash animation covers the fetch. The Welcome mounts only when
// BOTH finish — total wait is max(animation, fetch), never their sum — and so
// it never renders a loading state. welcome↔chat routing arrives with chat.
function App() {
  const [splashAnimationDone, setSplashAnimationDone] = useState(false)
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

  return !ready ? (
    <Splash onDone={() => setSplashAnimationDone(true)} />
  ) : (
    <Welcome
      verticals={verticals}
      error={verticalsError}
      health={health}
      onEnter={(verticalId) => {
        console.log(`enter chat: ${verticalId}`)
      }}
    />
  )
}

export default App
