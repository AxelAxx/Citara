import { useEffect, useState } from 'react'
import type { Health } from '../../api/client'
import { BrandMark } from '../../components/BrandMark'
import { DomainCard } from '../../components/DomainCard'
import { PrivacyPill } from '../../components/PrivacyPill'
import type { VerticalCorpus } from '../../hooks/useVerticals'
import { asVerticalId, setAccent } from '../../theme/accent'

// UI release label, not API data — bump by hand alongside releases.
const CITARA_VERSION = '0.4'

export interface WelcomeProps {
  /** Fired by the CTA; the chat screen wires real routing here later. */
  onEnter: (verticalId: string) => void
  /** Preloaded by App during the splash — already settled when this mounts. */
  verticals: VerticalCorpus[]
  error: string | null
  /** May still be in flight (slow Ollama preflight); the pill fills in late. */
  health: Health | null
}

/**
 * Welcome / domain-choice screen (mock: Citara_Bienvenida). Presentational
 * orchestration: App owns the data hooks and hands the results in as props,
 * so no loading state exists here. The mock's numbers ("14 documentos",
 * "llama3.1") are placeholders — corpus counts and LLM model are live values.
 */
export function Welcome({ onEnter, verticals, error, health }: WelcomeProps) {
  const [pickedId, setPickedId] = useState<string | null>(null)

  // Derived, not synced: "first vertical until the user picks" needs no
  // state-writing effect, and the API decides which vertical is first.
  const selected =
    verticals.find((v) => v.view.id === pickedId) ?? verticals[0] ?? null

  // One code path themes both the API-driven default and later picks.
  useEffect(() => {
    if (selected) setAccent(asVerticalId(selected.view.id))
  }, [selected])

  return (
    <div
      className="relative flex min-h-screen w-full flex-col items-center justify-center px-8 py-16"
      style={{
        // Inline because Tailwind can't compose a var()-driven radial halo;
        // the tint var keeps the glow tracking the active vertical live.
        background:
          'radial-gradient(120% 80% at 50% -10%, var(--accent-tint), transparent 55%), var(--bg)',
      }}
    >
      <div className="fixed left-6 top-6">
        <PrivacyPill text="100% local · sin conexión a la nube" />
      </div>
      <div className="fixed right-6 top-6 font-mono text-[11px] text-faint">
        Citara v{CITARA_VERSION}
        {health?.ok ? ` · ${health.llm_model}` : ''}
      </div>

      <div className="w-full max-w-[540px] text-center">
        <div className="mb-6 flex flex-col items-center gap-3.5">
          <BrandMark />
          <span className="font-serif text-[17px] font-semibold">Citara</span>
        </div>

        <h1 className="mb-3.5 font-serif text-[42px] font-semibold leading-[1.12] tracking-[-0.02em]">
          Pregunta a tus
          <br />
          documentos.
        </h1>
        <p className="mx-auto mb-[34px] max-w-[430px] text-base leading-[1.6] text-muted">
          Citara responde en español basándose{' '}
          <strong className="font-semibold text-text">solo</strong> en tus
          documentos, y cita la fuente exacta de cada afirmación. Todo el
          procesamiento ocurre en tu equipo.
        </p>

        <div className="mb-3 font-mono text-[11px] uppercase tracking-[0.07em] text-faint">
          Elige un dominio para empezar
        </div>

        {error ? (
          <div className="mb-[26px] rounded-md border border-warn-line bg-warn-tint p-4 text-left font-mono text-xs text-warn">
            {error}
          </div>
        ) : (
          <div className="mb-[26px] grid grid-cols-2 gap-3">
            {verticals.map((v) => (
              <DomainCard
                key={v.view.id}
                letter={v.view.domain_letter}
                name={v.view.domain_name}
                meta={`${v.view.domain_sublabel} · ${v.documentCount} ${
                  v.documentCount === 1 ? 'documento' : 'documentos'
                }`}
                active={v.view.id === selected?.view.id}
                onSelect={() => setPickedId(v.view.id)}
              />
            ))}
          </div>
        )}

        <button
          type="button"
          disabled={!selected}
          onClick={() => selected && onEnter(selected.view.id)}
          className="flex w-full items-center justify-center gap-2 rounded-[13px] bg-accent p-[15px] text-[15px] font-semibold text-accent-on disabled:cursor-default disabled:opacity-50"
        >
          Comenzar{selected ? ` · ${selected.view.domain_name}` : ''}{' '}
          <span className="text-[16px]">→</span>
        </button>
        <div className="mt-4 text-xs text-faint">
          No se envía nada a internet · sin telemetría · sin cuentas
        </div>
      </div>
    </div>
  )
}
