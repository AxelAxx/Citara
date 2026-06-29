"""Unit tests for the Embedder port + Ollama adapter (FR4, AC5, AC7).

No live Ollama: the preflight HTTP call is mocked at ``requests.get`` and the
LangChain embeddings client is injected, so nothing touches the network. This
also guards NFR1/AC5 — the only thing the adapter ever calls is the local
``/api/tags`` endpoint, which here is a fake.
"""

from __future__ import annotations

import pytest

from core.embed import Embedder, OllamaEmbedder, _model_is_available
from core.models import ModelNotPulledError, OllamaUnreachableError


class _FakeResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    """Stand-in for LangChain's OllamaEmbeddings."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.5, 0.6, 0.7]


def _make_embedder(client: object | None = None, model: str = "bge-m3") -> OllamaEmbedder:
    return OllamaEmbedder(
        model_name=model,
        ollama_base_url="http://localhost:11434",
        embeddings_client=client,
    )


# --- preflight: model presence ----------------------------------------------


def test_check_health_passes_when_model_pulled(monkeypatch):
    # ":latest" tag must satisfy an untagged "bge-m3" request.
    payload = {"models": [{"name": "bge-m3:latest"}, {"name": "qwen2.5:7b"}]}
    monkeypatch.setattr("requests.get", lambda url, timeout=None: _FakeResponse(200, payload))

    _make_embedder().check_health()  # no exception == pass


def test_check_health_raises_when_model_absent(monkeypatch):
    payload = {"models": [{"name": "qwen2.5:7b"}]}
    monkeypatch.setattr("requests.get", lambda url, timeout=None: _FakeResponse(200, payload))

    with pytest.raises(ModelNotPulledError) as exc:
        _make_embedder().check_health()
    # Actionable: the exact pull command appears in the message.
    assert "ollama pull bge-m3" in str(exc.value)


# --- preflight: reachability (distinct failure) ------------------------------


def test_check_health_raises_when_ollama_unreachable(monkeypatch):
    def boom(url, timeout=None):
        raise ConnectionError("connection refused")  # OSError subclass

    monkeypatch.setattr("requests.get", boom)

    with pytest.raises(OllamaUnreachableError):
        _make_embedder().check_health()


def test_unreachable_and_not_pulled_are_distinct(monkeypatch):
    # Same code path, two different prerequisites → two different exceptions.
    monkeypatch.setattr("requests.get", lambda url, timeout=None: _FakeResponse(200, {"models": []}))
    with pytest.raises(ModelNotPulledError):
        _make_embedder().check_health()

    def boom(url, timeout=None):
        raise ConnectionError("down")

    monkeypatch.setattr("requests.get", boom)
    with pytest.raises(OllamaUnreachableError):
        _make_embedder().check_health()


# --- embedding (client mocked, no preflight, no network) ---------------------


def test_embed_documents_returns_embeddings():
    embedder = _make_embedder(client=_FakeClient())
    result = embedder.embed_documents(["uno", "dos"])

    assert len(result) == 2
    assert all(isinstance(vec, list) for vec in result)
    assert all(isinstance(v, float) for v in result[0])


def test_embed_query_returns_one_embedding():
    embedder = _make_embedder(client=_FakeClient())
    vector = embedder.embed_query("¿cuál es el plazo?")

    assert isinstance(vector, list)
    assert all(isinstance(v, float) for v in vector)


def test_ollama_embedder_is_an_embedder():
    assert isinstance(_make_embedder(client=_FakeClient()), Embedder)


# --- model-match helper edge cases ------------------------------------------


def test_model_is_available_matching_rules():
    assert _model_is_available("bge-m3", {"bge-m3:latest"})  # untagged ↦ any tag
    assert _model_is_available("qwen2.5:7b", {"qwen2.5:7b"})  # exact tagged match
    assert not _model_is_available("bge-m3", {"qwen2.5:7b"})  # absent
    assert not _model_is_available("bge-m3:custom", {"bge-m3:latest"})  # tag mismatch
