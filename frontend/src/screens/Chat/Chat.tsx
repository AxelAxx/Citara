import { useEffect, useState } from 'react'
import { ChatHeader } from '../../components/chat/ChatHeader'
import { EmptyState } from '../../components/chat/EmptyState'
import { Sidebar } from '../../components/Sidebar/Sidebar'
import { useHealth } from '../../hooks/useHealth'
import { useVerticals } from '../../hooks/useVerticals'
import { asVerticalId, setAccent } from '../../theme/accent'

export interface ChatProps {
  /** The Vertical chosen on the Welcome; the switcher can change it later. */
  verticalId: string
}

/**
 * Conversations are client-side ONLY: the API is stateless (no history
 * endpoint), so the list lives in Chat's state and dies with the page.
 */
export interface Conversation {
  id: string
  title: string
  time: string
  /** Message history lands with the streaming step. */
  messages: unknown[]
}

function newConversation(): Conversation {
  return {
    id: crypto.randomUUID(),
    title: 'Nueva consulta',
    time: 'ahora',
    messages: [],
  }
}

/**
 * Chat screen shell (mock: Citara-Empty-Chat / sidebar.html), step 1 of 4:
 * sidebar + header — message list and composer land in the next steps, so
 * the chat area is an explicit placeholder. Orchestration: hooks feed the
 * Sidebar and ChatHeader; switching domain re-themes via setAccent.
 */
export function Chat({ verticalId }: ChatProps) {
  const { verticals, error } = useVerticals()
  const { health } = useHealth()
  const [activeId, setActiveId] = useState(verticalId)
  const [conversations, setConversations] = useState<Conversation[]>(() => [
    newConversation(),
  ])
  const [activeConversationId, setActiveConversationId] = useState<
    string | null
  >(null)
  // Suggestion picks land here until the real composer (step 3) consumes them.
  const [draft, setDraft] = useState('')

  const selected = verticals.find((v) => v.view.id === activeId) ?? null
  // Default to the newest conversation until one is explicitly picked.
  const activeConversation =
    conversations.find((c) => c.id === activeConversationId) ??
    conversations[0] ??
    null

  // Covers both the id inherited from the Welcome and switcher changes.
  useEffect(() => {
    setAccent(asVerticalId(activeId))
  }, [activeId])

  const startConversation = () => {
    const conversation = newConversation()
    // Newest first, like the mock's session list.
    setConversations((prev) => [conversation, ...prev])
    setActiveConversationId(conversation.id)
  }

  return (
    <div className="flex h-screen overflow-hidden bg-bg">
      <Sidebar
        verticals={verticals}
        selectedId={activeId}
        onSelect={setActiveId}
        health={health}
        conversations={conversations}
        activeConversationId={activeConversation?.id ?? null}
        onSelectConversation={setActiveConversationId}
        onNewConversation={startConversation}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        {selected && (
          <ChatHeader
            letter={selected.view.domain_letter}
            domainName={selected.view.domain_name}
            tagline={selected.view.domain_tagline}
            documentCount={selected.documentCount}
            model={health?.ok ? health.llm_model : '—'}
          />
        )}

        {/* Always the empty state in this step; the message list replaces it
            in step 3 when a conversation has messages. */}
        <div className="flex flex-1 flex-col items-center justify-center overflow-y-auto px-10 py-12">
          {error ? (
            <div className="w-full max-w-[640px] rounded-md border border-warn-line bg-warn-tint p-4 font-mono text-xs text-warn">
              {error}
            </div>
          ) : (
            selected && (
              <EmptyState
                suggestions={selected.view.example_questions}
                onSelect={setDraft}
              />
            )
          )}
        </div>

        {/* Placeholder: the composer arrives in step 3; it will consume draft. */}
        <div className="border-t border-border px-[34px] py-4 text-center font-mono text-xs text-faint">
          {draft || 'input — paso 3'}
        </div>
      </main>
    </div>
  )
}
