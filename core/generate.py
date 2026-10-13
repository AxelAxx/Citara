"""Generator: grounded prompt + local LLM + citations (module 6, FR7–FR9 → AC2, AC3, G4).

Designated *adapter* for the generation side: the ``requests``/Ollama call lives
**only here**, lazily, behind one class, so the rest of ``core/`` stays
framework-free (golden rule 1) and a missing dependency fails loud and actionable
instead of as an ImportError at collection time.

Why a direct HTTP call instead of an SDK: this module talks to Ollama's stable
``POST /api/chat`` endpoint with ``requests`` rather than ``langchain-ollama``'s
``ChatOllama``. The LangChain path is brittle across versions — ``ChatOllama``
reads ``langchain.verbose``, which no longer exists in langchain 1.x, so a
version skew raises ``AttributeError`` deep in the call. Speaking the documented
HTTP API directly removes that volatile dependency and unifies generation with
``embed.py``, which already calls ``/api/embed`` over HTTP for the same reason.

Two non-negotiable invariants this module exists to uphold:

  * **Abstention is a hard guard, not a hope (AC3 / G4).** An empty RetrievedContext
    returns an ``Answer.abstention`` *without ever calling the LLM*. We do not trust
    the model to abstain on its own — the deterministic guard is the net that makes
    "never fabricate when there's nothing to ground on" actually hold, and it's
    testable without Ollama.

  * **Every non-abstaining Answer is grounded and cited (FR8/FR9).** The
    ``system_prompt`` (vertical-specific, from the YAML) carries the grounding /
    citation / Spanish-output rules; this module only assembles it with the context
    and Query. Citations are derived from the *context the model was given*, so a
    grounded Answer can never ship without provenance.

Zero vertical logic here: every legal/health difference lives in the
``system_prompt`` text passed in by ``engine.py`` from ``VerticalConfig``.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterator

from core.embed import Embedder, _model_is_available  # shared model-match rule; keep one source
from core.models import (
    Answer,
    AnswerPart,
    Citation,
    CiteAnchor,
    CitePart,
    Embedding,
    InlineCitationMode,
    ModelNotPulledError,
    OllamaUnreachableError,
    Query,
    RagEngineError,
    RetrievedContext,
    SufficiencyVerdict,
    TextPart,
)

# Same rationale as the Embedder preflight: long enough for a cold local server,
# short enough to fail fast when nothing is listening.
_TAGS_TIMEOUT_SECONDS = 5

# Generation is the slow path (the LLM thinks token-by-token on local hardware),
# so this is far longer than the preflight: wait out a real reply, don't give up.
_CHAT_TIMEOUT_SECONDS = 300

# Low temperature for grounding: generation should hug the provided context, not
# get creative. Exposed as a constructor arg with this default — tunable, not magic.
_DEFAULT_TEMPERATURE = 0.1

# The Abstention text (Spanish — this is end-user UI content, FR8/G5). Centralized
# so the deterministic guard and any future LLM-side abstention read identically.
ABSTENTION_TEXT = "No encuentro esto en los documentos proporcionados."


# --- structured citation anchoring (inline_citation_mode="structured") --------
# The [N]-marker mechanism this replaced proved intermittent on the 7B (markers
# appeared or vanished per run/phrasing). This section works in two deterministic
# steps: (1) the Generator writes CLEAN prose (no markers), (2) a second LLM
# call with format:"json" anchors each sentence to its supporting fragment,
# validated fail-safe. CiteParts are born from validated anchors, not from the
# model's marker discipline.

# Spanish abbreviation endings a pragmatic splitter must NOT treat as sentence
# boundaries ("art. 21", "pág. 4", "p.ej. esto"). Lowercase, dot included;
# matched against the whitespace-delimited token ending at the candidate dot.
_ABBREVIATION_ENDINGS = frozenset(
    {
        "art.",
        "arts.",
        "núm.",
        "núms.",
        "apdo.",
        "apdos.",
        "pág.",
        "págs.",
        "cap.",
        "caps.",
        "p.",
        "ej.",
        "p.ej.",
        "vid.",
        "cfr.",
        "op.",
        "cit.",
        "ss.",
        "sr.",
        "sra.",
        "dr.",
        "dra.",
        "d.",
        "dña.",
        "etc.",
    }
)

# Technical instruction for the anchor pass. Lives in core as a constant, NOT
# in the vertical YAML: it is machine instruction (JSON in, JSON out), not
# vertical tone — the same anchoring contract for every Vertical (rule 2).
_ANCHOR_SYSTEM_PROMPT = (
    "Eres un verificador de citas para un sistema de recuperación de "
    "documentos. Recibirás las FRASES numeradas de una respuesta y los "
    "FRAGMENTOS numerados de los documentos usados para redactarla. Para "
    "cada frase cuya afirmación esté respaldada por el contenido de un "
    "fragmento, emite el par frase-fragmento. Una frase puede estar "
    "respaldada por varios fragmentos (un par por cada uno); omite por "
    "completo las frases sin respaldo. Responde ÚNICAMENTE con JSON válido, "
    "sin texto adicional, con esta forma exacta: "
    '{"anchors": [{"sentence": 1, "chunk": 2}]} '
    "donde sentence es el número de la frase y chunk el número del fragmento."
)


def split_into_sentences(text: str) -> list[str]:
    """Deterministic sentence segmentation for the anchor pass.

    Pragmatic by design — the input is the Generator's own es-ES prose, not
    arbitrary text. A sentence ends at '.', '!' or '?' followed by whitespace,
    which already keeps decimals ("3,5"), article numbering ("38.1") and any
    unspaced dot intact; a Spanish abbreviation list catches the spaced false
    ends ("art. 21"). Each sentence KEEPS its trailing whitespace so
    ``"".join(result) == text`` holds exactly — the assembled TextParts must
    reproduce the answer verbatim, byte for byte.
    """
    if not text:
        return []
    sentences: list[str] = []
    start = 0
    i = 0
    while i < len(text):
        if text[i] not in ".!?":
            i += 1
            continue
        if text[i] == "." and _ends_with_abbreviation(text, i):
            i += 1
            continue
        j = i + 1
        # Closing quotes/brackets belong to the sentence they close.
        while j < len(text) and text[j] in "\"'»”)":
            j += 1
        if j < len(text) and not text[j].isspace():
            # "38.1", "3.5", ids like BOE-A-2015-10565: a dot glued to the next
            # char is never a boundary.
            i = j
            continue
        while j < len(text) and text[j].isspace():
            j += 1
        sentences.append(text[start:j])
        start = j
        i = j
    if start < len(text):
        sentences.append(text[start:])
    return sentences


def _ends_with_abbreviation(text: str, dot_index: int) -> bool:
    """Is the dot at ``dot_index`` the end of a known Spanish abbreviation?"""
    start = dot_index - 1
    while start >= 0 and not text[start].isspace() and text[start] not in "([«\"'":
        start -= 1
    token = text[start + 1 : dot_index + 1].lower()
    return token in _ABBREVIATION_ENDINGS


def _parse_anchor_json(raw: str, num_sentences: int, num_chunks: int) -> list[CiteAnchor]:
    """Validate the anchor pass's JSON into CiteAnchors — fail-safe by design.

    The anchor pass is ADDITIVE: any failure here degrades to no chips, never
    a broken answer (rules 3/5 — the grounded text and its sources panel
    already exist; a chip is enhancement, not integrity). So: unparseable JSON
    → empty list; a malformed or out-of-range entry → that entry dropped;
    duplicates collapsed. Bools are rejected explicitly (bool is an int
    subclass — ``True`` must not pass as sentence 1).
    """
    try:
        payload = json.loads(raw)
    except ValueError:
        return []
    entries = payload.get("anchors") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return []

    anchors: list[CiteAnchor] = []
    seen: set[tuple[int, int]] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        sentence, chunk = entry.get("sentence"), entry.get("chunk")
        if isinstance(sentence, bool) or isinstance(chunk, bool):
            continue
        if not isinstance(sentence, int) or not isinstance(chunk, int):
            continue
        if not (1 <= sentence <= num_sentences and 1 <= chunk <= num_chunks):
            continue
        key = (sentence, chunk)
        if key in seen:
            continue
        seen.add(key)
        anchors.append(CiteAnchor(sentence_index=sentence, chunk_index=chunk))
    # Stable order for assembly: by sentence, preserving the model's order of
    # chunks within a sentence.
    anchors.sort(key=lambda anchor: anchor.sentence_index)
    return anchors


def _cosine(a: Embedding, b: Embedding) -> float:
    """Plain cosine similarity — pure Python on purpose (no numpy dependency
    for one dot product; bge-m3 vectors are ~1k dims, this is microseconds)."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0  # a zero vector supports nothing; never divide by zero
    return dot / (norm_a * norm_b)


