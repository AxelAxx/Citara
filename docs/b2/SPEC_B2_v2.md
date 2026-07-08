# SPEC-B2 v2 — AnswerabilityGate: deterministic abstention on insufficient context

> Addendum to [`SPEC.md`](../SPEC.md). Same contract discipline: code is correct when it
> satisfies the **Acceptance Criteria** (§8), not when it "feels done". New terms are in §7 and
> live in [`UBIQUITOUS_LANGUAGE.md`](../UBIQUITOUS_LANGUAGE.md) (committed `docs(glossary) …[B2]`).
> IDs are prefixed `B2-`.
>
> **v2 supersedes v1.** v1 specified a universal query↔chunks gate combining two signals (S1
> margin + S2 coverage). The measurement (`docs/b2/measurements/b2_margins_20260708-105727Z.md`,
> 18 labeled queries over the live corpus) changed the contract:
> - **Legal:** S1 (top-1 margin) separates cleanly → S1-only is authoritative, `μ` measured.
> - **Health:** S1 does **not** separate, and neither would S2 for the case that breaks it (see
>   §2.1). The gate is therefore **scoped**, not universal: authoritative where the signal
>   separates, explicitly out-of-scope where the failure is not a context-sufficiency failure.
>
> Reference: `docs/KNOWN_LIMITATION_B2_first_person_out_of_corpus.md` (diagnosis), the research
> report (staged recommendation), the diagnostic (hook points), the measurement (thresholds).

---

## 1. Problem statement

First-person, out-of-corpus queries (e.g. *"¿Cuánto IRPF me toca pagar este año?"*) make the
Generator emit a **prose decline** with invented recommendations instead of the canonical
`ABSTENTION_TEXT`. Because bug B (`92f2de3`/`22f7036`) decides `is_abstention` on the **resolved
state**, and that state is genuinely free prose (sometimes with a CitePart anchored to a fragment-
describing sentence), the answer renders as **normal**, `SourcesPanel` visible — an ungrounded
non-answer presented as grounded. Anti-case of golden rule 3.

Established: not the relevance gate (chunks pass on topical proximity), not fixable by prompt
(three architectures, identical failure), not fixable by model scale. Only a deterministic check
external to the LLM yields the hard requirement — a *guarantee* of abstention.

## 2. What the measurement established (the basis for v2)

Two verticals behave differently, and the difference is structural, not a tuning accident.

- **Legal separates.** Worst answerable margin `+0.0882` (`legal-bridge-002`) sits above the best
  not_answerable `+0.0615` (`legal-b2-001`). A clean gap with an operating band at recall 1.00 /
  precision 1.00. The archetypal flat-margin B2 (`legal-b2-002`, `+0.0150`) is caught easily.
- **Health does not separate.** `health-b2-001` ("¿qué dosis de ibuprofeno para MI dolor?") has
  the **highest** margin in the vertical (`+0.0956`) yet is `not_answerable`. No `μ` reaches
  recall ≥ 0.9 without abstaining on the answerable controls.

### 2.1 Why health does not separate — and why S2 would not save it

`health-b2-001` is **not a context-sufficiency failure**. The *general* answer (ibuprofeno adult
posology) IS in corpus, so the top-1 is a genuine standout — context is sufficient for the general
question. What makes it `not_answerable` is the **personal-applied framing** ("for **my** pain"),
which is invisible to any *shape-of-retrieval* signal.

- **S1 (margin) cannot see it:** the retrieval shape is that of an answerable query.
- **S2 (key-term coverage) cannot see it either:** "ibuprofeno"/"dolor" ARE in the chunks →
  coverage is *high*, the opposite of what would trigger abstention. Coverage separates the
  *other* health subtype (`health-b2-002/004`, genuinely out-of-corpus) — not the applied-general.

**Conclusion:** the applied-general health case (`first_person_applied_no_bridge`) is a **policy**
problem (health prompt deliberately carries no bridge), not a retrieval-sufficiency problem. It
belongs to vertical policy or to Stage 1 (NLI over answer↔context, which can see the framing),
**not** to the embeddings gate. Forcing it into the gate would corrupt a clean signal with a case
the signal structurally cannot represent.

## 3. Scope decision (v2)

- **Legal: gate ON, S1-only, authoritative.** `μ` from the measurement.
- **Health: gate OFF for now.** No `μ` separates; enabling it sacrifices an answerable control
  (`health-plain-001`, `+0.0563`). The genuinely out-of-corpus health cases are already handled by
  the existing hard guard (they retrieve nothing: `health-ood-001` is n=0 today). The
  applied-general residual is tracked (§10), not forced.
