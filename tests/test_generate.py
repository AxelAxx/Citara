"""Unit tests for the Generator (module 6, FR7–FR9 → AC2, AC3, G4).

No live Ollama: generation is mocked at ``requests.post`` (``/api/chat``) and the
preflight at ``requests.get`` (``/api/tags``), so nothing touches the network.
The tests assert the contract — the hard abstention guard never calls the LLM,
the prompt carries formatted citable blocks, Citations derive from context and
dedupe, the Answer invariant holds, and the failure modes stay distinct.
"""

from __future__ import annotations

import json

import pytest

from core.generate import (
    ABSTENTION_TEXT,
    Generator,
    iter_answer_parts,
    parse_citations,
    strip_trailing_abstention,
)
from core.models import (
    Answer,
    Chunk,
    ChunkMetadata,
    Citation,
    CitePart,
    ModelNotPulledError,
    OllamaUnreachableError,
    Query,
    RagEngineError,
    TextPart,
    Vertical,
)

_SYSTEM_PROMPT = "Eres un asistente legal. Responde solo con el contexto. Cita las fuentes."


class _FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        payload: dict | None = None,
        *,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> dict:
        # Mirror requests: a body that isn't JSON raises ValueError.
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


def _chat_reply(content: str) -> _FakeResponse:
    """A successful /api/chat response: text nested at message.content."""
    return _FakeResponse(200, {"message": {"role": "assistant", "content": content}})


def _install_chat(monkeypatch, reply: str = "Respuesta basada en el contexto.") -> list[dict]:
    """Mock requests.post to record bodies and replay a canned reply.

    Returns the list that captures each POST's JSON body, so a test can assert
    the request shape (model, messages, stream) the Generator sent.
    """
    bodies: list[dict] = []

    def fake_post(url, json=None, timeout=None):
        assert url.endswith("/api/chat")
        bodies.append(json)
        return _chat_reply(reply)

    monkeypatch.setattr("requests.post", fake_post)
    return bodies


