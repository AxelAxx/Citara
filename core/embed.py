"""Embedder: domain port + Ollama adapter + preflight (module 3, FR4 → AC5, AC7).

The ``Embedder`` ABC is the domain boundary: ``retrieve.py`` and ``engine.py``
depend on *this* abstraction, never on Ollama or HTTP (golden rule 1,
dependencies point inward). ``OllamaEmbedder`` is the one concrete adapter; the
``requests`` import lives here and is lazy, so the rest of ``core/`` stays
framework-free and importing this module is cheap.

Why a direct HTTP call instead of an SDK: the ``ollama`` Python SDK (via
``langchain-ollama``) routes embedding through an internal *runner* on an
ephemeral, randomly-chosen port (``http://127.0.0.1:<random>/tokenize``) which
refuses the connection in this environment, so ``embed_documents`` fails. The
public ``POST /api/embed`` endpoint on the stable Ollama server port is
verified-working (curl returns the 1024-dim bge-m3 vector in ~2s), so this
adapter talks to that endpoint directly and depends on nothing but ``requests``.

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

# Embedding a batch is the slow path (CPU embedding of many chunks), so this is
# far longer than the preflight: we want to wait out a real workload, not give up.
_EMBED_TIMEOUT_SECONDS = 120

# Max texts per /api/embed POST. Ollama starts an internal tokenizer runner (on
# an ephemeral /tokenize port) to handle a request, and that runner collapses
# under a single huge batch — sending the whole corpus at once fails, while a
# handful of texts per call is verified-working. So embed_documents chunks the
# input into batches of this size. Conservative on purpose; tune via the
# constructor's batch_size if a host can take more.
_EMBED_BATCH_SIZE = 16


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
    """Embedder backed by Ollama's stable ``POST /api/embed`` HTTP endpoint.

    ``model_name`` and ``ollama_base_url`` come from the ``VerticalConfig`` and
    are the single source of truth for which model/endpoint to use. The adapter
    calls the HTTP endpoint directly with ``requests`` (see the module docstring
    for why the SDK/runner path is unusable here); tests mock ``requests.post``
    so nothing touches the network.
    """

    def __init__(
        self,
        model_name: str,
        ollama_base_url: str,
        *,
        batch_size: int = _EMBED_BATCH_SIZE,
    ) -> None:
        self.model_name = model_name
        # Normalize once so URL joins are unambiguous regardless of config style.
        self.ollama_base_url = ollama_base_url.rstrip("/")
        # Texts per /api/embed POST; small batches keep Ollama's tokenizer runner
        # from overloading (see _EMBED_BATCH_SIZE). Injectable for host tuning.
        self.batch_size = batch_size

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
        # Ollama's /api/embed accepts a list in "input" and returns the
        # embeddings in the same order — but a single huge batch overloads its
        # internal tokenizer runner and the call fails (verified: a few texts per
        # call works, the whole corpus at once does not). So we slice into small
        # batches, POST one per batch, and concatenate; the result is identical
        # to one big call — same length, same global input order.
        result: list[Embedding] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            result.extend(self._embed(batch))
        return result

    def embed_query(self, text: str) -> Embedding:
        # Same endpoint with a single string; Ollama still wraps the result in a
        # list, so we unwrap the one vector here.
        vectors = self._embed(text)
        if not vectors:
            raise RagEngineError(
                f"Ollama /api/embed at '{self.ollama_base_url}' returned no "
                "embedding for the query."
            )
        return vectors[0]

    # --- HTTP call to the stable /api/embed endpoint -------------------------

    def _embed(self, model_input: str | list[str]) -> list[Embedding]:
        """POST to /api/embed and return the ``embeddings`` list (order preserved).

        We hit the server's stable HTTP endpoint directly rather than going
        through the ollama/langchain-ollama SDK: that SDK proxies embedding to an
        internal runner on an ephemeral port that refuses the connection here,
        whereas this endpoint is verified-working. See the module docstring.
        """
        requests = self._http()
        url = f"{self.ollama_base_url}/api/embed"
        body = {"model": self.model_name, "input": model_input}
        try:
            response = requests.post(url, json=body, timeout=_EMBED_TIMEOUT_SECONDS)
        except (requests.exceptions.RequestException, OSError) as exc:
            # Connection refused / DNS / timeout — the server isn't answering.
            raise OllamaUnreachableError(
                f"Cannot reach Ollama at '{self.ollama_base_url}'. "
                "Start it with `ollama serve` and verify the base URL."
            ) from exc

        if response.status_code != 200:
            detail = self._error_detail(response)
            lowered = detail.lower()
            # Ollama answers an unknown model with a "not found, try pulling it"
            # error; surface that as the actionable model error, not a generic one.
            if "not found" in lowered or "pull" in lowered:
                raise ModelNotPulledError(
                    f"Embedding model '{self.model_name}' is not available in "
                    f"Ollama (/api/embed → HTTP {response.status_code}: {detail}). "
                    f"Pull it first: `ollama pull {self.model_name}`."
                )
            raise RagEngineError(
                f"Ollama /api/embed at '{self.ollama_base_url}' returned HTTP "
                f"{response.status_code}: {detail}."
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise RagEngineError(
                f"Ollama /api/embed at '{self.ollama_base_url}' returned a "
                "non-JSON response. Verify it is really Ollama."
            ) from exc

        embeddings = payload.get("embeddings") if isinstance(payload, dict) else None
        if embeddings is None:
            raise RagEngineError(
                f"Ollama /api/embed at '{self.ollama_base_url}' returned no "
                "'embeddings' key. Verify the server version and model."
            )
        return embeddings

    @staticmethod
    def _error_detail(response) -> str:
        """Best-effort human-readable reason from a non-200 /api/embed response."""
        try:
            body = response.json()
        except ValueError:
            return (getattr(response, "text", "") or "").strip() or "<no body>"
        if isinstance(body, dict) and "error" in body:
            return str(body["error"])
        return str(body)

    @staticmethod
    def _http():
        try:
            import requests
        except ImportError as exc:
            raise RagEngineError(
                "requests is required to reach Ollama. "
                "Install it with `pip install -r requirements.txt`."
            ) from exc
        return requests
