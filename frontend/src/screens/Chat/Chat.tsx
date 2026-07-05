import { useEffect, useRef, useState } from 'react'
import { ChatHeader } from '../../components/chat/ChatHeader'
import { ChatInput } from '../../components/chat/ChatInput'
import { EmptyState } from '../../components/chat/EmptyState'
import { Message } from '../../components/chat/Message'
import { Sidebar } from '../../components/Sidebar/Sidebar'
import { useChat } from '../../hooks/useChat'
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
 * Chat screen (mocks: empty-1b / chat-1b), step 3a: functional streaming.
 * Orchestration only — useChat isolates the SSE, the components render.
 * Suggestion picks and the composer both funnel into the same send().
 */
export function Chat({ verticalId }: ChatProps) {
  const { verticals, error } = useVerticals()
  const { health } = useHealth()
  const [activeId, setActiveId] = useState(verticalId)
  const { messages, send, isStreaming } = useChat(activeId)
  const [conversations, setConversations] = useState<Conversation[]>(() => [
    newConversation(),
  ])
  const [activeConversationId, setActiveConversationId] = useState<
    string | null
  >(null)
  const bottomRef = useRef<HTMLDivElement | null>(null)

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

  // Fires on every token batch too, so the newest text stays in view while
  // the answer types itself out.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' })
  }, [messages])

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

        {messages.length === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center overflow-y-auto px-10 py-12">
            {error ? (
              <div className="w-full max-w-[640px] rounded-md border border-warn-line bg-warn-tint p-4 font-mono text-xs text-warn">
                {error}
              </div>
            ) : (
              selected && (
                <EmptyState
                  suggestions={selected.view.example_questions}
                  onSelect={send}
                />
              )
            )}
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto px-[34px] py-8">
            <div className="mx-auto flex w-full max-w-[760px] flex-col gap-[26px]">
              {messages.map((message, index) => (
                <Message key={index} message={message} />
              ))}
              <div ref={bottomRef} />
            </div>
          </div>
        )}

        <ChatInput
          onSubmit={send}
          disabled={isStreaming}
          placeholder={
            selected
              ? `Escribe tu pregunta sobre ${selected.view.domain_name.toLowerCase()}…`
              : 'Escribe tu pregunta…'
          }
        />
      </main>
    </div>
  )
}
