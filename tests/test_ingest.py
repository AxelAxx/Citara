"""Unit tests for the ingestion module (FR1–FR3, AC1, AC6).

No heavy/live dependencies: the token-counting tiktoken path is avoided by
injecting a trivial word-count ``length_function`` into the Chunker, and the
pymupdf4llm PDF path is exercised against a fake module placed in sys.modules.
Both are lazy-imported in core.ingest, so importing this test file pulls neither.
"""

from __future__ import annotations

import sys
import types

import pytest

from core.ingest import (
    Chunker,
    DocumentLoader,
    IngestedChunk,
    LoadedPage,
    derive_document_id,
    discover_corpus,
    ingest,
    make_chunk_id,
)
from core.models import (
    ChunkMetadata,
    EmptyCorpusError,
    SourceDocument,
    Vertical,
    VerticalConfig,
)


def _word_len(text: str) -> int:
    """Trivial token proxy: count words. Keeps tests off tiktoken."""
    return len(text.split())


def _make_config(tmp_path, vertical: Vertical = Vertical.HEALTH) -> VerticalConfig:
    return VerticalConfig(
        vertical=vertical,
        display_name="x",
        corpus_path=str(tmp_path),
        collection_name="c",
        system_prompt="p",
        embedding_model="bge-m3",
        llm_model="qwen2.5:7b",
    )


# --- Chunker -----------------------------------------------------------------


def test_chunker_respects_size_overlap_and_inherits_metadata():
    meta = ChunkMetadata(
        document_id="doc-1",
        page=7,
        vertical=Vertical.HEALTH,
        source_path="data/health/doc-1.pdf",
    )
    page = LoadedPage(text=" ".join(f"w{i}" for i in range(30)), metadata=meta)

    chunker = Chunker(chunk_size=10, chunk_overlap=3, length_function=_word_len)
    chunks = chunker.split(page)

    assert len(chunks) >= 2  # 30 words can't fit one 10-token chunk
    # chunk_size is measured with the injected length_function (words), not chars.
    assert all(_word_len(c.text) <= 10 for c in chunks)
    # Every Chunk inherits its page's provenance — the citeability invariant.
    assert all(c.metadata == meta for c in chunks)
    # Non-zero overlap: adjacent chunks share at least one token.
    assert set(chunks[0].text.split()) & set(chunks[1].text.split())


# --- make_chunk_id -----------------------------------------------------------


def test_make_chunk_id_is_deterministic_and_position_sensitive():
    base = make_chunk_id("doc-1", 1, 0)
    assert base == make_chunk_id("doc-1", 1, 0)  # stable across calls
    assert base != make_chunk_id("doc-2", 1, 0)  # document_id matters
    assert base != make_chunk_id("doc-1", 2, 0)  # page matters
    assert base != make_chunk_id("doc-1", 1, 1)  # index matters


# --- ingest() end-to-end with a stub Loader ---------------------------------


class _StubLoader:
    """Returns one fixed LoadedPage per SourceDocument — no PDF, no pymupdf4llm.

    Mirrors the real Loader contract: page metadata carries the source's id and
    Vertical, so the deterministic chunk ids are predictable from the filename.
    """

    def load(self, source: SourceDocument) -> list[LoadedPage]:
        meta = ChunkMetadata(
            document_id=source.document_id,
            page=1,
            vertical=source.vertical,
            source_path=source.source_path,
        )
        return [LoadedPage(text="uno dos tres", metadata=meta)]


def test_ingest_end_to_end_produces_deterministic_ids_and_counts(tmp_path):
    (tmp_path / "alpha.pdf").write_bytes(b"%PDF dummy")
    (tmp_path / "beta.pdf").write_bytes(b"%PDF dummy")
    config = _make_config(tmp_path)

    # chunk_size large enough that the 3-word page yields exactly one Chunk,
    # making the expected ids exact.
    chunker = Chunker(chunk_size=50, chunk_overlap=0, length_function=_word_len)
    result = ingest(config, loader=_StubLoader(), chunker=chunker)

    assert result.documents == 2
    assert result.chunk_count == 2
    assert all(isinstance(ic, IngestedChunk) for ic in result.chunks)

    ids = {ic.chunk_id for ic in result.chunks}
    assert ids == {make_chunk_id("alpha", 1, 0), make_chunk_id("beta", 1, 0)}

    # Idempotency at the id level (AC1): re-ingesting yields the same ids.
    rerun = ingest(config, loader=_StubLoader(), chunker=chunker)
    assert {ic.chunk_id for ic in rerun.chunks} == ids


# --- discover_corpus ---------------------------------------------------------


def test_discover_corpus_empty_dir_raises(tmp_path):
    config = _make_config(tmp_path)
    with pytest.raises(EmptyCorpusError):
        discover_corpus(config)


def test_discover_corpus_builds_source_documents(tmp_path):
    (tmp_path / "doc.pdf").write_bytes(b"%PDF dummy")
    (tmp_path / "UPPER.PDF").write_bytes(b"%PDF dummy")  # case-insensitive match
    config = _make_config(tmp_path, vertical=Vertical.LEGAL)

    sources = discover_corpus(config)

    assert len(sources) == 2
    assert all(s.vertical is Vertical.LEGAL for s in sources)
    by_id = {s.document_id: s for s in sources}
    assert set(by_id) == {"doc", "upper"}
    assert by_id["doc"].source_path == tmp_path / "doc.pdf"


# --- DocumentLoader real path, with pymupdf4llm faked -----------------------


def test_document_loader_reads_pages_and_preserves_page_numbers(monkeypatch, tmp_path):
    pdf = tmp_path / "BOE-A-2015-11430.pdf"
    pdf.write_bytes(b"%PDF-1.4 dummy")

    # Fake pymupdf4llm.to_markdown(page_chunks=True): blank page must be skipped
    # while page numbering stays 1-based over ALL returned pages (FR2).
    fake = types.SimpleNamespace(
        to_markdown=lambda path, page_chunks: [
            {"text": "primera pagina"},
            {"text": "   "},
            {"text": "tercera pagina"},
        ]
    )
    monkeypatch.setitem(sys.modules, "pymupdf4llm", fake)

    source = SourceDocument(
        document_id="BOE-A-2015-11430", source_path=pdf, vertical=Vertical.LEGAL
    )
    pages = DocumentLoader().load(source)

    assert [p.metadata.page for p in pages] == [1, 3]  # blank page 2 skipped
    assert pages[0].text == "primera pagina"
    assert all(p.metadata.document_id == "BOE-A-2015-11430" for p in pages)
    assert all(p.metadata.vertical is Vertical.LEGAL for p in pages)
    assert all(p.metadata.source_path == pdf for p in pages)


def test_derive_document_id_official_vs_slug(tmp_path):
    from pathlib import Path

    assert derive_document_id(Path("BOE-A-2015-11430.pdf")) == "BOE-A-2015-11430"
    assert derive_document_id(Path("Guia Clinica 2021.pdf")) == "guia-clinica-2021"