def verify_anchors(
    anchors: list[CiteAnchor],
    context: RetrievedContext,
    sentences: list[str],
    embedder: Embedder | None,
    fragment_to_citation: list[int],
    *,
    repair_margin: float,
    support_floor: float,
) -> list[CiteAnchor]:
    """AnchorVerifier: the LLM proposes, this deterministic guard disposes.

    The anchor pass emits IN-RANGE but sometimes semantically FALSE anchors
    (measured: a TOC page anchored for content living on another page; an
    ictus chunk anchored for a diabetes sentence). Each anchored sentence is
    scored (cosine) against every citation of ITS OWN context — chunks grouped
    by the same dedup key ``fragment_to_citation`` encodes, so two chunks of
    one (doc, page) count as one target and a same-page sibling never
    triggers a repair. Three branches, in precedence order:

      * discard: the context argmax is below ``support_floor`` — nothing the
        model saw supports the sentence, so no chip at all;
      * repair:  the argmax beats the anchored citation by more than
        ``repair_margin`` — remap to the argmax's best chunk. RELATIVE margin
        on purpose: absolute thresholds measurably do not separate true from
        false anchors (a known-false anchor scored 0.73, above the correct
        median);
      * keep:    small margins are legitimate ambiguity (adjacent pages with
        the same content sit at 0.005-0.03) — repairing them would churn.

    ADDITIVE like the anchor pass itself: no embedder wired (plain-constructor
    engines, tests), a chunk without its stored embedding, or a transient
    embedding failure all degrade to keeping the model's anchors — never a
    broken answer (rules 3/5).
    """
    if not anchors or embedder is None:
        return anchors
    if any(chunk.embedding is None for chunk in context):
        # All-or-nothing: scoring over a partial context could repair toward
        # whatever happens to carry a vector — worse than not verifying.
        return anchors

    # citation n -> its context chunk indexes (0-based), REUSING the dedup
    # remap instead of re-deriving the (doc, page) grouping here.
    chunks_by_citation: dict[int, list[int]] = {}
    for chunk_pos, citation_n in enumerate(fragment_to_citation):
        chunks_by_citation.setdefault(citation_n, []).append(chunk_pos)

    sentence_embeddings: dict[int, Embedding] = {}
    verified: list[CiteAnchor] = []
    for anchor in anchors:
        if anchor.sentence_index not in sentence_embeddings:
            try:
                sentence_embeddings[anchor.sentence_index] = embedder.embed_query(
                    sentences[anchor.sentence_index - 1].strip()
                )
            except RagEngineError:
                # Transient embedding failure: keep this anchor unverified
                # rather than dropping a chip the answer already earned.
                verified.append(anchor)
                continue
        sentence_embedding = sentence_embeddings[anchor.sentence_index]

        # Citation-level score: the best of its chunks (and WHICH chunk, so a
        # repair lands on a real fragment index).
        best_by_citation = {
            citation_n: max(
                (_cosine(sentence_embedding, context[pos].embedding), pos) for pos in positions
            )
            for citation_n, positions in chunks_by_citation.items()
        }
        anchored_n = fragment_to_citation[anchor.chunk_index - 1]
        cos_anchored = best_by_citation[anchored_n][0]
        argmax_n = max(best_by_citation, key=lambda n: best_by_citation[n][0])
        cos_max, best_pos = best_by_citation[argmax_n]

        # Exactly three branches, in precedence order. The floor is evaluated
        # ONCE, on cos_max: with a supported best target and a non-decisive
        # margin, the anchored citation is within delta of that support —
        # legitimate ambiguity, so discarding it there would be a false
        # negative chip (rule 3: honest visibility of what IS supported).
        if cos_max < support_floor:
            continue  # discard: even the best target is unsupported
        if cos_max - cos_anchored > repair_margin:
            verified.append(
                CiteAnchor(
                    sentence_index=anchor.sentence_index,
                    chunk_index=best_pos + 1,
                )
            )
            continue
        verified.append(anchor)  # keep: small margin = legitimate ambiguity
    return verified