class _FakeStreamResponse:
    """A /api/chat response consumed as a stream: iter_lines yields NDJSON bytes."""

    def __init__(
        self,
        lines: list[bytes],
        status_code: int = 200,
        payload: dict | None = None,
        *,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._lines = lines
        self._payload = payload
        self.text = text

    def json(self) -> dict:
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload

    def iter_lines(self):
        # Ollama yields bytes, one JSON object per line; mirror that here.
        yield from self._lines


def _stream_lines(fragments: list[str]) -> list[bytes]:
    """NDJSON lines for a streamed reply: one fragment per line, then a done marker."""
    lines = [
        json.dumps({"message": {"role": "assistant", "content": frag}, "done": False}).encode()
        for frag in fragments
    ]
    # Final line: Ollama sends an empty content with done=True to close the stream.
    lines.append(json.dumps({"message": {"role": "assistant", "content": ""}, "done": True}).encode())
    return lines


def _chunk(doc_id: str, page: int, text: str = "texto", **md_extra) -> Chunk:
    return Chunk(
        text=text,
        metadata=ChunkMetadata(document_id=doc_id, page=page, **md_extra),
    )


def _make_generator(system_prompt: str = _SYSTEM_PROMPT) -> Generator:
    return Generator(
        llm_model="qwen2.5:7b",
        ollama_base_url="http://localhost:11434",
        system_prompt=system_prompt,
    )


# --- AC3 / G4: hard abstention guard, no LLM call ----------------------------


def test_empty_context_abstains_without_calling_llm(monkeypatch):
    # If the LLM is ever called on empty context, this fake fails the test loudly.
    def boom(url, json=None, timeout=None):
        raise AssertionError("LLM must not be called on empty context")

    monkeypatch.setattr("requests.post", boom)
    generator = _make_generator()

    answer = generator.generate(Query(text="¿algo?"), context=[])

    assert isinstance(answer, Answer)
    assert answer.is_abstention is True
    assert answer.citations == []
    assert answer.text == ABSTENTION_TEXT


# --- FR7: grounded prompt carries formatted citable blocks -------------------


def test_prompt_contains_formatted_blocks_with_document_id_and_page(monkeypatch):
    bodies = _install_chat(monkeypatch)
    generator = _make_generator()
    context = [
        _chunk("BOE-A-2015-11430", 7, "El plazo es de un mes."),
        _chunk("guia-salud-01", 3, "Recomendación clínica."),
    ]

    generator.generate(Query(text="¿cuál es el plazo?"), context=context)

    # One POST; messages = [system, user] with the vertical system_prompt verbatim.
    assert len(bodies) == 1
    body = bodies[0]
    assert body["model"] == "qwen2.5:7b"
    assert body["stream"] is False
    messages = body["messages"]
    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[0]["content"] == _SYSTEM_PROMPT  # vertical system_prompt passed through

    prompt = messages[1]["content"]
    assert "[Documento: BOE-A-2015-11430, pág. 7]" in prompt
    assert "El plazo es de un mes." in prompt
    assert "[Documento: guia-salud-01, pág. 3]" in prompt
    assert "Recomendación clínica." in prompt
    assert "¿cuál es el plazo?" in prompt  # the Query is in the prompt


# --- FR9 / AC2: citations derive from context, with dedup --------------------


def test_citations_derive_from_context(monkeypatch):
    _install_chat(monkeypatch)
    generator = _make_generator()
    context = [
        _chunk("doc-a", 1, section="Artículo 1", vertical=Vertical.LEGAL),
        _chunk("doc-b", 5),
    ]

    answer = generator.generate(Query(text="x"), context=context)

    assert [(c.document_id, c.page) for c in answer.citations] == [("doc-a", 1), ("doc-b", 5)]
    # from_metadata carries section through; Citation has no vertical field.
    assert answer.citations[0].section == "Artículo 1"


def test_citations_dedup_same_document_and_page(monkeypatch):
    _install_chat(monkeypatch)
    generator = _make_generator()
    # Two distinct chunks from the same document+page → a single Citation.
    context = [
        _chunk("doc-a", 2, "primer fragmento"),
        _chunk("doc-a", 2, "segundo fragmento"),
        _chunk("doc-a", 3, "otra página"),
    ]

    answer = generator.generate(Query(text="x"), context=context)

    assert [(c.document_id, c.page) for c in answer.citations] == [("doc-a", 2), ("doc-a", 3)]


# --- Answer invariant: non-abstaining answer always cited --------------------


def test_non_abstaining_answer_always_has_at_least_one_citation(monkeypatch):
    _install_chat(monkeypatch)
    generator = _make_generator()

    answer = generator.generate(Query(text="x"), context=[_chunk("doc", 1)])

    assert answer.is_abstention is False
    assert len(answer.citations) >= 1


# --- FR7: LLM reply becomes the Answer text ----------------------------------


def test_answer_text_comes_from_llm_reply(monkeypatch):
    _install_chat(monkeypatch, reply="El plazo para recurrir es de un mes.")
    generator = _make_generator()

    answer = generator.generate(Query(text="¿plazo?"), context=[_chunk("doc", 1)])

    assert answer.text == "El plazo para recurrir es de un mes."
    assert isinstance(answer.text, str)


# --- generation-time failures (fail-fast) ------------------------------------


def test_generate_raises_unreachable_when_post_fails(monkeypatch):
    def boom(url, json=None, timeout=None):
        raise ConnectionError("connection refused")

    monkeypatch.setattr("requests.post", boom)

    with pytest.raises(OllamaUnreachableError):
        _make_generator().generate(Query(text="x"), context=[_chunk("doc", 1)])


def test_generate_raises_model_not_pulled_on_model_error(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        return _FakeResponse(404, {"error": "model 'qwen2.5:7b' not found, try pulling it first"})

    monkeypatch.setattr("requests.post", fake_post)

    with pytest.raises(ModelNotPulledError) as exc:
        _make_generator().generate(Query(text="x"), context=[_chunk("doc", 1)])
    assert "ollama pull qwen2.5:7b" in str(exc.value)


def test_generate_raises_on_missing_message_content(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        return _FakeResponse(200, {"unexpected": True})

    monkeypatch.setattr("requests.post", fake_post)

    with pytest.raises(RagEngineError):
        _make_generator().generate(Query(text="x"), context=[_chunk("doc", 1)])


# --- FR9 / 3b: inline [N] markers → AnswerParts --------------------------------


def test_parse_citations_valid_markers_build_parts():
    parts = parse_citations("Un mes [1]. Quince días [2].", num_citations=2)

    assert parts == [
        TextPart(text="Un mes "),
        CitePart(n=1),
        TextPart(text=". Quince días "),
        CitePart(n=2),
        TextPart(text="."),
    ]


def test_parse_citations_out_of_range_marker_is_dropped():
    # [7] has no fragment behind it — an LLM error, not a citation. It is
    # scrubbed whole and its text neighbours merge back together.
    parts = parse_citations("Cierto [1]. Inventado [7]. Fin.", num_citations=1)

    assert parts == [
        TextPart(text="Cierto "),
        CitePart(n=1),
        TextPart(text=". Inventado . Fin."),
    ]
    # [0] is equally out of range (1-based): it must never slip through and
    # reach citations[-1] via Python's negative indexing downstream.
    assert parse_citations("Nada [0].", num_citations=1) == [TextPart(text="Nada .")]


def test_parse_citations_plain_text_is_single_textpart():
    parts = parse_citations("Sin marcadores en absoluto.", num_citations=3)

    assert parts == [TextPart(text="Sin marcadores en absoluto.")]


def test_parse_citations_unclosed_or_nonnumeric_brackets_stay_text():
    # "[12" never closes and "[a]" is not a marker: both remain literal text.
    parts = parse_citations("Ver [12 y también [a].", num_citations=2)

    assert all(isinstance(p, TextPart) for p in parts)
    assert "".join(p.text for p in parts) == "Ver [12 y también [a]."


def test_parse_citations_template_literal_is_dropped():
    # The model sometimes echoes the prompt's "[N]" placeholder verbatim —
    # template garbage, not prose: dropped whole, neighbours merged.
    parts = parse_citations("Un mes [N]. Y quince días [1].", num_citations=1)

    assert parts == [
        TextPart(text="Un mes . Y quince días "),
        CitePart(n=1),
        TextPart(text="."),
    ]


# --- trailing-abstention strip (golden rule 3: cited OR abstention, never both) ---


def test_strip_trailing_abstention_removes_exact_suffix_and_surrounding_whitespace():
    text = f"El plazo es de un mes [1].\n\n  {ABSTENTION_TEXT}  \n"

    assert strip_trailing_abstention(text) == "El plazo es de un mes [1]."


def test_strip_trailing_abstention_returns_text_without_suffix_untouched():
    text = "El plazo es de un mes [1]."

    assert strip_trailing_abstention(text) == text


def test_cited_text_with_trailing_abstention_loses_it_in_parts():
    # The 7B's mixed failure mode: a correct cited answer + the abstention
    # sentence appended. The parts view must not carry the spurious TextPart.
    text = f"El plazo es de un mes [1].\n\n{ABSTENTION_TEXT}"

    parts = parse_citations(text, num_citations=2)

    assert parts == [
        TextPart(text="El plazo es de un mes "),
        CitePart(n=1),
        TextPart(text="."),
    ]


def test_pure_abstention_is_never_stripped():
    # 0 CiteParts ⇒ the phrase IS the answer (e.g. the empty-context guard):
    # stripping here would return an empty Answer — the critical non-case.
    parts = parse_citations(ABSTENTION_TEXT, num_citations=0)

    assert parts == [TextPart(text=ABSTENTION_TEXT)]


def test_cited_text_without_trailing_abstention_is_untouched():
    parts = parse_citations("El plazo es de un mes [1].", num_citations=1)

    assert parts == [
        TextPart(text="El plazo es de un mes "),
        CitePart(n=1),
        TextPart(text="."),
    ]


def test_mid_text_abstention_is_not_stripped():
    # Only a TRAILING occurrence goes; the phrase inside the prose stays.
    text = f"{ABSTENTION_TEXT} Sin embargo, el artículo 5 dice otra cosa [1]."

    parts = parse_citations(text, num_citations=1)

    assert parts == [
        TextPart(text=f"{ABSTENTION_TEXT} Sin embargo, el artículo 5 dice otra cosa "),
        CitePart(n=1),
        TextPart(text="."),
    ]


def test_paraphrased_trailing_abstention_is_not_stripped():
    # Byte-exactness: only the literal is removed, never a lookalike — a
    # paraphrase is LLM prose, and guessing at it would censor real text.
    text = "El plazo es de un mes [1]. No encuentro esto en los documentos."

    parts = parse_citations(text, num_citations=1)

    assert parts[-1] == TextPart(text=". No encuentro esto en los documentos.")


def test_generate_strips_trailing_abstention_from_text_and_parts(monkeypatch):
    # End-to-end through generate(): Answer.text and Answer.parts are one view —
    # both lose the appended sentence, neither loses the citation.
    _install_chat(
        monkeypatch, reply=f"El plazo es de un mes [1].\n\n{ABSTENTION_TEXT}"
    )
    generator = _make_generator()

    answer = generator.generate(Query(text="¿plazo?"), [_chunk("doc", 1)])

    assert answer.text == "El plazo es de un mes [1]."
    assert CitePart(n=1) in answer.parts
    assert all(
        ABSTENTION_TEXT not in part.text
        for part in answer.parts
        if isinstance(part, TextPart)
    )


def test_iter_answer_parts_template_literal_split_across_fragments():
    # "[N]" can arrive tokenized like any marker; it must still be dropped
    # whole, never leaking "[" or "N" into the text parts.
    fragments = ["Un mes [", "N", "]", " y fin."]

    parts = list(iter_answer_parts(fragments, num_citations=2))

    assert all(isinstance(p, TextPart) for p in parts)
    assert "".join(p.text for p in parts) == "Un mes  y fin."


def test_iter_answer_parts_resolves_marker_split_across_fragments():
    # The token stream splits "[2]" across three fragments — the parser must
    # withhold the prefix and emit one whole CitePart, leaking no bracket text.
    fragments = ["Un mes [", "2", "]", ". Fin."]

    parts = list(iter_answer_parts(fragments, num_citations=2))

    assert CitePart(n=2) in parts
    text = "".join(p.text for p in parts if isinstance(p, TextPart))
    assert text == "Un mes . Fin."


def test_iter_answer_parts_streams_text_before_marker_completes():
    fragments = iter(["Hola ", "mundo [", "1]"])

    stream = iter_answer_parts(fragments, num_citations=1)

    # Plain text flows through immediately — the parser never buffers text that
    # provably contains no marker (streaming must not degrade to batch).
    assert next(stream) == TextPart(text="Hola ")


def test_generate_remaps_fragment_markers_to_citation_indexes(monkeypatch):
    # Fragments are numbered per CHUNK (1..3) while citations dedupe by
    # (document_id, page): [2] cites the duplicated doc-a page and [3] cites
    # doc-b, so the CiteParts must carry the CITATION indexes (1 and 2) — the
    # front resolves n → citations[n-1] positionally.
    _install_chat(monkeypatch, reply="Afirmación [2]. Otra [3].")
    generator = _make_generator()
    context = [
        _chunk("doc-a", 1, "primer fragmento"),
        _chunk("doc-a", 1, "segundo fragmento"),
        _chunk("doc-b", 2, "otra fuente"),
    ]

    answer = generator.generate(Query(text="¿?"), context=context)

    assert len(answer.citations) == 2  # deduped
    assert [(c.document_id, c.page) for c in answer.citations] == [
        ("doc-a", 1),
        ("doc-b", 2),
    ]
    cites = [p for p in answer.parts if isinstance(p, CitePart)]
    assert [c.n for c in cites] == [1, 2]  # fragment [2]→cita 1, [3]→cita 2


def test_generate_stream_parts_empty_context_yields_single_abstention_textpart(
    monkeypatch,
):
    # Same hard guard as generate()/generate_stream(): empty context ⇒ the
    # abstention sentence as ONE TextPart, zero CiteParts, and no LLM call.
    def boom(url, json=None, timeout=None, stream=None):
        raise AssertionError("LLM must not be called on empty context")

    monkeypatch.setattr("requests.post", boom)

    parts = list(_make_generator().generate_stream_parts(Query(text="¿?"), []))

    assert parts == [TextPart(text=ABSTENTION_TEXT)]


def test_answer_rejects_citepart_index_out_of_citations_range():
    carried = Citation(document_id="doc", page=1)

    # n beyond the citations list would render a chip resolving to nothing.
    with pytest.raises(ValueError):
        Answer(text="t [2]", citations=[carried], parts=[CitePart(n=2)])
    # n=0 breaks the 1-based contract the same way.
    with pytest.raises(ValueError):
        Answer(text="t [0]", citations=[carried], parts=[CitePart(n=0)])


# --- AC7: preflight failures stay distinct -----------------------------------


def test_check_health_raises_when_model_absent(monkeypatch):
    payload = {"models": [{"name": "bge-m3:latest"}]}  # qwen2.5 not pulled
    monkeypatch.setattr("requests.get", lambda url, timeout=None: _FakeResponse(200, payload))

    with pytest.raises(ModelNotPulledError) as exc:
        _make_generator().check_health()
    assert "ollama pull qwen2.5:7b" in str(exc.value)


def test_check_health_passes_when_model_pulled(monkeypatch):
    payload = {"models": [{"name": "qwen2.5:7b"}, {"name": "bge-m3:latest"}]}
    monkeypatch.setattr("requests.get", lambda url, timeout=None: _FakeResponse(200, payload))

    _make_generator().check_health()  # no exception == pass


def test_check_health_raises_when_ollama_unreachable(monkeypatch):
    def boom(url, timeout=None):
        raise ConnectionError("connection refused")

    monkeypatch.setattr("requests.get", boom)

    with pytest.raises(OllamaUnreachableError):
        _make_generator().check_health()


# --- FR7 streaming: generate_stream yields fragments in order ----------------


def test_generate_stream_yields_fragments_in_order(monkeypatch):
    fragments = ["El plazo ", "es de ", "un mes."]
    bodies: list[dict] = []

    def fake_post(url, json=None, timeout=None, stream=None):
        assert url.endswith("/api/chat")
        assert stream is True  # streamed request, unlike the non-streamed generate()
        bodies.append(json)
        return _FakeStreamResponse(_stream_lines(fragments))

    monkeypatch.setattr("requests.post", fake_post)
    generator = _make_generator()

    got = list(generator.generate_stream(Query(text="¿plazo?"), context=[_chunk("doc", 1)]))

    # Fragments arrive in order and concatenate to the full reply (the empty done
    # marker is dropped, not yielded).
    assert got == fragments
    assert "".join(got) == "El plazo es de un mes."
    assert len(bodies) == 1
    assert bodies[0]["stream"] is True


def test_generate_stream_empty_context_abstains_without_calling_llm(monkeypatch):
    # AC3 / G4 must hold on the streaming path too: no context ⇒ no LLM call.
    def boom(url, json=None, timeout=None, stream=None):
        raise AssertionError("LLM must not be called on empty context")

    monkeypatch.setattr("requests.post", boom)
    generator = _make_generator()

    got = list(generator.generate_stream(Query(text="¿algo?"), context=[]))

    assert got == [ABSTENTION_TEXT]  # the abstention sentence, yielded whole
    assert "".join(got) == ABSTENTION_TEXT


def test_generate_stream_raises_unreachable_before_yielding(monkeypatch):
    # Fail-fast: an unreachable Ollama surfaces on the first iteration, before any
    # generated text reaches the caller.
    def boom(url, json=None, timeout=None, stream=None):
        raise ConnectionError("connection refused")

    monkeypatch.setattr("requests.post", boom)
    stream = _make_generator().generate_stream(Query(text="x"), context=[_chunk("doc", 1)])

    with pytest.raises(OllamaUnreachableError):
        list(stream)


# --- #09-lite: chunk_text provenance on Citations -----------------------------


def test_citation_from_chunk_composes_metadata_and_text():
    from core.models import Citation

    chunk = _chunk("doc-a", 3, "el pasaje citado", section="Artículo 9")

    citation = Citation.from_chunk(chunk)

    # from_metadata's base mapping + the chunk's text on top (viewer provenance).
    assert (citation.document_id, citation.page, citation.section) == ("doc-a", 3, "Artículo 9")
    assert citation.chunk_text == "el pasaje citado"


def test_citations_carry_chunk_text_and_dedup_keeps_first_seen(monkeypatch):
    _install_chat(monkeypatch)
    generator = _make_generator()
    context = [
        _chunk("doc-a", 2, "primer fragmento"),
        _chunk("doc-a", 2, "segundo fragmento"),  # same doc+page: collapses
        _chunk("doc-b", 5, "otro documento"),
    ]

    answer = generator.generate(Query(text="x"), context=context)

    # The FIRST chunk seen (relevance order) contributes the text.
    assert [c.chunk_text for c in answer.citations] == ["primer fragmento", "otro documento"]


def test_chunk_text_default_is_empty_fail_safe():
    from core.models import Citation

    citation = Citation(document_id="d", page=1)

    assert citation.chunk_text == ""
