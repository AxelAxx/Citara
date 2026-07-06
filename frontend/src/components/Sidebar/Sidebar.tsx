import type { Health } from '../../api/client'
import type { VerticalCorpus } from '../../hooks/useVerticals'
import { CITARA_VERSION } from '../../version'
import { QuitButton } from '../chat/QuitButton'
import { BrandMark } from '../BrandMark'
import { DomainCard } from '../DomainCard'
import { ConversationList } from './ConversationList'
import type { ConversationSummary } from './ConversationList'
import { CorpusBlock } from './CorpusBlock'
import { OllamaBadge } from './OllamaBadge'

export interface SidebarProps {
  verticals: VerticalCorpus[]
  selectedId: string
  onSelect: (verticalId: string) => void
  health: Health | null
  conversations: ConversationSummary[]
  activeConversationId: string | null
  onSelectConversation: (id: string) => void
  onNewConversation: () => void
  /** "Gestionar corpus" → opens the CorpusDrawer (state in Chat.tsx). */
  onManageCorpus: () => void
  /** "Salir de Citara" → opens the QuitDialog (state in Chat.tsx). */
  onQuit: () => void
}

/**
 * Chat sidebar (mock: Citara-Empty-Chat): wordmark, Ollama badge, domain
 * switcher, corpus status, footer. Presentational — all data arrives as
 * props; the switcher reuses the Welcome's DomainCard. Deliberately no
 * "Conversaciones" block: the API keeps no history (confirmed out of scope).
 */
export function Sidebar({
  verticals,
  selectedId,
  onSelect,
  health,
  conversations,
  activeConversationId,
  onSelectConversation,
  onNewConversation,
  onManageCorpus,
  onQuit,
}: SidebarProps) {
  const selected = verticals.find((v) => v.view.id === selectedId) ?? null

  // Width comes from --sidebar-w so the collapse rule (index.css) slides out
  // by exactly the same distance without duplicating the 296.
  return (
    <aside className="chat-sidebar flex h-full w-[var(--sidebar-w)] shrink-0 flex-col overflow-y-auto border-r border-border bg-bg2 px-[18px] py-[22px]">
      <div className="mb-[18px] flex items-center gap-[11px] px-1">
        <BrandMark size={38} />
        <div className="leading-[1.15]">
          <div className="font-serif text-[18px] font-semibold">Citara</div>
          <div className="text-[11.5px] text-faint">Respuestas con fuente</div>
        </div>
      </div>

      <div className="mb-[22px]">
        <OllamaBadge
          connected={health?.ok === true}
          model={health?.ok ? health.llm_model : '—'}
          baseUrl={health?.ok ? health.ollama_base_url : '—'}
        />
      </div>

      <div className="px-1 pb-[10px] font-mono text-[11px] uppercase tracking-[0.07em] text-faint">
        Dominio activo
      </div>
      <div className="flex flex-col gap-[9px]">
        {verticals.map((v) => (
          <DomainCard
            key={v.view.id}
            variant="row"
            letter={v.view.domain_letter}
            name={v.view.domain_name}
            meta={`${v.view.domain_sublabel} · ${v.documentCount} ${
              v.documentCount === 1 ? 'documento' : 'documentos'
            }`}
            active={v.view.id === selectedId}
            onSelect={() => onSelect(v.view.id)}
          />
        ))}
      </div>

      {selected && (
        <CorpusBlock
          ready={selected.documentCount > 0}
          documentCount={selected.documentCount}
          chunkCount={selected.chunkCount}
          onManage={onManageCorpus}
        />
      )}

      <ConversationList
        conversations={conversations}
        activeId={activeConversationId}
        onSelect={onSelectConversation}
        onNew={onNewConversation}
      />

      <div className="mt-auto border-t border-border px-1 pt-[14px] text-[11px] leading-[1.5] text-faint">
        Citara v{CITARA_VERSION} — todo el procesamiento ocurre en tu equipo.
        <QuitButton onClick={onQuit} />
      </div>
    </aside>
  )
}
