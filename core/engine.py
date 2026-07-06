"""RagEngine: the Application-layer composition root (module 7, G1, FR10 → AC4).

This is the **only** place in the codebase that instantiates the concrete adapters
(``OllamaEmbedder``, ``VectorStore``, ``Generator``) and wires them together. Every
``core/`` piece keeps depending on abstractions (the ``Embedder`` port, the injected
``VectorStore``/``Retriever``/``Generator``); the engine performs the composition.
That is exactly why the Application layer — and not the Domain — is allowed to import
the concrete adapters: it is the composition root, the seam where the abstract graph
is given concrete implementations.

Vertical-agnostic by construction (golden rule 2, G1): the engine never knows what
"legal" or "health" *means*. It only reads a ``VerticalConfig`` and wires from its
fields. There is no ``if vertical == ...`` here, and there must never be — switching
Vertical is switching the ``VerticalConfig`` that flows in (FR10/AC4), nothing more.

Still no UI/web framework here; Application depends inward on Domain, never on
presentation.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from core.embed import OllamaEmbedder
from core.generate import Generator
from core.ingest import load_vertical_config
from core.models import (
    Answer,
    AnswerPart,
    Citation,
    CitePart,
    CorpusStats,
    Query,
    RagEngineError,
    Vertical,
    VerticalConfig,
)
from core.retrieve import Retriever
from core.store import VectorStore


@dataclass(frozen=True)
class StreamedAnswer:
    """The streaming counterpart of an :class:`Answer`: content arrives
    incrementally, Citations are known up front.

    ``part_stream`` is the LIVE view: TextParts as the LLM emits clean prose
    (no inline markers — the citation redesign anchors citations after the
    fact). ``citations`` are derived from the retrieved context the moment
    retrieval returns — they do not change token-by-token — so the
    SourcesPanel renders from the same provenance the non-streaming
    :meth:`RagEngine.answer` carries.

    ``resolve_parts`` is the CLOSE seam: call it once with the accumulated
    full text and it returns the (final text, anchored parts) the Generator's
    ``parts_for_text`` produces — already bound to THIS answer's retrieved
    context, so the caller (the API's done event) never handles a
    RetrievedContext. In "structured" mode this is where the anchor pass runs
    (second LLM call — the latency between the last token and the parts).

    ``text_stream`` remains for plain-text consumers as a DERIVED view (see
    the property below), so nothing that renders raw text had to change.

    Trade-off, stated loudly: part_stream/text_stream wrap the SAME single-use
    LLM stream. Consume exactly ONE of them, exactly once — handing out two
    live iterators would require either a second LLM call or buffering the
    whole reply, both worse than this rule.
    """

    part_stream: Iterator[AnswerPart]
    citations: list[Citation]
    resolve_parts: Callable[[str], tuple[str, list[AnswerPart]]]

    @property
    def text_stream(self) -> Iterator[str]:
        """Compatibility view: the reply as plain text fragments.

        TextParts pass through; a validated marker is re-rendered as its
        literal ``[n]``. Two deliberate deviations from the raw LLM text: (1)
        markers dropped as invalid never re-appear — a cleanup, they had no
        source behind them; (2) ``n`` is the remapped citations-list index, so
        under dedup the digits may differ from what the LLM typed — but they
        now agree with the SourcesPanel ordering, which is what a reader cross-
        references.
        """
        return _plain_text_view(self.part_stream)


def _plain_text_view(parts: Iterator[AnswerPart]) -> Iterator[str]:
    for part in parts:
        if isinstance(part, CitePart):
            yield f"[{part.n}]"
        elif part.text:
            yield part.text


class RagEngine:
    """Orchestrates the full use case: a Query in, a grounded, cited Answer out (G1).

    Constructed two ways:
      * :meth:`from_vertical` / :meth:`from_vertical_config` — the real wiring from a
        ``VerticalConfig`` (the production path).
      * the plain constructor — accepts already-built ``Retriever``/``Generator`` (and
        optionally an ``embedder`` for the aggregated health check), so the use case
        is unit-testable without ever touching Ollama or Chroma.

    ``top_k`` is held from ``VerticalConfig.top_k`` and passed to every retrieval; it
    is never hardcoded.
    """

    def __init__(
        self,
        retriever: Retriever,
        generator: Generator,
        top_k: int,
        relevance_threshold: float,
        *,
        embedder: OllamaEmbedder | None = None,
        vector_store: VectorStore | None = None,
    ) -> None:
        self._retriever = retriever
        self._generator = generator
        self._top_k = top_k
        # Per-vertical relevance gate (VerticalConfig.relevance_threshold), fed to
        # every retrieval exactly like top_k — the engine holds it, never invents it.
        self._relevance_threshold = relevance_threshold
        # Held only so check_health() can delegate to the Embedder preflight as well
        # as the Generator's; not used on the query path.
        self._embedder = embedder
        # Held only so corpus_stats() can delegate to the store (same pattern as
        # _embedder above); the query path keeps reaching the store via Retriever.
        self._vector_store = vector_store

    # --- factories (the composition root) ------------------------------------

    @classmethod
    def from_vertical_config(cls, config: VerticalConfig) -> "RagEngine":
        """Wire all adapters from one VerticalConfig — the single instantiation site.

        Every concrete dependency is built here and injected; the embedding model
        flows into the Embedder while the same config is what later feeds query-time
        embedding, so ingest and query can never desynchronize models (golden rule 4).
        Construction is cheap and offline: the adapters build their Ollama/Chroma
        clients lazily, so this never hits the network.
        """
        embedder = OllamaEmbedder(
            model_name=config.embedding_model,
            ollama_base_url=config.ollama_base_url,
        )
        vector_store = VectorStore(collection_name=config.collection_name)
        retriever = Retriever(embedder, vector_store)
        generator = Generator(
            llm_model=config.llm_model,
            ollama_base_url=config.ollama_base_url,
            system_prompt=config.system_prompt,
            # Human titles for the context headers — config data, like top_k
            # and relevance_threshold (golden rule 2).
            document_titles=config.document_titles,
            # Chip strategy per vertical — data too; the Generator consumes
            # the mode, core never branches on the Vertical itself.
            inline_citation_mode=config.inline_citation_mode,
        )
        return cls(
            retriever=retriever,
            generator=generator,
            top_k=config.top_k,
            relevance_threshold=config.relevance_threshold,
            embedder=embedder,
            vector_store=vector_store,
        )

    @classmethod
    def from_vertical(cls, vertical: Vertical) -> "RagEngine":
        """Load the Vertical's YAML config, then wire the engine from it.

        YAML loading is shared with ``ingest.py``'s ``load_vertical_config`` so
        there is exactly one place that reads config (rule 4: ingest and query can
        never diverge on model names). A dedicated config module (module 9) may
        own it later; this call site won't change.
        """
        config = load_vertical_config(vertical)
        return cls.from_vertical_config(config)

    # --- the use case --------------------------------------------------------

    def answer(self, query: Query | str, *, where: dict | None = None) -> Answer:
        """Run the full pipeline: retrieve top_k context, then generate a cited Answer.

        Accepts a raw ``str`` for ergonomics and wraps it in a ``Query``. ``where`` is
        an optional metadata filter forwarded to retrieval (FR6); default ``None``
        searches the whole Collection. This is the single orchestration point — the
        Generator's abstention guard handles an empty context, so no special-casing
        is needed here.
        """
        if isinstance(query, str):
            query = Query(text=query)

        context = self._retriever.retrieve(
            query,
            top_k=self._top_k,
            relevance_threshold=self._relevance_threshold,
            where=where,
        )
        return self._generator.generate(query, context)

    def answer_stream(
        self, query: Query | str, *, where: dict | None = None
    ) -> StreamedAnswer:
        """Streaming twin of :meth:`answer` — same orchestration, incremental text.

        Streaming is *orchestration*, not presentation: it is still retrieve-then-
        generate, only split into two observable steps (retrieve the context, then
        stream the generated text). That split belongs here in the Application layer,
        exactly like :meth:`answer`, so the UI consumes one public seam and never
        reaches into the Retriever/Generator itself — Presentation stays decoupled
        from Application (golden rule 1).

        Returns the text generator together with the Citations derived from the
        retrieved context. The empty-context (abstention) case is handled coherently
        with :meth:`answer`: the Generator's stream yields the abstention text whole
        and ``citations`` is empty, so no LLM call happens and no special-casing is
        needed here. ``generate_stream`` is lazy, so an unreachable Ollama still fails
        fast on the caller's first iteration, before any text is shown.
        """
        if isinstance(query, str):
            query = Query(text=query)

        context = self._retriever.retrieve(
            query,
            top_k=self._top_k,
            relevance_threshold=self._relevance_threshold,
            where=where,
        )
        # Citations are fixed the instant retrieval returns; only content streams.
        part_stream = self._generator.generate_stream_parts(query, context)
        citations = self._generator.citations_for_context(context)
        return StreamedAnswer(
            part_stream=part_stream,
            citations=citations,
            # Bound to THIS retrieval's context so the streaming consumer can
            # resolve the final anchored parts at close without ever holding a
            # RetrievedContext itself (Presentation stays decoupled).
            resolve_parts=lambda full_text: self._generator.parts_for_text(
                full_text, context
            ),
        )

    def warm_up(self) -> None:
        """Preload the LLM into VRAM before the first Query (latency optimization).

        Delegates to the Generator's warm-up so Presentation can trigger it through
        the engine's public interface, never reaching into the Generator itself.
        Best-effort by nature (see :meth:`Generator.warm_up`): the caller may treat a
        failure as non-fatal, because the actionable reachability/model error still
        surfaces loudly through :meth:`check_health`.
        """
        self._generator.warm_up()

    # --- aggregated preflight (NFR6/AC7) -------------------------------------

    def check_health(self) -> None:
        """Verify all external prerequisites up front, failing fast and loud.

        Delegates to the existing Embedder and Generator preflights rather than
        re-implementing reachability/model checks: each surfaces its own distinct,
        actionable error (Ollama down vs. a specific model not pulled). Call once at
        startup before serving queries.
        """
        if self._embedder is not None:
            self._embedder.check_health()
        self._generator.check_health()

    # --- read-only Corpus snapshot --------------------------------------------

    def corpus_stats(self) -> CorpusStats:
        """Expose the Corpus snapshot — a façade that delegates to the VectorStore.

        The engine neither counts nor knows Chroma; it forwards the embedding
        model name from the SAME Embedder the ingest/query paths use (golden
        rule 4: one source, impossible to desynchronize). Engines built through
        the plain test constructor without these collaborators fail fast
        instead of inventing stats.
        """
        if self._vector_store is None or self._embedder is None:
            raise RagEngineError(
                "corpus_stats() requires an engine wired with a VectorStore and "
                "an Embedder. Build it via RagEngine.from_vertical_config()."
            )
        return self._vector_store.corpus_stats(
            embedding_model=self._embedder.model_name
        )

    @classmethod
    def corpus_stats_for(cls, config: VerticalConfig) -> CorpusStats:
        """Corpus snapshot WITHOUT building the full engine — no Generator, no warm-up.

        For callers that need counts for Verticals that are NOT active (e.g. the
        welcome's domain cards, one per Vertical): only the Vertical's VectorStore
        is built — on the same default persist path as ``from_vertical_config``,
        so both roads read the same persistence — and the model name comes from
        the same config field the Embedder is built from (golden rule 4).
        Delegates to :meth:`VectorStore.corpus_stats`: one logic site (DRY).
        """
        store = VectorStore(collection_name=config.collection_name)
        return store.corpus_stats(embedding_model=config.embedding_model)
