"""Unit tests for the VectorStore + ChromaDB adapter (module 4, FR5 → AC1, AC4).

No real ChromaDB: a fake client/collection records calls in memory, so nothing
touches ``./chroma_db`` and the tests assert the *contract* — that upsert uses
``upsert`` (not ``add``), that metadata is flattened to primitives, that query
forwards ``top_k``/``where`` and maps Chroma's response, and that failures surface
as a specific, actionable ``RetrievalError`` (NFR6/AC7).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.models import ChunkMetadata, RagEngineError, RetrievalError, Vertical
from core.store import QueryHit, VectorStore, flatten_metadata


class _FakeCollection:
    """Records upsert/query calls and replays a canned query response."""

    def __init__(self, count: int = 1, query_response: dict | None = None) -> None:
        self._count = count
        self._query_response = query_response or {}
        self.upsert_calls: list[dict] = []
        self.add_calls: list[dict] = []  # must stay empty: upsert, never add (AC1)
        self.query_calls: list[dict] = []

    def upsert(self, **kwargs) -> None:
        self.upsert_calls.append(kwargs)

    def add(self, **kwargs) -> None:  # present so a wrong call is observable
        self.add_calls.append(kwargs)

    def count(self) -> int:
        return self._count

    def query(self, **kwargs) -> dict:
        self.query_calls.append(kwargs)
        return self._query_response


class _FakeClient:
    """Stand-in for chromadb.PersistentClient; hands back one fake Collection."""

    def __init__(self, collection: _FakeCollection) -> None:
        self._collection = collection
        self.requested_names: list[str] = []

    def get_or_create_collection(self, name: str) -> _FakeCollection:
        self.requested_names.append(name)
        return self._collection


def _make_store(collection: _FakeCollection, name: str = "health_chunks") -> VectorStore:
    return VectorStore(collection_name=name, client=_FakeClient(collection))


# --- flatten_metadata: the one Path/Vertical/None flattening site ------------


def test_flatten_metadata_converts_rich_types_and_drops_none():
    metadata = ChunkMetadata(
        document_id="BOE-A-2015-11430",
        page=7,
        section=None,  # dropped
        vertical=Vertical.LEGAL,  # -> "legal"
        source_path=Path("data/legal/boe.pdf"),  # -> str
    )

    flat = flatten_metadata(metadata)

    assert flat == {
        "document_id": "BOE-A-2015-11430",
        "page": 7,
        "vertical": "legal",
        "source_path": str(Path("data/legal/boe.pdf")),
    }
    assert "section" not in flat  # None must be dropped, not stored as null
    # Every value is a Chroma-safe primitive.
    assert all(isinstance(v, (str, int, float, bool)) for v in flat.values())


def test_flatten_metadata_keeps_present_section():
    metadata = ChunkMetadata(document_id="doc", page=1, section="Artículo 3")
    assert flatten_metadata(metadata)["section"] == "Artículo 3"


# --- upsert idempotency (AC1): uses upsert, not add --------------------------


def test_upsert_calls_collection_upsert_not_add():
    collection = _FakeCollection()
    store = _make_store(collection)

    ids = ["id-a", "id-b"]
    texts = ["uno", "dos"]
    embeddings = [[0.1, 0.2], [0.3, 0.4]]
    metadatas = [{"document_id": "doc", "page": 1}, {"document_id": "doc", "page": 2}]

    store.upsert(ids, texts, embeddings, metadatas)

    assert collection.add_calls == []  # AC1: never add (would duplicate)
    assert len(collection.upsert_calls) == 1
    call = collection.upsert_calls[0]
    assert call["ids"] == ids
    assert call["documents"] == texts  # Chroma's param is "documents"
    assert call["embeddings"] == embeddings
    assert call["metadatas"] == metadatas


def test_upsert_empty_is_noop():
    collection = _FakeCollection()
    store = _make_store(collection)

    store.upsert([], [], [], [])

    assert collection.upsert_calls == []


def test_upsert_rejects_misaligned_lists():
    collection = _FakeCollection()
    store = _make_store(collection)

    with pytest.raises(RagEngineError):
        store.upsert(["id-a"], ["uno", "dos"], [[0.1]], [{"document_id": "d", "page": 1}])


def test_upsert_wraps_chroma_failure_as_retrieval_error():
    class _BoomCollection(_FakeCollection):
        def upsert(self, **kwargs):
            raise RuntimeError("disk full")

    store = _make_store(_BoomCollection())

    with pytest.raises(RetrievalError):
        store.upsert(["id"], ["t"], [[0.1]], [{"document_id": "d", "page": 1}])


# --- query: forwards top_k / where, maps Chroma's response -------------------


def test_query_forwards_top_k_and_where_and_maps_results():
    response = {
        "ids": [["id-a", "id-b"]],
        "documents": [["texto a", "texto b"]],
        "metadatas": [
            [{"document_id": "doc", "page": 1}, {"document_id": "doc", "page": 2}],
        ],
        "distances": [[0.12, 0.34]],
    }
    collection = _FakeCollection(count=2, query_response=response)
    store = _make_store(collection)

    where = {"document_id": "doc"}
    hits = store.query([0.5, 0.6], top_k=5, where=where)

    # forwarded verbatim to Chroma
    call = collection.query_calls[0]
    assert call["query_embeddings"] == [[0.5, 0.6]]
    assert call["n_results"] == 5
    assert call["where"] == where

    # mapped to the typed minimum retrieve.py needs
    assert hits == [
        QueryHit(id="id-a", text="texto a", metadata={"document_id": "doc", "page": 1}, distance=0.12),
        QueryHit(id="id-b", text="texto b", metadata={"document_id": "doc", "page": 2}, distance=0.34),
    ]


def test_query_omits_where_when_none():
    response = {"ids": [["id-a"]], "documents": [["t"]], "metadatas": [[{"document_id": "d", "page": 1}]]}
    collection = _FakeCollection(count=1, query_response=response)
    store = _make_store(collection)

    store.query([0.1], top_k=3)

    # Chroma rejects where={}; it must be absent, not empty.
    assert "where" not in collection.query_calls[0]


def test_query_tolerates_missing_distances():
    response = {
        "ids": [["id-a"]],
        "documents": [["t"]],
        "metadatas": [[{"document_id": "d", "page": 1}]],
        # no "distances" key
    }
    store = _make_store(_FakeCollection(count=1, query_response=response))

    hits = store.query([0.1], top_k=1)

    assert hits[0].distance is None


# --- fail-fast (NFR6/AC7) ----------------------------------------------------


def test_query_on_empty_collection_raises_retrieval_error():
    store = _make_store(_FakeCollection(count=0))

    with pytest.raises(RetrievalError) as exc:
        store.query([0.1], top_k=5)
    # Actionable: names the ingest command as the fix.
    assert "core.ingest" in str(exc.value)


def test_query_wraps_chroma_failure_as_retrieval_error():
    class _BoomCollection(_FakeCollection):
        def query(self, **kwargs):
            raise RuntimeError("index error")

    store = _make_store(_BoomCollection(count=3))

    with pytest.raises(RetrievalError):
        store.query([0.1], top_k=5)


def test_collection_open_failure_raises_retrieval_error():
    class _BoomClient:
        def get_or_create_collection(self, name: str):
            raise RuntimeError("locked")

    store = VectorStore(collection_name="x", client=_BoomClient())

    with pytest.raises(RetrievalError):
        store.query([0.1], top_k=5)


# --- AC4: switching vertical is just a different collection_name -------------


def test_collection_name_is_passed_through_unchanged():
    collection = _FakeCollection(count=1, query_response={"ids": [[]], "documents": [[]], "metadatas": [[]]})
    client = _FakeClient(collection)
    store = VectorStore(collection_name="legal_chunks", client=client)

    store.query([0.1], top_k=1)

    # No vertical branching: the name flows straight to Chroma as given.
    assert client.requested_names == ["legal_chunks"]
