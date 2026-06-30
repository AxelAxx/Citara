"""Retriever: top-k similarity search over the active Collection (module 5, FR6 → AC2, AC6).

This is pure domain orchestration — no framework, no vertical branching. It depends
only on the two ports it is handed: an ``Embedder`` (not ``OllamaEmbedder``) and a
``VectorStore``. The concrete Ollama/Chroma adapters are injected by ``engine.py``;
this module never imports them (golden rule 1, dependencies point inward).

Same-model guarantee (golden rule 4): the Query is embedded with ``embed_query`` on
the very Embedder that ingestion used, because both are built from one
``VerticalConfig.embedding_model``. Mismatched models silently destroy retrieval, so
the only safe place to enforce sameness is *construction* — done in ``engine.py``,
relied on here.

The other job of this module is the **inverse flattening boundary**. ``store.py``
flattened ``ChunkMetadata`` into Chroma-safe primitives on the way in; here
``rebuild_metadata`` mirrors that, turning the flat dict back into a rich
``ChunkMetadata`` (str → ``Path``/``Vertical``) so the rest of ``core/`` — and every
Citation — speaks the domain types again.
"""

from __future__ import annotations

from pathlib import Path

from core.embed import Embedder
from core.models import (
    Chunk,
    ChunkMetadata,
    Query,
    RetrievalError,
    RetrievedContext,
    Vertical,
)
from core.store import QueryHit, VectorStore


def rebuild_metadata(flat: dict) -> ChunkMetadata:
    """Reconstruct a ChunkMetadata from Chroma's flat metadata dict.

    The exact inverse of ``store.flatten_metadata``: primitives come back as the
    rich domain types (``vertical`` str → ``Vertical``, ``source_path`` str →
    ``Path``), and absent optional keys become ``None``.

    ``document_id`` and ``page`` are mandatory — a Chunk without them cannot be
    cited, which is a defect, not a partial result. If either is missing the stored
    row is corrupt, so we fail fast (RetrievalError) rather than hand back a
    half-built Chunk that would surface later as a broken Citation.
    """
    if "document_id" not in flat or "page" not in flat:
        raise RetrievalError(
            "Retrieved a chunk whose metadata is missing 'document_id' and/or "
            f"'page' (got keys {sorted(flat)}). The Collection looks corrupt; "
            "re-ingest the vertical: `python -m core.ingest --vertical <vertical>`."
        )

    vertical = flat.get("vertical")
    source_path = flat.get("source_path")
    return ChunkMetadata(
        document_id=flat["document_id"],
        page=flat["page"],
        section=flat.get("section"),  # optional; absent → None
        vertical=Vertical(vertical) if vertical is not None else None,
        source_path=Path(source_path) if source_path is not None else None,
    )


class Retriever:
    """Given a Query, returns the top-k most relevant Chunks from the active Collection (FR6).

    Holds the two ports it orchestrates and nothing else: no config, no vertical
    knowledge. ``top_k`` is a per-call argument (``engine.py`` passes
    ``VerticalConfig.top_k``); it is never hardcoded here.
    """

    def __init__(self, embedder: Embedder, vector_store: VectorStore) -> None:
        self._embedder = embedder
        self._vector_store = vector_store

    def retrieve(
        self,
        query: Query,
        top_k: int,
        where: dict | None = None,
    ) -> RetrievedContext:
        """Embed the Query, search the VectorStore, rebuild Chunks in relevance order.

        ``where`` is forwarded verbatim as Chroma's optional metadata filter (FR6).
        The returned ``RetrievedContext`` preserves the store's ordering — Chroma
        returns hits nearest-first, and that order is the relevance ranking the
        Generator depends on.
        """
        # Same model as ingestion by construction (golden rule 4) — embed_query, so
        # query-side normalization (if the model does any) matches the port's intent.
        embedding = self._embedder.embed_query(query.text)

        hits: list[QueryHit] = self._vector_store.query(embedding, top_k, where)

        # Order preserved: each QueryHit → Chunk, nearest-first as Chroma returned.
        return [self._to_chunk(hit) for hit in hits]

    @staticmethod
    def _to_chunk(hit: QueryHit) -> Chunk:
        """Map one QueryHit back to a domain Chunk via the inverse-flatten boundary."""
        return Chunk(text=hit.text, metadata=rebuild_metadata(hit.metadata))
