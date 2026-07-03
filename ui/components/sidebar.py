"""Sidebar Ollama badge: the three honest connection states (mock 02).

Extracted verbatim from app.py (V2 step 3).
"""

from __future__ import annotations

from html import escape

from streamlit.delta_generator import DeltaGenerator

from core.models import ModelNotPulledError, RagEngineError, VerticalConfig


def render_ollama_badge(
    slot: DeltaGenerator,
    config: VerticalConfig,
    preflight_error: RagEngineError | None,
    connecting: bool = False,
) -> None:
    """Fill the sidebar's .local-badge slot with the REAL Ollama state.

    Three honest states from the preflight that already ran (never a second
    check_health, never a hardcoded green): connected, model-not-pulled (the
    server DID answer — claiming "no connection" would lie the other way), and
    unreachable. ``connecting`` paints the honest interim while the engine
    (re)builds — the slot must never sit empty during a Vertical switch; the
    real state overwrites this same slot once the preflight resolves. Model
    and host come from VerticalConfig, not mock literals.
    """
    if connecting:
        dot, status = "dot-neutral", "Conectando…"
    elif preflight_error is None:
        dot, status = "dot-ok", "Conectado a Ollama"
    elif isinstance(preflight_error, ModelNotPulledError):
        dot, status = "dot-warn", "Modelo no descargado"
    else:
        dot, status = "dot-warn", "Sin conexión con Ollama"
    host = escape(config.ollama_base_url.removeprefix("http://").removeprefix("https://"))
    slot.markdown(
        '<div class="side-badge">'
        f'<div class="side-badge-status"><span class="dot {dot}"></span>'
        f"<span>{status}</span></div>"
        f'<div class="side-badge-model">{escape(config.llm_model)} · {host}</div>'
        '<div class="side-badge-local">Sin conexión a la nube · 100% local</div>'
        "</div>",
        unsafe_allow_html=True,
    )
