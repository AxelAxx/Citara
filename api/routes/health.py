"""GET /api/health — the aggregated preflight behind the sidebar badge."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.dependencies import get_engine
from api.errors import http_error_for
from core.generate import ABSTENTION_TEXT
from core.ingest import load_vertical_config
from core.models import RagEngineError, Vertical

router = APIRouter()


@router.get("/api/health")
def health() -> JSONResponse:
    """One aggregated check_health() (Embedder + Generator preflights).

    The preflight is server/model-level and identical for every Vertical, so it
    runs against the FIRST configured Vertical (enum iteration order) — no
    vertical is special-cased.
    """
    vertical = next(iter(Vertical))
    config = load_vertical_config(vertical)
    try:
        get_engine(vertical.value).check_health()
    except RagEngineError as exc:
        # /health carries ok:false ON TOP of the uniform error shape
        # (API_CONTRACT.md §/api/health) — handled here, not by the global handler.
        status, code = http_error_for(exc)
        return JSONResponse(
            status_code=status,
            content={"ok": False, "error_code": code, "message": str(exc)},
        )
    return JSONResponse(
        content={
            "ok": True,
            "llm_model": config.llm_model,
            "embedding_model": config.embedding_model,
            "ollama_base_url": config.ollama_base_url,
            # The exact abstention literal, published so the front's transient
            # streaming cleanup uses core's single source of truth instead of
            # duplicating the phrase (it is UI copy AND a domain constant).
            # Cosmetic use only — abstention is DECIDED by the done event.
            "abstention_text": ABSTENTION_TEXT,
        }
    )