def evaluate_answerability(
    context: RetrievedContext, *, margin_threshold: float
) -> SufficiencyVerdict:
    """AnswerabilityGate (B2): is this context SUFFICIENT to answer, by shape?

    Deterministic sibling of :func:`verify_anchors`, one step earlier in the
    pipeline: retrieval sufficiency instead of citation anchoring. Signal S1
    only — the relative top-1 margin over ``Chunk.distance`` (Chroma L2² in
    its native unit, lower = closer, zero transformations). RELATIVE on
    purpose: the ratio normalizes away the corpus's absolute distance scale
    (measured: legal and health distributions don't even overlap), so one mu
    semantics serves any vertical that opts in.

    Measured basis (docs/b2/measurements/): B2 queries retrieve
    topically-close-but-FLAT profiles (several look-alike chunks, no standout
    top-1); answerable queries show a standout. INSUFFICIENT when the margin
    sits under the vertical's measured mu.
    """
    distances: list[float] = []
    for chunk in context:
        if chunk.distance is None:
            # Never recompute, never assume: a retrieval-path Chunk without its
            # distance means the transient propagation broke, and a silent
            # SUFFICIENT would disable the gate invisibly (B2-NFR6).
            raise RagEngineError(
                "AnswerabilityGate received a retrieved Chunk without a "
                "distance. The transient-distance propagation "
                "(Retriever._to_chunk -> Chunk.distance) is broken; fix "
                "core/retrieve.py — the gate never recomputes distances."
            )
        distances.append(chunk.distance)

    if not distances:
        # Empty context is the HARD abstention guard's jurisdiction (it fires
        # before any LLM call, so this gate is never consulted for n=0). If a
        # caller asks anyway, sufficiency is not this gate's call — pass through.
        return SufficiencyVerdict.SUFFICIENT
    if len(distances) == 1:
        # No tail ⇒ no margin signal, and absence of signal is NEVER grounds
        # to abstain (SPEC_B2 v2 §5.1: an answerable control retrieves n=1).
        # This verdict means "no basis to override", not "measured sufficient".
        return SufficiencyVerdict.SUFFICIENT

    d_top1 = distances[0]  # nearest-first is the Retriever's ordering contract
    tail = distances[1:]
    tail_mean = sum(tail) / len(tail)
    if tail_mean == 0.0:
        # Gate-passing L2² distances are strictly positive; a zero tail mean is
        # corrupt data, not a measurable margin — refuse to divide.
        raise RagEngineError(
            "AnswerabilityGate: tail_mean is 0.0, so the relative margin is "
            "undefined — the retrieved distances look corrupt. Re-ingest the "
            "vertical and check the VectorStore before trusting any verdict."
        )
    margin = (tail_mean - d_top1) / tail_mean
    if margin < margin_threshold:
        return SufficiencyVerdict.INSUFFICIENT
    return SufficiencyVerdict.SUFFICIENT


def _parts_from_anchors(
    sentences: list[str],
    anchors: list[CiteAnchor],
    fragment_to_citation: list[int],
) -> list[AnswerPart]:
    """Interleave sentences and their anchored CiteParts into AnswerParts.

    Each anchored sentence emits its prose, then one CitePart per DISTINCT
    citation behind it — ``chunk_index`` remaps through the same dedup table
    the [N] path used (DRY), so two chunks sharing (doc, page) yield one chip.
    The chip sits right after the prose, before the sentence's trailing
    whitespace, so it reads attached to the claim it supports. Unanchored
    sentences stay plain text; adjacent TextParts merge (reused helper), and
    joining all TextParts reproduces the answer text exactly.
    """
    chunks_by_sentence: dict[int, list[int]] = {}
    for anchor in anchors:
        chunks_by_sentence.setdefault(anchor.sentence_index, []).append(anchor.chunk_index)

    parts: list[AnswerPart] = []
    for index, sentence in enumerate(sentences, 1):
        chunk_indexes = chunks_by_sentence.get(index)
        if not chunk_indexes:
            parts.append(TextPart(text=sentence))
            continue
        prose = sentence.rstrip()
        trailing = sentence[len(prose) :]
        parts.append(TextPart(text=prose))
        emitted: set[int] = set()
        for chunk_index in chunk_indexes:
            n = fragment_to_citation[chunk_index - 1]
            if n in emitted:
                continue
            emitted.add(n)
            parts.append(CitePart(n=n))
        if trailing:
            parts.append(TextPart(text=trailing))
    return _merge_adjacent_text(parts)