- The gate is **per-vertical enabled via config**, not hardcoded to legal — same generic mechanism,
  switched by data (no vertical branching in `core/`, golden rule 2).

## 4. Contract change

```
# before (bug B, resolved-state authority):
is_abstention = (zero CiteParts) AND (resolved text == ABSTENTION_TEXT, byte-exact)

# after (B2): the gate, when INSUFFICIENT, forces the resolved parts to be the canonical
# ABSTENTION_TEXT. Bug B's equality then resolves is_abstention = true ON ITS OWN.
```

The gate does **not** touch the API. Applied inside `Generator._resolve_parts` (the single
final-resolution site, per the diagnostic), an `INSUFFICIENT` verdict **replaces** the produced
parts with a single `TextPart(ABSTENTION_TEXT)` and zero `CitePart`s. Downstream, unchanged:
`query.py:106-107` sees zero CiteParts + byte-exact `ABSTENTION_TEXT` → `is_abstention=true` →
`suppress_citations=true` → panel hidden. The "OR" of the contract is realized in code by making
the resolved state *be* abstention — no new authority path in the API layer.

Bug B's byte-exact equality is **not loosened**. No fuzzy prose matching, ever.

## 5. The AnswerabilityGate

**What it is.** A deterministic component mapping `(RetrievedContext)` to a `SufficiencyVerdict ∈
{SUFFICIENT, INSUFFICIENT}` from the top-1 margin signal (S1) only, in this stage. Sibling of the
`AnchorVerifier` (`f7b1097`): the LLM proposes, a deterministic guard disposes — here at the
retrieval-sufficiency point.

**Where it lives.** `core/`, applied in `Generator._resolve_parts` (`core/generate.py:554-600`),
where the stripped text, sentences, context and `self.embedder` already coexist, immediately after
`verify_anchors`. Model- and vertical-agnostic.

**Signal — S1, relative top-1 margin.** From `Chunk.distance` (propagated in
`feat(retrieve): propagate query-chunk distance onto Chunk [B2]`), Chroma L2² native unit
(**lower = closer**), no transformation:

```
d_top1     = distances[0]                      # nearest
tail_mean  = mean(distances[1:])               # ranks 2..k
margin     = (tail_mean - d_top1) / tail_mean  # relative; scale-independent across verticals
verdict    = INSUFFICIENT if margin < μ else SUFFICIENT
```

**Formulation = relative** (not additive). Rationale: legal and health use different distance
scales (`relevance_threshold` 1.05 vs 0.90); the relative margin normalizes, so `μ` is interpretable
across verticals even though only legal enables the gate today. Both formulations gave a clean legal
band in the measurement; relative is chosen for scale-independence, not for a metric difference.

**μ (measured, legal).** Operating band recall 1.00 / precision 1.00 is `margin ∈ [0.0615, 0.0882)`.
**`μ = 0.075`** (band center). Recorded next to the measurement, exactly as δ=0.05 was for the
AnchorVerifier. Health carries no `μ` (gate disabled).

### 5.1 Edge rules (from the measurement's boundary cases)

- **n_chunks == 0 → gate not consulted.** The existing hard guard already abstains (context empty,
  no LLM call: `generate.py:455-456`, `493-495`). 4 of 18 queries, all correct today.
- **n_chunks == 1 → SUFFICIENT (fail-safe toward the user).** No tail ⇒ no margin signal.
  Abstaining without a signal would be a false abstain on an answerable (`health-plain-003`, n=1,
  answerable). Absence of signal is **never** grounds to abstain. The verdict here is not "we
  measured sufficiency" but "we have no basis to override" — pass through.

## 6. Non-functional requirements

- B2-NFR1. **Determinism.** Same `RetrievedContext` → same verdict. No randomness, no LLM.
- B2-NFR2. **LLM-independence.** Decision never reads the Generator's prose.
- B2-NFR3. **Testability.** Unit-testable with fixed `Chunk.distance` values; **no live LLM, no
  live embedder** (S1 needs only distances, already on the chunks).
- B2-NFR4. **No vertical logic in `core/`.** `μ` and the on/off switch are config; mechanism generic.
- B2-NFR5. **Typing.** `SufficiencyVerdict` is an enum, not a bool — the reason is legible in logs.
- B2-NFR6. **Fail-fast.** Missing `Chunk.distance` on a retrieval-path chunk → specific error
  ("distance propagation broke"), never a silent SUFFICIENT and never a recompute.
