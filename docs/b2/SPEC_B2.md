# SPEC-B2 — AnswerabilityGate: deterministic abstention on insufficient context

> Addendum to [`SPEC.md`](./SPEC.md). Same contract discipline: code is correct when it
> satisfies the **Acceptance Criteria** (§8), not when it "feels done". New terms are defined
> in §7 and MUST be added to [`UBIQUITOUS_LANGUAGE.md`](./UBIQUITOUS_LANGUAGE.md) **before** any
> code (golden rule 6). IDs are prefixed `B2-` to avoid collision with the base SPEC.
>
> Reference material: `docs/KNOWN_LIMITATION_B2_first_person_out_of_corpus.md` (the diagnosis)
> and the research report (staged recommendation). This SPEC is the *contract* those two feed.

---

## 1. Problem statement

First-person, out-of-corpus queries (e.g. *"¿Cuánto IRPF me toca pagar este año?"*) make the
Generator emit a **prose decline** ("Lo siento, la información no incluye...") with invented
recommendations from parametric memory, instead of the canonical `ABSTENTION_TEXT`. Because the
bug-B fix (`92f2de3`/`22f7036`) decides `is_abstention` on the **resolved state**, and that state
is genuinely free prose (occasionally with a technically-valid CitePart anchored to a fragment-
describing sentence), the answer renders as **normal**, with the `SourcesPanel` visible — an
ungrounded non-answer presented as grounded. This is the anti-case of golden rule 3.

Established (see the `.md`): it is **not** the relevance gate (chunks pass on topical proximity),
**not** fixable by prompt (three architectures, identical failure), **not** fixable by model
scale ("model scale has almost no effect" on abstention). The only mechanism that yields the hard
requirement — a *guarantee* of abstention — is a deterministic check external to the LLM.

## 2. Contract change (the core of B2)

B2 moves abstention authority:

```
# before (bug B, resolved-state authority):
is_abstention = (zero CiteParts) AND (resolved text == ABSTENTION_TEXT, byte-exact)

# after (B2, verified-support authority):
is_abstention = (resolved text == ABSTENTION_TEXT, byte-exact)
                OR (AnswerabilityGate verdict == INSUFFICIENT)
```

The gate's `INSUFFICIENT` verdict **overrides** the resolved state: the Application layer replaces
the produced parts with the canonical `ABSTENTION_TEXT`, sets `suppress_citations=true`, and drops
the `SourcesPanel`. The bug-B equality is **not loosened** — we never fuzzy-match "decline-ish"
prose (that would reintroduce exactly the prose-guessing bug B removed). We add an **orthogonal,
LLM-independent** authority alongside it.

This is a real contract change, not a patch. It is why B2 gets its own SPEC.

## 3. Goals / Non-goals

**Goals**
- B2-G1. A deterministic `AnswerabilityGate` in `core/` decides, from **query↔chunks signals
  only**, whether `RetrievedContext` is sufficient to answer — never reading the model's prose.
- B2-G2. On `INSUFFICIENT`, the Engine forces canonical `ABSTENTION_TEXT` + `suppress_citations`,
  **independently of what the LLM produced**.
- B2-G3. Reuses already-loaded infrastructure only: the BGE-M3 `Embedder`, the `_cosine` helper,
  and the chunk embeddings/scores retrieval already returns. **Zero new models, zero extra LLM
  calls** in this stage.
- B2-G4. Vertical-agnostic and model-agnostic: no `legal`/`health` branching in `core/`; the
  mechanism is the same across verticals (the trigger — personal phrasing + out-of-corpus + close
  retrieval — is itself vertical-agnostic).
- B2-G5. Unit-testable with a **stubbed Embedder, no live LLM**, per NFR4.
- B2-G6. Thresholds are **calibrated empirically** against the B2 labeled query set (§9), never
  guessed — the δ-calibration lesson from the AnchorVerifier.

**Non-goals**
- B2-N1. **No structured-output refactor in this stage.** The report's Ollama-JSON `answerable`
  field is a *detection* aid, not the *decision*; it touches the generation path and risks the
  existing bug-B and bug-C fixes. Named as future work (§10), not built here.
- B2-N2. **No NLI verifier (mDeBERTa) in this stage.** Parked until the embeddings gate is *measured*
  insufficient on the labeled set (§10, staged).
- B2-N3. No change to the bug-B byte-exact equality; no fuzzy prose matching, ever.
- B2-N4. No reranker, no model scale-up, no fine-tuning (§10, hardware-conditional / out of scope).

## 4. The AnswerabilityGate

**What it is.** A deterministic component that maps `(Query, RetrievedContext)` to a
`SufficiencyVerdict ∈ {SUFFICIENT, INSUFFICIENT}`, using only computable signals over embeddings
and lexical overlap. Sibling of the `AnchorVerifier` (`f7b1097`): *the LLM proposes, a deterministic
guard disposes* — but at a different point in the pipeline (retrieval sufficiency, not citation
anchoring).

