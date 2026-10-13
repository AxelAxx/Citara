import { useEffect, useMemo, useRef, useState } from 'react'
import type { AnswerPart, Citation } from '../../api/client'
import { splitCitations } from '../../lib/citations'
import type { NumberedCitation } from '../../lib/citations'
import { CiteChip } from './CiteChip'

/** A cite-chip click asking to reveal source n; key bumps per click so
    re-clicking the same chip re-triggers the effect. */
export interface SourceFocus {
  n: number
  key: number
}

/**
 * Collapsible sources panel under an answer (mock chat-1b.html), split in two
 * honest groups: "Fuentes citadas" (anchored by an inline chip) and "Otras
 * fuentes consultadas" (retrieved context the answer didn't cite). Showing
 * both keeps rule 3's transparency — nothing the Generator saw is hidden —
 * without implying an inline citation that doesn't exist.
 */
export interface SourcesPanelProps {
  citations: Citation[]
  /** The done event's parts — the anchoring truth the partition derives from. */
  parts: AnswerPart[] | null
  /** Anchor namespace for the cite→source ids (src-<msgId>-<n>). */
  msgId?: string
  /** Inline chip click: unfold, scroll to and flash card n. */
  focus?: SourceFocus | null
}

// Full chunk_text is ~600 chars (chunk_size) — rendered whole it is a wall of
// text that buries the next source card. Show a lead-in, expand on demand;
// the full text is never lost, it sits behind the toggle.
const SNIPPET_LEAD_CHARS = 160

function leadIn(text: string): string {
  if (text.length <= SNIPPET_LEAD_CHARS) return text
  // Cut at the last space before the limit so the ellipsis never splits a word.
  const lastSpace = text.lastIndexOf(' ', SNIPPET_LEAD_CHARS)
  return `${text.slice(0, lastSpace > 0 ? lastSpace : SNIPPET_LEAD_CHARS)}…`
}

function SourceSnippet({ text }: { text: string }) {
  // Local state per card: expanding one source never unfolds its siblings.
  const [expanded, setExpanded] = useState(false)
  const truncated = text.length > SNIPPET_LEAD_CHARS
  return (
    <>
      <div className="border-l-2 border-accent-line pl-[11px] font-serif text-[13.5px] italic leading-[1.6] text-muted">
        «{expanded || !truncated ? text : leadIn(text)}»
      </div>
      {truncated && (
        <button
          type="button"
          onClick={() => setExpanded((prev) => !prev)}
          className="mt-[6px] font-mono text-[10.5px] text-[color:var(--accent)] transition-colors hover:text-[color:var(--text)]"
        >
          {expanded ? 'Ocultar fragmento' : 'Ver fragmento completo'}
        </button>
      )}
    </>
  )
}

interface SourceCardProps {
  item: NumberedCitation
  /** Cited cards are chip-linked (id + ref + flash); consulted are not —
      no inline chip points at them, so a numbered anchor would dangle. */
  linkable: boolean
  msgId?: string
  flashing: boolean
  cardRef?: (el: HTMLDivElement | null) => void
}