# --- shared text helpers -------------------------------------------------------


def strip_abstention_phrase(text: str) -> str:
    """Remove one LEADING and/or one TRAILING byte-exact ``ABSTENTION_TEXT``
    occurrence — and the whitespace/newlines immediately around each — or
    return ``text`` untouched.

    Why this exists: the 7B intermittently appends the abstention sentence
    after a real answer, and the prompt cannot suppress it (10 wording
    variants were tested; every one traded the trailing phrase for other
    regressions). An answer carrying "I can't find this" next to real content
    contradicts itself (golden rule 3: grounded+cited OR abstention, never
    both), so the contradiction is removed deterministically here instead of
    hoped away in the prompt.

    Why symmetric (leading too): with abstention authority now on retrieval
    STATE (the API flags abstention only when retrieval returned nothing —
    never on prose), a reply that LEADS with the phrase and then carries real
    cited content flows through resolution like any answer; the leading
    contradiction must be cleaned in this same single site, exactly like the
    trailing case always was.

    Deliberately narrow, as before: byte-exact occurrences at the EDGES only —
    never a mid-text occurrence, never a paraphrase. Callers must guard the
    pure-abstention case (see ``Generator._resolve_parts``): when the phrase
    IS the whole answer this returns "", and the caller keeps the original
    instead.
    """
    result = text
    lstripped = result.lstrip()
    if lstripped.startswith(ABSTENTION_TEXT):
        result = lstripped[len(ABSTENTION_TEXT) :].lstrip()
    rstripped = result.rstrip()
    if rstripped.endswith(ABSTENTION_TEXT):
        result = rstripped[: -len(ABSTENTION_TEXT)].rstrip()
    return result


def _merge_adjacent_text(parts: list[AnswerPart]) -> list[AnswerPart]:
    """Collapse consecutive TextParts (unanchored sentences leave neighbours)."""
    merged: list[AnswerPart] = []
    for part in parts:
        if merged and isinstance(part, TextPart) and isinstance(merged[-1], TextPart):
            merged[-1] = TextPart(text=merged[-1].text + part.text)
        else:
            merged.append(part)
    return merged


