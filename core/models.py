"""Domain value objects, type aliases, and exceptions for rag-engine.

This is module 1 of the build order: the vocabulary from
``docs/UBIQUITOUS_LANGUAGE.md`` made concrete. There is no behaviour here beyond
the few invariants that are part of the *type itself* (Answer grounding, the
Citation factory). Everything in ``core/`` depends on these models; these depend
on nothing else in the project, and on no UI/IO framework (NFR3).

All value objects are immutable (``frozen=True``) so a Chunk and its provenance,
or an Answer and its Citations, cannot be mutated apart after construction.

Scope boundary — keep these models faithful to the *domain*. The conversion of
rich types (``Path``, ``Vertical``) into the flat primitives ChromaDB requires
for metadata is **not** done here; that lives in the VectorStore adapter
(``core/store.py``, module 4). Do not leak persistence concerns into these types.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# An Embedding is a dense vector. Aliased so domain boundaries read in the
# ubiquitous language instead of a bare ``list[float]``.
Embedding = list[float]


class Vertical(str, Enum):
    """A business domain the Engine is pointed at. Data + config, never code."""

    LEGAL = "legal"
    HEALTH = "health"


class SourceDocument(BaseModel):
    """One original file as downloaded, before any processing.

    Identified by a stable ``document_id`` (the official id where one exists,
    e.g. ``BOE-A-2015-11430``, otherwise the slugified filename).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str
    # Path, not str: the domain holds the rich type; the VectorStore adapter
    # (module 4) flattens it to a primitive for Chroma metadata, not here.
    source_path: Path
    vertical: Vertical


class ChunkMetadata(BaseModel):
    """Provenance attached to every Chunk — what makes Citations possible (FR9).

    ``document_id`` and ``page`` are mandatory: a Chunk whose origin cannot be
    traced cannot be cited, and an uncited Answer is a defect. ``section``,
    ``vertical``, and ``source_path`` are optional enrichments.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str
    page: int
    section: str | None = None
    vertical: Vertical | None = None
    source_path: Path | None = None


class Chunk(BaseModel):
    """Atomic unit of retrieval: a slice of a SourceDocument plus its provenance.

    ``metadata`` is non-optional by design — a Chunk is never stored or moved
    around without its ChunkMetadata, so the link from retrieved text back to a
    Citation can never be broken.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    metadata: ChunkMetadata


class Query(BaseModel):
    """The user's natural-language question (in Spanish)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str


# The ordered Chunks the Retriever returns for a Query — the only material the
# Generator is allowed to use, and nothing else. Aliased to a plain list so the
# domain term reads naturally without wrapping the sequence in a new type.
RetrievedContext = list[Chunk]


class Citation(BaseModel):
    """A reference pointing to the SourceDocument (and page) a claim came from.

    A Citation is *always* derived from the retrieved Chunk, never assembled by
    hand: build it through :meth:`from_chunk` (which composes
    :meth:`from_metadata`, the base provenance mapping). Centralizing
    construction keeps the metadata→citation mapping in one place, so the
    SourcesPanel can never drift from the provenance the Retriever actually
    returned.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str
    page: int
    section: str | None = None
    # Provenance for the source viewer ONLY — never injected into the LLM
    # prompt (grounding is assembled separately in Generator._build_prompt) and
    # never inline in the Answer text. Default "" is the fail-safe for
    # Citations built without a chunk at hand (e.g. an older session history).
    chunk_text: str = ""

    @classmethod
    def from_metadata(cls, metadata: ChunkMetadata) -> Citation:
        """The base provenance mapping: ChunkMetadata → Citation fields."""
        return cls(
            document_id=metadata.document_id,
            page=metadata.page,
            section=metadata.section,
        )

    @classmethod
    def from_chunk(cls, chunk: Chunk) -> Citation:
        """Derive a Citation from a retrieved Chunk: base mapping + its text.

        Composes :meth:`from_metadata` (the field mapping lives in one place)
        and attaches the chunk's text as viewer provenance.
        """
        base = cls.from_metadata(chunk.metadata)
        return base.model_copy(update={"chunk_text": chunk.text})


class TextPart(BaseModel):
    """A run of plain Answer text between inline citation markers.

    One arm of the :data:`AnswerPart` union. Carries no provenance on purpose:
    provenance lives only in :class:`CitePart`, so a renderer can never cite
    from the wrong arm.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["text"] = "text"
    text: str


class CitePart(BaseModel):
    """An inline citation marker resolved to ONLY its 1-based citation index.

    Deliberately decoupled from :class:`Citation`: the part carries just ``n``
    and the renderer resolves ``n → Answer.citations[n - 1]`` positionally, so
    the citation payload is never duplicated inline (one source of truth: the
    ``citations`` list). Built ONLY by the marker parser + remap in
    ``core.generate`` after validating against the real citation list — a
    CitePart indexing an invented source cannot reach an Answer (its validator
    enforces the range again).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["cite"] = "cite"
    n: int


# The typed pieces an Answer's text splits into once its inline [N] markers are
# parsed: plain text runs interleaved with resolved citation markers. A
# discriminated union on ``kind`` so (de)serialization stays unambiguous when
# the API layer ships parts over the wire later.
AnswerPart = Annotated[TextPart | CitePart, Field(discriminator="kind")]


