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

from core.embed import OllamaEmbedder
from core.generate import Generator
from core.ingest import _load_vertical_config  # see TODO(module 9) below
from core.models import Answer, Query, Vertical, VerticalConfig
from core.retrieve import Retriever
from core.store import VectorStore


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
        *,
        embedder: OllamaEmbedder | None = None,
    ) -> None:
        self._retriever = retriever
        self._generator = generator
        self._top_k = top_k
        # Held only so check_health() can delegate to the Embedder preflight as well
        # as the Generator's; not used on the query path.
        self._embedder = embedder

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
        )
        return cls(
            retriever=retriever,
            generator=generator,
            top_k=config.top_k,
            embedder=embedder,
        )

    @classmethod
    def from_vertical(cls, vertical: Vertical) -> "RagEngine":
        """Load the Vertical's YAML config, then wire the engine from it.

        TODO(module 9 / config): YAML loading is reused from ``ingest.py``'s minimal
        ``_load_vertical_config`` so there is exactly one place that reads config
        today. Module 9 will own a dedicated config loader; until then we share that
        single helper rather than duplicate the parsing here.
        """
        config = _load_vertical_config(vertical)
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

        context = self._retriever.retrieve(query, top_k=self._top_k, where=where)
        return self._generator.generate(query, context)

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
