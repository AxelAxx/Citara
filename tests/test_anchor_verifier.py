"""Unit tests for the AnchorVerifier (verify_anchors — bug C fix, FR9).

No live Ollama: the Embedder is a stub with FIXED synthetic vectors, so each
test pins the geometry and asserts one branch of the contract (repair / keep /
floor) independently of any real model. Chunk embeddings are set directly on
the Chunks, exactly as retrieval populates them.
"""

from __future__ import annotations

from core.embed import Embedder
from core.generate import Generator, verify_anchors
from core.models import Chunk, ChunkMetadata, CiteAnchor, Embedding

# The calibrated defaults under test (config values in production).
_MARGIN = 0.06
_FLOOR = 0.50


class _StubEmbedder(Embedder):
    """Deterministic text → vector map; unknown text fails the test loudly."""

    def __init__(self, vectors: dict[str, Embedding]) -> None:
        self._vectors = vectors

    def embed_documents(self, texts: list[str]) -> list[Embedding]:
        return [self._vectors[text] for text in texts]

    def embed_query(self, text: str) -> Embedding:
        return self._vectors[text]


def _chunk(document_id: str, page: int, embedding: Embedding | None) -> Chunk:
    return Chunk(
        text=f"{document_id} p{page}",
        metadata=ChunkMetadata(document_id=document_id, page=page),
        embedding=embedding,
    )


def _remap(context: list[Chunk]) -> list[int]:
    """The REAL dedup remap — the verifier must group by the same key."""
    citations = Generator._citations_from_context(context)
    return Generator._fragment_index_to_citation_index(context, citations)


def test_repair_remaps_to_the_argmax_citation() -> None:
    # Anchored citation scores near zero; another citation clearly supports
    # the sentence (margin >> delta) -> the anchor is repaired to the argmax.
    context = [_chunk("docA", 1, [1.0, 0.0]), _chunk("docB", 2, [0.0, 1.0])]
    embedder = _StubEmbedder({"La frase.": [0.1, 0.9]})

    verified = verify_anchors(
        [CiteAnchor(sentence_index=1, chunk_index=1)],
        context,
        ["La frase. "],
        embedder,
        _remap(context),
        repair_margin=_MARGIN,
        support_floor=_FLOOR,
    )

    assert verified == [CiteAnchor(sentence_index=1, chunk_index=2)]


def test_keep_on_small_margin_no_churn() -> None:
    # Two citations within delta of each other (adjacent-page ambiguity):
    # the model's anchor stands even though it is not the strict argmax.
    context = [_chunk("docA", 1, [1.0, 0.0]), _chunk("docA", 2, [0.999, 0.0447])]
    embedder = _StubEmbedder({"La frase.": [1.0, 0.0]})

    verified = verify_anchors(
        [CiteAnchor(sentence_index=1, chunk_index=2)],
        context,
        ["La frase. "],
        embedder,
        _remap(context),
        repair_margin=_MARGIN,
        support_floor=_FLOOR,
    )

    assert verified == [CiteAnchor(sentence_index=1, chunk_index=2)]


def test_keep_when_anchored_below_floor_but_max_is_supported() -> None:
    # The reviewed precedence bug: anchored citation at ~0.49 (below floor),
    # context max at ~0.52 (above floor), margin 0.03 < delta. The floor is
    # evaluated ONCE, on the max: a supported best target within delta means
    # legitimate ambiguity -> KEEP, never a residual discard.
    context = [_chunk("docA", 1, [0.52, 0.854]), _chunk("docB", 2, [0.49, 0.8717])]
    embedder = _StubEmbedder({"La frase.": [1.0, 0.0]})

    verified = verify_anchors(
        [CiteAnchor(sentence_index=1, chunk_index=2)],
        context,
        ["La frase. "],
        embedder,
        _remap(context),
        repair_margin=_MARGIN,
        support_floor=_FLOOR,
    )

    assert verified == [CiteAnchor(sentence_index=1, chunk_index=2)]


def test_floor_discards_unsupported_anchor() -> None:
    # Even the BEST citation scores below the floor: nothing the model saw
    # supports the sentence -> the anchor is discarded (prose keeps, chip goes).
    context = [_chunk("docA", 1, [1.0, 0.0]), _chunk("docB", 2, [0.0, 1.0])]
    embedder = _StubEmbedder({"La frase.": [-1.0, 0.2]})

    verified = verify_anchors(
        [CiteAnchor(sentence_index=1, chunk_index=1)],
        context,
        ["La frase. "],
        embedder,
        _remap(context),
        repair_margin=_MARGIN,
        support_floor=_FLOOR,
    )

    assert verified == []


def test_same_page_sibling_never_triggers_repair() -> None:
    # Two chunks of the SAME (doc, page) dedup to one citation. The anchored
    # chunk scores low but its same-page sibling is the global max: at
    # citation level the anchor is already optimal -> kept as-is (the measured
    # FLAG* false-positive class of the chunk-level proxy).
    context = [
        _chunk("docA", 1, [1.0, 0.0]),
        _chunk("docA", 1, [0.0, 1.0]),
        _chunk("docB", 2, [0.7, 0.7]),
    ]
    embedder = _StubEmbedder({"La frase.": [0.0, 1.0]})

    verified = verify_anchors(
        [CiteAnchor(sentence_index=1, chunk_index=1)],
        context,
        ["La frase. "],
        embedder,
        _remap(context),
        repair_margin=_MARGIN,
        support_floor=_FLOOR,
    )

    assert verified == [CiteAnchor(sentence_index=1, chunk_index=1)]


def test_no_embedder_keeps_anchors_unchanged() -> None:
    # Verification is ADDITIVE: an engine without the embedder wired (plain
    # constructor, tests) must behave exactly as before the verifier existed.
    context = [_chunk("docA", 1, [1.0, 0.0]), _chunk("docB", 2, [0.0, 1.0])]
    anchors = [CiteAnchor(sentence_index=1, chunk_index=1)]

    verified = verify_anchors(
        anchors,
        context,
        ["La frase. "],
        None,
        _remap(context),
        repair_margin=_MARGIN,
        support_floor=_FLOOR,
    )

    assert verified == anchors


def test_missing_chunk_embedding_keeps_anchors_unchanged() -> None:
    # All-or-nothing: with any stored vector missing, scoring the rest could
    # repair toward whatever happens to carry one — degrade to no verification.
    context = [_chunk("docA", 1, [1.0, 0.0]), _chunk("docB", 2, None)]
    anchors = [CiteAnchor(sentence_index=1, chunk_index=1)]
    embedder = _StubEmbedder({"La frase.": [0.0, 1.0]})

    verified = verify_anchors(
        anchors,
        context,
        ["La frase. "],
        embedder,
        _remap(context),
        repair_margin=_MARGIN,
        support_floor=_FLOOR,
    )

    assert verified == anchors
