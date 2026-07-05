import type { Message as ChatMessage } from '../../hooks/useChat'
import { BrandMark } from '../BrandMark'
import { AbstentionNote } from './AbstentionNote'
import { SourcesPanel } from './SourcesPanel'
import { ThinkingIndicator } from './ThinkingIndicator'

/** One chat turn, user or assistant (mocks chat-1b / 04-loading-answer). */
export interface MessageProps {
  message: ChatMessage
}

export function Message({ message }: MessageProps) {
  if (message.role === 'user') {
    return (
      <div className="flex justify-end gap-[13px]">
        <div className="max-w-[78%] rounded-[14px_14px_4px_14px] border border-border bg-surface2 px-4 py-3 text-[15px] leading-[1.55] text-text">
          {message.text}
        </div>
        <div className="flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-[9px] border border-border bg-surface font-mono text-[11px] text-muted">
          Tú
        </div>
      </div>
    )
  }

  const thinking = message.phase === 'thinking'

  // Plain streamed text for now — inline ¹ markers arrive in step 3b.
  const body = (
    <div className="text-[15px] leading-[1.72] text-text">
      {message.text}
      {message.phase === 'writing' && (
        <span
          aria-hidden="true"
          className="ml-1 inline-block h-[15px] w-[7px] animate-pulse rounded-[2px] bg-accent align-middle"
        />
      )}
    </div>
  )

  return (
    <div className="flex gap-[13px]">
      {/* The avatar pulses while thinking (mock 04's `pulse` on the logo). */}
      <div
        className={`h-8 w-8 shrink-0 ${thinking ? 'animate-citara-pulse' : ''}`}
      >
        <BrandMark size={32} />
      </div>
      <div className="min-w-0 flex-1">
        {thinking ? (
          <ThinkingIndicator />
        ) : message.phase === 'done' && message.isAbstention ? (
          <AbstentionNote>{body}</AbstentionNote>
        ) : (
          <>
            {/* On 'error' any partial text stays visible above the card. */}
            {message.text !== '' && body}
            {message.phase === 'error' && (
              <div className={`rounded-md border border-warn-line bg-warn-tint px-4 py-3 font-mono text-xs text-warn ${message.text !== '' ? 'mt-3' : ''}`}>
                {message.error}
              </div>
            )}
          </>
        )}

        {message.phase === 'done' &&
          !message.suppressCitations &&
          message.citations.length > 0 && (
            <SourcesPanel citations={message.citations} />
          )}
      </div>
    </div>
  )
}
