"""Unit tests for GET /api/health (API_CONTRACT.md §/api/health).

The route function is called directly with ``get_engine`` monkeypatched — no
TestClient, no network, no live Ollama — because what these tests pin down is
the PAYLOAD contract, not FastAPI's routing.
"""

from __future__ import annotations

import json

from core.generate import ABSTENTION_TEXT
from core.models import OllamaUnreachableError

from api.routes import health as health_route


class _HealthyEngine:
    def check_health(self) -> None:
        pass


def _payload(response) -> dict:
    return json.loads(response.body)


def test_health_ok_payload_includes_abstention_text(monkeypatch):
    monkeypatch.setattr(health_route, "get_engine", lambda vid: _HealthyEngine())

    response = health_route.health()
    payload = _payload(response)

    assert payload["ok"] is True
    # The contract publishes core's literal verbatim — the front's cosmetic
    # streaming cleanup consumes THIS value, so any drift from core's constant
    # would silently break the hide. One source of truth: core.generate.
    assert payload["abstention_text"] == ABSTENTION_TEXT
    # The rest of the ok:true shape, pinned so the payload can't regress.
    assert set(payload) == {
        "ok",
        "llm_model",
        "embedding_model",
        "ollama_base_url",
        "abstention_text",
    }


def test_health_failure_keeps_the_uniform_error_shape(monkeypatch):
    class _DownEngine:
        def check_health(self) -> None:
            raise OllamaUnreachableError("Cannot reach Ollama. Start it with `ollama serve`.")

    monkeypatch.setattr(health_route, "get_engine", lambda vid: _DownEngine())

    response = health_route.health()
    payload = _payload(response)

    assert response.status_code == 503
    assert payload["ok"] is False
    assert payload["error_code"] == "ollama_unreachable"