class Answer(BaseModel):
    """Generator output: the response text plus the Citations it is grounded on.

    Golden rule 3 made enforceable at the type level: a non-abstaining Answer
    must carry at least one Citation. ``citations`` may be empty *only* when
    ``is_abstention`` is True — the correct behaviour when RetrievedContext is
    insufficient (Abstention, FR8). Build an abstention through
    :meth:`abstention`; build a grounded Answer with its citations attached.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    citations: list[Citation] = []
    is_abstention: bool = False
    # The parsed view of ``text``: TextPart runs interleaved with CitePart
    # markers. Additive on purpose — ``text`` stays the plain reply so existing
    # consumers keep working; ``parts`` serves renderers that place citation
    # chips inline (FR9 / 3b). Empty ⇒ no parsed view was produced.
    parts: list[AnswerPart] = []

    @model_validator(mode="after")
    def _require_grounding(self) -> Answer:
        # An answered (non-abstaining) response with no citations is ungrounded:
        # the exact failure this architecture exists to prevent.
        if not self.is_abstention and not self.citations:
            raise ValueError(
                "A non-abstaining Answer must carry at least one Citation. "
                "Either attach the Citations it is grounded on, or build an "
                "Answer.abstention(...) when RetrievedContext is insufficient."
            )
        return self

    @model_validator(mode="after")
    def _parts_grounded_in_citations(self) -> Answer:
        # A CitePart whose n falls outside the citations list would render a
        # chip that resolves to nothing (the front looks up citations[n - 1]) —
        # the same "uncited claim" defect rule 3 exists to prevent, typed away.
        # This also keeps abstentions honest: with citations empty, ANY
        # CitePart is out of range, so an abstention can never carry cites.
        for part in self.parts:
            if isinstance(part, CitePart) and not (1 <= part.n <= len(self.citations)):
                raise ValueError(
                    "Answer.parts contains a CitePart whose n does not index "
                    "Answer.citations (1-based). Build parts through "
                    "core.generate (parse_citations + the Generator's fragment "
                    "remap) from the same citation list the Answer carries."
                )
        return self

    @classmethod
    def abstention(cls, text: str) -> Answer:
        """Factory for the Abstention case: no citations, explicitly flagged."""
        return cls(text=text, citations=[], is_abstention=True)


class CorpusStats(BaseModel):
    """Read-only snapshot of one Vertical's ingested Corpus.

    Data only, produced by the VectorStore adapter and exposed through
    ``RagEngine.corpus_stats()``. Deliberately carries NO ingest timestamp
    (ChromaDB stores none reliably — inventing one would be dishonest) and no
    per-document page ranges (v2).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_count: int
    chunk_count: int
    embedding_model: str
    document_ids: list[str]


class VerticalConfig(BaseModel):
    """Declarative description of a Vertical — the only thing that changes between
    legal and health (FR10). Loaded from ``config/<vertical>.yaml``.

    ``embedding_model`` and ``llm_model`` are centralized here on purpose
    (golden rule 4): the same embedding model name flows into both ingestion and
    query from one source, so the two can never silently desynchronize and
    destroy retrieval.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    vertical: Vertical
    display_name: str
    corpus_path: str
    collection_name: str
    system_prompt: str
    embedding_model: str
    llm_model: str
    chunk_size: int = 600
    chunk_overlap: int = 90
    top_k: int = 5
    ollama_base_url: str = "http://localhost:11434"
    # Presentation data consumed by the App's empty chat state (suggested Queries,
    # in Spanish — corpus-facing data, not code). Optional on purpose: a Vertical
    # without them is fully functional and simply shows no suggestions.
    example_questions: list[str] = Field(default_factory=list)
    # Welcome-screen card branding (Spanish UI data, not code). Optional on
    # purpose: an older YAML without them still validates — the App falls back
    # to display_name for the card title and renders no chip/sub-label content.
    # domain_sublabel names the SOURCE (e.g. "BOE"), never a document count:
    # real counts are runtime corpus data, not static config.
    domain_name: str = ""
    domain_letter: str = ""
    domain_sublabel: str = ""
    # Chat-header source line (e.g. "BOE · Legislación laboral"); empty ⇒ the
    # header omits it. Same optional Spanish-UI-data pattern as the trio above.
    domain_tagline: str = ""


# --- Domain exceptions -------------------------------------------------------
# Types only, no logic. Specific over bare Exception so callers can react, and
# with actionable messages so the fix is obvious when one fails fast (NFR6).


class RagEngineError(Exception):
    """Base class for all domain errors raised by the Engine."""


class OllamaUnreachableError(RagEngineError):
    """The Ollama server could not be reached.

    Actionable fix: start it (``ollama serve``) and confirm it is listening at
    the configured ``ollama_base_url`` (default ``http://localhost:11434``).
    """


class ModelNotPulledError(RagEngineError):
    """A required Ollama model is not available locally.

    Actionable fix: pull it first, e.g. ``ollama pull qwen2.5:7b`` or
    ``ollama pull bge-m3``.
    """


class EmptyCorpusError(RagEngineError):
    """A Vertical's Corpus has no ingestible documents.

    Actionable fix: place PDFs under ``data/<vertical>/`` and run
    ``python -m core.ingest --vertical <vertical>`` before querying.
    """


class RetrievalError(RagEngineError):
    """Retrieval against the active Collection failed.

    Actionable fix: confirm the Vertical has been ingested and its Collection
    exists in ``./chroma_db`` before issuing a Query.
    """
