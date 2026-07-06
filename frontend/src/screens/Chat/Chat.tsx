import { useEffect, useRef, useState } from 'react'
import type { Health } from '../../api/client'
import { ChatHeader } from '../../components/chat/ChatHeader'
import { ChatInput } from '../../components/chat/ChatInput'
import { CorpusDrawer } from '../../components/chat/CorpusDrawer'
import { QuitDialog } from '../../components/QuitDialog'
import { quitApp } from '../../lib/quit'
import { EmptyState } from '../../components/chat/EmptyState'
import { Message } from '../../components/chat/Message'
import { SidebarToggle } from '../../components/chat/SidebarToggle'
import { Sidebar } from '../../components/Sidebar/Sidebar'
import { useChat } from '../../hooks/useChat'
import type { VerticalCorpus } from '../../hooks/useVerticals'
import { asVerticalId, setAccent } from '../../theme/accent'

export interface ChatProps {
  /** The Vertical chosen on the Welcome; the switcher can change it later. */
  verticalId: string
  /** Preloaded by the warm-up gate — Chat never fetches, so the header,
      sidebar and empty-state all paint on the first frame. */
  verticals: VerticalCorpus[]
  health: Health
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
export function Chat({ verticalId, verticals, health }: ChatProps) {
  const [activeId, setActiveId] = useState(verticalId)
  const { messages, send, isStreaming } = useChat(activeId)
  const [conversations, setConversations] = useState<Conversation[]>(() => [
    newConversation(),
  ])
  const [activeConversationId, setActiveConversationId] = useState<
    string | null
  >(null)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [corpusOpen, setCorpusOpen] = useState(false)
  const [quitDialogOpen, setQuitDialogOpen] = useState(false)
  // True once the browser refused window.close() — renders the farewell
  // notice, the only thing left to say in a tab we cannot close ourselves.
  const [quitBlocked, setQuitBlocked] = useState(false)
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

  const confirmQuit = async () => {
    setQuitDialogOpen(false)
    // 'blocked' = the browser kept the tab open (only script-opened windows
    // may close themselves) — all we can do is say goodbye.
    if ((await quitApp()) === 'blocked') setQuitBlocked(true)
  }

  return (
    <div
      className={`relative flex h-screen overflow-hidden bg-bg ${
        sidebarCollapsed ? 'side-collapsed' : ''
      }`}
    >
      {/* Straddles the sidebar's right edge while open; parks floating at the
          window's top-left once the sidebar is gone. Its `left` transitions in
          step with the sidebar width (same .24s, index.css). top 27px + half
          the 28px button = 41px, the header's vertical center (py-5 20px +
          half the 42px domain chip) — the ‹ sits on the chip's midline. The
          -14px in the calc is likewise half the button, centered on the edge. */}
      <div
        className={`absolute top-[27px] z-20 transition-[left] duration-[240ms] ease-[ease] ${
          sidebarCollapsed ? 'left-5' : 'left-[calc(var(--sidebar-w)-14px)]'
        }`}
      >
        <SidebarToggle
          collapsed={sidebarCollapsed}
          onToggle={() => setSidebarCollapsed((prev) => !prev)}
        />
      </div>

      <Sidebar
        verticals={verticals}
        selectedId={activeId}
        onSelect={setActiveId}
        health={health}
        conversations={conversations}
        activeConversationId={activeConversation?.id ?? null}
        onSelectConversation={setActiveConversationId}
        onNewConversation={startConversation}
        onManageCorpus={() => setCorpusOpen(true)}
        onQuit={() => setQuitDialogOpen(true)}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        {selected && (
          <ChatHeader
            letter={selected.view.domain_letter}
            domainName={selected.view.domain_name}
            tagline={selected.view.domain_tagline}
            documentCount={selected.documentCount}
            model={health.ok ? health.llm_model : '—'}
          />
        )}

        {messages.length === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center overflow-y-auto px-10 py-12">
            {selected && (
              <EmptyState
                suggestions={selected.view.example_questions}
                onSelect={send}
              />
            )}
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto px-[34px] py-8">
            <div className="mx-auto flex w-full max-w-[760px] flex-col gap-[26px]">
              {messages.map((message, index) => (
                <Message
                  key={index}
                  message={message}
                  // The abstention literal published by /health (core's single
                  // source of truth) — feeds the transient streaming cleanup.
                  abstentionText={health.ok ? health.abstention_text : null}
                />
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

      {/* Data comes from the /corpus already loaded for this vertical (via
          VerticalCorpus.documentIds) — opening the drawer never refetches. */}
      {selected && (
        <CorpusDrawer
          open={corpusOpen}
          onClose={() => setCorpusOpen(false)}
          verticalId={selected.view.id}
          domainName={selected.view.domain_name}
          documentCount={selected.documentCount}
          chunkCount={selected.chunkCount}
          documents={selected.documentIds}
        />
      )}

      <QuitDialog
        open={quitDialogOpen}
        onCancel={() => setQuitDialogOpen(false)}
        onConfirm={confirmQuit}
      />

      {/* Farewell for the browser-blocked quit path: quitApp() already tried
          window.close(); the tab is now the user's to close. */}
      {quitBlocked && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-[var(--bg)]">
          <p className="px-6 text-center font-serif text-[19px] text-[color:var(--text)]">
            Puedes cerrar esta ventana. Hasta pronto.
          </p>
        </div>
      )}
    </div>
  )
}
