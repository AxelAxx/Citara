"""API-only schemas: ONLY what does not already exist in core.models.

``Answer``, ``Citation`` and ``CorpusStats`` are deliberately NOT redefined —
the domain models are frozen Pydantic and serialize natively, so redefining them
here could only drift from the domain (API_CONTRACT.md: "the domain models ARE
the response schemas").
"""

from __future__ import annotations

from pydantic import BaseModel

from core.models import VerticalConfig


class QueryRequest(BaseModel):
    """POST /api/verticals/{id}/query body."""

    query: str


class VerticalView(BaseModel):
    """Presentation-safe projection of VerticalConfig for /api/verticals.

    Deliberately HIDES system_prompt, corpus_path and collection_name: internal
    fields that are not the front's business (API_CONTRACT.md §/api/verticals).
    """

    id: str
    display_name: str
    domain_name: str
    domain_letter: str
    domain_sublabel: str
    domain_tagline: str
    example_questions: list[str]

    @classmethod
    def from_config(cls, config: VerticalConfig) -> "VerticalView":
        """The ONE config→view mapping site, so the hidden-fields rule can't fork."""
        return cls(
            id=config.vertical.value,
            display_name=config.display_name,
            domain_name=config.domain_name,
            domain_letter=config.domain_letter,
            domain_sublabel=config.domain_sublabel,
            domain_tagline=config.domain_tagline,
            example_questions=config.example_questions,
        )


class VerticalsResponse(BaseModel):
    """GET /api/verticals envelope — ``{"verticals": [...]}`` per the contract."""

    verticals: list[VerticalView]
