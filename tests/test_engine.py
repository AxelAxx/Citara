"""Unit tests for the RagEngine composition root (module 7, G1, FR10 → AC4).

No live Ollama or Chroma: the use case is exercised with injected fake
Retriever/Generator, and the wiring path is exercised with real adapters (which
build their clients lazily, so construction stays offline). The tests assert the
orchestration contract — top_k from config flows to retrieval, the Generator's
Answer is returned verbatim, a str Query is wrapped, health delegates to the
sub-preflights — and AC4: two different VerticalConfigs wire differently with no
vertical branching.
"""

from __future__ import annotations

import pytest

from core.engine import RagEngine
from core.models import Answer, Chunk, ChunkMetadata, Query, Vertical, VerticalConfig


class _FakeRetriever:
    def __init__(self, context) -> None:
        self.calls: list[dict] = []
        self._context = context

    def retrieve(self, query, top_k, where=None):
        self.calls.append({"query": query, "top_k": top_k, "where": where})
        return self._context


class _FakeGenerator:
    def __init__(self, answer: Answer) -> None:
        self.calls: list[dict] = []
        self._answer = answer
        self.health_checked = False

    def generate(self, query, context) -> Answer:
        self.calls.append({"query": query, "context": context})
        return self._answer

    def check_health(self) -> None:
        self.health_checked = True


class _FakeEmbedder:
    def __init__(self) -> None:
        self.health_checked = False

    def check_health(self) -> None:
        self.health_checked = True


def _answer_with_citation() -> Answer:
    from core.models import Citation

    return Answer(
        text="El plazo es de un mes.",
        citations=[Citation(document_id="doc", page=1)],
    )


def _config(vertical: Vertical, collection_name: str, system_prompt: str, top_k: int = 5) -> VerticalConfig:
    return VerticalConfig(
        vertical=vertical,
        display_name=f"{vertical.value} demo",
        corpus_path=f"data/{vertical.value}",
        collection_name=collection_name,
        system_prompt=system_prompt,
        embedding_model="bge-m3",
        llm_model="qwen2.5:7b",
        top_k=top_k,
    )


# --- orchestration: top_k from config, Answer passthrough --------------------


def test_answer_retrieves_with_config_top_k_and_returns_generator_answer():
    context = [Chunk(text="t", metadata=ChunkMetadata(document_id="doc", page=1))]
    retriever = _FakeRetriever(context)
    expected = _answer_with_citation()
    generator = _FakeGenerator(expected)
    engine = RagEngine(retriever=retriever, generator=generator, top_k=7)

    result = engine.answer(Query(text="¿plazo?"))

    # top_k flows from construction (config.top_k) into retrieval.
    assert retriever.calls[0]["top_k"] == 7
    # the context retrieved is exactly what the generator was handed.
    assert generator.calls[0]["context"] is context
    # the Generator's Answer is returned verbatim — engine adds nothing.
    assert result is expected


def test_where_is_forwarded_to_retrieval():
    retriever = _FakeRetriever([Chunk(text="t", metadata=ChunkMetadata(document_id="d", page=1))])
    engine = RagEngine(retriever=retriever, generator=_FakeGenerator(_answer_with_citation()), top_k=5)

    where = {"document_id": "doc"}
    engine.answer("¿algo?", where=where)

    assert retriever.calls[0]["where"] == where


# --- ergonomics: str is wrapped in Query -------------------------------------


def test_str_query_is_wrapped_in_query():
    retriever = _FakeRetriever([Chunk(text="t", metadata=ChunkMetadata(document_id="d", page=1))])
    generator = _FakeGenerator(_answer_with_citation())
    engine = RagEngine(retriever=retriever, generator=generator, top_k=5)

    engine.answer("texto plano")

    assert isinstance(retriever.calls[0]["query"], Query)
    assert retriever.calls[0]["query"].text == "texto plano"
    # the same wrapped Query reaches the generator.
    assert isinstance(generator.calls[0]["query"], Query)


# --- health delegation (NFR6/AC7) --------------------------------------------


def test_check_health_delegates_to_embedder_and_generator():
    embedder = _FakeEmbedder()
    generator = _FakeGenerator(_answer_with_citation())
    engine = RagEngine(
        retriever=_FakeRetriever([]),
        generator=generator,
        top_k=5,
        embedder=embedder,
    )

    engine.check_health()

    assert embedder.health_checked is True
    assert generator.health_checked is True


def test_check_health_without_embedder_still_checks_generator():
    generator = _FakeGenerator(_answer_with_citation())
    engine = RagEngine(retriever=_FakeRetriever([]), generator=generator, top_k=5)

    engine.check_health()  # no embedder injected; must not raise

    assert generator.health_checked is True


# --- AC4: two configs wire differently, with NO vertical branching ------------


def test_from_vertical_config_wires_collection_name_per_vertical():
    health = RagEngine.from_vertical_config(
        _config(Vertical.HEALTH, "health_chunks", "Eres un asistente clínico.")
    )
    legal = RagEngine.from_vertical_config(
        _config(Vertical.LEGAL, "legal_chunks", "Eres un asistente legal.")
    )

    # Same code path, different config → different wiring. The collection_name flows
    # straight from each config into its VectorStore with no branch on the Vertical.
    assert health._retriever._vector_store.collection_name == "health_chunks"
    assert legal._retriever._vector_store.collection_name == "legal_chunks"

    # The vertical's system_prompt likewise reaches its Generator unchanged.
    assert health._generator.system_prompt == "Eres un asistente clínico."
    assert legal._generator.system_prompt == "Eres un asistente legal."

    # Same embedding model centralized in config feeds both engines' Embedders.
    assert health._retriever._embedder.model_name == "bge-m3"
    assert legal._retriever._embedder.model_name == "bge-m3"


def test_from_vertical_config_propagates_top_k():
    engine = RagEngine.from_vertical_config(
        _config(Vertical.LEGAL, "legal_chunks", "prompt", top_k=3)
    )
    retriever = _FakeRetriever([Chunk(text="t", metadata=ChunkMetadata(document_id="d", page=1))])
    # Rebuild a tiny engine sharing the same top_k to confirm it was captured.
    assert engine._top_k == 3
