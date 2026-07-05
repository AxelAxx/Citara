/**
 * "Generando respuesta" body (mock 04-loading-answer.html), shown between
 * send and the first streamed token: retrieval + prompt eval take seconds on
 * a local model, and a silent gap reads as a hang. The pulsing C¹ avatar
 * lives in Message (which owns the avatar column); this is the right-hand
 * content only.
 */
export function ThinkingIndicator() {
  const shimmer = {
    background:
      'linear-gradient(90deg,var(--surface) 0%,var(--surface2) 50%,var(--surface) 100%)',
    backgroundSize: '200% 100%',
  }

  return (
    <div role="status" aria-label="Generando respuesta">
      <div className="mb-[14px] flex items-center gap-[10px]">
        <span className="text-[14px] text-muted">
          Buscando en los documentos
        </span>
        <span className="flex gap-[3px]">
          {[0, 1, 2].map((i) => (
            <span
              key={i}
              className="h-[5px] w-[5px] animate-citara-dots rounded-full bg-accent"
              style={{ animationDelay: `${i * 0.18}s` }}
            />
          ))}
        </span>
      </div>
      <div className="mb-[9px] h-[11px] w-full animate-citara-shimmer rounded-[6px]" style={shimmer} />
      <div className="mb-[9px] h-[11px] w-[92%] animate-citara-shimmer rounded-[6px]" style={shimmer} />
      <div className="h-[11px] w-[64%] animate-citara-shimmer rounded-[6px]" style={shimmer} />
      <div className="mt-[15px] flex gap-[14px] font-mono text-[11px]">
        <span className="text-accent">✓ Recuperando fragmentos</span>
        <span className="text-faint">· Redactando con citas</span>
      </div>
    </div>
  )
}
