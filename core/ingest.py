"""Ingestion: Loader + Chunker + offline driver (module 2, FR1–FR3 → AC1).

This is the designated *adapter* module for the ingestion side of the pipeline:
``pymupdf4llm`` (PDF → text/pages), ``langchain`` (splitting), and ``tiktoken``
(token-length measurement) are imported **only here**, behind small classes, so
the rest of ``core/`` stays framework-free (golden rule 1). Those imports are
lazy: the module imports cleanly for unit tests, and a missing dependency fails
loud with an actionable message instead of an ImportError at collection time.

Three traps this module exists to handle, called out where they bite:
  * tokens-vs-characters — RecursiveCharacterTextSplitter measures *characters*
    by default; we inject a token length function so ``chunk_size=600`` means 600
    *tokens* as the SPEC requires.
  * metadata inheritance — every Chunk inherits its page's ChunkMetadata; a Chunk
    without provenance can never be cited.
  * deterministic ids — each Chunk gets a stable id derived from
    (document_id, page, index) so re-ingestion upserts instead of duplicating
    (AC1, idempotency).

Scope boundary: this driver stops at producing Chunks + their deterministic ids.
It does **not** embed or persist — the upsert into the VectorStore is module 4
(``core/store.py``), wired by ``core/engine.py``. There is no vertical branching
here; everything that differs between legal/health arrives via ``VerticalConfig``.
"""

from __future__ import annotations

import argparse
import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from core.embed import Embedder
from core.models import (
    Chunk,
    ChunkMetadata,
    EmptyCorpusError,
    RagEngineError,
    SourceDocument,
    Vertical,
    VerticalConfig,
)
from core.store import VectorStore, flatten_metadata

# Importing the Embedder *port* and the VectorStore here is safe: neither imports
# ingest.py, so there is no cycle. Crucially, persist() depends on these
# abstractions and receives them *injected* — the driver never builds a concrete
# adapter inside its logic. The one concrete adapter (OllamaEmbedder) is reached for
# only in main(), the offline composition root (see bottom of file).

# --- document_id derivation --------------------------------------------------
# Official-id pattern (e.g. BOE-A-2015-11430). This is generic provenance logic,
# not vertical branching: it fires on any filename that *carries* such an id,
# regardless of the Vertical, and falls back to a slug otherwise.
_OFFICIAL_ID_RE = re.compile(r"[A-Z]{2,}-[A-Z]-\d{4}-\d+")


def derive_document_id(path: Path) -> str:
    """The single source of truth for a SourceDocument's stable id.

    Prefer an official id embedded in the filename (used verbatim in Citations);
    otherwise slugify the filename stem. Centralized so ingest and any later
    lookup agree on the same id for the same file.
    """
    match = _OFFICIAL_ID_RE.search(path.stem)
    if match:
        return match.group(0)
    return _slugify(path.stem)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug or "document"


def make_chunk_id(document_id: str, page: int, index: int) -> str:
    """Deterministic id for a Chunk: stable hash of (document_id, page, index).

    The same (document, page, position) always maps to the same id, so a second
    ingestion upserts onto the same VectorStore row instead of creating a
    duplicate. This id is the *mechanism* behind AC1 idempotency; the upsert
    itself lives in module 4.
    """
    raw = f"{document_id}|{page}|{index}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


# --- token-length measurement ------------------------------------------------
# Lazily-initialized encoding shared across Chunkers. We measure length in tokens
# (not characters) so the SPEC's chunk_size/overlap mean what they say.
_ENCODING = None


def _token_length(text: str) -> int:
    global _ENCODING
    if _ENCODING is None:
        try:
            import tiktoken
        except ImportError as exc:  # fail loud, with the fix
            raise RagEngineError(
                "tiktoken is required to measure chunk length in tokens. "
                "Install it with `pip install -r requirements.txt`."
            ) from exc
        # cl100k_base is a general-purpose BPE used as a tokenizer-agnostic proxy
        # for length; we only need a token COUNT, not BGE-M3's exact tokenization.
        _ENCODING = tiktoken.get_encoding("cl100k_base")
    return len(_ENCODING.encode(text))


