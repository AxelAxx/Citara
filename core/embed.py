"""Embedder: domain port + Ollama adapter + preflight (module 3, FR4 → AC5, AC7).

The ``Embedder`` ABC is the domain boundary: ``retrieve.py`` and ``engine.py``
depend on *this* abstraction, never on LangChain or Ollama (golden rule 1,
dependencies point inward). ``OllamaEmbedder`` is the one concrete adapter; the
heavy ``langchain``/``requests`` imports live here and are lazy, so the rest of
``core/`` stays framework-free and importing this module is cheap.

Two design points worth stating:
  * The embedding model name is taken **only** from the constructor (fed from
    ``VerticalConfig.embedding_model``). It is never read from a second place —
    ingestion and query must embed with the *same* model or retrieval silently
    breaks (golden rule 4).
  * The preflight (`check_health`) fails fast and loud (AC7/NFR6) and keeps the
    two failure modes distinct: Ollama unreachable vs. model not pulled get
    different exceptions and different actionable messages — collapsing them
    would hide which fix the user actually needs.

NFR1/AC5: the only endpoint ever contacted is the local Ollama server at the
configured base URL. There is no third-party inference path in this module.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.models import (
    Embedding,
    ModelNotPulledError,
    OllamaUnreachableError,
    RagEngineError,
)

# Generous enough for a cold local server, short enough to fail fast if nothing
# is listening on the port at all.
_TAGS_TIMEOUT_SECONDS = 5


class Embedder(ABC):
    """Port: turns text into Embeddings. The domain depends on this, not on Ollama.

    Two methods on purpose: query and document embeddings can diverge (some
    models prefix or normalize them differently), so the boundary keeps them
    separate even when an adapter happens to treat them the same.
    """

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[Embedding]:
        """Embed a batch of Chunk texts for ingestion."""

    @abstractmethod
    def embed_query(self, text: str) -> Embedding:
        """Embed a single Query for retrieval."""


def _model_is_available(requested: str, available: set[str]) -> bool:
    """Is ``requested`` among the pulled models?

    Ollama reports models tagged (e.g. ``bge-m3:latest``); config usually names
    them untagged (``bge-m3``). Treat an untagged request as satisfied by any
    tag of the same base name, so a normal ``ollama pull bge-m3`` counts.
    """
    if requested in available:
        return True
    if ":" in requested:
        return False
    return any(name.split(":", 1)[0] == requested for name in available)


class OllamaEmbedder(Embedder):
    """Embedder backed by LangChain's ``OllamaEmbeddings`` over local Ollama.

    ``model_name`` and ``ollama_base_url`` come from the ``VerticalConfig`` and
    are the single source of truth for which model/endpoint to use. The
    underlying LangChain client is injectable so tests never need a live server.
    """

    def __init__(
        self,
        model_name: str,
        ollama_base_url: str,
        *,
        embeddings_client: object | None = None,
    ) -> None:
        self.model_name = model_name
        # Normalize once so URL joins are unambiguous regardless of config style.
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self._client = embeddings_client  # lazily built on first use if None

    # --- preflight (AC7) -----------------------------------------------------

    def check_health(self) -> None:
        """Verify Ollama is reachable and the embedding model is pulled.

        Call this once at engine startup (before ingest or query). Raises a
        specific, actionable error so a missing prerequisite surfaces loudly
        instead of as a cryptic failure deep in the embedding call.
        """
        pulled = self._list_pulled_models()  # raises OllamaUnreachableError if down
        if not _model_is_available(self.model_name, pulled):
            raise ModelNotPulledError(
                f"Embedding model '{self.model_name}' is not available in Ollama. "
                f"Pull it first: `ollama pull {self.model_name}`."
            )

    def _list_pulled_models(self) -> set[str]:
        requests = self._http()
        url = f"{self.ollama_base_url}/api/tags"
        try:
            response = requests.get(url, timeout=_TAGS_TIMEOUT_SECONDS)
        except (requests.exceptions.RequestException, OSError) as exc:
            # Connection refused / DNS / timeout — the server isn't answering.
            raise OllamaUnreachableError(
                f"Cannot reach Ollama at '{self.ollama_base_url}'. "
                "Start it with `ollama serve` and verify the base URL."
            ) from exc

        if response.status_code != 200:
            raise OllamaUnreachableError(
                f"Ollama at '{self.ollama_base_url}' returned HTTP "
                f"{response.status_code} for /api/tags. Verify the server and URL."
            )

        try:
            models = response.json().get("models", [])
            return {entry["name"] for entry in models}
        except (ValueError, KeyError, TypeError) as exc:
            raise OllamaUnreachableError(
                f"Unexpected /api/tags response from Ollama at "
                f"'{self.ollama_base_url}'. Verify it is really Ollama."
            ) from exc

    # --- embedding -----------------------------------------------------------

    def embed_documents(self, texts: list[str]) -> list[Embedding]:
        return self._embeddings().embed_documents(texts)

    def embed_query(self, text: str) -> Embedding:
        return self._embeddings().embed_query(text)

    # --- lazy adapter wiring -------------------------------------------------

    def _embeddings(self):
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def _build_client(self):
        # Prefer the dedicated langchain-ollama package; fall back to the
        # (deprecated) community location so either install works.
        try:
            from langchain_ollama import OllamaEmbeddings
        except ImportError:
            try:
                from langchain_community.embeddings import OllamaEmbeddings
            except ImportError as exc:
                raise RagEngineError(
                    "langchain-ollama (or langchain-community) is required to "
                    "embed. Install it with `pip install -r requirements.txt`."
                ) from exc
        return OllamaEmbeddings(model=self.model_name, base_url=self.ollama_base_url)

    @staticmethod
    def _http():
        try:
            import requests
        except ImportError as exc:
            raise RagEngineError(
                "requests is required for the Ollama preflight. "
                "Install it with `pip install -r requirements.txt`."
            ) from exc
        return requests