**Where it lives.** In `core/`, Application layer, dependencies pointing inward. It is **downstream
of the Retriever** (needs `RetrievedContext` + per-chunk scores/embeddings) and its verdict is
**applied at the resolution/done boundary** where bug-B authority lives. Exact hook points
(function/module names) are confirmed by the read-only diagnostic (§11), **not invented here** —
the code is the source of truth where docs have drifted.

**What it reuses (no new deps).**
- BGE-M3 `Embedder` (already wired; same model as ingest/query — golden rule 4).
- `_cosine` (already used by the AnchorVerifier).
- Chunk embeddings and similarity scores the `Retriever` already computes/returns.

**Signals (combined, all deterministic).**
- **S1 — Relative top-1 margin.** Separation between the top-1 chunk score and the tail
  (mean/median of ranks 2..k). Rationale: B2 produces moderate-but-**flat** score profiles (several
  topically-similar chunks); an answerable query usually has a standout top-1. Threshold `μ`.
- **S2 — Query key-term coverage.** Fraction of the query's salient terms (entities/keywords, e.g.
  `IRPF`, `modelo 100`) actually present in the retrieved chunks — dense BGE-M3 signal complemented
  by a lexical/BM25-style check — vs. only same-domain terms (`tributo`, `Ley General Tributaria`).
  Rationale: topical proximity ≠ containing the answer (report Key Finding 2). Threshold `κ`.

**Combination policy (calibrated).** Start conservative to protect legitimate answerables (the
false-positive risk flagged in the `.md` §7):

```
verdict = INSUFFICIENT if (S1_margin < μ) AND (S2_coverage < κ) else SUFFICIENT
```

- AND is the conservative default: fire abstention only when *both* signals agree on insufficiency.
- Trade-off, stated plainly: AND maximizes precision on answerables (few false abstentions) but
  lowers abstention recall vs. OR. The combination operator **and** `μ`, `κ` are all calibration
  parameters resolved against the labeled set (§9), targeting abstention recall ≥ ~0.9 without
  degrading answerable precision. If AND can't hit the recall target without wrecking precision,
  that is the measured trigger to escalate to Stage 1 (§10), not a reason to guess wider here.

## 5. Functional requirements

- B2-FR1. **Gate contract.** `AnswerabilityGate.evaluate(query: Query, context: RetrievedContext)
  -> SufficiencyVerdict`. Pure function of its inputs + injected `Embedder`; no I/O, no LLM call.
- B2-FR2. **Signal S1** computed from per-chunk retrieval scores (relative margin, not absolute
  threshold).
- B2-FR3. **Signal S2** computed from query key-term coverage over chunk text (dense + lexical).
- B2-FR4. **Combination** per §4 policy, thresholds sourced from `VerticalConfig`/central config —
  never hardcoded in two places (golden rule 4 spirit).
- B2-FR5. **Override application.** On `INSUFFICIENT`, the Engine forces canonical `ABSTENTION_TEXT`,
  `suppress_citations=true`, empty `Citation` list, hidden `SourcesPanel` — regardless of the
  generated parts. On `SUFFICIENT`, behaviour is unchanged from today.
- B2-FR6. **Idempotent with bug B.** When the resolved text already equals `ABSTENTION_TEXT`, the
  gate's verdict cannot un-abstain it (authority is `OR`, never `AND`).

## 6. Non-functional requirements

- B2-NFR1. **Determinism.** Same `(Query, RetrievedContext)` → same verdict, always. No randomness,
  no temperature, no LLM.
- B2-NFR2. **LLM-independence.** The decision never reads the Generator's output prose.
- B2-NFR3. **Testability.** Unit-testable with a stubbed `Embedder` and fixed chunks; no live Ollama.
- B2-NFR4. **No vertical logic in `core/`.** Thresholds are data (config); mechanism is generic.
- B2-NFR5. **Typing.** Strong type hints on the gate's public surface; `SufficiencyVerdict` is an
  enum, not a bare bool, so the reason is legible in logs/tests.
- B2-NFR6. **Fail-fast.** Empty `RetrievedContext`, missing scores, or embedder failure → specific,
  actionable error (not a silent `SUFFICIENT`).
- B2-NFR7. **Locality.** No network/inference calls introduced (NFR1 preserved).

## 7. Ubiquitous language additions (add to glossary BEFORE coding)

| Term | Definition | Code identifier |
|------|------------|-----------------|
| **AnswerabilityGate** | Deterministic guard that decides, from query↔chunks signals only, whether `RetrievedContext` is sufficient to answer. Downstream of `Retriever`; verdict applied at the resolution boundary. Sibling of `AnchorVerifier`. | `AnswerabilityGate` |
| **SufficiencyVerdict** | The gate's output: `SUFFICIENT` or `INSUFFICIENT`. An enum, not a bool — the reason must be legible. | `SufficiencyVerdict` (enum) |
| **Answerability** | Whether the retrieved context *contains the answer* to the `Query`, distinct from topical relevance. B2 exists because relevance ≠ answerability. | — |
| **key-term coverage** | Signal S2: fraction of the query's salient terms present in the retrieved chunks (dense + lexical). | `coverage` |
| **top-1 margin** | Signal S1: separation between the top-ranked chunk score and the tail. | `margin` |