@dataclass(frozen=True)
class LoadedPage:
    """One page of a SourceDocument: its text plus page-level ChunkMetadata.

    The metadata here is the provenance every Chunk split from this page will
    inherit (``section`` is left unset — page granularity is the floor for now).
    """

    text: str
    metadata: ChunkMetadata


class DocumentLoader:
    """Reads a SourceDocument from disk into per-page text + ChunkMetadata (FR2).

    Uses ``pymupdf4llm.to_markdown(..., page_chunks=True)`` and preserves page
    numbers. Page numbers come from 1-based enumeration over the returned pages
    (which arrive in document order); we do not trust a possibly 0-based
    ``metadata['page']`` field, so the cited page always matches the human page.
    """

    def load(self, source: SourceDocument) -> list[LoadedPage]:
        raw_pages = self._read_pages(source.source_path)

        pages: list[LoadedPage] = []
        for page_number, raw in enumerate(raw_pages, start=1):
            text = raw.get("text", "") if isinstance(raw, dict) else str(raw)
            if not text.strip():
                continue  # nothing to embed on a blank page; skip cleanly
            metadata = ChunkMetadata(
                document_id=source.document_id,
                page=page_number,
                vertical=source.vertical,
                source_path=source.source_path,
            )
            pages.append(LoadedPage(text=text, metadata=metadata))
        return pages

    def _read_pages(self, source_path: Path) -> list[dict]:
        try:
            import pymupdf4llm
        except ImportError as exc:
            raise RagEngineError(
                "pymupdf4llm is required to load PDFs. "
                "Install it with `pip install -r requirements.txt`."
            ) from exc

        # A missing single file is not an empty Corpus — different semantics, so
        # the base RagEngineError, not EmptyCorpusError.
        if not source_path.exists():
            raise RagEngineError(
                f"SourceDocument not found at '{source_path}'. "
                "Check the file exists under data/<vertical>/ and is readable."
            )
        return pymupdf4llm.to_markdown(str(source_path), page_chunks=True)


class Chunker:
    """Splits a LoadedPage into Chunks, propagating full ChunkMetadata (FR3).

    chunk_size/chunk_overlap come from VerticalConfig (defaults 600/90); they are
    never hardcoded here. The injected ``length_function`` is the crux: without
    it the splitter counts characters, so ``chunk_size=600`` would slice ~150
    tokens — wrong granularity that quietly degrades retrieval. With a token
    length function, 600 means 600 tokens as the SPEC intends.
    """

    def __init__(
        self,
        chunk_size: int,
        chunk_overlap: int,
        length_function: Callable[[str], int] | None = None,
    ) -> None:
        self._splitter = self._build_splitter(
            chunk_size, chunk_overlap, length_function or _token_length
        )

    def split(self, page: LoadedPage) -> list[Chunk]:
        pieces = self._splitter.split_text(page.text)
        # Every Chunk inherits the page's provenance — never a Chunk without
        # metadata, so the path back to a Citation can never be broken.
        return [Chunk(text=piece, metadata=page.metadata) for piece in pieces]

    @staticmethod
    def _build_splitter(chunk_size: int, chunk_overlap: int, length_function: Callable[[str], int]):
        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter
        except ImportError as exc:
            raise RagEngineError(
                "langchain-text-splitters is required for chunking. "
                "Install it with `pip install -r requirements.txt`."
            ) from exc
        return RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=length_function,  # measure in tokens, not characters
        )


# --- ingestion driver --------------------------------------------------------


@dataclass(frozen=True)
class IngestedChunk:
    """A Chunk paired with its deterministic id — the unit handed to the
    VectorStore (module 4) for an idempotent upsert."""

    chunk_id: str
    chunk: Chunk


