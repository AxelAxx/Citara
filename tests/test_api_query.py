"""Unit tests for the /query SSE event stream (API_CONTRACT.md §/query).

``_stream_events`` is driven directly with a StreamedAnswer — no ASGI stack,
no LLM. What these tests pin down is the EVENT contract: ordering, the done
event serving core's anchored parts through the resolve_parts seam, and the
abstention shape (single TextPart, no resolve call).
"""

from __future__ import annotations

import json

from api.routes.query import _stream_events
from core.engine import StreamedAnswer
from core.generate import ABSTENTION_TEXT
from core.models import Citation, CitePart, TextPart


def _collect(events) -> list[tuple[str, dict]]:
    return [(event["event"], json.loads(event["data"])) for event in events]


def _citation() -> Citation:
    return Citation(document_id="doc", page=1)


def test_done_serves_anchored_parts_from_resolve_parts():
    resolve_calls: list[str] = []

    def resolve(full_text: str):
        resolve_calls.append(full_text)
        return full_text, [TextPart(text="El plazo es de un mes."), CitePart(n=1)]

    streamed = StreamedAnswer(
        part_stream=iter([TextPart(text="El plazo "), TextPart(text="es de un mes.")]),
        citations=[_citation()],
        resolve_parts=resolve,
    )

    events = _collect(_stream_events(streamed))

    assert [name for name, _ in events] == ["citations", "token", "token", "done"]
    # Resolved once, over the FULL accumulated text — the anchor pass needs
    # the whole answer, which is why parts arrive with done, not per token.
    assert resolve_calls == ["El plazo es de un mes."]
    done = events[-1][1]
    assert done["is_abstention"] is False
    assert done["parts"] == [
        {"kind": "text", "text": "El plazo es de un mes."},
        {"kind": "cite", "n": 1},
    ]


def test_done_serves_plain_textpart_when_core_mode_is_off():
    # The api never decides the inline_citation_mode: core does. In "off",
    # parts_for_text already returns a single TextPart — passthrough here.
    streamed = StreamedAnswer(
        part_stream=iter([TextPart(text="Texto plano.")]),
        citations=[_citation()],
        resolve_parts=lambda text: (text, [TextPart(text=text)]),
    )

    done = _collect(_stream_events(streamed))[-1][1]

    assert done["parts"] == [{"kind": "text", "text": "Texto plano."}]
    assert done["is_abstention"] is False


def test_leading_abstention_with_citations_is_not_abstention():
    # Bug B repro: the 7B LEADS with the abstention phrase and then delivers
    # real cited content. The old startswith authority marked this done as an
    # abstention WITH citations behind it — suppressing the panel and skipping
    # resolve_parts. State authority (citations exist) sends it through
    # resolve_parts like any answer; core's symmetric strip cleans the phrase.
    full = f"{ABSTENTION_TEXT} Sin embargo, el artículo 5 dice otra cosa."
    resolved_calls: list[str] = []

    def resolve(full_text: str):
        resolved_calls.append(full_text)
        # What core's _resolve_parts produces for this reply: leading phrase
        # stripped, content anchored.
        return "Sin embargo, el artículo 5 dice otra cosa.", [
            TextPart(text="Sin embargo, el artículo 5 dice otra cosa."),
            CitePart(n=1),
        ]

    streamed = StreamedAnswer(
        part_stream=iter([TextPart(text=full)]),
        citations=[_citation()],
        resolve_parts=resolve,
    )

    done = _collect(_stream_events(streamed))[-1][1]

    assert resolved_calls == [full]  # resolve_parts DID run (no short-circuit)
    assert done["is_abstention"] is False
    assert done["suppress_citations"] is False
    assert {"kind": "cite", "n": 1} in done["parts"]  # chips, not a raw TextPart


def test_pure_soft_decline_with_citations_is_abstention():
    # The symmetric contradiction the state-authority fix must NOT introduce:
    # retrieval hit (citations non-empty) but the 7B declined in prose — the
    # resolved parts carry ZERO CiteParts and the resolved text IS the
    # abstention sentence. Showing a sources panel next to "No encuentro
    # esto..." would be rule 3 inverted, so this IS an abstention: authority
    # is the RESOLVED state (parts + final text), not raw citations.
    streamed = StreamedAnswer(
        part_stream=iter([TextPart(text=ABSTENTION_TEXT)]),
        citations=[_citation()],  # retrieval found chunks; the model declined
        resolve_parts=lambda text: (text, [TextPart(text=text)]),
    )

    done = _collect(_stream_events(streamed))[-1][1]

    assert done["is_abstention"] is True
    assert done["suppress_citations"] is True
    assert done["parts"] == [{"kind": "text", "text": ABSTENTION_TEXT}]


def test_hard_abstention_done_is_single_textpart_without_resolve_call():
    def boom(full_text: str):
        raise AssertionError("resolve_parts must not run on an abstention (nothing to anchor)")

    streamed = StreamedAnswer(
        part_stream=iter([TextPart(text=ABSTENTION_TEXT)]),
        citations=[],  # hard path: empty context ⇒ no citations
        resolve_parts=boom,
    )

    events = _collect(_stream_events(streamed))

    assert events[0][0] == "citations"
    assert events[0][1]["is_abstention"] is True
    done = events[-1][1]
    assert done["is_abstention"] is True
    assert done["suppress_citations"] is True
    # The contract's abstention shape: one TextPart, zero CiteParts — and
    # never parts=[] (a parts-consumer would render nothing).
    assert done["parts"] == [{"kind": "text", "text": ABSTENTION_TEXT}]
