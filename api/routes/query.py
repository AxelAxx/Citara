"""POST /api/verticals/{id}/query — the core use case as an SSE stream."""

from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from core.generate import ABSTENTION_TEXT, parse_citations
from core.models import RagEngineError, TextPart

from api.dependencies import get_engine
from api.errors import http_error_for
from api.schemas import QueryRequest

router = APIRouter()


@router.post("/api/verticals/{vertical_id}/query")
def query(vertical_id: str, body: QueryRequest) -> EventSourceResponse:
    """Adapt StreamedAnswer to the contract's SSE sequence.

    Retrieval runs eagerly inside answer_stream, so retrieval-time errors (and
    an unknown vertical id) raise HERE, before any SSE bytes — they surface as
    the normal JSON error responses via the global handlers. Only generation
    failures (Ollama dropping mid-stream) become the in-stream "error" event.
    """
    streamed = get_engine(vertical_id).answer_stream(body.query)

    def events() -> Iterator[dict]:
        # citations FIRST (fixed the instant retrieval returned): the front
        # reserves the sources/abstention slot before any text arrives — the
        # same ordering app.py's label_slot relied on. Its is_abstention only
        # covers the EARLY hard path (empty context ⇒ no citations); the done
        # event below is the authoritative resolution, because the soft
        # abstention is only detectable once the full text is known.
        yield {
            "event": "citations",
            "data": json.dumps(
                {
                    "citations": [c.model_dump() for c in streamed.citations],
                    "is_abstention": len(streamed.citations) == 0,
                },
                ensure_ascii=False,
            ),
        }
        full_text = ""
        try:
            for fragment in streamed.text_stream:
                full_text += fragment
                yield {
                    "event": "token",
                    "data": json.dumps({"text": fragment}, ensure_ascii=False),
                }
        except RagEngineError as exc:
            # The HTTP status already went out with the stream headers, so a
            # mid-stream failure travels as the contract's terminal "error"
            # event — actionable message verbatim, never rewritten.
            _, code = http_error_for(exc)
            yield {
                "event": "error",
                "data": json.dumps(
                    {"error_code": code, "message": str(exc)}, ensure_ascii=False
                ),
            }
            return
        # Authoritative abstention resolution, mirror of the Streamlit layout's
        # _is_abstention_text: hard path (no citations) OR soft path (the LLM
        # declined in prose despite noisy retrieved context — vector search
        # always returns top-k neighbours, so the hard guard rarely fires on an
        # ingested corpus). suppress_citations tells the front to drop the
        # sources panel: sources under "I can't find this" would contradict the
        # answer (same rule that builds Answer.abstention in the Streamlit UI).
        is_abstention = not streamed.citations or full_text.strip().startswith(
            ABSTENTION_TEXT
        )
        if is_abstention:
            # One plain part, no cites: a chip under a suppressed sources panel
            # would point at nothing renderable (consistent with
            # suppress_citations below).
            parts = [TextPart(text=full_text)]
        else:
            # The typed view of the final text, REUSING core's parser — no
            # marker logic in api. The accumulated text came from core's
            # part_stream plain view, so its [n] markers are already validated
            # and remapped to citation indexes (invalid ones never reached the
            # wire); parsing against the citations count reproduces the same
            # parts core would attach to a non-streamed Answer.
            parts = parse_citations(
                full_text, num_citations=len(streamed.citations)
            )
        yield {
            "event": "done",
            "data": json.dumps(
                {
                    "is_abstention": is_abstention,
                    "suppress_citations": is_abstention,
                    "parts": [part.model_dump() for part in parts],
                },
                ensure_ascii=False,
            ),
        }

    return EventSourceResponse(events())