function SourceCard({ item, linkable, msgId, flashing, cardRef }: SourceCardProps) {
  const { n, citation } = item
  return (
    <div
      id={linkable && msgId ? `src-${msgId}-${n}` : undefined}
      ref={cardRef}
      className={`flex gap-[13px] rounded-card border bg-bg px-[14px] py-[13px] transition-all hover:border-accent-line hover:bg-surface2 ${
        flashing
          ? 'border-accent-line bg-surface2 ring-1 ring-[var(--accent-line)]'
          : 'border-border'
      }`}
    >
      <div className="shrink-0">
        {linkable ? (
          // The SAME n the inline chip shows — the single link between both.
          <CiteChip n={n} variant="card" />
        ) : (
          // Neutral marker: a consulted source has no inline chip pointing at
          // it, so a number here would promise a link that doesn't exist.
          <span
            aria-hidden="true"
            className="inline-flex h-[22px] min-w-[22px] items-center justify-center rounded-[5px] border border-border bg-surface2 text-[13px] text-[color:var(--faint)]"
          >
            ·
          </span>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <span className="font-mono text-[12.5px] font-medium text-text">
            {citation.document_id}
          </span>
          <span className="rounded-[6px] border border-border bg-surface2 px-[7px] py-px font-mono text-[10.5px] text-muted">
            pág. {citation.page}
          </span>
          {citation.section && (
            <span className="ml-auto text-[10.5px] tracking-[0.02em] text-faint">
              {citation.section}
            </span>
          )}
        </div>
        <SourceSnippet text={citation.chunk_text} />
      </div>
    </div>
  )
}

export function SourcesPanel({ citations, parts, msgId, focus }: SourcesPanelProps) {
  // Folded by default: the count badge advertises the evidence without
  // pushing a wall of snippets between consecutive answers.
  const [open, setOpen] = useState(false)
  // The consulted subsection folds independently, collapsed by default:
  // uncited context is secondary evidence, shown on demand.
  const [consultedOpen, setConsultedOpen] = useState(false)
  const [flashN, setFlashN] = useState<number | null>(null)
  const cardRefs = useRef(new Map<number, HTMLDivElement>())

  // Partition once per (citations, parts) — not per render.
  const { cited, consulted } = useMemo(
    () => splitCitations(citations, parts),
    [citations, parts],
  )

  useEffect(() => {
    if (!focus) return
    setOpen(true)
    setFlashN(focus.n)
    // One frame so the card exists when the panel was folded until now.
    const frame = requestAnimationFrame(() => {
      // block:'nearest' only moves the chat column — the app root is
      // h-screen/overflow-hidden, so no global page scroll can happen.
      cardRefs.current
        .get(focus.n)
        ?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    })
    const timer = window.setTimeout(() => setFlashN(null), 1200)
    return () => {
      cancelAnimationFrame(frame)
      window.clearTimeout(timer)
    }
  }, [focus])

  return (
    <div className="mt-[14px] rounded-[14px] border border-border bg-surface px-[14px] py-[13px]">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className="flex w-full items-center justify-between gap-[10px] p-px"
      >
        <span className="flex items-center gap-[9px]">
          <span
            className={`inline-flex w-4 items-center justify-center text-[15px] text-accent transition-transform duration-200 ${
              open ? 'rotate-90' : ''
            }`}
          >
            ›
          </span>
          <span className="text-[12.5px] font-semibold tracking-[0.01em] text-text">
            Fuentes citadas
          </span>
          <span className="rounded-full bg-accent-tint px-[7px] py-px font-mono text-[11px] text-accent">
            {cited.length}
          </span>
        </span>
        <span className="font-mono text-[11px] text-faint">
          {open ? 'Ocultar' : 'Mostrar'}
        </span>
      </button>

      {open && (
        <div className="mt-[13px] flex flex-col gap-[9px] border-t border-border pt-[13px]">
          {cited.map((item) => (
            <SourceCard
              key={`cited-${item.n}`}
              item={item}
              linkable
              msgId={msgId}
              flashing={flashN === item.n}
              cardRef={(el) => {
                if (el) cardRefs.current.set(item.n, el)
                else cardRefs.current.delete(item.n)
              }}
            />
          ))}

          {/* Retrieved-but-uncited context: honest (rule 3 — nothing the
              Generator saw is hidden) yet clearly separated so the badge
              count matches the inline chips. Never renders when empty; when
              cited is empty this is the whole panel (never an empty panel). */}
          {consulted.length > 0 && (
            <div className={cited.length > 0 ? 'mt-[4px]' : ''}>
              <button
                type="button"
                onClick={() => setConsultedOpen((prev) => !prev)}
                className="flex w-full items-center gap-[9px] p-px"
              >
                <span
                  className={`inline-flex w-4 items-center justify-center text-[13px] text-[color:var(--muted)] transition-transform duration-200 ${
                    consultedOpen ? 'rotate-90' : ''
                  }`}
                >
                  ›
                </span>
                <span className="text-[11.5px] font-medium tracking-[0.01em] text-[color:var(--muted)]">
                  Otras fuentes consultadas
                </span>
                <span className="rounded-full bg-surface2 px-[7px] py-px font-mono text-[10.5px] text-[color:var(--faint)]">
                  {consulted.length}
                </span>
              </button>
              {consultedOpen && (
                <div className="mt-[9px] flex flex-col gap-[9px]">
                  {consulted.map((item) => (
                    <SourceCard
                      key={`consulted-${item.n}`}
                      item={item}
                      linkable={false}
                      flashing={false}
                    />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