## 8. Acceptance criteria (definition of done)

- B2-AC1. For the labeled **out-of-corpus** B2 queries (§9), the gate returns `INSUFFICIENT` and the
  Engine emits **byte-exact** `ABSTENTION_TEXT` with `suppress_citations=true` and no `SourcesPanel`
  — including the IRPF case that today produces the broken prose decline.
- B2-AC2. For the labeled **answerable** queries (incl. the in-corpus first-person bridge case
  "¿cuántos días de vacaciones tengo?" → art. 38, `c0f78af`), the gate returns `SUFFICIENT` and the
  answer path is unchanged (no new false abstentions).
- B2-AC3. Measured on the labeled set: abstention **recall ≥ ~0.9** with answerable **precision**
  not degraded below the current baseline. Numbers recorded next to the calibrated `μ`, `κ`.
- B2-AC4. Vertical-agnostic: switching legal↔health changes only config; **no diff in the gate's
  `core/` logic** (`git diff`), thresholds may differ per config.
- B2-AC5. `pytest` green: gate returns `INSUFFICIENT` on a flat-margin/low-coverage fixture and
  `SUFFICIENT` on a standout-top-1 fixture, both with a **stubbed Embedder, no live LLM**.
- B2-AC6. Bug-B interaction: a genuine `ABSTENTION_TEXT` resolution stays abstained; a `SUFFICIENT`
  verdict never overrides an already-abstained answer (B2-FR6).
- B2-AC7. Airplane-mode unchanged: no external inference calls introduced (NFR1 preserved).
- B2-AC8. Fail-fast: empty context / missing scores raise a specific error, not a silent pass.

## 9. Calibration protocol (artifact #2 — the labeled set)

Thresholds `μ`, `κ` and the combination operator are **measured, not guessed** (δ-calibration
lesson). Required before any threshold is committed:

- A labeled set of queries per vertical, tagged `answerable` vs `not-answerable`, covering:
  the three B2 conditions (first-person + out-of-corpus + topically-close retrieval); the solved
  sibling (first-person in-corpus → bridge); plainly-answerable in-corpus; plainly out-of-domain.
- Run gate signals over the real corpus (fresh backend, real ChromaDB) → per-query `(margin,
  coverage)` → sweep `μ`, `κ` → pick the operating point hitting B2-AC3.
- Record the chosen point and the confusion matrix alongside the config, exactly as δ=0.05 was
  recorded for the AnchorVerifier.

**No threshold reaches a commit without this table.**

## 10. Out of scope / staged future (named, not built)

- **Stage 0-detection (future): structured output.** Ollama JSON schema with `answerable: bool`,
  `temperature=0`, Pydantic validation + retry. Makes the decline byte-exact-detectable and removes
  free-form prose decline. Deferred: touches the generation path; risks bug-B/bug-C. Detection only
  — still needs this gate for the decision.
- **Stage 1: NLI verifier.** `mDeBERTa-v3-base-mnli-xnli` (~278M, **FP32 mandatory** on Pascal,
  ~1.5–2 GB, fits the ~3 GB free; 84.5% XNLI-es). Entailment over (context, answer). Added **only if**
  this gate is measured short on the labeled set, and **only if** it beats the embeddings gate by
  ≥ ~5 F1 points of abstention. Caveat: validated on generic short-sentence NLI, not long-paragraph
  legal/clinical groundedness — measure before assuming.
- **Stage 2 (hardware-conditional):** `bge-reranker-v2-m3` in FP16 (needs Tensor Cores; FP32 is
  borderline in 8 GB), ES-retrained MiniCheck/AlignScore. Scaling the LLM to 14B/32B reduces prose-
  decline *frequency* but does **not** replace the deterministic guard.
- **Explicitly discarded:** verbalized confidence and self-critique/SelfCheckGPT (invalid in 3–9B);
  RAGAS with API (not local); MiniCheck/AlignScore/HHEM-2.1-open (English-only); reranker in FP32
  (borderline VRAM); per-query model swapping; a single absolute cosine/L2 threshold (the B2 root
  cause — can't tell "topically close" from "contains the answer").

## 11. Open questions (resolved in the read-only diagnostic, before code)

- Exact hook point where the resolution/done event computes `is_abstention` (bug-B site) — where the
  override is applied.
- Whether the `Retriever` already surfaces per-chunk scores + embeddings to the gate, or a read-only
  accessor is needed (no new retrieval call).
- Where `μ`, `κ` belong in `VerticalConfig` and how they're threaded to `core/` without hardcoding.
- Whether S2's lexical component reuses anything already present or needs a small helper (kept in
  `core/`, framework-free).

---

**Build order after this SPEC:** (1) glossary entries (§7) committed; (2) labeled set (§9);
(3) read-only diagnostic (§11) → design → implementation → calibration → smoke → atomic commit.
No push without hash approval.

---

**SUPERSEDED BY [`SPEC_B2_v2.md`](./SPEC_B2_v2.md)** — the measurement scoped the gate
(S1-only, legal-only; S2 reserved). Do not work from this version.
