import { useId, useState } from 'react'
import type { ReactNode } from 'react'
import type { Message as ChatMessage } from '../../hooks/useChat'
import { BrandMark } from '../BrandMark'
import { AbstentionNote } from './AbstentionNote'
import { CiteChip } from './CiteChip'
import { SourcesPanel } from './SourcesPanel'
import type { SourceFocus } from './SourcesPanel'
import { ThinkingIndicator } from './ThinkingIndicator'

/** One chat turn, user or assistant (mocks chat-1b / 04-loading-answer). */
export interface MessageProps {
  message: ChatMessage
}

// The 7B model emits [N] markers inline in the answer text; valid ones render
// as CiteChips in place and malformed/out-of-range ones ([12] with 5 sources,
// a verbatim "[N]") are dropped whole — a marker without a real source behind
// it is model garbage, not a citation. While streaming, an unfinished "[1"
// stays plain text until its "]" arrives (only COMPLETE markers parse).
// NOTE: this parsing lives here TEMPORARILY as a pragmatic shortcut — it
// moves into core (AnswerParts) with the full 3b step.
const MARKER_RE = /\[(\d+|N)\]/g

function renderTextWithCites(
  text: string,
  numCitations: number,
  msgId: string,
  onCite: (n: number) => void,
): ReactNode[] {
  const nodes: ReactNode[] = []
  let cursor = 0
  for (const match of text.matchAll(MARKER_RE)) {
    const index = match.index ?? 0
    if (index > cursor) nodes.push(text.slice(cursor, index))
    const n = Number(match[1])
    // Number("N") is NaN, so the literal "[N]" fails this check and is
    // dropped through the same fail-fast gate as out-of-range numbers.
    if (Number.isInteger(n) && n >= 1 && n <= numCitations) {
      nodes.push(
        <button
          key={`${index}-${n}`}
          type="button"
          id={`cite-${msgId}-${n}`}
          aria-label={`Ver fuente ${n}`}
          onClick={() => onCite(n)}
          className="mx-[2px] inline-flex"
        >
          <CiteChip n={n} variant="inline" />
        </button>,
      )
    }
    cursor = index + match[0].length
  }
  if (cursor < text.length) nodes.push(text.slice(cursor))
  return nodes
}

export function Message({ message }: MessageProps) {
  // Hooks before the user-branch early return (rules of hooks); a message's
  // role never changes across renders, but the order must not depend on it.
  const msgId = useId()
  const [sourceFocus, setSourceFocus] = useState<SourceFocus | null>(null)

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

  // key bumps on every click so re-clicking the same chip re-triggers the
  // panel's reveal/flash effect.
  const focusSource = (n: number) =>
    setSourceFocus((prev) => ({ n, key: (prev?.key ?? 0) + 1 }))

  const body = (
    <div className="text-[15px] leading-[1.72] text-text">
      {renderTextWithCites(
        message.text,
        message.citations.length,
        msgId,
        focusSource,
      )}
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
            <SourcesPanel
              citations={message.citations}
              msgId={msgId}
              focus={sourceFocus}
            />
          )}
      </div>
    </div>
  )
}
