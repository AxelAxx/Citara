# Known limitation B2: first-person out-of-corpus queries break the abstention discipline

## 1. Summary

First-person out-of-corpus queries (e.g. *"¿Cuánto IRPF me toca pagar este año?"*) make the
7B emit a polite prose decline ("Lo siento, pero la información proporcionada no incluye...")
instead of the exact `ABSTENTION_TEXT`. The behavior is **preexisting** (measured on baseline
`34a92f9`), **not caused** by the first-person bridge (`c0f78af`), and **not fixable by
prompt** (three prompt architectures tried, identical failure).

## 2. Symptom

The user asks a personal question whose answer is not in the corpus and gets, rendered as a
NORMAL answer:

> Lo siento, pero la información proporcionada no incluye datos personales ni detalles
> específicos sobre su situación fiscal para poder calcular cuánto IRPF debe pagar. [...]
> Le recomiendo que [...] utilice un software de declaración del IRPF o consulte a un asesor
> fiscal [...] puede consultar el modelo 100 de la Agencia Tributaria [...]

with `is_abstention=false`, `suppress_citations=false`, the sources panel **visible** (six
Ley General Tributaria citations that support nothing), and occasionally 1–3 CiteParts —
anchored, technically correctly, to the closing sentence that merely *describes* the
retrieved fragments ("la información proporcionada en los artículos citados se refiere a
normas generales sobre infracciones tributarias..."). This is the anti-case of golden rule 3:
an ungrounded non-answer presented as if it were grounded.

## 3. Root cause (measured)

The relevance gate **passes on topical proximity**: a tax question retrieves Ley 58/2003
(General Tributaria) chunks well under the 1.05 threshold, so the hard abstention guard never
fires. But the fragments do not contain the answer to "how much do **I** pay" — that depends
on the person's income, deductions, etc. Faced with a personal question plus
topically-close-but-insufficient context, the 7B slides into helpful-assistant mode and
elaborates (apology + explanation + recommendations from its own knowledge: "modelo 100",
"asesor fiscal") instead of copying the exact abstention sentence, violating three explicit
prompt prohibitions at once.

Contrast with the sibling case that IS solved: first-person **in-corpus** questions
("¿cuántos días de vacaciones tengo?") used to abstain because the *personal* figure is not
in the fragments; the bridge rule (`c0f78af`) redirects them to the general rule (art. 38),
which IS in the fragments. That bridge works precisely because there is grounded content to
redirect to. Here there is none — the failure mode is different in kind.

## 4. Interaction with resolved-state abstention authority (bug B, `92f2de3`/`22f7036`)

The done event decides:

```
is_abstention = (zero CiteParts in resolved parts) AND (resolved text == ABSTENTION_TEXT, byte-exact)
```

The prose decline is not the phrase, and sometimes even earns CiteParts → `is_abstention`
resolves to `false` → panel visible. **This is not a defect of the bug-B fix**: that fix
correctly decides on the RESOLVED STATE, and here the resolved state genuinely is free prose
(occasionally with a technically-valid anchor). The state authority faithfully reports what
the model produced; the problem is what the model produced. Loosening the equality to
fuzzy-match "decline-ish" prose would reintroduce exactly the prose-guessing that bug B
removed.

## 5. Evidence

IRPF query, 3 runs per variant (2 direct runs on baseline after reverting; the
amplified-protocol variant measured behaviorally identical to baseline), all against fresh
uvicorn + real corpus:

| Prompt variant | tengo (in-corpus personal) | IRPF (out-of-corpus personal) |
|---|---|---|
| baseline `34a92f9` | abstains | **"Lo siento..." (broken)** |
| bridge v1 (now `c0f78af`) | **answers 3/3** | "Lo siento..." 3/3 (= baseline) |
| hardened bridge (uncommitted experiment) | answers 3/3 | "Lo siento..." 3/3 |
| amplified protocol step 3 (uncommitted experiment) | abstains (regression) | "Lo siento..." 3/3 |

Every observation of the IRPF failure across variants was identical in kind (apology +
explanation + external recommendations, never the exact phrase).

**Method lesson**: IRPF was never measured on baseline until AFTER the bridge experiments —
the failure was initially misattributed to the bridge because a new variable (the bridge) and
a new query (IRPF) entered the experiment at the same time. Rule: **measure the baseline
before attributing**; one new variable per experiment.

## 6. Why prompt engineering cannot fix it

Three architecturally distinct prompt approaches failed identically (3/3 each):

1. **Special mode** (bridge v1 with a soft return clause "entonces sí aplica el protocolo").
2. **Hardened special mode** (imperative return clause re-quoting the exact phrase,
   "sin «Lo siento», sin recomendar nada externo...").
3. **Linear amplified criterion** (no mode; protocol step 3 widened to "the answer OR the
   general rule", with an explicit "vuelve al paso 2" fallback).

The 7B's helpful-assistant bias, when retrieval hands it topically close context, wins over
any imperative return instruction. This is a capability limit of the model at this size, not
a wording problem.

## 7. Fix (built for legal — `d96917c`)

> **Status update (`d96917c`):** shipped, but NOT as the prose-decline guard sketched below.
> What shipped is the `AnswerabilityGate` (S1 relative top-1 margin, μ=0.075), scoped per-vertical
> via config — **ON for legal, OFF for health** (`SPEC_B2_v2.md`). It forces byte-exact
> `ABSTENTION_TEXT` upstream of the resolved-state authority when the retrieval margin is
> insufficient. Legal IRPF is closed and verified in vivo (B2-AC1). The health applied-general
> residual (§8) stays unbuilt **by design** — not a context-sufficiency failure, the gate
> structurally cannot see it (`SPEC_B2_v2.md` §2.1); route is Stage 1 NLI. The sketch below is
> the original candidate, superseded by the gate.

A deterministic **prose-decline guard** in `core/` (Application layer, dependencies pointing
inward): after resolution, if the parts are NOT the abstention sentence BUT carry no
verifiable support either, force the abstention. Support verification could reuse the
AnchorVerifier infrastructure from `f7b1097` (same embedder, same sentence↔chunk cosine).

Trade-offs:

- **(+)** Reuses existing infrastructure (embedder wiring + `_cosine` + chunk embeddings
  already returned by retrieval) — no new dependencies, deterministic, unit-testable with a
  stubbed embedder.
- **(−)** Risk of false positives on legitimate grounded answers that happen to anchor
  weakly (degraded anchor pass, mode `off` has no anchors at all) — the guard would need the
  same calibration discipline as `anchor_repair_margin`.
- **(−)** Conceptually it moves abstention authority from "resolved text == phrase" to
  "verified support" — a real contract change that needs its own SPEC entry and acceptance
  criteria, not a patch.

Alternative: **accept as a 7B limitation and do not build** — defensible for a portfolio MVP,
since the trigger is narrow (see Scope).

## 8. Scope / status

**Legal: solved (`d96917c`, `AnswerabilityGate`, verified in vivo). Health applied-general residual: tracked, not built — by design.** Legal separates cleanly on S1 (μ=0.075); health does **not** (`SPEC_B2_v2.md` §2.1: `health-b2-001` has the highest margin in the vertical yet is not_answerable — a personal-framing/policy problem, not a retrieval-sufficiency one), so the gate is deliberately OFF there and the residual routes to Stage 1 NLI, built only if measured necessary.
Does not block the MVP; it is an edge case requiring all three conditions at once. First
recorded in `DECISIONS_merged.md` (commit `bdc1f17`); this document is the detailed
reference.
