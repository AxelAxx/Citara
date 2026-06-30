"""Unit tests for the Embedder port + Ollama adapter (FR4, AC5, AC7).

No live Ollama: the preflight is mocked at ``requests.get`` (``/api/tags``) and
embedding is mocked at ``requests.post`` (``/api/embed``), so nothing touches
the network. This also guards NFR1/AC5 — the only endpoints the adapter ever
calls are the local ``/api/tags`` and ``/api/embed``, which here are fakes.
"""

from __future__ import annotations

import pytest

from core.embed import Embedder, OllamaEmbedder, _model_is_available
from core.models import ModelNotPulledError, OllamaUnreachableError, RagEngineError


class _FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        payload: dict | None = None,
        *,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> dict:
        # Mirror requests: a body that isn't JSON raises ValueError.
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


def _make_embedder(model: str = "bge-m3", batch_size: int = 16) -> OllamaEmbedder:
    return OllamaEmbedder(
        model_name=model,
        ollama_base_url="http://localhost:11434",
        batch_size=batch_size,
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


# --- embedding (/api/embed mocked at requests.post, no network) --------------


def test_embed_documents_returns_embeddings(monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        # Ollama returns one vector per input string, in order.
        return _FakeResponse(200, {"embeddings": [[0.1, 0.2, 0.3] for _ in json["input"]]})

    monkeypatch.setattr("requests.post", fake_post)

    result = _make_embedder().embed_documents(["uno", "dos"])

    assert len(result) == 2
    assert all(isinstance(vec, list) for vec in result)
    assert all(isinstance(v, float) for v in result[0])
    # Hits the stable /api/embed endpoint with model + the batch as a list.
    assert captured["url"] == "http://localhost:11434/api/embed"
    assert captured["json"] == {"model": "bge-m3", "input": ["uno", "dos"]}


def test_embed_documents_batches_large_input(monkeypatch):
    # More texts than batch_size → one /api/embed POST per batch, concatenated.
    # Each text gets a unique vector keyed by its content so we can assert the
    # concatenated order matches the global input order exactly.
    calls: list[list[str]] = []

    def fake_post(url, json=None, timeout=None):
        batch = json["input"]
        calls.append(batch)
        return _FakeResponse(200, {"embeddings": [[float(int(t))] for t in batch]})

    monkeypatch.setattr("requests.post", fake_post)

    texts = [str(i) for i in range(10)]  # "0".."9"
    result = _make_embedder(batch_size=4).embed_documents(texts)

    # 10 texts, batch_size 4 → batches of 4, 4, 2.
    assert [len(b) for b in calls] == [4, 4, 2]
    assert calls == [["0", "1", "2", "3"], ["4", "5", "6", "7"], ["8", "9"]]
    # Concatenated result: same length and global order as a single big call.
    assert len(result) == 10
    assert result == [[float(i)] for i in range(10)]


def test_embed_query_returns_one_embedding(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        # A single string input still comes back wrapped in a list.
        assert json["input"] == "¿cuál es el plazo?"
        return _FakeResponse(200, {"embeddings": [[0.5, 0.6, 0.7]]})

    monkeypatch.setattr("requests.post", fake_post)

    vector = _make_embedder().embed_query("¿cuál es el plazo?")

    assert vector == [0.5, 0.6, 0.7]
    assert all(isinstance(v, float) for v in vector)


def test_embed_raises_unreachable_when_post_fails(monkeypatch):
    def boom(url, json=None, timeout=None):
        raise ConnectionError("connection refused")

    monkeypatch.setattr("requests.post", boom)

    with pytest.raises(OllamaUnreachableError):
        _make_embedder().embed_documents(["x"])


def test_embed_raises_model_not_pulled_on_model_error(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        return _FakeResponse(404, {"error": "model 'bge-m3' not found, try pulling it first"})

    monkeypatch.setattr("requests.post", fake_post)

    with pytest.raises(ModelNotPulledError) as exc:
        _make_embedder().embed_documents(["x"])
    assert "ollama pull bge-m3" in str(exc.value)


def test_embed_raises_on_missing_embeddings_key(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        return _FakeResponse(200, {"unexpected": True})

    monkeypatch.setattr("requests.post", fake_post)

    with pytest.raises(RagEngineError):
        _make_embedder().embed_documents(["x"])


def test_ollama_embedder_is_an_embedder():
    assert isinstance(_make_embedder(), Embedder)


# --- model-match helper edge cases ------------------------------------------


def test_model_is_available_matching_rules():
    assert _model_is_available("bge-m3", {"bge-m3:latest"})  # untagged ↦ any tag
    assert _model_is_available("qwen2.5:7b", {"qwen2.5:7b"})  # exact tagged match
    assert not _model_is_available("bge-m3", {"qwen2.5:7b"})  # absent
    assert not _model_is_available("bge-m3:custom", {"bge-m3:latest"})  # tag mismatch
