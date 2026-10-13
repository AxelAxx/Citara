import type { AnswerPart, Citation } from '../api/client'

/** A citation carrying its ORIGINAL 1-based index into the citations list.
    The n is what inline chips display and what the src-<msgId>-<n> anchors
    use — it must survive the cited/consulted partition unrenumbered, or
    "chip 1" would stop matching "fuente 1". */
export interface NumberedCitation {
  n: number
  citation: Citation
}

/**
 * Partition the consulted sources by whether the anchoring pass actually
 * cited them: a citation is "cited" iff some CitePart.n points at it.
 * Pure and exported on purpose (testable, single place for the criterion).
 * With parts null/absent (no done yet, older server) everything lands in
 * consulted — the panel never lies about anchoring it can't see.
 */
export function splitCitations(
  citations: Citation[],
  parts: AnswerPart[] | null,
): { cited: NumberedCitation[]; consulted: NumberedCitation[] } {
  const anchored = new Set<number>()
  for (const part of parts ?? []) {
    if (part.kind === 'cite') anchored.add(part.n)
  }
  const cited: NumberedCitation[] = []
  const consulted: NumberedCitation[] = []
  citations.forEach((citation, index) => {
    const item = { n: index + 1, citation }
    ;(anchored.has(item.n) ? cited : consulted).push(item)
  })
  return { cited, consulted }
}