@dataclass(frozen=True)
class IngestionResult:
    """Outcome of an ingestion run: counts plus the ids+Chunks to persist.

    This is the clean boundary to module 4: ``engine.py`` takes ``chunks`` and
    upserts (chunk_id → Chunk + Embedding) into the VectorStore. The driver does
    not persist anything itself.
    """

    documents: int
    chunks: list[IngestedChunk]

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)


def discover_corpus(config: VerticalConfig) -> list[SourceDocument]:
    """List the Corpus's SourceDocuments, failing fast on an empty/missing one."""
    root = Path(config.corpus_path)
    if not root.exists():
        raise EmptyCorpusError(
            f"Corpus path '{config.corpus_path}' does not exist for vertical "
            f"'{config.vertical.value}'. Create it and add PDFs under "
            f"data/{config.vertical.value}/."
        )

    # Case-insensitive match (".pdf"/".PDF"); glob() is case-sensitive on Linux.
    pdfs = sorted(p for p in root.iterdir() if p.suffix.lower() == ".pdf")
    if not pdfs:
        raise EmptyCorpusError(
            f"No PDFs found in '{config.corpus_path}' for vertical "
            f"'{config.vertical.value}'. Add SourceDocuments before ingesting."
        )

    return [
        SourceDocument(
            document_id=derive_document_id(pdf),
            source_path=pdf,  # keep the Path; the domain holds rich types
            vertical=config.vertical,
        )
        for pdf in pdfs
    ]


def ingest(
    config: VerticalConfig,
    *,
    loader: DocumentLoader | None = None,
    chunker: Chunker | None = None,
) -> IngestionResult:
    """Drive ingestion for one Vertical, returning Chunks + deterministic ids.

    Takes a VerticalConfig (the real Embedder/VectorStore wiring is engine.py's
    job); ``loader``/``chunker`` are injectable for testing. Reads chunk sizing
    from config so nothing vertical-specific leaks into this code.
    """
    loader = loader or DocumentLoader()
    chunker = chunker or Chunker(config.chunk_size, config.chunk_overlap)

    sources = discover_corpus(config)
    ingested: list[IngestedChunk] = []
    for source in sources:
        ingested.extend(_ingest_source(source, loader, chunker))

    return IngestionResult(documents=len(sources), chunks=ingested)


def _ingest_source(
    source: SourceDocument, loader: DocumentLoader, chunker: Chunker
) -> list[IngestedChunk]:
    out: list[IngestedChunk] = []
    for page in loader.load(source):
        # index is the chunk's position WITHIN the page — the third component of
        # the deterministic id, so re-runs map each Chunk to the same row.
        for index, chunk in enumerate(chunker.split(page)):
            chunk_id = make_chunk_id(chunk.metadata.document_id, chunk.metadata.page, index)
            out.append(IngestedChunk(chunk_id=chunk_id, chunk=chunk))
    return out


# --- persistence: embed -> upsert (FR4, FR5 → AC1) ---------------------------


def persist(result: IngestionResult, embedder: Embedder, store: VectorStore) -> int:
    """Embed the ingested Chunks and upsert them into the VectorStore. Returns the
    number of vectors written.

    This is the loop that was promised by ``ingest()``'s scope note: it completes
    the offline pipeline. ``embedder`` and ``store`` are **injected** on purpose —
    the ingestion *driver* orchestrates its own pipeline, but it must not couple to
    concrete adapters (golden rule 1); the composition root (``main()``) supplies
    them. Keeping this here, not on ``RagEngine``, also keeps the online query
    engine ignorant of vector writes: ingest (offline/batch) and query
    (online/cached) are different lifecycles.

    Idempotency (AC1) rides on the deterministic ``chunk_id``s: ``store.upsert``
    overwrites same-id rows instead of duplicating, so re-running this is safe.
    The embedding here uses the *same* Embedder the query path uses (built from the
    same ``VerticalConfig.embedding_model``), so ingest and query can never embed
    with different models and silently break retrieval (golden rule 4).
    """
    if not result.chunks:
        return 0  # nothing produced (caller already guards the empty-Corpus case)

    # Parallel lists, positionally paired — the contract store.upsert expects.
    ids = [item.chunk_id for item in result.chunks]
    texts = [item.chunk.text for item in result.chunks]
    # Reuse the store's single flattening site (Path->str, Vertical->value, drop
    # None); never re-implement that boundary here.
    metadatas = [flatten_metadata(item.chunk.metadata) for item in result.chunks]

    # Embed in one batch, then upsert. embed_documents preserves input order, so the
    # vectors line up with ids/texts/metadatas by position.
    embeddings = embedder.embed_documents(texts)
    store.upsert(ids, texts, embeddings, metadatas)
    return len(ids)