class Generator:
    """Builds a grounded prompt from RetrievedContext + Query, calls the local LLM,
    returns a cited Answer (FR7–FR9).

    ``llm_model`` and ``ollama_base_url`` come from ``VerticalConfig`` and are the
    single source of truth for which model/endpoint to use (golden rule 4 — never
    hardcoded, never read from config here). ``system_prompt`` is the vertical's
    instruction block, also from config. The adapter calls Ollama's HTTP endpoint
    directly with ``requests``; tests mock ``requests.post`` so nothing touches
    the network.
    """

    def __init__(
        self,
        llm_model: str,
        ollama_base_url: str,
        system_prompt: str,
        *,
        temperature: float = _DEFAULT_TEMPERATURE,
        document_titles: dict[str, str] | None = None,
        inline_citation_mode: InlineCitationMode = "off",
        embedder: Embedder | None = None,
        anchor_repair_margin: float = 0.06,
        anchor_support_floor: float = 0.50,
        answerability_gate_enabled: bool = False,
        answerability_margin: float | None = None,
    ) -> None:
        self.llm_model = llm_model
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.system_prompt = system_prompt
        self.temperature = temperature
        # document_id → human title for the context-block header (from
        # VerticalConfig.document_titles, injected like every other config
        # value — plain data, zero vertical branching). Empty dict = today's
        # id-only headers; see _format_block.
        self.document_titles = dict(document_titles or {})
        # Chip strategy (VerticalConfig.inline_citation_mode): "structured"
        # pays the anchor pass for reliable chips; "off" (default, mirroring
        # the config default) skips it entirely. Plain data, no branching by
        # vertical — the Generator only ever consults the mode.
        self.inline_citation_mode: InlineCitationMode = inline_citation_mode
        # AnchorVerifier wiring: the sentence-embedding port plus the two
        # calibrated bounds (VerticalConfig, injected by the engine like every
        # other config value). None ⇒ verification skipped — plain-constructor
        # engines and unit tests keep working, the verifier stays additive.
        self.embedder = embedder
        self.anchor_repair_margin = anchor_repair_margin
        self.anchor_support_floor = anchor_support_floor
        # AnswerabilityGate wiring (B2): per-vertical on/off + measured mu,
        # injected from VerticalConfig like the verifier bounds above. The
        # config validator already forbids enabled-without-mu; re-checked here
        # because the plain constructor bypasses config — fail at wiring, not
        # mid-query (golden rule 5).
        if answerability_gate_enabled and answerability_margin is None:
            raise ValueError(
                "answerability_gate_enabled=True requires answerability_margin "
                "(the vertical's measured mu). Pass both, or disable the gate."
            )
        self.answerability_gate_enabled = answerability_gate_enabled
        self.answerability_margin = answerability_margin

    # --- the use case --------------------------------------------------------

    def generate(self, query: Query, context: RetrievedContext) -> Answer:
        """Produce a grounded, cited Answer — or abstain when there's nothing to ground on."""
        # HARD ABSTENTION GUARD (AC3 / G4): no context ⇒ no LLM call, deterministic
        # abstention. Return early before any model interaction so an empty corpus
        # or a zero-hit retrieval can never yield an invented answer.
        if not context:
            return Answer.abstention(ABSTENTION_TEXT)

        prompt = self._build_prompt(query, context)
        text = self._invoke_llm(prompt)

        # Citations are derived from the context the model was actually given — the
        # honest set of sources consulted. The Answer invariant then forbids a
        # non-abstaining Answer with no citations, so grounding can't silently slip.
        citations = self._citations_from_context(context)
        # parts: the typed view of the clean prose. In "structured" mode the
        # anchor pass builds CiteParts from validated sentence↔fragment
        # anchors (remapped through the dedup table so CitePart.n indexes
        # Answer.citations); in "off" mode the answer is one TextPart. Both
        # views come from the ONE resolution site (_resolve_parts), so a
        # stripped edge abstention disappears from text and parts at once.
        fragment_to_citation = self._fragment_index_to_citation_index(context, citations)
        text, parts = self._resolve_parts(text, context, fragment_to_citation)
        return Answer(text=text, citations=citations, parts=parts)

    def generate_stream(self, query: Query, context: RetrievedContext) -> Iterator[str]:
        """Stream the grounded reply as text fragments, yielded as the LLM emits them.

        Why this exists: on local hardware (e.g. an RTX 1080) a full reply can take
        1–2 minutes to generate. Streaming does **not** make generation faster — it
        replaces a long, silent spinner with visible progress so the UI never *looks*
        hung. Only the *text* streams; the ``Citation``s do not change token-by-token,
        so callers derive them once from ``context`` (see :meth:`citations_for_context`).

        The non-streaming :meth:`generate` is kept intact as the tested fallback and
        for callers that want a whole ``Answer`` object in one call.
        """
        # HARD ABSTENTION GUARD (AC3 / G4): the exact same invariant as generate() —
        # an empty context yields the deterministic abstention sentence *whole* and
        # never calls the LLM. Yield-then-return so the caller's stream sink shows the
        # identical text the non-streaming path would return.
        if not context:
            yield ABSTENTION_TEXT
            return

        prompt = self._build_prompt(query, context)
        # Fail-fast is preserved: _invoke_llm_stream opens the connection before its
        # first yield, so an unreachable Ollama raises OllamaUnreachableError on the
        # first iteration — before any generated text reaches the caller.
        yield from self._invoke_llm_stream(prompt)

    def generate_stream_parts(
        self, query: Query, context: RetrievedContext
    ) -> Iterator[AnswerPart]:
        """Streaming twin of :meth:`generate` at AnswerPart granularity (3b).

        With clean-prose generation there are no inline markers to parse: the
        LIVE view is simply TextParts as fragments arrive (yield-through keeps
        laziness and fail-fast identical to :meth:`generate_stream`). Anchored
        CiteParts exist only in the FINAL resolution over the complete text —
        :meth:`parts_for_text`, which the API's done event serves — because
        anchoring needs the whole answer. In "structured" mode that second
        call adds latency between the last streamed token and the parts.

        Neither does the abstention-phrase strip happen here: emitted parts
        are already on the wire when an edge occurrence arrives. The
        authoritative views strip it (:meth:`parts_for_text` / :meth:`generate`).
        """
        for fragment in self.generate_stream(query, context):
            yield TextPart(text=fragment)

    def citations_for_context(self, context: RetrievedContext) -> list[Citation]:
        """Public seam to derive the Citations behind a context (FR9 / AC2).

        Streaming splits an Answer in two: the *text* streams from the LLM while the
        *Citations* are fixed the instant retrieval returns. The streaming caller
        renders the text with :meth:`generate_stream` and attaches sources via this
        method, so the SourcesPanel shows exactly the provenance the non-streaming
        path derives — same logic, one source of truth.
        """
        return self._citations_from_context(context)

    # --- final resolution: clean text → typed parts (both citation modes) ----

    def parts_for_text(self, text: str, context: RetrievedContext) -> tuple[str, list[AnswerPart]]:
        """Resolve a COMPLETED reply into (final text, typed parts) — the one
        public seam for the streaming close.

        Same logic :meth:`generate` uses; exposed so the API's done event can
        resolve the accumulated streamed text identically (one source of
        truth, no marker parsing anywhere else). In "structured" mode this is
        where the anchor pass runs — the latency between the last token and
        the parts.
        """
        citations = self._citations_from_context(context)
        fragment_to_citation = self._fragment_index_to_citation_index(context, citations)
        return self._resolve_parts(text, context, fragment_to_citation)

    def _resolve_parts(
        self,
        text: str,
        context: RetrievedContext,
        fragment_to_citation: list[int],
    ) -> tuple[str, list[AnswerPart]]:
        """THE single final-resolution site for clean-prose replies.

        Order matters: the abstention-phrase strip (leading AND trailing —
        symmetric since abstention authority moved to retrieval state) runs
        FIRST, so a mixed reply never reaches segmentation with the
        contradiction attached. With markers gone, cited-ness can no longer
        gate that strip (the old rule); the successor rule is: strip an edge
        occurrence unless the phrase IS the whole reply — a pure soft
        abstention stays intact, never emptied (rule 3).
        """
        stripped = strip_abstention_phrase(text)
        if stripped.strip():
            text = stripped

        if self.inline_citation_mode != "structured":
            # "off": no anchor pass, no chips, zero extra latency. The sources
            # panel still works — Answer.citations derive from context.
            return text, [TextPart(text=text)]
        if text.strip() == ABSTENTION_TEXT:
            # Soft abstention: nothing to anchor; spending a second LLM call
            # to confirm "no support" would be waste by construction.
            return text, [TextPart(text=text)]

        sentences = split_into_sentences(text)
        anchors = self.anchor_citations(sentences, context)
        # AnchorVerifier: between the anchor pass and assembly — repair
        # in-range-but-false anchors by relative margin before any CitePart
        # is born from them (see verify_anchors).
        anchors = verify_anchors(
            anchors,
            context,
            sentences,
            self.embedder,
            fragment_to_citation,
            repair_margin=self.anchor_repair_margin,
            support_floor=self.anchor_support_floor,
        )
        # AnswerabilityGate (B2), only where the vertical opted in: when the
        # retrieval SHAPE says the context cannot answer (flat top-1 margin
        # under the measured mu), the resolved state BECOMES the canonical
        # abstention — parts replaced whole, zero CiteParts. Bug B's byte-exact
        # authority downstream (query.py) then resolves is_abstention on its
        # own: no new decision path in the API, no prose matching anywhere.
        if (
            self.answerability_gate_enabled
            and evaluate_answerability(context, margin_threshold=self.answerability_margin)
            is SufficiencyVerdict.INSUFFICIENT
        ):
            return ABSTENTION_TEXT, [TextPart(text=ABSTENTION_TEXT)]
        if not anchors:
            # Degraded (anchor pass failed, found nothing, or nothing survived
            # verification): answer without chips, never a broken answer.
            return text, [TextPart(text=text)]
        return text, _parts_from_anchors(sentences, anchors, fragment_to_citation)

    # --- the anchor pass (inline_citation_mode="structured") -----------------

    def anchor_citations(self, sentences: list[str], context: RetrievedContext) -> list[CiteAnchor]:
        """Second LLM pass: anchor each supported sentence to its fragment.

        Sends numbered sentences + the SAME numbered fragment blocks the
        writing pass saw, constrained to JSON output (Ollama ``format:"json"``,
        temperature 0 — anchoring is classification, not writing), then
        validates deterministically (:func:`_parse_anchor_json`). ADDITIVE by
        contract: any failure — transport, HTTP, malformed JSON — degrades to
        no anchors (no chips), never a broken answer (rules 3/5). The primary
        reply already succeeded moments earlier, so swallowing a transient
        anchor failure hides no persistent outage: check_health still surfaces
        a down server loudly.
        """
        if not sentences or not context:
            return []
        try:
            raw = self._chat_once(
                [
                    {"role": "system", "content": _ANCHOR_SYSTEM_PROMPT},
                    {"role": "user", "content": self._build_anchor_prompt(sentences, context)},
                ],
                format_json=True,
                temperature=0.0,
            )
        except RagEngineError:
            return []
        return _parse_anchor_json(raw, num_sentences=len(sentences), num_chunks=len(context))

    def _build_anchor_prompt(self, sentences: list[str], context: RetrievedContext) -> str:
        """The anchor pass's user turn: numbered sentences + numbered fragments.

        Fragments reuse :meth:`_format_block` verbatim so the anchor model sees
        exactly the numbering (and human titles) the writing pass saw — one
        fragment indexing across both calls, no second numbering scheme.
        """
        numbered = "\n".join(
            f"{index}. {sentence.strip()}" for index, sentence in enumerate(sentences, 1)
        )
        blocks = "\n\n".join(
            self._format_block(index, chunk) for index, chunk in enumerate(context, 1)
        )
        return (
            f"FRASES DE LA RESPUESTA:\n{numbered}\n\n"
            f"FRAGMENTOS DE LOS DOCUMENTOS:\n{blocks}\n\n"
            "Devuelve el JSON de anclajes."
        )

    # --- grounded prompt assembly (FR7) --------------------------------------

    def _build_prompt(self, query: Query, context: RetrievedContext) -> str:
        """Assemble the user-side message: formatted citable context + the Query.

        The system_prompt (with the grounding/citation/Spanish rules) is sent
        separately as the system message; here we only build the human turn.
        """
        blocks = "\n\n".join(self._format_block(i, chunk) for i, chunk in enumerate(context, 1))
        # Spanish framing because the model answers in Spanish (G5); the binding
        # rules themselves live in the vertical's system_prompt, not here.
        return f"Contexto recuperado de los documentos:\n\n{blocks}\n\nPregunta: {query.text}"

    def _format_block(self, index: int, chunk) -> str:
        """One citable context block: provenance header + text.

        Uses the document_id and page guaranteed on every ChunkMetadata so the
        model can attribute claims to a real SourceDocument and page. When the
        vertical's ``document_titles`` knows this document, the human title
        leads the header: an opaque id alone ("BOE-A-2015-10565") gives the
        model no citable norm name, and it fills the gap from pretraining —
        the observed "RD-Ley 3/2012" misattribution. The document_id stays in
        the header regardless: it is the Citation anchor, never dropped. A
        document without a title entry falls back to today's id-only header.
        """
        md = chunk.metadata
        title = self.document_titles.get(md.document_id)
        if title is None:
            return f"[{index}] [Documento: {md.document_id}, pág. {md.page}]\n{chunk.text}"
        return f"[{index}] [Documento: {title} — {md.document_id}, pág. {md.page}]\n{chunk.text}"

    # --- citations (FR9 / AC2) ----------------------------------------------

    @staticmethod
    def _citations_from_context(context: RetrievedContext) -> list[Citation]:
        """Derive Citations from the consulted Chunks, deduped by (document_id, page).

        MVP choice: list the *sources consulted* (every Chunk in context), not
        sentence-by-sentence attribution. The LLM synthesizes across several chunks,
        so a clean list of the sources behind the Answer is both honest and
        sufficient — and it keeps the provenance the Retriever actually returned.
        Dedup so two chunks from the same document+page collapse to one Citation,
        preserving first-seen order (which mirrors relevance order) — the FIRST
        chunk seen also contributes ``chunk_text`` (the most relevant passage),
        which exists for the source viewer only and never enters the prompt.
        """
        citations: list[Citation] = []
        seen: set[tuple[str, int]] = set()
        for chunk in context:
            key = (chunk.metadata.document_id, chunk.metadata.page)
            if key in seen:
                continue
            seen.add(key)
            citations.append(Citation.from_chunk(chunk))
        return citations

    @staticmethod
    def _fragment_index_to_citation_index(
        context: RetrievedContext, citations: list[Citation]
    ) -> list[int]:
        """Remap table: prompt fragment ``[i+1]`` → 1-based index in ``citations``.

        The prompt numbers fragments 1..len(context), one per chunk
        (``_format_block``), but ``citations`` is deduped by (document_id, page)
        — two different indexings, so a fragment number used directly against
        the citations list would misindex whenever two chunks share a page.
        Each fragment resolves through its (doc, page) key to the POSITION of
        its deduped Citation, which is exactly the ``n`` a CitePart must carry:
        the renderer looks up ``Answer.citations[n - 1]``.
        """
        position = {(c.document_id, c.page): index for index, c in enumerate(citations, 1)}
        return [position[(chunk.metadata.document_id, chunk.metadata.page)] for chunk in context]

    # --- LLM call (FR7) + preflight (AC7) ------------------------------------

    def check_health(self) -> None:
        """Verify Ollama is reachable and the LLM model is pulled (fail-fast, AC7).

        Mirror of the Embedder preflight, kept as a distinct check so the two
        failure modes — server down vs. model not pulled — surface as different,
        actionable exceptions. Call once at engine startup before generating.
        """
        pulled = self._list_pulled_models()  # raises OllamaUnreachableError if down
        if not _model_is_available(self.llm_model, pulled):
            raise ModelNotPulledError(
                f"LLM model '{self.llm_model}' is not available in Ollama. "
                f"Pull it first: `ollama pull {self.llm_model}`."
            )

    def warm_up(self) -> None:
        """Force Ollama to load the LLM into VRAM before the first real Query.

        Why: the first generation of a session otherwise pays the model-load cost
        (``qwen2.5:7b`` ≈ 4.7 GB into VRAM), which reads as a hang. We send the
        smallest possible ``/api/chat`` request — a trivial message capped at a
        single predicted token (``num_predict = 1``) — purely to trigger the load;
        the reply is discarded, so no real answer is generated. ``keep_alive`` asks
        Ollama to hold the model resident afterwards, so the first user question
        finds it hot.

        This is an *optimization*, not the query path: fail-fast is still honoured
        here (a down server or missing model raises the usual actionable error), but
        the caller is expected to treat that failure as non-fatal — the same error
        surfaces loudly through :meth:`check_health` at startup, so swallowing it at
        the call site skips only the warm-up, it never hides the cause (golden rule 5).
        """
        requests = self._http()
        url = f"{self.ollama_base_url}/api/chat"
        body = {
            "model": self.llm_model,
            "messages": [{"role": "user", "content": "."}],
            "stream": False,
            # num_predict=1: emit at most one token — we want the model resident in
            # VRAM, not an actual answer.
            "options": {"num_predict": 1},
            # Hold the model loaded so the first real Query lands on a warm model.
            "keep_alive": "10m",
        }
        try:
            response = requests.post(url, json=body, timeout=_CHAT_TIMEOUT_SECONDS)
        except (requests.exceptions.RequestException, OSError) as exc:
            raise OllamaUnreachableError(
                f"Cannot reach Ollama at '{self.ollama_base_url}' while warming up. "
                "Start it with `ollama serve` and verify the base URL."
            ) from exc

        if response.status_code != 200:
            detail = self._error_detail(response)
            lowered = detail.lower()
            if "not found" in lowered or "pull" in lowered:
                raise ModelNotPulledError(
                    f"LLM model '{self.llm_model}' is not available in Ollama "
                    f"(warm-up /api/chat → HTTP {response.status_code}: {detail}). "
                    f"Pull it first: `ollama pull {self.llm_model}`."
                )
            raise RagEngineError(
                f"Ollama /api/chat at '{self.ollama_base_url}' returned HTTP "
                f"{response.status_code}: {detail} during warm-up."
            )

    def _list_pulled_models(self) -> set[str]:
        requests = self._http()
        url = f"{self.ollama_base_url}/api/tags"
        try:
            response = requests.get(url, timeout=_TAGS_TIMEOUT_SECONDS)
        except (requests.exceptions.RequestException, OSError) as exc:
            raise OllamaUnreachableError(
                f"Cannot reach Ollama at '{self.ollama_base_url}'. "
                "Start it with `ollama serve` and verify the base URL."
            ) from exc

        if response.status_code != 200:
            raise OllamaUnreachableError(
                f"Ollama at '{self.ollama_base_url}' returned HTTP "
                f"{response.status_code} for /api/tags. Verify the server and URL."
            )

        try:
            models = response.json().get("models", [])
            return {entry["name"] for entry in models}
        except (ValueError, KeyError, TypeError) as exc:
            raise OllamaUnreachableError(
                f"Unexpected /api/tags response from Ollama at "
                f"'{self.ollama_base_url}'. Verify it is really Ollama."
            ) from exc

    def _invoke_llm(self, user_prompt: str) -> str:
        """POST (system_prompt, user_prompt) to /api/chat and return the reply text.

        Direct HTTP to Ollama's stable ``/api/chat``, no SDK — same rationale as
        ``embed.py`` (see the module docstring): the ``ChatOllama`` path is
        brittle across LangChain versions, so we speak the documented HTTP API.
        """
        return self._chat_once(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            # Low temperature keeps generation hugging the grounding context.
            temperature=self.temperature,
        )

    def _chat_once(
        self,
        messages: list[dict],
        *,
        temperature: float,
        format_json: bool = False,
    ) -> str:
        """One non-streamed /api/chat call — shared by the writing pass and the
        anchor pass, so both speak the same endpoint with the same fail-fast
        error mapping. ``format_json=True`` sets Ollama's native ``format:
        "json"`` (constrained decoding), used only by the anchor pass.
        """
        requests = self._http()
        url = f"{self.ollama_base_url}/api/chat"
        body = {
            "model": self.llm_model,
            "messages": messages,
            # Non-streamed: we want the whole reply in one JSON response, not a
            # token stream to reassemble.
            "stream": False,
            "options": {"temperature": temperature},
        }
        if format_json:
            body["format"] = "json"
        try:
            response = requests.post(url, json=body, timeout=_CHAT_TIMEOUT_SECONDS)
        except (requests.exceptions.RequestException, OSError) as exc:
            # Connection refused / DNS / timeout — the server isn't answering.
            raise OllamaUnreachableError(
                f"Cannot reach Ollama at '{self.ollama_base_url}' while generating. "
                "Start it with `ollama serve` and verify the base URL."
            ) from exc

        if response.status_code != 200:
            detail = self._error_detail(response)
            lowered = detail.lower()
            # Ollama answers an unknown model with a "not found, try pulling it"
            # error; surface that as the actionable model error, not a generic one.
            if "not found" in lowered or "pull" in lowered:
                raise ModelNotPulledError(
                    f"LLM model '{self.llm_model}' is not available in Ollama "
                    f"(/api/chat → HTTP {response.status_code}: {detail}). "
                    f"Pull it first: `ollama pull {self.llm_model}`."
                )
            raise RagEngineError(
                f"Ollama /api/chat at '{self.ollama_base_url}' returned HTTP "
                f"{response.status_code}: {detail}."
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise RagEngineError(
                f"Ollama /api/chat at '{self.ollama_base_url}' returned a "
                "non-JSON response. Verify it is really Ollama."
            ) from exc

        # Ollama's non-streamed reply nests the text at message.content.
        message = payload.get("message") if isinstance(payload, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise RagEngineError(
                f"Ollama /api/chat at '{self.ollama_base_url}' returned no "
                "message content. Verify the server version and model."
            )
        return content

    def _invoke_llm_stream(self, user_prompt: str) -> Iterator[str]:
        """POST to /api/chat with ``stream=True`` and yield each content fragment.

        Ollama streams NDJSON: one JSON object per line, each carrying an incremental
        ``message.content``, until a final line with ``done: true``. We consume it with
        ``requests``' ``stream=True`` + ``iter_lines()``, parse each line, and yield the
        text pieces as they arrive. Same endpoint and same fail-fast error mapping as
        the non-streamed path — only ``stream`` and the response handling differ.
        """
        requests = self._http()
        url = f"{self.ollama_base_url}/api/chat"
        body = {
            "model": self.llm_model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            # Streamed: ask Ollama to emit incremental NDJSON fragments so the UI can
            # render tokens as they are produced instead of waiting for the whole reply.
            "stream": True,
            "options": {"temperature": self.temperature},
        }
        try:
            response = requests.post(url, json=body, timeout=_CHAT_TIMEOUT_SECONDS, stream=True)
        except (requests.exceptions.RequestException, OSError) as exc:
            # Raised before any fragment is yielded — fail-fast, loud, actionable.
            raise OllamaUnreachableError(
                f"Cannot reach Ollama at '{self.ollama_base_url}' while generating. "
                "Start it with `ollama serve` and verify the base URL."
            ) from exc

        if response.status_code != 200:
            detail = self._error_detail(response)
            lowered = detail.lower()
            # Same actionable model error as the non-streamed path.
            if "not found" in lowered or "pull" in lowered:
                raise ModelNotPulledError(
                    f"LLM model '{self.llm_model}' is not available in Ollama "
                    f"(/api/chat → HTTP {response.status_code}: {detail}). "
                    f"Pull it first: `ollama pull {self.llm_model}`."
                )
            raise RagEngineError(
                f"Ollama /api/chat at '{self.ollama_base_url}' returned HTTP "
                f"{response.status_code}: {detail}."
            )

        for line in response.iter_lines():
            if not line:
                continue  # Ollama may emit keep-alive blank lines; skip them.
            try:
                payload = json.loads(line)
            except ValueError:
                # A malformed line shouldn't abort a reply that's otherwise arriving;
                # skip it rather than crash mid-stream.
                continue
            message = payload.get("message") if isinstance(payload, dict) else None
            fragment = message.get("content") if isinstance(message, dict) else None
            if fragment:
                yield fragment
            if isinstance(payload, dict) and payload.get("done"):
                break

    @staticmethod
    def _error_detail(response) -> str:
        """Best-effort human-readable reason from a non-200 Ollama response."""
        try:
            body = response.json()
        except ValueError:
            return (getattr(response, "text", "") or "").strip() or "<no body>"
        if isinstance(body, dict) and "error" in body:
            return str(body["error"])
        return str(body)

    @staticmethod
    def _http():
        try:
            import requests
        except ImportError as exc:
            raise RagEngineError(
                "requests is required to reach Ollama. "
                "Install it with `pip install -r requirements.txt`."
            ) from exc
        return requests
