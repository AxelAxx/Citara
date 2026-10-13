"""GET /api/verticals + /api/verticals/{id}/corpus — presentation config and stats."""

from __future__ import annotations

from fastapi import APIRouter

from api.schemas import VerticalsResponse, VerticalView
from core.engine import RagEngine
from core.ingest import load_vertical_config
from core.models import CorpusStats, RagEngineError, Vertical

router = APIRouter()


@router.get("/api/verticals")
def list_verticals() -> VerticalsResponse:
    """Every configured Vertical as a presentation-safe view.

    A Vertical whose YAML is missing/invalid simply isn't offered — the same
    fail-safe rule as ui.state.vertical_options (the BYOD seam's HTTP twin).
    """
    views: list[VerticalView] = []
    for vertical in Vertical:
        try:
            config = load_vertical_config(vertical)
        except RagEngineError:
            continue
        views.append(VerticalView.from_config(config))
    return VerticalsResponse(verticals=views)


@router.get("/api/verticals/{vertical_id}/corpus")
def corpus_stats(vertical_id: str) -> CorpusStats:
    """CorpusStats serialized as-is via the LIGHT façade (no Generator, no warm-up).

    An unknown id raises ValueError from ``Vertical(...)`` → 404 unknown_vertical.
    """
    config = load_vertical_config(Vertical(vertical_id))
    return RagEngine.corpus_stats_for(config)
