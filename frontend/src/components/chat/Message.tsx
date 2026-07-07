import { useId, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
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
      used only by the transient streaming cleanup below. null (not yet
      loaded, or health ok:false) degrades gracefully: no live cleanup. */
  abstentionText: string | null
}

// The ONLY transient cleanup left for the LIVE stream. Since the citation
// redesign the model writes clean prose — no raw [N] markers can arrive, so
// the old marker-hiding regexes are gone. What CAN still stream in is the
// abstention sentence appended after a real answer (the 7B's mixed failure
// mode): core strips it from the FINAL view (the done event's parts), but its
// tokens hit the wire live. Hiding a trailing PREFIX of the sentence (it
// arrives token by token) keeps it from flashing mid-write; if more prose
// follows, the run is no longer trailing and reappears — cosmetic and
// self-correcting. The literal arrives from /health (core's single source of
// truth) — never redefined here; null (still loading) → no cleanup, harmless.
function hideTrailingAbstention(
  text: string,
  abstentionText: string | null,
): string {
  if (abstentionText === null) return text
  const trimmed = text.trimEnd()
  const max = Math.min(abstentionText.length, trimmed.length)
  for (let len = max; len > 0; len--) {
    if (trimmed.endsWith(abstentionText.slice(0, len))) {
      // trimEnd: drop the blank lines that preceded the hidden sentence too,
      // so the live cursor doesn't sit under a stray empty paragraph.
      const remaining = trimmed.slice(0, trimmed.length - len).trimEnd()
      // Mirror of core's rule: hide the sentence only when prose precedes
      // it. A PURE abstention (the sentence alone, e.g. the guard path)
      // must stay visible — hiding it would blank the whole message.
      return remaining === '' ? text : remaining
    }
  }
  return text
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
  // Entry-stagger order: every chip in the message mounts in the same commit
  // (the done event), so their CSS entry animation needs an explicit sequence
  // — --cite-i feeds .cite-chip-in's animation-delay (inherits to the chip).
  // Counts cite parts only, not all parts: text between chips must not
  // stretch the gaps.
  let citeOrder = 0
  return parts.map((part, index) =>
    part.kind === 'text' ? (
      parts[index + 1]?.kind === 'cite' ? (
        // The sentence that anchors the next chip flashes as the chip fades
        // in (cite-flash, index.css) so the citation doesn't pop out of inert
        // text. Same --cite-i as that chip: citeOrder is read BEFORE the
        // chip's ++ so both share the stagger slot and pulse together. The
        // whole TextPart is wrapped — core already splits the prose at cite
        // boundaries, so re-segmenting sentences here would be redundant.
        // Purely presentational: the text stays verbatim.
        <span
          key={`t-${index}`}
          className="cite-flash"
          style={{ '--cite-i': citeOrder } as CSSProperties}
        >
          {part.text}
        </span>
      ) : (
        part.text
      )
    ) : (
      <button
        key={`${index}-${part.n}`}
        type="button"
        id={`cite-${msgId}-${part.n}`}
        aria-label={`Ver fuente ${part.n}`}
        onClick={() => onCite(part.n)}
        className="mx-[2px] inline-flex"
        style={{ '--cite-i': citeOrder++ } as CSSProperties}
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

  // Two render modes by phase: while writing, the accumulated clean prose
  // (only a trailing abstention run is transiently hidden); on done, the
  // typed parts (chips anchored by core, text already tail-stripped). Plain
  // text stays as the fallback for 'error' partials and a done without parts.
  const body = (
    <div className="text-[15px] leading-[1.72] text-text">
      {message.phase === 'done' && message.parts
        ? renderParts(message.parts, msgId, focusSource)
        : hideTrailingAbstention(message.text, abstentionText)}
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
            {/* The anchoring gap (structured mode): tokens are done, the
                answer is fully readable above, and the server is running the
                citation anchor pass (~4-5s). A quiet working line justifies
                the wait; NO placeholder chips — we don't know where they land
                until done, and faking positions would be lying. The phase
                only exists when the gap is real (silence watchdog in
                useChat), so off/abstention never show this. */}
            {message.phase === 'anchoring' && (
              <div className="mt-[10px] flex items-center gap-2 font-mono text-[11px] text-[color:var(--muted)]">
                <span
                  aria-hidden="true"
                  className="h-[6px] w-[6px] animate-pulse rounded-full bg-[color:var(--accent)]"
                />
                Verificando fuentes…
              </div>
            )}
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
              parts={message.parts}
              msgId={msgId}
              focus={sourceFocus}
            />
          )}
      </div>
    </div>
  )
}
