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

from core.engine import RagEngine, StreamedAnswer
from core.generate import _ABSTENTION_TEXT
from core.models import Answer, Chunk, ChunkMetadata, Citation, Query, Vertical, VerticalConfig


class _FakeRetriever:
    def __init__(self, context) -> None:
        self.calls: list[dict] = []
        self._context = context

    def retrieve(self, query, top_k, where=None):
        self.calls.append({"query": query, "top_k": top_k, "where": where})
        return self._context


class _FakeGenerator:
    def __init__(self, answer: Answer, *, fragments=None, citations=None) -> None:
        self.calls: list[dict] = []
        self.stream_calls: list[dict] = []
        self._answer = answer
        self._fragments = list(fragments) if fragments is not None else []
        self._citations = list(citations) if citations is not None else []
        self.health_checked = False

    def generate(self, query, context) -> Answer:
        self.calls.append({"query": query, "context": context})
        return self._answer

    def generate_stream(self, query, context):
        # Mirror the real Generator contract: empty context abstains (yields the
        # abstention sentence whole, no LLM call); otherwise yield the fragments.
        self.stream_calls.append({"query": query, "context": context})
        if not context:
            yield _ABSTENTION_TEXT
            return
        yield from self._fragments

    def citations_for_context(self, context):
        # Citations derive from context: none when there is nothing to ground on.
        return list(self._citations) if context else []

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


# --- FR7/FR11: answer_stream orchestrates streaming (text + citations) --------


def test_answer_stream_returns_text_stream_and_citations():
    context = [Chunk(text="t", metadata=ChunkMetadata(document_id="doc", page=1))]
    retriever = _FakeRetriever(context)
    citations = [Citation(document_id="doc", page=1)]
    generator = _FakeGenerator(
        _answer_with_citation(),
        fragments=["El plazo ", "es de ", "un mes."],
        citations=citations,
    )
    engine = RagEngine(retriever=retriever, generator=generator, top_k=6)

    streamed = engine.answer_stream(Query(text="¿plazo?"))

    assert isinstance(streamed, StreamedAnswer)
    # top_k from config flows into retrieval, exactly like answer().
    assert retriever.calls[0]["top_k"] == 6
    # The text generator yields the generator's fragments, in order.
    assert list(streamed.text_stream) == ["El plazo ", "es de ", "un mes."]
    # Citations pass through from citations_for_context(context).
    assert streamed.citations == citations
    # The retrieved context is exactly what the generator streamed from.
    assert generator.stream_calls[0]["context"] is context


def test_answer_stream_wraps_str_query():
    context = [Chunk(text="t", metadata=ChunkMetadata(document_id="d", page=1))]
    retriever = _FakeRetriever(context)
    generator = _FakeGenerator(
        _answer_with_citation(),
        fragments=["hola"],
        citations=[Citation(document_id="d", page=1)],
    )
    engine = RagEngine(retriever=retriever, generator=generator, top_k=5)

    streamed = engine.answer_stream("texto plano")
    list(streamed.text_stream)  # generate_stream is lazy; consume it to record the call

    assert isinstance(retriever.calls[0]["query"], Query)
    assert retriever.calls[0]["query"].text == "texto plano"
    # the same wrapped Query reaches the generator's stream.
    assert isinstance(generator.stream_calls[0]["query"], Query)
    assert generator.stream_calls[0]["query"].text == "texto plano"


def test_answer_stream_empty_context_abstains_with_no_citations():
    retriever = _FakeRetriever([])  # nothing retrieved
    generator = _FakeGenerator(
        _answer_with_citation(),
        fragments=["no debería usarse"],
        citations=[Citation(document_id="x", page=1)],
    )
    engine = RagEngine(retriever=retriever, generator=generator, top_k=5)

    streamed = engine.answer_stream("¿algo?")

    # Coherent with answer(): empty context ⇒ abstention text streamed, no citations,
    # and no LLM fragments used.
    assert list(streamed.text_stream) == [_ABSTENTION_TEXT]
    assert streamed.citations == []


# --- corpus_stats façade (FR-#06): delegates, never counts ---------------------


def test_corpus_stats_requires_wired_store_and_embedder():
    from core.models import RagEngineError

    engine = RagEngine(
        retriever=_FakeRetriever([]),
        generator=_FakeGenerator(_answer_with_citation()),
        top_k=5,
        # plain test constructor: no VectorStore, no Embedder
    )

    # Fail fast with the actionable wiring hint — never invent stats.
    with pytest.raises(RagEngineError) as exc:
        engine.corpus_stats()
    assert "from_vertical_config" in str(exc.value)


def test_corpus_stats_delegates_with_the_configured_embedding_model():
    from core.models import CorpusStats

    class _FakeStore:
        def __init__(self):
            self.calls: list[str] = []

        def corpus_stats(self, embedding_model: str) -> CorpusStats:
            self.calls.append(embedding_model)
            return CorpusStats(
                document_count=0, chunk_count=0,
                embedding_model=embedding_model, document_ids=[],
            )

    class _NamedEmbedder(_FakeEmbedder):
        model_name = "bge-m3"

    store = _FakeStore()
    engine = RagEngine(
        retriever=_FakeRetriever([]),
        generator=_FakeGenerator(_answer_with_citation()),
        top_k=5,
        embedder=_NamedEmbedder(),
        vector_store=store,
    )

    stats = engine.corpus_stats()

    # Golden rule 4: the model name flows from the ONE Embedder source.
    assert store.calls == ["bge-m3"]
    assert stats.embedding_model == "bge-m3"


def test_corpus_stats_for_builds_only_the_vector_store(monkeypatch):
    """The light façade: only a VectorStore, config-sourced model, no Generator."""
    from core import engine as engine_module
    from core.models import CorpusStats

    built: dict = {}

    class _RecordingStore:
        def __init__(self, collection_name: str) -> None:
            built["collection_name"] = collection_name

        def corpus_stats(self, embedding_model: str) -> CorpusStats:
            built["embedding_model"] = embedding_model
            return CorpusStats(
                document_count=0, chunk_count=0,
                embedding_model=embedding_model, document_ids=[],
            )

    monkeypatch.setattr(engine_module, "VectorStore", _RecordingStore)
    config = _config(Vertical.HEALTH, "health_gpc", "prompt")

    stats = RagEngine.corpus_stats_for(config)

    # collection + model flow from the ONE config (golden rule 4); nothing else
    # is constructed — no Generator, no Embedder, no warm-up.
    assert built == {"collection_name": "health_gpc", "embedding_model": "bge-m3"}
    assert stats.document_count == 0
