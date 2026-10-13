import { useEffect } from 'react'
import { formatThousands } from '../../lib/format'

export interface CorpusDrawerProps {
  open: boolean
  onClose: () => void
  /** Active vertical's id — rendered into the real CLI command, no hardcode. */
  verticalId: string
  domainName: string
  documentCount: number
  chunkCount: number
  /** Real ingested document_ids from /corpus — never invented client-side. */
  documents: string[]
}

/**
 * Right-hand "Gestión de corpus" drawer (mock: Citara-Chat.html), READ-ONLY
 * by design: ingestion has no endpoint (offline CLI, SPEC §8), so the mock's
 * drop-zone becomes an informative note — a functional-looking upload that
 * cannot happen would lie to the user. Presentational: all data via props,
 * open/close state lives in Chat.tsx.
 */
export function CorpusDrawer({
  open,
  onClose,
  verticalId,
  domainName,
  documentCount,
  chunkCount,
  documents,
}: CorpusDrawerProps) {
  // Escape closes, like the mock. The listener only exists while open (and
  // is removed on unmount/close) so a closed drawer never eats keystrokes.
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-[60] flex justify-end bg-black/50"
      onClick={(event) => {
        // Only a click on the backdrop itself closes; clicks inside the panel
        // arrive here with a different target and are ignored.
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Gestión de corpus"
        className="corpus-drawer flex h-full w-[min(520px,96vw)] flex-col border-l border-[var(--border-strong)] bg-[var(--surface)] shadow-[-22px_0_70px_-22px_rgba(0,0,0,0.65)]"
      >
        <div className="flex items-start justify-between gap-4 border-b border-[var(--border)] px-6 py-5">
          <div className="min-w-0">
            <div className="font-mono text-[11px] uppercase tracking-[0.07em] text-[color:var(--faint)]">
              Gestión de corpus
            </div>
            <div className="mt-[6px] truncate font-serif text-[19px] font-semibold text-[color:var(--text)]">
              {domainName}
            </div>
            <div className="mt-1 font-mono text-[11px] text-[color:var(--muted)]">
              {formatThousands(documentCount)} docs ·{' '}
              {formatThousands(chunkCount)} fragmentos
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Cerrar"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[8px] border border-[var(--border)] text-[13px] text-[color:var(--muted)] transition-colors hover:border-[var(--border-strong)] hover:text-[color:var(--text)]"
          >
            ✕
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {/* CLI-ingestion note in the drop-zone's visual slot (dashed box). */}
          <div className="flex items-start gap-3 rounded-md border border-dashed border-[var(--border-strong)] px-4 py-4">
            <svg
              width="16"
              height="16"
              viewBox="0 0 16 16"
              fill="none"
              aria-hidden="true"
              className="mt-[2px] shrink-0 text-[color:var(--faint)]"
            >
              <path
                d="M3 5l3 3-3 3"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d="M8 12h5"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
            </svg>
            <div className="min-w-0">
              <div className="text-[13px] leading-[1.5] text-[color:var(--muted)]">
                La ingesta se realiza por línea de comandos
              </div>
              <code className="mt-[6px] block truncate font-mono text-[11.5px] text-[color:var(--faint)]">
                python -m core.ingest --vertical {verticalId}
              </code>
            </div>
          </div>

          <div className="mt-6">
            <div className="pb-[10px] font-mono text-[11px] uppercase tracking-[0.07em] text-[color:var(--faint)]">
              Documentos ({documentCount})
            </div>
            {documents.length === 0 ? (
              <div className="text-[13px] text-[color:var(--faint)]">
                Sin documentos ingestados.
              </div>
            ) : (
              <ul className="flex flex-col gap-2">
                {documents.map((id) => (
                  <li
                    key={id}
                    className="flex items-center gap-[10px] rounded-[9px] border border-[var(--border)] bg-[var(--surface2)] px-3 py-[9px]"
                  >
                    <svg
                      width="14"
                      height="14"
                      viewBox="0 0 16 16"
                      fill="none"
                      aria-hidden="true"
                      className="shrink-0 text-[color:var(--faint)]"
                    >
                      <path
                        d="M4 1.5h5.5L13 5v9.5H4z"
                        stroke="currentColor"
                        strokeWidth="1.3"
                        strokeLinejoin="round"
                      />
                      <path
                        d="M9.5 1.5V5H13"
                        stroke="currentColor"
                        strokeWidth="1.3"
                        strokeLinejoin="round"
                      />
                    </svg>
                    <span className="min-w-0 truncate font-mono text-[12px] text-[color:var(--muted)]">
                      {id}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