# --- minimal config boundary + CLI -------------------------------------------
# TODO(module 9 / config): a dedicated config loader will own YAML parsing and
# validation. The helper below is the minimal boundary the ingest CLI needs
# today and must not grow into that module.
_DEFAULT_EMBEDDING_MODEL = "bge-m3"
_DEFAULT_LLM_MODEL = "qwen2.5:7b"


def load_vertical_config(vertical: Vertical) -> VerticalConfig:
    """Read config/<vertical>.yaml into a VerticalConfig — the ONE config reader.

    Public on purpose: the engine (``from_vertical``) and the presentation layer
    both resolve config through this single seam, so ingest and query can never
    read different model names (rule 4). Module 9 may still move it to a
    dedicated config module; callers won't change.
    """
    try:
        import yaml
    except ImportError as exc:
        raise RagEngineError(
            "pyyaml is required to read VerticalConfig. "
            "Install it with `pip install -r requirements.txt`."
        ) from exc

    config_path = Path("config") / f"{vertical.value}.yaml"
    if not config_path.exists():
        raise RagEngineError(
            f"VerticalConfig not found at '{config_path}'. Expected config/{vertical.value}.yaml."
        )

    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    # embedding_model/llm_model belong IN the YAML (rule 4: one source of truth so
    # ingest and query can never read different model names). Until module 9 adds
    # them there, fall back to the documented defaults — kept in this one place.
    data.setdefault("embedding_model", _DEFAULT_EMBEDDING_MODEL)
    data.setdefault("llm_model", _DEFAULT_LLM_MODEL)
    return VerticalConfig(**data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m core.ingest",
        description="Ingest a Vertical's Corpus into Chunks (offline, idempotent).",
    )
    parser.add_argument(
        "--vertical",
        required=True,
        choices=[v.value for v in Vertical],
        help="Which Vertical's Corpus to ingest (data/<vertical>/).",
    )
    args = parser.parse_args(argv)

    config = load_vertical_config(Vertical(args.vertical))
    result = ingest(config)

    # main() is the composition root for the OFFLINE pipeline: it builds the concrete
    # adapters and injects them into persist(), the symmetric counterpart of
    # engine.from_vertical_config for the ONLINE query path. OllamaEmbedder is
    # imported locally so adapter instantiation stays at this entry point, never in
    # the driver's reusable logic.
    from core.embed import OllamaEmbedder

    embedder = OllamaEmbedder(
        model_name=config.embedding_model,
        ollama_base_url=config.ollama_base_url,
    )
    # Fail fast BEFORE embedding (NFR6/AC7): Ollama unreachable or the embedding
    # model not pulled surfaces now with an actionable message, not halfway through
    # the batch with a corrupt, partially-written Collection.
    embedder.check_health()

    store = VectorStore(collection_name=config.collection_name)
    written = persist(result, embedder, store)

    print(
        f"Ingested vertical '{config.vertical.value}': "
        f"{result.documents} SourceDocuments -> {result.chunk_count} Chunks -> "
        f"{written} vectors persisted in Collection '{config.collection_name}'."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
