/** Presentational Ollama connection card (sidebar top, mock Citara-Empty-Chat). */
export interface OllamaBadgeProps {
  connected: boolean
  model: string
  baseUrl: string
}

// The mock shows the bare host ("localhost:11434"); the API reports the full
// base URL — display-trim only, never used to build requests.
function stripScheme(url: string): string {
  return url.replace(/^https?:\/\//, '')
}

export function OllamaBadge({ connected, model, baseUrl }: OllamaBadgeProps) {
  return (
    <div className="rounded-md border border-border bg-surface px-[13px] py-3">
      <div className="mb-[7px] flex items-center gap-2">
        <span
          className={`h-[7px] w-[7px] rounded-full ${
            connected
              ? 'bg-ok shadow-[0_0_0_3px_rgba(70,207,166,0.18)]'
              : 'bg-warn shadow-[0_0_0_3px_rgba(230,169,92,0.18)]'
          }`}
        />
        <span className="text-[12.5px] font-semibold text-text">
          {connected ? 'Conectado a Ollama' : 'Ollama no disponible'}
        </span>
      </div>
      <div className="mb-2 font-mono text-[11px] text-muted">
        {model} · {stripScheme(baseUrl)}
      </div>
      <div className="border-t border-border pt-2 font-mono text-[11px] tracking-[0.02em] text-faint">
        Sin conexión a la nube · 100% local
      </div>
    </div>
  )
}
