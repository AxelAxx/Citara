import { useId, useState } from 'react'
import type { ReactNode } from 'react'
import type { AnswerPart } from '../../api/client'
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
  /** The abstention literal from /health (core's single source of truth),
      used only by the transient streaming cleanup. null (not yet loaded, or
      health ok:false) degrades gracefully: only raw [N] markers are hidden. */
  abstentionText: string | null
}

// Transient cosmetic cleanup for the LIVE stream only: raw "[1]" markers (and
// the echoed "[N]" template, and an unfinished trailing "[1" whose "]" hasn't
// arrived) are hidden so marker syntax never flashes while the model writes.
// Nothing is validated and no chips are built here — the authoritative render
// comes from the done event's `parts`, parsed and validated by core.
const RAW_MARKER_RE = /\[(?:\d+|N)\]/g
const TRAILING_PARTIAL_MARKER_RE = /\[(?:\d+|N)?$/

// The 7B sometimes appends the abstention sentence after a cited answer; core
// strips it from the final parts, but its tokens still stream in live. Hiding
// a trailing PREFIX of the sentence (it arrives token by token) keeps it from
// flashing mid-write; if more prose follows, the run is no longer trailing and
// reappears — cosmetic and self-correcting, like the marker hide above. The
// literal arrives from /health (core's single source of truth) — never
// redefined here.
function hideTrailingAbstention(text: string, abstentionText: string): string {
  const trimmed = text.trimEnd()
  const max = Math.min(abstentionText.length, trimmed.length)
  for (let len = max; len > 0; len--) {
    if (trimmed.endsWith(abstentionText.slice(0, len))) {
      // trimEnd: drop the blank lines that preceded the hidden sentence too,
      // so the live cursor doesn't sit under a stray empty paragraph.
      const remaining = trimmed.slice(0, trimmed.length - len).trimEnd()
      // Mirror of core's cited-only rule: hide the sentence only when prose
      // precedes it. A PURE abstention (the sentence alone, e.g. the guard
      // path) must stay visible — hiding it would blank the whole message.
      return remaining === '' ? text : remaining
    }
  }
  return text
}

function hideRawMarkers(text: string, abstentionText: string | null): string {
  const noMarkers = text
    .replace(RAW_MARKER_RE, '')
    .replace(TRAILING_PARTIAL_MARKER_RE, '')
  // No phrase yet (health still loading, or ok:false) → markers-only cleanup.
  // Graceful: this hide is cosmetic, its momentary absence breaks nothing.
  return abstentionText === null
    ? noMarkers
    : hideTrailingAbstention(noMarkers, abstentionText)
}

// The final render: a straight map over core's typed parts — no marker
// parsing in the front (that shortcut is gone; core owns it). Every CitePart's
// n was already validated and remapped against the citations list, so a chip
// here always resolves to citations[n-1].
function renderParts(
  parts: AnswerPart[],
  msgId: string,
  onCite: (n: number) => void,
): ReactNode[] {
  return parts.map((part, index) =>
    part.kind === 'text' ? (
      part.text
    ) : (
      <button
        key={`${index}-${part.n}`}
        type="button"
        id={`cite-${msgId}-${part.n}`}
        aria-label={`Ver fuente ${part.n}`}
        onClick={() => onCite(part.n)}
        className="mx-[2px] inline-flex"
      >
        <CiteChip n={part.n} variant="inline" />
      </button>
    ),
  )
}

export function Message({ message, abstentionText }: MessageProps) {
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

  // Two render modes by phase: while writing, the accumulated raw text with
  // markers cosmetically hidden; on done, the typed parts (chips in place,
  // text already stripped of the abstention tail by core). Plain cleaned text
  // stays as the fallback for 'error' partials and a done without parts.
  const body = (
    <div className="text-[15px] leading-[1.72] text-text">
      {message.phase === 'done' && message.parts
        ? renderParts(message.parts, msgId, focusSource)
        : hideRawMarkers(message.text, abstentionText)}
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
