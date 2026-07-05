/**
 * Boot splash — 1:1 port of the Streamlit splash markup (ui/theme.py
 * _SPLASH_HTML); the animation timeline lives in src/splash.css. No
 * window.__citaraSplashPlayed guard and no display:none reveal: those existed
 * because Streamlit reruns remount the markup mid-page-load — here App mounts
 * the splash exactly once and unmounts it on onDone.
 */
export interface SplashProps {
  /** Fired when the root fade-out finishes — the cue to unmount. */
  onDone: () => void
}

export function Splash({ onDone }: SplashProps) {
  return (
    <div
      className="citara-splash"
      role="status"
      aria-label="Cargando Citara"
      onAnimationEnd={(event) => {
        // Every child animation bubbles up here; only the root's own
        // citaraSplashOut ending means the splash has fully faded.
        if (
          event.target === event.currentTarget &&
          event.animationName === 'citaraSplashOut'
        )
          onDone()
      }}
    >
      <div className="sp-top">
        <span className="sp-badge">
          <span className="sp-dot" />
          <span className="sp-badge-text">100% local · sin nube</span>
        </span>
      </div>
      <div className="sp-logo">
        <div className="sp-halo" />
        <div className="sp-tile">
          <span className="sp-sweep" />
          <span className="sp-mark">
            <span className="sp-cee">C</span>
            <sup className="sp-one">1</sup>
          </span>
        </div>
      </div>
      <div className="sp-word">Citara</div>
      <div className="sp-rule" />
      <div className="sp-tag">Respuestas con su fuente exacta</div>
      <div className="sp-bottom">
        <div className="sp-dots">
          <span />
          <span />
          <span />
        </div>
      </div>
    </div>
  )
}
