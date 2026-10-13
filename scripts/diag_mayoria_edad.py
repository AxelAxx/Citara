"""Standalone READ-ONLY diagnostic: why does the legal query about the age of
majority ("mayoria de edad") abstain, when the Constitution (BOE-A-1978-31229,
art. 12) is ingested?

Two probes to separate the hypotheses:
  A) Raw retrieval with the relevance gate DISABLED and a widened top_k=15 —
     shows the real distances the system sees, including the tail beyond the
     production gate (top_k=6, relevance_threshold=1.05).
  B) Content presence — pulls ALL ingested Constitution chunks and greps them
     for the art. 12 wording, proving whether the content survived
     loading/chunking at all.

Reuses the REAL production components (same bge-m3 Embedder, same Chroma
Collection at ./chroma_db) — no mocks, no reimplemented logic. Run from the
repo root: `python scripts/diag_mayoria_edad.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make `core` importable when run as a plain script from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Windows consoles may default to cp1252; the corpus is Spanish (accents).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from core.embed import OllamaEmbedder
from core.ingest import load_vertical_config
from core.models import Vertical
from core.store import VectorStore

QUERY = "¿A qué edad se alcanza la mayoría de edad según la Constitución?"
TARGET_DOCUMENT_ID = "BOE-A-1978-31229"  # Constitución Española
WIDENED_TOP_K = 15  # deliberately above production's 6, to see the tail
GATE = 1.05  # production relevance_threshold, printed for comparison only

# Case-insensitive markers of the art. 12 wording.
CONTENT_MARKERS = ("dieciocho", "mayoría de edad", "mayores de edad")


def snippet(text: str, length: int) -> str:
    """One-line snippet: collapse all whitespace/newlines, then truncate."""
    return " ".join(text.split())[:length]


def main() -> None:
    # Same construction path RagEngine.from_vertical_config uses: config -> the
    # one embedding model name -> Embedder; config.collection_name -> store.
    config = load_vertical_config(Vertical.LEGAL)
    print(
        f"config: vertical={config.vertical.value!r} "
        f"collection={config.collection_name!r} "
        f"embedding_model={config.embedding_model!r} "
        f"top_k={config.top_k} relevance_threshold={config.relevance_threshold}"
    )

    embedder = OllamaEmbedder(
        model_name=config.embedding_model,
        ollama_base_url=config.ollama_base_url,
    )
    store = VectorStore(collection_name=config.collection_name)
    # Raw Chroma Collection — the diag queries it directly to bypass the gate.
    collection = store._get_collection()
    print(f"collection count: {collection.count()} chunks\n")

    # ------------------------------------------------------------------ probe A
    print("=" * 100)
    print(f"PROBE A — raw retrieval, gate DISABLED, top_k={WIDENED_TOP_K}")
    print(f"query: {QUERY}")
    print("=" * 100)

    embedding = embedder.embed_query(QUERY)
    raw = collection.query(
        query_embeddings=[embedding],
        n_results=WIDENED_TOP_K,
        include=["documents", "metadatas", "distances"],
    )
    ids = raw["ids"][0]
    documents = raw["documents"][0]
    metadatas = raw["metadatas"][0]
    distances = raw["distances"][0]

    rows = sorted(zip(ids, documents, metadatas, distances), key=lambda row: row[3])
    header = (
        f"{'':4}{'rank':>4} | {'distance':>8} | {'gate<=1.05':>10} | "
        f"{'document_id':<20} | {'page':>4} | snippet"
    )
    print(header)
    print("-" * len(header))
    for rank, (_, document, metadata, distance) in enumerate(rows, start=1):
        document_id = metadata.get("document_id", "?")
        page = metadata.get("page", "?")
        marker = ">>> " if document_id == TARGET_DOCUMENT_ID else "    "
        passes = "PASS" if distance <= GATE else "FAIL"
        print(
            f"{marker}{rank:>4} | {distance:>8.4f} | {passes:>10} | "
            f"{document_id:<20} | {page:>4} | {snippet(document, 120)}"
        )

    # ------------------------------------------------------------------ probe B
    print()
    print("=" * 100)
    print(f"PROBE B — is the art. 12 content ingested? (all chunks of {TARGET_DOCUMENT_ID})")
    print("=" * 100)

    got = collection.get(
        where={"document_id": TARGET_DOCUMENT_ID},
        include=["documents", "metadatas"],
    )
    chunk_texts = got.get("documents") or []
    chunk_metadatas = got.get("metadatas") or []
    print(f"total ingested chunks for {TARGET_DOCUMENT_ID}: {len(chunk_texts)}")

    matches = [
        (metadata, text)
        for text, metadata in zip(chunk_texts, chunk_metadatas)
        if any(marker in text.lower() for marker in CONTENT_MARKERS)
    ]
    print(f"chunks matching {CONTENT_MARKERS} (case-insensitive): {len(matches)}\n")

    if not matches:
        print("art. 12 content NOT found in ingested chunks")
    else:
        for metadata, text in matches:
            print(f"page {metadata.get('page', '?'):>4} | {snippet(text, 200)}")

    # ------------------------------------------------------------------ probe C
    print()
    print("=" * 100)
    print(f"PROBE C — FULL untruncated text of {TARGET_DOCUMENT_ID} chunks on pages 5 and 8")
    print("=" * 100)

    # Reuse probe B's full fetch; filter by page in Python (got is already the
    # complete set of Constitution chunks with documents + metadatas).
    page_chunks = [
        (metadata, text)
        for text, metadata in zip(chunk_texts, chunk_metadatas)
        if metadata.get("page") in (5, 8)
    ]
    print(f"chunks on pages 5/8: {len(page_chunks)}\n")
    for index, (metadata, text) in enumerate(
        sorted(page_chunks, key=lambda pair: pair[0].get("page", 0)), start=1
    ):
        print(
            f"--- chunk {index} | page {metadata.get('page', '?')} | {len(text)} chars " + "-" * 40
        )
        print(text)
        print()


if __name__ == "__main__":
    main()
