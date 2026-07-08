"""Unit tests for the AnswerabilityGate (evaluate_answerability — B2, SPEC_B2 v2).

No live LLM and no live embedder: S1 needs only ``Chunk.distance``, fixed by
hand (B2-NFR3 / B2-AC5). The integration tests drive the public
``Generator.parts_for_text`` seam with the anchor pass stubbed, pinning the
contract: INSUFFICIENT replaces the resolved parts with the canonical
abstention (zero CiteParts); SUFFICIENT leaves resolution untouched.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.generate import ABSTENTION_TEXT, Generator, evaluate_answerability
from core.models import (
    Chunk,
    ChunkMetadata,
    CiteAnchor,
    CitePart,
    RagEngineError,
    SufficiencyVerdict,
    TextPart,
    Vertical,
    VerticalConfig,
)

_MU = 0.075  # legal's measured mu: center of the [0.0615, 0.0882) operating band


def _chunk(doc_id: str, page: int, distance: float | None) -> Chunk:
    return Chunk(
        text=f"contenido de {doc_id} pág. {page}",
        metadata=ChunkMetadata(document_id=doc_id, page=page),
        distance=distance,
    )


def _context(distances: list[float | None]) -> list[Chunk]:
    # Distinct (doc, page) per chunk so the citation dedup never collapses them.
    return [_chunk(f"doc-{i}", i + 1, d) for i, d in enumerate(distances)]


# Profiles lifted from the measurement so the fixtures test the REAL shapes:
# flat = legal-b2-002 (margin +0.015, the archetypal B2); standout =
# legal-bridge-001 (margin +0.191, the dangerous false positive if over-fired).
_FLAT = [0.921, 0.925, 0.928, 0.940, 0.941, 0.941]
_STANDOUT = [0.674, 0.757, 0.839, 0.846, 0.852, 0.875]


# --- the verdict (B2-AC5) -----------------------------------------------------


def test_flat_margin_is_insufficient() -> None:
    verdict = evaluate_answerability(_context(_FLAT), margin_threshold=_MU)

    assert verdict is SufficiencyVerdict.INSUFFICIENT


def test_standout_top1_is_sufficient() -> None:
    verdict = evaluate_answerability(_context(_STANDOUT), margin_threshold=_MU)

    assert verdict is SufficiencyVerdict.SUFFICIENT


def test_single_chunk_is_sufficient() -> None:
    # No tail => no margin signal; absence of signal is never grounds to
    # abstain (SPEC_B2 v2 §5.1 — health-plain-003 retrieved n=1 and is
    # answerable). "No basis to override", not "measured sufficient".
    verdict = evaluate_answerability(_context([0.869]), margin_threshold=_MU)

    assert verdict is SufficiencyVerdict.SUFFICIENT


def test_empty_context_is_sufficient() -> None:
    # n=0 is the HARD abstention guard's jurisdiction (it fires before any LLM
    # call, upstream of this gate) — if consulted anyway, the gate passes
    # through rather than double-deciding someone else's case.
    verdict = evaluate_answerability([], margin_threshold=_MU)

    assert verdict is SufficiencyVerdict.SUFFICIENT


# --- fail-fast (B2-AC8 / B2-NFR6) ----------------------------------------------


def test_missing_distance_raises_actionable() -> None:
    # A retrieval-path chunk without a distance means the transient propagation
    # broke; a silent SUFFICIENT would disable the gate invisibly.
    context = _context([0.7, None, 0.8])

    with pytest.raises(RagEngineError, match="propagation"):
        evaluate_answerability(context, margin_threshold=_MU)


def test_zero_tail_mean_raises_not_zerodivision() -> None:
    with pytest.raises(RagEngineError, match="tail_mean"):
        evaluate_answerability(_context([0.0, 0.0, 0.0]), margin_threshold=_MU)


# --- integration at the single resolution site (_resolve_parts) ----------------


def _gate_generator() -> Generator:
    # No embedder wired: verify_anchors degrades to keep (additive), so the
    # only live-LLM seam left is anchor_citations — stubbed per test.
    return Generator(
        llm_model="qwen2.5:7b",
        ollama_base_url="http://localhost:11434",
        system_prompt="sp",
        inline_citation_mode="structured",
        answerability_gate_enabled=True,
        answerability_margin=_MU,
    )


def _stub_anchor_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        Generator,
        "anchor_citations",
        lambda self, sentences, context: [CiteAnchor(sentence_index=1, chunk_index=1)],
    )


def test_resolve_insufficient_forces_canonical_abstention(monkeypatch) -> None:
    # The gate runs AFTER verify_anchors, so valid anchors exist — and must be
    # discarded whole: the resolved state becomes the byte-exact abstention
    # that bug B's authority (query.py) recognizes on its own.
    _stub_anchor_pass(monkeypatch)
    generator = _gate_generator()

    text, parts = generator.parts_for_text("El plazo es de un mes.", _context(_FLAT))

    assert text == ABSTENTION_TEXT
    assert parts == [TextPart(text=ABSTENTION_TEXT)]  # zero CiteParts


def test_resolve_sufficient_leaves_resolution_untouched(monkeypatch) -> None:
    _stub_anchor_pass(monkeypatch)
    generator = _gate_generator()

    text, parts = generator.parts_for_text(
        "El plazo es de un mes.", _context(_STANDOUT)
    )

    assert text == "El plazo es de un mes."
    assert parts == [TextPart(text="El plazo es de un mes."), CitePart(n=1)]


def test_gate_disabled_never_evaluates(monkeypatch) -> None:
    # Default-off vertical (health today): even a flat context resolves as
    # before — the gate is data-switched, never consulted when disabled.
    _stub_anchor_pass(monkeypatch)
    monkeypatch.setattr(
        "core.generate.evaluate_answerability",
        lambda *args, **kwargs: pytest.fail("gate consulted while disabled"),
    )
    generator = Generator(
        llm_model="qwen2.5:7b",
        ollama_base_url="http://localhost:11434",
        system_prompt="sp",
        inline_citation_mode="structured",
    )

    text, parts = generator.parts_for_text("El plazo es de un mes.", _context(_FLAT))

    assert text == "El plazo es de un mes."
    assert parts == [TextPart(text="El plazo es de un mes."), CitePart(n=1)]


# --- config cross-validation (enabled requires the measured mu) ----------------


def _config_kwargs() -> dict:
    return dict(
        vertical=Vertical.LEGAL,
        display_name="Legal",
        corpus_path="data/legal",
        collection_name="legal_boe",
        system_prompt="sp",
        embedding_model="bge-m3",
        llm_model="qwen2.5:7b",
        relevance_threshold=1.05,
    )


def test_config_enabled_gate_without_margin_fails_validation() -> None:
    with pytest.raises(ValidationError, match="answerability_margin"):
        VerticalConfig(**_config_kwargs(), answerability_gate_enabled=True)


def test_config_enabled_gate_with_margin_validates() -> None:
    config = VerticalConfig(
        **_config_kwargs(),
        answerability_gate_enabled=True,
        answerability_margin=0.075,
    )

    assert config.answerability_margin == 0.075


def test_generator_enabled_gate_without_margin_fails_at_wiring() -> None:
    # The plain constructor bypasses VerticalConfig; the same invariant must
    # hold at the second construction seam (fail at wiring, not mid-query).
    with pytest.raises(ValueError, match="answerability_margin"):
        Generator(
            llm_model="m",
            ollama_base_url="u",
            system_prompt="s",
            answerability_gate_enabled=True,
        )
