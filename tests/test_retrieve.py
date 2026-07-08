"""Unit tests for the Retriever (module 5, FR6 → AC2, AC6).

No live Ollama or Chroma: the Embedder port and the VectorStore are both faked, so
the test asserts the *contract* — top_k Chunks in relevance order, each carrying a
correctly-typed ChunkMetadata rebuilt from Chroma's flat dict (Vertical/Path, not
str), ``where`` forwarded verbatim, ``embed_query`` called with the Query text
(same-model-by-construction), and corrupt metadata failing fast (RetrievalError).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.embed import Embedder
from core.models import Chunk, Query, RetrievalError, Vertical
from core.retrieve import Retriever, rebuild_metadata
from core.store import QueryHit, VectorStore


class _FakeEmbedder(Embedder):
    """Records the text it embedded and returns a fixed query vector."""

    def __init__(self, vector=None) -> None:
        self.embed_query_calls: list[str] = []
        self._vector = vector or [0.1, 0.2, 0.3]

    def embed_documents(self, texts):  # unused on the query path
        raise AssertionError("retrieve() must use embed_query, not embed_documents")

    def embed_query(self, text: str):
        self.embed_query_calls.append(text)
        return self._vector


class _FakeVectorStore(VectorStore):
    """VectorStore whose ``query`` replays canned hits and records its arguments."""

    def __init__(self, hits: list[QueryHit]) -> None:
        # Bypass VectorStore.__init__ (no real Chroma client) on purpose.
        self._hits = hits
        self.query_calls: list[dict] = []

    def query(self, embedding, top_k, where=None):
        self.query_calls.append({"embedding": embedding, "top_k": top_k, "where": where})
        return self._hits


def _hit(
    doc_id: str, page: int, text: str, distance: float | None = 0.5, **extra
) -> QueryHit:
    # distance defaults comfortably under the thresholds used in these tests, so
    # non-gate tests exercise their own concern without tripping the relevance gate.
    metadata = {"document_id": doc_id, "page": page, **extra}
    return QueryHit(
        id=f"{doc_id}-{page}", text=text, metadata=metadata, distance=distance
    )


def _make_retriever(hits, embedder=None):
    embedder = embedder or _FakeEmbedder()
    store = _FakeVectorStore(hits)
    return Retriever(embedder, store), embedder, store


# --- top_k and order (AC6) ---------------------------------------------------


def test_retrieve_returns_exactly_top_k_chunks_in_order():
    hits = [
        _hit("doc-a", 1, "primero"),
        _hit("doc-b", 2, "segundo"),
        _hit("doc-c", 3, "tercero"),
    ]
    retriever, _, store = _make_retriever(hits)

    context = retriever.retrieve(Query(text="¿plazo?"), top_k=3, relevance_threshold=1.0)

    assert len(context) == 3
    assert all(isinstance(c, Chunk) for c in context)
    # Relevance order preserved exactly as the store returned it.
    assert [c.text for c in context] == ["primero", "segundo", "tercero"]
    assert [c.metadata.document_id for c in context] == ["doc-a", "doc-b", "doc-c"]
    # top_k flows through to the store unchanged.
    assert store.query_calls[0]["top_k"] == 3


# --- metadata reconstruction: rich types, not str (AC2 provenance) -----------


def test_retrieve_rebuilds_richly_typed_metadata():
    hits = [
        _hit(
            "BOE-A-2015-11430",
            7,
            "texto",
            section="Artículo 3",
            vertical="legal",  # str on the wire -> Vertical
            source_path="data/legal/boe.pdf",  # str on the wire -> Path
        )
    ]
    retriever, _, _ = _make_retriever(hits)

    [chunk] = retriever.retrieve(Query(text="x"), top_k=1, relevance_threshold=1.0)
    md = chunk.metadata

    assert md.document_id == "BOE-A-2015-11430"
    assert md.page == 7
    assert md.section == "Artículo 3"
    # The inverse-flatten boundary: domain types restored, not left as str.
    assert md.vertical is Vertical.LEGAL
    assert isinstance(md.source_path, Path)
    assert md.source_path == Path("data/legal/boe.pdf")


def test_retrieve_leaves_absent_optionals_as_none():
    retriever, _, _ = _make_retriever([_hit("doc", 1, "t")])  # only mandatory keys

    [chunk] = retriever.retrieve(Query(text="x"), top_k=1, relevance_threshold=1.0)

    assert chunk.metadata.section is None
    assert chunk.metadata.vertical is None
    assert chunk.metadata.source_path is None


# --- where forwarding and same-model-by-construction -------------------------


def test_where_is_forwarded_verbatim_to_the_store():
    retriever, _, store = _make_retriever([_hit("doc", 1, "t")])
    where = {"document_id": "doc"}

    retriever.retrieve(Query(text="x"), top_k=5, relevance_threshold=1.0, where=where)

    assert store.query_calls[0]["where"] == where


def test_embed_query_called_with_query_text():
    embedder = _FakeEmbedder()
    retriever, _, store = _make_retriever([_hit("doc", 1, "t")], embedder=embedder)

    retriever.retrieve(
        Query(text="¿cuál es el plazo de recurso?"), top_k=5, relevance_threshold=1.0
    )

    # Same model as ingestion (golden rule 4) verified by construction: the Query
    # text reaches embed_query, and that embedding is what the store searches with.
    assert embedder.embed_query_calls == ["¿cuál es el plazo de recurso?"]
    assert store.query_calls[0]["embedding"] == embedder._vector


# --- fail-fast on corrupt metadata (NFR6) ------------------------------------


def test_hit_missing_page_raises_retrieval_error():
    # distance within the gate on purpose: a corrupt row must fail fast, not be
    # silently swallowed by the relevance filter before the check runs.
    bad = QueryHit(id="x", text="t", metadata={"document_id": "doc"}, distance=0.5)  # no page
    retriever, _, _ = _make_retriever([bad])

    with pytest.raises(RetrievalError):
        retriever.retrieve(Query(text="x"), top_k=1, relevance_threshold=1.0)


def test_hit_missing_document_id_raises_retrieval_error():
    # Same in-gate distance rationale as the missing-page test above.
    bad = QueryHit(id="x", text="t", metadata={"page": 1}, distance=0.5)  # no document_id
    retriever, _, _ = _make_retriever([bad])

    with pytest.raises(RetrievalError):
        retriever.retrieve(Query(text="x"), top_k=1, relevance_threshold=1.0)


# --- relevance gate (golden rule 3: noise never reaches the Generator) -------


def test_all_hits_beyond_threshold_yield_empty_context():
    # Off-domain Query: Chroma still returns top-k nearest, all far away. The gate
    # must empty the context so the deterministic abstention guard fires downstream.
    hits = [
        _hit("doc-a", 1, "ruido", distance=1.15),
        _hit("doc-b", 2, "ruido", distance=1.23),
        _hit("doc-c", 3, "ruido", distance=1.34),
    ]
    retriever, _, _ = _make_retriever(hits)

    context = retriever.retrieve(Query(text="¿capital de Marte?"), top_k=3, relevance_threshold=1.05)

    assert context == []


def test_all_hits_within_threshold_pass_untouched():
    hits = [
        _hit("doc-a", 1, "primero", distance=0.63),
        _hit("doc-b", 2, "segundo", distance=0.74),
        _hit("doc-c", 3, "tercero", distance=0.98),
    ]
    retriever, _, _ = _make_retriever(hits)

    context = retriever.retrieve(Query(text="¿vacaciones?"), top_k=3, relevance_threshold=1.05)

    # In-domain: the gate is invisible — same chunks, same relevance order.
    assert [c.text for c in context] == ["primero", "segundo", "tercero"]


def test_mixed_hits_keep_only_those_at_or_under_threshold():
    hits = [
        _hit("doc-a", 1, "cerca", distance=0.70),
        _hit("doc-b", 2, "en el borde", distance=1.05),  # == threshold: relevant
        _hit("doc-c", 3, "lejos", distance=1.06),  # just beyond: dropped
    ]
    retriever, _, _ = _make_retriever(hits)

    context = retriever.retrieve(Query(text="x"), top_k=3, relevance_threshold=1.05)

    assert [c.text for c in context] == ["cerca", "en el borde"]


def test_hit_without_distance_is_dropped():
    # A hit whose distance Chroma did not report cannot be shown to be relevant;
    # assuming relevance would silently reopen the noise path the gate closes.
    hits = [
        _hit("doc-a", 1, "con distancia", distance=0.5),
        _hit("doc-b", 2, "sin distancia", distance=None),
    ]
    retriever, _, _ = _make_retriever(hits)

    context = retriever.retrieve(Query(text="x"), top_k=2, relevance_threshold=1.05)

    assert [c.text for c in context] == ["con distancia"]


# --- transient distance rides onto the Chunk (AnswerabilityGate prerequisite) -


def test_to_chunk_propagates_distance_from_the_hit():
    # The distance is a per-retrieval fact, so it must survive the QueryHit →
    # Chunk boundary: the AnswerabilityGate measures the top-1 margin from the
    # resolved context, and recomputing distances there would need a second
    # embed call.
    chunk = Retriever._to_chunk(_hit("doc-a", 1, "texto", distance=0.42))

    assert chunk.distance == 0.42


def test_chunk_without_distance_still_validates():
    # Backcompat: distance is transient like ``embedding`` — every Chunk built
    # outside the retrieval path (ingest side, tests) keeps constructing
    # without it.
    chunk = Chunk(
        text="texto", metadata=rebuild_metadata({"document_id": "doc", "page": 1})
    )

    assert chunk.distance is None


# --- rebuild_metadata is the exact mirror of flatten_metadata ----------------


def test_rebuild_metadata_round_trips_flatten():
    from core.models import ChunkMetadata
    from core.store import flatten_metadata

    original = ChunkMetadata(
        document_id="doc-1",
        page=4,
        section="Sección 2",
        vertical=Vertical.HEALTH,
        source_path=Path("data/health/guia.pdf"),
    )

    assert rebuild_metadata(flatten_metadata(original)) == original
