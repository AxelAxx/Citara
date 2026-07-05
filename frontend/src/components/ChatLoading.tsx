import { BrandMark } from './BrandMark'
import './ChatLoading.css'

/**
 * Fullscreen warm-up overlay (mock 10-fullscreen-loading + citara.css
 * .fs-load): same halo-over-bg2 canvas as the splash, but with a spinner —
 * this one has no fixed duration, it stays until the engine preflight
 * resolves. Presentational; the accent vars carry the chosen vertical.
 */
export interface ChatLoadingProps {
  label?: string
}

export function ChatLoading({ label = 'Calentando motores…' }: ChatLoadingProps) {
  return (
    <div
      role="status"
      aria-label={label}
      className="fixed inset-0 z-[60] flex flex-col items-center justify-center gap-7"
      style={{
        background:
          'radial-gradient(120% 80% at 50% 38%, var(--accent-tint), transparent 60%), var(--bg2)',
      }}
    >
      <div className="flex flex-col items-center gap-[18px]">
        <div className="animate-citara-float">
          <BrandMark size={124} />
        </div>
        <span className="font-serif text-[22px] font-semibold text-text">
          Citara
        </span>
      </div>
      <div className="citara-spinner" />
      <div className="text-center">
        <div className="text-[15px] font-semibold text-text">{label}</div>
        <div className="mt-[5px] font-mono text-xs text-muted">
          Preparando el modelo · todo en local
        </div>
      </div>
    </div>
  )
}
