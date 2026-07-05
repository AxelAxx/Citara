import { Welcome } from './screens/Welcome'

// Single-screen for now: welcome↔chat routing is wired when the chat screen
// exists. The default vertical's accent is applied by Welcome itself once the
// API says which vertical comes first (src/index.css covers the first paint).
function App() {
  return (
    <Welcome
      onEnter={(verticalId) => {
        console.log(`enter chat: ${verticalId}`)
      }}
    />
  )
}

export default App
