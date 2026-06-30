"""VectorStore: ChromaDB adapter + Collection management (module 4, FR5 → AC1, AC4).

This is the designated *adapter* module for persistence. ``chromadb`` is imported
**only here**, lazily, behind one class, so the rest of ``core/`` stays
framework-free (golden rule 1) and importing this module is cheap. A missing
``chromadb`` fails loud with an actionable message instead of an ImportError at
collection time.

Three design points this module is built around:

  * **One Collection per Vertical (AC4).** The Collection name arrives through the
    constructor (fed from ``VerticalConfig.collection_name`` by ``engine.py``); the
    store never reads config itself and never branches on the Vertical. Switching
    Vertical = constructing a VectorStore against a different ``collection_name``,
    with **no code change**.

  * **Idempotent upsert (AC1).** We call ``collection.upsert`` (never ``add``):
    re-ingesting with the same deterministic ``chunk_id``s from ``ingest.py``
    overwrites the existing rows instead of duplicating them. The deterministic id
    is the *mechanism*; this upsert is where it pays off.

  * **The metadata-flattening boundary.** ChromaDB metadata accepts only primitives
    (str/int/float/bool). The note in ``models.py`` deferred the conversion of rich
    domain types (``Path``, ``Vertical``) to the VectorStore adapter — this is that
    one place. ``flatten_metadata`` is the single flattening site; nothing upstream
    should pre-flatten.

Decoupling boundary: ``upsert`` and ``query`` speak in primitives and a small
result struct, never in ``ingest.py``'s types. The store NEVER imports from
``ingest.py``; ``engine.py`` unpacks ``IngestedChunk``s into the primitive lists
this module expects. On the read side, ``query`` returns raw-but-typed ``QueryHit``s
(id + text + flat metadata dict) and leaves the mapping back to ``Chunk`` /
``ChunkMetadata`` / ``RetrievedContext`` to ``retrieve.py`` (module 5) — the store
does not reconstruct domain objects, which would pull retrieval concerns inward.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.models import (
    ChunkMetadata,
    Embedding,
    RagEngineError,
    RetrievalError,
)

# Default persistence location (SPEC §9). Passed in by engine.py via config where
# available; defaulted here so the store is usable standalone in tests/scripts.
_DEFAULT_PERSIST_PATH = "./chroma_db"


def flatten_metadata(metadata: ChunkMetadata) -> dict:
    """Flatten a ChunkMetadata into Chroma-safe primitives — the one flattening site.

    Chroma metadata values must be str/int/float/bool: ``Path`` becomes its string
    form and ``Vertical`` its ``.value``. ``None`` fields are dropped entirely
    (Chroma rejects ``None`` values), which is lossless here since ``document_id``
    and ``page`` are always present and are all a Citation needs.
    """
    flat: dict = {
        "document_id": metadata.document_id,
        "page": metadata.page,
    }
    if metadata.section is not None:
        flat["section"] = metadata.section
    if metadata.vertical is not None:
        flat["vertical"] = metadata.vertical.value  # enum -> primitive
    if metadata.source_path is not None:
        flat["source_path"] = str(metadata.source_path)  # Path -> primitive
    return flat


@dataclass(frozen=True)
class QueryHit:
    """One retrieval result: the minimum ``retrieve.py`` needs to rebuild a Chunk.

    Deliberately not a ``Chunk``: the store returns the flat ``metadata`` dict as
    Chroma stored it and lets ``retrieve.py`` map it back to ``ChunkMetadata`` (and
    a Citation). ``distance`` is the similarity distance Chroma reports (lower =
    closer), kept for optional downstream ranking/inspection.
    """

    id: str
    text: str
    metadata: dict
    distance: float | None = None


class VectorStore:
    """Persistent store of Chunks + Embeddings + ChunkMetadata, backed by ChromaDB.

    Holds exactly one ``Collection`` (one Vertical's vectors). Everything it needs
    arrives through the constructor — ``collection_name`` and ``persist_path`` — so
    it carries no config knowledge and no vertical-specific logic. The underlying
    Chroma client is injectable so unit tests never touch a real ``./chroma_db``.
    """

    def __init__(
        self,
        collection_name: str,
        persist_path: str = _DEFAULT_PERSIST_PATH,
        *,
        client: object | None = None,
    ) -> None:
        self.collection_name = collection_name
        self.persist_path = persist_path
        self._client = client  # lazily built (PersistentClient) on first use if None
        self._collection = None  # lazily get_or_create on first use

    # --- write side (AC1) ----------------------------------------------------

    def upsert(
        self,
        ids: list[str],
        texts: list[str],
        embeddings: list[Embedding],
        metadatas: list[dict],
    ) -> None:
        """Idempotently persist Chunks. Primitive signature on purpose (no ingest coupling).

        Uses ``collection.upsert`` rather than ``add``: re-ingesting with the same
        deterministic ``chunk_id``s overwrites in place instead of duplicating —
        this is the mechanism behind AC1 idempotency. ``engine.py`` builds these
        parallel lists from ``IngestedChunk``s (flattening each ChunkMetadata via
        :func:`flatten_metadata`); the store never sees ``ingest.py``'s types.
        """
        if not ids:
            return  # nothing to persist; an empty upsert is a no-op, not an error

        # Guard the parallel-list contract loudly: a silent misalignment here would
        # attach the wrong provenance to a Chunk and corrupt every future Citation.
        if not (len(ids) == len(texts) == len(embeddings) == len(metadatas)):
            raise RagEngineError(
                "upsert() requires ids, texts, embeddings and metadatas to be the "
                f"same length (got {len(ids)}, {len(texts)}, {len(embeddings)}, "
                f"{len(metadatas)}). They are positionally paired."
            )

        collection = self._get_collection()
        try:
            collection.upsert(
                ids=ids,
                documents=texts,
                embeddings=embeddings,
                metadatas=metadatas,
            )
        except Exception as exc:  # Chroma raises a variety of internal errors
            raise RetrievalError(
                f"Failed to upsert {len(ids)} chunks into Collection "
                f"'{self.collection_name}' at '{self.persist_path}'. "
                "Verify the chroma_db directory is writable and not corrupted."
            ) from exc

    # --- read side (consumed by retrieve.py, module 5) -----------------------

    def query(
        self,
        embedding: Embedding,
        top_k: int,
        where: dict | None = None,
    ) -> list[QueryHit]:
        """Top-k similarity search over the active Collection (FR6).

        ``where`` is an optional Chroma metadata filter (FR6's optional filtering);
        when ``None`` it is omitted so Chroma searches the whole Collection. Returns
        raw-but-typed ``QueryHit``s and leaves the Chunk/Citation reconstruction to
        ``retrieve.py``. Fails fast (RetrievalError) on an empty Collection or any
        Chroma error, so a missing ingest surfaces loudly instead of as silent
        zero results (NFR6).
        """
        collection = self._get_collection()

        # An empty Collection means the Vertical was never ingested — actionable,
        # not "0 results". Caught before the query so the message names the fix.
        try:
            count = collection.count()
        except Exception as exc:
            raise RetrievalError(
                f"Could not read Collection '{self.collection_name}' at "
                f"'{self.persist_path}'. Verify the vertical has been ingested."
            ) from exc
        if count == 0:
            raise RetrievalError(
                f"Collection '{self.collection_name}' is empty. Ingest the vertical "
                "first: `python -m core.ingest --vertical <vertical>`."
            )

        # Chroma rejects where={} — only pass the filter when one was given.
        kwargs: dict = {"query_embeddings": [embedding], "n_results": top_k}
        if where:
            kwargs["where"] = where

        try:
            raw = collection.query(**kwargs)
        except Exception as exc:
            raise RetrievalError(
                f"Similarity search failed against Collection "
                f"'{self.collection_name}' at '{self.persist_path}'."
            ) from exc

        return self._to_hits(raw)

    @staticmethod
    def _to_hits(raw: dict) -> list[QueryHit]:
        """Map Chroma's list-of-lists response (one inner list per query) to QueryHits.

        We always query with a single embedding, so we read index ``[0]`` of each
        parallel array. ``distances`` may be absent depending on Chroma's include
        defaults; treat it as optional rather than assuming its presence.
        """
        ids = (raw.get("ids") or [[]])[0]
        documents = (raw.get("documents") or [[]])[0]
        metadatas = (raw.get("metadatas") or [[]])[0]
        distances_outer = raw.get("distances")
        distances = distances_outer[0] if distances_outer else [None] * len(ids)

        return [
            QueryHit(
                id=id_,
                text=text or "",
                metadata=metadata or {},
                distance=distance,
            )
            for id_, text, metadata, distance in zip(
                ids, documents, metadatas, distances
            )
        ]

    # --- lazy adapter wiring -------------------------------------------------

    def _get_collection(self):
        """Lazily resolve the one Collection, creating it if absent (get_or_create).

        get_or_create keeps ingest (first run creates) and query (reuses) on one
        path, and means switching Vertical is purely a matter of the
        ``collection_name`` this store was built with — no code branch.
        """
        if self._collection is None:
            client = self._get_client()
            try:
                self._collection = client.get_or_create_collection(
                    name=self.collection_name
                )
            except Exception as exc:
                raise RetrievalError(
                    f"Could not open Collection '{self.collection_name}' at "
                    f"'{self.persist_path}'. Verify the chroma_db directory is "
                    "accessible and not corrupted."
                ) from exc
        return self._collection

    def _get_client(self):
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def _build_client(self):
        try:
            import chromadb
        except ImportError as exc:
            raise RagEngineError(
                "chromadb is required for the VectorStore. "
                "Install it with `pip install -r requirements.txt`."
            ) from exc
        # PersistentClient writes to disk so a Collection survives between the
        # offline ingest run and later query sessions (SPEC §9).
        return chromadb.PersistentClient(path=self.persist_path)
