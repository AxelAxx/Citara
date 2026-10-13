"""POST /api/verticals/{id}/query — the core use case as an SSE stream."""

from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from api.dependencies import get_engine
from api.errors import http_error_for
from api.schemas import QueryRequest
from core.engine import StreamedAnswer
from core.generate import ABSTENTION_TEXT
from core.models import CitePart, RagEngineError, TextPart

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
    return EventSourceResponse(_stream_events(streamed))


def _stream_events(streamed: StreamedAnswer) -> Iterator[dict]:
    """The SSE event sequence for one query: citations → token* → done | error.

    Module-level (not a closure) so tests can drive it with a fake
    StreamedAnswer and assert the emitted frames without the ASGI stack.
    """
    # citations FIRST (fixed the instant retrieval returned): the front
    # reserves the sources/abstention slot before any text arrives. Its
    # is_abstention only
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
            "data": json.dumps({"error_code": code, "message": str(exc)}, ensure_ascii=False),
        }
        return
    if not streamed.citations:
        # Hard path (unchanged): empty retrieval is an abstention by STATE.
        # One plain part, no cites — the abstention shape the contract
        # documents. No resolve_parts call: there is nothing to anchor, and
        # in "structured" mode that would be a wasted second LLM call.
        is_abstention = True
        parts = [TextPart(text=full_text)]
    else:
        # Retrieval hit: resolution ALWAYS runs — including for a pure
        # soft-decline, where it returns instantly (core's pure-abstention
        # guard short-circuits before the anchor pass), so no LLM call is
        # wasted. The anchored, core-validated parts come from
        # Generator.parts_for_text via the StreamedAnswer seam — the api
        # never parses or anchors anything, and never decides the vertical's
        # inline_citation_mode: core does. LATENCY, stated loudly: in
        # "structured" mode this is the second LLM call over the full text,
        # and the chips arrive with this done event a few seconds after the
        # last token. Accepted trade-off; "off" resolves instantly.
        final_text, parts = streamed.resolve_parts(full_text)
        # Abstention authority is the RESOLVED state, never raw prose and
        # never raw retrieval citations. A leading "No encuentro esto..."
        # followed by real cited content resolves to CiteParts => answered
        # (the old startswith marked it an abstention WITH citations behind
        # it). A pure soft-decline has citations (retrieval hit) but zero
        # CiteParts => abstention. Zero CiteParts ALONE is not enough — mode
        # "off" and a degraded anchor pass also produce chip-less GROUNDED
        # answers — so the resolved text must also BE core's abstention
        # sentence (byte-exact equality post-strip, the same pure-abstention
        # rule core applies in _resolve_parts).
        has_cite = any(isinstance(part, CitePart) for part in parts)
        is_abstention = not has_cite and final_text.strip() == ABSTENTION_TEXT
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
