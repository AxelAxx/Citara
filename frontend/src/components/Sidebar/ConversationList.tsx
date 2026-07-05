/**
 * Presentational "Conversaciones" section (mock sidebar.html). Client-side
 * only by design: the API keeps no history, so conversations live and die in
 * the front — this component just renders whatever list it is handed.
 */
export interface ConversationSummary {
  id: string
  title: string
  time: string
}

export interface ConversationListProps {
  conversations: ConversationSummary[]
  activeId: string | null
  onSelect: (id: string) => void
  onNew: () => void
}

export function ConversationList({
  conversations,
  activeId,
  onSelect,
  onNew,
}: ConversationListProps) {
  return (
    <div className="flex min-h-0 flex-col">
      <div className="flex items-center justify-between px-1 pb-[10px] pt-[22px]">
        <span className="font-mono text-[11px] uppercase tracking-[0.07em] text-faint">
          Conversaciones
        </span>
        <button type="button" onClick={onNew} className="text-[11.5px] text-accent">
          + Nueva
        </button>
      </div>
      <div className="flex flex-col gap-[3px] overflow-y-auto">
        {conversations.map((c) => (
          <button
            key={c.id}
            type="button"
            onClick={() => onSelect(c.id)}
            /* Both states carry a border so activation never shifts the layout. */
            className={`flex w-full flex-col gap-[2px] rounded-[9px] border px-[11px] py-[9px] text-left transition-all ${
              c.id === activeId
                ? 'border-accent-line bg-surface2'
                : 'border-transparent'
            }`}
          >
            <span className="overflow-hidden text-ellipsis whitespace-nowrap text-[13.5px] font-medium text-text">
              {c.title}
            </span>
            <span className="font-mono text-[10px] text-faint">{c.time}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
