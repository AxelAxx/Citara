"""RagEngineError → HTTP mapping (API_CONTRACT.md §Error mapping).

One table, two consumers: the global exception handlers (JSON error bodies) and
the /query SSE adapter (its mid-stream "error" event). The exception messages
from core are already actionable (NFR6) — passed through verbatim, never
rewritten here.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.models import (
    EmptyCorpusError,
    ModelNotPulledError,
    OllamaUnreachableError,
    RagEngineError,
    RetrievalError,
)

# Most specific first: http_error_for walks this in order, so the RagEngineError
# base catch-all must stay last.
_ERROR_MAP: list[tuple[type[Exception], int, str]] = [
    (OllamaUnreachableError, 503, "ollama_unreachable"),
    (ModelNotPulledError, 503, "model_not_pulled"),
    (EmptyCorpusError, 409, "empty_corpus"),
    (RetrievalError, 503, "retrieval_failed"),
    (RagEngineError, 500, "engine_error"),
]


def http_error_for(exc: Exception) -> tuple[int, str]:
    """Resolve (status, error_code) for a domain error — the ONE mapping site."""
    for exc_type, status, code in _ERROR_MAP:
        if isinstance(exc, exc_type):
            return status, code
    return 500, "engine_error"


def register_exception_handlers(app: FastAPI) -> None:
    """Install the contract's uniform ``{error_code, message}`` handlers."""

    @app.exception_handler(RagEngineError)
    async def _rag_engine_error(request: Request, exc: RagEngineError) -> JSONResponse:
        status, code = http_error_for(exc)
        return JSONResponse(
            status_code=status,
            content={"error_code": code, "message": str(exc)},
        )

    @app.exception_handler(ValueError)
    async def _unknown_vertical(request: Request, exc: ValueError) -> JSONResponse:
        # Vertical("bogus") raises ValueError — the only ValueError the routes
        # let escape — so it maps to 404 unknown_vertical (API_CONTRACT.md).
        return JSONResponse(
            status_code=404,
            content={"error_code": "unknown_vertical", "message": str(exc)},
        )
