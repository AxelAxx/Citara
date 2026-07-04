"""POST /api/verticals/{id}/query — the core use case as an SSE stream."""

from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from core.models import RagEngineError

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
        # same ordering app.py's label_slot relied on. Empty citations ⇔ the
        # engine took the empty-context abstention path (API_CONTRACT.md).
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
        try:
            for fragment in streamed.text_stream:
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
        yield {"event": "done", "data": json.dumps({})}

    return EventSourceResponse(events())