- B2-NFR7. **Locality.** No network/inference calls introduced.

## 7. Ubiquitous language (committed)

`AnswerabilityGate`, `SufficiencyVerdict` (enum SUFFICIENT|INSUFFICIENT), `Answerability`,
`top-1 margin` → `margin`. `key-term coverage` → `coverage` remains **reserved, not built** (S2 is
future work, §10).

## 8. Acceptance criteria

- B2-AC1. **Legal out-of-corpus abstains.** With the gate enabled on legal, `legal-b2-001/002/003`
  (n≥2) produce byte-exact `ABSTENTION_TEXT`, `suppress_citations=true`, no `SourcesPanel` —
  including the IRPF case that today emits the broken prose decline.
- B2-AC2. **Legal answerables unchanged.** `legal-bridge-001/002`, `legal-plain-001/002` return
  `SUFFICIENT`; answer path unchanged (no new false abstentions). `μ=0.075` sits in the measured
  band that guarantees this.
- B2-AC3. **Measured targets held.** On the labeled legal set: abstention recall ≥ ~0.9 (achieved
  1.00 at `μ=0.075`) with answerable precision 1.00. Table committed under `docs/b2/measurements/`.
- B2-AC4. **Vertical-agnostic mechanism.** Enabling/disabling the gate and setting `μ` is config
  only; **no diff in the gate's `core/` logic** between verticals (`git diff`). Health config
  leaves the gate off.
- B2-AC5. **pytest green, no live deps.** Gate returns `INSUFFICIENT` on a flat-margin fixture
  (distances clustered), `SUFFICIENT` on a standout-top-1 fixture, `SUFFICIENT` on n=1 and n=0;
  all from fixed `Chunk.distance`, no embedder/LLM.
- B2-AC6. **Bug-B interaction.** A genuine `ABSTENTION_TEXT` resolution stays abstained; a
  `SUFFICIENT` verdict never un-abstains it.
- B2-AC7. **Airplane-mode unchanged.** No external inference calls (NFR1 preserved).
- B2-AC8. **Fail-fast.** A retrieval-path chunk missing `distance` raises a specific, actionable
  error, not a silent pass.

## 9. Calibration record (artifact #2, done)

`docs/b2/b2_answerability_set.yaml` (labeled) → `docs/b2/measurements/b2_margins_20260708-*.md`
(measured over the live corpus, HEAD 9632817). `μ=0.075` (legal) is the band center of the
recall-1.00/precision-1.00 operating range `[0.0615, 0.0882)`. Health: no separating `μ` → gate
disabled, documented in §2.1/§3. Re-runs version new measurement artifacts without touching tooling.

## 10. Out of scope / staged future (named, not built)

- **Health applied-general residual (`first_person_applied_no_bridge`).** Not a sufficiency failure
  (§2.1). Routes to: (i) health vertical **policy** (prompt boundary — the human owns prompt YAML),
  or (ii) **Stage 1 NLI** (`mDeBERTa-v3-base-mnli-xnli`, FP32, answer↔context entailment — can see
  the personal framing that retrieval shape cannot). Build Stage 1 **only if** measured necessary.
- **S2 key-term coverage.** Reserved term, not built. Would separate genuinely out-of-corpus health
  (`health-b2-002/004`) — but those already hard-abstain (n=0) or are low-value to chase for the
  MVP. Revisit only if the health corpus grows and out-of-corpus queries start retrieving close-but-
  empty context that passes the relevance gate.
- **Structured output (Ollama JSON `answerable`).** Detection aid; touches generation, risks bug
  B/C. Deferred.
- **Explicitly discarded:** verbalized confidence, self-critique/SelfCheckGPT (invalid in 3–9B);
  RAGAS with API (not local); MiniCheck/AlignScore/HHEM (English-only); reranker FP32 (borderline
  VRAM); per-query model swapping; single absolute cosine/L2 threshold (the B2 root cause).

## 11. Build order (remaining)

1. **Gate implementation** — `AnswerabilityGate` + `SufficiencyVerdict` in `core/`, wired into
   `Generator._resolve_parts`, `μ` + on/off from `VerticalConfig` (same rail as
   `anchor_repair_margin`). Unit tests per B2-AC5.
2. **Smoke** — legal IRPF abstains byte-exact with panel hidden; legal answerables unchanged;
   health unchanged (gate off).
3. **Atomic commit**, hash to the human, no push without approval.
