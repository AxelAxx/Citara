"""Actionable error card (NFR6/AC7): domain error -> Spanish fix-it card.

Extracted verbatim from app.py (V2 step 3). ``error_presentation`` is public
API alongside ``render_error_card``: every presentation-layer consumer that
catches a RagEngineError (app.py's boot/preflight, the corpus panel, the query
path) maps it to card fields through this one function, so the Spanish error
copy can never fork.
"""

from __future__ import annotations

import re
from html import escape

import streamlit as st

from core.models import (
    EmptyCorpusError,
    ModelNotPulledError,
    OllamaUnreachableError,
    RagEngineError,
    VerticalConfig,
)

# --- error translation (NFR6/AC7) --------------------------------------------

# All user-visible error copy is born HERE, in Spanish: core/ raises technical
# English messages (those are code, kept as the .err-tech trace), and this layer
# maps the TYPED exception to the mock's actionable card. Commands and model
# names come from the VerticalConfig — never from mock literals (the mock says
# "llama3.1 · 4,7 GB"; the real model is whatever llm_model says, and the weight
# is omitted because there is no reliable source for it).

# core quotes the offending model name single-quoted in its messages.
_QUOTED = re.compile(r"'([^']+)'")


def error_presentation(exc: RagEngineError, config: VerticalConfig) -> dict[str, str | None]:
    """Map a domain error to the card fields (Spanish copy + real command)."""
    host = escape(config.ollama_base_url.removeprefix("http://").removeprefix("https://"))
    if isinstance(exc, OllamaUnreachableError):
        return {
            "kind": "servicio",
            "title": "Ollama no está disponible",
            "body": (
                "No se pudo conectar con el modelo local en "
                f'<span class="mono err-code">{host}</span>. '
                "Arráncalo en una terminal y reintenta."
            ),
            "command": "ollama serve",
            "technical": str(exc),
            "llm_model": config.llm_model,
            "host": config.ollama_base_url,
        }
    if isinstance(exc, ModelNotPulledError):
        # The missing model can be the LLM or the Embedder's (both preflights
        # raise this type); core carries it single-quoted in the message. The
        # llm_model fallback keeps the command real either way.
        match = _QUOTED.search(str(exc))
        model = match.group(1) if match else config.llm_model
        return {
            "kind": "modelo",
            "title": "El modelo no está descargado",
            "body": (
                f'El modelo <span class="mono err-code">{escape(model)}</span> '
                "no está en Ollama. Descárgalo una sola vez para empezar."
            ),
            "command": f"ollama pull {model}",
            "technical": str(exc),
            "llm_model": config.llm_model,
            "host": config.ollama_base_url,
        }
    if isinstance(exc, EmptyCorpusError):
        return {
            "kind": "corpus",
            "title": "El corpus está vacío",
            "body": (
                "No hay documentos ingestados para esta Vertical. Coloca los PDF en "
                f'<span class="mono err-code">{escape(config.corpus_path)}</span> '
                "y lanza la ingesta desde una terminal."
            ),
            "command": f"python -m core.ingest --vertical {config.vertical.value}",
            "technical": str(exc),
        }
    return {
        "kind": "motor",
        "title": "No se pudo completar la operación",
        "body": (
            "La operación falló de forma inesperada. El detalle técnico de "
            "abajo indica la causa."
        ),
        "technical": str(exc),
    }


@st.dialog("Poner Ollama en marcha")
def _show_install_guide(llm_model: str, host: str) -> None:
    """Spanish step-by-step to install/start Ollama and pull the model.

    Real commands only, model/host from VerticalConfig — the same honesty rule
    as the card itself.
    """
    st.markdown(
        "**1 · Instala Ollama** (una sola vez) desde "
        "[ollama.com/download](https://ollama.com/download)."
    )
    st.markdown(f"**2 · Arranca el servidor** en una terminal; debe quedar escuchando en `{host}`:")
    st.code("ollama serve", language="bash")
    st.markdown("**3 · Descarga el modelo** (una sola vez):")
    st.code(f"ollama pull {llm_model}", language="bash")
    st.markdown("**4 · Vuelve aquí** y pulsa «Reintentar conexión».")


def render_error_card(
    kind: str,
    title: str,
    body: str,
    command: str | None = None,
    technical: str | None = None,
    llm_model: str | None = None,
    host: str | None = None,
    key_suffix: str = "live",
) -> None:
    """Render an actionable error as the mock's state-card (05-errors.html).

    HTML paints the static part (``body`` is presentation-crafted HTML; dynamic
    values are escaped in error_presentation). The command is st.code so the
    copy button is REAL (native), and the buttons are real widgets: retry reruns
    the script — the health preflight re-executes on every run — and the guide
    opens a dialog. ``key_suffix`` keeps widget keys unique: the history replay
    plus a live card can put several of these on one page.
    """
    tech_html = f'<div class="err-tech">{escape(technical)}</div>' if technical else ""
    with st.container(key=f"citara-error-{key_suffix}"):
        st.markdown(
            f'<div class="label err-label">Error accionable · {escape(kind)}</div>'
            '<div class="err-row"><div class="err-icon">!</div>'
            f'<div class="err-main"><div class="err-title">{escape(title)}</div>'
            f'<div class="err-body">{body}</div>{tech_html}</div></div>',
            unsafe_allow_html=True,
        )
        if command:
            st.code(command, language="bash")
        # Buttons only where they are functional (the Ollama cards). Download
        # arrives in #05b; "choose another model" is icebox — neither is faked.
        if kind in ("servicio", "modelo") and llm_model and host:
            with st.container(horizontal=True):
                if st.button("Reintentar conexión", key=f"citara-retry-{key_suffix}"):
                    st.rerun()
                if st.button("Ver guía de instalación", key=f"citara-guide-{key_suffix}"):
                    _show_install_guide(llm_model, host)
